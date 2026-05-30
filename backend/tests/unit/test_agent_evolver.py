"""Unit tests for :class:`backend.agents.evolver.EvolverAgent`.

Covers the contract surface:

* "ok" verdict ⇒ exactly one proposal in the store.
* non-"ok" verdict ⇒ no proposal.
* ``results["evolve"] is False`` opt-out ⇒ no proposal.
* template path (no LLM) yields a syntactically valid proposal.
* LLM path (mocked) yields a proposal with title/summary parsed from
  the model's JSON output.
* LLM ``{"skip": true}`` ⇒ no proposal.
* LLM bad JSON ⇒ no proposal.
* ProposalStore failure ⇒ ``None`` returned, no exception escapes.
* Evolver never raises — even on absurd LLM output.

Mock LLM is preferred over httpx.MockTransport here: we exercise the
agent's branching, not the transport.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from backend.agents.evolver import EvolverAgent
from backend.core.llm.mock import MockLLMProvider
from backend.proposals.store import InMemoryProposalStore
from backend.tasks.models import TaskRecord
from backend.workflows.base import WorkflowOutput


def _record(workflow: str = "write", *, task_id: str = "abc12345") -> TaskRecord:
    return TaskRecord(
        id=task_id,
        workflow=workflow,
        status="ok",
        query="how to write the related-work section",
        input={"section": "related_work"},
        budget={"cost_usd": 0.0021, "calls": 4},
        result={"section": "related_work", "word_count": 612, "citations": ["a", "b"]},
        created_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
    )


def _output(verdict: str = "ok", **results) -> WorkflowOutput:
    return WorkflowOutput(
        task_id="abc12345",
        verdict=verdict,
        results=results or None,
        budget={"cost_usd": 0.0021},
    )


# ---------------------------------------------------------------------------
# Verdict / opt-out gates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_proposal_for_non_ok_verdict() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    out = _output(verdict="error", section="x")

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is None
    assert await store.list_all() == []


@pytest.mark.asyncio
async def test_opt_out_via_results_flag() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    out = _output(evolve=False, section="x", word_count=100)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is None
    assert await store.list_all() == []


# ---------------------------------------------------------------------------
# Template path (no LLM)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_template_path_creates_draft_proposal() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()  # no llm
    out = _output(section="related_work", word_count=612, citations=["a", "b"])

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is not None
    assert proposal.status == "draft"
    assert proposal.proposer_kind == "agent"
    assert proposal.proposer_id == "evolver"
    assert "self-evolution" in proposal.tags
    assert "write" in proposal.tags
    assert "llm-drafted" not in proposal.tags
    assert proposal.extras["via_llm"] is False
    assert proposal.extras["task_id"] == "abc12345"

    persisted = await store.list_all()
    assert len(persisted) == 1
    assert persisted[0].proposal_id == proposal.proposal_id


@pytest.mark.asyncio
async def test_template_summary_includes_word_count_for_write() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    out = _output(section="introduction", word_count=999, citations=["x"])

    proposal = await agent.evolve_from_run(record=_record("write"), output=out, store=store)
    assert proposal is not None
    assert "999 words" in proposal.summary


@pytest.mark.asyncio
async def test_template_summary_includes_change_count_for_revision() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    out = _output(change_log=[1, 2, 3])  # 3 changes

    proposal = await agent.evolve_from_run(record=_record("revision"), output=out, store=store)
    assert proposal is not None
    assert "3" in proposal.summary


# ---------------------------------------------------------------------------
# LLM path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_path_uses_parsed_json() -> None:
    store = InMemoryProposalStore()
    mock = MockLLMProvider()
    mock.queue_text(
        '{"title": "Cite primary source first",'
        ' "summary": "Lead with the primary citation in related-work paragraphs.",'
        ' "motivation": "Reviewer comments on prior runs flagged buried citations 7/12 times."}'
    )
    agent = EvolverAgent(llm=mock)
    out = _output(section="related_work", word_count=600)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is not None
    assert proposal.title == "Cite primary source first"
    assert proposal.summary.startswith("Lead with the primary citation")
    assert "Reviewer comments" in proposal.motivation
    assert "llm-drafted" in proposal.tags
    assert proposal.extras["via_llm"] is True


@pytest.mark.asyncio
async def test_llm_skip_true_falls_back_to_template() -> None:
    """When the LLM declines via {"skip": true}, the agent should
    fall back to the deterministic template — never producing zero
    proposals, so observability still shows the run finished."""

    store = InMemoryProposalStore()
    mock = MockLLMProvider()
    mock.queue_text('{"skip": true}')
    agent = EvolverAgent(llm=mock)
    out = _output(section="x", word_count=100)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is not None
    # Fell back to template, not LLM.
    assert proposal.extras["via_llm"] is False


@pytest.mark.asyncio
async def test_llm_bad_json_falls_back_to_template() -> None:
    store = InMemoryProposalStore()
    mock = MockLLMProvider()
    mock.queue_text("the model forgot how to JSON")
    agent = EvolverAgent(llm=mock)
    out = _output(section="x", word_count=10)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is not None
    assert proposal.extras["via_llm"] is False


@pytest.mark.asyncio
async def test_llm_code_fenced_json_is_parsed() -> None:
    store = InMemoryProposalStore()
    mock = MockLLMProvider()
    mock.queue_text(
        '```json\n{"title": "test t", "summary": "test s", "motivation": "test m"}\n```'
    )
    agent = EvolverAgent(llm=mock)
    out = _output(section="x", word_count=10)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is not None
    assert proposal.title == "test t"
    assert proposal.extras["via_llm"] is True


# ---------------------------------------------------------------------------
# Failure isolation — agent must never raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proposal_store_oserror_swallowed() -> None:
    """When the store raises OSError (e.g. yaml backend disk full),
    the agent must log + return None rather than escape."""

    class _FailingStore:
        async def create(self, body, *, actor=""):
            raise OSError("disk full")

        async def get(self, proposal_id):
            return None

        async def list_all(self, **kwargs):
            return []

        async def patch(self, proposal_id, body, *, actor=""):
            raise NotImplementedError

        async def transition(self, proposal_id, action, *, actor="", notes=""):
            raise NotImplementedError

        async def delete(self, proposal_id):
            return False

        async def close(self):
            pass

    agent = EvolverAgent()
    out = _output(section="x", word_count=10)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=_FailingStore())
    assert proposal is None


# ---------------------------------------------------------------------------
# P8 Phase C2 — bundle enrichment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bundle_change_attaches_diff_target_paths_and_extras() -> None:
    """When EvolverAgent is given a BundleChange, the resulting proposal
    must carry (a) target_paths set to [target_path], (b) a real unified
    diff in `diff`, and (c) the deterministic apply payload in `extras`."""
    from backend.tasks.runner import BundleChange

    store = InMemoryProposalStore()
    agent = EvolverAgent()

    change = BundleChange(
        manuscript_id="m_xyz",
        target_path="overleaf/sections/intro.tex",
        before="Our method is fast.\nWe report throughput.\n",
        after="Our method is fast (4.2x faster than baseline).\nWe report throughput.\n",
        workflow="revision",
    )

    out = _output(revised=change.after, section="intro")
    proposal = await agent.evolve_from_run(
        record=_record(workflow="revision"),
        output=out,
        store=store,
        bundle_change=change,
    )
    assert proposal is not None

    # target_paths replaced with bundle target.
    assert proposal.target_paths == ["overleaf/sections/intro.tex"]

    # diff is a real unified diff with proper headers + at least one + line.
    assert "--- a/overleaf/sections/intro.tex" in proposal.diff
    assert "+++ b/overleaf/sections/intro.tex" in proposal.diff
    assert "@@ " in proposal.diff
    assert "+Our method is fast (4.2x faster than baseline).\n" in proposal.diff

    # extras carries the deterministic apply payload.
    assert proposal.extras["manuscript_id"] == "m_xyz"
    assert proposal.extras["bundle_target"] == "overleaf/sections/intro.tex"
    assert proposal.extras["bundle_before"] == change.before
    assert proposal.extras["bundle_after"] == change.after
    assert proposal.extras["workflow"] == "revision"


@pytest.mark.asyncio
async def test_no_bundle_change_keeps_legacy_proposal_shape() -> None:
    """Sanity: when bundle_change is absent (i.e. single-doc / no
    manuscript), the proposal is still produced exactly as before —
    empty diff, empty target_paths, no bundle keys in extras."""
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    out = _output(section="x", word_count=10)

    proposal = await agent.evolve_from_run(record=_record(), output=out, store=store)
    assert proposal is not None
    assert proposal.target_paths == []
    assert proposal.diff == ""
    assert "bundle_target" not in proposal.extras
    assert "bundle_after" not in proposal.extras


# ---------------------------------------------------------------------------
# P9.4 — manual synthesis from a batch of recent runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evolve_from_recent_runs_template_path_creates_proposal() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    recs = [_record(workflow="revision", task_id=f"task{i:02d}") for i in range(3)]
    proposal = await agent.evolve_from_recent_runs(records=recs, store=store)
    assert proposal is not None
    assert "self-evolution" in proposal.tags
    assert "synthesis" in proposal.tags
    assert proposal.extras["synthesis"] is True
    assert proposal.extras["task_ids"] == [r.id for r in recs]
    assert proposal.extras["workflows"] == ["revision"]
    assert proposal.extras["via_llm"] is False


@pytest.mark.asyncio
async def test_evolve_from_recent_runs_skips_errors() -> None:
    """Records with status != 'ok' are silently dropped before drafting."""
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    recs = [
        _record(workflow="revision", task_id="good1"),
        TaskRecord(
            id="bad1",
            workflow="revision",
            status="error",
            error="something failed",
        ),
        _record(workflow="revision", task_id="good2"),
    ]
    proposal = await agent.evolve_from_recent_runs(records=recs, store=store)
    assert proposal is not None
    assert set(proposal.extras["task_ids"]) == {"good1", "good2"}


@pytest.mark.asyncio
async def test_evolve_from_recent_runs_no_ok_records_returns_none() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    recs = [
        TaskRecord(
            id="bad1",
            workflow="revision",
            status="error",
            error="boom",
        )
    ]
    proposal = await agent.evolve_from_recent_runs(records=recs, store=store)
    assert proposal is None


@pytest.mark.asyncio
async def test_evolve_from_recent_runs_mixed_workflows_uses_mixed_scope_label() -> None:
    store = InMemoryProposalStore()
    agent = EvolverAgent()
    recs = [
        _record(workflow="revision", task_id="rev1"),
        _record(workflow="write", task_id="w1"),
    ]
    proposal = await agent.evolve_from_recent_runs(records=recs, store=store)
    assert proposal is not None
    # scope label "mixed" makes it into tags & motivation
    assert "mixed" in proposal.tags


@pytest.mark.asyncio
async def test_bundle_change_for_new_file_diff_is_pure_addition() -> None:
    """A write-workflow bundle change with empty `before` (file did not
    exist before) must produce a unified diff whose body is all `+`
    lines — no `-` lines."""
    from backend.tasks.runner import BundleChange

    store = InMemoryProposalStore()
    agent = EvolverAgent()
    after = "# New section\n\nFresh prose.\n"

    change = BundleChange(
        manuscript_id="m_new",
        target_path="overleaf/sections/related-work.tex",
        before="",
        after=after,
        workflow="write",
    )
    out = _output(markdown=after, section="related-work")
    proposal = await agent.evolve_from_run(
        record=_record(workflow="write"),
        output=out,
        store=store,
        bundle_change=change,
    )
    assert proposal is not None

    body_lines = [
        line for line in proposal.diff.splitlines() if not line.startswith(("---", "+++", "@@"))
    ]
    assert any(line.startswith("+") for line in body_lines)
    assert not any(line.startswith("-") for line in body_lines)
    assert proposal.extras["bundle_before"] == ""
    assert proposal.extras["bundle_after"] == after
