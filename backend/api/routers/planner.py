"""Planner DAG API (M8.2) — `/api/planner`.

Surface (PLAN.md §20.9 M8.2):

* ``GET    /api/planner/skills_for_compile``  curated skill / tool catalogue
* ``POST   /api/planner/compile``             query -> :class:`PlanDAG`
* ``POST   /api/planner/validate``            structural / reference checks
* ``POST   /api/planner/execute``             enqueue ``dag`` workflow run

Compile and validate are cheap and synchronous. Execute returns a
``task_id`` (HTTP 202) and the actual run happens via the standard task
queue + ``dag`` workflow, so existing SSE clients (``/api/tasks/{id}/events``)
see node-level ``stage_start`` / ``stage_end`` events without changes.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.core.app_state import AppState, get_app_state
from backend.core.auth.dependencies import current_user
from backend.core.auth.models import User
from backend.planner import (
    CompilePlanInput,
    ExecutePlanInput,
    PlannerCompiler,
    ValidatePlanInput,
    ValidatePlanResponse,
    validate_plan,
)
from backend.planner.models import (
    PlanDAG,
    SkillsForCompileResponse,
)
from backend.tasks.models import TaskRecord

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/planner", tags=["planner"])


class ExecutePlanResponse(BaseModel):
    task_id: str
    status: str
    workflow: str = "dag"
    plan_id: str
    node_count: int


def _build_compiler(state: AppState) -> PlannerCompiler:
    return PlannerCompiler(
        llm=state.llm,
        skill_host=state.skill_host,
        tools=state.tools,
    )


@router.get(
    "/skills_for_compile",
    response_model=SkillsForCompileResponse,
    summary="List skills + tools the planner can wire into a DAG",
)
async def skills_for_compile(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> SkillsForCompileResponse:
    return _build_compiler(state).skills_for_compile()


@router.post(
    "/compile",
    response_model=PlanDAG,
    summary="Compile a free-form query into a PlanDAG",
)
async def compile_plan(
    body: CompilePlanInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> PlanDAG:
    settings = state.settings
    max_nodes = body.max_nodes
    if settings is not None:
        max_nodes = min(max_nodes, settings.planner_default_max_nodes)
    compiler = _build_compiler(state)
    return await compiler.compile(
        query=body.query,
        domain=body.domain,
        hints=body.hints,
        only_skills=body.only_skills,
        only_tools=body.only_tools,
        max_nodes=max_nodes,
    )


@router.post(
    "/validate",
    response_model=ValidatePlanResponse,
    summary="Statically validate a PlanDAG against the local registries",
)
async def validate_plan_endpoint(
    body: ValidatePlanInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> ValidatePlanResponse:
    return validate_plan(body.plan, skill_host=state.skill_host, tools=state.tools)


@router.post(
    "/execute",
    response_model=ExecutePlanResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Enqueue a `dag` task that runs the supplied PlanDAG",
)
async def execute_plan(
    body: ExecutePlanInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> ExecutePlanResponse:
    if state.task_store is None or state.task_queue is None:
        raise HTTPException(status_code=503, detail="task subsystem not ready")
    if state.workflows is None or not state.workflows.has("dag"):
        raise HTTPException(
            status_code=503,
            detail="`dag` workflow not registered; cannot execute plans",
        )

    pre_check = validate_plan(body.plan, skill_host=state.skill_host, tools=state.tools)
    if not pre_check.ok:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "plan failed validation",
                "errors": pre_check.errors,
                "warnings": pre_check.warnings,
            },
        )

    settings = state.settings
    max_parallel = settings.planner_max_parallel if settings is not None else 4

    plan_payload: dict[str, Any] = body.plan.model_dump(mode="json")
    record = TaskRecord(
        id=uuid.uuid4().hex,
        workflow="dag",
        status="queued",
        query=body.plan.query,
        input={
            "plan": plan_payload,
            "params": dict(body.params),
            "max_parallel": max_parallel,
            "dry_run": body.dry_run,
        },
        budget={},
        user_id=body.user_id or user.id,
        session_id=body.session_id,
    )
    saved = await state.task_store.create(record)
    await state.task_queue.enqueue(saved.id)
    return ExecutePlanResponse(
        task_id=saved.id,
        status=saved.status,
        plan_id=body.plan.plan_id,
        node_count=len(body.plan.nodes),
    )


__all__ = ["router"]
