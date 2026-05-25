---
name: aaf-harness-engineering
description: >-
  Entry-point skill for ANY engineering work on the academic-agent-framework
  repo itself. Routes to all other aaf-* engineering skills + alwaysApply
  rules by filesystem area. Load this FIRST whenever you intend to add /
  modify / refactor backend, frontend, deploy, or any .py / .ts / .tsx file
  in this repo. Use when user says "改 AAF / refactor / 加 module / fix bug
  / new endpoint / new workflow / new provider / 调样式 / docker / 部署 /
  施工 / engineering / develop"; or when you're about to touch any code in
  this repository.
domain: engineering
triggers:
  - aaf engineering
  - 施工
  - harness engineering
  - modify aaf
  - refactor aaf
  - new module
  - new file in backend
  - new file in frontend
  - aaf development
version: "1.0.0"
---

# AAF Harness Engineering — 入口地图

> **核心原则（永远记住）**：本仓库遵循 OpenAI Harness Engineering 纪律 ——
> "humans design constraints, the agent does the work, and **the repository is the only record system**"。
> 任何"我感觉对"都不算——`make check` 全绿才是 done。
>
> 文档会腐化（"docs decay; lints don't"），所以约束都被写成可机械执行的检查
> （`scripts/check_consistency.py` + `ruff` + `mypy` + `pytest` + `tsc`）。
> 你的工作就是先读约束、再写代码、最后跑 check。

---

## 一、Step 0 — 开工前的强制三件事

无论用户让你改什么，开工前**先做这三件**：

```bash
# 1. 看可用的工程 skill 与 rule
ls .cursor/skills .cursor/rules

# 2. 按你打算改的文件区域，读对应 skill + rule（见 §二 路由表）

# 3. 任何改动结束后，跑机械门
make check          # ruff + mypy + pytest + frontend typecheck + consistency
# 或最快子集
python3 scripts/check_consistency.py
```

如果你跳过 §二 的对应 skill 直接开写——**那就是蛮干**，违反本仓库纪律。

---

## 二、按"打算改的文件"路由到 skill / rule

| 你打算改 | 必读 skill（一次性，~5 分钟）| 必读 rule（alwaysApply，glob 自动命中）|
|---|---|---|
| 任何 `.py` 文件（无差别）| [`aaf-project-conventions`](../aaf-project-conventions/SKILL.md) | [`aaf-python-style`](../../rules/aaf-python-style.mdc) |
| `backend/api/**/*.py`（HTTP / SSE / Pydantic schema）| [`aaf-backend-api`](../aaf-backend-api/SKILL.md) | [`aaf-api-contract`](../../rules/aaf-api-contract.mdc) + python-style |
| `backend/core/llm/**`（provider / router / registry / mock）| [`aaf-llm-provider`](../aaf-llm-provider/SKILL.md) | python-style |
| `backend/core/skill_host/**`（loader / matcher / injector / executor）| [`aaf-skill-host`](../aaf-skill-host/SKILL.md) | python-style |
| `backend/memory/**`（vector / knowledge / heuristic / episodic / session）| [`aaf-memory-contract`](../aaf-memory-contract/SKILL.md) | python-style |
| `backend/agents/**` 或 `backend/workflows/**` | [`aaf-agent-workflow`](../aaf-agent-workflow/SKILL.md) | python-style |
| `scripts/**/*.py` | [`aaf-project-conventions`](../aaf-project-conventions/SKILL.md) | python-style（**`print()` 一样禁**）|
| `frontend/src/**/*.tsx`（组件 / hooks / stores）| [`aaf-frontend-react`](../aaf-frontend-react/SKILL.md) | [`aaf-react-style`](../../rules/aaf-react-style.mdc) |
| `frontend/src/styles/**` · `components/ui/**`（Tailwind / 主题 / dark mode）| [`aaf-tailwind-shadcn`](../aaf-tailwind-shadcn/SKILL.md) | aaf-react-style |
| `Dockerfile*` · `docker-compose*.yml` · `deploy/**` | [`aaf-deploy`](../aaf-deploy/SKILL.md) | — |
| `skills/<name>/SKILL.md`（runtime L1 学术 skill，不是工程 skill）| 仓库根 [`skills/AGENTS.md`](../../../skills/AGENTS.md) | — |
| `rules/*.md`（runtime L2 行为规则）| 仓库根 [`rules/AGENTS.md`](../../../rules/AGENTS.md) | — |

