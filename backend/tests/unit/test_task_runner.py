"""Unit tests for `tasks.runner.execute_task`."""

from __future__ import annotations

import pytest

from backend.core.events import Event, EventType
from backend.tasks.models import TaskRecord
from backend.tasks.runner import RunnerDeps, execute_task
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry


class _OKWorkflow(BaseWorkflow):
    name = "runner_ok"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START))
        await ctx.emit(Event(EventType.TASK_STAGE_START, data={"stage": "work"}))
        await ctx.emit(Event(EventType.TASK_STAGE_END, data={"stage": "work"}))
        await ctx.emit(Event(EventType.TASK_END))
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok", results={"value": 42})


class _ErrWorkflow(BaseWorkflow):
    name = "runner_err"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START))
        return WorkflowOutput(task_id=ctx.task_id, verdict="error", error="nope")


class _RaiseWorkflow(BaseWorkflow):
    name = "runner_raise"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        raise RuntimeError("kaboom")


async def _seed(workflow_cls) -> tuple[InMemoryTaskStore, WorkflowRegistry, TaskRecord]:
    store = InMemoryTaskStore()
    await store.init()
    reg = WorkflowRegistry()
    reg.register(workflow_cls)
    rec = await store.create(TaskRecord(id="t1", workflow=workflow_cls.name))
    return store, reg, rec


async def test_runner_success_path():
    store, reg, rec = await _seed(_OKWorkflow)
    deps = RunnerDeps(store=store, workflows=reg)
    await execute_task(rec.id, deps)

    final = await store.get(rec.id)
    assert final is not None
    assert final.status == "ok"
    assert final.result == {"value": 42}
    assert final.started_at is not None
    assert final.completed_at is not None

    events = await store.events(rec.id)
    assert [e.type for e in events] == [
        EventType.TASK_START,
        EventType.TASK_STAGE_START,
        EventType.TASK_STAGE_END,
        EventType.TASK_END,
    ]


async def test_runner_workflow_reports_error():
    store, reg, rec = await _seed(_ErrWorkflow)
    deps = RunnerDeps(store=store, workflows=reg)
    await execute_task(rec.id, deps)

    final = await store.get(rec.id)
    assert final is not None
    assert final.status == "error"
    assert final.error == "nope"


async def test_runner_catches_unhandled_exception():
    store, reg, rec = await _seed(_RaiseWorkflow)
    deps = RunnerDeps(store=store, workflows=reg)
    await execute_task(rec.id, deps)  # must not raise

    final = await store.get(rec.id)
    assert final is not None
    assert final.status == "error"
    assert final.error is not None
    assert "kaboom" in final.error

    events = await store.events(rec.id)
    assert any(e.type == EventType.TASK_ERROR for e in events)


async def test_runner_skips_missing_and_terminal_tasks():
    store = InMemoryTaskStore()
    reg = WorkflowRegistry()
    reg.register(_OKWorkflow)
    deps = RunnerDeps(store=store, workflows=reg)

    # missing — no raise, no writes
    await execute_task("does-not-exist", deps)

    rec = await store.create(TaskRecord(id="t2", workflow=_OKWorkflow.name, status="ok"))
    await execute_task(rec.id, deps)
    # still ok, no new events
    events = await store.events(rec.id)
    assert events == []


async def test_runner_rejects_unknown_workflow():
    store = InMemoryTaskStore()
    reg = WorkflowRegistry()  # empty
    rec = await store.create(TaskRecord(id="t3", workflow="ghost"))
    await execute_task(rec.id, RunnerDeps(store=store, workflows=reg))
    final = await store.get(rec.id)
    assert final is not None
    assert final.status == "error"
    assert "ghost" in (final.error or "")
