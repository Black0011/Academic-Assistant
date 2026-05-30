"""End-to-end unit test for `ResearchWorkflow`.

Uses an in-memory `MemoryBundle`, a `MockLLMProvider`, and a bespoke
`ToolRegistry` with canned arxiv/pdf results so the test hits every
stage (recall → search → parse → ingest → evolve → reflect) without
going to the network.
"""

from __future__ import annotations

from typing import Any

from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.tools.base import BaseTool, ToolResult
from backend.tools.registry import ToolRegistry
from backend.workflows.base import WorkflowContext
from backend.workflows.research import ResearchWorkflow


class _FakeArxiv(BaseTool):
    name = "arxiv__search"
    description = "fake arxiv"
    parameters = {"type": "object", "properties": {}}  # noqa: RUF012
    requires_network = False

    def __init__(self, hits: list[dict[str, Any]]) -> None:
        self._hits = hits

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={
                "query": arguments.get("query", ""),
                "count": len(self._hits),
                "results": self._hits,
            },
        )


class _FakePdf(BaseTool):
    name = "pdf__parse"
    description = "fake pdf"
    parameters = {"type": "object", "properties": {}}  # noqa: RUF012
    requires_network = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        url = arguments.get("url", "")
        return ToolResult(
            ok=True,
            data={
                "source": {"mode": "url", "url": url},
                "num_pages": 2,
                "pages_extracted": 2,
                "pages": [f"intro about {url}", "findings: cool stuff"],
                "text": f"intro about {url}\n\nfindings: cool stuff",
            },
        )


class _FakePdfFailing(BaseTool):
    name = "pdf__parse"
    description = "fake pdf that fails"
    parameters = {"type": "object", "properties": {}}  # noqa: RUF012
    requires_network = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=False, error="parse failed")


def _hits() -> list[dict[str, Any]]:
    return [
        {
            "paper_id": "aaa111",
            "arxiv_id": "2401.00001",
            "entry_id": "http://arxiv.org/abs/2401.00001",
            "title": "Retrieval Augmented Generation",
            "authors": ["Alice"],
            "year": 2024,
            "summary": "Abstract about RAG.",
            "pdf_url": "https://example.test/1.pdf",
            "categories": ["cs.CL"],
        },
        {
            "paper_id": "bbb222",
            "arxiv_id": "2402.00002",
            "entry_id": "http://arxiv.org/abs/2402.00002",
            "title": "Memory Networks",
            "authors": ["Bob"],
            "year": 2024,
            "summary": "About memory networks.",
            "pdf_url": "https://example.test/2.pdf",
            "categories": ["cs.AI"],
        },
    ]


def _registry(pdf_tool: BaseTool | None = None) -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_FakeArxiv(_hits()))
    reg.register(pdf_tool or _FakePdf())
    return reg


async def test_research_full_path_writes_memory():
    memory = MemoryBundle.in_memory()
    llm = MockLLMProvider()
    # Evolver will make one LLM call per paper (2) and one for session
    # reflection; queue permissive responses so the heuristic path isn't
    # taken. `{}` JSON keeps evolver in the "llm" mode with zero links.
    for _ in range(4):
        llm.queue_text("{}")

    ctx = WorkflowContext(
        task_id="t-123",
        query="retrieval augmented generation",
        tools=_registry(),
        memory=memory,
        llm=llm,
    )

    out = await ResearchWorkflow().run(ctx)

    assert out.verdict == "ok", out.error
    assert out.results["count"] == 2
    paper_ids = {p["paper_id"] for p in out.results["papers"]}
    assert paper_ids == {"aaa111", "bbb222"}

    # Knowledge store got two cards
    cards = await memory.knowledge.list_all()
    assert {c.paper_id for c in cards} == {"aaa111", "bbb222"}
    first = await memory.knowledge.get("aaa111")
    assert first is not None
    assert first.venue == "arXiv"
    assert first.source_run_id == "t-123"

    # Vector store indexed both
    assert await memory.vector.count() == 2

    # Episodic store has the session reflection
    recent = await memory.episodic.recent(n=5)
    assert recent, "expected a session reflection"
    assert recent[0].source_run_id == "t-123"

    # Trace includes the key stages
    stage_names = {e.data.get("stage") for e in out.trace if e.type == "task.stage_end"}
    assert {"recall", "search", "parse", "ingest", "evolve", "reflect"}.issubset(stage_names)

    # Tool events made it into the trace
    tool_events = [e for e in out.trace if e.type in ("skill.call", "skill.result")]
    assert any(e.data.get("tool") == "arxiv__search" for e in tool_events)
    assert any(e.data.get("tool") == "pdf__parse" for e in tool_events)


