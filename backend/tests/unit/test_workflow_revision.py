"""Unit tests for `RevisionWorkflow`."""

from __future__ import annotations

import json

import pytest

from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.memory.models import PaperCard
from backend.workflows.base import WorkflowContext
from backend.workflows.revision import (
    RevisionWorkflow,
    _extract_json_object,
    _normalise_comments,
)

ORIGINAL = (
    "The method works well in practice, but scalability has not been explored. "
    "Future work should investigate large-scale deployments."
)


async def _seed(memory: MemoryBundle) -> PaperCard:
    card = PaperCard(
        paper_id="aaa111",
        title="Scaling Retrieval",
        authors=["Alice"],
        abstract="Scaling study",
        summary="Discusses scalability of retrieval-augmented pipelines.",
        tags=["scalability"],
        url="https://arxiv.org/abs/2401.00004",
        citation_url="https://scholar.googleusercontent.com/scholar.bib?q=info:aaa111",
        citation_bibtex="@article{scale2024, title={Scaling Retrieval}, author={Alice}, year={2024}}",
    )
    await memory.knowledge.write_card(card)
    await memory.vector.add(card.paper_id, card.search_text())
    return card


async def test_revision_with_llm_full_path():
    memory = MemoryBundle.in_memory()
    await _seed(memory)
    llm = MockLLMProvider()
    plan_json = json.dumps(
        {
            "plan": [
                {
                    "comment_id": "c1",
                    "decision": "accept",
                    "action": "Add scalability discussion with citation.",
                },
                {
                    "comment_id": "c2",
                    "decision": "defer",
                    "action": "Reviewer out of scope.",
                },
            ]
        }
    )
    llm.queue_text(plan_json)
    revised_text = (
        "The method scales to billions of documents [aaa111]. "
        "We reserve deployment-environment concerns for later work."
    )
    llm.queue_text(revised_text)
    llm.queue_text("Revision reflection.")

    ctx = WorkflowContext(
        task_id="rev-1",
        query="Address reviewer comments on scaling.",
        input={
            "text": ORIGINAL,
            "section": "discussion",
            "comments": [
                {"id": "c1", "category": "critical", "text": "Please discuss scalability."},
                {"id": "c2", "category": "minor", "text": "What about SLA?"},
            ],
        },
        memory=memory,
        llm=llm,
    )
    out = await RevisionWorkflow().run(ctx)

    assert out.verdict == "ok", out.error
    res = out.results
    assert res["original"] == ORIGINAL
    assert "scales to billions" in res["revised"]
    assert res["citations"] == ["aaa111"]
    assert res["comments_addressed"] == ["c1"]
    assert res["comments_open"] == ["c2"]
    assert len(res["change_log"]) == 2
    assert res["change_log"][0]["decision"] == "accept"
    assert res["change_log"][1]["decision"] == "defer"

    recent = await memory.episodic.recent(n=3)
    assert recent and recent[0].source_run_id == "rev-1"


async def test_revision_falls_back_when_llm_absent():
    memory = MemoryBundle.in_memory()
    ctx = WorkflowContext(
        task_id="rev-2",
        query="polish",
        input={
            "text": ORIGINAL,
            "comments": ["Clarity needs improvement."],
        },
        memory=memory,
        llm=None,
    )
    out = await RevisionWorkflow().run(ctx)
    assert out.verdict == "ok", out.error
    # Fallback prepends the original and appends a revision-notes block.
    assert ORIGINAL.strip() in out.results["revised"]
    assert "Revision notes" in out.results["revised"]
    assert out.results["change_log"][0]["decision"] == "accept"


async def test_revision_requires_text_input():
    ctx = WorkflowContext(task_id="rev-3", query="no text", input={"text": ""})
    out = await RevisionWorkflow().run(ctx)
    assert out.verdict == "error"
    assert "text" in (out.error or "")
    # P9.0 — workflow error string keeps the exception type prefix so the
    # frontend can distinguish ValueError from LLMStreamError etc.
    assert (out.error or "").startswith("ValueError:")


async def test_revision_friendly_error_when_bundle_target_set_but_no_manuscript():
    ctx = WorkflowContext(
        task_id="rev-bundle-missing-ms",
        query="hint",
        input={"bundle_target": "overleaf/main.tex"},
    )
    out = await RevisionWorkflow().run(ctx)
    assert out.verdict == "error"
    assert "bundle_target was set but manuscript_id is empty" in (out.error or "")


