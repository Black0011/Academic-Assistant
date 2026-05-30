"""MemoryBundle.snapshot must merge PaperCard + DocChunk results (M7.3)."""

from __future__ import annotations

import pytest

from backend.memory.base import MemoryBundle
from backend.memory.chunker import chunk_markdown
from backend.memory.document_store import make_chunk_id
from backend.memory.models import DocChunk, KnowledgeDocument, PaperCard


@pytest.mark.asyncio
async def test_snapshot_returns_doc_chunks_alongside_papers() -> None:
    bundle = MemoryBundle.in_memory()
    assert bundle.documents is not None

    # Seed a PaperCard.
    await bundle.knowledge.write_card(
        PaperCard(
            paper_id="p1",
            title="Long-context language models",
            abstract="A study on extending context windows in transformers.",
            tags=["transformer", "context"],
        )
    )

    # Ingest one document about transformers — chunks land in the same vector store.
    text = (
        "# Transformer cookbook\n"
        "Transformers attend over long contexts using self-attention.\n\n"
        "## Speed\nFlashAttention reduces memory pressure.\n"
    )
    raw_chunks = chunk_markdown(text, target_tokens=200)
    chunks = [
        DocChunk(
            chunk_id=make_chunk_id("d1", idx),
            doc_id="d1",
            idx=idx,
            text=raw.text,
            char_offset_start=raw.char_offset_start,
            char_offset_end=raw.char_offset_end,
            section_path=list(raw.section_path),
        )
        for idx, raw in enumerate(raw_chunks)
    ]
    doc = KnowledgeDocument(
        doc_id="d1",
        title="Transformer cookbook",
        source_kind="md_upload",
        raw_text=text,
        chunk_ids=[c.chunk_id for c in chunks],
        bytes=len(text.encode("utf-8")),
        tags=["transformer"],
    )
    await bundle.documents.write(doc, chunks)

    snap = await bundle.snapshot("transformers context", k=5)
    assert snap.related_papers and snap.related_papers[0].paper_id == "p1"
    assert snap.doc_chunks
    flat = snap.doc_chunks_text(max_chars=400)
    assert "Transformer cookbook" in flat


@pytest.mark.asyncio
async def test_snapshot_no_documents_keeps_empty_doc_chunks() -> None:
    bundle = MemoryBundle.in_memory()
    snap = await bundle.snapshot("anything")
    assert snap.doc_chunks == []
    assert snap.doc_chunks_text() == ""
