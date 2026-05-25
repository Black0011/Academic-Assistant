# 运行时内部机制 —— 架构与设计参考

> **文档定位。** 本文是关于 AAF *运行时* 各部件如何协作的权威参考：上下文管理、对话隔离、提示词拼接、Provider 装饰器栈、记忆访问模式、自进化、遥测。
> 它是 [`docs/architecture.md`](architecture.md)（静态子系统地图）的动态版补充 —— 改一边时同 PR 改另一边。
>
> **真相源契约。** 文中每条结论都落到代码上：路径用 `path/to/file.py:Symbol` 形式标注，便于核对。当代码与文档分歧时**以代码为准**，请提 PR 把文档同步过来再合并。
>
> **英文同步版**：[`runtime-internals.md`](runtime-internals.md)。中英两版的章节编号一一对应，便于 cross-reference。

---

## 0. 一页心智模型

```
                           ┌─────────────────── 浏览器 ───────────────────┐
                           │  React 19 SPA · TanStack Query · SSE         │
                           └────────────────────┬─────────────────────────┘
                                                │ HTTPS
                       ┌────────────────────────┴─────────────────────────┐
                       │                  FastAPI app                     │
                       │ POST /api/tasks  →  TaskStore.create + enqueue   │
                       │ GET  /api/tasks/{id}/stream  →  SSE 重放+续推    │
                       └─────────┬─────────────────────────────┬──────────┘
                                 │ enqueue                     │ 轮询事件
                                 ▼                             │
                       ┌─────────────────┐                     │
                       │   TaskQueue     │  (in-mem | ARQ)     │
                       └────────┬────────┘                     │
                                │ Worker.execute_task          │
                                ▼                              │
   ┌────────────────────────────────────────────────────────────────────┐
   │                     单次任务运行                                   │
   │                                                                    │
   │   Workflow (BaseWorkflow 子类)                                     │
   │     │                                                              │
   │     │  ctx = WorkflowContext(task_id, llm, memory, tools, …)       │
   │     │  ctx.stage("planner") → emit Event → 持久化到 TaskStore      │
   │     │                                                              │
   │     ├── SkillHost.select_and_inject(query)  ← L1 技能注入          │
   │     ├── RuleEngine.compose_system_prompt()  ← L2 规则注入          │
   │     ├── ctx.llm.complete([...])             ← LLM 调用             │
   │     └── ctx.memory.knowledge.upsert(...)    ← 写入 6 个记忆库      │
   │                                                                    │
   │   终态时：                                                         │
   │     · TaskStore.update_terminal(status=ok|error, result=…)         │
   │     · EvolverAgent.maybe_propose(run) → ProposalStore (gated)      │
   └────────────────────────────────────────────────────────────────────┘
```

**关键不变量：**
- 一切跨边界的"动作"都先变成一条 `Event`；这条 Event 既要持久化到 `TaskStore`、也要广播到 SSE。
- 每次 LLM 调用都通过 *同一条* 装饰器链（Compactor → Routing → RouteTagged → Adapter），所以遥测、压缩、路由这三件事都"无侵入"。
- Skill 与 Rule 是两条独立的注入轨道：L1（技能）按 query 匹配后才注入；L2（规则）无条件注入。

---

## 1. 请求生命周期 —— 以 research 工作流为例

`backend/workflows/research.py:ResearchWorkflow` 的一次 `POST /api/tasks` 端到端：

| 步骤 | 路径 | 关键调用 |
|---|---|---|
| 1. HTTP 入口 | `POST /api/tasks` | `backend/api/routers/tasks.py:create_task` |
| 2. 任务记录 | `task = TaskStore.create(...)` | `backend/tasks/store.py:InMemoryTaskStore.create` |
| 3. 入队 | `await task_queue.enqueue(task.id)` | `backend/tasks/queue.py:InMemoryTaskQueue.enqueue` |
| 4. Worker 拉起 | `execute_task(task_id, deps)` | `backend/tasks/runner.py:execute_task` |
| 5. 装配 ctx | `WorkflowContext(task_id=…, llm=deps.llm, memory=deps.memory, …)` | `backend/workflows/base.py:WorkflowContext` |
| 6. workflow.run | `await workflow.run(ctx)` | `backend/workflows/research.py:ResearchWorkflow.run` |
| 7. stage 切换 | `async with ctx.stage("planner"): …` | `backend/workflows/base.py:BaseWorkflow.stage` |
| 8. Skill 注入 | `bundle = await skill_host.select_and_inject(query)` | `backend/core/skill_host/registry.py:SkillHost.select_and_inject` |
| 9. LLM 调用 | `await ctx.llm.complete(messages, tools=…)` | 装饰器链（见 §3） |
| 10. 终态写入 | `TaskStore.update_terminal(status, result, error)` | `backend/tasks/runner.py:_persist_outcome` |
| 11. 自进化触发 | `EvolverAgent.maybe_propose(run)` | `backend/agents/evolver.py:EvolverAgent.maybe_propose` |

每个 `ctx.stage()` 都会发出至少 3 类事件（`stage_started` / `stage_done` / `stage_error`），它们是 `Event` 实例，写入 `TaskStore.events`，再由 SSE 端点重放给前端 EventTimeline。

