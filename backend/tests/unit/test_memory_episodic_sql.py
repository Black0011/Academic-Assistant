"""SqlEpisodicStore — async SQLAlchemy backend smoke tests.

Runs against `sqlite+aiosqlite:///:memory:` so the suite stays hermetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from backend.memory import Reflection, SqlEpisodicStore


@pytest.fixture
async def store():
    s = SqlEpisodicStore.from_url("sqlite+aiosqlite:///:memory:")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


def _r(**overrides) -> Reflection:
    base = {
        "id": overrides.pop("id", "r-1"),
        "type": overrides.pop("type", "reflection"),
        "content": overrides.pop("content", "hello"),
        "tags": overrides.pop("tags", []),
        "user_id": overrides.pop("user_id", None),
        "session_id": overrides.pop("session_id", None),
        "source_run_id": overrides.pop("source_run_id", None),
        "created_at": overrides.pop("created_at", datetime.now(UTC)),
    }
    base.update(overrides)
    return Reflection(**base)


async def test_append_and_recent_orders_desc(store):
    older = _r(id="a", content="older", created_at=datetime.now(UTC) - timedelta(hours=1))
    newer = _r(id="b", content="newer", created_at=datetime.now(UTC))
    await store.append(older)
    await store.append(newer)
    out = await store.recent(n=5)
    assert [r.id for r in out] == ["b", "a"]


async def test_recent_respects_filters(store):
    await store.append(_r(id="a", session_id="s1", user_id="u1"))
    await store.append(_r(id="b", session_id="s2", user_id="u1"))
    await store.append(_r(id="c", session_id="s1", user_id="u2", type="insight"))

    by_session = await store.recent(session_id="s1")
    assert {r.id for r in by_session} == {"a", "c"}

    by_user = await store.recent(user_id="u1")
    assert {r.id for r in by_user} == {"a", "b"}

    by_type = await store.recent(type="insight")
    assert [r.id for r in by_type] == ["c"]


async def test_recent_limit_zero_returns_empty(store):
    await store.append(_r(id="a"))
    assert await store.recent(n=0) == []


async def test_rollback_run_deletes_matching(store):
    await store.append(_r(id="a", source_run_id="run-1"))
    await store.append(_r(id="b", source_run_id="run-1"))
    await store.append(_r(id="c", source_run_id="run-2"))
    removed = await store.rollback_run("run-1")
    assert removed == 2
    remaining = await store.recent(n=10)
    assert [r.id for r in remaining] == ["c"]


async def test_count_and_clear(store):
    for i in range(3):
        await store.append(_r(id=f"r{i}"))
    assert await store.count() == 3
    await store.clear()
    assert await store.count() == 0


async def test_tags_roundtrip(store):
    await store.append(_r(id="a", tags=["alpha", "beta"]))
    out = await store.recent(n=1)
    assert out[0].tags == ["alpha", "beta"]


# ---------------------------------------------------------------------------
# P14.A — manual CRUD: SQL parity with the in-memory store. The unit suite
# in ``test_memory_episodic_store.py`` pins behaviour; this suite pins SQL
# parity (so a subtle session/transaction bug doesn't sneak past).
# ---------------------------------------------------------------------------


async def test_get_and_update_partial(store):
    await store.append(_r(id="a", content="orig", tags=["x"]))
    out = await store.update("a", content="rewritten")
    assert out is not None and out.content == "rewritten"
    assert out.tags == ["x"]  # tags untouched

    fetched = await store.get("a")
    assert fetched is not None and fetched.content == "rewritten"


async def test_update_returns_none_for_missing(store):
    assert (await store.update("nope", content="x")) is None


async def test_update_does_not_change_provenance(store):
    await store.append(
        _r(id="a", user_id="u1", session_id="s1", source_run_id="run-a")
    )
    out = await store.update("a", content="rewritten")
    assert out is not None
    assert out.user_id == "u1"
    assert out.session_id == "s1"
    assert out.source_run_id == "run-a"


async def test_delete_returns_correct_bool(store):
    await store.append(_r(id="a"))
    assert (await store.delete("a")) is True
    assert (await store.delete("a")) is False


async def test_delete_by_session_and_run(store):
    await store.append(_r(id="a", session_id="s1", source_run_id="run-a"))
    await store.append(_r(id="b", session_id="s1", source_run_id="run-b"))
    await store.append(_r(id="c", session_id="s2", source_run_id="run-a"))

    n = await store.delete_by(session_id="s1")
    assert n == 2
    remaining = await store.recent(n=10)
    assert [r.id for r in remaining] == ["c"]


async def test_delete_by_combines_facets_with_and_semantics(store):
    await store.append(_r(id="a", session_id="s1", source_run_id="run-a"))
    await store.append(_r(id="b", session_id="s1", source_run_id="run-b"))
    n = await store.delete_by(session_id="s1", source_run_id="run-a")
    assert n == 1
    remaining = await store.recent(n=10)
    assert {r.id for r in remaining} == {"b"}


async def test_delete_by_no_filter_is_noop(store):
    await store.append(_r(id="a"))
    n = await store.delete_by()
    assert n == 0
    assert await store.count() == 1
