"""Unit tests for the proposals store + state machine (M8.1).

Both the in-memory and YAML implementations satisfy the same contract,
so we run the same tests against each via ``pytest.mark.parametrize``.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from backend.proposals.models import (
    CreateProposalInput,
    UpdateProposalInput,
)
from backend.proposals.store import (
    IllegalTransitionError,
    InMemoryProposalStore,
    ProposalStore,
    YamlProposalStore,
)


def _create_payload(**overrides: Any) -> CreateProposalInput:
    base: dict[str, Any] = {
        "title": "Add memory exporter skill",
        "summary": "expose recall stage as standalone skill",
        "motivation": "let CLI users dump bundle.snapshot()",
        "risk_level": "low",
        "target_paths": ["skills/aaf-memory-exporter/SKILL.md"],
        "diff": "diff --git a/skills/... b/skills/...",
        "tags": ["memory", "skill"],
        "proposer_kind": "human",
        "proposer_id": "user_1",
    }
    base.update(overrides)
    return CreateProposalInput(**base)


@pytest.fixture
def store_factory(tmp_path: Path) -> Callable[[str], ProposalStore]:
    def _make(kind: str) -> ProposalStore:
        if kind == "yaml":
            store = YamlProposalStore(tmp_path / "proposals")
            return store
        return InMemoryProposalStore()

    return _make


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_create_returns_draft_with_audit(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")
    assert proposal.status == "draft"
    assert proposal.proposer_id == "user_1"
    assert proposal.audit_log[-1].action == "create"
    assert proposal.audit_log[-1].actor == "user_1"
    fetched = await store.get(proposal.proposal_id)
    assert fetched is not None
    assert fetched.title == proposal.title


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_patch_updates_fields_and_appends_audit(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")
    patched = await store.patch(
        proposal.proposal_id,
        UpdateProposalInput(title="Add memory exporter (v2)", notes="renamed"),
        actor="user_1",
    )
    assert patched.title == "Add memory exporter (v2)"
    assert any(ev.action == "update" and ev.notes == "renamed" for ev in patched.audit_log)


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_full_happy_path_state_machine(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")

    submitted = await store.transition(proposal.proposal_id, "submit", actor="user_1")
    assert submitted.status == "pending"

    approved = await store.transition(
        proposal.proposal_id, "approve", actor="admin_1", notes="LGTM"
    )
    assert approved.status == "approved"
    assert approved.reviewer_id == "admin_1"
    assert approved.decided_at is not None
    assert any(ev.action == "approve" for ev in approved.audit_log)

    applied = await store.transition(proposal.proposal_id, "apply", actor="admin_1")
    assert applied.status == "applied"
    assert applied.applied_at is not None


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_illegal_transition_raises(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")
    # draft -> approve is forbidden (must go through submit first).
    with pytest.raises(IllegalTransitionError):
        await store.transition(proposal.proposal_id, "approve", actor="admin_1")
    # draft -> apply is forbidden.
    with pytest.raises(IllegalTransitionError):
        await store.transition(proposal.proposal_id, "apply", actor="admin_1")


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_reject_path_terminates(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")
    await store.transition(proposal.proposal_id, "submit", actor="user_1")
    rejected = await store.transition(
        proposal.proposal_id, "reject", actor="admin_1", notes="too risky"
    )
    assert rejected.status == "rejected"
    # Cannot un-reject by approving.
    with pytest.raises(IllegalTransitionError):
        await store.transition(proposal.proposal_id, "approve", actor="admin_1")


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_withdraw_from_pending(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")
    await store.transition(proposal.proposal_id, "submit", actor="user_1")
    withdrawn = await store.transition(proposal.proposal_id, "withdraw", actor="user_1")
    assert withdrawn.status == "withdrawn"


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_filters_in_list_all(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    a = await store.create(
        _create_payload(title="A", tags=["memory"], proposer_id="alice"), actor="alice"
    )
    b = await store.create(
        _create_payload(title="B", tags=["skill"], proposer_id="bob"), actor="bob"
    )
    await store.transition(b.proposal_id, "submit", actor="bob")

    drafts = await store.list_all(status="draft")
    assert {p.proposal_id for p in drafts} == {a.proposal_id}

    pending = await store.list_all(status="pending")
    assert {p.proposal_id for p in pending} == {b.proposal_id}

    by_tag = await store.list_all(tag="memory")
    assert {p.proposal_id for p in by_tag} == {a.proposal_id}

    by_proposer = await store.list_all(proposer_id="bob")
    assert {p.proposal_id for p in by_proposer} == {b.proposal_id}


@pytest.mark.parametrize("kind", ["memory", "yaml"])
async def test_delete_removes_proposal(
    kind: str, store_factory: Callable[[str], ProposalStore]
) -> None:
    store = store_factory(kind)
    if isinstance(store, YamlProposalStore):
        await store.init()
    proposal = await store.create(_create_payload(), actor="user_1")
    assert await store.delete(proposal.proposal_id) is True
    assert await store.get(proposal.proposal_id) is None
    # Idempotent on missing.
    assert await store.delete(proposal.proposal_id) is False


async def test_yaml_store_persists_across_instances(tmp_path: Path) -> None:
    root = tmp_path / "proposals"
    store_a = YamlProposalStore(root)
    await store_a.init()
    proposal = await store_a.create(_create_payload(), actor="user_1")
    await store_a.transition(proposal.proposal_id, "submit", actor="user_1")

    # Fresh process scenario: re-open the same root.
    store_b = YamlProposalStore(root)
    await store_b.init()
    fetched = await store_b.get(proposal.proposal_id)
    assert fetched is not None
    assert fetched.status == "pending"
    assert any(ev.action == "submit" for ev in fetched.audit_log)
