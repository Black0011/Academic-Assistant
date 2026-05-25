"""RedisSessionStore — uses fakeredis for hermetic tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from backend.core.errors import MemoryNotFound
from backend.memory import RedisSessionStore, SessionContext, SessionMessage

fakeredis = pytest.importorskip("fakeredis")


@pytest.fixture
async def client():
    c = fakeredis.aioredis.FakeRedis()
    try:
        yield c
    finally:
        await c.aclose()


@pytest.fixture
def store(client):
    return RedisSessionStore(client)


def _ctx(**overrides) -> SessionContext:
    data = {
        "session_id": overrides.pop("session_id", "s1"),
        "user_id": overrides.pop("user_id", "u1"),
        "title": overrides.pop("title", ""),
        "state": overrides.pop("state", {}),
        "messages": overrides.pop("messages", []),
        "created_at": overrides.pop("created_at", datetime.now(UTC)),
        "updated_at": overrides.pop("updated_at", datetime.now(UTC)),
    }
    data.update(overrides)
    return SessionContext(**data)


async def test_create_then_get_roundtrip(store):
    ctx = _ctx(state={"mode": "research"})
    await store.create(ctx)
    loaded = await store.get("s1")
    assert loaded is not None
    assert loaded.user_id == "u1"
    assert loaded.state == {"mode": "research"}


async def test_get_missing_returns_none(store):
    assert await store.get("nope") is None


async def test_update_merges_state_and_bumps_timestamp(store):
    await store.create(_ctx(state={"mode": "research"}))
    updated = await store.update("s1", state={"step": 2}, title="new")
    assert updated.state == {"mode": "research", "step": 2}
    assert updated.title == "new"
    assert updated.updated_at >= updated.created_at


async def test_update_missing_raises(store):
    with pytest.raises(MemoryNotFound):
        await store.update("ghost", title="x")


async def test_append_message_persists_and_bumps(store):
    await store.create(_ctx())
    msg = SessionMessage(role="user", content="hi")
    await store.append_message("s1", msg)
    again = await store.get("s1")
    assert len(again.messages) == 1
    assert again.messages[0].content == "hi"


async def test_append_message_missing_raises(store):
    with pytest.raises(MemoryNotFound):
        await store.append_message("ghost", SessionMessage(role="user", content="hi"))


async def test_delete_removes_and_updates_user_index(store):
    await store.create(_ctx(session_id="s1", user_id="u1"))
    await store.create(_ctx(session_id="s2", user_id="u1"))
    assert await store.delete("s1") is True
    assert await store.delete("s1") is False  # idempotent second call
    remaining = await store.list_for_user("u1")
    assert [s.session_id for s in remaining] == ["s2"]


async def test_list_for_user_sorted_by_recency(store):
    now = datetime.now(UTC)
    await store.create(_ctx(session_id="a", updated_at=now - timedelta(minutes=5)))
    await store.create(_ctx(session_id="b", updated_at=now))
    sessions = await store.list_for_user("u1")
    assert [s.session_id for s in sessions] == ["b", "a"]


async def test_namespace_isolates_stores(client):
    a = RedisSessionStore(client, namespace="tenantA")
    b = RedisSessionStore(client, namespace="tenantB")
    await a.create(_ctx(session_id="s", user_id="u"))
    assert await b.get("s") is None
    assert (await a.get("s")).session_id == "s"