**特别提醒**：`.cursor/skills/aaf-*` 是 **dev-time 工程纪律**（你写代码时遵守的）；`skills/`（项目根）是 **runtime L1 学术能力**（agent 在学术任务时调用的）。两者完全不同——别混。

---

## 三、永远生效的硬规则（不读 skill 也别违反）

### 3.1 Python（出自 `aaf-python-style.mdc` + `aaf-project-conventions`）

| 禁忌 | 替换为 |
|---|---|
| `print(...)` | `log = structlog.get_logger(__name__); log.info("event_name", k=v)` |
| `Any` 类型注解（除 LLM SDK 边界 + inline 注释外）| `object` 或具体泛型 |
| `raise Exception(...)` / `raise ValueError(...)`（非 stdlib 边界）| `raise SomeAAFError(...)`（来自 `backend/core/errors.py`）|
| `requests` 库 | `httpx.AsyncClient` |
| 同步 I/O 在 request path | `async def` + `await asyncio.to_thread(...)` |
| 顶层（import time）开文件 / 连 DB | 在 FastAPI lifespan 或 Registry class 里 |
| 直接 `from openai import ...` / `from anthropic import ...` | 走 `LLMProvider` Protocol |
| `backend/core/` import 自 `backend/agents` / `workflows` / `api` | 反向才合法 |
| 新模块没单元测试 | `backend/tests/unit/<path>.py` 配套 |

### 3.2 API（出自 `aaf-api-contract.mdc` + `aaf-backend-api`）

| 必须 | 说明 |
|---|---|
| 所有路由在 `/api/v1/` 下 | 破坏性改动开 `/api/v2/`，**不准改 v1** |
| 长任务 → 202 + `task_id`，入 ARQ 队列 | 不准在 request 里同步跑工作流 |
| Request schema `model_config = ConfigDict(extra="forbid")` | response schema 可选 |
| 不返回 SQLAlchemy row | 全部转 Pydantic |
| 错误用 `AAFError` 子类 → RFC 7807 Problem Details JSON | 不准 `return {"error": ...}` |
| 时间戳 ISO 8601 UTC 带 `Z` | Pydantic 自动 |
| 分页只用 cursor-based（`limit` + `cursor`）| 不准 page-number |
| SSE 用 `EventSourceResponse` + 15s 心跳 | 不准 `new EventSource()` 在前端 |
| 每个 router 文件配套 `backend/tests/integration/test_app_<resource>.py` | consistency check 强制 |

### 3.3 Memory（出自 `aaf-memory-contract`）

- **只能通过 `MemoryBundle`** 触达 5 个 store。`backend/` 任何**非 memory/ 目录**的代码 import `chromadb` / `PyYAML` 直接读写存储 → 违规。
- 5 个 store：`vector`(Chroma) / `knowledge`(YAML) / `heuristic`(YAML) / `episodic`(SQL) / `session`(Redis) + M7.3 `documents`(YAML+vector mirror)。
- 删除一律 soft delete（`_trash/`），保留 30 天。
- 写顺序固定：`knowledge.write_card` 先 → `vector.add` 后；vector 失败仅 log，nightly job 修。
- 每个 store 操作必带 `log.info("memory.<store>.<op>", id=...)` 用于审计。

### 3.4 Skill Host（出自 `aaf-skill-host`）

- 4 个模块各管一件事：`loader.py` / `matcher.py` / `injector.py` / `executor.py`。**不准跨界**（loader 不准调 LLM、matcher 不准碰文件系统、injector 不准跑脚本）。
- Loader 解析 SKILL.md **必须保留**未知 frontmatter 字段到 `raw_meta` —— 这是 v2.2.5 DAG metadata 等扩展字段的 forward compat 通道。
- Loader **永远不准 raise** —— 解析失败只 log + skip。
- Tool 命名一律 `{skill_name}__{script_stem}`（双下划线），脚本名不准带 `-`。