---

## 2. 对话隔离

> **设计目标**：同一进程同时跑多个任务（不同用户、不同 session）时，*绝不能*互相串记忆、串提示词、串中间状态。

### 2.1 五个标识符

| ID | 在哪生成 | 在哪用 | 谁能跨 ID 看到？ |
|---|---|---|---|
| `user_id` | 认证层（`current_user`） | 写入 `Manuscript`、`Reflection`、`Proposal` 时打标 | admin 可跨；普通 user 只看自己的 |
| `session_id` | 客户端可选传入 / `uuid4()` | 注入到 `ctx.session_id`；若启用 `SessionStore`，作为多轮上下文 key | 同 `user_id` 内可见 |
| `task_id` | `TaskStore.create()` 自动生成 | 贯穿 `Event.task_id`、SSE channel、`Reflection.source_run_id` | 唯一 |
| `source_run_id` | = `task_id`，写入 `Reflection`、`Heuristic` | 让"这条记忆从哪个 task 学来"可追溯 | 唯一 |
| `proposal_id` | `ProposalStore.draft()` 自动生成 | `Proposal` 的主键；审计日志的 `target` | 唯一 |

### 2.2 六道隔离机制

1. **每任务一份 `WorkflowContext`** —— 不共享可变状态；`ctx.state: dict` 仅在这次 task 内活。
2. **每任务一次 LLM 装饰器实例化** —— `Compactor` 持有的 `_summary` cache 也是任务局部的。
3. **`SessionStore` 按 `(user_id, session_id)` 命名空间** —— `backend/memory/session_store.py:InMemorySessionStore.append`。
4. **持久化记忆按 `user_id` 切片** —— `Manuscript`、`Reflection`、`Heuristic` 写入时强制带 `user_id`。
5. **`Reflection.source_run_id`** —— 学到的反思必须能回溯到某次具体 task；可重放、可回滚。
6. **`Proposal` 状态机** —— 自进化产出永远先进入 `draft`；只有人为 / CI 走完 `submit → approve → apply` 才会改框架本身（见 §8）。

### 2.3 ARQ 多 worker 场景的额外保证

跨进程时，`RunnerDeps` 在每个 worker 进程独立构造（`backend/workers/arq_worker.py`）。Worker 之间不共享 Python 内存，仅通过 Redis 队列交换"task_id"，所以上面的 6 道机制天然成立。

---

## 3. LLM Provider 装饰器栈

每次 `ctx.llm.complete(...)` 实际上经过这条**固定顺序**的装饰器链：

```
ctx.llm
  │
  ▼
CompactingLLMProvider          (backend/core/llm/compactor.py)
  │   ↳ 入口处估算 token；超阈值就召一次 compact，再重发
  ▼
RoutingLLMProvider             (backend/core/llm/router.py)
  │   ↳ 根据 ctx.llm.for_route("reasoning") 之类的"路由标签"挑实际 Provider
  ▼
_RouteTaggedProvider           (backend/core/llm/router.py)
  │   ↳ 设置 telemetry.active_route ContextVar，用于遥测归类
  ▼
真正的 Provider Adapter        (openai / anthropic / ollama / mock)
```

**为什么固定这个顺序？**

- *Compactor 在最外层*：压缩必须看到"用户原始 messages"，否则会重复压缩已经被 router 改过的版本。
- *Router 在 Compactor 内层、Adapter 外层*：路由决策只看 `route` 标签，不应被压缩状态干扰。
- *RouteTagged 紧贴 Adapter*：保证 Adapter.complete() 执行时 ContextVar 是对的，遥测才能正确归类。

**`for_route()` 的传播**：`for_route("reasoning")` 返回一个**新的 LLMProvider**，但它仍然共享同一条装饰器链 —— 关键在 `RoutingLLMProvider.for_route` 把内层 Provider 换成 routes 字典里指定的那个，再外层重新包一层 `CompactingLLMProvider`（如果开了压缩）。

**`active_route` ContextVar**：定义在 `backend/core/llm/telemetry.py:_ACTIVE_ROUTE`。通过 `_RouteTaggedProvider.complete` 的 `with _ACTIVE_ROUTE.set(self._route): ...` 设置，`telemetry.record(...)` 读它。这避免了把 `route` 参数到处显式传 —— 任何下游 Adapter 写遥测时都能拿到正确的归类。

---

## 4. 提示词拼接管道

Workflow 调用 `ctx.llm.complete(messages, tools=...)` 时，`messages[0]`（system prompt）的内容由 5 个成分按**固定顺序**组合而成。

| 顺序 | 成分 | 来源 | 何时出现 |
|---|---|---|---|
| 1 | **workflow base prompt** | `BaseWorkflow.system_prompt(ctx)` 默认实现 | 总是 |
| 2 | **L1 Skill 注入块** | `SkillInjector.inject(matched_skills)` | 当 `SkillMatcher.score(query) > threshold` 至少匹中一个 skill |
| 3 | **L2 Rule 注入块** | `RuleEngine.compose_system_prompt()` | 总是（无条件注入；L2 规则就是"始终适用"的约束） |
| 4 | **Compactor 摘要** | `CompactingLLMProvider.compact_messages` 产出的 `[summary] …` 占位行 | 当原始 messages token 数超过窗口阈值 |
| 5 | **Memory 摘要** | `ctx.memory.snapshot(query)` 中相关性 top-k 的卡片 | 当 workflow 显式调用（如 ResearchWorkflow 在 planner 阶段） |

