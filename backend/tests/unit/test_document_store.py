"""Unit tests for InMemoryDocumentStore + YamlDocumentStore (M7.3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.memory.chunker import chunk_markdown
from backend.memory.document_store import (
    InMemoryDocumentStore,
    YamlDocumentStore,
    make_chunk_id,
)
from backend.memory.models import DocChunk, KnowledgeDocument
from backend.memory.vector_store import InMemoryVectorStore

SAMPLE_TEXT = (
    "# Embeddings primer\n"
    "Embeddings map text to dense vectors.\n\n"
    "## Use cases\n"
    "Search, classification, and clustering.\n"
)


def _build_doc(
    *, doc_id: str = "d-test", run_id: str | None = None
) -> tuple[KnowledgeDocument, list[DocChunk]]:
    raw_chunks = chunk_markdown(SAMPLE_TEXT, target_tokens=200)
    chunks = [
        DocChunk(
            chunk_id=make_chunk_id(doc_id, idx),
            doc_id=doc_id,
            idx=idx,
            text=raw.text,
            char_offset_start=raw.char_offset_start,
            char_offset_end=raw.char_offset_end,
            section_path=list(raw.section_path),
        )
        for idx, raw in enumerate(raw_chunks)
    ]
    document = KnowledgeDocument(
        doc_id=doc_id,
        title="Embeddings primer",
        source_kind="md_upload",
        raw_text=SAMPLE_TEXT,
        tags=["rag", "memory"],
        chunk_ids=[c.chunk_id for c in chunks],
        bytes=len(SAMPLE_TEXT.encode("utf-8")),
        source_run_id=run_id,
    )
    return document, chunks


# ---------------------------------------------------------------------------
# In-memory impl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_write_and_search_round_trip() -> None:
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)

    doc, chunks = _build_doc()
    await store.write(doc, chunks)

    fetched = await store.get("d-test")
    assert fetched is not None
    assert fetched.title == "Embeddings primer"
    assert (await store.get_chunks("d-test"))[0].section_path == ["Embeddings primer"]
    # Vector store has one entry per chunk and they are tagged kind=doc_chunk.
    assert await vector.count() == len(chunks)

    hits = await store.search_chunks("embeddings vector", k=2)
    assert hits and hits[0].doc_title == "Embeddings primer"


@pytest.mark.asyncio
async def test_in_memory_delete_prunes_vector_entries() -> None:
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)

    doc, chunks = _build_doc()
    await store.write(doc, chunks)
    assert await vector.count() == len(chunks)

    assert await store.delete("d-test") is True
    assert await store.get("d-test") is None
    assert await vector.count() == 0


@pytest.mark.asyncio
async def test_in_memory_reindex_replaces_old_chunks() -> None:
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)

    doc, chunks = _build_doc()
    await store.write(doc, chunks)
    first = await vector.count()

    # Re-write with FEWER chunks → vector store must shrink.
    smaller = chunks[:1]
    doc2 = doc.model_copy(update={"chunk_ids": [smaller[0].chunk_id]})
    await store.write(doc2, smaller)
    second = await vector.count()
    assert second < first
    assert second == 1


@pytest.mark.asyncio
async def test_in_memory_rollback_run_clears_documents_and_vectors() -> None:
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)

    doc_a, chunks_a = _build_doc(doc_id="d-a", run_id="run-1")
    doc_b, chunks_b = _build_doc(doc_id="d-b", run_id="run-2")
    await store.write(doc_a, chunks_a)
    await store.write(doc_b, chunks_b)
    total = await vector.count()
    assert total == len(chunks_a) + len(chunks_b)

    removed = await store.rollback_run("run-1")
    assert removed == 1
    assert await store.get("d-a") is None
    assert await store.get("d-b") is not None
    assert await vector.count() == len(chunks_b)


# ---------------------------------------------------------------------------
# YAML impl
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_yaml_round_trip(tmp_path: Path) -> None:
    vector = InMemoryVectorStore()
    store = YamlDocumentStore(tmp_path, vector=vector)

    doc, chunks = _build_doc()
    await store.write(doc, chunks)

    # Files should appear on disk (atomic write completes).
    doc_dir = tmp_path / "d-test"
    assert (doc_dir / "document.yaml").exists()
    assert (doc_dir / "chunks.yaml").exists()

    fetched = await store.get("d-test")
    assert fetched is not None
    assert fetched.title == "Embeddings primer"
    chunks_back = await store.get_chunks("d-test")
    assert len(chunks_back) == len(chunks)


@pytest.mark.asyncio
async def test_yaml_delete_prunes_dir_and_vectors(tmp_path: Path) -> None:
    vector = InMemoryVectorStore()
    store = YamlDocumentStore(tmp_path, vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)
    assert await vector.count() == len(chunks)

    assert await store.delete("d-test") is True
    assert not (tmp_path / "d-test").exists()
    assert await vector.count() == 0


@pytest.mark.asyncio
async def test_yaml_list_filters_underscored_dirs(tmp_path: Path) -> None:
    vector = InMemoryVectorStore()
    store = YamlDocumentStore(tmp_path, vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)
    # Reserved-prefix directories should be ignored.
    (tmp_path / "_disabled").mkdir()
    (tmp_path / ".cache").mkdir()
    docs = await store.list_all()
    assert {d.doc_id for d in docs} == {"d-test"}


# ---------------------------------------------------------------------------
# P14.B — update_metadata: partial edits, no re-chunk, vector cascade
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_update_metadata_partial() -> None:
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)

    out = await store.update_metadata("d-test", title="New title")
    assert out is not None
    assert out.title == "New title"
    # Untouched fields stay put.
    assert out.summary == doc.summary
    assert out.tags == doc.tags
    assert out.source_kind == doc.source_kind


@pytest.mark.asyncio
async def test_in_memory_update_metadata_returns_none_for_missing() -> None:
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)
    assert (await store.update_metadata("nope", title="x")) is None


@pytest.mark.asyncio
async def test_in_memory_update_metadata_does_not_touch_raw_text() -> None:
    """Pin the contract: raw_text and chunk_ids are NEVER mutated by the
    metadata edit path. If you want to rewrite the body, go through
    write/reindex (which re-embeds)."""
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)
    pre_count = await vector.count()
    pre_raw = (await store.get("d-test")).raw_text  # type: ignore[union-attr]

    await store.update_metadata("d-test", title="Renamed", tags=["fresh"])

    post = await store.get("d-test")
    assert post is not None
    assert post.raw_text == pre_raw
    assert post.chunk_ids == doc.chunk_ids
    # Vector entry count unchanged: chunks are re-emitted (overwrite),
    # not added on top.
    assert await vector.count() == pre_count


@pytest.mark.asyncio
async def test_in_memory_update_metadata_refreshes_vector_doc_title() -> None:
    """When title changes, the chunk-level ``doc_title`` denormalisation
    must follow — otherwise search_chunks would render stale labels."""
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)

    await store.update_metadata("d-test", title="Renamed primer")
    hits = await store.search_chunks("embeddings", k=2)
    assert hits and hits[0].doc_title == "Renamed primer"


@pytest.mark.asyncio
async def test_in_memory_update_metadata_summary_only_skips_vector_rewrite(
    monkeypatch,
) -> None:
    """Editing only ``summary`` should not trigger vector re-emit
    (summary is not denormalised into chunk metadata). This is a
    guard rail against the cheap-edit path becoming O(N chunks)
    accidentally."""
    vector = InMemoryVectorStore()
    store = InMemoryDocumentStore(vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)

    # Spy: count vector.add calls during the edit.
    add_calls = 0
    real_add = vector.add

    async def counting_add(*args, **kwargs):
        nonlocal add_calls
        add_calls += 1
        return await real_add(*args, **kwargs)

    monkeypatch.setattr(vector, "add", counting_add)
    await store.update_metadata("d-test", summary="brand new summary")
    assert add_calls == 0


@pytest.mark.asyncio
async def test_yaml_update_metadata_persists_atomically(tmp_path: Path) -> None:
    vector = InMemoryVectorStore()
    store = YamlDocumentStore(tmp_path, vector=vector)
    doc, chunks = _build_doc()
    await store.write(doc, chunks)

    await store.update_metadata("d-test", title="Disk-renamed", tags=["x"])

    # Re-instantiate the store (simulates restart) — the change must
    # have been flushed, not just held in memory.
    store2 = YamlDocumentStore(tmp_path, vector=vector)
    fetched = await store2.get("d-test")
    assert fetched is not None
    assert fetched.title == "Disk-renamed"
    assert fetched.tags == ["x"]


@pytest.mark.asyncio
async def test_yaml_update_metadata_returns_none_for_missing(tmp_path: Path) -> None:
    vector = InMemoryVectorStore()
    store = YamlDocumentStore(tmp_path, vector=vector)
    assert (await store.update_metadata("nope", title="x")) is None
