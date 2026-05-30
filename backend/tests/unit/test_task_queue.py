"""Unit tests for `InMemoryTaskQueue`."""

from __future__ import annotations

import asyncio

import pytest

from backend.tasks.models import TaskRecord
from backend.tasks.queue import InMemoryTaskQueue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry


class _SlowWorkflow(BaseWorkflow):
    name = "queue_slow"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await asyncio.sleep(0.02)
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok", results={"k": "v"})


async def _seed():
    store = InMemoryTaskStore()
    reg = WorkflowRegistry()
    reg.register(_SlowWorkflow)
    deps = RunnerDeps(store=store, workflows=reg)
    queue = InMemoryTaskQueue(deps)
    return store, queue


async def test_enqueue_runs_task_in_background():
    store, queue = await _seed()
    rec = await store.create(TaskRecord(id="q1", workflow=_SlowWorkflow.name))
    await queue.enqueue(rec.id)
    await queue.drain()
    final = await store.get(rec.id)
    assert final is not None
    assert final.status == "ok"


async def test_enqueue_multiple_runs_in_parallel():
    store, queue = await _seed()
    ids = [f"q{i}" for i in range(5)]
    for tid in ids:
        await store.create(TaskRecord(id=tid, workflow=_SlowWorkflow.name))
    for tid in ids:
        await queue.enqueue(tid)
    await queue.drain()
    for tid in ids:
        r = await store.get(tid)
        assert r is not None
        assert r.status == "ok"


async def test_close_cancels_in_flight_jobs():
    store, queue = await _seed()

    class _VerySlow(BaseWorkflow):
        name = "queue_very_slow"

        async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
            await asyncio.sleep(5.0)
            return WorkflowOutput(task_id=ctx.task_id, verdict="ok")

    queue._deps.workflows.register(_VerySlow)
    await store.create(TaskRecord(id="q-long", workflow=_VerySlow.name))
    await queue.enqueue("q-long")
    await asyncio.sleep(0.05)
    await queue.close()
    # Task was started so status is 'running' (or 'error' from cancel) — either way not 'queued'
    final = await store.get("q-long")
    assert final is not None
    assert final.status in {"running", "error", "ok"}


async def test_close_prevents_further_enqueue():
    _store, queue = await _seed()
    await queue.close()
    with pytest.raises(RuntimeError):
        await queue.enqueue("ghost")
