# CLAUDE.md — Academic Agent Framework

> Engineering entry point. Runtime skills live in `skills/`; engineering
> discipline lives in `.claude/skills/aaf-*`. Read the relevant skill before
> touching code in that area. This file loads automatically into every
> Claude Code session.

## Hard gates (must pass before committing)

- `make check` = ruff + mypy + pytest + frontend typecheck + consistency
- `make lint` + `make typecheck` pass per-file
- Pre-commit hook: `ruff format --check` + `ruff check`

## STOP — 施工前必读

| 你打算改 | 必读 `.claude/skills/` |
|---|---|
| 任何 `.py` | `aaf-project-conventions/SKILL.md` |
| `backend/api/**` | `aaf-backend-api/SKILL.md` |
| `backend/core/llm/**` | `aaf-llm-provider/SKILL.md` |
| `backend/core/skill_host/**` | `aaf-skill-host/SKILL.md` |
| `backend/memory/**` | `aaf-memory-contract/SKILL.md` |
| `backend/agents/**` or `backend/workflows/**` | `aaf-agent-workflow/SKILL.md` |
| `frontend/src/**/*.tsx` | `aaf-frontend-react/SKILL.md` |
| `frontend/src/styles/**` or `components/ui/**` | `aaf-tailwind-shadcn/SKILL.md` |
| `Dockerfile` · `docker-compose*` · `deploy/**` | `aaf-deploy/SKILL.md` |

顶层入口：`.claude/skills/aaf-harness-engineering/SKILL.md`

## 反模式（违反任一视为蛮干）

- ❌ 只读本文就开工，跳过上面表里对应的 skill
- ❌ 改 `backend/**/*.py` 不先读 `aaf-python-style.mdc`
- ❌ 给 `backend/core/` 加新模块不在 `backend/tests/unit/` 加同名 unit test
- ❌ 用 `print()` / `Any` / 裸 `Exception` / `from openai import …`
- ❌ 不更新 `.env.example` / `PLAN.md` 就引入新 ENV var / 新概念

## Python 铁律

- **Python 3.11+**，async-first，所有 I/O 异步
- **Type hints 全覆盖**，`mypy --strict` 兼容
- **Log**: `structlog.get_logger(__name__)`，key-value 格式。绝不用 `print`（CI 会 grep）
- **Error**: 继承 `backend.core.errors.AAFError`，绝不抛裸 `Exception`
- **Import 序**: stdlib / third-party / `backend.*`，空行分隔。ruff 强制
- **命名**: `snake_case.py` / `PascalCase` / `UPPER_SNAKE` / `_private`
- **禁止**: `langchain`, `langgraph`, `crewai`, `autogen`, `requests`(非测试)
- **分层**: `backend/core/` 不引 `backend/agents/` `backend/workflows/` `backend/api/`

## API 铁律

- 一路由一文件: `backend/api/routers/<resource>.py`
- Schema 独立: `backend/api/schemas/<resource>.py`，`extra="forbid"`
- 长任务返 202 + task_id，用 SSE 推送进度
- Error 走 `AAFError` 子类 → RFC 7807 Problem JSON
- 分页用 cursor-based，不用 page-number

## 目录结构

```
academic-agent-framework/
├── CLAUDE.md              ← 你在看
├── AGENTS.md              ← 旧入口（保留兼容）
├── PLAN.md                ← 设计权威来源
├── .claude/skills/aaf-*   ← 工程 skill（自动加载）
├── .claude/rules/aaf-*    ← 工程 rule
├── skills/                ← L1 学术能力（运行时）
├── rules/                 ← L2 行为约束（运行时）
├── backend/
│   ├── api/               ← FastAPI 路由
│   ├── core/              ← LLM / skill host / rule engine
│   ├── workflows/         ← 自主编排的 agent 循环
│   ├── memory/            ← 6 种存储后端
│   ├── tasks/             ← 长任务队列 + runner
│   ├── tools/             ← 共享工具注册
│   ├── proposals/         ← 框架变更提案（人工审批）
│   └── tests/{unit,integration}
└── frontend/              ← React 19 + Vite + Tailwind v4
```
