# Academic Agent Framework — 设计与复现蓝图

> **版本**：v0.1（初始设计稿）  
> **日期**：2026-04-23  
> **目标读者**：任何具备基本工程能力的开发者，或任何有代码工具调用能力的 LLM Agent。  
> **目标**：仅凭本文档 + 源仓库 `Academic-Agent/`（作为学术 Skill 原始资产来源），在**任意一台 Linux/macOS 机器**上完整复现本框架。  
> **非目标**：不讨论具体实验、不绑定任何商业 LLM 提供方、不依赖 Cursor/Claude Code 等特定 IDE。

---

## 目录

| # | 章节 | 内容 |
|---|---|---|
| [1](#1-项目定位) | 项目定位 | 这是什么、不是什么 |
| [2](#2-核心设计哲学) | 核心设计哲学 | 六条不可妥协的原则 |
| [3](#3-系统架构总览) | 系统架构总览 | 分层图与数据流 |
| [4](#4-三层-skill--rule-体系) | 三层 Skill / Rule 体系 | L1 能力 / L2 纪律 / L3 经验 |
| [5](#5-目录结构规范) | 目录结构规范 | 完整目录树与各目录契约 |
| [6](#6-skill-host-详细设计) | Skill Host 详细设计 | Loader / Matcher / Injector / Executor |
| [7](#7-rule-engine-设计) | Rule Engine 设计 | 规则加载、注入、硬约束执行 |
| [8](#8-heuristic-store-与-evolver-设计) | Heuristic Store 与 Evolver | L3 自进化策略 |
| [9](#9-llm-provider-抽象层) | LLM Provider 抽象层 | 统一协议、多后端适配 |
| [10](#10-agent-engine-与-workflow) | Agent Engine 与 Workflow | 核心 Agent、四种预制 Workflow |
| [11](#11-memory-子系统) | Memory 子系统 | 五类 store 的职责与契约 |
| [12](#12-tool-registry) | Tool Registry | 工具注册、权限、调用契约 |
| [13](#13-backend-api-设计) | Backend API 设计 | REST + SSE，完整端点清单 |
| [14](#14-frontend-设计) | Frontend 设计 | 页面结构、关键组件、状态 |
| [15](#15-sdk--cli) | SDK / CLI | Python SDK、TypeScript SDK、CLI |
| [16](#16-部署方案) | 部署方案 | Docker Compose、Nginx、备份 |
| [17](#17-安全沙箱性能) | 安全、沙箱、性能 | Skill 执行隔离、超时、成本控制 |
| [18](#18-从-academic-agent-迁移) | 从 Academic-Agent 迁移 | 三步迁移法 |
| [19](#19-工程-skill-aaf-) | 工程 Skill（aaf-*） | 给 AI 编程助手看的施工说明书 |
| [20](#20-milestone-实施路线) | Milestone 实施路线 | M0 → M7 + P0–P8 分阶段目标 |
| [21](#21-验收测试评估) | 验收、测试、评估 | 各层交付标准 |
| [22](#22-技术选型与版本) | 技术选型与版本 | 锁定版本号清单 |
| [23](#23-附录) | 附录 | SKILL.md frontmatter、API Schema、错误码、ENV 列表 |

---

## 1. 项目定位

### 1.1 一句话定义

**Academic Agent Framework（简称 AAF）** 是一个**面向学术工作的、LLM 无关的、自带 Skill 运行时的开源 Agent 框架**。

### 1.2 解决什么问题

现状 Academic-Agent 已经在 Cursor 内部实现了：
- 多 Agent 协作（Planner / Executor / Evaluator / Evolver）
- 三层记忆（Semantic / Episodic / Procedural）
- 15 个学术 Skill（调研、精读、写作、改稿、rebuttal、综述、PPT…）
- A-Mem 进化式记忆（typed_links、synthesis notes、session reflections）

但它**只在 Cursor 里活得了**：Skill 靠 Cursor 扫描 `.cursor/skills/` 加载，工具执行依赖 Cursor 的沙箱，LLM 被绑定在 Cursor 支持的模型上。

AAF 的目标：把上面所有资产**保留并放大**，但把"宿主环境"替换成**自研的、可独立部署的、对任意 LLM 开放的运行时**。

### 1.3 产品形态

同一份代码以四种形态分发：

| 形态 | 接入方式 | 典型用户 |
|---|---|---|
| Web 应用 | 浏览器访问，图形化 UI | 科研终端用户 |
| HTTP API | REST + SSE | 二次开发者、脚本集成 |
| Python SDK | `pip install academic-agent-framework` | 科研自动化流水线 |
| CLI | `aaf research/write/revise` | CI、后台批处理、命令行爱好者 |

可选：导出为 **MCP Server**，反向接入 Cursor / Claude Desktop / 任意 MCP 兼容客户端，形成生态闭环。

### 1.4 关键承诺（SLA）

1. **任意 LLM**：凡是能说 OpenAI-compatible 协议的模型，**零代码改动**即可接入；Anthropic、Gemini 等非兼容协议通过 adapter 一键接入。
2. **私有部署**：单机 Docker Compose 一键启动；也可拆分到多台机器。
3. **离线可用**：本地 LLM（Ollama / vLLM） + 本地向量库 + 本地 PDF 解析器，无外网也能跑（除非用户主动检索外部论文库）。
4. **数据主权**：所有记忆、论文、笔记永久存储在用户自己的磁盘 / 对象存储，无任何上云。

### 1.5 明确的非目标

- **不做**通用 coding agent（Cursor/Claude Code 已经做得很好）
- **不做**商业 SaaS 多租户（初版只考虑单机 / 单组织私有部署）
- **不做**"取代 LLM"的事——框架提供的是**专业知识 + 纪律 + 记忆**，推理仍然交给 LLM

---

## 2. 核心设计哲学

这六条是地基，**任何后续设计决策都必须回答"是否违反这些原则"**。

### 2.1 Skill 是一等公民

AAF 的全部能力都通过 **Skill** 表达。所谓 Skill 就是一个**自包含目录**：

```
skills/<skill-name>/
├── SKILL.md          # YAML frontmatter + Markdown 正文
├── scripts/          # 可执行 Python 脚本（框架沙箱运行）
├── references/       # 模板、示例（只读材料）
└── evals/            # Skill 自我测试
```

Skill 格式沿用 **Anthropic Agent Skills 开放规范**，向下兼容 Cursor 与 Claude Code。添加新能力 = 新建一个 skill 目录；删除能力 = 删除目录。**没有硬编码 if/else 分发**。

### 2.2 Rules 是纪律，不是能力

Skill 告诉 Agent "你会什么"；Rule 告诉 Agent "你必须/禁止什么"。Rule 是**无条件注入**的 system prompt 不变量，外加（可选）**Pre-Action Hook**，在 Agent 写入敏感区域（如 knowledge store）前强制拦截。

### 2.3 LLM 是可替换的推理内核

框架不假设任何 LLM 能力上限。所有 Skill / Rule / Tool 都必须在"**最差可用模型**（如 7B 本地模型）"上能运行（可能质量下降，但不能崩溃）。具体措施：
- Prompt 模板保守（不依赖 GPT-4 级别的推理跳跃）
- Tool 描述详尽（不假设 LLM 能"猜"出参数语义）
- 失败路径明确（工具调用失败 → 重试 → 降级 → 人工介入信号）

### 2.4 记忆是显式的、可审计的

所有"Agent 记住的东西"必须**以文件或数据库记录形式存在**，不得只存在 LLM context。内存状态（session state）定期 flush 到持久层。这保证：
- 用户可以**查看、修改、删除**任何记忆
- 系统重启后记忆不丢
- 可做版本控制、回放、A/B 对比

### 2.5 进化是可关闭的

Evolver（自进化模块）可能产生**错误经验污染记忆库**。框架必须：
- Evolver 可配置为 dry-run（只产出候选，不落盘）
- 所有 Evolver 产物带 `source_run_id`，可追溯并批量回滚
- 用户可手动冻结某条 heuristic

### 2.6 Prompt 即代码

所有 Prompt 模板（Planner、Executor、Evaluator、Evolver、Skill 内部的 LLM 调用）**必须存在独立文件里**（`prompts/*.md` 或 Jinja2 模板），而非散落在 Python 字符串中。版本化、diff-able、可被用户覆写。

---

## 3. 系统架构总览

### 3.1 分层图

```
┌────────────────────────────────────────────────────────────────┐
│  ⑦ 交付层                                                       │
│  Web UI (React 19)│  REST/SSE API │  Python SDK  │  CLI  │ MCP │
└───────────┬────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────┐
│  ⑥ 编排层  Workflows                                            │
│  research / write / revise / rebuttal / survey / custom         │
└───────────┬────────────────────────────────────────────────────┘
            │
┌───────────▼────────────────────────────────────────────────────┐
│  ⑤ Agent 层  Planner / Executor / Evaluator / Evolver           │
│  （共用同一 LLM Provider + Skill Host + Memory）                 │
└─────┬──────────────────┬────────────────┬──────────────────────┘
      │                  │                │
┌─────▼────────┐  ┌──────▼────────┐  ┌────▼──────────────────┐
│ ④ Skill Host │  │ ③ Rule Engine │  │ ② LLM Provider Layer  │
│              │  │               │  │                        │
│ loader       │  │ rule loader   │  │ OpenAICompatible       │
│ matcher      │  │ system prompt │  │ Anthropic              │
│ injector     │  │ pre-hook      │  │ Ollama / vLLM          │
│ executor     │  │               │  │ MockProvider (tests)   │
└─────┬────────┘  └───────────────┘  └────────────────────────┘
      │
┌─────▼──────────────────────────────────────────────────────────┐
│  ① 资产与存储层                                                 │
│  skills/   rules/   data/skills/(L3)   memory/(5 stores)       │
│  tools/    prompts/                                             │
│  Postgres  Redis  Chroma  MinIO/S3                              │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 请求流（以"写一篇 RLHF 综述引言"为例）

1. **前端** POST `/api/v1/write`，body = `{mode:"intro", query:"RLHF survey intro", llm:"gpt-4o-mini"}`
2. **API 层** 创建 `task_id`，入 ARQ 队列，立即返回；同时打开 `/api/v1/tasks/{id}/stream`（SSE）
3. **Worker** 拉起 `write` workflow
4. **Rule Engine** 加载所有 `rules/*.md`，拼入 system prompt 头部
5. **Skill Host · Matcher** 根据 query 选出 L1 skill：`paper-writing`、`literature-search`；并从 L3 Heuristic Store 拉出匹配的 `writing` 域策略
6. **Skill Host · Injector** 把 SKILL.md body + L3 hints + tool schema 合成为 LLM 请求
7. **LLM Provider** 调用用户指定的模型（OpenAI / Anthropic / Ollama…），流式返回
8. LLM 决定调用 `paper-writing/scripts/outline_generator.py`
9. **Skill Host · Executor** 在沙箱子进程运行该脚本，stdout 作为 tool-response 回流 LLM
10. 过程中每个阶段 emit 事件 → ARQ 推到 Redis pubsub → SSE 推给前端
11. Workflow 结束 → **Evolver** 读取轨迹 → 若质量分 > 阈值，写入 `data/skills/writing/` 形成 L3 新策略
12. 结果 + 轨迹落 Postgres；产物（`.md/.tex/.pdf`）落 MinIO

### 3.3 关键数据流

```
用户 query
   │
   ▼
┌─────────────────────┐
│ Rule Engine 注入    │
│ （system prompt 头） │
└─────┬───────────────┘
      │
      ▼
┌─────────────────────┐      ┌──────────────────┐
│ L1 Skill Matcher    │─────▶│ 召回 1-3 个 Skill │
│ （embedding + trig） │      └──────────────────┘
└─────┬───────────────┘
      │
      ▼
┌─────────────────────┐      ┌──────────────────┐
│ L3 Heuristic Match  │─────▶│ 召回 0-3 条策略   │
└─────┬───────────────┘      └──────────────────┘
      │
      ▼
┌─────────────────────┐
│ Prompt Composer     │  ← Skill body + L3 hints + Rule + memory summary
└─────┬───────────────┘
      │
      ▼
┌─────────────────────┐
│ LLM Provider        │  ─── tool call ───▶ Skill Host · Executor
│ （stream）           │  ◀─ tool result ──
└─────┬───────────────┘
      │
      ▼
最终产物 + 轨迹 → Memory + Evolver
```

---

## 4. 三层 Skill / Rule 体系

这是 AAF 最重要的概念切分，**从此以后文档里出现 skill 一词必须标明层级**。

### 4.1 L1 · Capability Skills（能力技能）

**定位**：定义"Agent 会做什么"。

| 维度 | 内容 |
|---|---|
| 存储 | `skills/<name>/` 目录，项目根下，与语言无关 |
| 格式 | Anthropic Agent Skills 规范：`SKILL.md`（YAML frontmatter + Markdown 正文）+ 可选 `scripts/`、`references/`、`evals/` |
| 写作者 | 人（开发者、领域专家） |
| 读取者 | 框架运行时 Skill Host |
| 初始集合 | 从 `Academic-Agent/.cursor/skills/` 原样迁移 15 个：`autoresearch`, `literature-search`, `paper-reading`, `paper-writing`, `paper-revision`, `rebuttal-writer`, `survey-writing`, `survey-table`, `brainstorming`, `creative-thinking`, `download-paper`, `paper-presentation`, `pptx`, `presentation-maker`, `skill-creator` |
| 扩展方式 | 新建目录 → 框架启动时自动发现 |
| 禁止 | 在 Python 代码里硬编码"当 query 含 X 时做 Y" |

**frontmatter 最小契约**（详见 §23.1）：

```yaml
---
name: paper-writing              # 必填，目录名一致
description: >                   # 必填，给 LLM 看的何时使用
  Generate outlines, draft sections...
domain: writing                  # 推荐，用于 L3 分区
triggers: [write paper, 论文写作] # 推荐，matcher 字面关键词
compatibility:
  requires: [python>=3.11]
version: "1.0.0"                 # 推荐
---
```

### 4.2 L2 · Behavior Rules（行为纪律）

**定位**：定义"Agent 必须遵守什么"。

| 维度 | 内容 |
|---|---|
| 存储 | `rules/<name>.md`，项目根下 |
| 格式 | 简化 frontmatter + Markdown 正文，详见 §23.2 |
| 写作者 | 人（系统设计者） |
| 读取者 | 框架运行时 Rule Engine |
| 初始集合 | 从 `Academic-Agent/.cursor/rules/` 迁移：`knowledge-protection.md`、`self-evolution.md` |
| 注入方式 | 拼进 system prompt **最顶部**（优先级最高） |
| 强制手段 | 可选声明 `enforcement: hook`，触发 Pre-Action Hook 在代码层拦截 |

### 4.3 L3 · Heuristic Skills（经验技能）

**定位**：Agent 自己从过往成功里沉淀的"心得"。

| 维度 | 内容 |
|---|---|
| 存储 | `data/skills/<domain>/skill_<id>.yaml` + `_index.yaml`（各 domain 一份） |
| 格式 | YAML，字段：`id, name, domain, trigger_pattern, strategy{planning_hints, search_tips, evaluation_criteria}, success_count, source_run_id, created_at, updated_at`（详见 §23.3） |
| 写作者 | 框架 · Evolver 模块（自动） |
| 读取者 | 框架 · Skill Host · Matcher（按 trigger_pattern 字面/语义匹配后 inject 为 hint） |
| 初始集合 | 从 `Academic-Agent/data/skills/` 迁移 3 条（全部是 research 域），后续按 `domain` 字段分区：`research/`, `writing/`, `revision/`, `rebuttal/`, `survey/` |
| 生命周期 | 有 `success_count`（正反馈）+ `failure_count`（负反馈），淘汰阈值可配置；用户可手动冻结 |

### 4.4 三层协作示意

```
用户: "写一篇 RLHF 奖励模型综述的相关工作"
             │
             ▼
  ┌────────────────────────────────┐
  │ L2 Rules                        │  ← 永远注入，不看 query
  │   knowledge-protection          │
  │   self-evolution                │
  └────────────────────────────────┘
             │
             ▼
  ┌────────────────────────────────┐
  │ L1 Skills（Matcher 挑选）       │  ← 主要能力
  │   paper-writing                 │
  │   survey-writing                │
  │   literature-search             │
  └────────────────────────────────┘
             │
             ▼
  ┌────────────────────────────────┐
  │ L3 Heuristics（Matcher 挑选）   │  ← 经验辅助
  │   "gap-driven multi-direction   │
  │    RL/reward model research"    │
  └────────────────────────────────┘
             │
             ▼
       合并进 Prompt 后交给 LLM
```

---

## 5. 目录结构规范

**完整目录树**（`~/Code/academic-agent-framework/`）：

```
academic-agent-framework/
│
├── PLAN.md                              # 本文件
├── README.md                            # 用户向
├── LICENSE                              # MIT
├── pyproject.toml                       # Python 工程定义 (uv)
├── uv.lock
├── .env.example                         # ENV 变量模板
├── docker-compose.yml                   # 一键部署
├── docker-compose.dev.yml               # 开发覆盖
├── Makefile                             # 常用命令封装
│
├── skills/                              # ★ L1 运行时能力（迁入）
│   ├── autoresearch/
│   ├── literature-search/
│   ├── paper-reading/
│   ├── paper-writing/
│   ├── paper-revision/
│   ├── rebuttal-writer/
│   ├── survey-writing/
│   ├── survey-table/
│   ├── brainstorming/
│   ├── creative-thinking/
│   ├── download-paper/
│   ├── paper-presentation/
│   ├── pptx/
│   ├── presentation-maker/
│   └── skill-creator/
│
├── rules/                               # ★ L2 运行时纪律（迁入）
│   ├── knowledge-protection.md
│   └── self-evolution.md
│
├── prompts/                             # 所有 Prompt 模板
│   ├── planner/
│   │   ├── base.md
│   │   └── with_heuristic.md
│   ├── executor/
│   ├── evaluator/
│   └── evolver/
│
├── data/                                # ★ L3 经验 + 运行时数据
│   ├── skills/                          # L3：Evolver 产物
│   │   ├── _index.yaml
│   │   ├── research/
│   │   ├── writing/
│   │   ├── revision/
│   │   ├── rebuttal/
│   │   └── survey/
│   ├── knowledge/                       # 论文结构化笔记 YAML
│   ├── chroma/                          # 向量库本地数据
│   ├── papers/                          # 原始 PDF 与解析中间产物
│   └── cases/                           # episodic memory
│
├── backend/
│   ├── __init__.py
│   ├── main.py                          # FastAPI 入口
│   ├── settings.py                      # Pydantic Settings
│   ├── core/                            # 框架内核
│   │   ├── llm/
│   │   │   ├── base.py
│   │   │   ├── openai_compat.py
│   │   │   ├── anthropic.py
│   │   │   ├── ollama.py
│   │   │   ├── mock.py
│   │   │   └── registry.py
│   │   ├── skill_host/
│   │   │   ├── loader.py
│   │   │   ├── matcher.py
│   │   │   ├── injector.py
│   │   │   ├── executor.py
│   │   │   └── registry.py
│   │   ├── rule_engine.py
│   │   ├── prompt_composer.py
│   │   ├── tool_registry.py
│   │   └── events.py                    # 事件总线定义
│   ├── agents/
│   │   ├── planner.py
│   │   ├── executor.py
│   │   ├── evaluator.py
│   │   └── evolver.py
│   ├── workflows/
│   │   ├── base.py
│   │   ├── research.py
│   │   ├── write.py
│   │   ├── revise.py
│   │   ├── rebuttal.py
│   │   └── survey.py
│   ├── memory/
│   │   ├── vector_store.py
│   │   ├── knowledge_store.py
│   │   ├── heuristic_store.py
│   │   ├── episodic_store.py
│   │   └── session_store.py
│   ├── tools/                           # 通用工具（非 skill 内部 scripts）
│   │   ├── arxiv.py
│   │   ├── semantic_scholar.py
│   │   ├── pdf_parser.py
│   │   ├── web_search.py
│   │   ├── bibtex.py
│   │   └── latex_compile.py
│   ├── api/
│   │   ├── __init__.py
│   │   ├── deps.py
│   │   ├── auth.py
│   │   ├── routers/
│   │   │   ├── research.py
│   │   │   ├── write.py
│   │   │   ├── revise.py
│   │   │   ├── memory.py
│   │   │   ├── skills.py
│   │   │   ├── rules.py
│   │   │   ├── models.py
│   │   │   ├── tasks.py
│   │   │   └── health.py
│   │   └── schemas/                     # Pydantic request/response models
│   ├── workers/                         # ARQ workers
│   │   ├── __init__.py
│   │   └── tasks.py
│   ├── db/
│   │   ├── models.py                    # SQLAlchemy
│   │   ├── session.py
│   │   └── migrations/                  # Alembic
│   └── tests/
│       ├── unit/
│       └── integration/
│
├── sdk/
│   ├── python/                          # pip install academic-agent-framework
│   │   └── aaf/
│   └── ts/                              # npm @aaf/sdk
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   ├── components.json                  # shadcn/ui registry
│   ├── index.html
│   └── src/
│       ├── main.tsx
│       ├── App.tsx
│       ├── routes/                      # React Router 7 route tree
│       ├── stores/                      # Zustand stores
│       ├── api/                         # HTTP + SSE client
│       ├── hooks/                       # useSSE / useTaskMonitor / …
│       ├── components/
│       │   ├── ui/                      # shadcn/ui primitives
│       │   ├── research/
│       │   ├── writer/
│       │   ├── revision/
│       │   ├── memory/
│       │   └── common/
│       └── pages/
│           ├── Dashboard.tsx
│           ├── Research.tsx
│           ├── Writer.tsx
│           ├── Revision.tsx
│           ├── Memory.tsx
│           └── Settings.tsx
│
├── deploy/
│   ├── nginx/
│   │   └── default.conf
│   ├── postgres/
│   │   └── init.sql
│   └── backup.sh
│
├── cli/                                 # 复用 backend core 的轻封装
│   └── aaf.py
│
├── .cursor/                             # ★ 开发期专用，运行时不读
│   ├── skills/
│   │   ├── aaf-project-conventions/
│   │   ├── aaf-skill-host/
│   │   ├── aaf-llm-provider/
│   │   ├── aaf-backend-api/
│   │   ├── aaf-agent-workflow/
│   │   ├── aaf-memory-contract/
│   │   ├── aaf-frontend-react/
│   │   ├── aaf-tailwind-shadcn/
│   │   └── aaf-deploy/
│   └── rules/
│       ├── aaf-python-style.mdc
│       ├── aaf-react-style.mdc
│       └── aaf-api-contract.mdc
│
└── docs/
    ├── architecture.md
    ├── writing-your-own-skill.md
    ├── writing-your-own-llm-provider.md
    ├── deployment.md
    └── api-reference.md
```

**目录约束**：
- `skills/` 与 `rules/` 下**只能放用户面向的能力/纪律**，框架代码严禁写入
- `backend/core/` 与 `backend/agents/` **严禁直接读文件系统**，必须通过 `memory/` 或 `skill_host/` 接口
- `.cursor/` 目录在 Docker 镜像中**不打包**，仅在源码开发期存在
- `data/` 目录是**用户数据主权区**，镜像里为空 volume mount

---

## 6. Skill Host 详细设计

这是框架的**灵魂**。Cursor/Claude Code 在自家产品里实现了这套能力；AAF 必须独立实现一遍。

> **M7 起新增**：Skill 管理 HTTP API + UI（详见 §20.8 M7.2）。`SkillHost` 的 hot-reload / staging 流程会在 §6 现有内核基础上扩展，**核心运行时不变**。

### 6.1 职责边界

Skill Host 的唯一职责：**把 L1 skill 这个"目录型数据"变成 LLM 可消费的 prompt + 可调用的 tool，并安全执行 skill 内部脚本**。

它**不**：做业务决策、不调 LLM、不写 memory。它只做"加载—匹配—注入—执行"四件事。

### 6.2 Loader（`backend/core/skill_host/loader.py`）

**职责**：启动时扫描 `skills/`，产出 `SkillRegistry`。

**接口**：
```python
class SkillMeta(BaseModel):
    name: str
    path: Path
    description: str
    domain: str | None
    triggers: list[str]
    version: str
    requires: list[str]
    scripts: list[ScriptMeta]        # 扫描 scripts/ 得到
    references: list[Path]
    body: str                         # SKILL.md 去掉 frontmatter 后的 markdown

class SkillLoader:
    def load_all(self, root: Path) -> SkillRegistry: ...
    def reload(self, name: str) -> SkillMeta: ...    # 热更新
    def watch(self) -> None: ...                      # inotify / fsevents
```

**实现要点**：
- 解析 `SKILL.md` 用 `python-frontmatter`
- `scripts/` 下每个 `.py` 文件必须有顶部 docstring 和 `if __name__ == "__main__":` 入口，Loader 读取 docstring 作为 tool description
- 启动时为每个 `description` 生成 embedding（调用 default embedder），存入内存索引
- 提供文件监听，开发模式下自动 reload

### 6.3 Matcher（`matcher.py`）

**职责**：给定 query + 会话上下文，返回相关性最高的 skills。

**接口**：
```python
class SkillMatcher:
    def match(self, query: str, context: str = "", top_k: int = 3,
              min_score: float = 0.3) -> list[ScoredSkill]: ...
```

**算法**：
1. **关键词通道**：遍历 `triggers` 字段，命中次数为 `kw_score`
2. **语义通道**：embedding 相似度（query → description embedding），为 `sem_score`
3. **硬规则通道**：frontmatter 可声明 `exclusive: true`（如 `paper-presentation` 与 `paper-writing` 不应同时命中），matcher 保证互斥
4. 总分：`score = 0.4 * kw_score + 0.6 * sem_score`，阈值过滤后 top-k

**退化策略**：
- 无 embedder 时：退化为纯关键词
- 全未命中时：返回一个 fallback skill `general-assistant`（内置，见 §6.7）

### 6.4 Injector（`injector.py`）

**职责**：把选中的 skills 转成 LLM 请求的 `system_prompt_additions` + `tools` 列表。

**接口**：
```python
class SkillInjector:
    def inject(self, skills: list[ScoredSkill],
               heuristics: list[HeuristicSkill] = None
               ) -> InjectionBundle: ...

class InjectionBundle(BaseModel):
    system_additions: str           # 追加到 system prompt
    tool_specs: list[ToolSpec]      # OpenAI tool schema
    script_index: dict[str, Path]   # tool_name → scripts/xxx.py
```

**规则**：
- 多 skill 时，正文按 matcher 打分降序拼接，使用 `---` 分隔
- 每个 skill 生成一个或多个 tool（每个 script 一个），tool name 约定为 `{skill_name}__{script_stem}`
- L3 heuristic 作为"⚡ 实战经验"小节追加到 system 末尾
- 若注入后 prompt 超长度阈值（默认 8000 tokens），按 score 从低到高裁剪

#### 6.4.1 渐进式注入契约（progressive injection invariant）

这是用户要求 #2 "渐进式读取 skill" 的运行时保证：

> **only matched skills' bodies enter the prompt** —— 不论目录里有多少 SKILL.md，
> 一次 `select_and_inject(query, top_k=K)` 调用至多放 K 个 skill 的 body 进
> system prompt，未匹配的 SKILL 完全不出现在 LLM context 里。

具体到 Loader vs Injector 的分工：

| 阶段 | 读什么 | 何时读 | 进 LLM context？ |
|------|--------|--------|------------------|
| Loader（启动时） | 24× SKILL.md 的 frontmatter + body | 每次 `SkillHost.load()` | ❌ 只进 SkillRegistry |
| Matcher（每次请求） | description + triggers + 缓存的 description embedding | `SkillHost.select_and_inject(...)` | ❌ 只用于打分 |
| Injector（每次请求） | 仅 top-K 命中的 SkillMeta.body | 同上 | ✅ 被拼到 system_prompt_additions |

启动时一次性把所有 body 读进内存是显式选择（24 个文件 < 1 MB，简化并发 / 缓存），
真正"在 LLM 视角下渐进"的层是 Injector：未匹配的 SKILL 永远不会被 LLM 看见。

回归测试：`backend/tests/integration/test_skill_progressive_load.py` 跑真实 `./skills/`
（24 个 skill）打三个保证：

1. `len(bundle.matched_skills) <= top_k`，与 skill 总数解耦
2. 命中的 skill body 出现在 `system_additions` 里
3. 至少 3 个未命中 skill 的独特指纹串 **不出现** 在 `system_additions` 里
4. `top_k=3` 的 `system_additions` 长度 < 全 body 拼接长度的 40%

任何让 Injector 把全量 body 注入 prompt 的回归（比如有人改成"全量上下文给 LLM
判断"）都会被这套测试当场抓住。

### 6.5 Executor（`executor.py`）

**职责**：安全执行 skill 脚本，返回 stdout/stderr 给 LLM。

**接口**：
```python
class SkillExecutor:
    async def execute(self, script_path: Path, args: dict,
                      timeout: int = 120,
                      env: dict[str, str] = None) -> ExecResult: ...

class ExecResult(BaseModel):
    ok: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    artifacts: list[Path]          # 脚本输出的文件
```

**沙箱方案**（按隔离强度递增）：
1. **子进程**：默认方案。`subprocess` + resource limits（`RLIMIT_AS`, `RLIMIT_CPU`），`cwd` 锁到工作目录
2. **Docker exec**：生产推荐。每个 skill 一个预烘焙镜像或共用 `aaf-skill-runtime:latest`
3. **Firecracker / gVisor**：高安全场景可选

**环境变量白名单**：只透传 `AAF_WORKDIR`、`AAF_LLM_ENDPOINT`（给脚本回调自己的 LLM）、`AAF_TASK_ID`，其余全部清空。

**超时与强杀**：默认 120s，通过 ProcessGroup 强杀整个进程树。

### 6.6 Registry（`registry.py`）

薄封装，聚合 Loader / Matcher / Injector / Executor，提供面向 workflow 的高层 API：

```python
class SkillHost:
    async def select_and_inject(self, query: str, context: str) -> InjectionBundle: ...
    async def call_tool(self, tool_name: str, args: dict) -> ExecResult: ...
    def list_skills(self) -> list[SkillMeta]: ...
```

### 6.7 内置 Fallback Skill

框架自带一个 `skills/general-assistant/`，当 matcher 无命中时兜底：
- `SKILL.md` 只包含"按常识回答用户问题，若涉及学术研究建议调用具体工具"之类通用指令
- 无 scripts

---

## 7. Rule Engine 设计

**文件**：`backend/core/rule_engine.py`

### 7.1 Rule frontmatter

```yaml
---
name: knowledge-protection
scope: [planner, executor, evolver]   # 哪些 agent 受约束；默认全部
priority: 10                          # 数字越大越靠前
enforcement: prompt | hook            # prompt=仅文字；hook=代码强制
hook: backend.core.hooks.protect_knowledge  # enforcement=hook 时必填
---
```

### 7.2 加载与注入

```python
class RuleEngine:
    def load(self, root: Path) -> list[Rule]: ...
    def system_prompt(self, agent: str) -> str: ...     # 拼好的规则段
    async def pre_action(self, agent: str, action: Action) -> Action: ...
    # pre_action 对每条 enforcement=hook 的规则依次调用其 hook，
    # hook 可修改或阻断 action
```

### 7.3 Hook 协议

```python
async def protect_knowledge(action: WriteAction, ctx: Context) -> WriteAction | Block:
    # 若 action 试图写入 data/knowledge/ 但未经 Evaluator 签名 → Block
    ...
```

Hook 的 signature 固定：`async def <name>(action, ctx) -> Action | Block`。

---

## 8. Heuristic Store 与 Evolver 设计

### 8.1 数据模型（`memory/heuristic_store.py`）

```python
class HeuristicSkill(BaseModel):
    id: str                        # 12-hex
    name: str
    description: str
    domain: Literal["research", "writing", "revision", "rebuttal", "survey"]
    trigger_pattern: str           # 关键词逗号分隔，用于 matcher
    strategy: StrategyBlock        # planning_hints / search_tips / evaluation_criteria
    source_run_id: str
    success_count: int = 1
    failure_count: int = 0
    frozen: bool = False           # 冻结后不再参与匹配
    created_at: datetime
    updated_at: datetime
```

**存储**：`data/skills/<domain>/skill_<id>.yaml` + `data/skills/_index.yaml`（加速扫描）。

### 8.2 Matcher

复用 L1 Skill Matcher 的算法，对 `trigger_pattern` 和 `description` 做两路匹配。

### 8.3 Evolver

位置：`backend/agents/evolver.py`  
触发：每个 workflow 末尾。

**决策树**：
```
if verdict == "pass" and score >= threshold:
    # 成功路径
    existing = heuristic_store.match(query, top_k=3)
    if existing and similarity(existing[0], new_observation) > 0.85:
        heuristic_store.bump_success(existing[0].id)
    else:
        new_skill = extract_skill(trace, query, llm)
        heuristic_store.add(new_skill)
else:
    # 失败路径
    matched = heuristic_store.match(query, top_k=3)
    for s in matched:
        heuristic_store.bump_failure(s.id)
    if any skill.failure_count / total > 0.6: mark frozen
```

`extract_skill` 使用独立 prompt 模板（`prompts/evolver/extract.md`），让 LLM 回答三问："这次为什么成功？什么关键词能复用？下次遇到同类问题怎么做？"

### 8.4 回滚与审计

- `GET /api/v1/memory/heuristics/{id}/trace` → 返回 `source_run_id` 的完整轨迹
- `POST /api/v1/memory/heuristics/{id}/freeze` → 冻结
- `DELETE /api/v1/memory/heuristics/{id}` → 删除（软删，移入 `data/skills/_trash/`）
- `POST /api/v1/memory/heuristics/rollback?run_id=...` → 批量回滚某次运行产生的所有 heuristic

---

## 9. LLM Provider 抽象层

### 9.1 协议（`backend/core/llm/base.py`）

```python
class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart]
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

class ToolSpec(BaseModel):
    name: str
    description: str
    parameters: dict               # JSON Schema

class LLMProvider(Protocol):
    name: str
    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[CompletionChunk]: ...
    
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]: ...
    
    def supports_tools(self) -> bool: ...
    def supports_streaming(self) -> bool: ...
    def context_window(self, model: str) -> int: ...
    async def estimate_cost(self, messages, model) -> CostEstimate: ...
```

### 9.2 实现

- **`openai_compat.py`**：默认/兜底实现。任何暴露 `/v1/chat/completions`、`/v1/embeddings` 的服务都能接（OpenAI、DeepSeek、Moonshot、千问、vLLM、Ollama with OpenAI mode、LocalAI…）
- **`anthropic.py`**：使用 `anthropic` SDK，负责把框架 ToolSpec ↔ Anthropic tool_use schema 相互转换（区别：Anthropic 的 tool_result 作为 user 消息回传）
- **`ollama.py`**：（可选）Ollama 原生 API；推荐用户直接走 Ollama 的 OpenAI 兼容模式即可省掉此 adapter
- **`mock.py`**：测试/离线开发用，按预设 YAML 剧本返回响应

### 9.3 Registry

```python
class LLMRegistry:
    def register(self, name: str, factory: Callable[[dict], LLMProvider]): ...
    def get(self, name: str, config: dict) -> LLMProvider: ...
    def list(self) -> list[str]: ...
```

配置文件 `config/llm_providers.yaml`（可由前端 Settings 页改写）：

```yaml
providers:
  openai:
    type: openai_compat
    base_url: https://api.openai.com/v1
    api_key_env: OPENAI_API_KEY
    default_model: gpt-4o-mini
    models: [gpt-4o-mini, gpt-4o, gpt-4.1]
  anthropic:
    type: anthropic
    api_key_env: ANTHROPIC_API_KEY
    default_model: claude-3-5-sonnet-latest
  local-qwen:
    type: openai_compat
    base_url: http://ollama:11434/v1
    api_key_env: ""
    default_model: qwen2.5:14b
```

### 9.4 使用方与用量统计

- 所有 LLM 调用必须经过 `LLMRegistry.get(name).complete(...)`
- 框架在 `backend/core/llm/telemetry.py` 记录每次调用 (`provider, model, prompt_tokens, completion_tokens, duration_ms, cost_usd, task_id`)
- 前端 Settings 页展示用量曲线

### 9.5 任务级模型路由（M-Router）

> **设计目标**：同一个工作流里，不同 stage 用不同模型——比如 `research/planner` 用 `deepseek-reasoner`（强推理），`research/ingest_summarize` 用 `deepseek-chat`（快+便宜），离线场景全切 `ollama:llama3.1:8b`——而**不破坏 LLMProvider Protocol，也不强制每个部署都开**。

#### 9.5.1 抽象

`backend/core/llm/router.py` 新增 `RoutingLLMProvider`，包装一个 `default` provider + 一组 `name → provider` 路由：

```python
class RoutingLLMProvider:        # 满足 LLMProvider Protocol（代理到 default）
    def for_route(self, name: str | None) -> LLMProvider: ...
    @property
    def default_provider(self) -> LLMProvider: ...
    def route_names(self) -> list[str]: ...
```

* **代理语义**：`RoutingLLMProvider.complete/embed/...` 全部委托给 `default`，所以**老代码 0 改动**就能继续跑。
* **opt-in**：workflow 想换模型的地方显式写 `provider = ctx.llm.for_route("reasoning")`。
* **未知 route 名**降级为 `default`——部署侧新增/删除 route 不会让 workflow 崩。

#### 9.5.2 配置（`config/model_routing.yaml`）

```yaml
default:
  provider: openai                   # registry name
  api_key_env: DEEPSEEK_API_KEY
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat               # cheap/fast 默认
routes:
  reasoning:                         # 强推理（planner/evaluator/evolver）
    model: deepseek-reasoner         # 其余字段继承 default
  fast:                              # 快（ingest summary、tool 描述）
    model: deepseek-chat
  local:                             # 完全离线
    provider: ollama
    base_url: http://localhost:11434/v1
    model: llama3.1:8b
    api_key_env: ""
```

* 每个 route 缺省字段从 `default` 继承（provider / base_url / api_key 等）。
* `api_key_env` 指 ENV 变量名，**不准在文件里写明文 key**。
* **文件不存在 → 不启用 routing**（zero-config / 单 provider 行为完全保留）。

#### 9.5.3 装配（`backend/app.py:_build_llm`）

启动时按以下顺序：

1. `Settings.default_llm_provider` → 选 base provider（无 credential 走 mock）。
2. `load_routing_policy(settings.model_routing_config)` 读 yaml；缺文件返 `None`。
3. 若有 policy → `build_routing_provider(policy)` 包装；否则直接返 base。
4. 任意一步出错（`ConfigError` / `NotFoundError` / `OSError`）都 `log.exception` + 回退 base，**永不阻断启动**。

`AAF_MODEL_ROUTING_CONFIG` 环境变量覆盖配置路径（默认 `./config/model_routing.yaml`）。

#### 9.5.4 在 workflow 里使用

```python
# backend/workflows/research.py
async def _planner_stage(self, ctx: WorkflowContext) -> Plan:
    provider = ctx.llm.for_route("reasoning")   # 退化到 default 也能跑
    async for chunk in await provider.complete(messages):
        ...
```

集成测试用 `MockLLMProvider` 同时注册到 default + 各 route 名即可断言"reasoning stage 走了 reasoning route"。

#### 9.5.5 telemetry & UI

* `backend/core/llm/telemetry.record(...)` 接受新字段 `route` —— `RoutingLLMProvider` 的 `for_route` 返回的 sub-provider 在 wrapper 里调 record 时填入选中的 route 名。
* `/api/v1/models/usage` 按 `route` 维度聚合（已有按 `provider`/`model` 的统计基础）。
* 前端 Settings 页"模型用量"卡片新增"按 route 分布"分段。

#### 9.5.6 何时不该用

* 团队只用一个模型 → 别建 `model_routing.yaml`，保持 zero-config。
* MCP / tool call 链路 → 让 tool 自己决定模型（routing 只对 LLM 推理 stage 有意义）。

### 9.6 上下文自动压缩（M-Compactor）

> **设计目标**：长任务（多轮 rebuttal、整篇 paper drafter、跨多个 paper 的 survey）
> 的 prompt 会随着每轮拼接逐步逼近 context window —— 一旦撞上模型就抛 422。
> 我们要在用户感知到 token 上限之前**自动**压缩历史，且**不破坏 LLMProvider Protocol**，也**不强制每个部署都开**。

#### 9.6.1 抽象

`backend/core/llm/compactor.py` 新增 `CompactingLLMProvider`，是包在所有 LLM provider 外层的最终 wrapper（即装配顺序：`base → routing → compactor`）：

```python
class CompactingLLMProvider:    # 满足 LLMProvider Protocol
    async def complete(self, messages, ...) -> AsyncIterator[CompletionChunk]:
        if est_tokens(messages) > inner.context_window(model) * threshold:
            messages = await compact_messages(messages, summariser, model, keep_recent_n).compacted
        return await self._inner.complete(messages, ...)

    def for_route(self, name): ...   # 透传 routing 能力
```

* **压缩规则**：保留所有 `system` 消息 + 最近 `keep_recent_n` 条非 system → 中间历史让 summariser 用一次 LLM 调用浓缩成一条 `system` 消息插入末尾前。
* **summariser 选择**：调 `inner.for_route("fast")`（如果 routing 启用），否则用 inner 自己；用 `temperature=0.0` + `stream=False` 保证确定性。
* **递归保护**：用 contextvar `_INSIDE_COMPACTION`，summariser 自己调 `complete()` 时 wrapper 直接透传，杜绝死循环。
* **Token 估算**：`len(text) // 4` + 4/msg 系统开销 + 16/tool_call —— 不引入 `tiktoken` 依赖；阈值默认 0.7 留足误差余量。
* **可观测性**：每次 fire 一行 `log.info("llm.compacted", model, original_tokens, compacted_tokens, dropped_messages, duration_ms)`。

#### 9.6.2 配置（4 个 ENV）

| ENV | 默认 | 含义 |
|---|---|---|
| `AAF_AUTOCOMPACT_ENABLED` | `false` | opt-in 开关；off → wrapper 不构造 |
| `AAF_AUTOCOMPACT_THRESHOLD` | `0.7` | 占 context window 多少比例时触发；约束 `[0.1, 0.95]` |
| `AAF_AUTOCOMPACT_KEEP_RECENT_N` | `6` | 保留最近多少条非 system 消息 |
| `AAF_AUTOCOMPACT_SUMMARISER_ROUTE` | `"fast"` | summariser 的 route 名（routing 启用时） |

#### 9.6.3 失败处理

* settings 非法（如 threshold=2.0）→ `log.exception("app.llm.autocompact_disabled_invalid_settings")` + 跳过 wrapper（不阻断启动）。
* summariser 调用失败 → 异常上抛到调用方（workflow stage 已有 try/except 兜底；让用户看到错比悄悄丢历史更安全）。
* 压缩后 token 仍 > threshold → 不再二次压缩（保留语义完整 + log 记录），由调用方决定下一步（通常是 LLM 抛 `LLMContextWindowError`，workflow 走 retry 路径）。

#### 9.6.4 何时不该开

* 短任务（单轮 chat / tool 调用）→ 0 收益、白白多一次潜在 LLM 调用。
* 没有 routing 配置 + summariser 是 reasoner 类强模型 → 一次压缩可能比一次完整调用还贵。
* 想让 workflow 显式控制 history（自定义 reduce 策略）→ 关 wrapper，自己在 stage 里调 `compact_messages(...)` 即可。

### 9.7 本地嵌入器（M-LocalEmbed）

#### 9.7.1 问题

`LLMProvider.embed()` 默认走 chat 同源（OpenAI / DeepSeek 的 `/v1/embeddings`）。
两个痛点：
1. **离线模式不可用**：Ollama 端点没有 `/v1/embeddings`，强行走同一 provider 会抛 404，VectorStore 直接退化成关键词检索。
2. **成本/延迟**：所有向量库 add / query 都打远端 API，对 RAG-heavy 工作流不友好。

#### 9.7.2 设计

新增 `LocalSentenceTransformerEmbedder`（`backend/core/llm/local_embedder.py`），**只实现 `LLMProvider` 的 `embed()` 那一半**：

* `complete()` / `estimate_cost()` 抛 `NotImplementedError`，明确"它不是用来 chat 的"
* 第一次 `embed()` 调用时懒加载 SentenceTransformer 模型，后续调用复用
* `encode()` 用 `asyncio.to_thread` 卸载到工作线程，不阻塞事件循环
* 失败统一翻译成 `LLMAPIError`（与远端 provider 一致），让 VectorStore 的 fallback 逻辑保持单分支

启用方式（opt-in，默认 off）：

```ini
AAF_EMBEDDING_BACKEND=local                  # provider | local
AAF_LOCAL_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
# 可选：AAF_LOCAL_EMBEDDING_DEVICE=cpu / cuda / mps
# 可选：AAF_LOCAL_EMBEDDING_CACHE_FOLDER=./data/hf_cache
```

`backend/app.py:_build_embedder` 选 `local` 时构造 `LocalSentenceTransformerEmbedder`，**只**注入到 `MemoryFactory` 与 `SkillHost`（这两处只调 `embed()`），chat LLM 仍按 `DEFAULT_LLM_PROVIDER` 单独构造（典型组合：`ollama` 跑 chat + 本地 ST 跑 embed）。

#### 9.7.3 依赖与体积

* sentence-transformers 是**可选 extra**：`uv sync --extra offline` 才装（拉 torch ~ 1 GB）
* 默认模型 `BAAI/bge-small-en-v1.5`（133 MB, 384-dim）—— 笔记本可承受
* 想省更多：`sentence-transformers/all-MiniLM-L6-v2`（90 MB, 384-dim）
* 想多语言：`BAAI/bge-m3`（568 MB, 1024-dim）

未装 extra 而开了 `AAF_EMBEDDING_BACKEND=local` → 第一次 `embed()` 抛 `ConfigError("install with uv sync --extra offline")`，**不静默降级**：用户明确要求本地嵌入器，应该让他们看到具体错误而不是猜为啥 RAG 突然没结果。

#### 9.7.4 验收

* `backend/tests/unit/test_local_embedder.py`：encode 维度 / 空输入 / tolist 归一化 / 错误翻译 / `complete` 抛 NotImplementedError / `sys.modules[...] = None` 触发 ConfigError
* `backend/tests/integration/test_app_local_embedder.py`：用 `monkeypatch.setitem(sys.modules, ...)` 注入 fake `SentenceTransformer`，跑完整 lifespan，断言：
  - `state.memory.vector._embedder` 是 `LocalSentenceTransformerEmbedder`
  - `state.skill_host._matcher._embedder` 与 vector 同一对象
  - `vector.add(...) → vector.query(...)` 用本地嵌入器返回正确的 top-1
* `.env.offline.example`：Ollama 跑 chat + 本地 ST 跑 embed 的整套示例

---

## 10. Agent Engine 与 Workflow

> **设计决策（v0.1 修订）**：AAF **不引入 LangGraph / LangChain / CrewAI 等外部编排框架**，自研一套极简、可读、零魔法的 async Python 编排层。理由：  
> ① 现有 Academic-Agent 的 workflow 逻辑本就非常线性（`Planner → Executor → Evaluator → Evolver` + 最多一次 retry），LangGraph 的图式建模属于过度设计；  
> ② 保持零编排依赖意味着更好的可读性、可调试性、可审计性，**任何 LLM 都能凭本 PLAN 重写一遍**，而无需先学第三方 DSL；  
> ③ 事件发射、checkpoint、重试、分支这些能力用 <200 行 Python 即可实现，且与框架内部概念（emit、MemoryBundle、RuleEngine、SkillHost）完全对齐；  
> ④ 旧仓库 `Academic-Agent/workflows/research.py` 里 LangGraph 路径与 fallback 纯 Python 路径其实**并存**，迁移时直接采纳后者即可。

### 10.1 四个 Agent（沿用现有角色）

| Agent | 职责 | 关键输入 | 关键输出 |
|---|---|---|---|
| **Planner** | 拆分任务 | query + memory summary + heuristics | `list[Task]` |
| **Executor** | 调用 skills/tools 完成单个 task | task | 结果 + 轨迹 |
| **Evaluator** | 质量评分 | 所有结果 + reading notes | verdict + score + feedback |
| **Evolver** | 沉淀经验 | 轨迹 + verdict | 新 L3 skill / bump counter |

实现：每个 Agent 是一个 Python 类，构造器接受 `LLMProvider + SkillHost + MemoryBundle + RuleEngine` 依赖注入，**不存储全局状态**，所有中间数据都经 `WorkflowContext` 显式传递。

### 10.2 自研编排引擎（`backend/workflows/base.py`）

四个核心抽象，**总代码量目标 < 300 行**，任意 LLM 能基于下面接口重写。

#### 10.2.1 WorkflowContext（运行时上下文）

```python
class WorkflowContext:
    """一次 workflow run 的运行时上下文，显式替代图式编排框架的 State。"""
    task_id: str
    user_id: str | None
    session_id: str | None
    query: str
    input: dict                           # workflow 入参原始 dict
    llm: LLMProvider                      # 当前任务指定的 LLM
    memory: MemoryBundle                  # 五个 store 的聚合（§11）
    skill_host: SkillHost                 # §6
    rule_engine: RuleEngine               # §7
    budget: Budget                        # token / cost / wallclock 预算
    state: dict                           # workflow 自由状态（阶段间传递）
    trace: list[Event]                    # 完整事件轨迹（供 Evolver 读取）

    async def emit(self, event: Event) -> None:
        self.trace.append(event)
        await self._sink(event)           # 推到 Redis pubsub / SSE

    async def checkpoint(self, label: str) -> None:
        """把当前 state JSON 化持久化到 Postgres tasks.checkpoint 字段，
        允许任务 crash 后从 label 处恢复（见 §10.4）。"""
```

#### 10.2.2 BaseWorkflow

```python
class BaseWorkflow(ABC):
    name: ClassVar[str]
    version: ClassVar[str] = "1.0.0"

    @abstractmethod
    async def run(self, ctx: WorkflowContext) -> WorkflowOutput: ...

    async def stage(self, ctx, name: str, fn: Callable) -> Any:
        """一个 stage：自动 emit start/end、计时、异常捕获、budget 校验。
        替代 LangGraph 的 add_node + add_edge 样板代码。"""
        await ctx.budget.assert_ok()
        await ctx.emit(Event("task.stage_start", task_id=ctx.task_id,
                             data={"stage": name}))
        t0 = time.monotonic()
        try:
            out = await fn(ctx)
            await ctx.emit(Event("task.stage_end", task_id=ctx.task_id,
                data={"stage": name,
                      "duration_ms": int((time.monotonic()-t0)*1000)}))
            if ctx.checkpoint_enabled:
                await ctx.checkpoint(label=name)
            return out
        except Exception as e:
            await ctx.emit(Event("task.error", task_id=ctx.task_id,
                data={"stage": name, "message": str(e)}))
            raise
```

#### 10.2.3 编排原语（`backend/workflows/primitives.py`）

自研 5 个小工具，替代 LangGraph 的 `add_edge / conditional_edge / Send`。都是普通 async 函数，无魔法、无隐式状态——你甚至可以不用它们，直接写 `await foo(ctx); await bar(ctx)`。

```python
async def sequential(ctx, stages: list[Callable]) -> list[Any]: ...
async def parallel(ctx, stages: list[Callable], max_concurrency=4) -> list[Any]: ...
async def retry(ctx, fn, max_attempts=2, on=lambda e: True) -> Any: ...
async def branch(ctx, predicate, if_true, if_false) -> Any: ...
async def loop_until(ctx, fn, until, max_iter=3) -> list[Any]: ...
```

#### 10.2.4 Event 结构

```python
@dataclass(frozen=True)
class Event:
    type: str                             # 见 §23.5
    task_id: str = ""
    at: datetime = field(default_factory=utc_now)
    data: dict = field(default_factory=dict)
```

### 10.3 Research Workflow 参考实现（伪码）

展示自研编排的可读性——与 `Academic-Agent/workflows/research.py` 的 LangGraph 版本相比，**行数更少、概念更少、可直接 step-debug**。

```python
class ResearchWorkflow(BaseWorkflow):
    name = "research"

    def __init__(self, planner, executor, evaluator, evolver):
        self.planner = planner; self.executor = executor
        self.evaluator = evaluator; self.evolver = evolver

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        # 1. 拉记忆（§11 数据流节点 A）
        mem_summary = await ctx.memory.vector.summary_for(ctx.query, k=5)
        matched_heur = await ctx.memory.heuristic.match(
            ctx.query, domain="research", top_k=3)
        ctx.state["mem_summary"] = mem_summary
        ctx.state["heuristics"] = matched_heur

        # 2. 规划
        tasks = await self.stage(ctx, "planner",
            lambda c: self.planner.plan(c, mem_summary, matched_heur))
        ctx.state["tasks"] = tasks

        # 3. 执行（并行子任务）
        results = await self.stage(ctx, "executor",
            lambda c: parallel(c, [
                (lambda t=t: self.executor.execute(c, t)) for t in tasks
            ], max_concurrency=4))
        ctx.state["results"] = results

        # 4. 评估 + 至多一次重试
        async def eval_then_maybe_retry(c):
            v = await self.evaluator.evaluate(c, results)
            if v.verdict == "fail" and c.state.get("retry_count", 0) == 0:
                c.state["retry_count"] = 1
                await c.emit(Event("task.retry", data={"reason": v.feedback}))
                return await self.run(c)   # 简单递归，无需状态图
            return v
        verdict = await self.stage(ctx, "evaluator", eval_then_maybe_retry)

        # 5. 记忆写回（§11 数据流节点 B）
        await self.stage(ctx, "memory_write",
            lambda c: self._write_memory(c, results))

        # 6. 进化（§11 数据流节点 C）
        await self.stage(ctx, "evolver",
            lambda c: self.evolver.evolve(c, verdict))

        return WorkflowOutput(
            verdict=verdict.verdict, score=verdict.score,
            results=results, trace=ctx.trace,
        )
```

整个 workflow 就是**一个 async 函数**——能打断点、能 `print`、能直接 `pytest`，不需要理解任何第三方 DSL。

### 10.4 Checkpoint / Resume（自研，可选启用）

配置开关 `AAF_CHECKPOINT_ENABLED=true` 时：
- 每个 `stage()` 结束自动把 `ctx.state` JSON 化写入 Postgres `tasks.checkpoint` 字段
- 重启后 `POST /api/v1/tasks/{id}/resume` 从上次 checkpoint 继续
- 实现：`class Checkpoint` 一个类，`save(ctx, label)` / `load(task_id)`，**< 100 行**

不启用时完全不产生任何 IO，零开销。

### 10.5 五种预置 Workflow

| 文件 | 流程 |
|---|---|
| `research.py` | Planner → Executor×N（并行） → Evaluator →（可选 retry）→ Memory Write → Evolver |
| `write.py` | Outline → DraftSection×N（并行） → CiteInsert → Polish → Evaluator → Evolver |
| `revise.py` | ParseDoc → Critique → Rewrite → Diff → Evaluator → Evolver |
| `rebuttal.py` | ParseReviews → MatchToFindings → DraftResponse → Evaluator |
| `survey.py` | 复用 `research` 产出素材 → 复用 `write` 生成综述文本 → 合并 |

所有 workflow 都继承 `BaseWorkflow`，使用同一套 primitives。

### 10.6 可插拔 Workflow

用户可在 `backend/workflows/custom/` 放自己的 workflow 文件；框架启动时扫描所有 `BaseWorkflow` 子类并自动注册到 API `/api/v1/{workflow.name}`。无需改任何框架代码即可添加新流程。

### 10.7 自进化触发链路（M-Evolver）

> **设计目标**：每个成功 workflow 跑完后，自动尝试把"这次为什么 work"沉淀成一条可被未来 run 复用的 heuristic。**全程 gated**——不直接落 HeuristicStore，先进 Proposals 队列，人审通过才生效。

#### 10.7.1 抽象（`backend/agents/evolver.py`）

```python
class EvolverAgent:                                          # stateless
    def __init__(self, *, llm: LLMProvider | None = None): ...
    async def evolve_from_run(
        self,
        *,
        record: TaskRecord,
        output: WorkflowOutput,
        store: ProposalStore,
        actor: str | None = None,
    ) -> Proposal | None: ...
```

* **Stateless** —— 不持任何 per-task 可变状态，runner 只构造一次。
* **Never raises** —— 内部所有失败路径都 `log.exception` + 返回 `None`，runner 永远不会被 evolver 拖垮。
* **不写 HeuristicStore** —— 只产 `Proposal`（status=`draft`）；apply 走 M8.1 的人审 → approve → apply 链路。
* **优雅退化**：`output.verdict != "ok"` → `None`；`output.results["evolve"] is False` → `None`（workflow 可显式拒绝单次 evolve）。
* **LLM 可选**：构造时不传 `llm` → 用确定性 template；传了 `llm` → 走 LLM 草稿（自动 `for_route("reasoning")` 如果 routing 启用），LLM 失败时回落到 template。

#### 10.7.2 接入点（`backend/tasks/runner.py:execute_task`）

成功 workflow 的尾部（在 `_maybe_commit_manuscript` 之后、`store.mark_completed` 之前）调一次 `_maybe_run_evolver(deps, record, output)`：

```
workflow.run(ctx) → out
  ↓
_maybe_commit_manuscript(...)        # 已有：把产物落 manuscript 版本
_maybe_run_evolver(...)              # 新：fire EvolverAgent 产 proposal 草稿
store.mark_completed(...)            # 标记任务终态
```

* `RunnerDeps` 新增 `proposals: ProposalStore | None` + `evolver_enabled: bool` + `evolver: EvolverAgent | None`（测试可注入 mock）。
* `_maybe_run_evolver` 在 `evolver_enabled=False` 或 `proposals=None` 时**直接返回**（zero overhead）。
* 任何异常都 try/except 包住——决不让 evolver bug 把 task 标成 `error`。

#### 10.7.3 配置

| ENV | 默认 | 含义 |
|---|---|---|
| `AAF_EVOLVER_ENABLED` | `false` | opt-in 开关 |

* 默认关闭，避免给用户留下一堆未审 proposal。
* 启用后所有 ok-verdict 的 run 都会产 1 个 `draft` proposal，进 `/api/v1/proposals?status=draft` 等审。

#### 10.7.4 何时不该开

* 跑批量自动化（CI 跑 100 个 workflow run）→ 队列会堆积；要么关掉，要么定期 batch-reject。
* 已有完整 SOP 不需要新 heuristic → 关掉以节省 LLM 调用。
* 所在团队没有 reviewer 角色配 `/api/v1/proposals` → 提案会卡在 `draft` 永不生效。

### 10.8 MCP 客户端集成（M-MCP）

> **设计目标**：让 AAF 像 Cursor / Claude Desktop 一样消费任意 MCP（Model Context Protocol）server，把 server 暴露的 tool 自动注册到 AAF 的 ToolRegistry，workflow / planner 调用时**无感**——和本地 `arxiv__search` 同样路径。

#### 10.8.1 抽象（`backend/tools/mcp_*.py`）

```
backend/tools/
  mcp_config.py     # MCPServerConfig (Pydantic) + load_mcp_config(YAML)
  mcp_client.py     # MCPClient: 一个长生命周期 stdio/sse session
  mcp_tool.py       # MCPTool(BaseTool): 把 mcp.types.Tool 投影到 AAF Tool 协议
  mcp_loader.py     # register_mcp_servers(): 把 N 个 server 接入 ToolRegistry
```

`MCPClient` 的关键设计是**整段生命周期跑在一个 background task** 里——SDK 内部用 `anyio.TaskGroup` 持有 `stdio_client` 的 cancel scope，一旦把 enter/exit 拆到不同 task（典型坑：`AsyncExitStack` 跨 stage 持有），就会触发 *"Attempted to exit cancel scope in a different task than it was entered in"*。

#### 10.8.2 Tool 命名约定

远端 tool 通过 `mcp__<server_name>__<remote_name>` 注册到 `ToolRegistry`：

```
filesystem MCP server, tool=read_file  →  registry.call("mcp__filesystem__read_file", {...})
```

Workflow 既可以让 LLM 在工具列表里看到、也可以代码里直显式调用，和本地 tool 完全一致。

#### 10.8.3 配置（`config/mcp_servers.yaml` + ENV）

| ENV | 默认 | 含义 |
|---|---|---|
| `AAF_MCP_ENABLED` | `false` | opt-in 总开关 |
| `AAF_MCP_CONFIG` | `./config/mcp_servers.yaml` | server 列表 |

YAML schema 见 `config/mcp_servers.example.yaml`：每个 server 指定 `transport`（stdio / sse）、`command` / `url`、可选 `allow` 白名单、capability flags（`requires_network` / `requires_paid_api`）。`${VAR}` 引用从 `os.environ` 替换，secrets 不进 YAML。

#### 10.8.4 故障隔离

* config 文件不存在 / `mcp_enabled=false` → 直接 no-op，不影响启动。
* 单个 server 起不来 → 在 `MCPRegistration` 里记 `connected=false, error=...`，**不**阻断其他 server 也不影响 app 启动。
* `list_tools` 失败 → 该 server 注册 0 个 tool，但 session 保留（下次重启再试）。
* 调 tool 时 transport 错 → `MCPCallError` → `ToolResult(ok=False, meta={"code": "aaf.mcp.call_failed"})`，workflow 走标准错误分支。

#### 10.8.5 笔记本场景

启 N 个 MCP server 会派生 N 个子进程；笔记本默认开关在 `false`，需要时只填要的几个 server——和 Cursor "MCP enabled servers" 同思路。

---

## 11. Memory 子系统

> **一句话回答**：**记忆系统完全保留，并从"Academic-Agent 内部模块"提升为"框架第一公民"**。原有三层记忆架构（Semantic / Episodic / Procedural）+ A-Mem 进化机制（typed_links / synthesis notes / session reflections）全部迁入，扩展为五类 Store。
>
> **M7 起新增**：第六类 Store —— `DocumentStore`（任意文档分块 + RAG 召回，详见 §20.8 M7.3）。`MemoryBundle.read()` 会**同时**召回 `KnowledgeStore` 的 PaperCard 与 `DocumentStore` 的 chunk，按 score 合并。

### 11.1 记忆系统在框架里的位置

Memory 是**运行时核心依赖**之一：每个 workflow、每个 agent 都通过 `WorkflowContext.memory`（类型 `MemoryBundle`）与它交互，**不存在绕过 memory 直接触达底层存储的路径**。

```
      ┌─────────────────────────────────────────────┐
      │           WorkflowContext.memory            │
      │               (MemoryBundle)                │
      └───┬──────┬──────┬──────┬──────┬─────────────┘
          │      │      │      │      │
      ┌───▼──┐┌──▼───┐┌─▼───┐┌─▼───┐┌─▼───┐
      │vector││know- ││heur-││epi- ││sess-│
      │store ││ledge ││istic││sodic││ion  │
      │      ││store ││store││store││store│
      └───┬──┘└──┬───┘└──┬──┘└──┬──┘└──┬──┘
          │     │        │     │      │
     ┌────▼──┐┌─▼─────┐┌─▼───┐│      │
     │Chroma ││YAML   ││YAML ││      │
     │（嵌入）││files  ││files││      │
     └───────┘│(papers)││(L3) ││      │
              └───────┘└─────┘│      │
                     ┌────────▼──┐┌──▼────────┐
                     │ Postgres  ││ Redis +   │
                     │ (reflect) ││ Postgres  │
                     └───────────┘└───────────┘
```

### 11.2 五类 Store 职责表（完整版）

| Store | 对标 Academic-Agent 模块 | 底层 | 读写者 | 保存什么 |
|---|---|---|---|---|
| **VectorStore** | `memory/vector_store.py`、`paper_memory.py` 的 chroma 部分 | ChromaDB（持久目录 `data/chroma/`） | 读：Planner / Executor（查相似论文）；写：任何新论文被吸收时 | 论文标题 + 摘要 + reading notes 的 embedding；`paper_id → vector` |
| **KnowledgeStore** | `memory/knowledge_store.py`、`paper_memory.py` 的 YAML 部分 | YAML 文件系统（`data/knowledge/`） | 读：所有 workflow；写：Executor（论文笔记）、Evaluator 签名后 | 结构化论文卡片（含 summary、method、typed_links、synthesis notes）、失败案例、每次 run 的 findings |
| **HeuristicStore** | `memory/skill_store.py` + `data/skills/*.yaml` | YAML 文件系统（`data/skills/<domain>/`） | 读：Planner（匹配策略注入）；写：Evolver | L3 经验（§8），即"做过哪些成功的调研/写作，下次怎么做" |
| **EpisodicStore** | `memory/episodic_store.py` | Postgres 表 `episodic`（可选 pgvector） | 读：Planner（近期反思）；写：Evolver（会话反思） | 每次 run 的 session reflection（"这次发现了什么？犯了什么错？"） |
| **SessionStore** | （新增，旧项目无） | Redis hot + Postgres cold | 读写：API 层与所有 workflow | 多轮对话上下文、当前项目状态、临时变量 |

> **关键**：前四类与现在 `Academic-Agent/memory/` 一一对应——**等于把旧 memory 原地重命名 + 加一个 `SessionStore`**。没有任何功能被砍。

### 11.3 代码迁移映射（精确到文件）

| 旧路径 | 新路径 | 改动 |
|---|---|---|
| `Academic-Agent/memory/__init__.py` | `backend/memory/__init__.py` | 新增 `MemoryBundle` 聚合类 |
| `Academic-Agent/memory/vector_store.py` | `backend/memory/vector_store.py` | `Path` 基准改为 `settings.data_dir / "chroma"`；embedder 改走 `LLMProvider.embed` |
| `Academic-Agent/memory/knowledge_store.py` | `backend/memory/knowledge_store.py` | 增加 `session_id`、`user_id` 字段；函数签名加 `base_path` 参数（由 settings 注入） |
| `Academic-Agent/memory/paper_memory.py` | `backend/memory/paper_memory.py` | A-Mem 进化逻辑**完整保留**；LLM 调用改走 `LLMProvider`；移除对 OpenAI / Anthropic SDK 的直接 import |
| `Academic-Agent/memory/skill_store.py` | `backend/memory/heuristic_store.py` | **重命名**以消除歧义（避免和 L1 skill 混淆）；类名 `SkillStore → HeuristicStore`；YAML 存储结构加 `domain/` 子目录分区 |
| `Academic-Agent/memory/episodic_store.py` | `backend/memory/episodic_store.py` | 存储从文件改 Postgres（可选保留文件 fallback） |
| —（新） | `backend/memory/session_store.py` | Redis 存 hot 上下文，Postgres `sessions/messages` 表存冷数据 |

> 完整重命名表的意图：**通过"Heuristic"这个词避免把运行时 L3 的 YAML 策略和 L1 的能力 skill 搞混**——L1 skill 在 `skills/`（目录 + SKILL.md），L3 heuristic 在 `data/skills/<domain>/`（YAML 文件）。

### 11.4 MemoryBundle 统一访问接口

```python
@dataclass
class MemoryBundle:
    vector: VectorStore
    knowledge: KnowledgeStore
    heuristic: HeuristicStore
    episodic: EpisodicStore
    session: SessionStore

    # 统一快照（用于 Planner 的 one-shot 拉取）
    async def snapshot(self, query: str, *, domain: str, k: int = 5) -> MemorySnapshot:
        return MemorySnapshot(
            vector_summary = await self.vector.summary_for(query, k=k),
            related_papers = await self.knowledge.find_related(query, k=k),
            heuristics     = await self.heuristic.match(query, domain=domain, top_k=3),
            recent_reflect = await self.episodic.recent(n=3, filter={"type":"reflection"}),
        )
```

**规则**：所有 agent / workflow **只依赖 `MemoryBundle`，不允许直接 import 某个具体 store**。单元测试可传入 in-memory fake 实现。

### 11.5 生命周期（运行时何时实例化）

| 对象 | 生命周期 | 说明 |
|---|---|---|
| `VectorStore` / `KnowledgeStore` / `HeuristicStore` / `EpisodicStore` | **进程级单例** | FastAPI lifespan 启动时创建，关闭时 close；线程安全（ChromaDB 自己处理并发） |
| `SessionStore` | **进程级单例** | 其实 client 是单例，但操作时带 `session_id` |
| `MemoryBundle` | **请求级** | 每次 workflow run 创建一个，聚合上面的单例引用；这样可以按用户/会话切换底层实例（未来多租户） |
| A-Mem 进化线程 | **后台 worker** | ARQ 周期任务：扫描新增论文 → 调用 `paper_memory.evolve()` → 写 typed_links |

### 11.6 端到端数据流（一次 research 任务全程）

以 "帮我调研多任务 RLHF 的最新进展" 为例：

```
时刻  动作                                 memory 读/写
----  -----------------------------------  ------------------------------
T0    用户 POST /api/v1/research           session.create(session_id)
T1    Worker pick up 任务                  memory = MemoryBundle(...)
T2    Workflow.run 入口                    snap = memory.snapshot(query, "research")
         ├ 读 vector 相似论文              vector.summary_for(q, k=5)
         ├ 读 knowledge 近邻卡片           knowledge.find_related(q, k=5)
         ├ 读 heuristic L3 策略            heuristic.match(q, "research", 3)
         └ 读 episodic 近期反思            episodic.recent(3, type="reflection")
T3    Planner 用 snapshot 生成 tasks       （纯计算，不碰 memory）
T4    Executor 并行跑每个 task
         ├ arxiv/semantic_scholar 检索     （外部 API，不碰 memory）
         ├ 下载 PDF + 三遍阅读             （写临时文件到 data/papers/）
         └ 产出 reading_notes              （仍在内存中，未入库）
T5    Evaluator 打分 verdict=pass          （只读 reading_notes）
T6    stage "memory_write"
         ├ 对每篇新论文                    knowledge.write_card(paper, notes)
         ├ 同时写 embedding                vector.add(paper_id, embed(...))
         └ 触发 A-Mem 进化                 paper_memory.evolve(new_card)
                                              ├ vector.query(card, k=5) 找近邻
                                              ├ LLM 判断 typed_links
                                              └ knowledge.link(a, b, type)
T7    stage "evolver"
         ├ 提取可复用策略                  heuristic.add(new_skill, domain=research)
         ├ bump 命中过的 L3 策略           heuristic.bump_success(id)
         └ 写本次反思                      episodic.append(type="reflection", ...)
T8    任务结束                             session.update(session_id, last_task=t_xxx)
```

**每一次写入都附带 `source_run_id`**，支持第 8 点所列的回滚能力。

### 11.7 A-Mem 进化机制（完整保留）

`Academic-Agent/memory/paper_memory.py` 里实现的 A-Mem 能力全部迁入 `backend/memory/paper_memory.py`，具体包括：

| 能力 | 触发点 | 记忆操作 |
|---|---|---|
| **typed_links 自动标注** | 每次新论文写入 `knowledge_store` 后 | vector 找最近 5 篇 → LLM 判断关联类型（extends/contradicts/applies/motivated_by/baseline-of）→ 双向写入 YAML |
| **Synthesis Note 生成** | 某 cluster（typed_links 连通分量）达到阈值（默认 5 篇） | 触发 LLM 生成聚合分析 → 写 `knowledge_store.cluster_notes` |
| **Session Reflection** | 每个 workflow 结束 | Evolver 调 LLM 生成反思 → 写 `episodic_store` |
| **主动补链** | 检索时发现"明显应该关联但未关联"的论文对 | 写入 `data/paper_evolution_queue.jsonl`，后台 worker 定期处理 |
| **检索质量量化** | 日常评估 | 从 `data/eval_sets/` 跑 recall@k，结果存 `data/eval_reports/` |

这些能力的代码 **90%+ 原样保留**，仅把 LLM 调用改走 `LLMProvider`。

### 11.8 可观察性与用户控制

Memory 不是黑箱——所有读写都**对用户可见、可编辑、可回滚**：

- **前端 Memory Explorer（§14.2.5）**：Knowledge / Heuristic / Episodic / Session 四个 Tab，全文搜索、详情、编辑、删除、导出
- **typed_links 可视化**：Knowledge Tab 右侧 ECharts graph，展示论文关联图
- **回滚 API**：`POST /api/v1/memory/rollback?run_id=t_xxx`，撤销某次 run 产生的所有 memory 写入
- **冻结 API**：`POST /api/v1/memory/heuristics/{id}/freeze`，让 Matcher 不再匹配该策略
- **导出**：`GET /api/v1/memory/export`，打包 YAML + JSON，用户可带走自己的数据

### 11.9 一致性与事务边界

- **Knowledge + Vector 双写一致性**：采用"先写 knowledge YAML，再更新 vector"的顺序；若 vector 写失败，有 `scripts/rebuild_chroma.py` 从 YAML 完全重建（幂等）
- **Heuristic 写入**：文件系统原子写（先写 `.tmp` 再 rename），`_index.yaml` 最后更新
- **Session / Episodic**：Postgres 事务保证
- **无分布式事务**：框架假设单机部署，不处理跨节点一致性

### 11.10 验收点

- [ ] 旧仓库的 `data/knowledge/` 直接拷贝进新仓库即可读
- [ ] 旧仓库的 `data/skills/*.yaml` 移到 `data/skills/research/` 后即可被 HeuristicStore 识别
- [ ] `scripts/rebuild_chroma.py` 能在空 Chroma 上从 knowledge YAML 重建向量库
- [ ] 在前端 Memory Explorer 删除一条论文卡片，vector / typed_links 同步失效
- [ ] Evolver dry-run 模式下，heuristic YAML 有候选产出但未落盘

---

## 12. Tool Registry

### 12.1 与 Skill 的关系

- **Skill 内部 scripts** = skill 私有工具，命名 `{skill}__{script}`
- **Tool Registry 工具** = 所有 skill 共享的通用工具，命名 `{namespace}__{action}`，如 `arxiv__search`, `pdf__parse`, `web__search`

### 12.2 接口

```python
class Tool(Protocol):
    name: str
    description: str
    parameters: dict               # JSON Schema
    requires_network: bool
    requires_paid_api: bool
    async def __call__(self, **kwargs) -> ToolResult: ...

class ToolRegistry:
    def register(self, tool: Tool): ...
    def get(self, name: str) -> Tool: ...
    def list_for_injection(self, allow_network: bool = True) -> list[ToolSpec]: ...
```

### 12.3 内置工具（迁移自 Academic-Agent）

- `arxiv__search`
- `semantic_scholar__search`
- `semantic_scholar__paper`
- `pdf__download`
- `pdf__parse`
- `web__search`（Tavily / SearXNG）
- `bibtex__format`
- `latex__compile`（调用 tectonic / tinytex；可选）

---

## 13. Backend API 设计

> **M7 起新增三组 router**：`/api/knowledge/papers/ingest`（M7.1，合并 PDF→PaperCard→evolver）、`/api/skills/*`（M7.2，在线管理 skill）、`/api/documents/*`（M7.3，任意文档 RAG）。完整契约见 §20.8。

### 13.1 原则

- 统一前缀 `/api/v1/`
- 所有长任务**立即返回 task_id**，状态通过 SSE 或轮询
- 错误遵循 RFC 7807 Problem Details
- 请求/响应全部 Pydantic，自动生成 OpenAPI

### 13.2 端点清单

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/v1/research` | 启动 research workflow |
| POST | `/api/v1/write` | 启动 write workflow |
| POST | `/api/v1/revise` | 启动 revise workflow |
| POST | `/api/v1/rebuttal` | 启动 rebuttal workflow |
| POST | `/api/v1/survey` | 启动 survey workflow |
| GET | `/api/v1/tasks` | 任务列表 |
| GET | `/api/v1/tasks/{id}` | 任务详情 |
| GET | `/api/v1/tasks/{id}/stream` | SSE 事件流 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消 |
| GET | `/api/v1/skills` | L1 列表 |
| GET | `/api/v1/skills/{name}` | L1 详情 |
| POST | `/api/v1/skills/reload` | 热重载 |
| GET | `/api/v1/rules` | L2 列表 |
| GET | `/api/v1/memory/knowledge/search?q=` | 论文卡片检索 |
| GET | `/api/v1/memory/knowledge/{id}` | 论文卡片详情 |
| PUT | `/api/v1/memory/knowledge/{id}` | 编辑 |
| DELETE | `/api/v1/memory/knowledge/{id}` | 删除 |
| GET | `/api/v1/memory/heuristics?domain=` | L3 列表 |
| POST | `/api/v1/memory/heuristics/{id}/freeze` | 冻结 |
| DELETE | `/api/v1/memory/heuristics/{id}` | 删除 |
| GET | `/api/v1/memory/sessions` | 会话列表 |
| GET | `/api/v1/memory/sessions/{id}` | 会话详情 |
| GET | `/api/v1/models/providers` | LLM provider 列表 |
| PUT | `/api/v1/models/providers/{name}` | 编辑 provider |
| GET | `/api/v1/models/usage` | 用量统计 |
| POST | `/api/v1/auth/login` | JWT 签发 |
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/health/ready` | 就绪检查 |

完整 request/response schema 见 `docs/api-reference.md`（M4 产出）。

### 13.3 SSE 事件协议

```
event: task.stage_start
data: {"task_id":"t_xxx","stage":"planner","at":"..."}

event: task.llm_token
data: {"task_id":"t_xxx","delta":"some text"}

event: task.tool_call
data: {"task_id":"t_xxx","tool":"arxiv__search","args":{...}}

event: task.tool_result
data: {"task_id":"t_xxx","ok":true,"duration_ms":1230}

event: task.stage_end
data: {"task_id":"t_xxx","stage":"planner","output_summary":"..."}

event: task.finished
data: {"task_id":"t_xxx","verdict":"pass","score":78}

event: task.error
data: {"task_id":"t_xxx","code":"LLM_TIMEOUT","message":"..."}
```

---

## 14. Frontend 设计

> **M7 起新增页面**：`Memory → Knowledge` 抽屉里的 "Ingest paper"（M7.1）、新增一级页面 `/skills`（M7.2，列表 + 详情 + Install/Edit/Dry-run）、新增一级页面 `/library`（M7.3，文档 RAG 库）。导航顺序：Dashboard → Research → Manuscripts → Library → Memory → Skills → Tasks → Settings。

### 14.1 技术栈（详见 §22）

React 19 + TypeScript 5 + Vite 5 + React Router 7 + **Zustand**（UI 状态）+ **TanStack Query v5**（服务端状态与 SSE 缓存）+ **shadcn/ui** + **Tailwind CSS v4** + Monaco Editor (`@monaco-editor/react`) + Tiptap (`@tiptap/react`) + markdown-it + KaTeX + ECharts (`echarts-for-react`) + `@microsoft/fetch-event-source` + `react-i18next`

**为什么选这套**：Agent / 流式对话场景的生态基本都是 React-first（Vercel AI SDK、assistant-ui、CopilotKit、shadcn/ui）。Zustand + TanStack Query 的组合比 Redux 轻、比纯 hooks 稳；shadcn/ui 把组件源码直接拷到项目里，长期维护可控性远高于三方组件库。Tailwind v4 在样式层提供一致的设计 token，和 shadcn 深度绑定。

### 14.2 页面与组件

#### 14.2.1 Dashboard (`/`)
- 最近任务卡片（状态、耗时、模型、评分）
- 用量曲线（按 provider / 按日）
- 快捷入口：新建调研 / 新建写作 / 打开最近项目

#### 14.2.2 Research Console (`/research`)
- 左：输入区（query、模型选择、skill 过滤、使用历史记忆开关）
- 中：**实时轨迹面板**（Planner 的任务树 → Executor 每个任务的进度条 → Evaluator 评分 → Evolver 产物）
  - 组件：`<StageTimeline />`、`<LLMTokenStream />`、`<ToolCallCard />`
- 右：论文卡片列表（过滤、排序、"写入记忆"按钮）

#### 14.2.3 Paper Writer (`/writer/:projectId`)
- 左：大纲树（可拖拽，基于 `dnd-kit`）
- 中：Markdown/LaTeX 编辑器（Monaco），下方预览（markdown-it + KaTeX）
- 右：AI 侧栏（改写/补全/插引用/逻辑检查），每个操作调用对应 workflow

#### 14.2.4 Revision Studio (`/revision/:docId`)
- 上：审稿意见解析（从粘贴的评审文本自动结构化）
- 下左：原稿 diff 前；下右：改稿 diff 后（`react-diff-viewer-continued`）
- 底部：生成 rebuttal letter

#### 14.2.5 Memory Explorer (`/memory`)
- Tab：Knowledge / Heuristic / Episodic / Session
- Knowledge Tab：表格 + 详情 Sheet（shadcn），支持 typed_links 可视化（ECharts graph）
- Heuristic Tab：按 domain 分组，支持冻结/删除/回滚
- 全文搜索

#### 14.2.6 Settings (`/settings`)
- LLM Providers：每个一张卡（endpoint、key、默认模型、温度、启用开关）
- Prompt 模板：展示 `prompts/` 下所有模板，支持在线编辑（持久化到 `prompts/overrides/`）
- Skill / Rule 开关：允许运行时禁用某个 skill 或 rule
- 系统：数据导出、备份、重置

### 14.3 状态管理（Zustand + TanStack Query）

**Zustand（UI 本地状态）**：
- `useSessionStore`：当前会话、历史消息
- `useAuthStore`：token、user
- `useUIStore`：主题、侧栏折叠、弹窗栈

**TanStack Query（服务端状态与缓存）**：
- `queries/tasks.ts`：`useTasksList()`、`useTask(id)`
- `queries/memory.ts`：`useMemorySnapshot({query, domain, k})`、`useKnowledgeList()`、`useHeuristics(domain)`
- `queries/models.ts`：`useProvidersList()`、`useProviderMutation()`
- `queries/skills.ts`：`useSkillsList()`

SSE 事件流单独走 `useTaskMonitor(taskId)`（见 §14.4），与 React Query 共享缓存 key（任务事件推流完成后 invalidate 对应 query）。

### 14.4 关键 Hooks

- `useSSE(url, body?)` → `{ events, running, error, start, stop }`  
  基于 `@microsoft/fetch-event-source`（比原生 `EventSource` 支持 POST、headers 和自动重连）
- `useLLMStream(provider, messages)` → 流式 token（基于 `useSSE`）
- `useTaskMonitor(taskId)` → 封装 `useSSE` + 状态机 + React Query 失效
- `useBudget()` → 读 `/api/budget`，过阈值闪烁预警
- `useToast()` → shadcn `sonner` 封装

### 14.5 UI 基线

- 深浅色主题（Tailwind `dark:` + shadcn CSS 变量）
- 所有组件都用 TypeScript 强类型，`props` 必写 interface
- 样式一律 Tailwind utility classes + shadcn primitives，**禁用 CSS-in-JS**（避免运行时样式生成影响 SSR / 水合）
- 布局：shadcn `<Sidebar>` + `<Sheet>` + `<Dialog>` + `<Card>` + `<Tabs>`
- 所有长列表走 `@tanstack/react-virtual` 虚拟滚动
- 表单走 `react-hook-form` + `zod` 校验，错误直接映射后端 `aaf.*` 错误码

---

## 15. SDK / CLI

### 15.1 Python SDK（`sdk/python/aaf/`）

```python
from aaf import Framework

fw = Framework(base_url="http://localhost:8000", api_key="...")
# 或 fw = Framework.embedded(workdir="~/aaf-data")  # 进程内直接跑

result = await fw.research("Survey on process reward models")
doc = await fw.write(mode="intro", query="RLHF overview")
```

`Framework.embedded` 模式**不启后端服务**，直接 import backend 代码，用于 CI 或 notebook。

### 15.2 CLI（`cli/aaf.py`）

```bash
aaf research "your query" --llm openai:gpt-4o-mini --no-read
aaf write --mode intro "your topic"
aaf memory ls --domain writing
aaf skill list
aaf skill test paper-writing   # 跑 skills/paper-writing/evals/
aaf server up
```

CLI 底层调用 Python SDK embedded 模式 或 HTTP API（通过 `--remote` 切换）。

### 15.3 TypeScript SDK（`sdk/ts/`，M6 起步）

只实现 HTTP 模式，给前端和 Node 脚本使用。

---

## 16. 部署方案

### 16.1 Docker Compose 构成

```yaml
# docker-compose.yml 关键服务
services:
  nginx:         # 443/80 反代
  frontend:      # vite build 后的静态文件 + nginx
  backend:       # FastAPI + uvicorn
  worker:        # ARQ worker
  postgres:      # 元数据
  redis:         # 队列 + pubsub + 缓存
  chroma:        # 向量库
  minio:         # 对象存储（PDF、产物）
```

### 16.2 Volume 布局（主机路径 → 容器）

- `./data/chroma`   → 容器 `/data/chroma`
- `./data/knowledge` → 容器 `/data/knowledge`
- `./data/skills`   → 容器 `/data/skills`
- `./data/papers`   → 容器 `/data/papers`
- `./skills`        → 容器 `/app/skills`（只读）
- `./rules`         → 容器 `/app/rules`（只读）
- `./prompts`       → 容器 `/app/prompts`
- `minio_data`      → 容器内
- `postgres_data`   → 容器内

### 16.3 一键启动

```bash
git clone ... academic-agent-framework
cd academic-agent-framework
cp .env.example .env    # 填入 LLM API key
docker compose up -d
# 访问 http://localhost:8080
```

### 16.4 资源建议

- 最小：4 核 8GB，纯远程 LLM
- 推荐：8 核 32GB + GPU 24GB（跑本地 7B~14B 模型）
- 笔记本 / 单人模式：见 §16.6

### 16.5 备份与恢复

`deploy/backup.sh`：
- `pg_dump` postgres
- `mc mirror` minio → 远端 S3（可选）
- `tar` data/ 目录

恢复：反向操作，附带 `scripts/rebuild_chroma.py` 从 knowledge YAML 重建向量库。

### 16.6 笔记本 / 单人模式（Laptop preset）

为"单人 + 一台笔记本"场景准备的 zero-ops 部署配方，**与生产 stack 完全并存**：

| 项 | 生产 stack | Laptop preset |
|----|------------|---------------|
| 配置文件 | `.env` + `docker-compose.yml` | `.env.laptop` + `docker-compose.lite.yml`（或 `make dev-laptop` 走宿主 Python） |
| 任务 / 文稿 / episodic store | Postgres | SQLite（`./data/aaf.db`） |
| Vector / Session store | Chroma 持久化 / Redis | 全部内存版 |
| Task Queue | ARQ + Redis worker | `InMemoryTaskQueue` |
| Auth | JWT | `AUTH_DISABLED=true`（单用户） |
| LLM | 真实 provider | 缺 key 时落到 `mock`，UI 仍可用 |
| 自动压缩 | 默认关 | 默认开（节省 token） |
| MCP / Evolver | 默认关 | 默认关，按需开 |
| 资源 | 多容器 | 单 backend 进程，~250 MB RAM，冷启 ~3s |

落地文件：

- `.env.laptop.example`：所有 laptop-friendly 默认值，含注释说明
- `Makefile` 新增 `dev-laptop` / `up-lite` / `down-lite`
- `docker-compose.lite.yml`：仅 backend + frontend
- `docs/laptop-mode.md`：完整使用说明 + 与生产 stack 的差异表

向上迁移路径：SQLite → Postgres、内存 vector → Chroma、内存 queue → ARQ，皆为切换 `AAF_*_BACKEND` 即可，数据格式向前兼容。

### 16.7 运行时 LLM Provider 覆盖（P6 Phase A）

笔记本场景下，用户期望「装好就能用」。光靠 env 变量配 LLM 还不够 —— 我们额外引入了一份运行时覆盖层：

- 持久化文件：`data/runtime/provider.yaml`（明文 YAML，目录 `0700`、文件 `0600`，已 gitignore）。
- 后端 API：`/api/settings/llm`（GET / PUT / DELETE / `:test` / `/providers`），见 `backend/api/routers/settings.py`。
- 启动时：`backend/app.py:lifespan` 优先读这个 YAML，覆盖 env 默认 Provider。
- 热重载：`PUT` 同时换 `state.llm` 和 `state.runner_deps.llm`，新入队的任务立刻用新 Provider；正在跑的任务保持启动时绑定，避免破坏 §6.1 的对话隔离不变量。
- 单元 + 集成测试：`backend/tests/unit/test_runtime_config.py`、`backend/tests/integration/test_app_settings.py`（共 33 个新增用例）。

设计细节与契约见 [`docs/runtime-internals.md` §10.1](docs/runtime-internals.md#101-runtime-llm-provider-override-frontend-settings-panel) 或中文版 [`docs/runtime-internals.zh.md` §10.1](docs/runtime-internals.zh.md#101-运行时-llm-provider-覆盖前端-settings-面板)。

### 16.8 前端中英双语 + 首启 Onboarding（P6 Phase B / Phase C）

- **i18n**：`react-i18next`，`frontend/src/i18n/index.ts`，bundle 内嵌 `en.json` + `zh.json`，单 namespace 嵌套 key。语言选择持久化到 `aaf.ui` localStorage（`useUiStore.language`）。顶栏 EN / 中切换器即时生效。
- **覆盖范围**：Sidebar、TopBar、Login、Register、Dashboard、Research Console、Tasks、Settings、NotFound 全量翻译；其余 8 个二级页面已翻译 PageHeader 标题与描述，二级 UI 字符串将随用户使用反馈逐步补齐。
- **首启向导**：`frontend/src/components/settings/OnboardingDialog.tsx`，挂在 `AppLayout`。检测条件 = `source === "env" && !api_key_set && provider === "mock" && !localStorage.aaf.onboarding.dismissed`。复用 `LLMProviderForm` 实现"输入 → 测试 → 保存即热重载"。
- **设置面板**：`frontend/src/pages/SettingsPage.tsx` 顶部 LLM Provider 卡，下面才是只读的运行时 / 前端 / 工具 / 工作流概览。

---

## 17. 安全、沙箱、性能

### 17.1 Skill 脚本沙箱
- 默认子进程 + rlimit（见 §6.5）
- 生产：Docker `aaf-skill-runtime` 镜像，无 network namespace（除非 skill frontmatter 声明 `network: required`）

### 17.2 Prompt 注入防护
- 所有外部文本（论文摘要、用户粘贴的审稿意见）在注入前通过 `sanitize()` 去除疑似"越权指令"标记（按关键词 + LLM judge 可选）
- Rule Engine 强制要求 agent 在每轮 tool 调用前 re-read system prompt

### 17.3 超时 / 重试 / 降级
- LLM 单次调用默认 60s；重试 2 次（指数退避 2s → 8s）
- Tool 调用默认 120s，失败不自动重试（由 agent 决策）
- 达到预算上限（token 或 cost）自动 graceful-stop，返回当前中间产物

### 17.4 速率限制
- 全局 LLM QPS 由 Redis token bucket 控制
- 每用户每小时最大任务数可配置

### 17.5 鉴权
- M4 起启用 JWT；单机模式可配置 `AUTH_DISABLED=true` 跳过

### 17.6 审计日志
- 所有 write 动作写 `audit_log` 表（Postgres）
- 所有 LLM 调用写 `llm_log` 表，含完整 prompt 和 response（可按配置脱敏）

---

## 18. 从 Academic-Agent 迁移

### 18.1 三步迁移法

**Step 1：资产迁移（M0 第一天）**

```bash
cd ~/Code
# 1. 创建新仓库骨架（通过工程 skill 生成）
# 2. 拷贝 L1 skills
cp -r Academic-Agent/.cursor/skills/*  academic-agent-framework/skills/
# 3. 拷贝 L2 rules（改后缀）
for f in Academic-Agent/.cursor/rules/*.mdc; do
  name=$(basename "$f" .mdc)
  cp "$f" "academic-agent-framework/rules/$name.md"
done
# 4. 拷贝 L3 heuristics（加 domain 分区）
mkdir -p academic-agent-framework/data/skills/research
cp Academic-Agent/data/skills/skill_*.yaml academic-agent-framework/data/skills/research/
# 5. 拷贝知识库与向量库
cp -r Academic-Agent/data/knowledge  academic-agent-framework/data/
cp -r Academic-Agent/data/chroma     academic-agent-framework/data/
```

**Step 2：frontmatter 轻改造**（M0 第二天）

给每个 L1 skill 的 `SKILL.md` 添加（若缺失）：
```yaml
domain: <research|writing|revision|rebuttal|survey|meta>
triggers: [...]
version: "1.0.0"
```

Cursor 对未知字段宽容，不影响现有 Cursor 使用。

**Step 3：代码迁移**（M1-M2）

`Academic-Agent/` 的 Python 代码按以下映射迁入：

| 原路径 | 新路径 |
|---|---|
| `agents/*.py` | `backend/agents/*.py` |
| `workflows/research.py` | `backend/workflows/research.py` |
| `memory/*.py` | `backend/memory/*.py`（改 base path） |
| `tools/*.py` | `backend/tools/*.py` |
| `config/default.yaml` | `backend/settings.py` 读取 + `.env` |
| `cli.py` | `cli/aaf.py`（重写为 SDK 薄封装） |

**不动旧仓库**：`Academic-Agent/` 保留为历史参考，新仓库独立演进。

### 18.2 兼容性承诺

- 旧仓库的 SKILL.md 无须修改也能在新框架跑（frontmatter 额外字段可选）
- 旧 `data/skills/*.yaml` 放入 `data/skills/research/` 即可被新 HeuristicStore 识别
- 旧知识库 YAML 格式完全保留

---

## 19. 工程 Skill（aaf-*）

这些 skill 放在 `.cursor/skills/aaf-*/`，**只给写代码的 AI Agent（Cursor 等）用**，与框架运行时无关。统一 `aaf-` 前缀。

| Skill | 内容要点 |
|---|---|
| **aaf-project-conventions** | 目录命名规则、Python/TS 代码风格、依赖管理（uv / pnpm）、logging 约定、错误处理模式、commit message 约定 |
| **aaf-skill-host** | Loader/Matcher/Injector/Executor 四大模块接口契约；新增匹配策略的方式；如何写 skill host 的单元测试 |
| **aaf-llm-provider** | `LLMProvider` protocol 模板；tool-call schema 映射；streaming chunk 规范；如何写 Mock provider |
| **aaf-backend-api** | FastAPI 路由规范；Pydantic model 约定；SSE 事件命名；错误码表（§23.6） |
| **aaf-agent-workflow** | 新增 workflow 的步骤；State schema；如何发事件；与 Evolver 的集成点 |
| **aaf-memory-contract** | 五类 store 的读写契约、事务边界、迁移脚本规则 |
| **aaf-frontend-react** | React 19 组件模式（Server Components 取舍、Suspense、`use()`）、Zustand store 切分、TanStack Query 缓存键规范、`useSSE` hook 模板、i18n |
| **aaf-tailwind-shadcn** | Tailwind v4 设计 token、shadcn/ui 组件定制规范、暗黑主题切换、响应式断点 |
| **aaf-deploy** | Dockerfile 多阶段构建、secrets 注入、健康检查、备份恢复步骤 |

生成方式：M0 第三天统一用 `create-skill` 工具批量创建。每个 `SKILL.md` 控制在 150-300 行。

### 19.1 工程 Rule（aaf-*）

放 `.cursor/rules/aaf-*.mdc`：
- `aaf-python-style.mdc`：type hint 强制、line length、docstring、禁用 print 等
- `aaf-react-style.mdc`：组件命名 PascalCase、props 接口显式声明、Hooks 依赖数组规范、Zustand store 分片、TanStack Query key 命名
- `aaf-api-contract.mdc`：所有路由必须有 OpenAPI tag；SSE 事件必须有 schema

---

## 20. Milestone 实施路线

每个 Milestone 的**完成定义（DoD）**明确、可验证。截至 2026-05，M0–M6 全部交付完毕，M7（"自管理"能力闭环）进行中 —— 把"用户上传的论文 / 知识 / skill"沉淀为可复用记忆与可在线扩展的能力，详见 §20.8。

| 里程碑 | 交付物 | 状态 |
|---|---|---|
| M0 | 项目骨架 + skill/rule 抽象 + harness engineering | ✅ 已交付 |
| M1 | 五大 memory store + bundle + snapshot/evolver | ✅ 已交付 |
| M2 | 工作流核心 / Skill Host / 规则引擎 / Research workflow | ✅ 已交付 |
| M3 | 工作流自动注册 + Write/Revision + 长任务 + ARQ | ✅ 已交付 |
| M4 | Manuscript 子系统（含 Manuscripts / Paper Writer / Revision Studio 前端） | ✅ 已交付 |
| M5 | 鉴权（stdlib JWT + PBKDF2 + UserStore）+ Memory Explorer 前端 | ✅ 已交付 |
| M6 | Docker 化部署、SDK、文档 | ✅ 已交付（部署冒烟需在目标机执行） |
| M7 | Paper Ingest 管线 + Skill 管理 API/UI + Knowledge Document RAG | ✅（M7.1 ✅ / M7.2 ✅ / M7.3 ✅；详见 §20.8） |
| M8 | Gated Proposals + Planner DAG（compile / validate / execute） | ✅ 已交付（M8.1 + M8.2；详见 §20.9） |

### M0 · 项目骨架与 Harness Engineering ✅ 已交付

**实际交付**：
- 仓库 `academic-agent-framework/` 按 §5 结构落地，`skills/` + `rules/` + `data/` 迁移完成。
- `pyproject.toml`（hatchling 构建、ruff/mypy 配置、`extend-exclude = ["skills"]`）+ `Makefile` + `.env.example`。
- **Harness Engineering 完整接入**：根目录 `AGENTS.md` + 子目录 `AGENTS.md`（`backend/`、`backend/api/`、`backend/workflows/`、`backend/core/skill_host/`、`backend/memory/`、`frontend/`、`skills/`、`rules/`），`scripts/check_consistency.py`（机械化不变量检查），`.githooks/pre-commit`，`.github/workflows/consistency.yml` CI。
- 8+ `aaf-*` 工程 skill 与 `aaf-*` rule 全部带 `domain` / `triggers` frontmatter。

**实际 DoD**：`make check` 一键串起 `ruff` + `mypy` + `consistency` + `pytest` + `fe-typecheck`。

### M1 · Memory Bundle + Skill Host + LLM Provider + Rule Engine ✅ 已交付

**实际交付**：
- `backend/core/llm/{base,openai_compat,anthropic,mock}.py` + `LLMRegistry`。
- `backend/core/skill_host/{loader,matcher,injector,executor,registry}.py` 自研 Skill Host。
- `backend/core/rule_engine.py`（prompt + hook 两种 enforcement）。
- 五大 memory store：`VectorStore` / `KnowledgeStore` / `HeuristicStore` / `EpisodicStore` / `SessionStore`，统一通过 `MemoryBundle` 暴露；`MemorySnapshot` + `PaperMemoryEvolver`。
- 单元测试覆盖率 > 80%；`backend/tests/` 含 unit + integration 双层。

### M2 · FastAPI + 异步 Worker + Research Workflow ✅ 已交付

**实际交付**：
- FastAPI app（`backend/app.py`）+ `lifespan` 注入 `AppState`，所有 router 通过 `_require_*` 守卫子系统。
- 自研工作流编排（`backend/workflows/`），不依赖 LangGraph；`WorkflowRegistry` + 自动发现。
- Research workflow 完全迁入并可跑；SSE `/api/tasks/:id/stream` 通过 `Event` dataclass + `aaf:auth:expired` 头部携带 token。
- `Budget` + `TelemetryRecorder` + `AAFError` 错误层级齐全。

### M3 · React 前端 MVP + 长任务 + ARQ ✅ 已交付

**实际交付**：
- Vite + React 19 + Tailwind v4 + shadcn-style UI 拷贝到项目内。
- `useTaskStream` hook（基于 `@microsoft/fetch-event-source`，自动注入 Authorization 头）；TanStack Query v5 + Zustand。
- Dashboard / Research Console / Tasks / Settings 页面齐全。
- 长任务持久化：`TaskStore`（InMemory + SQL）+ `TaskQueue`（InMemory + ARQ），`backend/tasks/runner.py` 统一 `_maybe_commit_manuscript` 钩子。

### M4 · Manuscript 子系统 + Paper Writer / Revision Studio ✅ 已交付

**实际交付**：
- 后端：`backend/manuscripts/`（`models.py`、`store.py` InMemory + SQL、`exporter.py`）；`/api/manuscripts` router 含 list / create / upload(PDF/MD) / commit version / version history / export。
- 前端：`ManuscriptsPage`（含 "Revise" 快捷入口）/ `PaperWriterPage`（Monaco 编辑器 + 自动保存 + 版本历史 + diff）/ `RevisionPage`（粘贴审稿意见 → 触发 revision workflow → SSE 实时进度 → 自动 v+1 commit）。
- 集成测试 `backend/tests/integration/test_app_revision_e2e.py`：HTTP → runner → 自动 commit 新版本闭环。

### M5 · Memory Explorer + 鉴权 ✅ 已交付

**实际交付（含与 PLAN 的偏差）**：
- **认证（stdlib-only，刻意零额外加密依赖）**：`backend/core/auth/{models,password,tokens,users,dependencies}.py`，PBKDF2-HMAC-SHA256 + HS256 JWT 全部用 Python stdlib 实现。注：偏离 PLAN §22 的 `python-jose`/`passlib` 选型，为的是保持自包含。
- `UserStore` 抽象 + `InMemoryUserStore` + `YamlUserStore`（per-user file），用 `auth_disabled` 开关支持开发/单机模式。
- `/api/auth/{config,login,register,me,logout}`，第一个注册用户自动是 admin；FastAPI 依赖 `current_user` / `require_role("admin")`。
- 前端：`AuthProvider` 引导 + `RequireAuth` 路由守卫 + `LoginPage` / `RegisterPage` + `lib/api.ts` 自动注入 `Authorization` header + 401 触发 `aaf:auth:expired` 全局清缓存重定向。
- **Memory Explorer 五个 Tab**（比 PLAN 多了 Synthesis 隐式分类、显式 Rollback Tab）：Overview（counts、5s 轮询） / Knowledge（PaperCard list + 搜索 + 删除） / Heuristics（按 domain 过滤 + freeze/unfreeze + bump pass/fail + StrategyBlock 详情） / Reflections（list + 追加） / Rollback（按 `run_id` 一键回滚 knowledge/heuristics/reflections 三表）。
- TopBar：登录用户徽章（display_name + admin 角标）+ logout 按钮，`auth.config.enabled` 关闭时整块隐藏。

**实际 DoD**：`make check` 通过；431 passed / 1 skipped；frontend `tsc -b` + `vite build` 通过（156 kB gzip）。

### M6 · 部署、SDK、文档（进行中）

**目标**：
- 一台干净的 Linux 服务器执行 `docker compose up -d` 即可跑起完整栈（api / worker / web / postgres / redis）。
- 前端 SPA 由 Nginx 服务并反代 `/api/*` 与 `/api/tasks/:id/stream` SSE 到后端。
- `deploy/README.md` 给出从 0 到 1 的清单（克隆仓库 → 填 `.env` → `make up` → 第一个管理员注册）。
- Python SDK 占位（M6 中后段补，最低先 publish 本地 wheel）。

详细拆分见 §20.7。

### 20.7 M6 详细拆分（落地清单）

```
deploy/
├── README.md                    # 部署指南（含 nginx 反代 + HTTPS 提示）
├── docker-compose.yml           # 顶层 compose
├── docker-compose.prod.yml      # 生产 overlay（resource limits / restart 策略）
├── .env.example                 # 环境变量模板
├── api.Dockerfile               # 后端镜像（uv install + uvicorn + arq）
├── web.Dockerfile               # 前端镜像（multi-stage：vite build → nginx）
├── nginx/
│   ├── default.conf             # SPA fallback + /api 反代 + SSE buffering off
│   └── security-headers.conf
└── postgres/init.sql            # 初次启动建库（如未启用 alembic）
```

**M6.1 后端镜像**：
- `python:3.12-slim` base，安装 `uv`，`uv sync --frozen` 锁定依赖。
- 同一 image，`CMD` 可切换为 `uvicorn backend.main:app` 或 `arq backend.tasks.queue.WorkerSettings`，由 compose 不同 service 决定。
- `HEALTHCHECK` 走 `/api/version`。

**M6.2 前端镜像**：
- Stage 1: `node:20-alpine` → `npm ci && npm run build` 输出 `dist/`。
- Stage 2: `nginx:1.27-alpine`，拷贝 `dist/` + `nginx/default.conf`。
- `default.conf` 关键配置：
  - SPA fallback `try_files $uri /index.html`。
  - `/api/` 反代到 `api:8000`。
  - SSE：`proxy_buffering off; proxy_cache off; proxy_read_timeout 1h;` 避免事件流被缓冲。

**M6.3 docker-compose**：服务清单
- `api`（FastAPI）：依赖 `postgres` + `redis`，挂 `./data:/data`。
- `worker`（ARQ）：同一 image 不同 CMD；共享 `./data` 卷。
- `web`（Nginx + SPA）：依赖 `api`，对外 `80:80`。
- `postgres:16-alpine`：volumes `pg-data:/var/lib/postgresql/data`，POSTGRES_USER/PASSWORD/DB 由 env 注入。
- `redis:7.2-alpine`：appendonly + healthcheck。
- 全部带 `restart: unless-stopped` + `healthcheck`。

**M6.4 ENV 一致性**：把 `.env.example` 与 `backend/settings.py` 字段一一对齐（去掉 PLAN §23.7 里目前未实现的 `AAF_WORKDIR` 等无效项；新增 `auth_allow_signup`、`users_dir`、`task_store_dsn`、`task_queue` 等已落地字段）。

**M6.5 deploy README**：覆盖
1. 目标系统：Ubuntu 22.04 / Debian 12 + Docker 24+。
2. `git clone … && cp deploy/.env.example deploy/.env && vi deploy/.env`（必填 `AAF_SECRET_KEY`、`OPENAI_API_KEY` 或其他 LLM provider）。
3. `docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --build`。
4. 浏览器打开 `http://<host>/`，第一个 `register` 自动获得 admin 角色。
5. HTTPS：示例用 caddy/traefik 反代到 `web:80` 的写法（不内置）。
6. 升级：`docker compose pull && docker compose up -d`；备份：`./data/` + `pg_dump`。

**M6.6 Smoke test**：
- `docker compose up -d` 后 `curl http://localhost/api/version` 返回 200。
- `curl -N http://localhost/api/tasks/__nonexistent__/stream` 立即收到合法的 SSE 错误事件而不是 502（验证 SSE 反代）。

**DoD（M6）**：
- 在干净 Ubuntu 22.04 机器上 `make up` ≤ 5 分钟启动；`/api/version` 200；前端 `/` 200 渲染登录页；注册第一个用户后能正常进入 Dashboard。
- 删除 `OPENAI_API_KEY` 仍能启动（`MockLLMProvider` 兜底），跑一次 research workflow 不报硬错。
- `deploy/README.md` 让新同事 10 分钟内跑起来。

**累计实际**：M0–M5 一个完整周期内交付（含 harness engineering 与全部前后端）；M6 预计 1–2 个工作日。

#### 实际交付（2026-04-30）

- **基础设施**：`docker-compose.yml` + `deploy/backend.Dockerfile` + `deploy/frontend.Dockerfile` + `deploy/nginx/frontend.conf` + `.env.example` + `Makefile compose-*` 目标全部到位（M6.1–M6.4 完成）。
- **生产 overlay**：`docker-compose.prod.yml` 增加 `caddy` 服务（自动 Let's Encrypt + HTTP/3 + SSE friendly），并通过 `ports: []` 把 `frontend` 从主机解绑；模板见 `deploy/caddy/Caddyfile.example`。新增 env：`AAF_DOMAIN`、`AAF_ACME_EMAIL`、`AAF_TLS_HTTP_PORT`、`AAF_TLS_HTTPS_PORT`。
- **deploy/README.md**：覆盖五分钟安装、架构图、bind mounts、Day-2 操作（日志/升级/备份/admin 改密）、HTTPS（两条路径：上游反代 vs 内置 prod overlay）、Troubleshooting 表、Pre-flight checklist（M6.5 完成）。
- **Python SDK**：`sdk/python/aaf-sdk` 0.1.0 — `httpx + pydantic` 二依赖，覆盖 `auth/tasks/manuscripts/knowledge/heuristics/memory/workflows/tools` 8 个子客户端，sync + async facade，自定义 SSE 解析器。已纳入 ruff + mypy + 8 个 respx smoke 测试，`uv pip install --native-tls -e sdk/python` 可装。
- **docs 套件**：`docs/architecture.md`（运行时拓扑 + 请求流程 + ASCII 图）、`docs/api-reference.md`（10 个路由全量 endpoint 表）、`docs/writing-your-own-skill.md`（L1/L2/L3 + 脚本 magic comment + 测试模板）、`docs/writing-your-own-llm-provider.md`（Protocol + 注册 + 完整示例）、`docs/README.md` 索引。
- **Smoke test**：因沙箱无 docker daemon，未在本机执行 `docker compose up`。所有 docker-compose 文件经 Python YAML 解析校验通过；正式部署需在目标机上执行《deploy/README.md》§Five-minute install 流程并核对 §Pre-flight checklist。

### 20.8 M7 · "自管理"能力闭环（进行中）

#### 背景

M0–M6 完成后，框架已经能在任意私有机器上跑前后端、走通 research / write / revision workflow、管理稿件与记忆。但有三块**用户主动管理**能力暴露在外：

1. **Paper Ingest 缺合一管线**：用户读到一篇 PDF，希望"传一下就进知识库 + 自动跑 typed-link 进化"。当前 `manuscripts.upload`（草稿）和 `knowledge.papers.create`（PaperCard）是两条互不连通的路径，evolver 只在 `research` workflow 内部触发，离线 / 公司内网 / 无 arxiv 访问的用户没法激活这条路径。
2. **Skill 管理无 HTTP 入口**：`SkillHost` 引擎完整（loader / matcher / injector / executor + 热重载），但**没有任何 router 暴露**，前端看不到 skill 列表，也无法在不重启情况下安装 / 编辑 / 启停 skill。
3. **知识库不接收任意文档**：`VectorStore` 当前只承载 `PaperCard`，不支持"上传一份 markdown / PDF 笔记 / 组会纪要"做 RAG 召回；workflow 的 RECALL 阶段因此只能命中"框架自己写过的"内容。

M7 用三个互相解耦的子里程碑同时收敛这三块。每一块单独可上线、有独立 DoD 与单测。

#### M7 总目标（一句话）

让用户**只用 UI / API**就能："上传论文让框架自己整理"、"上传任意知识让 RAG 召回"、"安装 / 编辑 / 启停 skill"，**整个过程不需要进 Cursor、不需要重启后端、不需要外网搜索**。

#### M7 整体里程碑表

| 子里程碑 | 范围 | 阻塞解锁的产品行为 | 工作量估计 |
|---|---|---|---|
| M7.1 | Paper Ingest 管线（PDF/MD → PaperCard → evolver） | "我有篇论文，让框架自己记住" | 后端 ~2h，前端 ~1h |
| M7.2 | Skill 管理 API + UI（list / detail / upload / edit / enable / disable / invocations） | "在线扩 capability，不重启" | 后端 ~3-4h，前端 ~4-5h |
| M7.3 | Knowledge Document RAG（DocumentStore + chunking + bundle.read 集成） | "传一份知识进来，未来 workflow 都能召回" | ✅ 已交付（后端 + SDK + 前端 + 文档） |

三个子里程碑**互不阻塞**，可任意顺序推进；推荐顺序 M7.1 → M7.2 → M7.3（按 ROI 与工作量递增）。

---

#### M7.1 · Paper Ingest 管线

**目标**：合并三条现存能力（PDF→markdown / `KnowledgeStore.write_card` / `PaperMemoryEvolver.evolve_new_paper`）成一个用户可见的 ingest 入口。

**API 契约**（新增于 `backend/api/routers/knowledge.py`）：

```http
POST /api/knowledge/papers/ingest
Content-Type: multipart/form-data | application/json

— multipart 形态（文件上传） —
file:               required, .pdf / .md / .markdown / .txt   (≤ 25 MB)
title:              optional, 缺省时从 file 名 / PDF metadata 推断
authors:            optional, 逗号分隔
year:               optional, int
tags:               optional, 逗号分隔
source_kind:        optional ∈ {"user_upload","arxiv","doi","manual"}, 缺省 "user_upload"
trigger_evolution:  optional bool, 缺省 true
llm_extract:        optional bool, 缺省 true（关掉则纯启发式抽取）

— JSON 形态（仅 metadata，无文件） —
{
  "title": "A-Mem ...",
  "authors": ["..."],
  "year": 2024,
  "summary": "...",
  "tags": [...],
  "source_kind": "manual",
  "extras": { ... },
  "trigger_evolution": true
}

→ 201 IngestResponse
{
  "card": PaperCard,
  "evolution": {
    "mode": "llm" | "heuristic" | "skip",
    "neighbors_considered": int,
    "typed_links_added": [TypedLink],
    "tags_added": [str],
    "reason": str
  },
  "synthesis": SynthesisNote | null,         # 命中 check_synthesis_trigger 时给出
  "extracted": {                              # 给 UI 展示提取过程的可见性
    "method": "pdf+llm" | "pdf+heuristic" | "metadata_only",
    "extract_ms": int,
    "evolve_ms": int,
    "preview": str (≤ 1000 字, body 摘要)
  }
}
```

**实现点**：

1. **复用** `manuscripts.py` 里现成的 `_pdf_to_markdown`，提到 `backend/core/text/pdf.py` 当公共 helper（manuscripts 与 knowledge 都引用，避免循环）。
2. 新增 `backend/knowledge/extractor.py`：`PaperExtractor.extract(text, llm=None) → ExtractedPaper(title, authors, year, abstract, summary, sections, contributions, baselines, datasets)`。
   - LLM 路径：构造一个**强 schema 约束**的 prompt，要求 LLM 返回 JSON；解析失败 fallback 到启发式。
   - 启发式路径：正则取 title（首个 H1）/ year（4 位数字 1990-2030）/ abstract（"Abstract" 段直到下一个 H1 / "Introduction"）。
3. 新增 `backend/knowledge/ingest.py`：`PaperIngestor.ingest(input) → IngestResult`，串：`extract → write_card → evolve_new_paper → check_synthesis_trigger`。
4. 复用现有 `PaperMemoryEvolver.evolve_new_paper(card, run_id="ingest:<paper_id>")`，无需改动。
5. **路由层**：实现 `multipart` 与 `JSON` 两套，共享同一个 `PaperIngestor`。
6. **配置开关**：`AAF_PAPER_INGEST_MAX_BYTES`（默认 25 MB）、`AAF_PAPER_INGEST_LLM_TIMEOUT_S`（默认 60s）。
7. **Telemetry**：`telemetry.record("knowledge.ingest", paper_id, extract_ms, evolve_ms, mode)`。

**前端**（`frontend/src/pages/MemoryPage.tsx::KnowledgeTab` + 新组件）：

- 卡片列表上方加 ① "Ingest paper" 按钮。
- 抽屉（Drawer）打开后两个 tab：**Upload file** / **Paste metadata**。
- 文件 tab：拖拽上传 + 表单 (title 可选、authors、year、tags) + `trigger_evolution` 开关。
- metadata tab：纯表单 + summary 长文本框。
- 提交后显示 `Ingest in progress…`，后端 200 后用一个**结果卡片**展示：
  - 提取的 title / authors / year / abstract preview
  - Typed-links 可视化（每条一行：`extends → [Other Paper Title]`，颜色标 link_type）
  - tags_added + synthesis 触发提示

**单元测试**：

- `backend/tests/unit/test_paper_extractor.py`：mock 文本 → 检验启发式抽取；mock LLM 返回 → 检验 JSON 解析路径。
- `backend/tests/unit/test_paper_ingestor.py`：用 `MockLLMProvider` 跑完整管线，断言 `evolve_new_paper` 被调用一次、写入 KnowledgeStore 的卡片是预期形状。
- `backend/tests/integration/test_app_paper_ingest.py`：HTTP `POST /api/knowledge/papers/ingest`（multipart 与 JSON 两条）→ 检 201 + IngestResponse + Knowledge 表新增一行。

**SDK**：`sdk/python/aaf/knowledge.py` 加 `KnowledgeAPI.ingest_paper(file=..., **metadata)` 与 `IngestResult` DTO。

**docs**：`docs/api-reference.md` Knowledge 段加新条目；`docs/architecture.md` Paper Ingest 流程图。

**DoD（M7.1）**：

- [x] `make check` 全绿（新增单测 ≥ 3 个 + 集成 1 个）
- [x] UI 抽屉传一个 PDF / Markdown → 显示 typed-links → `Memory → Knowledge` 列表多一张卡 → 用 SDK `client.knowledge.list_all()` 也能看到
- [x] 离线 / mock LLM 模式下整条链路工作（`mode=heuristic`，typed-link 仅靠 tag 重叠）
- [x] `data/knowledge/` 下出现新文件，rollback `/api/memory/rollback/ingest:<paper_id>` 可一键回滚

**已交付**（2026-05）：
- 后端：`backend/core/text/pdf.py`（共享 PDF→md helper）/ `backend/knowledge/{extractor,ingest}.py` / `POST /api/knowledge/papers/ingest`（multipart + JSON）
- 前端：`MemoryPage → Knowledge` tab 内的 `IngestPaperPanel`（Upload file / Paste metadata 双 tab + 结果展示）
- SDK：`aaf.knowledge.{Async,}KnowledgeAPI.ingest_paper(file=..., **metadata)` + `IngestPaperResponse / IngestExtracted / IngestEvolution` DTO
- 测试：`test_paper_extractor.py`（5 用例）、`test_paper_ingestor.py`（6 用例）、`test_app_knowledge.py` 内 ingest 集成 4 用例

---

#### M7.2 · Skill 管理 API + UI

**目标**：把 `SkillHost` 暴露给前端，让用户能**在线**看 / 创建 / 编辑 / 上传 / 启停 skill，并查看每个 skill 的真实调用历史。

**API 契约**（新增 `backend/api/routers/skills.py`）：

```http
GET    /api/skills                                # list with metadata + stats
GET    /api/skills/{name}                         # full SKILL.md body + scripts + heuristics
POST   /api/skills                                # create new
                                                  # multipart: tarball (.tar.gz of SKILL.md + scripts/)
                                                  #   OR JSON { name, description, body_md, scripts:[{name,content,inputs,uses_llm}] }
PATCH  /api/skills/{name}                         # edit body / metadata / scripts (replace semantics)
DELETE /api/skills/{name}                         # soft-delete: move skills/<name>/ → skills/_disabled/<name>/
POST   /api/skills/{name}:reload                  # hot-reload single skill (no full restart)
POST   /api/skills/{name}:enable                  # restore from _disabled/
POST   /api/skills/{name}:disable                 # = soft-delete; idempotent
GET    /api/skills/{name}/invocations             # last N runs (q from task event log)
POST   /api/skills/{name}/scripts/{script}:dry_run  # validate + run with stub args, no memory write
```

**列表 + 详情返回 schema**：

```jsonc
// GET /api/skills
{
  "items": [{
    "name": "literature-search",
    "description": "...",
    "tags": ["research","arxiv"],
    "domain": "academic",
    "enabled": true,
    "scripts": ["search","filter"],
    "uses_llm_any": false,
    "last_used_at": "2026-05-05T...",
    "invocation_count_30d": 24,
    "avg_elapsed_ms": 2400,
    "version_hash": "sha256:...",       // 用于检测外部编辑
    "loaded_from": "skills/literature-search/"
  }],
  "total": 18
}

// GET /api/skills/{name}
{
  ...上述字段,
  "body_md": "<SKILL.md 正文>",
  "scripts_detail": [{"name":"search","path":"...","inputs":{...},"uses_llm":false,"source":"..."}],
  "heuristics": [HeuristicSkill]    // 通过 SkillMatcher / HeuristicStore 关联
}
```

**安全 / 沙箱**：

1. **写操作（POST/PATCH/DELETE）必须 `require_role("admin")`**（`auth_disabled=true` 时跳过）。
2. **上传脚本走 staging**：上传后先解压到 `skills/_pending/<name>/`，校验 frontmatter + 脚本前 30 行的 `# aaf:` magic comments。校验通过才**原子 mv**到 `skills/<name>/`。失败时整目录 unlink，绝不留半成品。
3. **路径白名单**：`SKILL.md` + `scripts/*.py`；任何 `..`、绝对路径、symlink、hidden file 直接拒。
4. **大小限制**：单 tarball ≤ 1 MB，单脚本 ≤ 64 KB。
5. **dry_run**：用 `SkillExecutor` 的环境白名单 + 5s 超时；输出截断到 8 KB；**不写 memory、不让脚本看到真 LLM key**。
6. **审计日志**：每次写操作落 `EpisodicStore.append_reflection(type="audit")` 并打 structlog `skill.admin.*`。

**前端**（新增 `frontend/src/pages/SkillsPage.tsx`，左侧导航加一级页面）：

- **列表视图**：表格（name / domain / enabled / last_used / inv_30d / avg_ms），右上角「Install skill」按钮。
- **详情视图**（点单条进入）：
  - 顶部 metadata 卡（含 toggle enabled、version_hash、Reload 按钮）。
  - Tabs：**Body**（Monaco markdown 只读 → 编辑模式 + Save）/ **Scripts**（左侧脚本树 + 右侧 Monaco python 视图，每个脚本带 Dry-run 按钮）/ **Heuristics**（从 `heuristicsApi.list({skill: name})` 拉取）/ **Invocations**（30 天内每次调用的时间 / task_id / status / elapsed / 错误片段）。
- **Install Skill 抽屉**：
  - Tab A — 上传 tarball
  - Tab B — 用模板新建（填 name/description/scripts，前端给一个最小 SKILL.md + script.py 模板）
- 删除 / 禁用按钮带二级确认 + "5 秒撤回 toast"（lib `sonner` 的 dismissable）。

**单元测试**：

- `backend/tests/unit/test_skill_admin_validator.py`：上传 tarball 校验路径白名单 + frontmatter + 大小限制。
- `backend/tests/integration/test_app_skills_api.py`：POST 创建 → GET 列表能看到 → POST :disable → GET 列表里 enabled=false → POST :enable → 恢复。
- `backend/tests/integration/test_skill_dry_run.py`：dry-run 一个有 sleep 的脚本，验证 5s 超时杀进程组。

**SDK**：`sdk/python/aaf/skills.py` 新加全套客户端方法。

**docs**：`docs/writing-your-own-skill.md` 加章节"通过 API 在线管理 skill"；`docs/api-reference.md` 整段 Skills 表。

**DoD（M7.2）**：

- [x] `make check` 全绿（M7.2 全阶段：494 passed, 1 skipped + tsc OK + frontend build OK + consistency green）
- [x] 在 UI 上传 / 编辑一个最小 skill（JSON-only 入口） → 列表立刻能看到 → 点 Reload 后 generation 计数器递增 → 脚本能在 Scripts tab 用 dry-run 验证，并在 Invocations tab 看到一行 `dry_run` 状态
- [x] 非 admin 用户调写操作返回 403；`auth_disabled=true` 时通过（`require_admin_or_open_mode` 集成测试覆盖）
- [x] 恶意 payload（路径不合法、超大脚本、name 跟 frontmatter 不一致）全部被拒，`skills/_pending/` 在失败后干净（`test_skill_admin.py`）
- [x] dry-run 一个无限循环脚本能在 5s 内被杀干净（`test_executor_records_timeout` + dry_run 路径继承同一个 `SkillExecutor`）

**已交付**（2026-05，M7.2 后端 + 前端 + SDK）：

- 后端：
  - `backend/core/skill_host/invocations.py` —— `SkillInvocation` / `InvocationStats` / `InMemorySkillInvocationStore` 环形 buffer + 30 天聚合
  - `backend/core/skill_host/admin.py` —— `SkillAdmin`（staging dir → 原子 rename → reload + 失败回滚），`SkillInstallInput` / `SkillScriptInput` / `SkillAdminError`，路径 / 大小 / frontmatter 严格校验
  - `backend/core/skill_host/executor.py` —— 注入 invocation store；`success / error / timeout / dry_run` 全部落表
  - `backend/core/skill_host/registry.py` —— `SkillHost` 暴露 `generation` / `executor` / `invocations` / `list_invocations` / `invocation_stats` / `skills_root`
  - `backend/api/routers/skills.py` —— 新 router（list / detail + 渐进披露的 `/scripts/{script}` / install / patch / delete / `:disable` / `:enable` / `:reload` / `:dry_run` / `/invocations`），`require_admin_or_open_mode` 角色门
  - `backend/app.py` lifespan 装配 `SkillHost.build(...)` + `SkillAdmin`，挂到 `AppState.skill_host` / `AppState.skill_admin`
  - `backend/settings.py` 新增 `aaf_skills_root` / `aaf_skill_workdir_root` / `aaf_skill_dry_run_timeout_s`
- 前端：
  - `frontend/src/types/api.ts` —— 12 个 skill DTO 镜像（`SkillSummary` / `SkillDetail` / `SkillInvocation` / `SkillInstallInput` / …）
  - `frontend/src/lib/skills.ts` —— `skillsApi`：list / get / getScript / invocations / install / update / delete / disable / enable / reload / dryRun
  - `frontend/src/pages/SkillsPage.tsx` —— 一级页面 `/skills` 与 `/skills/:name`：左侧列表（含 active + disabled 标签 + 30 天 stats），右侧详情，三个 Tab：**Body**（Monaco markdown 只读）、**Scripts**（左脚本树 + Monaco python 视图 + JSON args + dry-run 即时反馈），**Invocations**（30 天表格、每 10 s 自动刷新）
  - `frontend/src/pages/SkillsPage.tsx` Install/Edit drawer —— 复用同一个组件：新建走模板（`TEMPLATE_BODY` + `TEMPLATE_SCRIPT`），编辑则按需懒拉每个脚本源，原子保存后自动跳转到详情；侧边栏增加 `Skills` 一级入口（Dashboard → Research → Manuscripts → Revision → Memory → **Skills** → Tasks → Settings）
  - 二级动作：Disable 按钮带 `window.confirm` + `sonner` 5s `Undo`，Enable / Reload 直接生效后弹绿色 toast
- SDK：`sdk/python/aaf/skills.py` 全套 `Async/Sync SkillsAPI`（list / get / get_script / install / update / disable / enable / reload / dry_run / invocations）+ DTO 在 `models.py` 镜像
- 测试：`test_skill_admin.py` ×16、`test_skill_invocations.py` ×9、`test_app_skills.py` ×12、`sdk/.../test_smoke.py` ×2 (skills 段)
- 渐进披露：`GET /api/skills` 仅返回 frontmatter + 统计；`GET /api/skills/{name}` 加 SKILL.md body 但 **不带** 脚本源；脚本源通过 `GET /api/skills/{name}/scripts/{script}` 单独懒加载，前端 `BodyTab` / `ScriptsTab` / Install drawer 全部按这个三阶段分别请求，与 Cursor / Claude Code 的"L1 元数据 → L2 body → L3 脚本"分层一致
- 一致性约定：`scripts/check_consistency.py` 现在显式忽略下划线前缀的保留目录（`_disabled`、`_pending`、`_trash`），与 `SkillLoader` 既有规则统一

---

#### M7.3 · Knowledge Document RAG

**目标**：把"任意文档"当作框架的工作记忆 —— 用户上传一段 markdown / 一份 PDF 笔记 / 一篇博客正文，框架**chunk + embed + 索引**，未来任何 workflow 的 RECALL 阶段都能命中。

这是 PaperCard 的**正交补充**：PaperCard 是高度结构化的"已读论文卡"，DocumentStore 是非结构化的"任意知识资源"。

**新增数据模型**（`backend/memory/models.py`）：

```python
class KnowledgeDocument(BaseModel):
    doc_id: str              # stable_id("doc", source, title)
    title: str
    source_kind: Literal["pdf_upload","md_upload","txt_upload","note","url","clipboard"]
    source_uri: str | None   # 原始 URL / 文件路径（如果有）
    summary: str             # 长度 ≤ 500，LLM 或启发式生成
    raw_text: str            # 完整原文（不直接喂 LLM，用于回溯）
    tags: list[str]
    chunk_ids: list[str]     # 关联的 chunk
    bytes: int
    created_at: datetime
    user_id: str | None
    extras: dict[str, Any]


class DocChunk(BaseModel):
    chunk_id: str            # f"{doc_id}#{idx:04d}"
    doc_id: str
    idx: int
    text: str                # 800-token 切片（默认）
    char_offset_start: int
    char_offset_end: int
    section_path: list[str]  # 标题面包屑（["Methods","Architecture"]），可选
    tags: list[str]          # 继承自 doc + chunk-specific（可选）
```

**新增 Store**（与现有 `KnowledgeStore` 平级）：

- `backend/memory/document_store.py`
  - `DocumentStore` Protocol：`write / get / delete / list / search_chunks(query) / rollback_run(run_id)`
  - `YamlDocumentStore`（`data/documents/<doc_id>.yaml`）+ `SqlDocumentStore`（与现有 `SqlEpisodicStore` 共用 engine）
- 写时**同时**调用 `vector_store.add(chunk_id, text, metadata={doc_id, tags, section_path, kind="doc_chunk"})`。
- `MemoryBundle` 加 `documents: DocumentStore` 字段；`MemoryFactory` 根据 `settings.document_store_backend` 装配（默认 yaml，sql 可选）。

**Chunking 管线**（`backend/memory/chunker.py`）：

```python
def chunk_markdown(
    text: str,
    *,
    target_tokens: int = 800,        # 估算用 chars/4
    overlap_tokens: int = 100,
    respect_headings: bool = True,
) -> list[Chunk]: ...
```

策略：
1. 先按 H1-H6 切大块（保留 section_path）。
2. 大块超 `target_tokens` → 用滑动窗口再切，相邻块 overlap `overlap_tokens` 防上下文断裂。
3. 不强切代码块 / 表格（探测 ``` ```、`|---|`）。

**Ingest 端点**（新增 `backend/api/routers/documents.py`）：

```http
POST   /api/documents/ingest      multipart: file (pdf/md/txt) + optional metadata fields
                                  OR JSON: {title, raw_text, source_kind, ...}
                                  → 201 { document: KnowledgeDocument, chunks_indexed: int, indexer_ms: int }
GET    /api/documents
GET    /api/documents/{doc_id}
GET    /api/documents/{doc_id}/chunks?offset=&limit=
POST   /api/documents/{doc_id}:reindex     # 重新 chunk + 重建向量
DELETE /api/documents/{doc_id}             # 删 doc + 所有 chunk_ids 从 vector store 撤回
POST   /api/documents/search               # body { q, top_k, filters }
                                            # → { hits: [{chunk_id, doc_id, doc_title, text, score, section_path}] }
```

**Workflow 集成**（`backend/workflows/base.py` 的 RECALL stage 与 `MemoryBundle.read`）：

- `MemoryBundle.read(query)` 当前只查 `KnowledgeStore`，扩展为**并发**查 `KnowledgeStore.match_papers(query)` + `DocumentStore.search_chunks(query)`，把两类结果按 `(score, kind)` 二级排序合并，`kind="doc_chunk"` 的命中带 `doc_title + section_path` 注入 prompt。
- RECALL 阶段事件加 `data={"papers": int, "doc_chunks": int}` 让 UI 看清来源比例。

**前端**（新增 `frontend/src/pages/KnowledgeLibraryPage.tsx`，左侧导航加一级页面，与 `Memory → Knowledge` 并列）：

- 列表：每条 doc 显示 title / source_kind 角标 / chunk 数 / tags / 创建时间。
- 详情：原文 markdown 渲染 + 右侧 chunk 索引导航（点击高亮对应原文段落）+ "Re-index" 按钮。
- Ingest 抽屉：拖文件 / 粘 markdown / 给 URL（URL fetch 留 backlog）。
- 搜索框：`/api/documents/search` 实时搜，结果显示 `doc_title › section_path → snippet`。

**单元测试**：

- `backend/tests/unit/test_chunker.py`：markdown 切 5 个 case（短 / 含代码块 / 多级标题 / 大块切三 / 中文）。
- `backend/tests/unit/test_document_store_yaml.py`：write / get / delete / rollback。
- `backend/tests/unit/test_memory_bundle_read_with_docs.py`：bundle.read 同时返回 PaperCard 和 doc chunk。
- `backend/tests/integration/test_app_documents_api.py`：upload md → search 命中 → delete → search 不再命中。

**SDK**：`sdk/python/aaf/documents.py` 全新模块，与 `knowledge.py` 平级。

**docs**：`docs/architecture.md` 加 Knowledge Library 章节（说明它跟 Knowledge cards 的边界）；`docs/api-reference.md` 加 Documents 表。

**DoD（M7.3）**：

- [x] `make check` 全绿（516 passed + 1 skipped + tsc OK + frontend build OK + ruff/mypy OK；2026-05）
- [x] UI 上传一份 markdown → 立刻在 `POST /api/documents/search` 命中（`backend/tests/integration/test_app_documents.py::test_ingest_json_creates_chunks_and_indexes_vectors`、前端 `KnowledgeLibraryPage` Search tab 实测）；workflow `RECALL` stage 现在的 `MEMORY_READ` 事件包含 `doc_chunks` 计数（`research/demo/write/revision` 全部更新）
- [x] 删 doc 后 vector store 也对应清干净（`backend/tests/unit/test_document_store.py::test_in_memory_delete_prunes_vector_entries` + integration `test_delete_prunes_vector_entries` 用 `vector.count()` 验证）
- [x] `bundle.snapshot("...")` 同时返回 PaperCard + DocChunk，按 score 合排，无重复（`backend/tests/unit/test_memory_bundle_with_docs.py::test_snapshot_returns_doc_chunks_alongside_papers`）

**已交付**（2026-05，M7.3 后端 + SDK + 前端）：

- 后端：
  - `backend/memory/models.py` —— `KnowledgeDocument` / `DocChunk` / `DocChunkHit` / `DocumentSourceKind`，`MemorySnapshot.doc_chunks` + `doc_chunks_text(max_chars)` helper
  - `backend/memory/base.py` —— `DocumentStore` Protocol；`MemoryBundle.documents: DocumentStore | None` + `MemoryBundle.snapshot()` 现在并发查 `KnowledgeStore` + `DocumentStore`
  - `backend/memory/chunker.py` —— heading-aware sliding window，原子代码块/表格保护，UTF-8 中文/英文混排可用
  - `backend/memory/document_store.py` —— `InMemoryDocumentStore` + `YamlDocumentStore`（`<root>/<doc_id>/{document.yaml, chunks.yaml}`），`make_chunk_id` + `heuristic_summary`
  - `backend/memory/factory.py` + `backend/settings.py` —— 新增 `documents` 段（`memory_documents_backend`、`memory_documents_dir`），与现有 `auto/yaml/memory` 选择保持一致
  - `backend/api/routers/documents.py` —— 7 个端点：`POST /api/documents/ingest`（multipart **或** JSON）、`GET /api/documents`、`GET /api/documents/{doc_id}`、`GET /api/documents/{doc_id}/chunks`、`POST /api/documents/{doc_id}:reindex`、`DELETE /api/documents/{doc_id}`、`POST /api/documents/search`（filter `kind=doc_chunk` + `doc_id`）
  - `backend/app.py` —— wires `documents_router` 在 lifespan 之后注册
  - `backend/workflows/{research,demo,write,revision}.py` —— `MEMORY_READ` event 新增 `doc_chunks` 字段
  - 测试：`tests/unit/test_chunker.py`（7 case：短文 / 多级标题 / 滑窗 overlap / 代码块原子 / 中文 / 无标题 / 空输入）、`tests/unit/test_document_store.py`（in-memory + YAML 双实现 round trip / delete cascade / reindex shrink / rollback / `_disabled` 过滤）、`tests/unit/test_memory_bundle_with_docs.py`（snapshot 同时召回 PaperCard 与 DocChunk）、`tests/integration/test_app_documents.py`（6 case：JSON ingest / multipart MD ingest / list+get+chunks pagination / delete cascades vector / reindex 保 doc_id / 拒绝空 raw_text）
- SDK：`sdk/python/aaf/documents.py`（`AsyncDocumentsAPI` + `DocumentsAPI`）、`sdk/python/aaf/models.py` 新增 `KnowledgeDocument` / `DocChunk` / `DocChunkHit` / `DocumentSourceKind` / `IngestDocumentResponse`，`AAFClient.documents` / `AsyncAAFClient.documents` 自动注入；`sdk/python/tests/test_smoke.py` 增加 `documents_ingest_and_search` + `documents_list_get_and_delete`
- 前端：
  - `frontend/src/types/api.ts` —— 镜像 9 个 document DTO（`KnowledgeDocument` / `DocChunk` / `DocChunkHit` / `IngestDocumentResponse` / list/page/search 响应 / `IngestDocumentJSONInput`）
  - `frontend/src/lib/documents.ts` —— `documentsApi`：list / get / listChunks / ingestJSON / ingestFile / reindex / delete / search
  - `frontend/src/pages/KnowledgeLibraryPage.tsx` —— 一级页面 `/library` 与 `/library/:docId`：左侧文档列表（source_kind 角标 + chunk 数 + tags + 相对时间 + tag filter），右侧详情面板带三个 Tab（**Body**：Monaco markdown 只读 / **Chunks**：左 chunk 索引 + 右 monospace 详情，section_path 面包屑显示 / **Search**：scoped to 当前 doc，每条 hit 显示 score + 面包屑 + 摘要）；右上角 Re-index / Delete（带 `window.confirm`）/ Close 按钮
  - 「Ingest document」抽屉 —— Paste text（Monaco markdown + source_kind + tags）/ Upload file（PDF / MD / TXT 单文件）双模式，`sonner` toast 反馈，成功后自动跳转到详情；侧边栏在 Revision 之后插入 `Library` 一级入口
- 文档：`docs/api-reference.md` 增加 Documents 表 + `KnowledgeDocument` / `DocChunk` JSON 范例 + chunker 默认值；`docs/architecture.md` §3.3 表格新增 `documents` 行 + 解释，新增 §5c "Request flow — document ingest (M7.3)"；`backend/api/AGENTS.md` 把 M7 路由表格状态从 "in flight" 改为 "delivered"；`backend/memory/AGENTS.md` `documents` 行从 "M7.3 待交付" 改为 "✅"；`frontend/AGENTS.md` 同步两条新路由

---

#### M7 全局 DoD

- [x] M7.1 / M7.2 / M7.3 各自 DoD 全绿
- [x] `scripts/check_consistency.py` 通过（含新 router、新 Store 的注册；`backend/tests/integration/test_app_documents.py` 自动满足 router ↔ test 配对要求）
- [x] `frontend tsc + vite build` 通过
- [x] 一致性：`backend/api/AGENTS.md` / `backend/memory/AGENTS.md` / `frontend/AGENTS.md` 均反映新增子系统
- [x] PLAN §11 / §12 / §13 中相应章节脚注 "M7 起新增" 提示
- [x] `docs/api-reference.md` + `docs/architecture.md` 同步
- [ ] SDK Python 三个新模块（`paper_ingest` 复用 `knowledge`、`skills`、`documents`）+ smoke test

---

### 20.9 M8 · Gated Proposals + Planner DAG

#### 总览

老 `Academic-Agent` 设计中的 ADR-008（"未批准前绝不修改代码"）以及 LLM 编译 DAG 的能力，没有 1:1 移植到当前框架。M8 把这两个机制做回来，但放到独立的子系统里：

- **M8.1 Gated Proposals**（`/api/proposals`）—— 给框架自身的代码 / skill / rule / 配置 改动加门：任何 LLM 或人类的修改都先落成 `Proposal` 草稿，经过 `submit → approve` 才允许 `apply`。本轮 `apply` 仅记录 `status=applied` + 写审计日志，**不**自动改盘上文件，保持安全边界由人或 CI 兜底。
- **M8.2 Planner DAG**（`/api/planner`）—— 一个可选的 `PlannerAgent`：宿主 LLM 给出 query，框架返回一张 `PlanDAG`（可序列化的 skill / tool / llm / memory 节点 + 依赖边），可单独调 `validate`，也可调 `execute` 异步跑。`execute` 会把 plan 塞进新增的 `dag` 工作流并入 Task 系统，复用既有 SSE 通道。

两者都是可选能力：原有 workflow（research / write / revision / demo）路径保持不变，宿主 LLM 想"先 compile 再 execute"才走 planner。

---

#### M8.1 · Gated Proposals (`/api/proposals`)

**目标 DoD**

- [x] `backend/proposals/` 提供 `ProposalStore` Protocol + `InMemoryProposalStore` + `YamlProposalStore`（atomic write）
- [x] `backend/api/routers/proposals.py` 暴露 9 个端点（list / create / get / patch / submit / approve / reject / apply / withdraw）+ `DELETE`
- [x] 状态机硬约束：非法迁移返回 409（详见下表）
- [x] 每次状态变更 / patch 写入 `audit_log`（actor / action / timestamp / notes）
- [x] 鉴权：写操作（含 approve/reject/apply/delete）在 `auth_disabled=False` 时要求 `admin` role；`auth_disabled=True` 全开
- [x] 单元（store）+ 集成（router）测试覆盖所有合法 / 非法状态迁移
- [x] SDK `aaf.proposals` + smoke test
- [x] 前端 `/proposals` 页面（list + detail + draft form + state-aware action 按钮）

**核心模型**（`backend/proposals/models.py`）

```python
ProposalStatus = Literal["draft", "pending", "approved", "rejected", "applied", "withdrawn"]
RiskLevel = Literal["low", "medium", "high", "tier_d"]
ProposerKind = Literal["human", "llm", "agent"]
ProposalAction = Literal["create", "update", "submit", "approve", "reject", "apply", "withdraw", "comment"]


class ProposalAuditEvent(BaseModel):
    timestamp: datetime
    actor: str             # user_id | "system" | "llm:openai" | ...
    action: ProposalAction
    notes: str = ""
    metadata: dict[str, Any] = {}


class Proposal(BaseModel):
    proposal_id: str       # 12-hex
    title: str
    summary: str = ""
    motivation: str = ""   # markdown
    risk_level: RiskLevel = "low"
    target_paths: list[str] = []
    diff: str = ""         # unified diff or descriptive change
    status: ProposalStatus = "draft"
    proposer_id: str = ""
    proposer_kind: ProposerKind = "human"
    reviewer_id: str | None = None
    review_notes: str = ""
    tags: list[str] = []
    created_at: datetime
    updated_at: datetime
    decided_at: datetime | None = None
    applied_at: datetime | None = None
    audit_log: list[ProposalAuditEvent] = []
    extras: dict[str, Any] = {}
```

**状态机**

| 起始 | 触发 | 允许角色 | 终态 |
|---|---|---|---|
| `draft` | `submit` | proposer | `pending` |
| `draft` | `withdraw` | proposer | `withdrawn` |
| `pending` | `approve` | admin | `approved` |
| `pending` | `reject` | admin | `rejected` |
| `pending` | `withdraw` | proposer | `withdrawn` |
| `approved` | `apply` | admin | `applied` |
| `approved` | `withdraw` | proposer | `withdrawn` |
| 其他 | * | * | **409 Conflict** |

`PATCH` 仅在 `draft` / `pending` 允许（admin 任意状态），写入 `update` audit。`DELETE` 仅 `draft` / `withdrawn`、admin。

**端点契约**

| 方法 | 路径 | Body | 返回 | 鉴权 |
|---|---|---|---|---|
| `GET` | `/api/proposals` | (query: status, proposer_id, tag, page, page_size) | `ProposalListResponse` | user |
| `POST` | `/api/proposals` | `CreateProposalInput` | `Proposal`(draft) | user (open mode) / admin |
| `GET` | `/api/proposals/{id}` | — | `Proposal` | user |
| `PATCH` | `/api/proposals/{id}` | `UpdateProposalInput` | `Proposal` | proposer or admin |
| `POST` | `/api/proposals/{id}:submit` | `{notes?}` | `Proposal`(pending) | proposer |
| `POST` | `/api/proposals/{id}:approve` | `{notes?}` | `Proposal`(approved) | admin |
| `POST` | `/api/proposals/{id}:reject` | `{notes?}` | `Proposal`(rejected) | admin |
| `POST` | `/api/proposals/{id}:apply` | `{notes?}` | `Proposal`(applied) | admin |
| `POST` | `/api/proposals/{id}:withdraw` | `{notes?}` | `Proposal`(withdrawn) | proposer or admin |
| `DELETE` | `/api/proposals/{id}` | — | `204` | admin |

**安全约束**

`apply` **不修改盘上文件**。它只是把状态置 `applied` + 记录 audit，并返回 proposal。真正的代码落地由人或 CI 取 `diff` 字段去 apply，对应老 ADR-008 的"门"。后续轮次可以扩展白名单路径（如 `skills/`）+ 复用 `SkillAdmin` 的 staging/atomic/rollback。

**Settings**

```env
aaf_proposals_backend=auto       # auto | memory | yaml
aaf_proposals_dir=./data/proposals
```

`auto` 在生产侧解析为 `yaml`，单测/CI 解析为 `memory`。

---

#### M8.2 · Planner DAG (`/api/planner`)

**目标 DoD**

- [x] `backend/planner/{models,compiler,validator,executor}.py` 完成
- [x] `PlannerCompiler.compile(query, ...)` —— 优先 LLM JSON-mode；LLM 不可用 / 解析失败时回退启发式 fallback（单节点 plan）
- [x] `validate_plan` 检测：节点 id 唯一、依赖存在、无环、未知 skill / tool 名、参数最小 schema
- [x] `DAGExecutor` 拓扑分层 + 每层 `asyncio.gather` 并行 + 节点级 retry + `on_failure` 三档（abort / skip / continue）
- [x] 节点级 SSE 事件（`stage_start` / `stage_end` 携带 `node_id` + `kind`）
- [x] 新增 `dag` workflow 自动注册，`/api/planner/execute` 经过现有 Task 系统下发，可直接接 SSE 流
- [x] `GET /api/planner/skills_for_compile` 输出宿主 LLM 可用的 skill / tool 元信息（含 JSON 参数 schema）
- [x] 单元 + 集成测试覆盖 compile / validate / execute / topo / cycle / failure-mode
- [x] SDK `aaf.planner` + smoke test
- [x] 前端 `/planner` 页面（query → compile → 可视化 DAG → 一键 execute → 同步现有 task 流）

**核心模型**（`backend/planner/models.py`）

```python
NodeKind = Literal["llm", "tool", "skill", "memory.read", "memory.write"]
OnFailure = Literal["abort", "skip", "continue"]


class PlanNode(BaseModel):
    id: str                          # unique within DAG
    kind: NodeKind
    name: str = ""                   # tool name / skill name / "" for llm/memory
    args: dict[str, Any] = {}
    depends_on: list[str] = []
    description: str = ""
    expected_output: str = ""
    on_failure: OnFailure = "abort"
    retries: int = 0


class PlanDAG(BaseModel):
    plan_id: str
    query: str
    domain: str = ""
    nodes: list[PlanNode]
    rationale: str = ""
    estimated_steps: int = 0
    created_at: datetime
    llm_provider: str = ""
    extras: dict[str, Any] = {}
```

**Compiler 协议**（pseudo）

```python
class PlannerCompiler:
    def __init__(self, *, llm: LLMProvider | None, skill_host: SkillHost, tools: ToolRegistry): ...

    async def compile(self, *, query: str, domain: str = "",
                      hints: list[str] = (),
                      only_skills: list[str] | None = None,
                      only_tools: list[str] | None = None,
                      max_nodes: int = 30) -> PlanDAG:
        # 1. 列出可用 skill + tool 摘要 + JSON schema
        # 2. system prompt + user query, 要求 JSON 输出 PlanDAG
        # 3. 解析 / 校验 / 截断到 max_nodes
        # 4. 失败回退到 fallback()

    def fallback(self, *, query: str, domain: str = "") -> PlanDAG:
        # 单节点 memory.read + llm 总结
```

**Executor 关键不变量**

1. `PlanDAG` 必须先 `validate_plan(...).ok=True` 才进入 executor；router 入口强制再校一次
2. 同层并行度受 `max_parallel`（默认 = `min(layer_size, 4)`）限制
3. 节点失败：
   - `on_failure="abort"` → 整个 DAG 终止，下游 `skipped`
   - `on_failure="skip"` → 当前节点 `failed`，下游 `skipped`，其它无关节点继续
   - `on_failure="continue"` → 当前节点 `failed`，下游收到空 output 继续
4. 节点级 retry 使用既有 `tenacity` 风格指数退避
5. 输出：节点结果按 `node_id` 落到 ctx 的局部 map，下游通过 `${node_id.field}` 占位符在 `args` 取值（最小实现：在 args 里支持 `"$ref": "node_id"`）

**端点契约**

| 方法 | 路径 | Body | 返回 |
|---|---|---|---|
| `GET` | `/api/planner/skills_for_compile` | — | `{skills: [...], tools: [...]}` |
| `POST` | `/api/planner/compile` | `CompilePlanInput` | `PlanDAG` |
| `POST` | `/api/planner/validate` | `{plan: PlanDAG}` | `ValidatePlanResponse` |
| `POST` | `/api/planner/execute` | `{plan, params, dry_run}` | `{task_id: str}`（202 Accepted） |

`execute` 真正逻辑由新增的 `dag` workflow 承载（`backend/workflows/dag.py`），从 `payload["plan"]` 中拿 plan，调 `DAGExecutor.run()` 并 yield 标准 `Event`，因此前端 `useTaskStream(task_id)` 不需要任何改动即可可视化。

**Settings**

```env
aaf_planner_default_max_nodes=30
aaf_planner_default_retry=1
aaf_planner_max_parallel=4
```

---

#### M8 全局 DoD

- [x] M8.1 + M8.2 各自 DoD 全绿
- [x] `scripts/check_consistency.py` 通过（含两个新 router、`dag` workflow、`ProposalStore`）
- [x] `frontend tsc + vite build` 通过
- [x] 一致性：新增 `backend/proposals/AGENTS.md` + `backend/planner/AGENTS.md` + 更新 `backend/api/AGENTS.md` / `backend/workflows/AGENTS.md` / `frontend/AGENTS.md`
- [x] `docs/api-reference.md` + `docs/architecture.md` 同步（新增 5 / 6 章节）
- [x] SDK 两个新模块（`proposals` / `planner`）+ smoke test
- [x] 老 `Academic-Agent/学术&调研PLAN.md` 中 ADR-008 + DAG-compile 能力以"独立子系统"形式回归

---

### 20.10 P7 · 项目目录稿件（Bundle layout）

**起点**：用户的稿件并不是一段 Markdown 字符串 —— 真实形态是
`/Users/.../paper-dataagent-eval` 这样的项目目录：`overleaf/` + `plan/`
+ `experiments/` + `design.md` + 等等；最终交付件是 Overleaf 项目包。
P7 要求 AAF 用文件夹形式管理稿件、能读多种文件、最终能导出 Overleaf
版本，**同时不破坏 pre-P7 的单文档行为**。

**核心设计决策（已与用户确认）**：

| 决策 | 选择 | 理由 |
|---|---|---|
| 物理布局 | 同时支持 **copy** + **link** 两模式，UI 默认推荐 link | copy = 自包含可备份；link 与既有 git/Overleaf-sync 工作流共存 |
| 版本控制 | copy 模式默认 `bundle_versioning=true`（zip 快照）；link 模式默认 false | link 模式由用户的 git 接管，AAF 不重叠 |
| Overleaf 导出 | 自动识别 `bundle-root/overleaf/` 子目录 | 与 `paper-dataagent-eval` 既有约定一致 |
| 大小上限 | `MAX_FILE_MB=50` / `MAX_BUNDLE_MB=500` | 笔记本规模够用；超过用 `.env` 调 |
| 数据库迁移 | 不做迁移，新字段塞进现有 `meta` JSON 列 | 老数据无感升级 |

**Phase A · 后端 Bundle 内核**（commit `f6de725`）：

- `backend/manuscripts/models.py`：新增 `ManuscriptLayout` Literal、
  `ManuscriptFile` / `BundleManifest` / `WriteFileInput` / `BundleConvertInput`；
  `Manuscript` 模型加 `layout / bundle_link_path / bundle_versioning`。
- `backend/manuscripts/bundle_storage.py` (NEW)：路径安全 + 大小限制
  + `tree / read / write / delete / stat / init_for / remove_owned`。
  四道防御：拒绝绝对路径 / `..` 段 / 编码绕过 / 软链逃逸。
- `backend/core/errors.py`：`ManuscriptError` 家族（5 个新异常 → RFC 7807）。
- `backend/settings.py` + `.env.example`：3 个新配置（`AAF_MANUSCRIPT_ROOT` / `AAF_MANUSCRIPT_MAX_FILE_MB` / `AAF_MANUSCRIPT_MAX_BUNDLE_MB`）。
- `SqlManuscriptStore`：用 `meta` JSON round-trip 新字段（无 schema migration）。
- `backend/api/routers/manuscripts.py`：6 个新端点（`POST {id}/bundle`、
  `GET {id}/tree`、`{GET/PUT/POST/DELETE} {id}/files/{path:path}`）。
- 测试：unit (`test_bundle_storage.py`, +13) + integration
  (`test_app_manuscripts.py`, +12) → 728 passed。

**Phase B · 导入 / 导出**（commit `ffa8c9a`）：

- `BundleStorage`：`import_directory` / `import_zip` / `export_zip`
  / `detect_overleaf_subdir`。`import_zip` 防御 zip-slip + 软链 entry。
  写、解压、导入都流式 + 边算边检大小（projected = current − existing
  + entry_size），超限即抛 `ManuscriptBundleTooLarge`。
- 4 个新端点：
  - `POST /import-folder`（`{ local_path, mode: copy|link, ... }`）
  - `POST /import-zip`（multipart .zip）
  - `GET {id}/export-zip[?subdir=<path>|.|<空>]`（自动识别 overleaf）
  - `GET {id}/download/{path:path}`（原始字节流）
- 测试：+7 → 735 passed。覆盖 `paper-dataagent-eval` 形状的 fixture
  在 copy / link 双模式下的 round-trip + zip-slip 拒绝。

**Phase C · 前端**（commit `ebf8592`）：

- `types/api.ts`：扩 `Manuscript` + 新 DTO；`lib/manuscripts.ts` 加
  bundle API + URL helpers（仍走 `lib/api.ts`，保持机械门禁的 no-inline-fetch）。
- `i18n/locales/{en,zh}.json`：`manuscripts.*` + `bundle.*` 命名空间，
  i18next `_plural` 复数。
- `components/manuscripts/BundleExplorer.tsx` (NEW)：左侧文件树（按
  顶级目录分组、可过滤）+ 右侧 Monaco 编辑器（按扩展名挑语言：
  markdown / latex / bibtex / python / json / yaml / …）+ 工具栏
  （New file / Upload / Save / Delete / Download zip）。
- `PaperWriterPage`：`layout==="bundle"` 早 return 进 `BundleExplorer`，
  pre-P7 单文档路径完全不动。
- `ManuscriptsPage`：加 "Import folder" 模态 + "Import .zip" 按钮 +
  Bundle/Linked 徽章。
- 机械门禁：`tsc -b --noEmit` + `vite build` + 全栈 pytest 全绿。

**Phase D · 文档同步**：

- `docs/runtime-internals.zh.md` + `runtime-internals.md` 新增 §11
  (Manuscripts subsystem)，原 §11/§12/§13 顺延为 §12/§13/§14。
- `PLAN.md` 本节（§20.10）。
- `docs/architecture.md` 不需改 —— 子系统结构没变（仍是
  `backend/manuscripts/`），只是其内部加了 `bundle_storage.py`。

**P7 全局 DoD**：

- [x] 4 个 Phase 各自 commit + ruff/mypy/pytest/check_consistency 全绿
- [x] 总测试数：703 → **735 passed / 1 skipped**（+32）
- [x] `scripts/check_consistency.py` 通过（新端点 / 新文件树）
- [x] `tsc -b --noEmit` + `vite build`（dist 706 KB → 208 KB gzip）
- [x] 中英 i18n 复数 + `manuscripts.*` / `bundle.*` 命名空间齐全
- [x] `runtime-internals.{md,zh.md}` §11 同步落地
- [x] pre-P7 的 `layout="single"` 行为完全保留（旧测试一行没动）

### 20.11 P8 · Agent 自动写 Bundle + 提案 gate

> **目标**：让 RevisionWorkflow / WriteWorkflow 能直接读写 bundle 里的具体文件（例如 `overleaf/sections/intro.tex`），让 EvolverAgent 把 bundle 改动以 unified diff 的形式起草成 Proposal，并提供独立的 `apply-to-bundle` 端点给 admin 重放写入 —— 仍然把 `apply` 状态机和"实际写文件"解耦，控制更明确。

**5 个 Phase（每个一 commit、各自全绿门禁、不破坏 P7/single-doc）**：

- **Phase A · `BundleAdapter` 注入**（commit `a11708a`）
  - 新文件 `backend/workflows/bundle_adapter.py`：薄壳，绑定 `(Manuscript, BundleStorage)`，转发 `read_text` / `write_text` / `list_tree` / `stat` / `detect_overleaf_subdir`。
  - `BundleAdapter.maybe_build` 工厂：缺少 manuscript_id / 缺依赖 / 单文档 ⇒ 返回 `None`（纯 additive，不改 pre-P7 行为）。
  - `WorkflowContext` 加 `bundle: Any | None = None`。
  - `RunnerDeps` 加 `bundle_storage`，`execute_task` 自动注入 adapter；`backend/app.py` + `backend/workers/arq_worker.py` 同步装配。
  - 新单测 8 条覆盖 `maybe_build` 全分支 + read/write 往返 + 路径安全 passthrough。

- **Phase B · RevisionWorkflow bundle 目标文件**（commit `c2e16d7`）
  - workflow 本体不动；runner 在调 workflow 前把 `input.bundle_target` 指向的文件预读到 `input.text`；workflow 完成后把 `results.revised` 原子写回该文件，并发 `manuscript.bundle_write` SSE 事件给前端刷新文件树。
  - 新增 +6 测试：单测 3（happy / 无 target ⇒ no-op / 单文档路径不变）+ 集成 3（HTTP 全链路 / 无 target / 路径越权也不越界）。

- **Phase C1 · WriteWorkflow → bundle 路径**（commit `99b6ac9`）
  - bundle 分支扩展到 `write` workflow：`results.markdown` 写到 `bundle_target`。
  - 可选 `input.register_in_main`：在 `overleaf/main.tex` 里 `\input{<rel>}`，`\end{document}` 之前；幂等；缺 `\end{document}` 直接 skip；不创建 `main.tex`。
  - 新增 +5 测试覆盖幂等、关闭默认、无 target、单文档不变。

- **Phase C2 · EvolverAgent diff + `apply-to-bundle`**（commit `1c0c6aa`）
  - runner 把 `(manuscript_id, target, before, after, workflow)` 收成 `BundleChange` 传给 EvolverAgent。
  - EvolverAgent 的草稿被 `_enrich_with_bundle_change` 加上：unified diff（`difflib.unified_diff`）+ `target_paths` + `extras={manuscript_id, bundle_target, bundle_before, bundle_after, workflow}`。**diff 仅用于 UI 渲染；apply 用 `extras.bundle_after` 直接写**（不实现 diff applier）。
  - 新端点 `POST /api/proposals/{id}:apply-to-bundle`（admin / open mode）：
    - 校验 extras 完备 → 解析 manuscript（必须 `layout=="bundle"`）
    - linked + `risk_level != "low"` ⇒ 403
    - 比 `extras.bundle_before` 与磁盘当前内容 ⇒ 不一致 + 没 `force` ⇒ 409
    - 通过则 `BundleStorage.write_text` + `store.patch(extras += applied_to_bundle_at/by/size)`，**`status` 不变**
  - 新增 +7 测试：3 evolver 单测（diff 形态 / 无 bundle change ⇒ legacy / 新文件 diff = 纯加号）+ 4 集成（happy chain / 无 payload ⇒ 400 / force 覆盖 staleness / linked + high-risk ⇒ 403）。

- **Phase D · 前端**（commits `0ff551d` D1, `8640269` D2, `1e1ede7` D3）
  - **D1 ProposalsPage**：bundle proposal 卡片（target file / manuscript / last-applied）+ "Apply to bundle" + "Force" 按钮（独立于 `Apply` 状态键，`Force` 走 `confirm()`）；header bundle badge；新 `proposalsApi.applyToBundle()`；i18n `proposals.actions.applyToBundle*` / `proposals.bundle.*`。
  - **D2 RevisionPage**：把 RevisionStudio 拆成 dispatcher + `SingleRevisionStudio`（旧版本链）+ `BundleRevisionStudio`（target file picker / before-after diff），单文档完全不变。i18n `revision.bundle.*`。
  - **D3 BundleExplorer**：编辑器加 "Revise this file" 深链按钮，跳到 `RevisionPage?manuscript=…&bundle_target=…`；非文本扩展 disabled；i18n `bundle.reviseThisFile*`。

- **Phase E · 文档同步**（本 commit）
  - `runtime-internals.{md,zh.md}` 新增 §11.8 "Bundle 自动写入与提案"（call graph + 不变量表 + diff/apply payload 解释 + 前端 surface 表）。
  - PLAN.md §20.11（本节）。
  - `api-reference.md` 加 `:apply-to-bundle` 端点 + 新 `Proposal.extras.bundle_*` 字段说明。

**关键设计决定**（用户已确认）：
- workflow 不感知 layout，所有分支在 runner 里 → 减小 workflow 改动半径。
- proposal 上同时存 unified diff（人类阅读）+ `extras.bundle_after`（机器写入）→ 既保留"diff 是契约"语义又免实现 diff applier。
- `apply` 与 `apply-to-bundle` 分离 → 状态机和文件系统操作不耦合，admin 控制更明确。
- linked bundle + 非 low risk ⇒ 拒绝 → 用户管理的外部目录不被 agent 自动改写。

**验收**：
- [x] 5 个 Phase 各自 commit + ruff/mypy/pytest/tsc/consistency 全绿
- [x] 总测试数：735 → **762 passed / 1 skipped**（+27）
- [x] `scripts/check_consistency.py` 通过（新端点 / 新 i18n key / 新 router 测试）
- [x] `tsc -b --noEmit` 通过（前端 ProposalsPage / RevisionPage / BundleExplorer 双语完整）
- [x] pre-P7/P8-bundle 之外的 single-doc 路径行为完全保留（旧测试一行没改逻辑）
- [x] linked bundle 安全策略：高风险拒绝 + 强制写需 admin + force=true

---

### 20.12 P12 · UI 收敛 + 纵深防护 + 版本可观测

**目标**：把"前后端能用"提升到"日常用着像 cursor"。问题来自真实使用：
1. P10 之后仍偶发 `BrokenPipeError`（用户：「彻底解决」）。
2. 用户看不到自己当前跑的是哪个版本的后端 → 无法判断修复有没有真生效。
3. 顶栏长出了 13 个 sidebar 项；用户的真实心智只有两条：**调研** vs. **写作**。

#### Phase 0 · 仓库卫生（commits `1f5caba`, `3c9808e`, `24677aa`, `a5725ff`）
- BundleExplorer 增加递归文件树（同时导出 `BundleFileTree`，PaperChat 复用）。
- 探索文档归档到 `docs/exploration/2026-05-10-manuscripts/` + `INDEX.md`。
- `.gitignore` 加 `data/manuscripts/` / `data/proposals/` / `data/*.db*` / `data/knowledge/*.yaml`；`data/aaf.db` `git rm --cached`。
- 顺手修了 P11 遗留的 2 个 tsc 报错（`PageHeader.description: ReactNode`、`StreamEvent.seq` 不存在）。

#### Phase 1 · BrokenPipe 纵深防护（commit `7c15f4f`）
四层防御 + `InfrastructureError` 类型化：
1. **adapter 层**（P9/P10）：`OpenAICompatProvider` / `AnthropicProvider` 把 `OSError` → `LLMStreamError` / `LLMAPIError`。
2. **memory snapshot 层**（P10）：`MemoryBundle.snapshot` 每个 store 独立 try/except，单点失败不污染整体。
3. **workflow stage 层**（新）：
   - `_recall` / `_reflect` 改用新 `BaseWorkflow.stage_soft()`：失败 → 发 `TASK_WARNING`（前端琥珀色横幅）+ 返回 `None`，任务继续。
   - 适用于：`consult` / `revision` / `write` / `research` / `demo`。
4. **stage() 兜底层**（新）：`BaseWorkflow.stage()` 捕获所有逃逸的 `OSError` 包成 `InfrastructureError`（`http_status=502`, `retryable=True`, 携带原始 `source_type`）再 raise；前后端拿到的都是同一个 typed error。

新增 `EventType.TASK_WARNING` + `EventTimeline` 琥珀色渲染 + 5 个 stage 单测 + 4 个 workflow 集成测（每个 workflow 各一）。

#### Phase 2 · 版本可观测（commit `24de8f7`）
- `backend/core/build_info.py`：启动时 `subprocess.run("git ...")` 抓 SHA / dirty / commit ts / subject；失败回落到 env vars 或 `"unknown"`。**绝不抛**。
- `/api/version` 加 `build` 字段；`app.lifespan` 启动日志打 build banner。
- 前端 `VersionBadge`（TopBar 右侧）：短 SHA + dirty 琥珀点 + hover 完整 commit 信息。

#### Phase 3 · IA 收敛 / Workbench（commits `8e7d7f3`, `744638a`）
- **新布局原语** `WorkbenchShell` + `useWorkbenchStore`：三栏（文件 / 编辑器 / 对话），各栏可拖宽、可隐藏，状态持久化到 `aaf.workbench.layout`。**手写**而非依赖 `react-resizable-panels`（aaf-project-conventions §4：能 < 100 行 std 代码做的就别加 dep）。
- **路由收敛**：`/workbench/:id` 为主，`/chat/:id` 保留 alias。`PaperChatPage` 内部主视图换成 `WorkbenchShell`：左 `BundleFileTree` · 中 Monaco preview（语言自动识别）· 右原 chat thread + composer。
- **研究控制台改 2-tab**（URL 同步：`?tab=research|writing`）：
  - Tab 1 调研：原表单 + SSE 时间线（行为不变）。
  - Tab 2 写作：列出所有稿件 → click 直接进 Workbench。替代独立的「稿件」sidebar 项。
- **sidebar 从 13 → 5 + 6 分组**：
  - 主组（日常）：Dashboard / Research Console / Workbench / Tasks / Settings。
  - 「更多」组（高级）：Library / Memory / Proposals / Skills / MCP / Planner。
  - 移除主导航但保留路由：`/papers` `/chat` `/revision`（书签仍可用）。

**关键设计决定**：
- `stage_soft` 与 `stage` 并存，**调用方显式选择**降级语义 → 不会把硬错误偷偷吞掉。
- `InfrastructureError` 保留 `source_type` 字段 → 监控可以按底层异常分类。
- IA mantra："one front-door per workflow" — 未来再加新写作 surface，先想能不能塞到 `/workbench` 里或者 `/research?tab=` 里。
- VersionBadge 即使 git 不可用也必须渲染 → 启动可观测优先级高于精度。

**验收**：
- [x] 4 个 commit 各自机械门绿：`make check` / `ruff` / `mypy` / `pytest` / `tsc -b --noEmit` / i18n parity / consistency。
- [x] 总测试数：762 → **778+ passed**（+10 stage soft-fail 单测 + 4 workflow recall-fail 集成测 + build_info 单测 + 集成）。
- [x] i18n 463 / 463（en/zh parity，含 `workbench.*` / `nav.workbench` / `nav.sectionMore` / `research.tabs.*` / `research.writing.*` / `app.build*`）。
- [x] 旧路由全保留：`/chat/:id` / `/papers` / `/revision` / `/papers/:id` 均仍可访问。
- [x] WorkbenchShell 状态持久化通过 `persist({ name: "aaf.workbench.layout" })` 验证。

**未做**（留到下一轮）：
- WorkbenchPage 文件名仍是 `PaperChatPage.tsx`，重命名会让 diff 爆炸；下次 IA 调整时一起重构。
- `RevisionPage` 的批量审稿表单未并入 Workbench：它的"reviewer-comments JSON 批处理"结构和 chat 流不同，强行合并会失功能。

---

### 20.13 P13 · Skill 图谱 + 记忆库手动 CRUD

**目标**：把 P12 之后用户报告的两个真实痛点收口。
1. **写作面板 hook 报错** — P12.3b refactor 把一个 `useMemo` 放到了两个 early-return 之后，React 看到不同渲染路径有不同 hook 数 → `Rendered fewer hooks than expected`（fix commit `a75502e`）。
2. **Skill 是 DAG，需要图形化管理** — 用户要可视化看 + 增删改 + 拖拽组合。
3. **记忆库（论文/案例/知识库/材料）需要手动 CRUD** + 论文卡片要有 `大方向-小方向` 归属 + 论文链接。

**Phase 拆解**：

#### Phase A · PaperCard 加字段（commit `a8e5e75`）
- `backend.memory.models.PaperCard` 加 3 个 Optional 字段：`url`、`field_major`、`field_minor`。
- `search_text()` 将 `field_major / field_minor` 一并纳入，按方向召回论文也能命中。
- **零迁移**：Pydantic Optional 默认 None，旧 YAML 文件缺这三个 key 照样 load（pin 在 `test_yaml_reads_legacy_card_without_new_fields`）。
- `CreatePaperCardInput` / `UpdatePaperCardInput` 同步加字段；`frontend/types/api.ts` 原子镜像（aaf-api-contract）。
- 测试：+4 单测 +2 集成测；总 17/17 + 17/17 passed。

#### Phase B · `/api/skills/graph` 端点（commit `2efbb7c`）
- 新增 `GET /api/skills/graph` → `{nodes, edges, dangling, cycles, generation}`。
- 节点 = 已安装 skill（含 disabled），边 = `compatibility.upstream / .downstream` 聚合。
- 边的 `declared_by` ∈ `{"source", "target", "both"}` — 两侧都声明则 dedupe 成单条 `both`。
- Tarjan SCC 检测环，UI 用琥珀色高亮但**不拒绝返回**。
- 自引用（`downstream: same-name`）静默丢弃，不变成 self-loop。
- **路由顺序至关重要**：`/graph` 必须在 `/{name}` **之前**注册，否则会被参数路由吞掉 → `test_graph_route_takes_precedence_over_name_route` 即是该 regression guard。
- 测试：+15 单测（含 4 个 cycle 检测、3 个 declared_by 合并、确定性排序）+ 3 集成测。

**Drive-by fix**：之前的 StrReplace 把 `DryRunResponse` 截断到 3 个字段，本次顺手恢复全部 6 字段并 pin 在 `git show HEAD` 对照。

#### Phase C · MemoryPage Knowledge 手动 CRUD（commit `2f8d9ec`）
- 新增 `knowledgeApi.createPaper` / `updatePaper`（thin POST/PATCH 包装），`deletePaper` 已有。
- 新组件 `components/memory/PaperFormDrawer.tsx`（~360 行）：12 字段表单的 modal panel，复用 OnboardingDialog 同款 `fixed inset-0 + bg-black/40` 样式，**不**新加 Dialog primitive。
- `MemoryPage.KnowledgeTab` 增加：
  - 顶栏 `+ 新建` + 原 `导入论文` 并列；ingest 与 manual 通道职责分离（ingest 还会写 vector/episodic）。
  - 每行 `✏ 编辑` `🗑 删除`（删除走 `window.confirm`，撤销不了的操作配真正中断式确认）。
  - `TaxonomyFilter`：基于已加载卡片客户端聚合 `field_major / field_minor`，pills with counts + 二级展开。
  - 卡片行渲染 `field_major / field_minor` badge + `url` 外链图标。
- Clear-field 语义沿用既有约定：`""` 清空（`exclude_none=True` 把 `null` 过滤掉）；前端构造 payload 时空字符串 → `null`。
- i18n：+36 keys（`memory.toast.*` / `memory.knowledge.*` / `memory.paperForm.*`），en/zh 完全对等。

**未做**（明确写出避免回归）：
- 案例（episodic）/材料（documents）的 CRUD UI 没做：后端早就有 POST/PATCH/DELETE，但本轮只先满足"论文卡片"这条最重要的线，避免一次推太大。下一轮做。

#### Phase D · SkillsGraphView（commit `7854d1a`）
- 新增 deps：`@xyflow/react@12`、`dagre@0.8`、`@types/dagre` — **本轮唯一一次破例**。理由写在 commit body 和组件 docstring：
  - pan / zoom / minimap / layered DAG 手写 >1500 行，远超 `aaf-project-conventions §4` 的 100 行阈值。
  - xyflow 是 React node-editor 的事实标准，包体本身合理（~+180KB gzip）。
- 新组件 `components/skills/SkillsGraphView.tsx`（~290 行）：
  - `applyLayout()` 纯函数：dagre LR layout，节点按 domain 上色（writing/revision/rebuttal/research/survey/meta）。
  - 边样式：`declared_by="both"` emerald `↔` / 单边 slate-gray `→` / cycle 上 animated 琥珀。
  - dangling 节点 dashed 边 + 透明背景，"破链"清晰可见。
  - 点击节点 → 在父级（SkillsPage）触发 `handleSelect(name)` → 现有 SkillDetailPanel 弹出。
  - MiniMap 节点颜色按同样的 domain palette，远视图也能定位。
- `SkillsPage` 顶栏新增 `ViewToggle` 段控制器（List/Graph），状态绑 URL `?view=graph` —— 刷新保持视图、bookmark 可分享。
- **关键决定 · 不做拖拽建边**：edges 的真源是各 SKILL.md 的 `compatibility` 字段；graph 改边等于再加一条改 frontmatter 的 code path，会和 body editor 抢权。Graph 保持 read-mostly，所有编辑回归现有 body-md drawer。

**未做**（避免范围蔓延）：
- 节点拖拽布局 + 持久化用户拖出的图形：dagre 自动布局已经够看，加自定义布局意味着要存"per-skill (x,y)"到某个新 store，本轮不开。
- "Skill 拖拽组合"（拖一个上 skill 出来 = 调一个 chained workflow）：这是 Planner 的能力域，不该绑死在 skills page。

**关键设计决定**：
- 三个新功能彼此**正交**：PaperCard 字段（A）、Skill 图（B+D）、Memory CRUD UI（C）—— 拆 4 commit 而非揉成 1，回滚粒度合理。
- A 用 Pydantic Optional + "零迁移"，把"add field requires script"这条惯性砍掉。
- B 暴露的 graph 不光给 UI 用；后续 Planner 编排时也能直接消费，不必各自解析 SKILL.md。
- D 是本轮唯一加 dep 的地方，commit body 里把"为什么破例"写到无可争辩 → 下次有类似诱惑可以反向引用。
- 写作面板 hooks bug 单独做一个 commit（`a75502e`）+ 行内注释，防止下个 agent 把那个 `useMemo` 再挪回 early-return 之后。

**验收**：
- [x] 5 个 commit 各自机械门绿：`uv run pytest` / `ruff` / `mypy` / `tsc -b --noEmit` / `npm run build` / `scripts/check_consistency.py` / i18n parity。
- [x] 后端新增 23 个 test（17 unit + 6 integration），现有 testset 全绿。
- [x] i18n 完全对等（en-only=0, zh-only=0），新增 ~49 个 key 全部翻译。
- [x] 写作面板 `Rendered fewer hooks` 报错已修复（hoist `useMemo` + 行内注释 + commit message 解释根因）。
- [x] Skills page `?view=graph` 直接进入图谱，节点 click 自然衔接现有 detail drawer。
- [x] Memory page Knowledge tab 可一键新建 / 编辑 / 删除论文卡片，URL + 大方向-小方向归属可见、可筛选。

---

### 20.14 P14 · Episodic / Documents CRUD + Skill 拖拽建删边

**目标**：兑现 P13 显式记下的"未做"清单 — 让 episodic（案例）/ documents（材料/书籍）也走完 CRUD 链，并把 SkillsGraphView 从只读升到无代码 DAG 编辑器。同时 drive-by 修复一个由旁路 agent 在工作树里留下的 `_build_graph` 改动（识别它是 bugfix → 补测试 → 独立 commit；详见 commit `e7baa5e`）。

**记忆系统三件套的语义边界**（这次先把概念说死，避免下次再被问"和论文什么关系"）：

| 形态 | 是什么 | 与 PaperCard 关系 | 存储 |
|---|---|---|---|
| **PaperCard** | 你**结构化读完一篇论文**之后写下的卡片：title/abstract/method/findings + P13.A 加的 url / field_major / field_minor | — | `MemoryBundle.knowledge`（YAML per card） |
| **Reflection (episodic)** | Agent **在 workflow run 中自己写下**的备注，三种 type：`reflection`/`observation`/`insight`。绑定 `session_id` + `source_run_id` + `user_id` 作为来源指纹 | 完全正交 — 不指向某篇论文，而是指向某次 run / session | SQL `episodic` 表（in-memory + sqlite/postgres 双实现） |
| **KnowledgeDocument (documents)** | 用户**扔进来的任意 blob**：PDF/Markdown/Note/网页。会按 chunk 切片，每个 chunk 同时进入 vector store（`metadata.kind="doc_chunk"`），按 RAG 召回 | 完全正交 — PaperCard 是"读后笔记"，Document 是"原始材料按 chunk 检索" | SQL `document` + `doc_chunk` 表 + vector store 联动 |

三者**平行存在**于 MemoryBundle，UI 在 MemoryPage 顶部 tab 也按这个边界拆。

**Phase 拆解**（6 commit + 1 drive-by fix = 7）：

#### Drive-by · 顶层 `downstream_skills` 字段被 _build_graph 拾取（commit `e7baa5e`）
- 工作树里发现一个未提交的 `_build_graph` 改动 + 8 份未追踪的 AI 长文档（同会话之外的 agent 留下的）。
- 改动本身是真 bugfix：9 个 in-tree skill（writing-core / peer-review / paper-orchestration / brainstorming-research / evidence-driven-writing / experiment-results-planning / writing-chapters / prompts-collection / verification）用顶层 `downstream_skills:` 而不是嵌套 `compatibility.downstream:`，原 `_build_graph` 漏读 → 这 9 个 skill 的边在图里**不可见**。
- 处理：保留改动 + 补 2 个 unit（`test_graph_picks_up_top_level_downstream_skills_field` / `test_graph_top_level_field_coexists_with_compatibility_block`）+ 独立 commit；同时清掉 8 份 stray 文档（按 `aaf-project-conventions §5` 的"探索文档应归档而非堆 repo 根"约定）。

#### Phase A · Episodic CRUD（commit `9aff74e`）
- `EpisodicStore` Protocol 加 `get(id)` / `update(id, *, type, content, tags)` / `delete(id)` / `delete_by(*, session_id, source_run_id)`。`InMemoryEpisodicStore` + `SqlEpisodicStore` 双实现保持 protocol parity。
- `update` **故意排除** `user_id` / `session_id` / `source_run_id` / `id` / `created_at`：这五个字段是 provenance marker，被 rollback-by-run + session 时间线视图依赖，重写它们 = 静默破坏这两个调用方。
- `delete_by` **AND-语义**：两个 facet 都给则只删两者都匹配的行（OR 会让 `session_id="s1", source_run_id="run-X"` 不小心夷平整 session）。空 facet = no-op，路由层 400。
- `PATCH /api/memory/reflections/{id}`（`extra="forbid"` → 试图 spoof `user_id` 直接 422）/ `DELETE /api/memory/reflections/{id}`（再次 delete = 404，不是 204；故意泄露存在性，让 admin 脚本可调试）/ `DELETE /api/memory/reflections?session_id=&source_run_id=`（双重 0-filter 防御：路由层 400 + store 层 no-op）。
- 测试：+12 in-memory unit + 7 SQL parity unit + 6 HTTP integration = +25。

#### Phase B · Documents 元数据 PATCH（commit `46cf1f6`）
- `DocumentStore` Protocol 加 `update_metadata(doc_id, *, title, summary, tags, source_kind, source_uri)`。**`raw_text` 不在编辑面**：改 raw_text 不重切 chunk = 持久化文本和 vector 嵌入静默 desync，每次 search_chunks 都在撒谎 → reindex 才是改正文的官方路径。
- 双实现都做：title/tags/source_kind 改了 → re-emit chunk-level vector metadata（`vector.add` 在 chunk_id 上是 idempotent overwrite，安全重放）；只改 summary → **跳过**向量 pass（防止"便宜编辑路径"被偷偷变成 O(N chunks)；用 monkeypatch 计 `add()` 调用数 pin 死）。
- `PATCH /api/documents/{doc_id}`，`extra="forbid"` 防 `raw_text` 偷渡。
- 测试：+6 unit + 5 integration = +11。

#### Phase C · Skill `:edges` 端点（commit `a72d1ee`）
- 新端点 `POST /api/skills/{name}:edges`，body `{add: [{kind, target}], remove: [...]}`，response `{name, body_md, added, removed, skipped_dup, skipped_missing, warnings}`。
- 算法核心 `_apply_edge_ops` 是**纯函数**（SKILL.md text → new text + report），单测 18 个跑 <200ms：覆盖 add 单/多边、自引用静默丢弃、`coerce_name_list` 字符串/列表/垃圾值容错、空 compat 自动 `del meta["compatibility"]`、单值 scalar / 多值 sorted list、idempotency。
- ADD 永远走 canonical `compatibility.{kind}`；REMOVE **同时**搜 `compatibility.*` 和 legacy 顶层 `downstream_skills`（兼容上面 9 个 skill）。
- `SkillAdmin.update_edges`：read SKILL.md → apply pure → `_validate_skill_md` → `shutil.copyfile` 备份 → `tmp.replace()` 原子写 → reload → 失败回滚。disabled skill 也允许编辑（不 reload，对称于 body editor）。
- **删除 "both" edge 需要两次调用**（一边一次），后端**故意不级联**：保持 UI 控制谁声明谁这条 invariant。pin 在 integration `test_edges_endpoint_two_calls_remove_both_sides`。
- **Trade-off**：YAML round-trip 通过 PyYAML 走，`#` 注释会丢。`_frontmatter_has_inline_comments` 启发式探测原文是否有注释 → 写入 `report.warnings` → 前端 toast.warning（一次性提示，不阻塞）。决意不引 ruamel.yaml 来"漂亮地保留注释"，符合 §22 dep 政策。
- 测试：+18 unit + 7 integration = +25。

#### Phase D · ReflectionsTab CRUD UI（commit `a301435`）
- `MemoryPage.ReflectionsTab` 加：filter 行（type / session_id / run_id 子串）+ 行内 `Pencil` / `Trash2` + 顶部"批量删除"红钮。
- `ReflectionEditDialog` 弹窗复用 PaperFormDrawer 的 `fixed inset-0` + ESC-close 模式；provenance 字段不进表单（前后端契约一致）。
- 批量删除前端预防卫：两个 filter 都为空时直接 `toast.error` 拒绝，不发请求 — defence in depth 配合后端 400。
- run_id filter 是**客户端子串过滤**（已经 narrow 到 ≤200 行的 list 上 JS filter 完事）—— backend list 端点只支持 `session_id` 一个 facet，加 `run_id` 要 schema 改动；为一个过滤器不值。
- i18n +25 keys, en/zh parity。

#### Phase E · MemoryPage Documents tab（commit `2d2f09e`）
- 新 `DocumentsTab`（list + edit metadata + delete + reindex）+ `DocumentEditDialog`（5 字段：title/summary/tags/source_kind/source_uri）。
- **不在 MemoryPage 内做 ingest**：`/library` 页面的 ingest 表单已经处理 file upload + source_kind 自动检测 + chunk 参数；这边镜像一份 = 重复 ~150 行 UI。改用 "Add document" 按钮跳转 `/library`，create path 落在唯一入口。
- Reindex 按钮就是直接调既有 `:reindex` 端点 — 用户真改了源文件想重切，不必离开 tab。
- subtitle 用一句话讲清和 PaperCard 的语义边界（"orthogonal to knowledge cards — chunk-level RAG vs structured reading note"），降低首次用户的归类困惑。
- i18n +30 keys。

#### Phase F · SkillsGraphView 拖拽建删边（commit `2fac161`）
- **反转 P13.D 的"不做拖拽建边"决定**：当时的理由是"会和 body editor 抢权 / 两条 mutation path 漂移"；P14.C 给出**专用** `:edges` 端点后，两条 path 操作的是**互斥**的文件切片（frontmatter vs body），漂移风险消失。
- `SkillsGraphView` 加 prop `onAddEdge` / `onRemoveEdge` / `busy` — 两个回调都给才进"edit mode"，都不给保持 read-only（向前兼容任何只读嵌入）。
- xyflow `nodesConnectable: true`，`busy=true` 期间禁用拖拽（不让用户 queue 多次 drag）。Self-loop / dup edge 客户端预防卫，省掉无意义 round trip。
- 点边 → 浮动"Delete A → B"按钮（右上角）+ Delete/Backspace 键盘快捷键 → 调 `onRemoveEdge`。tablet/touchpad 友好。
- `SkillsPage` 包两个 mutation：`addEdge` 一次调用；`removeEdge` 根据 `declared_by` 决定 1 / 2 个并发 `Promise.all` 调用 — UI 层负责"两边都删"的协调。
- mutations **故意不 optimistic**：YAML 重写 + reload ~10ms 服务端，乐观更新的 UX 收益不抵维护客户端 YAML 镜像的复杂度。
- 后端 `warnings`（如注释丢失）走 `toast.warning` 立刻可见，不让用户事后才发现。
- i18n +7 keys（editableHint / editableBadge / deleteEdge + 4 个 toast）。

**关键设计决定**：
- 三件套 + skill graph 编辑彻底正交 → 7 commit 各管一段，回滚单元清晰。下游 agent 想撤"拖拽编辑"只需 revert P14.F；其它五件依然成立。
- Episodic / Documents 编辑面**故意都不暴露 provenance / raw_text**。这是 store 层 + HTTP 层双重契约（`extra="forbid"` + `update()` 函数签名都不接），不是"前端忘了暴露"。
- Skill `:edges` 不级联 "both" 删除是 invariant，不是 missing feature — pin 在测试。
- 决意不引 `ruamel.yaml`：注释丢失用 `warnings` 暴露给 UI 是更好的契约（让用户知道 trade-off），而不是为一个微特性多扛一个 dep。

**验收**：
- [x] 7 个 commit 各自机械门绿：`uv run pytest backend` / `ruff` / `mypy` / `tsc --noEmit` / `vite build` / `scripts/check_consistency.py` / i18n parity。
- [x] 后端测试从 836 → **902 passed**（+66 = 25 episodic + 11 docs + 25 skill edges + 5 misc 修复 / drive-by）。
- [x] i18n 完全对等（en-only=0, zh-only=0），新增 ~70 个 key 全部 en/zh 翻译。
- [x] MemoryPage 现在三个记忆面板（Knowledge / Documents / Reflections）都支持 list + create + edit + delete + 必要的 filter。
- [x] SkillsGraphView 在 `?view=graph` 下进入"edit mode"badge，拖拽和键盘删除均可用，"both"-declared 边的双侧协调由 UI 负责（已有测试覆盖）。
- [x] 8 份 stray AI 文档清理完毕，repo 根目录恢复干净。

---

## 21. 验收、测试、评估

### 21.1 单元测试

- `backend/tests/unit/` 覆盖所有 core 模块
- 关键断言：skill loader 能正确解析 frontmatter；matcher 召回率；injector 不超 token；executor 超时强杀有效；Evolver 的 YAML 写入幂等

### 21.2 集成测试

- `backend/tests/integration/` 用 `mock.py` LLM provider 跑完整 workflow
- 每个 workflow 至少 2 个 case：成功路径 + 失败路径

### 21.3 Skill 自测试

每个 L1 skill 的 `evals/` 目录包含 YAML 输入与预期输出，`aaf skill test <name>` 批量运行。

### 21.4 端到端测试（E2E）

- Playwright 跑前端关键流程：新建调研 → 看到结果 → 查记忆
- 每次 release 前必跑

### 21.5 性能基线

- 冷启动：后端 < 3s；skill loader 首次扫描 < 1s（15 skill 内）
- 单次 research workflow（不含 LLM）编排开销 < 200ms
- 内存：空载 < 300MB

### 21.6 质量评估

- 复用 `Academic-Agent/scripts/self_test.py` → 迁到 `backend/tests/benchmark/`
- 对比指标：旧框架 vs 新框架在相同 benchmark 上的平均 score / recall@5

---

## 22. 技术选型与版本

### 22.1 锁定版本（最低版本）

| 类别 | 技术 | 版本 |
|---|---|---|
| 语言 | Python | 3.11+ |
| 语言 | Node.js | 20.x LTS |
| 包管理（py） | uv | 0.5+ |
| 包管理（js） | pnpm | 9.x |
| 后端框架 | FastAPI | 0.115+ |
| 后端框架 | Pydantic | 2.9+ |
| 异步任务 | ARQ | 0.26+ |
| 编排框架 | **自研**（§10） | — |
| 前端框架 | React | 19+ |
| 前端构建 | Vite | 5.x |
| 前端样式 | Tailwind CSS | 4.x |
| 前端 UI | shadcn/ui | latest（组件源码拷到项目内） |
| 路由 | React Router | 7.x |
| UI 状态 | Zustand | 5.x |
| 服务端状态 | TanStack Query | 5.x |
| 表单 | React Hook Form + Zod | 7.x / 3.x |
| 编辑器 | Monaco Editor (`@monaco-editor/react`) | 0.52+ |
| 富文本 | Tiptap (`@tiptap/react`) | 2.8+ |
| 数据库 | PostgreSQL | 16 |
| 缓存 / 队列 | Redis | 7.2 |
| 向量库 | ChromaDB | 0.5+ |
| 对象存储 | MinIO | RELEASE.2024 |
| Web 服务器 | Nginx | 1.25 |
| LLM SDK | openai | 1.50+ |
| LLM SDK | anthropic | 0.40+ |

### 22.2 推荐而非强制的库

**前端**：
- `@microsoft/fetch-event-source` 2+（可靠 SSE 客户端，支持 POST/headers/重连）
- `echarts-for-react` 3+
- `markdown-it` 14+ / `react-markdown` 9+（任选其一，优先 `markdown-it` 与后端共用预设）
- `KaTeX` 0.16+
- `@tanstack/react-virtual` 3+（长列表虚拟滚动）
- `dnd-kit` 6+（大纲/卡片拖拽）
- `react-i18next` 15+
- `sonner` 1+（Toast，shadcn 默认）
- `react-diff-viewer-continued` 3+

**后端**：
- `SQLAlchemy` 2.x + `Alembic` 1.13+
- `pdfplumber` 0.11+ / `pypdf` 5+
- `feedparser` 6+

### 22.3 运行时依赖矩阵

| 场景 | 必需外部服务 |
|---|---|
| 最小跑通 | Postgres + Redis + 任一 LLM |
| 完整功能 | 上述 + ChromaDB + MinIO |
| 离线研发 | 上述 + Ollama/vLLM |

---

## 23. 附录

### 23.1 SKILL.md frontmatter 完整 Schema

```yaml
---
# 必填
name: string                     # 目录名，小写连字符
description: string              # 何时使用，LLM 读取

# 推荐
domain: research | writing | revision | rebuttal | survey | meta
triggers: [string]               # 字面匹配关键词
version: semver

# 兼容性
compatibility:
  requires: [string]             # 例: ["python>=3.11", "tectonic"]
  os: [linux, darwin]            # 可选

# 行为开关
network: none | optional | required   # executor 是否允许联网
max_duration_s: integer               # 覆盖默认 120s
exclusive: boolean                    # 不与其他互斥 skill 同时命中

# 元数据
author: string
tags: [string]
---

# Markdown 正文
...
```

### 23.2 Rule frontmatter Schema

```yaml
---
name: string                     # 必填
description: string              # 必填
scope: [planner, executor, evaluator, evolver] | all
priority: integer                # 默认 0
enforcement: prompt | hook       # 默认 prompt
hook: string                     # enforcement=hook 时必填，点分 import 路径
---

# Markdown 正文：规则的详细描述
```

### 23.3 L3 Heuristic YAML Schema

```yaml
id: string                       # 12-hex
name: string
description: string
domain: research|writing|revision|rebuttal|survey
trigger_pattern: string          # 关键词逗号分隔
strategy:
  planning_hints: string
  search_tips: string
  evaluation_criteria: string
source_query: string
source_verdict: pass | fail
source_run_id: string
success_count: integer
failure_count: integer
frozen: boolean
created_at: datetime
updated_at: datetime
```

### 23.4 Postgres 主要表

```sql
-- 用户
CREATE TABLE users (
  id UUID PRIMARY KEY,
  username TEXT UNIQUE NOT NULL,
  email TEXT UNIQUE,
  password_hash TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 会话
CREATE TABLE sessions (
  id UUID PRIMARY KEY,
  user_id UUID REFERENCES users(id),
  title TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ
);

-- 消息
CREATE TABLE messages (
  id UUID PRIMARY KEY,
  session_id UUID REFERENCES sessions(id),
  role TEXT,
  content JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 任务
CREATE TABLE tasks (
  id TEXT PRIMARY KEY,                 -- "t_<uuid>"
  user_id UUID REFERENCES users(id),
  session_id UUID,
  workflow TEXT NOT NULL,              -- research / write / ...
  status TEXT NOT NULL,                -- queued/running/finished/error/cancelled
  input JSONB,
  output JSONB,
  trace JSONB,                         -- 事件流
  llm_provider TEXT,
  llm_model TEXT,
  score FLOAT,
  verdict TEXT,
  duration_ms INT,
  token_usage JSONB,
  cost_usd FLOAT,
  error JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  finished_at TIMESTAMPTZ
);

-- LLM 调用日志
CREATE TABLE llm_log (
  id UUID PRIMARY KEY,
  task_id TEXT REFERENCES tasks(id),
  provider TEXT,
  model TEXT,
  prompt_tokens INT,
  completion_tokens INT,
  cost_usd FLOAT,
  duration_ms INT,
  prompt JSONB,
  response JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 审计
CREATE TABLE audit_log (
  id UUID PRIMARY KEY,
  user_id UUID,
  action TEXT,
  target TEXT,
  detail JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Episodic（反思）
CREATE TABLE episodic (
  id UUID PRIMARY KEY,
  user_id UUID,
  session_id UUID,
  type TEXT,            -- reflection / observation / insight
  content TEXT,
  embedding VECTOR(1536), -- 可选 pgvector
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 23.5 SSE 事件完整类型表

| event | data 字段 |
|---|---|
| `task.created` | task_id, workflow, input |
| `task.stage_start` | task_id, stage |
| `task.stage_end` | task_id, stage, summary |
| `task.llm_request` | task_id, provider, model, tokens |
| `task.llm_token` | task_id, delta |
| `task.llm_response` | task_id, content, tokens |
| `task.tool_call` | task_id, tool, args |
| `task.tool_result` | task_id, ok, duration_ms, preview |
| `task.memory_write` | task_id, store, id |
| `task.evaluation` | task_id, verdict, score |
| `task.evolution` | task_id, skill_id, action (add/bump/freeze) |
| `task.finished` | task_id, output_url |
| `task.error` | task_id, code, message |
| `task.cancelled` | task_id |

### 23.6 错误码表

| Code | HTTP | 含义 |
|---|---|---|
| `LLM_TIMEOUT` | 504 | LLM 调用超时 |
| `LLM_RATE_LIMIT` | 429 | 上游限流 |
| `LLM_API_ERROR` | 502 | 上游返回错误 |
| `SKILL_NOT_FOUND` | 404 | skill 不存在 |
| `SKILL_EXEC_TIMEOUT` | 504 | 脚本超时 |
| `SKILL_EXEC_CRASH` | 500 | 脚本异常退出 |
| `MEMORY_NOT_FOUND` | 404 | 记忆项不存在 |
| `MEMORY_CONFLICT` | 409 | 写入冲突（并发） |
| `RULE_BLOCKED` | 403 | 被 rule hook 拦截 |
| `BUDGET_EXCEEDED` | 402 | 任务预算超限 |
| `AUTH_REQUIRED` | 401 | 未登录 |
| `AUTH_FORBIDDEN` | 403 | 权限不足 |
| `VALIDATION_ERROR` | 422 | 输入校验失败 |

### 23.7 ENV 变量清单（`.env.example`）

```bash
# ===== 基础 =====
AAF_ENV=development                       # development|production|test
AAF_WORKDIR=/data                         # 容器内数据根目录
AAF_LOG_LEVEL=INFO
AAF_SECRET_KEY=change-me                  # JWT 密钥

# ===== 鉴权 =====
AUTH_DISABLED=false
JWT_EXPIRE_SECONDS=86400

# ===== 数据库 =====
DATABASE_URL=postgresql+asyncpg://aaf:aaf@postgres:5432/aaf
REDIS_URL=redis://redis:6379/0
CHROMA_URL=http://chroma:8000
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=aaf

# ===== LLM =====
DEFAULT_LLM_PROVIDER=openai               # 在 models yaml 里定义的 name
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
ANTHROPIC_API_KEY=
# 其他 provider 的 key 自行追加

# ===== 外部工具 =====
SEMANTIC_SCHOLAR_API_KEY=
TAVILY_API_KEY=                           # 可选，web_search
TECTONIC_PATH=/usr/local/bin/tectonic     # 可选，latex_compile

# ===== 限额 =====
AAF_MAX_PARALLEL_TASKS=4
AAF_DEFAULT_BUDGET_USD=2.0
AAF_SKILL_EXEC_TIMEOUT_S=120

# ===== 前端 =====
VITE_API_BASE=http://localhost:8000/api/v1
```

### 23.8 Makefile 速记

```makefile
.PHONY: dev up down logs test fmt lint migrate

dev:        ## 本地开发：backend + frontend 热更
	@uv run uvicorn backend.main:app --reload &
	@pnpm -C frontend dev

up:         ## docker compose 起服务
	@docker compose up -d

down:
	@docker compose down

logs:
	@docker compose logs -f --tail=100

test:
	@uv run pytest backend/tests -v

fmt:
	@uv run ruff format .
	@pnpm -C frontend format

lint:
	@uv run ruff check .
	@uv run mypy backend
	@pnpm -C frontend lint

migrate:
	@uv run alembic upgrade head
```

### 23.9 "零污染复现"校验 Checklist

当开发者（或 LLM）基于本 PLAN 复现本框架时，必须满足以下所有条件方可认为 M0-M6 合格：

- [ ] `docker compose up -d` 在干净 Ubuntu 22.04 / macOS 13 上首次启动 < 5 分钟
- [ ] 未设置任何 `OPENAI_API_KEY` 时，`/api/v1/health` 仍返回 200
- [ ] 启动后前端 Dashboard 页面可打开，LLM Provider 列表为空但页面不报错
- [ ] 配置一个 Ollama 本地 provider 后，可完整跑完一次 research workflow
- [ ] 删除 `skills/paper-writing/` 后，框架仍正常启动，仅该能力不可用
- [ ] 删除 `rules/knowledge-protection.md` 不影响启动（警告日志可以）
- [ ] `aaf skill test paper-writing` 返回所有 eval 通过
- [ ] 关闭外网后，所有非 LLM 相关功能（记忆查询、skill 列表、skill 执行非网络脚本）可用
- [ ] 在完全不进 Cursor 的情况下，单用 `aaf` CLI 能完成一次写作任务

满足以上 9 条 = 框架真正做到了"LLM 无关、Cursor 无关、可私有部署"。

---

## 结语

这份 PLAN 以**三层 Skill/Rule 体系**、**自研 Skill Host 运行时**、**LLM 无关协议**为三大支柱。所有后续代码必须回答：

- 我加的这段逻辑，是 L1 能力 / L2 纪律 / L3 经验？还是工程脚手架？
- 这段逻辑是否绑定了特定 LLM / 特定 IDE？
- 这段逻辑是否把记忆藏在了 LLM context 里？

**任何违反 §2 六条原则的代码都必须在 PR 里显式论证**。

下一步：确认本 PLAN → 启动 M0。
