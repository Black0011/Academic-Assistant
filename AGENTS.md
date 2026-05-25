# AGENTS.md — Academic Agent Framework

> A short map for agents and humans. **Not a manual.** Each subdirectory has its
> own `AGENTS.md` with the local conventions; don't read everything at once.
> Pull what's relevant on-demand, the way a Cursor / Codex / Claude agent
> would.

If something matters for behaviour, it must live in this repository as a
versioned artifact. Slack threads, Google Docs, "asked once in chat" — none
of those exist for an agent.

---

## STOP · 施工前必读（适用于 LLM agent 在本仓库做任何改动前）

本仓库分两类 skill / rule —— **不要混淆**：

| 层 | 路径 | 作用 | 何时读 |
|---|---|---|---|
| **Runtime（L1/L2/L3）** | `skills/` · `rules/` · `data/skills/` | 学术工作能力 + 行为约束（agent 在响应学术任务时使用） | 跑 research / writing / revision 等学术工作流时，由 SkillHost 注入 |
| **Engineering（dev-time）** | `.claude/skills/aaf-*` · `.claude/rules/aaf-*.mdc` | 施工纪律：Python style / API contract / LLM provider / Skill Host / Memory / Frontend / Deploy | **你在改本仓库代码时本人必读** |

**Step 0（强制）**：开工前先 `ls .cursor/skills .cursor/rules`，按下表选要读的，**通读后再动一行代码**：

| 你打算改 | 必读 skill（`.cursor/skills/`）| 必读 rule（`.cursor/rules/`，alwaysApply）|
|---|---|---|
| 任何 `.py`（无差别）| `aaf-project-conventions/SKILL.md` | `aaf-python-style.mdc`（glob `backend/**/*.py` + `scripts/**/*.py`）|
| `backend/api/**` | `aaf-backend-api/SKILL.md` | `aaf-api-contract.mdc`（glob `backend/api/**`）|
| `backend/core/llm/**` | `aaf-llm-provider/SKILL.md` | — |
| `backend/core/skill_host/**` | `aaf-skill-host/SKILL.md` | — |
| `backend/memory/**` 或读写用户数据 | `aaf-memory-contract/SKILL.md` | — |
| `backend/agents/**` 或 `backend/workflows/**` | `aaf-agent-workflow/SKILL.md` | — |
| `backend/tools/**`（含 `mcp_*.py`） | `aaf-agent-workflow/SKILL.md`（tool/registry 接入路径在 §1）+ `aaf-llm-provider/SKILL.md`（透过 ToolSpec 投到 LLM）| — |
| `frontend/src/**/*.tsx` | `aaf-frontend-react/SKILL.md` | `aaf-react-style.mdc`（glob `frontend/src/**`）|
| `frontend/src/styles/**` 或 `components/ui/**` | `aaf-tailwind-shadcn/SKILL.md` | `aaf-react-style.mdc` |
| `Dockerfile` · `docker-compose.yml` · `deploy/**` · `docker-compose.lite.yml` | `aaf-deploy/SKILL.md` | — |

**入口跳转**：直接读 `CLAUDE.md`（自动加载）或 [`.claude/skills/aaf-harness-engineering/SKILL.md`](.claude/skills/aaf-harness-engineering/SKILL.md)
即可拿到上面这张表的完整版（含每个 skill 的 trigger / 关键约束摘要 / 验收清单）。
外层快捷入口：`../aaf-engineering-framework/`（NTFS Junction → `.claude/`），对外部 agent 更友好。

**反模式（违反任一即视为蛮干）**：
- ❌ 只读 `AGENTS.md` 系列就开工，跳过 `.claude/skills/`
- ❌ 改 `backend/**/*.py` 时不先读 `aaf-python-style.mdc`（CI / lint 会发现，但应在写之前就避免）
- ❌ 给 `backend/core/` 加新模块但不在 `backend/tests/unit/` 加同名 unit test
- ❌ 用 `print()` / `Any` / 裸 `Exception` / `from openai import …`（直接 import LLM SDK）
- ❌ 不更新 `.env.example` / `PLAN.md` 就引入新 ENV var / 新概念

---

## Navigation

