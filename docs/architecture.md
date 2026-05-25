# Architecture

The Academic Agent Framework (AAF) is a self-hosted, LLM-agnostic agent
runtime for academic work — research, paper writing, revision, rebuttal,
survey synthesis. Everything below describes what is **actually
implemented** in `main`. When the code drifts from this document, the
code wins; please send a PR.

## 1. Goals

- **Reproducible**: anyone with the repo, Docker, and an LLM key (or
  `mock`) can stand up the full system in five minutes.
- **LLM-agnostic**: any provider that speaks OpenAI-style chat
  completions (or Anthropic Messages, or Ollama) plugs in via a
  `LLMProvider` Protocol — no vendor SDK in the hot path.
- **Self-orchestrated**: workflows are plain Python coroutines. No
  LangGraph, no DAG library — just `BaseWorkflow.run()`.
- **Portable memory + skills**: `skills/` and `rules/` are markdown
  with YAML frontmatter; the runtime loads them through the Skill Host
  rather than importing Python.
- **Inspectable**: every meaningful side effect (LLM call, tool call,
  memory write, stage transition) is an `Event` on a per-task SSE
  stream.

## 2. Runtime topology

```
                   ┌──────────────────────────────────────────────┐
                   │  Browser (frontend/)                         │
                   │  React 19 + shadcn/ui + TanStack Query +    │
                   │  fetch-event-source                          │
                   └───────────────┬──────────────────────────────┘
                                   │  HTTPS  (or HTTP in dev)
                                   ▼
              ┌────────────────────────────────────────────────────┐
              │  Reverse proxy (nginx in deploy/, Caddy in prod)   │
              │  /          → static SPA (index.html + /assets/)   │
              │  /api/      → FastAPI                              │
              │  /api/.../stream  → FastAPI (SSE; buffering off)   │
              └───────────────┬───────────────────────┬────────────┘
                              │                       │
                              ▼                       ▼
                ┌────────────────────────┐ ┌────────────────────┐
                │  FastAPI app           │ │  ARQ worker        │
                │  backend.app:create_app│ │  backend.workers.  │
                │  Depends on AppState   │ │     arq_worker     │
                └────┬─────────┬─────────┘ └────────┬───────────┘
                     │         │                    │
        ┌────────────┘         │                    │ enqueue
        ▼                      ▼                    ▼
  ┌───────────┐         ┌──────────────┐    ┌───────────────────┐
  │ Postgres  │ ◄────── │ TaskStore    │ ── │ Redis             │
  │ (sql      │         │ (Sql/InMem)  │    │ (ARQ queue +      │
  │  manuscr/ │         │ ManuscriptStr│    │  session memory)  │
  │  task)    │         │ (Sql/InMem)  │    └───────────────────┘
  └───────────┘         └──────────────┘
        │                      │
        ▼                      ▼
  ┌──────────────────────────────────┐
  │  MemoryBundle                    │
  │  ├─ vector  (Chroma | InMem)     │
  │  ├─ knowledge (Yaml | InMem)     │
  │  ├─ heuristic (Yaml | InMem)     │
  │  ├─ episodic  (Sql  | InMem)     │
  │  └─ session   (Redis| InMem)     │
  └──────────────────────────────────┘
                  ▲
                  │ ⇄ embedder (LLMProvider.embed)
                  │
       ┌──────────┴───────────┐
       │ LLM provider         │
       │ openai | anthropic   │
       │ ollama | mock        │
       └──────────────────────┘
```

### 2.1 Single-machine deployment (`deploy/docker-compose.yml`)

Five containers; one image is built (`backend.Dockerfile`) and reused
for both `backend` and `worker`:

| Service     | Image / build                                  | Purpose                                       |
|-------------|------------------------------------------------|-----------------------------------------------|
| `frontend`  | built from `deploy/frontend.Dockerfile`        | nginx serving SPA + reverse-proxying `/api/*` |
| `backend`   | built from `deploy/backend.Dockerfile`         | uvicorn `backend.app:create_app --factory`    |
| `worker`    | same image, `command: arq backend.workers...`  | runs ARQ queue consumer                        |
| `postgres`  | `postgres:16-alpine`                           | manuscripts + tasks + episodic memory          |
| `redis`     | `redis:7.2-alpine`                             | ARQ queue + session memory                     |

