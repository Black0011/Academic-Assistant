---
name: aaf-agent-workflow
description: >-
  How to write AAF agents (Planner/Executor/Evaluator/Evolver) and workflows
  on top of the self-built async orchestration engine. AAF does NOT use
  LangGraph — this skill defines the substitute conventions. Load when
  editing backend/agents/ or backend/workflows/.
domain: engineering
triggers:
  - new agent
  - new workflow
  - planner
  - executor
  - evaluator
  - evolver
  - backend/agents
  - backend/workflows
version: "1.0.0"
---

# AAF Agents & Workflows — Authoring Guide

AAF intentionally ships **no** LangGraph / LangChain. The engine is ~300 LOC of plain async Python (`backend/workflows/base.py`). See `PLAN.md` §10.

## 1. The four agents

Each agent is a **stateless class** with one main async method. Constructor takes dependencies via DI; no global state.

```python
class Planner:
    def __init__(self, llm: LLMProvider, skill_host: SkillHost,
                 rule_engine: RuleEngine, prompts: PromptLoader): ...
    async def plan(self, ctx: WorkflowContext,
                   mem_summary: MemorySnapshot,
                   heuristics: list[HeuristicSkill]) -> list[Task]: ...

class Executor:
    async def execute(self, ctx: WorkflowContext, task: Task) -> TaskResult: ...

class Evaluator:
    async def evaluate(self, ctx: WorkflowContext,
                       results: list[TaskResult]) -> Verdict: ...

class Evolver:
    async def evolve(self, ctx: WorkflowContext, verdict: Verdict) -> EvolveReport: ...
```

Rules:
- Agents access LLM/memory/skills **only via `WorkflowContext`**. Never hold references in instance state.
- Agents never spawn subprocesses directly — use `ctx.skill_host.call_tool(...)`.
- Prompts come from `prompts/<agent>/*.md` loaded by `PromptLoader`; never hardcode in Python.
- Agent outputs are **Pydantic models**, not dicts.

## 2. WorkflowContext — what it carries

```python
class WorkflowContext:
    task_id: str
    user_id: str | None
    session_id: str | None
    query: str
    input: dict
    llm: LLMProvider
    memory: MemoryBundle
    skill_host: SkillHost
    rule_engine: RuleEngine
    budget: Budget
    state: dict                 # workflow-free-form state
    trace: list[Event]
    checkpoint_enabled: bool

    async def emit(self, event: Event) -> None: ...
    async def checkpoint(self, label: str) -> None: ...
```

Rules:
- Mutable `state` dict is the only place for cross-stage data. Keep keys documented.
- Don't stash big artifacts in `state`; write them to `data/` and keep file paths.

## 3. Writing a new workflow

File: `backend/workflows/<name>.py`. Subclass `BaseWorkflow`:

```python
class MyWorkflow(BaseWorkflow):
    name: ClassVar[str] = "my_workflow"
    version: ClassVar[str] = "1.0.0"

    def __init__(self, planner, executor, evaluator, evolver): ...

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        snap = await ctx.memory.snapshot(ctx.query, domain="research")
        tasks = await self.stage(ctx, "planner",
            lambda c: self.planner.plan(c, snap, snap.heuristics))
        ...
```

Use `self.stage(ctx, name, fn)` to wrap each stage — it handles:
- `emit` start/end events
- timing
- budget check
- exception propagation
- optional checkpoint

## 4. Primitives

From `backend/workflows/primitives.py`:

```python
sequential(ctx, stages)
parallel(ctx, stages, max_concurrency=4)
retry(ctx, fn, max_attempts=2, on=lambda e: True)
branch(ctx, predicate, if_true, if_false)
loop_until(ctx, fn, until, max_iter=3)
```

All return the collected output. Prefer writing straight `await a(); await b()` when a primitive isn't needed.

## 5. Event names

Follow `PLAN.md` §23.5. Standard per-stage events are emitted automatically by `self.stage(...)`. Emit custom events with the convention `task.<domain>.<action>`:

- `task.memory.knowledge_write`
- `task.tool.call` / `task.tool.result`
- `task.retry`

## 6. Registering a workflow

Workflow discovery is automatic: at startup `backend.workflows.registry` scans `backend/workflows/*.py` and `backend/workflows/custom/*.py` for `BaseWorkflow` subclasses. If your class attribute `name` is set, the API route `/api/v1/<name>` is auto-registered.

Don't manually register in `main.py`. If autoload fails, the issue is a missing `name` attribute or a import-time side effect.

## 7. Retry and loop conventions

- Default retry count for transient failures: 2 (i.e., total attempts 3).
- Per-stage budget enforcement: `ctx.budget.assert_ok()` inside `self.stage()` runs first.
- A full-workflow retry happens by recursive `run(ctx)` with `ctx.state["retry_count"]` set — do NOT build a separate state machine.

## 8. Tests

For every workflow:

- `backend/tests/integration/workflows/test_<name>.py`
- Inject `MockLLMProvider` + `InMemoryMemoryBundle` + real `SkillHost` pointed at `backend/tests/fixtures/skills/`.
- Assert: (1) exit status, (2) required events were emitted in order, (3) memory writes happened.

## 9. Prompt templates

One Jinja2 file per agent call: `prompts/<agent>/<purpose>.md` (e.g. `prompts/planner/base.md`, `prompts/evolver/extract.md`). Variables injected by `PromptLoader.render(name, **ctx)`.

Never concatenate strings to build a prompt inside Python code.

## 10. Non-goals

- Don't introduce a "tool-using agent" that loops on its own without stages.
- Don't share mutable state across workflow instances.
- Don't open DB/LLM connections in `__init__` — rely on the DI layer.
- Don't call `ctx.emit` after `run()` returns.

## 11. Checklist for new workflow PR

- [ ] New file under `backend/workflows/` with a `BaseWorkflow` subclass
- [ ] Prompts in `prompts/<agent>/` with Jinja2 syntax
- [ ] API auto-route verified by `curl /api/v1/<name>`
- [ ] Integration test using `MockLLMProvider`
- [ ] Events observed via SSE happy-path test
- [ ] `PLAN.md` §10.5 table updated if this is a predefined workflow