async def test_research_requires_tool_registry():
    memory = MemoryBundle.in_memory()
    ctx = WorkflowContext(
        task_id="t-1",
        query="x",
        memory=memory,
        tools=None,
    )
    out = await ResearchWorkflow().run(ctx)
    assert out.verdict == "error"
    assert "ToolRegistry" in (out.error or "")


async def test_research_handles_pdf_parse_failure_gracefully():
    memory = MemoryBundle.in_memory()
    llm = MockLLMProvider()
    for _ in range(4):
        llm.queue_text("{}")
    ctx = WorkflowContext(
        task_id="t-2",
        query="q",
        tools=_registry(_FakePdfFailing()),
        memory=memory,
        llm=llm,
    )
    out = await ResearchWorkflow().run(ctx)
    # Ingest still runs; cards are created from metadata even when PDF fails.
    assert out.verdict == "ok", out.error
    assert out.results["count"] == 2


class _ExplodingMemory:
    """Stand-in MemoryBundle whose ``snapshot`` raises BrokenPipeError.

    Forces the recall stage to exercise the P12.1 ``stage_soft`` path so
    research keeps running with no prior memory context."""

    async def snapshot(self, *_args, **_kwargs):
        raise BrokenPipeError(32, "Broken pipe")


async def test_research_recall_failure_does_not_abort_task():
    """P12.1 — broken vector store / embedder must degrade recall to a
    warning, not crash the whole discovery task."""

    from backend.core.events import EventType

    reg = ToolRegistry()
    reg.register(_FakeArxiv([]))  # empty arxiv result is fine for this test
    reg.register(_FakePdf())

    ctx = WorkflowContext(
        task_id="research-recall-fail",
        query="any topic",
        tools=reg,
        memory=_ExplodingMemory(),
        llm=MockLLMProvider(),
    )
    out = await ResearchWorkflow().run(ctx)

    # The task succeeds (verdict "empty" because arxiv returned nothing,
    # but crucially NOT "error"). Recall warning is in the trace.
    assert out.verdict != "error", out.error

    warnings = [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    assert warnings
    assert warnings[0].data["stage"] == "recall"
    assert warnings[0].data["source_type"] == "BrokenPipeError"


async def test_research_empty_search_returns_empty_verdict():
    memory = MemoryBundle.in_memory()

    class _Empty(BaseTool):
        name = "arxiv__search"
        description = "empty"
        requires_network = False

        async def call(self, arguments: dict[str, Any]) -> ToolResult:
            return ToolResult(ok=True, data={"count": 0, "results": []})

    reg = ToolRegistry()
    reg.register(_Empty())
    reg.register(_FakePdf())

    ctx = WorkflowContext(
        task_id="t-3", query="nothing", tools=reg, memory=memory, llm=MockLLMProvider()
    )
    out = await ResearchWorkflow().run(ctx)
    assert out.verdict == "empty"
    assert out.results["count"] == 0





class _MixedPdf(BaseTool):
    """PDF parser that fails on every other URL (simulating partial network issues)."""
    
    name = "pdf__parse"
    description = "mixed success/failure pdf parser"
    requires_network = False
    
    def __init__(self):
        self.call_count = 0

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        self.call_count += 1
        url = arguments.get("url", "")
        
        # Fail on even-numbered calls (2nd, 4th, etc.)
        if self.call_count % 2 == 0:
            return ToolResult(ok=False, error=f"Simulated network failure for {url}")
        
        return ToolResult(
            ok=True,
            data={
                "source": {"mode": "url", "url": url},
                "num_pages": 2,
                "pages_extracted": 2,
                "pages": [f"intro about {url}", "findings: cool stuff"],
                "text": f"intro about {url}\n\nfindings: cool stuff",
            },
        )


async def test_research_handles_mixed_pdf_parse_success_and_failure():
    """When some PDF parses fail (return ok=False) and others succeed, the workflow
    should ingest all papers with available content. Papers with successful parses
    have enriched content from the PDF; those with failed parses have metadata only."""

    memory = MemoryBundle.in_memory()
    llm = MockLLMProvider()
    # Evolver needs canned responses for papers that make it through
    for _ in range(10):  # Extra buffer for possible partial success
        llm.queue_text("{}")
    
    # Create 4 papers to parse; mixed tool will fail on 2nd and 4th
    hits = [
        {
            "paper_id": "paper1",
            "arxiv_id": "2401.00001",
            "title": "Paper 1",
            "authors": ["Author 1"],
            "year": 2024,
            "summary": "First paper abstract.",
            "pdf_url": "https://example.test/1.pdf",
            "categories": ["cs.AI"],
        },
        {
            "paper_id": "paper2",
            "arxiv_id": "2401.00002",
            "title": "Paper 2",
            "authors": ["Author 2"],
            "year": 2024,
            "summary": "Second paper abstract.",
            "pdf_url": "https://example.test/2.pdf",
            "categories": ["cs.ML"],
        },
        {
            "paper_id": "paper3",
            "arxiv_id": "2401.00003",
            "title": "Paper 3",
            "authors": ["Author 3"],
            "year": 2024,
            "summary": "Third paper abstract.",
            "pdf_url": "https://example.test/3.pdf",
            "categories": ["cs.NLP"],
        },
        {
            "paper_id": "paper4",
            "arxiv_id": "2401.00004",
            "title": "Paper 4",
            "authors": ["Author 4"],
            "year": 2024,
            "summary": "Fourth paper abstract.",
            "pdf_url": "https://example.test/4.pdf",
            "categories": ["cs.CV"],
        },
    ]

    class _FakeArxivMulti(BaseTool):
        name = "arxiv__search"
        description = "fake arxiv with multiple results"
        parameters = {"type": "object", "properties": {}}  # noqa: RUF012
        requires_network = False

        async def call(self, arguments: dict[str, Any]) -> ToolResult:
            return ToolResult(ok=True, data={"count": len(hits), "results": hits})

    reg = ToolRegistry()
    reg.register(_FakeArxivMulti())
    mixed_pdf = _MixedPdf()
    reg.register(mixed_pdf)

    ctx = WorkflowContext(
        task_id="t-mixed",
        query="test",
        tools=reg,
        memory=memory,
        llm=llm,
        input={"max_parse": 4},  # Try to parse all 4
    )

    out = await ResearchWorkflow().run(ctx)

    # The workflow should succeed (not error) because failed parses are
    # handled gracefully by the tool registry (returns ok=False not an exception)
    assert out.verdict == "ok", f"Expected ok, got {out.verdict}: {out.error}"
    
    # Should have ingested all 4 papers
    assert out.results["count"] == 4, f"Expected 4 papers, got {out.results['count']}"
    
    # All 4 papers should be in memory
    cards = await memory.knowledge.list_all()
    paper_ids = {c.paper_id for c in cards}
    assert paper_ids == {"paper1", "paper2", "paper3", "paper4"}
    
    # Papers with successful parses should have enriched content from PDF
    paper1 = await memory.knowledge.get("paper1")
    assert paper1 is not None
    assert "cool stuff" in paper1.summary  # From successful PDF parse
    
    # Papers with failed parses should have metadata-only content
    paper2 = await memory.knowledge.get("paper2")
    assert paper2 is not None
    assert paper2.summary == "Second paper abstract."  # Only the abstract, no PDF content
    
    # Third paper should have PDF content (odd-numbered)
    paper3 = await memory.knowledge.get("paper3")
    assert paper3 is not None
    assert "cool stuff" in paper3.summary
    
    # Fourth paper should have metadata-only (even-numbered, failed)
    paper4 = await memory.knowledge.get("paper4")
    assert paper4 is not None
    assert paper4.summary == "Fourth paper abstract."