A `minio` service is defined under the `storage` profile for the
optional object-store extension.

### 2.2 Local dev

`uvicorn backend.app:create_app --factory --reload` is enough; the
zero-config defaults pick `mock` LLM, in-memory task store/queue,
SQLite (file) for the SQL stores, and YAML stores for knowledge +
heuristics under `./data/`.

## 3. Subsystems

### 3.1 LLM provider layer (`backend/core/llm/`)

- `base.py` declares the `LLMProvider` Protocol plus canonical models
  (`ChatMessage`, `ToolSpec`, `CompletionChunk`, `Usage`,
  `CostEstimate`).
- `registry.py` maps a short name → factory; `default_registry()`
  pre-registers `openai`, `anthropic`, `ollama`, `mock`.
- Concrete adapters (`openai_compat.py`, `anthropic.py`, `mock.py`)
  use raw `httpx` so tests can inject `httpx.MockTransport`.
- See `docs/writing-your-own-llm-provider.md` for the full extension
  recipe.

### 3.2 Skill / Rule / Heuristic stack

| Layer | Lives in              | Loaded by                                | Purpose                              |
|-------|-----------------------|------------------------------------------|--------------------------------------|
| L1    | `skills/<name>/`      | `backend.core.skill_host`                | a capability the agent can invoke    |
| L2    | `rules/*.md`          | `backend.core.rule_engine`               | always-true / sometimes-true rule    |
| L3    | `MemoryBundle.heuristic` (in-process) | `backend.memory.heuristic_store`         | learned strategy block (mutable)     |

L1 + L2 are markdown with YAML frontmatter — portable, model-agnostic,
no Python imports. L3 lives in the memory subsystem and evolves as
runs succeed/fail; see `backend/memory/paper_memory_evolver.py`.

### 3.3 Memory bundle (`backend/memory/`)

`MemoryBundle` exposes five stores; each store has at least one
in-memory backend (zero-dep tests) and at least one durable backend
(production). Selection is driven by `Settings.memory_config()`:

| Store      | Backends                  | Persistence                                    |
|------------|---------------------------|------------------------------------------------|
| vector     | `chroma`, `memory`         | Chroma persist dir → `data/chroma`             |
| knowledge  | `yaml`, `memory`           | one file per `PaperCard` under `data/knowledge`|
| heuristic  | `yaml`, `memory`           | one file per heuristic under `data/skills`     |
| episodic   | `sql`, `memory`            | append-only `Reflection` rows in Postgres/SQLite|
| session    | `redis`, `memory`          | conversation state TTL'd in Redis              |
| documents  | `yaml`, `memory`           | `<root>/<doc_id>/{document.yaml, chunks.yaml}` (M7.3) |

Reads usually happen via `MemoryBundle.snapshot(query, domain)` which
returns a `MemorySnapshot` (vector summary + related papers + heuristics
+ recent reflections **+ doc chunks since M7.3**). Writes are direct:
`bundle.knowledge.write_card(card)` / `bundle.documents.write(doc, chunks)`.

The `documents` store is a free-form RAG layer that complements the
structured `knowledge` cards. Every chunk written through
`DocumentStore.write` is also registered with the shared `VectorStore`
under `metadata.kind="doc_chunk"`, so `MemoryBundle.snapshot()` returns
PaperCards and DocChunks together (deduped by score). Deletes cascade —
`DocumentStore.delete(doc_id)` removes the chunk rows **and** prunes the
vector entries, keeping `vector.count()` honest.

### 3.4 Workflow engine (`backend/workflows/`)

