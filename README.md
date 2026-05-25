# Academic Agent Framework (AAF)

> LLM-agnostic academic agent framework with a self-hosted Skill runtime.

**Status**: ✅ M0–M6 delivered. 🚧 **M7 in flight** — three independent
self-management capabilities being added in parallel: Paper Ingest pipeline
(M7.1), Skill management API + UI (M7.2), Knowledge Document RAG (M7.3);
spec at [`PLAN.md`](./PLAN.md) §20.8.

Single-host Docker stack lives in
[`deploy/`](./deploy/) (with a TLS overlay at
[`docker-compose.prod.yml`](./docker-compose.prod.yml) +
[`deploy/caddy/Caddyfile.example`](./deploy/caddy/Caddyfile.example)),
the Python SDK at [`sdk/python/`](./sdk/python/), and full docs at
[`docs/`](./docs/). See [`PLAN.md`](./PLAN.md) §20 for the milestone
table and [`AGENTS.md`](./AGENTS.md) for the agent / contributor map.

AAF turns the Academic-Agent system (originally a Cursor-only research assistant) into a **standalone, privately deployable, LLM-agnostic agent framework** for academic work — literature survey, paper writing, revision, rebuttals, surveys, and presentations.

## Why this exists

Cursor and Claude Code have built excellent **skill hosts** — mechanisms that discover skills on disk, inject them into prompts, and execute bundled scripts. But those runtimes only work inside Cursor/Claude Code.

AAF implements its own skill host, so you can:

- Run any of the 15 academic Skills (autoresearch, paper-writing, paper-revision, rebuttal-writer, …) **with any LLM** (OpenAI, Anthropic, Ollama, vLLM, DeepSeek, …).
- Deploy to **your own server**, keep all your papers / notes / memories local.
- Use via **web UI, REST API, Python SDK, or CLI** — same code.

## Three layers of "skill"

| Layer | Location | What | Who writes | Who reads |
|---|---|---|---|---|
| **L1 · Capability** | `skills/<name>/SKILL.md` | What the agent can do (paper-writing, etc.) | Humans | AAF Skill Host at runtime |
| **L2 · Behavior rule** | `rules/*.md` | What the agent must / must not do | Humans | AAF Rule Engine |
| **L3 · Heuristic** | `data/skills/<domain>/*.yaml` | Learned strategies from past runs | AAF Evolver (auto) | AAF Planner |

## Quick start

**Production-style (Docker Compose)** — see [`deploy/README.md`](./deploy/README.md) for the full guide:

```bash
git clone <repo> academic-agent-framework
cd academic-agent-framework
cp .env.example .env                      # fill AAF_SECRET_KEY + ≥1 LLM key
make up                                   # builds aaf-backend + aaf-web, boots 5 services
open http://localhost:8080                # first /register becomes admin
```

**Local development** — backend + frontend on the host, Postgres / Redis still in compose:

```bash
make install
docker compose up -d postgres redis       # storage only
make dev                                  # uvicorn (reload) + vite (HMR)
```

## Project layout

```
skills/                 L1 capability skills
rules/                  L2 behavior rules
data/skills/            L3 heuristic skills (per-domain)
data/knowledge/         Paper cards, typed_links, findings
data/chroma/            Local vector store
prompts/                All LLM prompt templates (Jinja2)
backend/                FastAPI app, agents, workflows, memory, tools
frontend/               React 19 SPA (Vite + shadcn/ui + TanStack Query)
sdk/                    Python & TypeScript SDKs
cli/                    `aaf` command-line
deploy/                 Docker / Nginx / Postgres init
.cursor/                Dev-time-only skills & rules (aaf-*) used when coding AAF itself
docs/                   Additional documentation
```

## Engineering convention — Harness Engineering

We follow the [Harness Engineering](https://openai.com/zh-Hans-CN/index/harness-engineering/)
discipline: humans design constraints, the agent does the work, and the
**repository is the only record system**.

- **Map, not manual.** [`AGENTS.md`](./AGENTS.md) is a ~120-line index;
  every key subdirectory has its own `AGENTS.md` with local conventions
  (progressive disclosure).
- **Mechanical execution > docs.** [`scripts/check_consistency.py`](./scripts/check_consistency.py)
  is the merge gate. It validates SKILL/Rule frontmatter, that every
  router is wired into `app.py`, that every workflow class has a unique
  name, that no `print()` leaks into backend code, that the frontend
  doesn't bypass `lib/api.ts`, and more — each error carries an inline
  `Fix:` hint.
- **Run it locally.** `make consistency` (fast, stdlib-only) or
  `make check` (full gate: ruff + mypy + pytest + frontend typecheck +
  consistency).
- **Pre-commit hook.** One-time setup: `make install-hooks`. CI
  ([`.github/workflows/consistency.yml`](.github/workflows/consistency.yml))
  enforces the same gate independent of local hooks.
- **Disposable plans, durable artefacts.** When the plan stops fitting
  reality, change `PLAN.md`. Every behaviour decision is a versioned
  artifact — Slack and chat memory don't count.

If you're tempted to add "remember to do X" to a doc, write a check
instead. See `scripts/check_consistency.py` for examples.

## Documentation

- [AGENTS.md](./AGENTS.md) — agent / contributor navigation map
- [PLAN.md](./PLAN.md) — full architecture & implementation blueprint (≈ 2000 lines)
- `docs/architecture.md` — system diagrams & flows (M6)
- `docs/writing-your-own-skill.md` — add a new L1 skill (M6)
- `docs/writing-your-own-llm-provider.md` — add a new LLM adapter (M6)
- `docs/deployment.md` — private server deployment guide (M6)
- `docs/api-reference.md` — full API reference (M4)

## License

[MIT](./LICENSE)
