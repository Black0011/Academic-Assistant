"""Integration tests for ``/api/proposals`` (M8.1).

We rely on the in-memory store to keep the tests hermetic. Auth is
``auth_disabled=True`` (the default) so admin transitions succeed
without bearer tokens — non-open mode is exercised in
``test_app_proposals_auth.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.proposals.store import InMemoryProposalStore
from backend.settings import Settings


@pytest.fixture
def app_state() -> AppState:
    settings = Settings()  # type: ignore[call-arg]
    return AppState(settings=settings, proposals=InMemoryProposalStore())


@pytest.fixture
async def client(app_state: AppState) -> AsyncIterator[AsyncClient]:
    app = create_app(state=app_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


def _payload(**kwargs: object) -> dict[str, object]:
    base: dict[str, object] = {
        "title": "Add memory exporter skill",
        "summary": "expose recall stage as standalone skill",
        "motivation": "let CLI users dump bundle.snapshot()",
        "risk_level": "low",
        "target_paths": ["skills/aaf-memory-exporter/SKILL.md"],
        "diff": "diff --git a/x b/x",
        "tags": ["memory"],
        "proposer_kind": "human",
        "proposer_id": "user_1",
    }
    base.update(kwargs)
    return base


async def test_create_then_get(client: AsyncClient) -> None:
    resp = await client.post("/api/proposals", json=_payload())
    assert resp.status_code == 201, resp.text
    data = resp.json()
    pid = data["proposal_id"]
    assert data["status"] == "draft"

    resp = await client.get(f"/api/proposals/{pid}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Add memory exporter skill"


async def test_list_filters(client: AsyncClient) -> None:
    a = (await client.post("/api/proposals", json=_payload(title="A"))).json()
    b_payload = _payload(title="B", tags=["skill"], proposer_id="bob")
    b = (await client.post("/api/proposals", json=b_payload)).json()
    await client.post(f"/api/proposals/{b['proposal_id']}:submit", json={"notes": "ready"})

    drafts = (await client.get("/api/proposals", params={"status": "draft"})).json()
    assert {p["proposal_id"] for p in drafts["items"]} == {a["proposal_id"]}

    pending = (await client.get("/api/proposals", params={"status": "pending"})).json()
    assert {p["proposal_id"] for p in pending["items"]} == {b["proposal_id"]}

    by_tag = (await client.get("/api/proposals", params={"tag": "skill"})).json()
    assert {p["proposal_id"] for p in by_tag["items"]} == {b["proposal_id"]}


async def test_patch_in_draft(client: AsyncClient) -> None:
    p = (await client.post("/api/proposals", json=_payload())).json()
    pid = p["proposal_id"]
    resp = await client.patch(
        f"/api/proposals/{pid}",
        json={"title": "Updated", "notes": "renamed"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["title"] == "Updated"
    actions = [ev["action"] for ev in body["audit_log"]]
    assert "update" in actions


async def test_full_lifecycle_open_mode(client: AsyncClient) -> None:
    p = (await client.post("/api/proposals", json=_payload())).json()
    pid = p["proposal_id"]

    submitted = (await client.post(f"/api/proposals/{pid}:submit")).json()
    assert submitted["status"] == "pending"

    approved = (await client.post(f"/api/proposals/{pid}:approve", json={"notes": "LGTM"})).json()
    assert approved["status"] == "approved"
    assert approved["decided_at"] is not None

    applied = (await client.post(f"/api/proposals/{pid}:apply")).json()
    assert applied["status"] == "applied"
    assert applied["applied_at"] is not None
    actions = [ev["action"] for ev in applied["audit_log"]]
    assert actions[-1] == "apply"


async def test_illegal_transition_returns_409(client: AsyncClient) -> None:
    p = (await client.post("/api/proposals", json=_payload())).json()
    pid = p["proposal_id"]
    # Skipping submit -> approve must be rejected.
    resp = await client.post(f"/api/proposals/{pid}:approve")
    assert resp.status_code == 409
    assert "illegal transition" in resp.text


async def test_withdraw_path(client: AsyncClient) -> None:
    p = (await client.post("/api/proposals", json=_payload())).json()
    pid = p["proposal_id"]
    await client.post(f"/api/proposals/{pid}:submit")
    withdrawn = (await client.post(f"/api/proposals/{pid}:withdraw")).json()
    assert withdrawn["status"] == "withdrawn"


async def test_reject_path(client: AsyncClient) -> None:
    p = (await client.post("/api/proposals", json=_payload())).json()
    pid = p["proposal_id"]
    await client.post(f"/api/proposals/{pid}:submit")
    rejected = (
        await client.post(f"/api/proposals/{pid}:reject", json={"notes": "scope creep"})
    ).json()
    assert rejected["status"] == "rejected"
    assert rejected["audit_log"][-1]["notes"] == "scope creep"


async def test_delete_only_when_draft_or_withdrawn(client: AsyncClient) -> None:
    p = (await client.post("/api/proposals", json=_payload())).json()
    pid = p["proposal_id"]
    await client.post(f"/api/proposals/{pid}:submit")

    # Cannot delete pending.
    resp = await client.delete(f"/api/proposals/{pid}")
    assert resp.status_code == 409

    # Withdraw, then delete succeeds.
    await client.post(f"/api/proposals/{pid}:withdraw")
    resp = await client.delete(f"/api/proposals/{pid}")
    assert resp.status_code == 204

    resp = await client.get(f"/api/proposals/{pid}")
    assert resp.status_code == 404
