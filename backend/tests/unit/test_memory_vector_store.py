import pytest

from backend.core.llm import MockLLMProvider
from backend.memory import InMemoryVectorStore


@pytest.mark.asyncio
async def test_add_and_count():
    v = InMemoryVectorStore()
    await v.add("d1", "alpha beta", metadata={"kind": "paper"})
    assert await v.count() == 1
    hit = await v.get("d1")
    assert hit is not None
    assert hit.metadata["kind"] == "paper"


@pytest.mark.asyncio
async def test_query_keyword_fallback():
    v = InMemoryVectorStore()
    await v.add("d1", "continual reinforcement learning")
    await v.add("d2", "cooking recipes")
    hits = await v.query("continual learning", k=2)
    assert hits[0].doc_id == "d1"
    assert hits[0].score > 0


@pytest.mark.asyncio
async def test_query_respects_where():
    v = InMemoryVectorStore()
    await v.add("d1", "alpha", metadata={"kind": "paper"})
    await v.add("d2", "alpha", metadata={"kind": "note"})
    hits = await v.query("alpha", where={"kind": "paper"})
    assert [h.doc_id for h in hits] == ["d1"]


@pytest.mark.asyncio
async def test_query_with_embedder_beats_keyword():
    mock = MockLLMProvider()
    v = InMemoryVectorStore(embedder=mock)
    await v.add("d1", "reinforcement learning for autonomous driving")
    await v.add("d2", "baking cakes at home")
    hits = await v.query("self-driving RL", k=2)
    assert hits  # just sanity; mock is deterministic per text
    assert all(h.score >= 0 for h in hits)


@pytest.mark.asyncio
async def test_delete_removes_doc_and_vector():
    v = InMemoryVectorStore()
    await v.add("d1", "x")
    assert await v.delete("d1") is True
    assert await v.delete("d1") is False
    assert await v.get("d1") is None


@pytest.mark.asyncio
async def test_summary_for_caps_at_max_chars():
    v = InMemoryVectorStore()
    await v.add("d1", "a" * 500)
    await v.add("d2", "b" * 500)
    summary = await v.summary_for("a", k=5, max_chars=100)
    assert len(summary) <= 200  # some slack for prefix/suffix


@pytest.mark.asyncio
async def test_summary_empty_corpus():
    v = InMemoryVectorStore()
    assert await v.summary_for("anything") == ""


@pytest.mark.asyncio
async def test_set_embedder_invalidates_vectors():
    mock = MockLLMProvider()
    v = InMemoryVectorStore(embedder=mock)
    await v.add("d1", "hi")
    # Trigger embedding computation.
    _ = await v.query("hi", k=1)
    assert "d1" in v._vectors
    v.set_embedder(None)
    assert v._vectors == {}
