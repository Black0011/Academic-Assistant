"""Integration tests for `/api/heuristics`."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.settings import Settings


@pytest.fixture
async def client():
    state = AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def _create(client, **overrides):
    body = {
        "name": "Cite seminal first",
        "description": "Anchor surveys with the seminal paper.",
        "domain": "writing",
        "trigger_pattern": "intro,survey,seminal",
        "strategy": {
            "planning_hints": "Find the seminal work first.",
            "search_tips": "Sort by year ascending.",
            "evaluation_criteria": "Citations of the seminal work.",
        },
    }
    body.update(overrides)
    r = await client.post("/api/heuristics", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_create_get_delete(client):
    h = await _create(client)
    hid = h["id"]
    assert h["domain"] == "writing"
    assert h["success_count"] == 1

    r = await client.get(f"/api/heuristics/{hid}")
    assert r.status_code == 200
    assert r.json()["name"] == "Cite seminal first"

    r = await client.delete(f"/api/heuristics/{hid}")
    assert r.status_code == 204
    assert (await client.get(f"/api/heuristics/{hid}")).status_code == 404


async def test_list_filtered_by_domain(client):
    await _create(client, name="W1", domain="writing")
    await _create(client, name="R1", domain="research")
    await _create(client, name="R2", domain="research")

    r = await client.get("/api/heuristics", params={"domain": "research"})
    assert r.status_code == 200
    body = r.json()
    names = sorted(h["name"] for h in body["items"])
    assert names == ["R1", "R2"]


async def test_match_returns_top_k(client):
    await _create(
        client,
        name="Survey rule",
        domain="writing",
        trigger_pattern="survey,outline,intro",
    )
    await _create(
        client,
        name="Other rule",
        domain="writing",
        trigger_pattern="rebuttal,reply",
    )
    r = await client.get(
        "/api/heuristics/match",
        params={"query": "outline survey intro", "domain": "writing", "top_k": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["items"], body
    assert body["items"][0]["name"] == "Survey rule"


async def test_patch_updates_strategy(client):
    h = await _create(client)
    r = await client.patch(
        f"/api/heuristics/{h['id']}",
        json={
            "description": "Updated description",
            "strategy": {
                "planning_hints": "Updated hint",
                "search_tips": "",
                "evaluation_criteria": "",
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["description"] == "Updated description"
    assert body["strategy"]["planning_hints"] == "Updated hint"


async def test_freeze_unfreeze_hides_from_match(client):
    h = await _create(client, name="Freezable", trigger_pattern="x,y,z")
    hid = h["id"]

    r = await client.post(f"/api/heuristics/{hid}/freeze")
    assert r.status_code == 200
    assert r.json()["frozen"] is True

    # Frozen entries are hidden from match.
    r = await client.get("/api/heuristics/match", params={"query": "x y z", "domain": "writing"})
    assert all(h["id"] != hid for h in r.json()["items"])

    r = await client.post(f"/api/heuristics/{hid}/unfreeze")
    assert r.status_code == 200
    assert r.json()["frozen"] is False


async def test_bump_success_and_failure(client):
    h = await _create(client)
    hid = h["id"]

    r = await client.post(f"/api/heuristics/{hid}/bump", json={"verdict": "pass"})
    assert r.status_code == 200
    assert r.json()["success_count"] >= 2

    r = await client.post(f"/api/heuristics/{hid}/bump", json={"verdict": "fail"})
    assert r.status_code == 200
    assert r.json()["failure_count"] >= 1


async def test_list_excludes_frozen_when_requested(client):
    h = await _create(client, name="Hidden", trigger_pattern="hidden")
    await client.post(f"/api/heuristics/{h['id']}/freeze")

    r = await client.get("/api/heuristics", params={"include_frozen": False})
    assert all(item["id"] != h["id"] for item in r.json()["items"])

    r = await client.get("/api/heuristics", params={"include_frozen": True})
    assert any(item["id"] == h["id"] for item in r.json()["items"])