### 4.1 渐进式技能注入（关键不变量）

> Skill Host 的核心承诺：**只有匹中的 skill 内容才进入 LLM context，未匹中的 skill 哪怕注册了 24 个，也不会膨胀 token。**

- `SkillLoader.load_all()` 在 boot 时把 `skills/<name>/SKILL.md` 全量元数据（frontmatter + 描述）读入内存。
- `SkillMatcher.match(query)` 用关键词 + 语义打分挑出 top-k。
- `SkillInjector.inject(matched)` 只为 matched 的 skill 渲染**完整正文**到 prompt。

集成测试 `backend/tests/integration/test_skill_progressive_load.py` 保证不会回退成"全量注入"。

### 4.2 prompt 总预算

`SkillInjector` 拿到 `Budget.total_prompt_tokens` 软上限（默认 2000 token），用 `_approx_tokens_for(text)` 估算后排除超额 skill。剩余预算交给 ResearchWorkflow 自己分配给 memory snippets。

---

## 5. 上下文管理 & 自动压缩

### 5.1 token 估算

`backend/core/llm/compactor.py:estimate_message_tokens` 用 *字符数 / 4* 的快速估算 —— 不引入 tiktoken 依赖、误差 ≤ 15%，对"是否触发压缩"这个二元决策足够。

### 5.2 触发条件

```python
if estimated_tokens > model.context_window * settings.autocompact_threshold:
    messages = await self.compact_messages(messages)
```

- 默认 `threshold = 0.7`：留出 30% 给响应。
- `autocompact_keep_recent_n` (默认 6)：最近 N 条 message 永不压缩。
- `autocompact_summariser_route` (默认 `"fast"`)：用便宜路由跑摘要。

### 5.3 压缩算法

1. 把 messages 切成三段：开头 system / pinned + 中段（要被压缩的） + 尾段最后 N 条。
2. 把中段送到 `summariser_provider.complete(summary_prompt)`，得到 `[summary] …`。
3. 拼回去，重发原始请求。

### 5.4 递归压缩护栏

`_INSIDE_COMPACTION` ContextVar：当压缩自身又触发了 LLM 调用（比如让 `fast` 路由跑摘要），这条 ContextVar 被设为 `True`，外层装饰器看到 True 就跳过再次压缩，防止无限递归。

### 5.5 上下文窗口 vs Budget

- **窗口** 是 Provider 物理上限（在 `LLMProvider.context_window` 上声明）。压缩看的是窗口。
- **Budget** 是经济上限（`backend/core/budget.py:Budget`）：dollars / total_tokens / wall_seconds。每次 LLM 调用通过 `budget.accrue_llm(...)` 累加；超出 `BudgetExceededError`。

---

## 6. 记忆子系统 —— 读写模式

`backend/memory/base.py:MemoryBundle` 是 6 个独立 store 的门面：

| Store | 职责 | 后端实现（laptop / 生产） |
|---|---|---|
| `vector` | 嵌入相似度搜索 | InMemoryVectorStore / ChromaVectorStore |
| `knowledge` | 论文卡 (`PaperCard`) + 综合 | InMemoryKnowledgeStore / YamlKnowledgeStore |
| `heuristic` | L3 学到的策略 | InMemoryHeuristicStore / YamlHeuristicStore |
| `episodic` | 事件级追溯（每个 stage） | InMemoryEpisodicStore / SqlEpisodicStore |
| `session` | 多轮对话上下文 | InMemorySessionStore / RedisSessionStore |
| `documents` | RAG 用的文档分片 | InMemoryDocumentStore / YamlDocumentStore |

### 6.1 写入硬规则

- 任何写入 `Manuscript` / `Reflection` / `Heuristic` 都必须带 `user_id`（详见 §2.1）。
- `Reflection` 必须带 `source_run_id`（指向触发它的 task）。
- `documents` 入库时必须同步写一份向量到 `vector` —— `DocumentStore.ingest` 自动做这个 mirror，不允许绕过。

### 6.2 `documents` 与 `knowledge` 为何并存

- `knowledge` 是**结构化**的：`PaperCard` 有 title / abstract / venue / year 等字段，给 review/citation 用。
- `documents` 是**半结构化**的：扁平 chunk + 元数据，给 RAG 用，`ResearchWorkflow` 检索时直接拿原文片段。

两个 store 都写到 `vector`，但通过不同 `namespace` 区分，避免互相污染。

---

## 7. Skill Host 流水线

`backend/core/skill_host/__init__.py` 暴露 4 个组件：

