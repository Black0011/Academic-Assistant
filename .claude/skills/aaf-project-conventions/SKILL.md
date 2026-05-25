---
name: aaf-project-conventions
description: >-
  Global conventions for writing ANY code in the Academic Agent Framework
  (AAF) repository: directory layout, naming, dependencies, logging, error
  handling, commit messages, and test layout. Load this skill before writing
  or reviewing any AAF code so all modules stay consistent.
domain: engineering
triggers:
  - aaf
  - academic agent framework
  - add module
  - new file in backend
  - new file in frontend
version: "1.0.0"
---

# AAF Project Conventions

Read this FIRST before writing any code in the `academic-agent-framework/` repo.

## 1. Directory layout (authoritative)

See `PLAN.md` §5. Three non-negotiables:

- **`skills/` and `rules/`** — project root, runtime assets (L1 / L2). Never put framework code here.
- **`backend/core/`** — framework internals (skill host, rule engine, LLM layer). Must not import from `backend/agents/` or `backend/workflows/`.
- **`.cursor/`** — dev-time only. Never reference `.cursor/` paths from runtime code; those paths do not exist in the deployed Docker image.

## 2. Python conventions

- **Python 3.11+** only. Use `match`, `|`-unions, `Self`, `TaskGroup`.
- **Type hints everywhere.** `mypy --strict`-compatible.
- **async first.** All I/O (LLM, HTTP, DB, file ops when large) must be async. Sync helpers only for pure computation.
- **Dependencies managed with `uv`.** Add to `pyproject.toml`, run `uv sync`.
- **Import order:** stdlib / third-party / first-party (`backend.*`), blank line between groups. `ruff` will enforce.
- **Naming:**
  - modules: `snake_case.py`
  - classes: `PascalCase`
  - functions / variables: `snake_case`
  - constants: `UPPER_SNAKE`
  - private: `_leading_underscore`
- **Never use `print`.** Use `structlog.get_logger(__name__)` and log key-value pairs:
  ```python
  log = structlog.get_logger(__name__)
  log.info("skill.loaded", name=skill.name, path=str(skill.path))
  ```
- **Errors:** raise a subclass of `backend.core.errors.AAFError`; never raise bare `Exception`. API layer maps exception subclass → HTTP status via `backend.api.errors.exception_handlers`.
- **No module-level side effects.** Don't open files / connect DBs at import time. Use FastAPI lifespan or a `Registry` class.

## 3. TypeScript / React conventions

- **React 19 + TypeScript strict.** Functional components only; no class components.
- **Component files:** `PascalCase.tsx`; props interface declared inline or adjacent.
- **UI state** via **Zustand** (one store per feature area); **server state** via **TanStack Query** (see `aaf-frontend-react` skill).
- **Hooks** start with `use*` and live in `frontend/src/hooks/`.
- **API calls** only go through `frontend/src/api/*.ts` wrappers and TanStack Query hooks — never `fetch()` inside components.
- **Style:** **Tailwind CSS v4** utilities + **shadcn/ui** primitives (sources in `frontend/src/components/ui/`). **No CSS-in-JS.** No custom CSS files for components (only theme tokens in `src/styles/globals.css`).
- **Forms:** `react-hook-form` + `zod`; error mapping follows `aaf.*` error codes.

## 4. Dependency policy

- Python deps: must be listed in `pyproject.toml` with a **minimum version**, never pinned exactly.
- Frontend deps: use **`pnpm`** (not npm/yarn). `pnpm add -E` (exact) for runtime deps that must be reproducible; `pnpm add` (caret) for dev tools.
- **No LangChain / LangGraph / CrewAI / AutoGen.** Orchestration is self-written (PLAN §10).
- Before adding any new dependency, ask: "Can I do this in < 100 lines of std code?" If yes, don't add the dep.

## 5. Testing

- **Unit tests:** `backend/tests/unit/<module>.py`, every non-trivial function. Use `pytest` + `pytest-asyncio`.
- **Integration tests:** `backend/tests/integration/*.py`, use the `MockLLMProvider` from `backend/core/llm/mock.py`.
- **Skill evals:** every skill in `skills/<name>/` may ship an `evals/` folder; runnable via `aaf skill test <name>`.
- **Coverage target:** 80% for `backend/core/` and `backend/agents/`.

## 6. Logging and telemetry

- One logger per module: `log = structlog.get_logger(__name__)`.
- Standard event names: `<subsystem>.<action>` — e.g. `skill.loaded`, `llm.request`, `workflow.stage_end`.
- Every log line must include enough context to filter by `task_id`, `user_id`, `provider`, `workflow`.
- Log **values**, not interpolated strings: `log.info("x", foo=foo)` not `log.info(f"x {foo}")`.

## 7. Commit messages

Conventional Commits: `<type>(<scope>): <subject>`.

- `feat(skill-host): add hot-reload on SIGHUP`
- `fix(llm): correct anthropic tool_use mapping`
- `refactor(memory): rename SkillStore → HeuristicStore`
- `docs(plan): clarify checkpoint semantics`
- `test(skill-host): cover fallback path`
- `chore(deps): bump fastapi`

## 8. Documentation

- Every public function/class has a **docstring** stating purpose, params, raises.
- Non-obvious constants go in `backend/core/constants.py` with a comment explaining *why*.
- If you add a new concept, update `PLAN.md` in the same PR.

## 9. What NOT to do

- Don't bypass `MemoryBundle` to read raw YAML / Chroma directly.
- Don't call an LLM SDK (`openai`, `anthropic`) directly from an agent or workflow. Always go through `LLMProvider`.
- Don't hard-code skill names in workflow logic. Use `skill_host.match(...)`.
- Don't write into `data/` from unit tests — use `tmp_path` fixture.
- Don't put business logic in API routers; routers only glue request → workflow and response.
- Don't silently swallow exceptions. If you must catch, log and re-raise or convert to `AAFError`.

## 10. Pull request checklist

Before submitting a PR:

- [ ] `make fmt lint typecheck test` all pass
- [ ] New deps justified (see §4)
- [ ] `PLAN.md` updated if you changed architecture
- [ ] New ENV vars added to `.env.example`
- [ ] New API endpoints have OpenAPI description + Pydantic schemas
- [ ] No `TODO` without an issue number
