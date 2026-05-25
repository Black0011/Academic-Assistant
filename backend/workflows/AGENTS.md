# backend/workflows/AGENTS.md

Self-orchestrated agent loops. **No LangGraph.** Each workflow is a
`BaseWorkflow` subclass; the registry auto-discovers everything in this
package.

## Contract

```python
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput

class WriteWorkflow(BaseWorkflow):
    name = "write"             # required, kebab-case, unique
    version = "1.0.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        async with ctx.stage("plan"):
            ...
        async with ctx.stage("draft"):
            ...
        return WorkflowOutput(verdict="ok", results={...})
```

Every concrete subclass with a non-empty `name` is registered at boot.
`name` collisions fail the build.

## Stages and events

- Use `async with ctx.stage("<name>"):` for every meaningful phase. The
  context manager emits `task.stage_start` / `task.stage_end`; the SSE
  layer renders them as a timeline (see `frontend/src/components/research/EventTimeline.tsx`).
- Stage names: snake_case, ≤16 chars. Canonical sequence for academic
  workflows: `plan → search → read → write → evaluate → evolve`.
- For LLM, tool, and memory side effects, use the helpers in
  `WorkflowContext` so `llm.*`, `skill.*`, `memory.*` events fire
  automatically.

## Side-effect rules

| Side effect                     | Mechanism                                                           |
| ------------------------------- | ------------------------------------------------------------------- |
| LLM call                        | `await ctx.llm.generate(...)` (records token+cost in `ctx.budget`)  |
| Skill execution                 | `await ctx.skill_host.invoke(...)`                                  |
| Tool call                       | `await ctx.tools.invoke(name, args)`                                |
| Memory write                    | `await ctx.memory.<store>.upsert(...)`                              |
| Persisting a paper version      | Write `ctx.results["markdown"]` and set `ctx.input["manuscript_id"]`; the runner hook commits a new manuscript version automatically. |

Don't open new HTTP clients, DB sessions, or file handles inside `run()` —
take them from `ctx`.

## Long tasks

The runner converts a workflow run into a task. To trigger it:

```bash
POST /api/tasks
{
  "workflow": "<name>",
  "query": "...",
  "input": {...},
  "budget_usd": 1.5
}
```

The frontend Research Console submits this exact payload.

## Adding a workflow — checklist

1. New file: `backend/workflows/<name>.py`. One workflow per file.
2. Subclass `BaseWorkflow`, set `name`. Implement `async def run`.
3. Add a unit test in `backend/tests/unit/test_workflow_<name>.py`
   with `MockLLMProvider`.
4. Add an integration test in `backend/tests/integration/test_app_workflows.py`
   that posts to `/api/workflows/<name>/run` with a tiny budget.
5. `make consistency` — verifies the class has a `name` and the discovery
   layer can import it.

## M8.2 — `dag` workflow

`backend/workflows/dag.py` is the host for the **PlannerAgent** path.
Instead of hand-coding stages it accepts a pre-compiled `PlanDAG` in
`ctx.input["plan"]` (produced by `POST /api/planner/compile`) and delegates
node execution to `backend.planner.executor.DAGExecutor`. The executor
emits the *same* `task.stage_start` / `task.stage_end` events any other
workflow would, so the existing SSE timeline renders DAG nodes for free.

Trigger:

```bash
POST /api/planner/execute   # 202 + task_id   (preferred)
POST /api/tasks             # workflow="dag", input={"plan": {...}}
```

Don't reach into `backend.planner.*` from any other workflow — keep the
boundary clean. If you need DAG-style execution inside a custom
workflow, build a `PlanDAG` in memory and call `DAGExecutor.run`
directly.
