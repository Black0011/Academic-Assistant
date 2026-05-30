"""``dag`` workflow — runs a compiled :class:`PlanDAG` (M8.2).

Invoked via ``POST /api/planner/execute`` which enqueues a task with
``workflow="dag"`` and ``input={"plan": <PlanDAG dict>, "params": {...}}``.

The workflow itself is a thin wrapper around
:class:`backend.planner.executor.DAGExecutor`: we deserialize the plan,
build an executor with the same collaborators every other workflow has
(``ctx.memory``, ``ctx.llm``, ``ctx.tools``, ``ctx.skill_host``), and
emit ``task.start`` / ``task.end`` framing events so the existing
SSE consumers see a well-formed timeline.

Why a dedicated workflow class instead of running inline in the
router? Because the existing :class:`backend.tasks.runner` already
provides:

* persisting the run record to :class:`TaskStore`,
* SSE fan-out via the event sink,
* ARQ-backed durability when configured,

and we get all of that for free by going through the registry.
"""

from __future__ import annotations

from typing import Any

from backend.core.events import Event, EventType
from backend.planner import (
    DAGExecutor,
    PlanDAG,
    validate_plan,
)
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput


class DAGWorkflow(BaseWorkflow):
    """Executes a pre-compiled :class:`PlanDAG` from ``ctx.input["plan"]``."""

    name = "dag"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        raw_plan = (ctx.input or {}).get("plan")
        if not isinstance(raw_plan, dict):
            await ctx.emit(
                Event(
                    EventType.TASK_ERROR,
                    data={"error": "missing or invalid 'plan' in task input"},
                )
            )
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                error="missing or invalid 'plan' in task input",
                trace=list(ctx.trace),
            )

        try:
            plan = PlanDAG.model_validate(raw_plan)
        except Exception as exc:
            await ctx.emit(
                Event(
                    EventType.TASK_ERROR,
                    data={"error": f"plan parse failed: {exc}"},
                )
            )
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                error=f"plan parse failed: {exc}",
                trace=list(ctx.trace),
            )

        validation = validate_plan(plan, skill_host=ctx.skill_host, tools=ctx.tools)
        if not validation.ok:
            await ctx.emit(
                Event(
                    EventType.TASK_ERROR,
                    data={
                        "error": "plan failed validation",
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                    },
                )
            )
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                error="plan failed validation: " + "; ".join(validation.errors),
                trace=list(ctx.trace),
            )

        params: dict[str, Any] = (ctx.input or {}).get("params") or {}
        max_parallel = int((ctx.input or {}).get("max_parallel") or 4)

        await ctx.emit(
            Event(
                EventType.TASK_START,
                data={
                    "workflow": "dag",
                    "plan_id": plan.plan_id,
                    "nodes": len(plan.nodes),
                    "query": plan.query,
                },
            )
        )

        executor = DAGExecutor(
            memory=ctx.memory,
            llm=ctx.llm,
            tools=ctx.tools,
            skill_host=ctx.skill_host,
            max_parallel=max_parallel,
        )

        verdict, outcomes = await executor.run(plan, ctx=ctx, params=params)

        await ctx.emit(
            Event(
                EventType.TASK_END,
                data={
                    "verdict": verdict,
                    "plan_id": plan.plan_id,
                    "node_count": len(outcomes),
                    "succeeded": sum(1 for o in outcomes.values() if o.status == "succeeded"),
                    "failed": sum(1 for o in outcomes.values() if o.status == "failed"),
                    "skipped": sum(1 for o in outcomes.values() if o.status == "skipped"),
                },
            )
        )

        results = {
            "plan_id": plan.plan_id,
            "verdict": verdict,
            "outcomes": {nid: o.model_dump() for nid, o in outcomes.items()},
        }
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict=verdict,
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )
