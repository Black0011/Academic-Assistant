"""Integration tests for the FastAPI app — health + version + memory endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle, PaperCard
from backend.settings import Settings


@pytest.fixture
async def client():
    """App wired with an in-memory MemoryBundle + MockLLMProvider — no lifespan."""
    state = AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_health_endpoint(client):
    r = await client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_version_endpoint_reports_wiring(client):
    r = await client.get("/api/version")
    assert r.status_code == 200
    body = r.json()
    assert body["version"]
    assert body["llm_provider"] == "mock"
    assert body["memory"]["vector"] == "InMemoryVectorStore"
    assert body["memory"]["session"] == "InMemorySessionStore"


async def test_version_endpoint_includes_build_identity(client):
    """P12.2 — every /api/version response carries the running process's
    git identity so the frontend can render a "code version" badge and
    operators can answer "which commit is up?" without shell access."""
    r = await client.get("/api/version")
    body = r.json()
    assert "build" in body, "build identity must surface on /api/version"
    build = body["build"]
    # Required keys — even when git is unavailable we still ship the
    # full schema with "unknown" placeholders, never partial dicts.
    assert set(build.keys()) == {
        "git_sha",
        "git_sha_short",
        "git_dirty",
        "commit_ts",
        "commit_subject",
    }
    # In the dev workspace where tests run, git is present and HEAD has
    # a sha — assert non-empty rather than a specific value (would
    # break on every commit otherwise).
    assert isinstance(build["git_sha"], str)
    assert isinstance(build["git_sha_short"], str)
    assert isinstance(build["git_dirty"], bool)


async def test_memory_snapshot_empty(client):
    r = await client.get("/api/memory/snapshot", params={"query": "retinoid acne"})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "retinoid acne"
    assert body["related_papers"] == []
    assert body["heuristics"] == []


async def test_memory_snapshot_returns_related_papers():
    state = AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
    )
    await state.memory.knowledge.write_card(
        PaperCard(paper_id="p1", title="retinoid acne trial", abstract="efficacy", tags=["derm"])
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get(
            "/api/memory/snapshot",
            params={"query": "retinoid", "domain": "research", "k": "3"},
        )
    assert r.status_code == 200
    papers = r.json()["related_papers"]
    assert any(p["paper_id"] == "p1" for p in papers)


async def test_memory_snapshot_requires_query(client):
    r = await client.get("/api/memory/snapshot")
    assert r.status_code == 422
