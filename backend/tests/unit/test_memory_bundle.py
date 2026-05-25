"""MemoryBundle integration + snapshot wiring."""

import pytest

from backend.memory import (
    Heuristic,
    MemoryBundle,
    PaperCard,
    Reflection,
    SessionContext,
    StrategyBlock,
)


@pytest.mark.asyncio
async def test_in_memory_factory_wires_all_five_stores():
    bundle = MemoryBundle.in_memory()
    assert bundle.vector is not None
    assert bundle.knowledge is not None
    assert bundle.heuristic is not None
    assert bundle.episodic is not None
    assert bundle.session is not None


@pytest.mark.asyncio
async def test_snapshot_returns_all_channels_populated():
    bundle = MemoryBundle.in_memory()

    await bundle.knowledge.write_card(
        PaperCard(
            paper_id="p1",
            title="RLHF reward model scaling",
            abstract="Studies of reward model scaling for RLHF alignment",
            source_run_id="run-1",
        )
    )
    await bundle.vector.add("p1", "RLHF reward model scaling paper")
    await bundle.heuristic.add(
        Heuristic(
            id="a" * 12,
            name="rlhf research tip",
            domain="research",
            trigger_pattern="rlhf, reward model",
            strategy=StrategyBlock(planning_hints="start from gap analysis"),
            source_run_id="run-1",
        )
    )
    await bundle.episodic.append(
        Reflection(
            id="r1",
            type="reflection",
            content="Prior session discovered gap in multi-task reward scaling.",
            session_id="sess-1",
        )
    )

    snap = await bundle.snapshot("rlhf reward model", domain="research", session_id="sess-1")
    assert snap.query == "rlhf reward model"
    assert snap.related_papers and snap.related_papers[0].paper_id == "p1"
    assert snap.heuristics and snap.heuristics[0].id == "a" * 12
    assert snap.recent_reflections and snap.recent_reflections[0].id == "r1"
    assert "p1" in snap.vector_summary


@pytest.mark.asyncio
async def test_snapshot_empty_memory_is_safe():
    bundle = MemoryBundle.in_memory()
    snap = await bundle.snapshot("anything", domain="research")
    assert snap.related_papers == []
    assert snap.heuristics == []
    assert snap.recent_reflections == []
    assert snap.vector_summary == ""


@pytest.mark.asyncio
async def test_rollback_across_stores_via_run_id():
    bundle = MemoryBundle.in_memory()
    await bundle.knowledge.write_card(PaperCard(paper_id="p1", title="t", source_run_id="run-1"))
    await bundle.heuristic.add(
        Heuristic(
            id="a" * 12,
            name="h",
            domain="research",
            strategy=StrategyBlock(),
            source_run_id="run-1",
        )
    )
    await bundle.episodic.append(
        Reflection(id="r1", type="reflection", content="x", source_run_id="run-1")
    )

    removed_k = await bundle.knowledge.rollback_run("run-1")
    removed_h = await bundle.heuristic.rollback_run("run-1")
    removed_e = await bundle.episodic.rollback_run("run-1")
    assert (removed_k, removed_h, removed_e) == (1, 1, 1)


@pytest.mark.asyncio
async def test_session_roundtrip():
    bundle = MemoryBundle.in_memory()
    await bundle.session.create(SessionContext(session_id="s1", user_id="u1", title="hi"))
    got = await bundle.session.get("s1")
    assert got is not None
    assert got.user_id == "u1"


# ---------------------------------------------------------------------------
# P10 — recall must never abort a workflow because of a single bad store
# ---------------------------------------------------------------------------


class _ExplodingStore:
    """Drop-in store stub that raises whatever's configured on every call.

    Mimics what we saw in the field: a transient ``BrokenPipeError`` from
    a stale embedder connection escaping into the recall stage.
    """

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc

    async def summary_for(self, query, *, k=5, max_chars=1000):
        raise self._exc

    async def find_related(self, query, *, k=5):
        raise self._exc

    async def match(self, query, *, domain=None, top_k=3):
        raise self._exc

    async def recent(self, *, n=3, type=None, session_id=None, user_id=None):
        raise self._exc

    async def search_chunks(self, query, *, k=5, where=None):
        raise self._exc


@pytest.mark.asyncio
async def test_snapshot_swallows_per_leg_failures_and_returns_empty():
    """All five stores raising must still produce a usable snapshot —
    callers (recall stage) treat empty signals as 'no recall available'
    rather than 'abort the task'."""

    boom = BrokenPipeError(32, "Broken pipe")
    bundle = MemoryBundle(
        vector=_ExplodingStore(boom),
        knowledge=_ExplodingStore(boom),
        heuristic=_ExplodingStore(boom),
        episodic=_ExplodingStore(boom),
        session=None,
        documents=_ExplodingStore(boom),
    )

    snap = await bundle.snapshot("anything", domain="research")
    assert snap.query == "anything"
    assert snap.vector_summary == ""
    assert snap.related_papers == []
    assert snap.heuristics == []
    assert snap.recent_reflections == []
    assert snap.doc_chunks == []


@pytest.mark.asyncio
async def test_snapshot_partial_failure_keeps_healthy_legs():
    """Only the broken store should drop out — healthy stores still
    contribute their signals to the snapshot."""

    bundle = MemoryBundle.in_memory()
    await bundle.knowledge.write_card(
        PaperCard(paper_id="p1", title="alignment paper", source_run_id="r1")
    )
    # Sabotage just the vector store.
    bundle.vector = _ExplodingStore(RuntimeError("vector down"))

    snap = await bundle.snapshot("alignment", domain="research")
    assert snap.vector_summary == ""  # leg failed silently
    assert snap.related_papers and snap.related_papers[0].paper_id == "p1"