### 3.5 LLM Provider（出自 `aaf-llm-provider`）

- 所有 adapter 满足 `LLMProvider` Protocol（在 `backend/core/llm/base.py`），**用 `typing.Protocol` 不用 ABC**。
- adapter 内部用 `httpx.AsyncClient`，不准 `requests` / `openai` SDK 直接传出去。
- 只 emit `CompletionChunk`，不准把 vendor 原生 chunk 传出 adapter 边界。
- 错误必须映射到 `LLMTimeout` / `LLMRateLimit` / `LLMAuthError` / `LLMContextWindowError` / `LLMAPIError` 五个 AAFError 子类之一。
- 重试用 `tenacity`（exponential jitter，最多 3 次），不准重试 tool-level error。
- 每次完成的 stream 都 call `backend.core.llm.telemetry.record(...)`。
- 集成测试**只用 `MockLLMProvider`**，永远不打真实 API。

### 3.6 Workflow（出自 `aaf-agent-workflow`）

- **不准引入 LangGraph / LangChain / CrewAI / AutoGen**。
- 4 个 agent（Planner / Executor / Evaluator / Evolver）都是 stateless class，**只通过 `WorkflowContext` 拿依赖**。
- 用 `self.stage(ctx, name, fn)` 包装每个阶段——它自动处理 emit / 计时 / budget / 异常 / checkpoint。
- Prompt 不准 hardcode 在 Python 字符串里——必须存 `prompts/<agent>/*.md` 由 `PromptLoader` 渲染。
- workflow 必须在 `backend/tests/integration/workflows/test_<name>.py` 配 integration test，用 `MockLLMProvider` + `InMemoryMemoryBundle`。

### 3.7 Frontend（出自 `aaf-react-style.mdc` + `aaf-frontend-react` + `aaf-tailwind-shadcn`）

- 只用：React 19 函数组件 + TS strict + Vite 5 + Zustand 5（仅 UI state）+ TanStack Query v5（所有 server state）+ Tailwind v4 + shadcn/ui + `@microsoft/fetch-event-source`。
- **禁用**：CSS-in-JS / styled-components / Redux / Vue / Pinia / `React.FC` / class components / 默认导出（page 除外）/ `any` / `@ts-ignore` 无 issue 引用 / `fetch()` 在组件里 / `new EventSource()` / 第二个 icon 库（只准 `lucide-react`）/ Tailwind 任意值颜色（`bg-[#123456]`）。
- 所有 HTTP 走 `@/api/*.ts` wrapper + TanStack Query hook；所有 SSE 走 `@/hooks/useSSE.ts`。
- 主题 token 只在 `src/styles/globals.css`，`:root` + `.dark` 必须同步加。

### 3.8 Deploy（出自 `aaf-deploy`）

- 单机部署 SLA：**clean 机器 5 分钟内能跑起**——任何破坏这条的都是 bug。
- 每个新 ENV 变量四件事：`.env.example` 加注释 / `backend/settings.py` 加 Pydantic field / `docs/deployment.md` 文档 / `docker-compose.yml` 传给容器。
- Dockerfile 必须 multi-stage + 有 `HEALTHCHECK`，不准 `COPY .` 起手。
- 删数据用 soft delete（移 `_trash/`）。
- Nginx SSE 三件套必须有：`proxy_buffering off; proxy_cache off; proxy_read_timeout 24h;`

---

## 四、施工后的机械门（唯一的 done 标准）

| 命令 | 何时跑 | 失败处理 |
|---|---|---|
| `python3 scripts/check_consistency.py` | 每次改完 | 按 `Fix:` hint 改 artifact，不要改 check |
| `ruff format . && ruff check .` | 提交前 | auto-fix 优先，剩下手改 |
| `mypy backend` | 改 .py 后 | 补 type hint，禁加 `# type: ignore` |
| `pytest backend/tests -q` | 改 backend 后 | 必须 100% pass + 不退回 skipped |
| `npm --prefix frontend run typecheck && npm --prefix frontend run build` | 改 frontend 后 | 0 error |
| **`make check`** | 提交 PR 前 | 上面五条全部包含 |