```
backend/workflows/
├── base.py        # BaseWorkflow + WorkflowContext + WorkflowOutput
├── registry.py    # auto-discovery; collisions fail the build
├── demo.py        # smallest example (single LLM call)
├── research.py    # plan → search → read → synthesise
├── write.py       # outline → section drafting → consistency check
└── revision.py    # critique → patch → re-evaluate (loop with budget)
```

Each `BaseWorkflow.run(ctx)` is a plain coroutine. `ctx.stage(name)` is
an async context manager that emits `task.stage_start` /
`task.stage_end` events automatically. LLM calls go through `ctx.llm`
(records cost in `ctx.budget`); tool calls go through `ctx.tools`;
memory writes through `ctx.memory.<store>`. See
`backend/workflows/AGENTS.md` for the side-effect rules.

### 3.5 Task layer (`backend/tasks/` + `backend/workers/arq_worker.py`)

- `TaskRecord` + `TaskEventRecord` are the durable shapes.
- `TaskStore` (`InMemoryTaskStore`, `SqlTaskStore`) persists records
  and per-task event logs.
- `TaskQueue` (`InMemoryTaskQueue`, `ArqTaskQueue`) enqueues runs.
- `RunnerDeps` bundles everything a worker needs (`store`, `workflows`,
  `memory`, `llm`, `tools`, `manuscripts`, `default_budget_usd`); the
  runner reads a `TaskRecord`, instantiates the workflow, and emits
  events back into the store.
- The HTTP `POST /api/tasks` route returns `202 Accepted` with the
  `task_id`; clients consume `/api/tasks/{id}/stream` (SSE) for live
  events or `/api/tasks/{id}/events?after_seq=N` for replay.

### 3.6 Tool registry (`backend/tools/`)

Tools are framework-shared callables (e.g. arxiv search, semantic
scholar lookup, pdf fetch). The registry exposes `names() / has() /
call(name, args, *, allow_network, allow_paid_api)`. Workflows reach
tools via `ctx.tools.invoke(...)`; the HTTP `/api/tools` endpoints are
introspection + debugging only.

### 3.7 Manuscript subsystem (`backend/manuscripts/`)

- `Manuscript` + `ManuscriptVersion` are append-only — every commit
  writes a new version row.
- `ManuscriptStore` (`InMemoryManuscriptStore`, `SqlManuscriptStore`)
  handles CRUD + diff helpers.
- The Write and Revision workflows produce new versions automatically
  by setting `ctx.results["markdown"]` and `ctx.input["manuscript_id"]`;
  the runner hook commits a version on workflow success.

### 3.8 Auth (`backend/core/auth/`)

- Stdlib-only JWT (HS256) + PBKDF2-SHA256 password hashing — no
  external crypto deps.
- `UserStore` is pluggable: `InMemoryUserStore` for tests, default
  `YamlUserStore` for prod (one YAML file per user under
  `Settings.users_dir`).
- `AUTH_DISABLED=true` short-circuits every auth dependency to a
  synthetic anonymous user; that's the default for local dev.
- `AUTH_ALLOW_SIGNUP=true` enables `/api/auth/register`. The first
  user to register becomes `admin` so a fresh deployment always has
  an admin path in.

### 3.9 Gated proposals (`backend/proposals/`) · M8.1

- `Proposal` + `ProposalAuditEvent` Pydantic models with a strict state
  machine: `draft → pending → approved → applied`, plus `withdraw` /
  `reject` exits. Illegal transitions raise `IllegalTransitionError`,
  which the router maps to 409.
- `ProposalStore` Protocol with `InMemoryProposalStore` (tests) and
  `YamlProposalStore` (prod, atomic `tmp + os.replace`) implementations,
  selected via `settings.proposals_backend`.
- The `apply` action **records status only**; it never edits files. A
  future patcher can dispatch into `SkillAdmin` (M7.2) for skill-scoped
  proposals to inherit staging / atomic / rollback.

### 3.10 Planner DAG (`backend/planner/` + `backend/workflows/dag.py`) · M8.2

- `PlanDAG` / `PlanNode` Pydantic models cover five kinds: `llm`,
  `tool`, `skill`, `memory.read`, `memory.write`.