| Where you're going                | Read first                                           |
| --------------------------------- | ---------------------------------------------------- |
| **Engineering discipline (dev-time)** | `CLAUDE.md` (auto-loaded) + [`.claude/skills/aaf-harness-engineering/SKILL.md`](.claude/skills/aaf-harness-engineering/SKILL.md) — also reachable via the outer junction `../aaf-engineering-framework/` |
| Add or edit an L1 capability skill| [`skills/AGENTS.md`](skills/AGENTS.md)               |
| Add or edit an L2 behaviour rule  | [`rules/AGENTS.md`](rules/AGENTS.md)                 |
| Backend Python work               | [`backend/AGENTS.md`](backend/AGENTS.md)             |
| New HTTP endpoint                 | [`backend/api/AGENTS.md`](backend/api/AGENTS.md)     |
| New workflow (research / write…)  | [`backend/workflows/AGENTS.md`](backend/workflows/AGENTS.md) |
| Skill Host internals              | [`backend/core/skill_host/AGENTS.md`](backend/core/skill_host/AGENTS.md) |
| Memory subsystem                  | [`backend/memory/AGENTS.md`](backend/memory/AGENTS.md) |
| Frontend (React 19 + Vite)        | [`frontend/AGENTS.md`](frontend/AGENTS.md)           |
| Big-picture design                | [`PLAN.md`](PLAN.md)                                 |

---

## House rules (non-negotiable)

1. **Repository is the only record system.** Decisions live in
   `PLAN.md`, `AGENTS.md`, code, or commits — nowhere else.
2. **Docs decay; lints don't.** Mechanical checks (`make check`) are the
   actual gate. If you're tempted to write "remember to do X" in docs,
   write a check instead.
3. **Map, not manual.** Every `AGENTS.md` is ≤ ~150 lines and points
   outward to deeper files. Anything longer is a smell.
4. **Boring tech wins.** When choosing libraries, optimise for what models
   already know — FastAPI / SQLAlchemy / React / Tailwind. No clever
   metaprogramming when explicit code will do.
5. **One concern per change.** If your diff touches `skills/`, `backend/`
   *and* `frontend/`, split it.

---

## Mechanical checks (the real gate)

A green `make check` is the merge bar. Locally:

```bash
make check          # ruff + mypy + pytest + frontend typecheck + consistency
make consistency    # just the structural invariants (fast, no network)
```

CI runs the same `scripts/check_consistency.py` on every push (see
`.github/workflows/consistency.yml`). It enforces things like:

- every `skills/*/SKILL.md` has the required frontmatter and a known `domain`
- every `rules/*.md` has the required frontmatter
- every router file under `backend/api/routers/` is included in `backend/app.py`
- every concrete `BaseWorkflow` subclass has a non-empty `name`
- every directory listed in this map actually has an `AGENTS.md`

Errors carry an inline `Fix:` hint — read it, then fix the artifact, not the
check. If a rule is genuinely wrong, change `scripts/check_consistency.py`
in the **same PR** as the artefact and call it out in the commit message.

---

## What lives where

```
academic-agent-framework/
├── PLAN.md                 ← single source of truth for the design
├── AGENTS.md               ← you are here
├── backend/                ← FastAPI + ARQ + workflows + memory + skills runtime
│   ├── api/                ← HTTP routers (one file per resource)
│   ├── core/               ← LLM provider, skill host, rule engine, events, app state
│   ├── workflows/          ← Self-orchestrated agent loops (no LangGraph)
│   ├── memory/             ← 6 stores: vector / knowledge / heuristic / episodic / session / documents
│   ├── manuscripts/        ← Paper draft + version subsystem
│   ├── tasks/              ← Long-running task store + queue (in-memory or ARQ/Redis)
│   ├── tools/              ← Shared tool registry (arxiv, pdf, search…)
│   ├── proposals/          ← M8.1 gated framework-change proposals (no auto-apply)
│   ├── planner/            ← M8.2 PlanDAG models + compiler + validator + executor
│   └── tests/{unit,integration}
├── frontend/               ← React 19 + Vite + Tailwind v4 + TanStack Query
├── skills/                 ← L1 academic skills (research, writing, revision, …)
├── rules/                  ← L2 behaviour rules (always-apply discipline)
├── data/skills/research/   ← L3 heuristics (learned strategies, evolvable)
├── prompts/                ← Reusable prompt fragments
├── deploy/                 ← Dockerfiles, nginx, postgres init
├── docs/                   ← Reproduction guides (M6)
├── sdk/python|ts/          ← Embedding clients (M6)
├── cli/                    ← `aaf` command-line entry (M6)
└── scripts/                ← Mechanical checks + housekeeping
```

---

## Working style for agents

- **Fresh context is reliability.** Re-read this file at the top of any
  loop. Don't assume earlier turns saw the same state.
- **Disk is state, git is memory.** Write intermediates to disk, commit
  meaningful state, treat memory as throwaway.
- **The plan is disposable.** When the plan stops fitting reality, write a
  new one — don't fight reality.
- **Steer with signals, not scripts.** Add a check, a rule frontmatter
  field, a fix-hint — don't write step-by-step procedures.

If a task feels like it needs prose more than the above, you're probably
about to add a new constraint that should be a check.
