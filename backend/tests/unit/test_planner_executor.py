"""Unit tests for ``backend.planner.executor`` (M8.2).

We avoid spinning up the full app state. The :class:`DAGExecutor` is
designed around protocols (``memory``, ``tools``, ``llm``,
``skill_host``) so we use lightweight stubs and a minimal
:class:`WorkflowContext`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from backend.core.events import Event
from backend.core.llm.mock import MockLLMProvider
from backend.planner.executor import (
    DAGExecutor,
    _resolve_args,
    topo_layers,
)
from backend.planner.models import NodeOutcome, PlanDAG, PlanNode
from backend.workflows.base import WorkflowContext


def _ctx() -> WorkflowContext:
    return WorkflowContext(task_id="t1", query="demo")


@dataclass
class _ToolResult:
    ok: bool = True
    output: dict[str, Any] = field(default_factory=dict)
    error: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


class _StubTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail_for: set[str] = set()

    async def call(self, name: str, args: dict[str, Any]) -> _ToolResult:
        self.calls.append((name, dict(args)))
        if name in self.fail_for:
            raise RuntimeError(f"deliberate failure in {name}")
        return _ToolResult(ok=True, output={"echo": args})


@dataclass
class _Snap:
    vector_summary: str
    related_papers: list[Any] = field(default_factory=list)
    doc_chunks: list[Any] = field(default_factory=list)
    heuristics: list[Any] = field(default_factory=list)


class _StubMemory:
    async def snapshot(self, query: str, *, domain: str = "", k: int = 5) -> _Snap:
        return _Snap(vector_summary=f"summary({query})")


# ---------------------------------------------------------------------------
# Topological layers
# ---------------------------------------------------------------------------


def test_topo_layers_handles_diamond() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(id="a", kind="memory.read"),
            PlanNode(id="b", kind="llm", depends_on=["a"]),
            PlanNode(id="c", kind="llm", depends_on=["a"]),
            PlanNode(id="d", kind="llm", depends_on=["b", "c"]),
        ],
    )
    layers = topo_layers(plan.nodes)
    assert layers is not None
    assert [sorted(n.id for n in layer) for layer in layers] == [
        ["a"],
        ["b", "c"],
        ["d"],
    ]


def test_topo_layers_returns_none_on_cycle() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(id="a", kind="llm", depends_on=["b"]),
            PlanNode(id="b", kind="llm", depends_on=["a"]),
        ],
    )
    assert topo_layers(plan.nodes) is None


# ---------------------------------------------------------------------------
# $ref resolution
# ---------------------------------------------------------------------------


def test_resolve_args_replaces_ref() -> None:
    outcomes = {
        "a": NodeOutcome(node_id="a", kind="llm", status="succeeded", output={"text": "hello"}),
    }
    args = {"prompt": {"$ref": "a.text"}, "literal": 42}
    resolved = _resolve_args(args, outcomes)
    assert resolved == {"prompt": "hello", "literal": 42}


def test_resolve_args_missing_ref_yields_none() -> None:
    outcomes: dict[str, NodeOutcome] = {}
    assert _resolve_args({"x": {"$ref": "ghost"}}, outcomes) == {"x": None}


# ---------------------------------------------------------------------------
# Execution: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_runs_nodes_in_order() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(id="a", kind="memory.read", args={"query": "x"}),
            PlanNode(id="b", kind="tool", name="arxiv__search", args={"q": "x"}, depends_on=["a"]),
            PlanNode(
                id="c",
                kind="llm",
                depends_on=["b"],
                args={"prompt": "summarise"},
                description="summarise",
            ),
        ],
    )
    tools = _StubTools()
    llm = MockLLMProvider().queue_text("final answer")
    memory = _StubMemory()
    executor = DAGExecutor(memory=memory, tools=tools, llm=llm, skill_host=None)
    verdict, outcomes = await executor.run(plan, ctx=_ctx())
    assert verdict == "ok"
    assert outcomes["a"].status == "succeeded"
    assert outcomes["b"].status == "succeeded"
    assert outcomes["c"].status == "succeeded"
    assert outcomes["c"].output.get("text") == "final answer"
    assert tools.calls == [("arxiv__search", {"q": "x"})]


# ---------------------------------------------------------------------------
# Execution: failure modes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_abort_on_failure_skips_descendants() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(
                id="a",
                kind="tool",
                name="arxiv__search",
                args={"q": "x"},
                on_failure="abort",
            ),
            PlanNode(id="b", kind="llm", depends_on=["a"], description="x"),
        ],
    )
    tools = _StubTools()
    tools.fail_for.add("arxiv__search")
    llm = MockLLMProvider().queue_text("never reached")
    executor = DAGExecutor(tools=tools, llm=llm, memory=_StubMemory(), skill_host=None)
    verdict, outcomes = await executor.run(plan, ctx=_ctx())
    assert verdict == "error"
    assert outcomes["a"].status == "failed"
    assert outcomes["b"].status == "skipped"


@pytest.mark.asyncio
async def test_skip_keeps_unrelated_nodes_running() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(id="root", kind="memory.read", args={"query": "x"}),
            PlanNode(
                id="bad",
                kind="tool",
                name="arxiv__search",
                args={"q": "x"},
                depends_on=["root"],
                on_failure="skip",
            ),
            PlanNode(id="downstream_of_bad", kind="llm", depends_on=["bad"], description="x"),
            PlanNode(id="independent", kind="llm", depends_on=["root"], description="x"),
        ],
    )
    tools = _StubTools()
    tools.fail_for.add("arxiv__search")
    llm = MockLLMProvider().queue_text("ok").queue_text("ok2")
    executor = DAGExecutor(tools=tools, llm=llm, memory=_StubMemory(), skill_host=None)
    verdict, outcomes = await executor.run(plan, ctx=_ctx())
    assert verdict == "ok"  # skip mode does not abort the whole DAG
    assert outcomes["bad"].status == "failed"
    assert outcomes["downstream_of_bad"].status == "skipped"
    assert outcomes["independent"].status == "succeeded"


@pytest.mark.asyncio
async def test_node_retries_until_success() -> None:
    """Tool fails twice, then succeeds — node configured for retries=2."""

    class _FlakyTools:
        def __init__(self) -> None:
            self.attempts = 0

        async def call(self, name: str, args: dict[str, Any]) -> _ToolResult:
            self.attempts += 1
            if self.attempts < 3:
                raise RuntimeError("transient failure")
            return _ToolResult(ok=True, output={"attempt": self.attempts})

    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(
                id="a",
                kind="tool",
                name="arxiv__search",
                args={"q": "x"},
                retries=2,
            ),
        ],
    )
    tools = _FlakyTools()
    executor = DAGExecutor(tools=tools, llm=None, memory=None, skill_host=None)
    verdict, outcomes = await executor.run(plan, ctx=_ctx())
    assert verdict == "ok"
    assert outcomes["a"].status == "succeeded"
    assert outcomes["a"].attempts == 3


@pytest.mark.asyncio
async def test_continue_on_failure_lets_downstream_run() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(
                id="a",
                kind="tool",
                name="arxiv__search",
                args={"q": "x"},
                on_failure="continue",
            ),
            PlanNode(id="b", kind="llm", depends_on=["a"], description="x"),
        ],
    )
    tools = _StubTools()
    tools.fail_for.add("arxiv__search")
    llm = MockLLMProvider().queue_text("post-failure summary")
    executor = DAGExecutor(tools=tools, llm=llm, memory=_StubMemory(), skill_host=None)
    verdict, outcomes = await executor.run(plan, ctx=_ctx())
    assert verdict == "ok"
    assert outcomes["a"].status == "failed"
    assert outcomes["b"].status == "succeeded"


@pytest.mark.asyncio
async def test_emits_stage_start_and_end_events() -> None:
    plan = PlanDAG(
        query="x",
        nodes=[
            PlanNode(id="a", kind="memory.read", args={"query": "x"}),
        ],
    )
    captured: list[Event] = []

    async def sink(ev: Event) -> None:
        captured.append(ev)

    ctx = _ctx().with_sink(sink)
    executor = DAGExecutor(memory=_StubMemory(), llm=None, tools=None, skill_host=None)
    verdict, _ = await executor.run(plan, ctx=ctx)
    assert verdict == "ok"
    types = [e.type for e in captured]
    assert "task.stage_start" in types
    assert "task.stage_end" in types
