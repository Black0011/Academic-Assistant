# ruff: noqa: RUF001
# (test fixtures contain Chinese full-width punctuation — that is the
# whole point of these strings; we *want* to verify the prompt builder
# handles them as-is.)
"""Unit tests for ``ConsultWorkflow`` (P11).

The contract under test is the *read-only* shape: consult must never
mutate the bundle, must answer with analytical prose, and must keep
working in template-fallback mode (no LLM wired).
"""

from __future__ import annotations

import pytest

from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.memory.models import PaperCard
from backend.workflows.base import WorkflowContext
from backend.workflows.consult import (
    ConsultWorkflow,
    _normalise_history,
    _parse_suggestions,
)

ORIGINAL = (
    "Current evaluation of Data Agents relies on single-score metrics that "
    "conflate distinct failure modes. We propose OmniEval, a hierarchical "
    "fuzzy evaluation framework."
)


async def _seed(memory: MemoryBundle) -> PaperCard:
    card = PaperCard(
        paper_id="aaa111",
        title="Reward Model Scaling",
        abstract="Studies of reward model scaling for RLHF alignment.",
        summary="Discusses reward model scaling.",
        tags=["rlhf"],
        url="https://arxiv.org/abs/2201.00003",
        citation_url="https://scholar.googleusercontent.com/scholar.bib?q=info:aaa111",
        citation_bibtex="@article{rm2022, title={Reward Model Scaling}, author={Alice}, year={2022}}",
    )
    await memory.knowledge.write_card(card)
    await memory.vector.add(card.paper_id, card.search_text())
    return card


# ---------------------------------------------------------------------------
# Happy path with a real (mock) LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_with_llm_returns_prose_and_does_not_rewrite():
    """Core contract: ``analysis`` carries the LLM's prose answer and
    the result must NOT have a ``revised`` field. Suggestions parsed
    out of the bullet lines flow into ``suggestions``."""

    memory = MemoryBundle.in_memory()
    await _seed(memory)
    llm = MockLLMProvider()
    analysis_md = (
        "## 观察\n"
        "- 第一句话节奏机械，重复 'Current evaluation' 略生硬。\n"
        "- 缺少与 [aaa111] 的对比说明，建议补一句桥接。\n\n"
        "## 建议\n"
        "- 把 single-score 改写成具体的 metric 名（Execution Accuracy 等）。\n"
        '- 在 OmniEval 引入处加一句"为何要 fuzzy"。\n'
    )
    llm.queue_text(analysis_md)
    llm.queue_text("Consult reflection.")  # for _reflect step

    ctx = WorkflowContext(
        task_id="consult-1",
        query="帮我分析这个摘要是否 AI 味道过重？",
        input={"text": ORIGINAL, "section": "abstract"},
        memory=memory,
        llm=llm,
    )
    out = await ConsultWorkflow().run(ctx)

    assert out.verdict == "ok"
    assert out.results is not None
    r = out.results
    assert r["section"] == "abstract"
    assert r["original"] == ORIGINAL
    assert "AI 味道" not in r["analysis"]  # we didn't echo the question back
    assert "[aaa111]" in r["analysis"]
    assert r["citations"] == ["aaa111"]
    assert len(r["suggestions"]) >= 2
    # Crucially: NO revised field. Consult never writes back.
    assert "revised" not in r
    assert "change_log" not in r


@pytest.mark.asyncio
async def test_consult_template_fallback_when_no_llm():
    """No LLM wired → deterministic fallback message that still mirrors
    the live result shape so the UI keeps working in offline mode."""

    memory = MemoryBundle.in_memory()
    ctx = WorkflowContext(
        task_id="consult-2",
        query="哪些地方还能改？",
        input={"text": ORIGINAL, "section": "abstract"},
        memory=memory,
        llm=None,
    )
    out = await ConsultWorkflow().run(ctx)

    assert out.verdict == "ok"
    assert out.results is not None
    assert "Template fallback" in out.results["analysis"]
    assert out.results["original"] == ORIGINAL


# ---------------------------------------------------------------------------
# Validation contract — explicit errors instead of generic "missing text"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consult_missing_text_yields_clear_error():
    ctx = WorkflowContext(
        task_id="consult-err-1",
        query="anything?",
        input={},
        memory=MemoryBundle.in_memory(),
        llm=None,
    )
    out = await ConsultWorkflow().run(ctx)
    assert out.verdict == "error"
    assert out.error is not None
    assert out.error.startswith("ValueError:")
    assert "consult needs" in out.error


