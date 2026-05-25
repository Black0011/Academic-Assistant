"""Unit tests for `InMemoryManuscriptStore` + `SqlManuscriptStore`.

Same fixture pattern as `test_task_store.py`: every test runs against
both backends so behaviour drift is caught immediately.
"""

from __future__ import annotations

import pytest

from backend.manuscripts.models import (
    CommitVersionInput,
    CreateManuscriptInput,
    UpdateManuscriptInput,
)
from backend.manuscripts.sql_store import SqlManuscriptStore
from backend.manuscripts.store import InMemoryManuscriptStore


@pytest.fixture(params=["memory", "sql"])
async def store(request):
    if request.param == "memory":
        s = InMemoryManuscriptStore()
    else:
        s = SqlManuscriptStore.from_url("sqlite+aiosqlite:///:memory:")
    await s.init()
    try:
        yield s
    finally:
        await s.close()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


async def test_create_without_content_starts_at_v0(store):
    record, version = await store.create(
        CreateManuscriptInput(title="Untitled draft", kind="paper")
    )
    assert record.id
    assert record.title == "Untitled draft"
    assert record.kind == "paper"
    assert record.current_version == 0
    assert version is None

    fetched = await store.get(record.id)
    assert fetched is not None
    assert fetched.current_version == 0


async def test_create_with_content_commits_v1(store):
    record, version = await store.create(
        CreateManuscriptInput(
            title="My intro",
            content="# Intro\n\nHello world.",
            note="seed",
            tags=["draft", "intro"],
        )
    )
    assert version is not None
    assert version.version == 1
    assert version.note == "seed"
    assert version.word_count == 3  # "Intro Hello world"

    final = await store.get(record.id)
    assert final is not None
    assert final.current_version == 1
    assert "draft" in final.tags


# ---------------------------------------------------------------------------
# List + filter
# ---------------------------------------------------------------------------


async def test_list_filters_and_orders_by_updated_at(store):
    a, _ = await store.create(CreateManuscriptInput(title="A", user_id="u1", tags=["x"]))
    b, _ = await store.create(CreateManuscriptInput(title="B", user_id="u2", tags=["y"]))
    c, _ = await store.create(
        CreateManuscriptInput(title="C", user_id="u1", tags=["x", "y"], status="final")
    )

    all_items = await store.list()
    ids = [m.id for m in all_items]
    assert {a.id, b.id, c.id} <= set(ids)

    user1 = await store.list(user_id="u1")
    assert {m.id for m in user1} == {a.id, c.id}

    tagged = await store.list(tag="y")
    assert {m.id for m in tagged} == {b.id, c.id}

    final_only = await store.list(status="final")
    assert [m.id for m in final_only] == [c.id]


async def test_list_pagination(store):
    ids = []
    for i in range(5):
        rec, _ = await store.create(CreateManuscriptInput(title=f"M{i}"))
        ids.append(rec.id)

    page1 = await store.list(limit=2, offset=0)
    page2 = await store.list(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {m.id for m in page1}.isdisjoint({m.id for m in page2})


# ---------------------------------------------------------------------------
# Update + delete
# ---------------------------------------------------------------------------


async def test_update_partial_fields(store):
    record, _ = await store.create(CreateManuscriptInput(title="Old title", tags=["a"]))
    updated = await store.update(
        record.id,
        UpdateManuscriptInput(title="New title", tags=["a", "b"], status="in_revision"),
    )
    assert updated.title == "New title"
    assert updated.tags == ["a", "b"]
    assert updated.status == "in_revision"
    # Unchanged fields stay put.
    assert updated.kind == record.kind


async def test_update_missing_raises(store):
    with pytest.raises(KeyError):
        await store.update("nope", UpdateManuscriptInput(title="x"))


async def test_delete_removes_manuscript_and_versions(store):
    record, _ = await store.create(CreateManuscriptInput(title="ToDelete", content="text"))
    assert await store.delete(record.id) is True
    assert await store.get(record.id) is None
    # A subsequent versions read raises.
    with pytest.raises(KeyError):
        await store.list_versions(record.id)


async def test_delete_missing_returns_false(store):
    assert await store.delete("missing") is False


# ---------------------------------------------------------------------------
# Versions
# ---------------------------------------------------------------------------


async def test_commit_version_appends_monotonically(store):
    record, v1 = await store.create(CreateManuscriptInput(title="Doc", content="first"))
    assert v1 is not None and v1.version == 1

    v2 = await store.commit_version(
        record.id,
        CommitVersionInput(content="second pass", note="rev1", origin="revision_workflow"),
    )
    v3 = await store.commit_version(
        record.id,
        CommitVersionInput(content="third pass", note="rev2", produced_by="task-xyz"),
    )

    assert v2.version == 2
    assert v3.version == 3
    assert v3.produced_by == "task-xyz"

    final = await store.get(record.id)
    assert final is not None
    assert final.current_version == 3
    # Origin from a non-api commit should be propagated.
    assert final.origin == "revision_workflow"


async def test_commit_version_missing_manuscript(store):
    with pytest.raises(KeyError):
        await store.commit_version("nope", CommitVersionInput(content="hi"))


async def test_list_versions_returns_newest_first(store):
    record, _ = await store.create(CreateManuscriptInput(title="Doc", content="v1"))
    await store.commit_version(record.id, CommitVersionInput(content="v2"))
    await store.commit_version(record.id, CommitVersionInput(content="v3"))

    versions = await store.list_versions(record.id)
    assert [v.version for v in versions] == [3, 2, 1]


async def test_get_version(store):
    record, _ = await store.create(CreateManuscriptInput(title="Doc", content="v1"))
    v = await store.get_version(record.id, 1)
    assert v is not None
    assert v.content == "v1"
    assert await store.get_version(record.id, 99) is None


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


async def test_stats(store):
    a, _ = await store.create(CreateManuscriptInput(title="A", content="x"))
    _b, _ = await store.create(CreateManuscriptInput(title="B", status="final"))
    await store.commit_version(a.id, CommitVersionInput(content="x2"))

    s = await store.stats()
    assert s["total"] == 2
    assert s["versions_total"] == 2  # A has v1+v2, B has 0
    assert s["by_status"].get("draft", 0) == 1
    assert s["by_status"].get("final", 0) == 1
