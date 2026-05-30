import pytest

from backend.core.errors import MemoryNotFound
from backend.memory import InMemorySessionStore, SessionContext, SessionMessage


def _s(session_id: str = "s1", user_id: str = "u1", **kw) -> SessionContext:
    return SessionContext(session_id=session_id, user_id=user_id, **kw)


@pytest.mark.asyncio
async def test_create_and_get():
    store = InMemorySessionStore()
    s = _s()
    await store.create(s)
    assert (await store.get("s1")) is not None


@pytest.mark.asyncio
async def test_update_shallow_merges_state():
    store = InMemorySessionStore()
    await store.create(_s(state={"a": 1}))
    updated = await store.update("s1", state={"b": 2})
    assert updated.state == {"a": 1, "b": 2}


@pytest.mark.asyncio
async def test_update_replaces_title():
    store = InMemorySessionStore()
    await store.create(_s(title="old"))
    updated = await store.update("s1", title="new")
    assert updated.title == "new"


@pytest.mark.asyncio
async def test_append_message_updates_and_orders():
    store = InMemorySessionStore()
    await store.create(_s())
    await store.append_message("s1", SessionMessage(role="user", content="hi"))
    await store.append_message("s1", SessionMessage(role="assistant", content="hello"))
    s = await store.get("s1")
    assert s is not None
    assert [m.role for m in s.messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_append_message_on_missing_raises():
    store = InMemorySessionStore()
    with pytest.raises(MemoryNotFound):
        await store.append_message("ghost", SessionMessage(role="user", content="x"))


@pytest.mark.asyncio
async def test_update_missing_raises():
    store = InMemorySessionStore()
    with pytest.raises(MemoryNotFound):
        await store.update("ghost", title="y")


@pytest.mark.asyncio
async def test_list_for_user_sorted_by_recency():
    store = InMemorySessionStore()
    await store.create(_s("a", user_id="u1", title="old"))
    await store.create(_s("b", user_id="u1", title="newer"))
    await store.update("b", title="newer-2")
    sessions = await store.list_for_user("u1")
    assert next(s.session_id for s in sessions) == "b"


@pytest.mark.asyncio
async def test_delete_returns_true_only_first_time():
    store = InMemorySessionStore()
    await store.create(_s())
    assert await store.delete("s1") is True
    assert await store.delete("s1") is False
