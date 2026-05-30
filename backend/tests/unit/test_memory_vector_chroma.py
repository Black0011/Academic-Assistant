"""ChromaVectorStore — skipped on platforms missing chromadb wheels.

These tests run only when the ``memory`` extra is installed. We use an
ephemeral client so nothing lands on disk.
"""

from __future__ import annotations

import pytest

chromadb = pytest.importorskip("chromadb")

from backend.memory.models import VectorHit
from backend.memory.vector_chroma import ChromaVectorStore


class _StaticEmbedder:
    """Deterministic embedder: each term gets a fixed one-hot coordinate."""

    def __init__(self) -> None:
        self._vocab: dict[str, int] = {}

    async def embed(self, texts, *, model=None):
        vecs = []
        for t in texts:
            vec = [0.0] * 32
            for token in t.lower().split():
                idx = self._vocab.setdefault(token, len(self._vocab) % 32)
                vec[idx] = 1.0
            vecs.append(vec)
        return vecs


@pytest.fixture
def store():
    return ChromaVectorStore(collection_name="aaf_test", embedder=_StaticEmbedder())


async def test_add_get_count_roundtrip(store):
    await store.add("p1", "gene therapy acne", metadata={"tag": "derm"})
    assert await store.count() == 1
    hit = await store.get("p1")
    assert isinstance(hit, VectorHit)
    assert hit.doc_id == "p1"
    assert hit.metadata.get("tag") == "derm"


async def test_query_returns_sorted_hits_by_similarity(store):
    await store.add("p1", "gene therapy acne", metadata={"tag": "derm"})
    await store.add("p2", "reinforcement learning robotics", metadata={"tag": "rl"})
    hits = await store.query("acne therapy", k=2)
    assert next(h.doc_id for h in hits) == "p1"


async def test_query_where_filter_narrows_results(store):
    await store.add("p1", "gene therapy acne", metadata={"tag": "derm"})
    await store.add("p2", "gene therapy oncology", metadata={"tag": "onco"})
    hits = await store.query("gene therapy", k=5, where={"tag": "onco"})
    assert [h.doc_id for h in hits] == ["p2"]


async def test_delete_returns_false_when_missing(store):
    assert await store.delete("nope") is False
    await store.add("p1", "something", metadata={})
    assert await store.delete("p1") is True
    assert await store.count() == 0


async def test_summary_for_truncates_and_joins(store):
    for i in range(3):
        await store.add(f"p{i}", f"acne paper {i}" * 20, metadata={})
    summary = await store.summary_for("acne paper", k=3, max_chars=60)
    assert len(summary) <= 80  # allow for the ellipsis/joiner
    assert "acne paper" in summary


async def test_set_embedder_wipes_collection(store):
    await store.add("p1", "x", metadata={})
    assert await store.count() == 1
    store.set_embedder(_StaticEmbedder())
    assert await store.count() == 0


async def test_query_without_embedder_returns_empty():
    s = ChromaVectorStore(collection_name="aaf_test_noemb", embedder=None)
    await s.add("p1", "anything", metadata={})
    assert await s.query("anything", k=3) == []
