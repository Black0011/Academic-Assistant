# backend/planner/AGENTS.md

Optional `PlannerAgent` (M8.2) — turn a natural-language goal into a
declarative `PlanDAG`, then run it through the existing Task system.

The planner is **decoupled** from the built-in workflows: it doesn't
replace `research` / `write` / `revision`. It exists for hosts that
want "compile then execute" semantics and for LLM-side orchestration
where each node may itself be a skill, tool, memory op, or LLM call.

## Layout

```
backend/planner/
├── __init__.py        ← exports models + compiler + executor + validator
├── models.py          ← NodeKind / OnFailure / NodeStatus / PlanNode / PlanDAG / NodeOutcome
├── compiler.py        ← PlannerCompiler — LLM JSON-mode + heuristic fallback
├── validator.py       ← validate_plan() — cycles / unknown refs / id uniqueness
└── executor.py        ← DAGExecutor — topo layers + parallel + retry + on_failure
```

The HTTP surface lives at `backend/api/routers/planner.py` and the runtime
host is `backend/workflows/dag.py` (the `dag` workflow, registered like
any other).

## Pipeline

```
query
  ▼
PlannerCompiler.compile()        # LLM → JSON → PlanDAG (or fallback)
  ▼
validate_plan()                  # router enforces ok=True before /execute
  ▼
POST /api/planner/execute        # 202 + task_id (workflow="dag")
  ▼
DAGWorkflow.run(ctx)             # framing events
  ▼
DAGExecutor.run(plan, ctx, ...)  # topo + gather + retry + SSE
  ▼
TaskRecord {status, results, trace}
```

## Compiler contract

- LLM call goes via `ctx.llm.complete(... json=True)` when available;
  failure (no provider, parse error, schema mismatch) falls back to a
  single-node memory.read + LLM-summarise plan.
- The compiler curates the available skills / tools per call. To narrow
  scope, callers set `only_skills` / `only_tools`. Empty = let the LLM
  pick anything from the registry.
- `max_nodes` truncates compiler output. Keep the cap modest (default
  30) — long DAGs fail validation more often than they help.

## Executor invariants

1. **Topology is computed once.** `topo_layers` returns `None` on a
   cycle; the executor refuses to run.
2. **Per-layer parallelism.** `asyncio.gather` within a `Semaphore`
   bounded by `max_parallel`. Don't add cross-layer parallelism — it
   breaks dataflow.
3. **Per-node retry.** Exponential backoff capped at `node.retries + 1`
   total attempts. Emits `task.retry` between attempts.
4. **Failure handling.**
   - `abort` → DAG verdict becomes `error`; descendants `skipped`.
   - `skip` → only descendants `skipped`; siblings keep running.
   - `continue` → descendants run with `output={}` for the failed dep.
5. **Argument resolution.** `args` values shaped `{"$ref": "node[.field]"}`
   are replaced with upstream node outputs. The minimum useful dataflow
   primitive — don't smuggle in templating.

## SSE shape

The executor emits the standard `task.stage_start` / `task.stage_end`
events with:

```jsonc
// task.stage_start
{ "stage": "node:<id>", "node_id": "<id>", "kind": "tool", "name": "...", "description": "..." }
// task.stage_end
{ "stage": "node:<id>", "node_id": "<id>", "status": "succeeded",
  "attempts": 1, "duration_ms": 42, "error": "" }
```

The frontend `useTaskStream` consumer projects these back onto the
graph; don't invent new event types.

## Don'ts

- Don't add a global "planner state" — every compile / execute is a
  pure function call against `ctx`.
- Don't write to memory / disk from the validator. It's a pure check.
- Don't reach into `backend/workflows/*` from the planner subsystem;
  the only crossover point is the `dag` workflow.

## Tests

- `backend/tests/unit/test_planner_validator.py` — id uniqueness,
  cycle detection, unknown skill / tool, missing dep, self-loop.
- `backend/tests/unit/test_planner_compiler.py` — JSON extraction,
  malformed nodes, fallback when LLM is missing or returns garbage.
- `backend/tests/unit/test_planner_executor.py` — topo, `$ref`,
  failure modes, retry semantics, event emission.
- `backend/tests/integration/test_app_planner.py` — `compile` with a
  mocked LLM, `validate` rejecting cycles, `execute` end-to-end via
  the task runner.
