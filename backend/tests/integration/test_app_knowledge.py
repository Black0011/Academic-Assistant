"""Integration tests for `/api/knowledge` (papers + links + syntheses)."""

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


# ---------------------------------------------------------------------------
# Paper card CRUD
# ---------------------------------------------------------------------------


async def test_create_and_get_paper(client):
    r = await client.post(
        "/api/knowledge/papers",
        json={
            "title": "Self-Evolving Agents",
            "authors": ["Alice", "Bob"],
            "year": 2024,
            "abstract": "A study of agents that improve themselves.",
            "tags": ["agent", "memory"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    pid = body["paper_id"]
    assert pid

    r = await client.get(f"/api/knowledge/papers/{pid}")
    assert r.status_code == 200
    assert r.json()["title"] == "Self-Evolving Agents"


async def test_create_with_explicit_id_overrides_derivation(client):
    r = await client.post(
        "/api/knowledge/papers",
        json={"paper_id": "p-explicit", "title": "Custom"},
    )
    assert r.status_code == 201
    assert r.json()["paper_id"] == "p-explicit"


async def test_get_missing_paper_returns_404(client):
    r = await client.get("/api/knowledge/papers/nope")
    assert r.status_code == 404


async def test_list_filters_and_searches(client):
    await client.post(
        "/api/knowledge/papers",
        json={"title": "Agent paper", "tags": ["agent"], "user_id": "u1"},
    )
    await client.post(
        "/api/knowledge/papers",
        json={"title": "Vision paper", "tags": ["vision"], "user_id": "u2"},
    )
    await client.post(
        "/api/knowledge/papers",
        json={"title": "Agent vision combo", "tags": ["agent", "vision"], "user_id": "u1"},
    )

    r = await client.get("/api/knowledge/papers", params={"user_id": "u1"})
    assert r.status_code == 200
    body = r.json()
    titles = {p["title"] for p in body["items"]}
    assert titles == {"Agent paper", "Agent vision combo"}

    r = await client.get("/api/knowledge/papers", params={"q": "vision"})
    titles = {p["title"] for p in r.json()["items"]}
    assert "Vision paper" in titles

    r = await client.get("/api/knowledge/papers", params={"tag": "agent"})
    titles = {p["title"] for p in r.json()["items"]}
    assert titles == {"Agent paper", "Agent vision combo"}


async def test_patch_partial_update(client):
    create = await client.post(
        "/api/knowledge/papers", json={"title": "Original", "summary": "old"}
    )
    pid = create.json()["paper_id"]

    r = await client.patch(
        f"/api/knowledge/papers/{pid}",
        json={"summary": "new summary", "tags": ["t1"]},
    )
    assert r.status_code == 200
    assert r.json()["summary"] == "new summary"
    assert r.json()["tags"] == ["t1"]
    # Title untouched.
    assert r.json()["title"] == "Original"


async def test_delete_paper(client):
    create = await client.post("/api/knowledge/papers", json={"title": "Disposable"})
    pid = create.json()["paper_id"]
    r = await client.delete(f"/api/knowledge/papers/{pid}")
    assert r.status_code == 204
    assert (await client.get(f"/api/knowledge/papers/{pid}")).status_code == 404


# ---------------------------------------------------------------------------
# P13 — manual-CRUD metadata fields (url / field_major / field_minor)
# ---------------------------------------------------------------------------


async def test_create_with_taxonomy_and_url(client):
    """The new fields must flow through ``POST`` end-to-end and be readable
    on the subsequent ``GET``. This is the UI's happy-path."""
    r = await client.post(
        "/api/knowledge/papers",
        json={
            "title": "Self-Refine",
            "url": "https://arxiv.org/abs/2303.17651",
            "field_major": "NLP",
            "field_minor": "LLM-Agent",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["url"] == "https://arxiv.org/abs/2303.17651"
    assert body["field_major"] == "NLP"
    assert body["field_minor"] == "LLM-Agent"


async def test_patch_updates_taxonomy(client):
    """PATCH must accept the new fields and leave others alone."""
    create = await client.post(
        "/api/knowledge/papers",
        json={"title": "Untaxonomied", "url": "https://example.com/v1"},
    )
    pid = create.json()["paper_id"]

    r = await client.patch(
        f"/api/knowledge/papers/{pid}",
        json={"field_major": "Alignment", "field_minor": "RLAIF"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["field_major"] == "Alignment"
    assert body["field_minor"] == "RLAIF"
    # url untouched
    assert body["url"] == "https://example.com/v1"
    # title untouched
    assert body["title"] == "Untaxonomied"


# ---------------------------------------------------------------------------
# Bulk
# ---------------------------------------------------------------------------


async def test_bulk_create(client):
    r = await client.post(
        "/api/knowledge/papers:bulk",
        json={
            "papers": [
                {"title": "Bulk 1"},
                {"title": "Bulk 2", "year": 2025},
                {"title": "Bulk 3", "tags": ["x"]},
            ]
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["created"]) == 3
    assert body["failed"] == []


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------


async def test_attach_typed_link(client):
    a = (await client.post("/api/knowledge/papers", json={"title": "Source"})).json()["paper_id"]
    b = (await client.post("/api/knowledge/papers", json={"title": "Target"})).json()["paper_id"]

    r = await client.post(
        f"/api/knowledge/papers/{a}/links",
        json={"target_paper_id": b, "link_type": "extends", "evidence": "see §3"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert any(
        link["target_paper_id"] == b and link["link_type"] == "extends"
        for link in body["typed_links"]
    )

    # bidirectional default — the inverse appears on the target.
    r = await client.get(f"/api/knowledge/papers/{b}")
    assert any(link["target_paper_id"] == a for link in r.json()["typed_links"])


async def test_attach_link_to_missing_target(client):
    a = (await client.post("/api/knowledge/papers", json={"title": "Source"})).json()["paper_id"]
    r = await client.post(
        f"/api/knowledge/papers/{a}/links",
        json={"target_paper_id": "ghost", "link_type": "extends"},
    )
    # The store raises MemoryNotFound which the router maps to 404.
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Syntheses
# ---------------------------------------------------------------------------


async def test_synthesis_crud(client):
    r = await client.post(
        "/api/knowledge/syntheses",
        json={
            "cluster_tag": "memory-evolution",
            "content": "Cluster summary",
            "summary": "tl;dr",
            "paper_ids": ["p1", "p2"],
        },
    )
    assert r.status_code == 201
    assert r.json()["cluster_tag"] == "memory-evolution"
    assert r.json()["version"] == 1

    # Upsert again — version bumps.
    r = await client.post(
        "/api/knowledge/syntheses",
        json={"cluster_tag": "memory-evolution", "content": "v2 content"},
    )
    assert r.json()["version"] == 2

    r = await client.get("/api/knowledge/syntheses")
    assert r.json()["total"] >= 1

    r = await client.get("/api/knowledge/syntheses/memory-evolution")
    assert r.status_code == 200

    r = await client.delete("/api/knowledge/syntheses/memory-evolution")
    assert r.status_code == 204
    assert (await client.get("/api/knowledge/syntheses/memory-evolution")).status_code == 404


# ---------------------------------------------------------------------------
# Ingest pipeline (M7.1)
# ---------------------------------------------------------------------------


SAMPLE_INGEST_BODY = """# Self-Evolving Agents

Alice, Bob — 2024

## Abstract

We study a class of agents that improve their own behaviour by editing
their long-term memory after each task.

## Introduction

Prior work…
"""


async def test_ingest_paper_via_json_body(client):
    r = await client.post(
        "/api/knowledge/papers/ingest",
        json={
            "title": "Self-Evolving Agents",
            "authors": ["Alice", "Bob"],
            "year": 2024,
            "summary": "Agents that revise their memory.",
            "tags": ["agent", "memory"],
            "source_kind": "manual",
            "trigger_evolution": False,
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["card"]["title"] == "Self-Evolving Agents"
    assert body["card"]["year"] == 2024
    assert body["evolution"]["mode"] == "skip"
    assert body["extracted"]["method"] in {"heuristic", "metadata_only"}

    # The card is now in the regular list endpoint.
    r = await client.get("/api/knowledge/papers")
    titles = [c["title"] for c in r.json()["items"]]
    assert "Self-Evolving Agents" in titles


async def test_ingest_paper_via_multipart_markdown(client):
    files = {"file": ("paper.md", SAMPLE_INGEST_BODY.encode("utf-8"), "text/markdown")}
    data = {
        "tags": "agent,memory",
        "source_kind": "user_upload",
        "trigger_evolution": "false",
    }
    r = await client.post("/api/knowledge/papers/ingest", files=files, data=data)
    assert r.status_code == 201, r.text
    body = r.json()
    # Heuristic title extraction from the markdown H1.
    assert body["card"]["title"] == "Self-Evolving Agents"
    assert "agent" in body["card"]["tags"]
    assert body["extracted"]["method"] == "heuristic"
    assert body["extracted"]["preview"].startswith("# Self-Evolving Agents")


async def test_ingest_rejects_when_neither_file_nor_json(client):
    r = await client.post(
        "/api/knowledge/papers/ingest",
        headers={"content-type": "text/plain"},
        content=b"hi",
    )
    assert r.status_code == 415


async def test_ingest_rejects_empty_upload(client):
    files = {"file": ("empty.md", b"", "text/markdown")}
    r = await client.post("/api/knowledge/papers/ingest", files=files)
    assert r.status_code == 400


async def test_ingest_falls_back_to_filename_when_body_has_no_heading(client):
    # Empty body (no first non-empty line either) → filename stem becomes
    # the title via the extractor's fallback path.
    files = {"file": ("paper.md", b"   \n  \n", "text/markdown")}
    data = {"trigger_evolution": "false"}
    r = await client.post("/api/knowledge/papers/ingest", files=files, data=data)
    assert r.status_code == 201
    assert r.json()["card"]["title"] == "paper"