```
SkillLoader ─→ SkillRegistry ─→ SkillMatcher ─→ SkillInjector
   │              │                  │                │
   │              │                  │                ▼
   │              │                  │       composes prompt bundle
   │              │                  ▼
   │              │           keyword + semantic 打分
   │              ▼
   │      内存表：name → SkillMeta
   ▼
boot 时一次扫盘 ./skills/*/SKILL.md
```

**热重载**：`SkillAdmin.reload()` 重跑 `Loader.load_all()`，原子换 Registry，不重启进程。`/api/skills/reload` 暴露给 admin。

**脚本执行**：`SkillHost.execute_script(...)` 走 `subprocess + rlimit`，沙箱细节在 `backend/core/skill_host/executor.py`。

---

## 8. 自进化链

```
workflow.run 成功 ──→ EvolverAgent.maybe_propose(run)
                              │
                              ▼
                       ProposalStore.draft(...)
                              │
                              │  status=draft
                              ▼
                  ┌──────────────────────────┐
                  │ /api/proposals 路由组    │
                  │  GET   /api/proposals    │
                  │  POST  /{id}:submit      │
                  │  POST  /{id}:approve     │
                  │  POST  /{id}:reject      │
                  │  POST  /{id}:apply       │
                  └──────────────────────────┘
```

状态机：`draft → pending → approved → applied`（任何阶段可 `rejected`）。
`apply` **只更新 status + 写审计**，**不改文件** —— 真正的代码 / skill / 配置变更走人 / CI 的 PR 流程。这是 P5 阶段刻意做的"硬护栏"，避免 EvolverAgent 自动改框架自身。

---

## 9. 遥测 & 可观测性

`backend/core/llm/telemetry.py:TelemetryRecorder` 是进程内环形缓冲：

- 每次 LLM 调用通过 `record(provider, model, route, prompt_tokens, completion_tokens, cost_usd, error)` 写入。
- `route` 来自 §3 的 `_ACTIVE_ROUTE` ContextVar。
- `/api/v1/models/usage`、`/api/v1/models/routes` 把这份缓冲渲染成"前端 Dashboard 用的样本"。

> ⚠️ **API 前缀不一致提示**：当前路由前缀有两种风格 —— 大多数路由是 `/api/<resource>`（如 `/api/tasks`），但 `mcp` 与 `models` 路由用的是 `/api/v1/<resource>`。新增路由请遵循 `/api/<resource>`；已有的 `v1/` 端点维持不动以避免破坏前端。

**外部可观测性**：日志走 `structlog` JSON renderer，每条日志都带 `event` key，便于在 Loki / Datadog 中按 event 名称聚合。

---

## 10. 设置与部署画像

`backend/settings.py:Settings` 是 `pydantic.BaseSettings`，每个字段带 `alias` 映射 `AAF_*` 环境变量。三大画像：

| 画像 | env 文件 | 存储 | Auth | 自动压缩 | 适用场景 |
|---|---|---|---|---|---|
| 生产 | `.env.example` | Postgres + Redis + Chroma | 启用 | 关 | `docker-compose.yml` 多容器部署 |
| Laptop | `.env.laptop.example` | SQLite + 内存队列 + 内存向量 | 关闭 | 开 (0.7) | 个人笔记本，`make dev-laptop` / `docker-compose.lite.yml` |
| Offline | `.env.offline.example` | 同 Laptop | 关闭 | 开 (0.6) | Ollama + 本地 sentence-transformers，零外网调用 |

完整说明见 [`docs/laptop-mode.md`](laptop-mode.md)。

### 10.1 运行时 LLM Provider 覆盖（前端 Settings 面板）

env-only 配置适合服务器和 CI；笔记本场景里我们额外加了**运行时覆盖层**，让用户在前端 Settings 面板填一次 API key 就能即刻生效，不用改 dotfile、不用重启。覆盖层用一个 YAML 文件做持久化：

```
data/runtime/provider.yaml
```

由 `backend/core/runtime_config.py:RuntimeConfigStore` 拥有：

- **文件格式**：明文 YAML，5 个用户可编辑字段（`provider`、`api_key`、`base_url`、`default_model`、`timeout_s`）。
- **权限**：目录 `0700`、文件 `0600`，每次保存都强制设置；`data/runtime/` 已在 `.gitignore` 内（`.keep` 占位文件保留目录）。
- **原子写入**：先写 `provider.yaml.tmp`、再 `os.replace` —— 半截写入永远不会产出可读但残缺的文件。
- **容忍式加载**：文件缺失 / 损坏 / 形状不对 → 记录 warning 并返回 `None`，回退到 env-only，**绝不**让进程因此崩溃。

#### HTTP 接口

`backend/api/routers/settings.py` 把这个覆盖层暴露成 REST：

| Method | Path | 用途 |
|---|---|---|
| `GET`  | `/api/settings/llm` | 读当前 Provider —— `api_key` 永远以 mask 形式返回（`sk-…XXXX`），原始值不离进程 |
| `PUT`  | `/api/settings/llm` | 持久化 + 热重载 `state.llm` 与 `runner_deps.llm` |
| `DELETE` | `/api/settings/llm` | 清除覆盖，回退到 env / mock |
| `POST` | `/api/settings/llm:test` | 用候选配置做一次 ping 调用（不持久化） |
| `GET`  | `/api/settings/llm/providers` | 提供给 UI 下拉的白名单 |