@pytest.mark.asyncio
async def test_consult_missing_query_yields_clear_error():
    ctx = WorkflowContext(
        task_id="consult-err-2",
        query="",
        input={"text": ORIGINAL},
        memory=MemoryBundle.in_memory(),
        llm=None,
    )
    out = await ConsultWorkflow().run(ctx)
    assert out.verdict == "error"
    assert out.error is not None
    assert "non-empty query" in out.error


@pytest.mark.asyncio
async def test_consult_bundle_target_without_manuscript_id_yields_clear_error():
    ctx = WorkflowContext(
        task_id="consult-err-3",
        query="what about this?",
        input={"bundle_target": "overleaf/sections/abstract.tex"},
        memory=MemoryBundle.in_memory(),
        llm=None,
    )
    out = await ConsultWorkflow().run(ctx)
    assert out.verdict == "error"
    assert out.error is not None
    assert "bundle_target was set" in out.error


# ---------------------------------------------------------------------------
# Recall soft-fail (P12.1) — a broken memory layer must not abort consult.
# ---------------------------------------------------------------------------


class _ExplodingMemory:
    """Stand-in MemoryBundle whose ``snapshot`` raises BrokenPipeError.

    Mirrors the real failure mode we saw in production: the embedder's
    socket got into a bad state mid-recall and the OSError escaped
    every existing wrapper. P12.1 says the workflow must keep going
    with an empty snapshot rather than die."""

    async def snapshot(self, *_args, **_kwargs):
        raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.asyncio
async def test_consult_recall_failure_does_not_abort_task():
    """A failing recall stage must:
    * keep ``verdict == "ok"`` (analysis can still run without history),
    * emit a ``task.warning`` carrying the normalised
      ``InfrastructureError`` type,
    * leave ``papers == []`` in the result so downstream rendering
      doesn't blow up."""

    from backend.core.events import EventType

    llm = MockLLMProvider()
    llm.queue_text("No related work available — here's a direct analysis.\n")
    llm.queue_text("Reflection.")

    ctx = WorkflowContext(
        task_id="consult-recall-fail",
        query="abstract 看起来怎么样？",
        input={"text": ORIGINAL, "section": "abstract"},
        memory=_ExplodingMemory(),
        llm=llm,
    )
    out = await ConsultWorkflow().run(ctx)

    assert out.verdict == "ok"
    assert out.results is not None
    assert out.results["papers"] == []

    warnings = [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    assert warnings, "recall failure must emit a task.warning"
    w = warnings[0].data
    assert w["stage"] == "recall"
    assert w["source_type"] == "BrokenPipeError"
    assert w["type"] == "InfrastructureError"
    assert w["recoverable"] is True


# ---------------------------------------------------------------------------
# History normalisation — multi-turn behaviour
# ---------------------------------------------------------------------------


def test_normalise_history_keeps_role_and_caps_per_turn_length():
    raw = [
        {"role": "user", "content": "first question"},
        {"role": "ASSISTANT", "content": "first answer"},
        {"role": "bogus", "content": "second question"},  # defaults to user
        {"role": "user", "content": ""},  # dropped (empty)
        {"role": "user", "content": "x" * 1200},  # capped
    ]
    out = _normalise_history(raw)
    assert [t["role"] for t in out] == ["user", "assistant", "user", "user"]
    assert all(len(t["content"]) <= 600 for t in out)


def test_normalise_history_keeps_only_recent_turns():
    raw = [{"role": "user", "content": f"q{i}"} for i in range(20)]
    out = _normalise_history(raw)
    assert len(out) == 8
    assert out[-1]["content"] == "q19"


def test_normalise_history_ignores_non_list_input():
    assert _normalise_history(None) == []
    assert _normalise_history("nope") == []
    assert _normalise_history({"role": "user", "content": "x"}) == []


# ---------------------------------------------------------------------------
# Suggestion parser — best-effort bullet extraction
# ---------------------------------------------------------------------------


def test_parse_suggestions_pulls_bullet_lines_and_caps_at_eight():
    md = """
## 观察
正文段落，不应该被解析。

- 第一条建议
- 第二条建议
1. 第三条建议
2) 第四条建议
* 第五条建议
- 第六条建议
- 第七条建议
- 第八条建议
- 第九条建议（应该被截掉）
"""
    out = _parse_suggestions(md)
    assert len(out) == 8
    assert out[0] == "第一条建议"


def test_parse_suggestions_handles_no_bullets():
    assert _parse_suggestions("Just prose, no bullets at all.\n") == []