- `PlannerCompiler` prefers LLM JSON-mode (`ctx.llm.complete(json=True)`)
  with a curated skill / tool catalogue and falls back to a single-node
  heuristic when the LLM is missing or returns garbage.
- `validate_plan` is pure (no I/O): id uniqueness, dependency
  reachability, acyclicity, known skill / tool names, minimal arg
  schemas for memory nodes.
- `DAGExecutor` runs topo-layered nodes with bounded `asyncio.gather`,
  per-node retry / `on_failure` (`abort` / `skip` / `continue`), and
  `{"$ref": "node[.field]"}` argument resolution.
- The `dag` workflow (`backend/workflows/dag.py`) is the thin runtime
  host: it deserializes `ctx.input["plan"]`, validates again, and
  delegates to `DAGExecutor.run(...)`. Standard `task.stage_*` SSE
  events surface node progress with no frontend code changes required.

## 4. Lifecycle & boot order

`backend.app.lifespan()` brings everything up in this order (shutdown
runs the inverse):

1. `Settings()` is loaded (env + `.env`).
2. `_build_llm(settings)` picks an `LLMProvider` (falls back to `mock`
   if the configured provider has no credentials — boot must succeed
   even without keys).
3. `MemoryFactory(settings.memory_config(), embedder=llm).build()`
   constructs the `MemoryBundle`.
4. `build_tools()` + `build_workflows()` populate their registries.
5. `_build_task_store(settings)` and `_build_manuscript_store(settings)`
   pick `Sql*` when `database_url` is set, else in-memory.
6. `_build_user_store(settings)` opens `YamlUserStore` if
   `users_dir` is configured.
7. `_build_task_queue(settings, runner_deps)` chooses `arq` only when
   `env=production` AND `redis_url` is set AND `arq` imports.
8. Everything is attached to `AppState` (`app.state.aaf`); routers
   pull it via `Depends(get_app_state)`.

## 5. Request flow — research workflow

```
Browser                  FastAPI                     ARQ Worker             MemoryBundle / LLM
   │                         │                           │                          │
   │ POST /api/tasks         │                           │                          │
   │ {workflow:"research"}   │                           │                          │
   │ ──────────────────────▶ │                           │                          │
   │                         │ store.create(record)      │                          │
   │                         │ queue.enqueue(task_id)    │                          │
   │ ◀── 202 task_id         │                           │                          │
   │                         │                           │ pop task                 │
   │                         │                           │ load workflow            │
   │ GET /api/tasks/{id}/stream                           │ ctx.stage("plan")        │
   │ ──────────────────────▶ │                           │   await ctx.llm.complete │ ─▶ provider.complete()
   │                         │ store.events(after_seq=N) │                          │
   │ ◀ SSE task.stage_start  │ ◀── ───────────────────── │                          │
   │ ◀ SSE llm.token_delta   │                           │                          │
   │ ◀ SSE memory.write      │                           │ bundle.knowledge.write   │
   │ ◀ SSE task.end          │                           │ store.mark_completed()   │
```

## 5b. Request flow — paper ingest (M7.1)

```
Browser                  FastAPI                                   MemoryBundle / LLM
   │                         │                                          │
   │ POST /api/knowledge/papers/ingest                                   │
   │ multipart: file=paper.pdf, tags="agent,memory"                      │
   │ ──────────────────────▶ │                                          │
   │                         │ pdf_to_markdown(raw)                     │
   │                         │ PaperExtractor.extract()                 │ ─▶ llm.complete (optional)
   │                         │ ──────────────────────────────────────▶  │
   │                         │ ◀── ExtractedPaper{title,authors,...}    │
   │                         │                                          │
   │                         │ knowledge.write_card(card)               │
   │                         │ vector.add(paper_id, search_text())      │
   │                         │                                          │
   │                         │ evolver.evolve_new_paper(card)           │ ─▶ vector.query(k=5)
   │                         │                                          │ ─▶ llm.complete (typed-link inference)
   │                         │ ◀── EvolutionResult{links, tags}         │
   │                         │                                          │
   │                         │ evolver.check_synthesis_trigger(top_tag) │
   │ ◀── 201 IngestPaperResponse                                         │
```