权限：`auth_disabled=false` 时要求 admin 角色；笔记本预设默认 `auth_disabled=true`，对所有调用者放行。

#### 「空 `api_key` ⇒ 沿用」语义

前端只看得到 mask 后的 key，不可能也不应该每次保存都重新输入。契约：

- `api_key == ""` 且**同一个** Provider 已配置 ⇒ 沿用已存的 key。
- `api_key == ""` 且**切换** Provider ⇒ 必须显式给新 key（HTTP 400 拒绝；`mock` / `ollama` 例外，它们本就不需要）。
- `api_key != ""` ⇒ 替换。

#### 热重载边界

`PUT` 同时换掉 `state.llm` 和 `state.runner_deps.llm`，新入队的任务立刻用新 Provider。**正在运行的任务保持 `WorkflowContext` 上绑定的 Provider 不变** —— 这与 §2 的隔离不变量一致。

ARQ worker 是独立进程，启动时读 env，**不**监听运行时覆盖。响应里用 `warns_arq_worker: true` 提示前端给运维做 toast 警告。

#### 前端入口

- **Settings 页**：顶部一张"LLM Provider"卡片，包含 LLMProviderForm，能保存、测试、清除。
- **首启 Onboarding 模态框**：当 `source === "env" && !api_key_set && provider === "mock"` 且用户没"跳过"过时，AppLayout 自动弹出，引导第一次填 key。"跳过"会写一个 localStorage 标记，之后不再骚扰。

### 10.2 前端中英双语（i18n）

- 框架：`react-i18next`（`frontend/src/i18n/index.ts`）。
- locale：`frontend/src/i18n/locales/{en,zh}.json`，单 namespace + 嵌套 key。
- 检测顺序：持久化 `useUiStore.language` → `navigator.language` → `"en"`。
- 顶栏"EN / 中"切换器，状态即时落到 `aaf.ui` 这个 localStorage key。
- 全量翻译：Sidebar / TopBar / Login / Register / Dashboard / Research Console / Settings / NotFound / Tasks。
- 已翻译标题与描述：Manuscripts / Revision / Library / Memory / Skills / MCP / Planner / Proposals。

新增 UI 字符串的工作流：先加 key 到 `en.json` + `zh.json`，再用 `t("xxx.yyy")` 替换硬编码字符串。CI 不强制覆盖率，但 `returnEmptyString: false` 会让漏译在开发模式立刻露馅。

---

## 11. Manuscripts 子系统 —— 单文档 与 项目目录（Bundle）

> 入口：`backend/manuscripts/`、`backend/api/routers/manuscripts.py`、`frontend/src/pages/PaperWriterPage.tsx`、`frontend/src/components/manuscripts/BundleExplorer.tsx`。

AAF 的稿件有 **两种 layout**，同一张表两种形态：

| `layout` | 物理布局 | 适用场景 |
|---|---|---|
| `single` | 一段 Markdown 字符串 + 版本链（`ManuscriptVersion` 表） | 短稿、由 write-workflow 自动产出的草稿、需要清晰 v1→vN 历史的场景 |
| `bundle` | 一棵磁盘上的项目目录（`overleaf/` + `plan/` + `experiments/` + …），通过 `BundleStorage` 访问 | Overleaf 项目、复合稿件、已经在 git/IDE 里管理的稿件（例如 `data/papers/paper-dataagent-eval` 这种结构） |

`layout` 字段及 `bundle_link_path` / `bundle_versioning` 通过 `meta` JSON 列在 `SqlManuscriptStore` 里 round-trip —— **没有数据库迁移**，所有 pre-P7 的稿件默认 `layout="single"`，行为完全不变。

### 11.1 Bundle 的两种物理模式

```
┌──────────────────── Manuscript (layout="bundle") ───────────────────┐
│                                                                       │
│  ① copy 模式（默认）                                                  │
│     bundle_link_path = None                                            │
│     物理根   = ./data/manuscripts/<id>/work/                          │
│     语义     = AAF 持有这份目录（自包含、可备份、可打包）             │
│                                                                       │
│  ② link 模式                                                          │
│     bundle_link_path = "/Users/.../paper-dataagent-eval"               │
│     物理根   = 该路径本身                                             │
│     语义     = AAF 只是引用用户既有的项目目录；读写都直接落到原地 ─  │
│                与 git / VSCode / Overleaf-sync 的工作流无缝共存       │
└───────────────────────────────────────────────────────────────────────┘
```

**关键不变量：**
- 单文档稿件 (`layout="single"`) 的所有旧 API（`/upload`、`/versions`、`/export`）都没动，行为与 P7 之前完全一致。
- 删除 `bundle` 稿件时：copy 模式会清理 `./data/manuscripts/<id>/work/`；link 模式 *永远不动用户目录* —— 这条由 `BundleStorage.remove_owned()` 强约束。

### 11.2 路径安全 —— `BundleStorage._safe_resolve`

