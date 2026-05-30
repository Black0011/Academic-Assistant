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


async def _build_thread_history(store, task, max_ancestors: int = 20) -> list[dict]:
    """Walk up the parent_task_id chain and build a full message history.
    Returns oldest-first list of {role, content, tool_calls?, ...} dicts
    suitable for passing as input.history to a new task."""
    chain: list = []
    current = task
    for _ in range(max_ancestors):
        chain.append(current)
        pid = (current.input or {}).get("parent_task_id")
        if not pid:
            break
        parent = await store.get(pid)
        if parent is None:
            break
        current = parent
    chain.reverse()  # oldest first

    history: list[dict] = []
    for ti, t in enumerate(chain):
        r = t.result or {}
        tc = r.get("tool_calls") or []
        if isinstance(tc, list) and tc:
            history.append({"role": "user", "content": t.query or ""})
            history.append({
                "role": "assistant",
                "content": "Let me use the appropriate tools for this request.",
                "tool_calls": [
                    {
                        "id": (c.get("id") or f"a{ti}_{j}"),
                        "name": c.get("name", "?"),
                        "arguments": c.get("args", {}),
                    }
                    for j, c in enumerate(tc) if isinstance(c, dict)
                ],
            })
            for j, c in enumerate(tc):
                if isinstance(c, dict):
                    tool_call_id = c.get("id") or f"a{ti}_{j}"
                    history.append({
                        "role": "tool",
                        "content": c.get("result_summary", f"Tool {c.get('name', '?')} completed."),
                        "tool_call_id": tool_call_id,
                        "name": c.get("name", ""),
                    })
        # Final answer
        answer = r.get("answer") or r.get("analysis") or r.get("revised") or ""
        if answer:
            history.append({"role": "assistant", "content": str(answer)[:4000]})
        elif not tc:
            # No tools and no answer → just a user query, push placeholder
            if t.query:
                history.append({"role": "user", "content": t.query})
    return history


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

    input_data = dict(body.input)
    # Auto-build history from parent chain when parent_task_id is set
    # but no history was provided — ensures thread continuity.
    pid = input_data.get("parent_task_id")
    if pid and not input_data.get("history"):
        parent = await store.get(pid)
        if parent is not None:
            chain_history = await _build_thread_history(store, parent)
            if chain_history:
                input_data["history"] = chain_history

    record = TaskRecord(
        id=uuid.uuid4().hex,
        workflow=body.workflow,
        status="queued",
        query=body.query,
        input=input_data,
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
    history: list[dict] | None = Field(default=None, description="Full message chain from the conversation thread.")


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
    if body.history:
        inherited["history"] = body.history
    else:
        # Auto-build history from the parent chain so the new task
        # inherits the full conversation context.
        chain_history = await _build_thread_history(store, parent)
        if chain_history:
            inherited["history"] = chain_history

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
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a completed/failed/cancelled task permanently",
)
async def delete_task(
    task_id: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_store(state)
    record = await store.get(task_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"task '{task_id}' not found")
    if not record.is_terminal and record.status != "waiting":
        raise HTTPException(
            status_code=409,
            detail="Cannot delete a running/queued task. Wait for it to complete first.",
        )
    await store.delete(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
            await asyncio.sleep(0.05 if current.status == "running" else 0.2)
            idle_ticks = 0 if batch else idle_ticks + 1
            # Safety: don't poll forever if task is stuck for >10 min with no events.
            if idle_ticks > 3000:  # 3000 * 0.2s = 10 min
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
