"""Workflow execution endpoints.

Two transport modes on a shared runner:

* ``POST /api/workflows/{name}/run`` — synchronous, returns final
  :class:`WorkflowOutput` as JSON. Good for short tasks + tests.
* ``POST /api/workflows/{name}/stream`` — Server-Sent Events; each event
  is one :class:`backend.core.events.Event`. Caller closes when they see
  ``task.end``.

We keep the workflow registry intentionally tiny in Stage 2c — just the
``demo`` workflow. Stage 2d introduces discovery + long-running tasks via
ARQ.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from backend.core.app_state import AppState, get_app_state
from backend.core.budget import Budget
from backend.core.events import Event
from backend.workflows import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry, build_default_registry

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


def _get_registry(state: AppState) -> WorkflowRegistry:
    if state.workflows is not None:
        return state.workflows
    # Fall back to a fresh discovery-backed registry so tests that don't
    # wire one still work. Memoise onto the state so it's built once.
    state.workflows = build_default_registry()
    return state.workflows


def _get_workflow(state: AppState, name: str) -> BaseWorkflow:
    reg = _get_registry(state)
    if not reg.has(name):
        raise HTTPException(
            status_code=404,
            detail=f"workflow '{name}' not found. Available: {reg.names()}",
        )
    return reg.instantiate(name)


# ---- request / response shapes ---------------------------------------


class RunRequest(BaseModel):
    query: str = Field(..., min_length=1)
    input: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    session_id: str | None = None
    budget_usd: float | None = Field(default=None, ge=0)


class RunResponse(BaseModel):
    task_id: str
    verdict: str
    results: Any | None = None
    error: str | None = None
    budget: dict[str, float | int] = Field(default_factory=dict)
    events: list[dict[str, Any]] = Field(default_factory=list)

    @classmethod
    def from_output(cls, out: WorkflowOutput) -> RunResponse:
        return cls(
            task_id=out.task_id,
            verdict=out.verdict,
            results=out.results,
            error=out.error,
            budget=out.budget,
            events=[e.to_dict() for e in out.trace],
        )


# ---- shared runner ----------------------------------------------------


def _make_context(req: RunRequest, state: AppState) -> WorkflowContext:
    ctx = WorkflowContext(
        task_id=str(uuid.uuid4()),
        query=req.query,
        input=dict(req.input),
        user_id=req.user_id,
        session_id=req.session_id,
        llm=state.llm,
        memory=state.memory,
        tools=state.tools,
    )
    if req.budget_usd is not None:
        ctx.budget = Budget(max_cost_usd=req.budget_usd)
    return ctx


# ---- synchronous endpoint --------------------------------------------


@router.get("", summary="List registered workflows")
async def list_workflows(state: AppState = Depends(get_app_state)) -> list[dict[str, str]]:
    return _get_registry(state).describe()


@router.post("/{name}/run", response_model=RunResponse, summary="Run a workflow synchronously")
async def run(
    name: str,
    req: RunRequest,
    state: AppState = Depends(get_app_state),
) -> RunResponse:
    workflow = _get_workflow(state, name)
    ctx = _make_context(req, state)
    out = await workflow.run(ctx)
    return RunResponse.from_output(out)


# ---- SSE endpoint ----------------------------------------------------


@router.post("/{name}/stream", summary="Run a workflow, stream events as SSE")
async def stream(
    name: str,
    req: RunRequest,
    state: AppState = Depends(get_app_state),
) -> EventSourceResponse:
    workflow = _get_workflow(state, name)
    ctx = _make_context(req, state)
    queue: asyncio.Queue[Event | None] = asyncio.Queue()

    async def sink(event: Event) -> None:
        await queue.put(event)

    ctx.with_sink(sink)

    async def driver() -> None:
        try:
            await workflow.run(ctx)
        finally:
            await queue.put(None)  # sentinel → close stream

    async def event_source() -> AsyncIterator[dict[str, Any]]:
        task = asyncio.create_task(driver())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield {"event": item.type, "data": _json_dumps(item.to_dict())}
        finally:
            if not task.done():
                task.cancel()
            # Surface workflow exceptions into server logs; the client
            # already sees ``task.error`` emitted by BaseWorkflow.stage().
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                import structlog

                structlog.get_logger(__name__).exception("workflow.stream.driver_failed")

    return EventSourceResponse(event_source())


def _json_dumps(obj: Any) -> str:
    import json

    def _default(x: Any) -> Any:
        if hasattr(x, "model_dump"):
            return x.model_dump()
        if hasattr(x, "isoformat"):
            return x.isoformat()
        if hasattr(x, "__dict__"):
            return asdict(x) if hasattr(x, "__dataclass_fields__") else x.__dict__
        return str(x)

    return json.dumps(obj, default=_default, ensure_ascii=False)