任何对 bundle 内文件的操作都要先过 `_safe_resolve(manuscript, rel_path)`，它一次性拒绝四种攻击：

1. 绝对路径（`/etc/passwd`、`C:\…`）
2. `..` 段（`../../etc/passwd`）
3. URL 编码 / 大小写 / 斜杠绕过
4. 软链逃逸（先 `mkdir -p target` 再读：`Path.resolve()` 后比对 `relative_to(root)` 抓住）

且 zip 导入路径在解压前**复用同一组检查** —— `import_zip` 拒绝任何会落到根目录之外的 entry，配合 `external_attr` 中 `0o120000` 位检测拒绝软链 entry。

### 11.3 大小限制 & 写入会计

两条阀值（`backend/settings.py`）：

| 设置 | 默认 | 含义 |
|---|---|---|
| `AAF_MANUSCRIPT_MAX_FILE_MB` | 50 MB | 单文件上限（写、上传、解压共享） |
| `AAF_MANUSCRIPT_MAX_BUNDLE_MB` | 500 MB | 整个 bundle 上限（含覆盖写时正确扣回旧大小） |

写、解压、目录导入都是**流式 + 边算边检**：先 `os.walk` 得到当前总大小，再每解一个 entry 累加 `projected = current - existing + entry_size`，超限立即抛 `ManuscriptBundleTooLarge` 中止；不会让恶意 zip 在被检测前先把磁盘填满。

### 11.4 异步与事件循环

所有阻塞性 FS 调用（`os.walk`、`shutil.copy2`、`zipfile.extract`）都通过 `asyncio.to_thread(...)` 卸载到线程池，FastAPI 的事件循环不会被一个大 zip 卡死；这条规则被 ruff `ASYNC240` 机械保证（直接在 async 函数里调 `Path.exists()` 会被拒绝合并）。

### 11.5 端点矩阵

```
POST   /api/manuscripts/{id}/bundle             single → bundle 升级（copy 或 link）
GET    /api/manuscripts/{id}/tree               BundleManifest（path / size / mime / is_text / sha256? / mtime）
GET    /api/manuscripts/{id}/files/{path:path}  小文件读取（text → JSON; binary → JSON+base64）
PUT    /api/manuscripts/{id}/files/{path:path}  UTF-8 文本写
POST   /api/manuscripts/{id}/files/{path:path}  multipart 二进制上传
DELETE /api/manuscripts/{id}/files/{path:path}  删除单文件 / 空目录

POST   /api/manuscripts/import-folder           按 local_path + mode 导入既有项目目录
POST   /api/manuscripts/import-zip              multipart .zip 导入
GET    /api/manuscripts/{id}/export-zip         打包下载（subdir 缺省 = 自动识别 overleaf/）
GET    /api/manuscripts/{id}/download/{path:p}  原始字节流下载
```

`export-zip` 的"自动识别 overleaf 子目录"规则非常简单：根目录下若存在 `overleaf/` 就只打包它（响应头 `X-Bundle-Subdir: overleaf`），否则整包。前端"下载 Overleaf 包"按钮直接走这条；也可以传 `?subdir=.` 强制整包。

### 11.6 错误家族

新加的错误都继承 `AAFError`，由 `app.py` 的统一 handler 转 RFC 7807 响应：

| 异常 | HTTP | 触发场景 |
|---|---|---|
| `ManuscriptLayoutMismatch` | 409 | 在 `single` 稿件上调 bundle-only 端点（或反之） |
| `ManuscriptPathInvalid` | 400 | `_safe_resolve` 拒绝（含 zip-slip） |
| `ManuscriptFileTooLarge` | 413 | 单文件超 `MAX_FILE_MB` |
| `ManuscriptBundleTooLarge` | 413 | 整个 bundle 超 `MAX_BUNDLE_MB` |
| `ManuscriptIOError` | 500 | 真正的 OS 错误（disk full、权限等） |

### 11.7 前端拼装

- `ManuscriptsPage` 列表行：根据 `manuscript.layout` 给 `Bundle` / `Linked` 徽章；右侧下载图标在 bundle 上指向 `export-zip`，在 single 上指向 `export`（旧 markdown 导出）。
- "Import folder" 模态接 `POST /import-folder`；"Import .zip" 按钮接 `POST /import-zip`。
- `PaperWriterPage` 在 `layout==="bundle"` 时早 return 进入 `BundleExplorer`：左侧文件树（按顶级目录分组、可过滤），右侧 Monaco 编辑器（按扩展名挑语言：markdown / latex / bibtex / python / json / yaml / …）；二进制文件渲染成"binary placeholder + Download"。
- 所有 UI 字符串走 `i18n/locales/{en,zh}.json` 的 `manuscripts.*` + `bundle.*` 命名空间，并启用 i18next 的 `_plural` 复数。

### 11.8 Bundle 自动写入与提案（P8）

P8 把 bundle 从"人工 + 前端"扩展到"agent 自动 + 提案 gate"。整条链路严格分层、对单文档稿件零影响、对 link 模式有专门的风险拒绝。

**调用图（仅 bundle 路径）**：

