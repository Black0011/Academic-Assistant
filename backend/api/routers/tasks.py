"""Long-running task endpoints.

* ``POST   /api/tasks``             — enqueue a workflow run (returns 202).
* ``GET    /api/tasks/{id}``         — current :class:`TaskRecord`.
* ``GET    /api/tasks``              — paginated list of tasks.
* ``DELETE /api/tasks/{id}``         — cancel (best-effort).
* ``GET    /api/tasks/{id}/events``  — paged event log (replay buffer).
* ``GET    /api/tasks/{id}/stream``  — SSE: replay history + tail new events.

The SSE endpoint polls the store instead of pub/sub so it works across
API ↔ ARQ-worker processes without extra infrastructure. The poll
cadence backs off while the task is still queued and is tight while the
task is running.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.core.app_state import AppState, get_app_state
from backend.tasks.models import (
    CreateTaskInput,
    TaskEventRecord,
    TaskRecord,
    TaskStatus,
)

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ---- helpers ----------------------------------------------------------


def _require_store(state: AppState):
    if state.task_store is None:
        raise HTTPException(
            status_code=503,
            detail="task store not configured on this server",
        )
    return state.task_store


def _require_queue(state: AppState):
    if state.task_queue is None:
        raise HTTPException(
            status_code=503,
            detail="task queue not configured on this server",
        )
    return state.task_queue


# ---- responses --------------------------------------------------------


class CreateTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    workflow: str


class TaskListResponse(BaseModel):
    items: list[TaskRecord]
    total: int = Field(..., description="Count of returned items (not total rows).")


class EventListResponse(BaseModel):
    items: list[TaskEventRecord]
    next_after_seq: int


# ---- endpoints --------------------------------------------------------


@router.post(
    "",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a workflow run",
)
async def create_task(
    body: CreateTaskInput,
    state: AppState = Depends(get_app_state),
) -> CreateTaskResponse:
    store = _require_store(state)
    queue = _require_queue(state)
    if state.workflows is None or not state.workflows.has(body.workflow):
        available = state.workflows.names() if state.workflows else []
        raise HTTPException(
            status_code=404,
            detail=f"workflow '{body.workflow}' not found. Available: {available}",
        )

    budget_payload: dict[str, Any] = {}
    if body.budget_usd is not None:
        budget_payload["max_cost_usd"] = body.budget_usd

    record = TaskRecord(
        id=uuid.uuid4().hex,
        workflow=body.workflow,
        status="queued",
        query=body.query,
        input=dict(body.input),
        budget=budget_payload,
        user_id=body.user_id,
        session_id=body.session_id,
    )
    saved = await store.create(record)
    await queue.enqueue(saved.id)
    return CreateTaskResponse(task_id=saved.id, status=saved.status, workflow=saved.workflow)


@router.get("", response_model=TaskListResponse, summary="List tasks")
async def list_tasks(
    user_id: str | None = None,
    task_status: TaskStatus | None = None,
    parent_task_id: str | None = None,
    manuscript_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
    state: AppState = Depends(get_app_state),
) -> TaskListResponse:
    store = _require_store(state)
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    items = await store.list(user_id=user_id, status=task_status, limit=limit, offset=offset)
    if parent_task_id is not None:
        items = [i for i in items if i.input.get("parent_task_id") == parent_task_id]
    if manuscript_id is not None:
        # P18: filter threads by manuscript_id stored in input
        items = [i for i in items if i.input.get("manuscript_id") == manuscript_id]
    return TaskListResponse(items=items, total=len(items))


class FollowUpInput(BaseModel):
    """Body for ``POST /api/tasks/{task_id}/follow-up`` (P9.3).

    Creates a *child* task that inherits the parent's manuscript-related
    fields and seeds itself from the parent's result so the user can
    iterate without re-filling the form.
    """

    query: str = Field("", max_length=10000)
    comments: list[dict] | list[str] | None = None
    budget_usd: float | None = Field(default=None, ge=0)
    notes: str = Field("", description="Free-form note copied into the child task's input.")


@router.post(
    "/{task_id}/follow-up",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a follow-up task threaded to this one (P9.3)",
)
async def follow_up_task(
    task_id: str,
    body: FollowUpInput,
    state: AppState = Depends(get_app_state),
) -> CreateTaskResponse:
    """Enqueue a child task carrying the parent's context.

    Inheritance rules (kept conservative on purpose so the user retains
    control):

    * The parent must already be terminal (``ok``/``error``/``cancelled``)
      — multi-turn conversations on a still-running task are out of
      scope for P9.3.
    * ``manuscript_id``, ``bundle_target``, ``section``, ``register_in_main``
      copy through verbatim. Bundle revision will then re-read the file
      from disk so the child sees whatever the parent wrote.
    * For non-bundle revision workflows the parent's ``result.revised``
      is seeded as ``input.text`` so the child can polish the latest
      version without the user pasting it in.
    * For non-bundle write workflows the parent's ``result.markdown``
      is seeded as ``input.text`` for the same reason.
    * Every child task records the parent's id under
      ``input.parent_task_id`` so the frontend can render a thread
      view via ``GET /api/tasks?parent_task_id=<id>``.
    """

    store = _require_store(state)
    queue = _require_queue(state)
    parent = await store.get(task_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    if not parent.is_terminal:
        raise HTTPException(
            status_code=409,
            detail="cannot fork a follow-up from a non-terminal parent task",
        )

    inherited: dict[str, Any] = {}
    parent_input = parent.input or {}
    for key in ("manuscript_id", "bundle_target", "section", "register_in_main"):
        if key in parent_input and parent_input[key] not in (None, ""):
            inherited[key] = parent_input[key]
    inherited["parent_task_id"] = parent.id

    # Seed ``input.text`` from the parent's result for single-doc
    # revision / write so the child can build on the latest output.
    # Bundles intentionally skip this — the runner's pre-read step will
    # load the file fresh from disk, including any edits made between
    # parent and child.
    # Pass suspect citations from parent so child workflows can verify them
    parent_result = parent.result or {}
    parent_suspect = parent_result.get("suspect_citations", [])
    if parent_suspect:
        inherited["suspect_citations"] = parent_suspect

    is_bundle = bool(inherited.get("bundle_target"))
    if not is_bundle:
        if parent.workflow == "revision" and isinstance(parent_result.get("revised"), str):
            inherited["text"] = parent_result["revised"]
        elif parent.workflow == "write" and isinstance(parent_result.get("markdown"), str):
            inherited["text"] = parent_result["markdown"]

    if body.comments is not None:
        inherited["comments"] = body.comments
    if body.notes:
        inherited["notes"] = body.notes

    budget_payload: dict[str, Any] = {}
    if body.budget_usd is not None:
        budget_payload["max_cost_usd"] = body.budget_usd
    elif parent.budget:
        # Carry over the parent's budget envelope as a sensible default.
        budget_payload = dict(parent.budget)

    record = TaskRecord(
        id=uuid.uuid4().hex,
        workflow=parent.workflow,
        status="queued",
        query=body.query or parent.query,
        input=inherited,
        budget=budget_payload,
        user_id=parent.user_id,
        session_id=parent.session_id,
    )
    saved = await store.create(record)
    await queue.enqueue(saved.id)
    return CreateTaskResponse(task_id=saved.id, status=saved.status, workflow=saved.workflow)


class RespondToTaskInput(BaseModel):
    """Body for ``POST /api/tasks/{task_id}/respond``.

    Creates a *child* task that resumes the parent from a pause point.
    The parent must be in ``"waiting"`` status.
    """

    response: str = Field("", max_length=10000, description="User's free-text answer.")
    response_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured answer data, e.g. {action: 'accept_some', rejected_files: [...]}.",
    )


@router.post(
    "/{task_id}/respond",
    response_model=CreateTaskResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Respond to a waiting task, creating a child that resumes execution",
)
async def respond_to_task(
    task_id: str,
    body: RespondToTaskInput,
    state: AppState = Depends(get_app_state),
) -> CreateTaskResponse:
    store = _require_store(state)
    queue = _require_queue(state)
    parent = await store.get(task_id)
    if parent is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    if parent.status != "waiting":
        raise HTTPException(
            status_code=409,
            detail=f"task is not waiting for input; current status: {parent.status}",
        )

    snapshot = parent.result or {}
    resume_state = snapshot.get("state", {})
    resume_checkpoint = snapshot.get("checkpoint", "")

    inherited: dict[str, Any] = dict(parent.input or {})
    for key in ("manuscript_id", "bundle_target", "section", "register_in_main"):
        if key not in inherited or inherited[key] in (None, ""):
            continue
    inherited["_resume_state"] = resume_state
    inherited["_resume_checkpoint"] = resume_checkpoint
    inherited["_user_response"] = {
        "prompt": body.response,
        "data": body.response_data,
    }
    inherited["parent_task_id"] = parent.id

    child = TaskRecord(
        id=uuid.uuid4().hex,
        workflow=parent.workflow,
        status="queued",
        query=body.response or parent.query,
        input=inherited,
        budget=dict(parent.budget),
        user_id=parent.user_id,
        session_id=parent.session_id,
    )
    saved = await store.create(child)
    await queue.enqueue(saved.id)
    return CreateTaskResponse(task_id=saved.id, status=saved.status, workflow=saved.workflow)


@router.get("/{task_id}", response_model=TaskRecord, summary="Read a task record")
async def get_task(
    task_id: str,
    state: AppState = Depends(get_app_state),
) -> TaskRecord:
    store = _require_store(state)
    record = await store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    return record


@router.delete(
    "/{task_id}",
    response_model=TaskRecord,
    summary="Cancel a task (best-effort)",
)
async def cancel_task(
    task_id: str,
    state: AppState = Depends(get_app_state),
) -> TaskRecord:
    store = _require_store(state)
    record = await store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    if record.is_terminal:
        return record
    await store.mark_completed(task_id, status="cancelled", error="cancelled by user")
    updated = await store.get(task_id)
    assert updated is not None
    return updated


@router.get(
    "/{task_id}/events",
    response_model=EventListResponse,
    summary="Fetch events (polling-friendly)",
)
async def list_events(
    task_id: str,
    after_seq: int = 0,
    limit: int = 200,
    state: AppState = Depends(get_app_state),
) -> EventListResponse:
    store = _require_store(state)
    record = await store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    after_seq = max(0, after_seq)
    limit = max(1, min(limit, 500))
    items = await store.events(task_id, after_seq=after_seq, limit=limit)
    next_after = items[-1].seq if items else after_seq
    return EventListResponse(items=items, next_after_seq=next_after)


@router.get(
    "/{task_id}/stream",
    summary="Replay history then tail new events via SSE",
)
async def stream_events(
    task_id: str,
    after_seq: int = 0,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    record = await store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")

    async def generator() -> AsyncIterator[dict[str, Any]]:
        import json

        cursor = max(0, after_seq)
        # Poll cadence: 50ms while running, 200ms while queued, stop after terminal.
        idle_ticks = 0
        while True:
            batch = await store.events(task_id, after_seq=cursor, limit=200)
            for ev in batch:
                cursor = ev.seq
                yield {"event": ev.type, "data": json.dumps(_event_to_dict(ev), default=str)}
            current = await store.get(task_id)
            if current is None:
                break
            if current.is_terminal and not batch:
                # Drain any last events that slipped in between poll + status.
                trailing = await store.events(task_id, after_seq=cursor, limit=200)
                if trailing:
                    for ev in trailing:
                        cursor = ev.seq
                        yield {
                            "event": ev.type,
                            "data": json.dumps(_event_to_dict(ev), default=str),
                        }
                break
            # Poll cadence: 50ms running, 200ms queued, 1000ms waiting.
            if current.status == "waiting":
                await asyncio.sleep(1.0)
            elif current.status == "running":
                await asyncio.sleep(0.05)
            else:
                await asyncio.sleep(0.2)
            # Don't count idle ticks for waiting tasks — indefinite wait is expected.
            if current.status != "waiting":
                idle_ticks = 0 if batch else idle_ticks + 1
                # Safety: don't poll forever if stuck >10 min with no events.
                if idle_ticks > 3000:
                    break

    return EventSourceResponse(generator())


def _event_to_dict(ev: TaskEventRecord) -> dict[str, Any]:
    return {
        "task_id": ev.task_id,
        "seq": ev.seq,
        "type": ev.type,
        "at": ev.at.isoformat() if isinstance(ev.at, datetime) else str(ev.at),
        "data": dict(ev.data),
    }


def _now() -> datetime:
    return datetime.now(UTC)
