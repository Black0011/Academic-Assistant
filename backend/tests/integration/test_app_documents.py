"""Integration tests for the `/api/documents` router (M7.3)."""

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
        yield c, state


SAMPLE_MD = (
    "# Vector databases\n"
    "Vector databases index dense embeddings.\n\n"
    "## Why\nAccelerated retrieval for RAG pipelines.\n\n"
    "## When\nWhen the corpus exceeds RAM but fits a few GBs of disk.\n"
)


async def test_ingest_json_creates_chunks_and_indexes_vectors(client) -> None:
    c, state = client
    r = await c.post(
        "/api/documents/ingest",
        json={
            "title": "Vector databases",
            "raw_text": SAMPLE_MD,
            "source_kind": "note",
            "tags": ["rag"],
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["chunks_indexed"] >= 2
    doc_id = body["document"]["doc_id"]
    assert doc_id

    # Vector store is shared with the bundle — chunks must be there.
    assert state.memory is not None
    vector_count = await state.memory.vector.count()
    assert vector_count >= body["chunks_indexed"]

    # Search returns at least one hit.
    r = await c.post(
        "/api/documents/search",
        json={"q": "rag retrieval", "top_k": 3},
    )
    assert r.status_code == 200
    hits = r.json()["items"]
    assert hits and hits[0]["doc_title"] == "Vector databases"


async def test_ingest_multipart_markdown_file(client) -> None:
    c, _ = client
    files = {"file": ("notes.md", SAMPLE_MD.encode("utf-8"), "text/markdown")}
    r = await c.post(
        "/api/documents/ingest",
        files=files,
        data={"tags": "rag, vector"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["document"]["title"]
    assert body["chunks_indexed"] >= 2


async def test_list_get_chunks_and_pagination(client) -> None:
    c, _ = client
    await c.post("/api/documents/ingest", json={"title": "A", "raw_text": SAMPLE_MD})
    await c.post(
        "/api/documents/ingest",
        json={"title": "B", "raw_text": "# B\nshort body."},
    )
    r = await c.get("/api/documents")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {d["title"] for d in items} == {"A", "B"}

    target = next(d for d in items if d["title"] == "A")
    r = await c.get(f"/api/documents/{target['doc_id']}")
    assert r.status_code == 200
    assert r.json()["title"] == "A"

    r = await c.get(f"/api/documents/{target['doc_id']}/chunks", params={"limit": 1})
    assert r.status_code == 200
    page = r.json()
    assert len(page["items"]) == 1
    assert page["total"] >= 1


async def test_delete_prunes_vector_entries(client) -> None:
    c, state = client
    r = await c.post(
        "/api/documents/ingest",
        json={"title": "Drop me", "raw_text": SAMPLE_MD},
    )
    assert r.status_code == 201
    doc_id = r.json()["document"]["doc_id"]
    indexed = r.json()["chunks_indexed"]

    assert state.memory is not None
    before = await state.memory.vector.count()
    assert before >= indexed

    r = await c.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 204

    after = await state.memory.vector.count()
    assert after == before - indexed

    # Search should no longer hit.
    r = await c.post(
        "/api/documents/search",
        json={"q": "rag retrieval", "top_k": 3},
    )
    items = r.json()["items"]
    assert all(h["doc_id"] != doc_id for h in items)


async def test_reindex_keeps_doc_id_and_refreshes_chunks(client) -> None:
    c, _ = client
    r = await c.post(
        "/api/documents/ingest",
        json={"title": "Steady", "raw_text": SAMPLE_MD},
    )
    doc_id = r.json()["document"]["doc_id"]

    r = await c.post(
        f"/api/documents/{doc_id}:reindex",
        json={"target_tokens": 200, "overlap_tokens": 0},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["document"]["doc_id"] == doc_id
    assert body["chunks_indexed"] >= 1


async def test_ingest_rejects_empty_payload(client) -> None:
    c, _ = client
    r = await c.post(
        "/api/documents/ingest",
        json={"title": "x", "raw_text": "    \n  "},
    )
    assert r.status_code in {400, 422}


# ---------------------------------------------------------------------------
# P14.B — PATCH /api/documents/{doc_id}
# ---------------------------------------------------------------------------


async def _ingest(c, *, title: str = "Edit me", raw_text: str = SAMPLE_MD) -> str:
    r = await c.post("/api/documents/ingest", json={"title": title, "raw_text": raw_text})
    assert r.status_code == 201
    return str(r.json()["document"]["doc_id"])


async def test_patch_document_updates_title(client) -> None:
    c, _ = client
    doc_id = await _ingest(c)
    r = await c.patch(
        f"/api/documents/{doc_id}",
        json={"title": "Renamed"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Renamed"

    # GET reflects the change.
    r = await c.get(f"/api/documents/{doc_id}")
    assert r.json()["title"] == "Renamed"


async def test_patch_document_partial_does_not_clobber_other_fields(client) -> None:
    """Send only ``summary``; tags + source_kind must remain."""
    c, _ = client
    r = await c.post(
        "/api/documents/ingest",
        json={
            "title": "Has tags",
            "raw_text": SAMPLE_MD,
            "tags": ["alpha", "beta"],
            "source_kind": "note",
        },
    )
    doc_id = r.json()["document"]["doc_id"]

    r = await c.patch(
        f"/api/documents/{doc_id}",
        json={"summary": "edited summary"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "edited summary"
    assert sorted(body["tags"]) == ["alpha", "beta"]
    assert body["source_kind"] == "note"


async def test_patch_document_404_for_missing(client) -> None:
    c, _ = client
    r = await c.patch("/api/documents/does-not-exist", json={"title": "x"})
    assert r.status_code == 404


async def test_patch_document_rejects_unknown_fields(client) -> None:
    """``extra="forbid"`` — protects against attempts to mutate
    ``raw_text`` (which would silently desync chunks) or ``doc_id``."""
    c, _ = client
    doc_id = await _ingest(c)
    r = await c.patch(
        f"/api/documents/{doc_id}",
        json={"raw_text": "haha"},
    )
    assert r.status_code == 422


async def test_patch_document_title_change_propagates_to_search_results(client) -> None:
    """Search hits show the NEW title, not the stale one — proves the
    chunk-vector ``doc_title`` denormalisation got refreshed."""
    c, _ = client
    doc_id = await _ingest(c, title="Original")
    await c.patch(f"/api/documents/{doc_id}", json={"title": "Refreshed"})
    r = await c.post("/api/documents/search", json={"q": "rag retrieval", "top_k": 3})
    assert r.status_code == 200
    hits = r.json()["items"]
    matching = [h for h in hits if h["doc_id"] == doc_id]
    assert matching, "PATCH'd document should still be searchable"
    assert all(h["doc_title"] == "Refreshed" for h in matching)
