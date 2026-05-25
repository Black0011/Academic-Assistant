"""Unit tests for `WriteWorkflow`."""

from __future__ import annotations

import pytest

from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.memory.models import PaperCard
from backend.workflows.base import WorkflowContext
from backend.workflows.write import (
    WriteWorkflow,
    _extract_citations,
    _parse_outline,
    _template_outline,
    _word_count,
)


def _cards() -> list[PaperCard]:
    return [
        PaperCard(
            paper_id="aaa111",
            title="Retrieval Augmented Generation",
            authors=["Alice"],
            year=2023,
            abstract="RAG overview",
            summary="RAG combines retrieval with generation.",
            tags=["rag", "nlp"],
            url="https://arxiv.org/abs/2301.00001",
            citation_url="https://scholar.googleusercontent.com/scholar.bib?q=info:aaa111",
            citation_bibtex="@article{rag2023, title={RAG}, author={Alice}, year={2023}}",
        ),
        PaperCard(
            paper_id="bbb222",
            title="Memory Networks",
            authors=["Bob"],
            year=2015,
            abstract="Memory-augmented NNs",
            summary="Introduces external memory.",
            tags=["memory"],
            url="https://arxiv.org/abs/1501.00002",
            citation_url="https://scholar.googleusercontent.com/scholar.bib?q=info:bbb222",
            citation_bibtex="@article{mem2015, title={Memory Networks}, author={Bob}, year={2015}}",
        ),
    ]


async def _seed(memory: MemoryBundle) -> None:
    for c in _cards():
        await memory.knowledge.write_card(c)
        await memory.vector.add(c.paper_id, c.search_text(), metadata={"title": c.title})


async def test_write_workflow_with_llm_full_path():
    memory = MemoryBundle.in_memory()
    await _seed(memory)
    llm = MockLLMProvider()
    # 1 outline + 3 draft calls + 1 reflection
    llm.queue_text("1. Motivation\n2. Prior work\n3. Our contribution")
    llm.queue_text("## Motivation\n\nRAG is important [aaa111].")
    llm.queue_text("## Prior work\n\nMemory networks [bbb222] preceded RAG.")
    llm.queue_text("## Our contribution\n\nWe combine [aaa111] and [bbb222].")
    llm.queue_text("Reflection: wrote intro.")

    ctx = WorkflowContext(
        task_id="t-1",
        query="retrieval augmented generation",
        input={"section": "introduction", "length": 400},
        memory=memory,
        llm=llm,
    )
    out = await WriteWorkflow().run(ctx)

    assert out.verdict == "ok", out.error
    results = out.results
    assert results["section"] == "introduction"
    assert len(results["outline"]) == 3
    assert results["outline"][0].startswith("Motivation")
    assert "RAG is important" in results["markdown"]
    assert "[aaa111]" in results["markdown"]
    assert results["citations"] == ["aaa111", "bbb222"]
    assert results["word_count"] > 0

    # Reflection stored
    recent = await memory.episodic.recent(n=3)
    assert recent and recent[0].source_run_id == "t-1"


async def test_write_workflow_falls_back_when_llm_missing():
    memory = MemoryBundle.in_memory()
    await _seed(memory)
    ctx = WorkflowContext(
        task_id="t-2",
        query="memory networks",
        input={"section": "related work"},
        memory=memory,
        llm=None,
    )
    out = await WriteWorkflow().run(ctx)
    assert out.verdict == "ok", out.error
    assert out.results["outline"], "template outline expected"
    assert out.results["markdown"].startswith("# Related Work:")


async def test_write_workflow_survives_llm_error_on_outline():
    memory = MemoryBundle.in_memory()
    await _seed(memory)
    llm = MockLLMProvider()
    llm.queue_error("boom")
    # drafts use fallback; queue nothing for drafts so LLM stream stays empty
    ctx = WorkflowContext(
        task_id="t-3",
        query="topic",
        input={"section": "method"},
        memory=memory,
        llm=llm,
    )
    out = await WriteWorkflow().run(ctx)
    assert out.verdict == "ok", out.error
    # Template outline kicks in for method-like sections
    assert any("Overview" == h or h.startswith("Overview") for h in out.results["outline"])


# ---------------------------------------------------------------------------
# Recall soft-fail (P12.1) — write must keep going with empty recall.
# ---------------------------------------------------------------------------


class _ExplodingMemory:
    async def snapshot(self, *_args, **_kwargs):
        raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.asyncio
async def test_write_recall_failure_does_not_abort_task():
    from backend.core.events import EventType

    llm = MockLLMProvider()
    llm.queue_text("1. Motivation")
    llm.queue_text("## Motivation\n\nA draft without recalled context.")
    llm.queue_text("Reflection: wrote without recall.")

    ctx = WorkflowContext(
        task_id="write-recall-fail",
        query="anything",
        input={"section": "introduction"},
        memory=_ExplodingMemory(),
        llm=llm,
    )
    out = await WriteWorkflow().run(ctx)

    assert out.verdict == "ok", out.error
    assert out.results["citations"] == []

    warnings = [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    assert warnings
    assert warnings[0].data["stage"] == "recall"
    assert warnings[0].data["source_type"] == "BrokenPipeError"


def test_parse_outline_supports_various_bullets():
    raw = "1. Alpha\n- Beta\n* Gamma\n   2) Delta\nnot an item"
    assert _parse_outline(raw) == ["Alpha", "Beta", "Gamma", "Delta"]


def test_template_outline_switches_by_section():
    assert _template_outline("introduction", [])[0].startswith("Motivation")
    assert _template_outline("method", [])[0] == "Overview"
    assert _template_outline("experiments", [])[0] == "Setup"


def test_extract_citations_filters_to_known_papers():
    papers = _cards()
    md = "See [aaa111] and [zzzzz9] and [bbb222]."
    assert _extract_citations(md, papers) == {"aaa111", "bbb222"}


def test_word_count():
    assert _word_count("hello world  foo-bar, it's great!") == 5
    assert _word_count("") == 0
