# backend/AGENTS.md

Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2.x, ARQ. No LangGraph —
workflows are hand-rolled async orchestration in `backend/workflows/`.

## House rules

1. **Type strict.** `from __future__ import annotations` at the top of
   every module. `mypy` is a hard gate.
2. **Pydantic for boundaries.** HTTP I/O, store inputs, queue payloads —
   all Pydantic models. Internal helpers can be plain dataclasses.
3. **No global state.** Everything goes through `AppState`
   (`backend/core/app_state.py`). Tests construct one explicitly.
4. **Async by default.** Sync helpers are fine inside, but the public
   surface (router → service → store) is `async def`.
5. **Errors are typed.** Raise from `backend/core/errors.py`
   (`AAFError` hierarchy). HTTP routers convert via `HTTPException`.

## Layout

```
backend/
├── app.py                ← FastAPI factory + lifespan
├── settings.py           ← Pydantic Settings, single source of env truth
├── api/routers/          ← One file per resource — see api/AGENTS.md
├── core/
│   ├── app_state.py      ← Runtime singletons holder
│   ├── budget.py         ← Tokens / cost / wall-clock guard
│   ├── errors.py         ← AAFError + subclasses
│   ├── events.py         ← Immutable Event + canonical types
│   ├── llm/              ← Provider abstraction (openai/anthropic/ollama/mock)
│   ├── prompt_composer.py
│   ├── rule_engine.py    ← Loads rules/*.md, injects into prompts
│   └── skill_host/       ← Loader, matcher, injector, executor — see its AGENTS.md
├── workflows/            ← BaseWorkflow + concrete workflows — see its AGENTS.md
├── memory/               ← 5 stores + factory — see its AGENTS.md
├── manuscripts/          ← Paper draft + immutable versions
├── tasks/                ← TaskStore + TaskQueue + runner
├── tools/                ← Tool registry
├── proposals/            ← M8.1 gated framework-change records (no auto-apply)
├── planner/              ← M8.2 PlanDAG models + compiler + validator + executor
├── workers/arq_worker.py ← Stand-alone ARQ worker; mirrors lifespan
└── tests/{unit,integration}
```

## Adding any new module

1. Decide which subdirectory it belongs in. If unclear, you're probably
   building a new layer — read `PLAN.md` first.
2. If it has runtime state (DB connection, cache), expose it through
   `AppState` and wire it in `app.py:lifespan` and `workers/arq_worker.py`.
3. If it has HTTP surface, follow `api/AGENTS.md`.
4. Add unit + integration tests. The integration test is mechanically
   required for every router file (consistency check).
5. Run `make check` — `ruff` + `mypy` + `pytest` + frontend typecheck +
   structure invariants.

## Anti-patterns

- Importing `app` or `state` at module top — request scope only.
- Reaching across stores (e.g. router → SQLAlchemy session directly).
  Always go through the store / service abstraction.
- Sync I/O on the request path. Use `httpx.AsyncClient`, `asyncpg`, etc.
- Catching `Exception` to log-and-swallow. Either narrow or re-raise.