```
POST /api/tasks {workflow=revision|write, input.manuscript_id, input.bundle_target}
  → InMemoryTaskQueue → execute_task
        ① BundleAdapter.maybe_build  (返回 None ⇒ 走旧 commit_version)
        ② Workflow.run               (revision 用 ctx.input.text；
                                       runner 已把 bundle 文件预读为 text)
        ③ _maybe_commit_manuscript
              · revision: write_text(bundle_target, results.revised)
              · write   : write_text(bundle_target, results.markdown)
                          + 可选 _maybe_register_in_main(\input{...})
              · → 返回 BundleChange(before/after/target)
              · 同时发 SSE 事件 manuscript.bundle_write
        ④ _maybe_run_evolver(bundle_change=…)
              · EvolverAgent._enrich_with_bundle_change:
                  - target_paths = [target]
                  - diff = difflib.unified_diff(before, after)   ← 仅人类阅读
                  - extras = {manuscript_id, bundle_target,
                              bundle_before, bundle_after, workflow}
              · 草稿存进 ProposalStore(status="draft")

POST /api/proposals/{id}:apply-to-bundle  (admin)
  → 校验 status / extras / 风险 / 链接模式 / 新鲜度
  → BundleStorage.write_text(manuscript, bundle_target, extras.bundle_after)
  → store.patch(extras += applied_to_bundle_at/by/size)   ← 不动 status
```

**关键不变量**：

| 不变量 | 在哪强制 |
|---|---|
| Workflow 不知道 layout / bundle_target | `WorkflowContext.bundle` 是 `Any` 类型；workflow 只读 `ctx.input["text"]`，所有 layout 分支都在 runner 里 |
| 单文档老路径不被打扰 | `BundleAdapter.maybe_build` 在任何 fallback 情况都返回 `None`；`_maybe_commit_manuscript` 的 bundle 分支只在 `bundle is not None` 时进入；`apply-to-bundle` 不存在于状态机里 |
| 自动写入不能越界 | 所有写入都过 `BundleStorage.write_text` → `_safe_resolve` + 单文件 / bundle 总大小 cap，路径 traversal 在 storage 层就被拒 |
| EvolverAgent 不直接改文件 | 它只产出 `Proposal`；写入只发生在 `apply-to-bundle` 端点，需要 admin 权限 |
| `apply` 与 `apply-to-bundle` 解耦 | `apply` 仍然只 stamp 状态；`apply-to-bundle` 不动 status，只在 extras 里加 `applied_to_bundle_at/by/size` |
| 提案的"新鲜度"不被默默吞掉 | apply-to-bundle 在写之前比较 `extras.bundle_before` 与磁盘上当前内容，不一致直接 409，要 force=true 才覆盖 |
| 链接稿件不接受高风险自动写 | `manuscript.bundle_link_path` 非空 + `proposal.risk_level != "low"` ⇒ 403 |

**Diff 字段 vs apply payload**：proposal.diff 是 unified diff，仅供 UI 渲染（`Editor language="diff"`）；apply 的实际写回内容来自 `extras.bundle_after`。这样我们既保留了"unified diff 是契约"的语义，又避免实现/维护一个 diff applier。

**前端 surface**：

| 页面 | 改动 |
|---|---|
| `RevisionPage` | bundle 稿件走专门的 `BundleRevisionStudio`（target 文件 picker + 单文件 before/after diff），单文档保留 `SingleRevisionStudio`（版本链 + diff） |
| `BundleExplorer` | 编辑器工具栏新增 "Revise this file"，深链跳到 `RevisionPage?manuscript=…&bundle_target=…` |
| `ProposalsPage` | 当 `extras.bundle_target` 非空时显示 "Bundle change" 卡片：目标路径 / 稿件 ID / 上次写入时间 + "Apply to bundle" 与 "Force" 按钮（独立于 `Apply` 状态键）|
| i18n | 新增 `revision.bundle.*` / `proposals.actions.applyToBundle*` / `proposals.bundle.*` / `bundle.reviseThisFile*`，en/zh 双语真翻译 |

---

## 12. 机械门禁（合并条）

每次提交都要过这 6 道检查（本地 `make check` + CI `.github/workflows/consistency.yml`）：

| 工具 | 检查内容 | 何处运行 |
|---|---|---|
| `ruff format` + `ruff check` | 风格 + lint（禁 `print`、禁裸 `Exception`、禁 SDK 边界外的 `Any`…） | 本地 + CI |
| `mypy backend` | 严格类型（每个 `# type: ignore` 都要有理由） | 本地 + CI |
| `pytest backend/tests -q` | 全套单元 + 集成测试（当前 703 通过、1 跳过） | 本地 + CI |
| `npm --prefix frontend run typecheck` + `build` | TS strict + 生产构建成功 | 本地 + CI |
| `scripts/check_consistency.py` | 结构性约束 —— 见下 | `make consistency` + CI |
| `.github/workflows/consistency.yml` | 同上，每次 push / PR 跑一次 | 仅 CI |

**`scripts/check_consistency.py` 检查的不变量**（每条都有 `Fix:` 提示）：

