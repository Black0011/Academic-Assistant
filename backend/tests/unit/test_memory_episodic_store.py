from datetime import UTC, datetime, timedelta

import pytest

from backend.memory import InMemoryEpisodicStore, Reflection


def _r(id_: str, *, offset_minutes: int = 0, **kw) -> Reflection:
    base = datetime(2026, 4, 1, tzinfo=UTC)
    return Reflection(
        id=id_,
        created_at=base + timedelta(minutes=offset_minutes),
        content=kw.pop("content", f"content-{id_}"),
        **kw,
    )


@pytest.mark.asyncio
async def test_append_and_count():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1"))
    await s.append(_r("r2"))
    assert await s.count() == 2


@pytest.mark.asyncio
async def test_recent_orders_desc_and_caps_n():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", offset_minutes=0))
    await s.append(_r("r2", offset_minutes=10))
    await s.append(_r("r3", offset_minutes=5))
    recent = await s.recent(n=2)
    assert [r.id for r in recent] == ["r2", "r3"]


@pytest.mark.asyncio
async def test_recent_filters_by_type():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", type="reflection"))
    await s.append(_r("r2", type="observation"))
    await s.append(_r("r3", type="reflection"))
    out = await s.recent(n=10, type="reflection")
    assert {r.id for r in out} == {"r1", "r3"}


@pytest.mark.asyncio
async def test_recent_filters_by_session_and_user():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", session_id="s1", user_id="u1"))
    await s.append(_r("r2", session_id="s2", user_id="u1"))
    await s.append(_r("r3", session_id="s1", user_id="u2"))
    assert {r.id for r in await s.recent(n=10, session_id="s1")} == {"r1", "r3"}
    assert {r.id for r in await s.recent(n=10, user_id="u1")} == {"r1", "r2"}


@pytest.mark.asyncio
async def test_rollback_run_removes_matching():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", source_run_id="run-a"))
    await s.append(_r("r2", source_run_id="run-b"))
    removed = await s.rollback_run("run-a")
    assert removed == 1
    assert (await s.count()) == 1


@pytest.mark.asyncio
async def test_clear_empties_the_store():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1"))
    await s.clear()
    assert (await s.count()) == 0


# ---------------------------------------------------------------------------
# P14.A — manual CRUD: get / update / delete / delete_by
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_returns_none_for_missing_id():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1"))
    assert (await s.get("does-not-exist")) is None
    got = await s.get("r1")
    assert got is not None and got.id == "r1"


@pytest.mark.asyncio
async def test_update_partial_only_changes_supplied_fields():
    """``None`` for a field means "leave it alone" — pin that contract so
    a future refactor doesn't accidentally clobber tags when the caller
    only meant to edit content."""
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", type="reflection", tags=["a", "b"]))
    out = await s.update("r1", content="rewritten")
    assert out is not None
    assert out.content == "rewritten"
    assert out.type == "reflection"
    assert out.tags == ["a", "b"]


@pytest.mark.asyncio
async def test_update_replaces_tags_wholesale_when_supplied():
    """Tags are list-replace semantics, not list-append. The HTTP layer
    decides how to merge; the store stays dumb."""
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", tags=["a", "b"]))
    out = await s.update("r1", tags=["c"])
    assert out is not None and out.tags == ["c"]


@pytest.mark.asyncio
async def test_update_returns_none_for_missing_id():
    s = InMemoryEpisodicStore()
    assert (await s.update("nope", content="x")) is None


@pytest.mark.asyncio
async def test_update_does_not_change_provenance_fields():
    """user_id / session_id / source_run_id / id / created_at must NEVER
    move through this path — they're provenance markers used by the
    rollback + session timeline views."""
    s = InMemoryEpisodicStore()
    original = _r(
        "r1",
        type="reflection",
        user_id="u1",
        session_id="s1",
        source_run_id="run-a",
    )
    await s.append(original)
    out = await s.update("r1", content="x")
    assert out is not None
    assert out.user_id == "u1"
    assert out.session_id == "s1"
    assert out.source_run_id == "run-a"
    assert out.created_at == original.created_at


@pytest.mark.asyncio
async def test_delete_returns_true_only_when_row_existed():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1"))
    assert (await s.delete("r1")) is True
    assert (await s.delete("r1")) is False
    assert (await s.count()) == 0


@pytest.mark.asyncio
async def test_delete_by_session_filters_correctly():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", session_id="s1"))
    await s.append(_r("r2", session_id="s2"))
    await s.append(_r("r3", session_id="s1"))
    n = await s.delete_by(session_id="s1")
    assert n == 2
    remaining = {r.id for r in await s.recent(n=10)}
    assert remaining == {"r2"}


@pytest.mark.asyncio
async def test_delete_by_run_filters_correctly():
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", source_run_id="run-a"))
    await s.append(_r("r2", source_run_id="run-b"))
    n = await s.delete_by(source_run_id="run-a")
    assert n == 1


@pytest.mark.asyncio
async def test_delete_by_combines_facets_with_and_semantics():
    """Both filters supplied ⇒ only rows that match BOTH are removed.
    This is the safe default — you'd never want OR semantics here, since
    delete_by(session_id="s1", source_run_id="run-X") might unexpectedly
    nuke the entire session."""
    s = InMemoryEpisodicStore()
    await s.append(_r("r1", session_id="s1", source_run_id="run-a"))
    await s.append(_r("r2", session_id="s1", source_run_id="run-b"))
    await s.append(_r("r3", session_id="s2", source_run_id="run-a"))
    n = await s.delete_by(session_id="s1", source_run_id="run-a")
    assert n == 1
    remaining = {r.id for r in await s.recent(n=10)}
    assert remaining == {"r2", "r3"}


@pytest.mark.asyncio
async def test_delete_by_with_no_filters_is_a_noop():
    """Refuse the unbounded delete — only ``clear()`` (test helper) wipes
    everything. The HTTP layer gives 400 instead, this layer just shrugs."""
    s = InMemoryEpisodicStore()
    await s.append(_r("r1"))
    n = await s.delete_by()
    assert n == 0
    assert (await s.count()) == 1
