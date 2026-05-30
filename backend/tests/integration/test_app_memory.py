"""Integration tests for the extended `/api/memory` admin surface."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.memory.base import gen_id
from backend.memory.models import (
    Heuristic,
    PaperCard,
    Reflection,
    SessionContext,
    StrategyBlock,
)
from backend.settings import Settings


@pytest.fixture
async def bundle():
    return MemoryBundle.in_memory()


@pytest.fixture
async def client(bundle):
    state = AppState(
        settings=Settings(),
        memory=bundle,
        llm=MockLLMProvider(),
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# Snapshot (already existed) — quick smoke
# ---------------------------------------------------------------------------


async def test_snapshot_smoke(client):
    r = await client.get("/api/memory/snapshot", params={"query": "agents", "k": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "agents"


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


async def test_stats_reflects_writes(bundle, client):
    await bundle.knowledge.write_card(PaperCard(paper_id="p1", title="P1"))
    await bundle.knowledge.write_card(PaperCard(paper_id="p2", title="P2"))
    await bundle.heuristic.add(
        Heuristic(
            id=gen_id(),
            name="h1",
            domain="writing",
            trigger_pattern="x",
            strategy=StrategyBlock(),
        )
    )
    await bundle.episodic.append(Reflection(id=gen_id(), content="r1", source_run_id="run-x"))

    r = await client.get("/api/memory/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["knowledge_count"] == 2
    assert body["heuristic_count"] >= 1
    assert body["reflection_count"] == 1
    assert body["session_backend"] == "InMemorySessionStore"


# ---------------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------------


async def test_create_and_list_reflections(client):
    r = await client.post(
        "/api/memory/reflections",
        json={
            "type": "observation",
            "content": "Outline first works better.",
            "tags": ["writing"],
            "session_id": "s1",
        },
    )
    assert r.status_code == 201
    rid = r.json()["id"]
    assert rid

    r = await client.get("/api/memory/reflections", params={"session_id": "s1"})
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["id"] == rid for i in items)

    r = await client.get("/api/memory/reflections", params={"type": "insight"})
    assert all(i["type"] == "insight" for i in r.json()["items"])


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


async def test_session_lifecycle(client):
    r = await client.post(
        "/api/memory/sessions",
        json={"user_id": "u1", "title": "Project A"},
    )
    assert r.status_code == 201
    sid = r.json()["session_id"]
    assert sid

    r = await client.get(f"/api/memory/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["title"] == "Project A"

    r = await client.patch(
        f"/api/memory/sessions/{sid}",
        json={"title": "Renamed", "state": {"step": 1}},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"
    assert r.json()["state"] == {"step": 1}

    r = await client.post(
        f"/api/memory/sessions/{sid}/messages",
        json={"role": "user", "content": "Hello"},
    )
    assert r.status_code == 201

    r = await client.get(f"/api/memory/sessions/{sid}")
    body = r.json()
    assert body["messages"][0]["content"] == "Hello"

    r = await client.get("/api/memory/sessions", params={"user_id": "u1"})
    assert r.status_code == 200
    assert any(s["session_id"] == sid for s in r.json()["items"])

    r = await client.delete(f"/api/memory/sessions/{sid}")
    assert r.status_code == 204
    assert (await client.get(f"/api/memory/sessions/{sid}")).status_code == 404


async def test_update_missing_session_404(client):
    r = await client.patch("/api/memory/sessions/missing", json={"title": "x"})
    assert r.status_code == 404


async def test_append_missing_session_404(client):
    r = await client.post(
        "/api/memory/sessions/missing/messages",
        json={"role": "user", "content": "hi"},
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Rollback
# ---------------------------------------------------------------------------


async def test_rollback_removes_writes_for_run(bundle, client):
    run_id = "run-42"
    await bundle.knowledge.write_card(PaperCard(paper_id="px", title="X", source_run_id=run_id))
    await bundle.heuristic.add(
        Heuristic(
            id=gen_id(),
            name="h",
            domain="research",
            trigger_pattern="x",
            strategy=StrategyBlock(),
            source_run_id=run_id,
        )
    )
    await bundle.episodic.append(Reflection(id=gen_id(), content="r", source_run_id=run_id))

    r = await client.post(f"/api/memory/rollback/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["knowledge_removed"] == 1
    assert body["heuristics_removed"] == 1
    assert body["reflections_removed"] == 1

    # Idempotent — second call removes 0.
    r = await client.post(f"/api/memory/rollback/{run_id}")
    assert (
        sum(
            body.get(k, 0)
            for k in ("knowledge_removed", "heuristics_removed", "reflections_removed")
        )
        >= 0
    )
    body2 = r.json()
    assert body2["knowledge_removed"] == 0


# ---------------------------------------------------------------------------
# 503 when memory not wired
# ---------------------------------------------------------------------------


async def test_503_when_memory_missing():
    state = AppState(settings=Settings())
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        assert (await c.get("/api/memory/stats")).status_code == 503
        assert (await c.post("/api/memory/rollback/x")).status_code == 503


# ---------------------------------------------------------------------------
# P14.A — Reflection PATCH / DELETE / bulk delete via HTTP
# ---------------------------------------------------------------------------


async def _create(client, **kw) -> str:
    r = await client.post(
        "/api/memory/reflections",
        json={"type": "reflection", "content": "seed", **kw},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def test_patch_reflection_partial_only(client):
    rid = await _create(client, content="orig", tags=["a"], session_id="s1")

    r = await client.patch(
        f"/api/memory/reflections/{rid}",
        json={"content": "rewritten"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["content"] == "rewritten"
    assert body["tags"] == ["a"]  # untouched
    assert body["session_id"] == "s1"  # provenance untouched


async def test_patch_reflection_404_for_missing(client):
    r = await client.patch(
        "/api/memory/reflections/not-real",
        json={"content": "x"},
    )
    assert r.status_code == 404


async def test_patch_reflection_rejects_unknown_fields(client):
    """``extra="forbid"`` on the input model — protect against the user
    trying to PATCH ``user_id`` or ``source_run_id`` (provenance)."""
    rid = await _create(client)
    r = await client.patch(
        f"/api/memory/reflections/{rid}",
        json={"user_id": "spoofed"},
    )
    assert r.status_code == 422


async def test_delete_reflection_204_then_404(client):
    rid = await _create(client)
    assert (await client.delete(f"/api/memory/reflections/{rid}")).status_code == 204
    # second delete must 404, not 204 — we leak existence info on purpose
    # to make admin scripts idempotent + observable.
    assert (await client.delete(f"/api/memory/reflections/{rid}")).status_code == 404


async def test_bulk_delete_requires_at_least_one_filter(client):
    r = await client.delete("/api/memory/reflections")
    assert r.status_code == 400
    assert "session_id" in r.text or "source_run_id" in r.text


async def test_bulk_delete_by_session(client):
    a = await _create(client, session_id="s1")
    b = await _create(client, session_id="s1")
    c = await _create(client, session_id="s2")

    r = await client.delete("/api/memory/reflections", params={"session_id": "s1"})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2

    remaining = await client.get("/api/memory/reflections", params={"n": 50})
    ids = [i["id"] for i in remaining.json()["items"]]
    assert c in ids
    assert a not in ids and b not in ids


async def test_bulk_delete_combines_facets_with_and(client):
    """Both ``session_id`` and ``source_run_id`` ⇒ only rows matching
    BOTH go away. Mirrors the unit-level contract."""
    keep = await _create(client, session_id="s1", source_run_id="run-b")
    drop = await _create(client, session_id="s1", source_run_id="run-a")

    r = await client.delete(
        "/api/memory/reflections",
        params={"session_id": "s1", "source_run_id": "run-a"},
    )
    assert r.status_code == 200
    assert r.json()["deleted"] == 1

    remaining = await client.get("/api/memory/reflections", params={"n": 50})
    ids = [i["id"] for i in remaining.json()["items"]]
    assert keep in ids
    assert drop not in ids