- 每个 `skills/*/SKILL.md` 有必填 frontmatter + 已知 `domain`
- 每个 `rules/*.md` 有必填 frontmatter
- 每个 `backend/api/routers/` 下的 router 文件都被 `routers/__init__.py` 导入
- 每个具体的 `BaseWorkflow` 子类有非空 `name`
- 每个导航地图列出的目录都有 `AGENTS.md`
- `backend/**/*.py` 与 `scripts/**/*.py` 里没有 `print(...)` 调用
- `frontend/src/**/*.tsx` 里没有内联 `fetch()` / `new EventSource()`（必须走 `@/lib/api` / `@/hooks/useSSE`）
- 每个 router 都有对应的 `backend/tests/integration/test_app_<resource>.py`

原则是 *"文档会过期、Lint 不会"* —— 你想在 markdown 里写"记得做 X"时，先想能不能换成一道检查。

---

## 13. "去哪改…" 速查表

| 你想… | 改这里 | 然后还要改 |
|---|---|---|
| 加一个新 LLM Provider | `backend/core/llm/<name>.py` 写 Adapter；`backend/core/llm/registry.py` 注册；在 `backend/core/runtime_config.py:SUPPORTED_PROVIDERS` 加白名单 | 加 `backend/tests/unit/test_<name>_provider.py`；`docs/runtime-internals.md` §3 的图 |
| 换默认压缩阈值 | `backend/settings.py:Settings.autocompact_threshold` | 同步 `.env.example` 的注释 |
| 加一个新 Workflow | `backend/workflows/<name>.py:<Name>Workflow(BaseWorkflow)` | `backend/workflows/__init__.py` 导出；可选 `backend/tests/integration/test_app_<name>_workflow.py` |
| 加一个 Skill | `skills/<name>/SKILL.md` + 可选脚本 | 直接热重载或 `/api/skills/reload` |
| 加一个 Rule | `rules/<name>.md` + frontmatter | 重启或 `/api/rules/reload`（如有） |
| 加一个 HTTP 端点 | `backend/api/routers/<resource>.py` | `routers/__init__.py` 导入；写 `tests/integration/test_app_<resource>.py`（机械门禁强制） |
| 加一个前端页面 | `frontend/src/pages/<Name>Page.tsx` | `frontend/src/routes/index.tsx` 注册路由；`Sidebar.tsx` 加导航；`i18n/locales/{en,zh}.json` 加 namespace |
| 调整稿件大小上限 | `backend/settings.py:Settings.manuscript_max_{file,bundle}_mb` | 同步 `.env.example` 的注释 |
| 加一种 Bundle 文件忽略规则 | `backend/manuscripts/bundle_storage.py:DEFAULT_IGNORE_{DIRS,FILES}` | 加 unit 测试；同步 §11.5 |

---

## 14. 术语表

| 术语 | 含义 |
|---|---|
| **Workflow** | `BaseWorkflow` 子类，组织一次任务的 stage 序列 |
| **WorkflowContext** | 单次任务运行的"上下文对象"，挂载 llm / memory / tools / state |
| **Stage** | Workflow 内一段语义清晰的子步骤；每个 stage 都会发出 `stage_started/done/error` 事件 |
| **Event** | 不可变 dataclass，记一次有意义的副作用；写 `TaskStore.events` + 广播 SSE |
| **Skill (L1)** | `SKILL.md` 定义的能力，按 query 匹配后才注入 prompt |
| **Rule (L2)** | `rules/*.md` 定义的行为约束，无条件注入 system prompt 或作 pre-action hook |
| **Heuristic (L3)** | 从历史成功 run 学出来的策略，存 `heuristic` store；也是 `Proposal` 的常见类型 |
| **MemoryBundle** | 6 个 store 的统一门面 |
| **Compactor** | `CompactingLLMProvider`，自动压缩超长 messages |
| **Routing** | `RoutingLLMProvider`，按 `route` 标签挑实际 Provider |
| **Telemetry** | `TelemetryRecorder`，进程内 LLM 用量 / 成本 / 错误环形缓冲 |
| **Proposal** | 自进化产出，状态机 `draft → pending → approved → applied` |
| **Onboarding** | 首启时的 LLM Provider 配置向导（Phase C 引入） |
| **Runtime override** | `data/runtime/provider.yaml`，前端 Settings 面板写入的 LLM 配置覆盖（Phase A 引入） |
| **Bundle (P7)** | 项目目录形态的稿件（`layout="bundle"`）；多文件、可被 git/Overleaf 共管 |
| **Copy 模式** | AAF 持有该 bundle 物理目录（`./data/manuscripts/<id>/work/`），自包含 |
| **Link 模式** | bundle 物理根 = 用户提供的外部目录；AAF 只读写、不复制、不删除 |
| **BundleStorage** | `backend/manuscripts/bundle_storage.py` 内的路径安全 + 大小限制 + tree/read/write/delete/import/export 总线 |
| **Overleaf 子目录约定** | bundle 根下的 `overleaf/`；export-zip 默认只打包它 |

---

*维护提示：本文与 `runtime-internals.md`（英文）章节编号严格对齐。改动其中一份请同步另一份；CI 不强制双语 diff，但 PR review 会人工比对。*