Key invariants:

- `source_run_id = "ingest:<paper_id>"` everywhere — one rollback call
  reverses the whole pipeline.
- LLM and evolver each *soft-fail*: an extractor exception falls back
  to the heuristic regex path; an evolver exception is logged and
  reported as `evolution.mode = "skip"` with a reason.
- The pipeline is reused by the SDK (`KnowledgeAPI.ingest_paper`) and
  the frontend "Ingest paper" drawer — same code path.

## 5c. Request flow — document ingest (M7.3)

```
Browser                  FastAPI                                   MemoryBundle / VectorStore
   │                         │                                          │
   │ POST /api/documents/ingest                                          │
   │  multipart file=notes.md  OR  json {title,raw_text,tags}            │
   │ ──────────────────────▶ │                                          │
   │                         │ decode_blob(raw)  → markdown body        │
   │                         │ chunk_markdown(body, target=800)         │
   │                         │   ↳ heading-aware sliding window         │
   │                         │   ↳ atomic code fences / table rows      │
   │                         │                                          │
   │                         │ documents.write(doc, chunks)             │
   │                         │   ↳ vector.add(chunk_id, text, metadata) │
   │                         │                                          │
   │ ◀── 201 IngestDocumentResponse{document, chunks_indexed}            │
```

Recall path (any workflow's RECALL stage):

```
ctx.memory.snapshot(query)
  ├── knowledge.find_related(query)             # PaperCards, keyword overlap
  ├── documents.search_chunks(query, k)         # filtered to kind=doc_chunk
  │     └── vector.query(query, where={"kind": "doc_chunk"})
  └── …
returns MemorySnapshot{ related_papers, doc_chunks, … }
```

Key invariants:

- `chunk_id = f"{doc_id}#{idx:04d}"` — deterministic, so re-indexing the
  same document never breaks links from prior runs.
- Every `delete()` and `rollback_run()` cascades into the vector store;
  `vector.count()` is the canonical leak detector for tests.
- The chunker never splits code fences (```` ``` ````) or table rows
  (`|...|`) — they are treated as atomic blocks.
- The pipeline is reused by the SDK (`AsyncDocumentsAPI.ingest_text` /
  `ingest_file`) and the frontend `Knowledge Library` page — same code
  path, no shadow re-implementation.

## 5d. Gated proposals (M8.1)

```
Browser              FastAPI                          ProposalStore
   │                    │                                  │
   │ POST /api/proposals (CreateProposalInput)             │
   │ ─────────────────▶ │                                  │
   │                    │ store.create()  → status=draft   │
   │                    │ append audit{action:create}      │
   │ ◀── 201 Proposal   │                                  │
   │                    │                                  │
   │ POST /api/proposals/{id}:submit                       │
   │ ─────────────────▶ │ _check_transition(...)           │
   │                    │ store.transition()  draft→pending│
   │                    │ append audit{action:submit}      │
   │                    │                                  │
   │ POST /api/proposals/{id}:approve  (admin)             │
   │ ─────────────────▶ │ pending → approved               │
   │                    │                                  │
   │ POST /api/proposals/{id}:apply    (admin)             │
   │ ─────────────────▶ │ approved → applied               │
   │                    │ ⚠ records status; does NOT       │
   │                    │   modify any files on disk       │
```

Invariants:

- The store is the single source of state-machine truth. Routers raise
  409 on illegal transitions; everything else is append-only audit.
- `apply` deliberately decouples "approval" from "deploy". The diff
  field carries the change; humans / CI consume it.
- A future "auto-apply for skills/" mode will dispatch to `SkillAdmin`
  (M7.2) and reuse staging / atomic / rollback there — no file writes
  ever happen from the proposals router itself.

## 5e. Planner DAG (M8.2)

```
Browser            FastAPI / Planner          DAGExecutor / Task system
   │                  │                              │
   │ POST /api/planner/compile  {query, hints, ...}  │
   │ ───────────────▶ │ skills_for_compile(...)      │
   │                  │ LLM JSON-mode (or fallback)  │
   │                  │ → PlanDAG                    │
   │ ◀── 200 PlanDAG  │                              │
   │                  │                              │
   │ POST /api/planner/validate {plan}               │
   │ ───────────────▶ │ validate_plan() — cycles /   │
   │                  │   unknown nodes / args       │
   │ ◀── ValidatePlanResponse                        │
   │                  │                              │
   │ POST /api/planner/execute {plan}                │
   │ ───────────────▶ │ tasks.create(workflow="dag", │
   │                  │   input={"plan": ...})       │
   │ ◀── 202 task_id  │ ──────────────────────────▶  │ DAGWorkflow.run(ctx)
   │                  │                              │   topo_layers + gather
   │ GET /api/tasks/{id}/stream                      │   per-node retry
   │ ───────────────▶ │                              │   on_failure semantics
   │ ◀ SSE task.stage_start/end {node_id, kind, ...} │
   │ ◀ SSE task.end   │                              │
```

Invariants:

- `compile` is best-effort: a missing or misbehaving LLM falls back to
  a single-node `memory.read → llm` plan so the operator can still try.
- `validate` is pure: no I/O, no LLM calls. The router calls it again
  before `execute` regardless of what the client did.
- The `dag` workflow reuses `WorkflowContext` collaborators
  (`ctx.memory`, `ctx.llm`, `ctx.tools`, `ctx.skill_host`) — DAG nodes
  see the same runtime as built-in workflows.
- Argument dataflow uses `{"$ref": "node[.field]"}` placeholders only.
  The minimum viable wiring; resist templating creep.

## 6. SSE conventions

| Channel                                | Event types emitted                                        |
|----------------------------------------|------------------------------------------------------------|
| `POST /api/workflows/{name}/stream`    | direct workflow events; live for the request               |
| `GET  /api/tasks/{id}/stream`          | replay-then-tail polling against the durable event log     |

Common event types: `task.start`, `task.stage_start`, `task.stage_end`,
`task.end`, `task.error`, `task.retry`, `llm.token_delta`, `llm.usage`,
`tool.invoke`, `tool.result`, `memory.write`, `skill.invoke`. The
frontend `EventTimeline` component groups them by stage. The DAG
workflow reuses `task.stage_*` with `data.stage = "node:<id>"` and
`data.{node_id, kind, status, attempts, duration_ms, error}`.

## 7. Mocks & determinism

- `MockLLMProvider` returns canned chunks based on the prompt — used
  by every unit test.
- `InMemoryTaskQueue` runs the workflow inline (`asyncio.create_task`)
  so end-to-end tests don't need Redis.
- `InMemoryTaskStore`, `InMemoryManuscriptStore`, `InMemoryUserStore`,
  in-memory memory backends, `respx`-friendly httpx clients — every
  external dependency has a stub, and CI runs entirely without
  Postgres / Redis.

## 8. Where to make changes

| You want to…                                | Touch                                              |
|---------------------------------------------|----------------------------------------------------|
| Add an HTTP endpoint                        | `backend/api/routers/<area>.py` and register in `app.py` |
| Add a new workflow                          | `backend/workflows/<name>.py` + a unit test         |
| Add a new tool                              | `backend/tools/<name>.py` + register in `build_default_registry()` |
| Add a new LLM provider                      | `backend/core/llm/<name>.py` + extend `register_defaults()` |
| Add a new skill (capability)                | `skills/<name>/SKILL.md` (+ optional `script.py`)  |
| Add a new behaviour rule                    | `rules/<short-kebab>.md`                            |
| Promote a behaviour to a static check       | `scripts/check_consistency.py`                      |

Mechanical invariants are enforced by `make consistency`. CI fails the
build if any check returns non-zero — so once your change passes
locally, it's safe to push.