绿了才是 done。**绿之前不要回复用户"我做完了"**——这是 `verification` 类纪律的本仓库版本。

---

## 五、容易在本仓库踩的"半隐式"坑（亲身经历）

1. **混淆"两类 skill"** —— `skills/`（runtime L1）和 `.cursor/skills/`（dev-time 工程）完全不同；改 runtime SKILL frontmatter 找 `skills/AGENTS.md`，写 backend 代码找 `.cursor/skills/aaf-*`
2. **以为 alwaysApply rule 会自动注入到上下文** —— 不可靠。**主动 ls + read** 是唯一保险
3. **`scripts/` 里写 `print()`** —— `aaf-python-style.mdc` 的 glob 包含 `scripts/**/*.py`，`print` 一样禁
4. **跨 store 事务** —— forbidden。任何"我想 atomically 写 knowledge + episodic"的诱惑都要拒
5. **改 `backend/core/llm/__init__.py` 不读 `aaf-llm-provider`** —— provider Protocol 是冻结契约，乱加 method 会破所有 adapter
6. **加新 workflow 不更新 `PLAN.md` §10.5 表** —— `aaf-project-conventions` §8 强制
7. **新 ENV 不加进 `.env.example`** —— `aaf-deploy` §5 + `aaf-project-conventions` §10 PR checklist 双重强制
8. **认为"测试只覆盖 happy path 就够了"** —— 集成测试每个 endpoint 至少 1 个 4xx edge case（`aaf-backend-api` §10）

---

## 六、何时需要新增 / 修改一条工程 skill 或 rule

- 当你发现一条新约束被你重复说了 ≥ 3 次 → 写成 rule（`.cursor/rules/aaf-*.mdc`，alwaysApply + glob）
- 当一类工作有完整方法论（不止"必须"和"禁止"，还要"步骤 + 模板"）→ 写成 skill（`.cursor/skills/aaf-*/SKILL.md`）
- 调用全局 [`create-rule`](../../../.cursor/skills-cursor/create-rule/SKILL.md) / [`create-skill`](../../../.cursor/skills-cursor/create-skill/SKILL.md) skill（在 `~/.cursor/skills-cursor/` 下）来生成正确格式
- 加完后**同时更新本文件 §二 路由表**——否则别人找不到

---

## 七、与本仓库的"runtime"层（容易混的）

| 维度 | runtime（学术能力）| dev-time（工程纪律）|
|---|---|---|
| 路径 | `skills/` · `rules/` · `data/skills/` | `.cursor/skills/aaf-*` · `.cursor/rules/aaf-*.mdc` |
| 触发者 | SkillHost.matcher 在 agent 跑学术任务时 | 你（人 / LLM agent）在写本仓库代码时 |
| frontmatter `domain` 取值 | `research` / `writing` / `revision` / `rebuttal` / `survey` / `presentation` / `ideation` / `meta` | 一律 `engineering` |
| 是否进 Docker 镜像 | ✅ 是（用户运行时需要） | ❌ 不（dev-time only） |
| 由谁维护 | 学科专家（写法 / 选题 / 综述方法）| 框架开发者（你 / 后续贡献者）|

---

## 八、自检清单（每次开工前过一遍）

- [ ] 我已 `ls .cursor/skills .cursor/rules`，知道有哪些资产
- [ ] 我已 read 与本次改动 glob 命中的所有 alwaysApply rule
- [ ] 我已 read §二 路由表里命中的 skill
- [ ] 我已确认本次改动不违反 §三 任何硬规则
- [ ] 我已规划好 §四 的 done 标准（具体跑哪几条命令）
- [ ] 如果我引入新约束 / 新概念，我已规划是否要写 rule / 更新 PLAN.md / 改 .env.example

只要这 6 条全打勾，再开始动代码。
