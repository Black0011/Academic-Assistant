"""Unit tests for `InMemoryTaskStore` + `SqlTaskStore`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from backend.core.events import Event
from backend.tasks.models import TaskRecord
from backend.tasks.sql_store import SqlTaskStore
from backend.tasks.store import InMemoryTaskStore


def _rec(**overrides: Any) -> TaskRecord:
    base: dict[str, Any] = {
        "id": uuid.uuid4().hex[:12],
        "workflow": "demo",
        "query": "hello",
        "input": {"k": 1},
        "user_id": "u1",
    }
    base.update(overrides)
    return TaskRecord(**base)


@pytest.fixture(params=["memory", "sql"])
async def store(request):
    if request.param == "memory":
        s = InMemoryTaskStore()
    else:
        s = SqlTaskStore.from_url("sqlite+aiosqlite:///:memory:")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


async def test_create_and_get(store):
    rec = _rec()
    saved = await store.create(rec)
    assert saved.id == rec.id
    got = await store.get(rec.id)
    assert got is not None
    assert got.workflow == "demo"
    assert got.status == "queued"


async def test_create_auto_id(store):
    rec = TaskRecord(id="", workflow="demo")
    saved = await store.create(rec)
    assert saved.id
    assert await store.get(saved.id) is not None


async def test_get_missing_returns_none(store):
    assert await store.get("nope") is None


async def test_mark_started_then_completed(store):
    rec = await store.create(_rec())
    await store.mark_started(rec.id)
    mid = await store.get(rec.id)
    assert mid is not None
    assert mid.status == "running"
    assert mid.started_at is not None

    await store.mark_completed(
        rec.id, status="ok", result={"answer": 42}, budget={"max_cost_usd": 1.0}
    )
    final = await store.get(rec.id)
    assert final is not None
    assert final.status == "ok"
    assert final.result == {"answer": 42}
    assert final.budget == {"max_cost_usd": 1.0}
    assert final.completed_at is not None
    assert final.is_terminal


async def test_mark_missing_raises_key_error(store):
    with pytest.raises(KeyError):
        await store.mark_started("missing")
    with pytest.raises(KeyError):
        await store.mark_completed("missing", status="ok")


async def test_append_and_replay_events(store):
    rec = await store.create(_rec())
    for i in range(3):
        await store.append_event(
            rec.id,
            Event(type="x", task_id=rec.id, at=datetime.now(UTC), data={"i": i}),
        )
    events = await store.events(rec.id)
    assert [e.seq for e in events] == [1, 2, 3]
    assert [e.data["i"] for e in events] == [0, 1, 2]

    tail = await store.events(rec.id, after_seq=2)
    assert [e.seq for e in tail] == [3]

    limited = await store.events(rec.id, limit=2)
    assert [e.seq for e in limited] == [1, 2]


async def test_list_filter_and_sort(store):
    a = await store.create(_rec(user_id="alice"))
    b = await store.create(_rec(user_id="bob"))
    await store.mark_completed(a.id, status="ok")
    by_alice = await store.list(user_id="alice")
    assert [r.id for r in by_alice] == [a.id]
    ok_only = await store.list(status="ok")
    assert [r.id for r in ok_only] == [a.id]
    everyone = await store.list()
    assert {r.id for r in everyone} == {a.id, b.id}
