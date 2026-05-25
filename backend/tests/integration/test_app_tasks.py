"""End-to-end HTTP tests for `/api/tasks`."""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.settings import Settings
from backend.tasks.queue import InMemoryTaskQueue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry


class _IntegrationWorkflow(BaseWorkflow):
    name = "int_task"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        from backend.core.events import Event, EventType

        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        await ctx.emit(Event(EventType.TASK_STAGE_START, data={"stage": "work"}))
        await asyncio.sleep(0.01)
        await ctx.emit(Event(EventType.TASK_STAGE_END, data={"stage": "work"}))
        await ctx.emit(Event(EventType.TASK_END, data={"verdict": "ok"}))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={"echoed": ctx.query, "input": ctx.input},
        )


@pytest.fixture
async def client():
    reg = WorkflowRegistry()
    reg.register(_IntegrationWorkflow)
    store = InMemoryTaskStore()
    await store.init()
    deps = RunnerDeps(
        store=store,
        workflows=reg,
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
    )
    queue = InMemoryTaskQueue(deps)
    state = AppState(
        settings=Settings(),
        memory=deps.memory,
        llm=deps.llm,
        workflows=reg,
        task_store=store,
        task_queue=queue,
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        try:
            yield c, store, queue
        finally:
            await queue.close()


async def _wait_terminal(client_tuple, task_id: str, *, max_wait: float = 2.0) -> dict:
    client, _store, _queue = client_tuple
    elapsed = 0.0
    while elapsed < max_wait:
        resp = await client.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in {"ok", "error", "cancelled"}:
            return body
        await asyncio.sleep(0.02)
        elapsed += 0.02
    raise AssertionError(f"task {task_id} did not terminate in {max_wait}s")


async def test_create_task_returns_202_and_terminates_ok(client):
    http, _store, queue = client
    resp = await http.post(
        "/api/tasks",
        json={"workflow": "int_task", "query": "hello", "input": {"x": 1}},
    )
    assert resp.status_code == 202
    body = resp.json()
    tid = body["task_id"]
    assert body["workflow"] == "int_task"
    assert body["status"] == "queued"

    await queue.drain()
    final = await _wait_terminal(client, tid)
    assert final["status"] == "ok"
    assert final["result"] == {"echoed": "hello", "input": {"x": 1}}


async def test_create_task_unknown_workflow_returns_404(client):
    http, *_ = client
    resp = await http.post("/api/tasks", json={"workflow": "nope"})
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"]


async def test_get_missing_task_returns_404(client):
    http, *_ = client
    resp = await http.get("/api/tasks/missing")
    assert resp.status_code == 404


async def test_list_events_paginates(client):
    http, _store, queue = client
    resp = await http.post("/api/tasks", json={"workflow": "int_task", "query": "list"})
    tid = resp.json()["task_id"]
    await queue.drain()
    first = await http.get(f"/api/tasks/{tid}/events", params={"limit": 2})
    assert first.status_code == 200
    page1 = first.json()
    assert len(page1["items"]) == 2
    assert page1["next_after_seq"] == 2

    rest = await http.get(f"/api/tasks/{tid}/events", params={"after_seq": page1["next_after_seq"]})
    remaining = rest.json()["items"]
    assert [e["seq"] for e in remaining] == [3, 4]


async def test_cancel_terminates_task(client):
    http, _store, _queue = client
    rec = await http.post("/api/tasks", json={"workflow": "int_task", "query": "cancel"})
    tid = rec.json()["task_id"]
    # cancel immediately (task is likely still queued or running briefly)
    resp = await http.delete(f"/api/tasks/{tid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"cancelled", "ok"}  # may have completed first

    # second cancel is idempotent
    again = await http.delete(f"/api/tasks/{tid}")
    assert again.status_code == 200


async def test_list_tasks_filters_by_user(client):
    http, *_ = client
    a = await http.post(
        "/api/tasks", json={"workflow": "int_task", "query": "a", "user_id": "alice"}
    )
    b = await http.post("/api/tasks", json={"workflow": "int_task", "query": "b", "user_id": "bob"})
    assert a.status_code == b.status_code == 202

    resp = await http.get("/api/tasks", params={"user_id": "alice"})
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["user_id"] == "alice"


async def test_stream_events_replays_history(client):
    http, _store, queue = client
    resp = await http.post("/api/tasks", json={"workflow": "int_task", "query": "sse"})
    tid = resp.json()["task_id"]
    await queue.drain()

    async with http.stream("GET", f"/api/tasks/{tid}/stream") as stream:
        events: list[str] = []
        async for line in stream.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
                if events.count("task.end") >= 1:
                    break
    assert "task.start" in events
    assert "task.end" in events


async def test_service_unavailable_without_queue():
    state = AppState(settings=Settings())
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        resp = await c.post("/api/tasks", json={"workflow": "demo"})
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# P9.3 — follow-up tasks (threaded conversation)
# ---------------------------------------------------------------------------


async def test_follow_up_inherits_manuscript_and_records_parent(client):
    http, _store, queue = client
    parent = await http.post(
        "/api/tasks",
        json={
            "workflow": "int_task",
            "query": "first turn",
            "input": {
                "manuscript_id": "ms_abc",
                "bundle_target": "overleaf/sections/intro.tex",
                "section": "intro",
            },
        },
    )
    pid = parent.json()["task_id"]
    await queue.drain()
    await _wait_terminal(client, pid)

    fu = await http.post(
        f"/api/tasks/{pid}/follow-up",
        json={"query": "tighten the prose"},
    )
    assert fu.status_code == 202, fu.text
    cid = fu.json()["task_id"]
    await queue.drain()
    final = await _wait_terminal(client, cid)
    assert final["status"] == "ok"

    inp = final["input"]
    assert inp["parent_task_id"] == pid
    assert inp["manuscript_id"] == "ms_abc"
    assert inp["bundle_target"] == "overleaf/sections/intro.tex"
    assert inp["section"] == "intro"


async def test_follow_up_seeds_text_from_parent_result_for_revision(client):
    # _IntegrationWorkflow echoes input; we just need to verify the
    # endpoint copies results forward for single-doc revision.
    http, store, _queue = client
    # Bypass create_task to plant a fake completed revision parent.
    from datetime import UTC, datetime

    from backend.tasks.models import TaskRecord

    parent = TaskRecord(
        id="parent_rev_1",
        workflow="revision",
        status="ok",
        query="first revision",
        input={"text": "First version."},
        result={"revised": "Second version after first revision."},
        completed_at=datetime.now(UTC),
    )
    await store.create(parent)

    # The child task will still hit _IntegrationWorkflow because we
    # only registered that one — but the runner will reject it since
    # "revision" isn't registered. We assert on the *child record* the
    # endpoint creates, not on workflow execution.
    fu = await http.post(
        f"/api/tasks/{parent.id}/follow-up",
        json={"query": "punch up the verbs", "comments": [{"id": "c1", "text": "shorter"}]},
    )
    assert fu.status_code == 202, fu.text
    cid = fu.json()["task_id"]

    child = await store.get(cid)
    assert child is not None
    assert child.workflow == "revision"
    assert child.query == "punch up the verbs"
    assert child.input["parent_task_id"] == "parent_rev_1"
    # Parent's revised text was seeded as the new input.text.
    assert child.input["text"] == "Second version after first revision."
    assert child.input["comments"] == [{"id": "c1", "text": "shorter"}]


async def test_follow_up_on_running_task_returns_409(client):
    http, store, _queue = client
    from backend.tasks.models import TaskRecord

    parent = TaskRecord(id="running_parent", workflow="int_task", status="running")
    await store.create(parent)
    resp = await http.post(f"/api/tasks/{parent.id}/follow-up", json={"query": "x"})
    assert resp.status_code == 409
    assert "non-terminal" in resp.json()["detail"]


async def test_list_tasks_filters_by_parent_task_id(client):
    http, _store, queue = client
    parent = await http.post("/api/tasks", json={"workflow": "int_task", "query": "p"})
    pid = parent.json()["task_id"]
    await queue.drain()
    await _wait_terminal(client, pid)

    c1 = await http.post(f"/api/tasks/{pid}/follow-up", json={"query": "c1"})
    c2 = await http.post(f"/api/tasks/{pid}/follow-up", json={"query": "c2"})
    other = await http.post("/api/tasks", json={"workflow": "int_task", "query": "unrelated"})
    await queue.drain()

    resp = await http.get("/api/tasks", params={"parent_task_id": pid})
    assert resp.status_code == 200
    ids = {item["id"] for item in resp.json()["items"]}
    assert ids == {c1.json()["task_id"], c2.json()["task_id"]}
    assert other.json()["task_id"] not in ids