async def test_revision_friendly_error_when_manuscript_set_but_no_bundle_target():
    ctx = WorkflowContext(
        task_id="rev-bundle-missing-target",
        query="hint",
        input={"manuscript_id": "abc"},
    )
    out = await RevisionWorkflow().run(ctx)
    assert out.verdict == "error"
    assert "manuscript_id was set but bundle_target is empty" in (out.error or "")


async def test_revision_friendly_error_when_both_set_but_text_empty():
    # Simulates what the runner does when pre-read returns an empty file.
    ctx = WorkflowContext(
        task_id="rev-bundle-empty-file",
        query="hint",
        input={
            "manuscript_id": "abc",
            "bundle_target": "overleaf/sections/intro.tex",
            "text": "",
        },
    )
    out = await RevisionWorkflow().run(ctx)
    assert out.verdict == "error"
    err = out.error or ""
    assert "target file is empty after pre-read" in err
    assert "manuscript=abc" in err
    assert "bundle_target=overleaf/sections/intro.tex" in err


async def test_revision_synthesises_comment_when_none_given():
    memory = MemoryBundle.in_memory()
    ctx = WorkflowContext(
        task_id="rev-4",
        query="tighten the prose",
        input={"text": ORIGINAL},
        memory=memory,
        llm=None,
    )
    out = await RevisionWorkflow().run(ctx)
    assert out.verdict == "ok", out.error
    assert out.results["change_log"][0]["comment_id"] == "c1"
    assert "tighten" in out.results["change_log"][0]["comment"]


# ---------------------------------------------------------------------------
# Recall soft-fail (P12.1) — broken memory must not abort revision.
# ---------------------------------------------------------------------------


class _ExplodingMemory:
    async def snapshot(self, *_args, **_kwargs):
        raise BrokenPipeError(32, "Broken pipe")


@pytest.mark.asyncio
async def test_revision_recall_failure_does_not_abort_task():
    """A failing recall stage must keep verdict==ok and emit task.warning.

    Without this, the user's prior bug report — "revision task dies on
    [Errno 32] Broken pipe" — re-surfaces every time the embedder hiccups."""

    from backend.core.events import EventType

    llm = MockLLMProvider()
    llm.queue_text(
        json.dumps({"plan": [{"comment_id": "c1", "decision": "accept", "action": "tighten"}]})
    )
    llm.queue_text("Tightened prose without external citations.")
    llm.queue_text("Revision reflection.")

    ctx = WorkflowContext(
        task_id="rev-recall-fail",
        query="tighten",
        input={
            "text": ORIGINAL,
            "comments": [{"id": "c1", "category": "minor", "text": "Tighten."}],
        },
        memory=_ExplodingMemory(),
        llm=llm,
    )
    out = await RevisionWorkflow().run(ctx)

    assert out.verdict == "ok", out.error
    # Revision output doesn't expose `papers` directly; it surfaces
    # citations parsed out of the revised text. With recall degraded
    # and no citations in the revised text, that list is empty.
    assert out.results["citations"] == []
    # The actual revised text still got produced — that's the whole
    # point of soft-fail.
    assert out.results["revised"]

    warnings = [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    assert warnings, "recall failure must emit a task.warning"
    recall_warning = next(w for w in warnings if w.data.get("stage") == "recall")
    assert recall_warning.data["source_type"] == "BrokenPipeError"


def test_normalise_comments_accepts_strings_and_dicts():
    comments = _normalise_comments(
        ["Fix grammar.", {"id": "X", "category": "major", "text": "Add results."}]
    )
    assert comments[0].id == "c1"
    assert comments[0].category == "general"
    assert comments[1].id == "X"
    assert comments[1].category == "major"


def test_normalise_comments_empty_inputs():
    assert _normalise_comments(None) == []
    assert _normalise_comments([]) == []
    assert _normalise_comments([{"text": ""}]) == []


def test_extract_json_handles_fences_and_prose():
    assert _extract_json_object('{"plan": []}') == {"plan": []}
    assert _extract_json_object('```json\n{"a":1}\n```') == {"a": 1}
    assert _extract_json_object('prose before {"b":2} and after') == {"b": 2}
    assert _extract_json_object("nothing") is None
