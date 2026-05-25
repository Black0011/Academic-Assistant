# 学术助手（Academic Agent Framework）— 迁移复现指南

> 本文件面向**在新电脑上复现学术助手**的场景。无需了解框架内部实现。

## 系统要求

| 依赖 | 版本 | 安装方式 |
|------|------|---------|
| **Python** | ≥ 3.11 | [python.org](https://www.python.org/) 或 `brew install python@3.11` |
| **uv** | ≥ 0.10 | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| **Node.js** | ≥ 18 | [nodejs.org](https://nodejs.org/) 或 `brew install node` |
| **npm** | 随 Node 自带 | — |
| **Git** | 任意 | `brew install git` 或系统自带 |

> macOS / Linux / WSL2 均可。Windows 原生未测试，建议用 WSL2。

## 一、解压

```bash
tar xzf academic-agent-framework.tar.gz
cd academic-agent-framework
```

## 二、安装依赖

```bash
# Python 后端依赖（自动创建 .venv）
uv sync --all-extras

# 前端依赖
npm --prefix frontend install
```

## 三、配置 LLM Provider

学术助手需要一个 LLM 来驱动调研和写作。支持 OpenAI 兼容的任何 API。

### 方式 A：DeepSeek（推荐，便宜）

```bash
# 1. 复制环境模板
cp .env.laptop.example .env.laptop

# 2. 创建 LLM 运行时配置
mkdir -p data/runtime
cat > data/runtime/provider.yaml << 'EOF'
provider: openai
base_url: https://api.deepseek.com/v1
api_key: <你的 DeepSeek API Key>
default_model: deepseek-chat
timeout_s: 120
EOF
```

去 [platform.deepseek.com](https://platform.deepseek.com/) 获取 API Key。

### 方式 B：OpenAI

```bash
cp .env.laptop.example .env.laptop

mkdir -p data/runtime
cat > data/runtime/provider.yaml << 'EOF'
provider: openai
base_url: https://api.openai.com/v1
api_key: <你的 OpenAI API Key>
default_model: gpt-4o
timeout_s: 120
EOF
```

### 方式 C：本地模型（Ollama）

```bash
cp .env.offline.example .env.laptop

mkdir -p data/runtime
cat > data/runtime/provider.yaml << 'EOF'
provider: openai
base_url: http://localhost:11434/v1
api_key: ollama
default_model: llama3.1:8b
timeout_s: 120
EOF
```

需先安装 [Ollama](https://ollama.ai/) 并 `ollama pull llama3.1:8b`。

## 四、启动

```bash
make dev-laptop
```

启动后：
- 前端：**http://127.0.0.1:5173**（浏览器打开这个）
- 后端：http://127.0.0.1:8000（前端自动代理 /api 到此）

> 首次启动会自动创建 SQLite 数据库（`data/aaf.db`），无需手动建表。

## 五、验证

打开浏览器 http://127.0.0.1:5173，你应该看到学术助手界面。

### 快速测试

```bash
# 后端健康检查
curl http://127.0.0.1:8000/api/health
# 预期: {"status":"ok"}

# 提交一个调研任务（中文也行）
curl -X POST http://127.0.0.1:8000/api/tasks \
  -H 'Content-Type: application/json' \
  -d '{"workflow":"research","query":"knowledge distillation for LLM agents"}'
```

## 功能概览

### 核心功能

| 功能 | 入口 | 说明 |
|------|------|------|
| **文献调研** | 新建任务 → research | LLM 自动规划搜索策略，支持中文查询 |
| **论文写作** | 新建任务 → write | 逐章节写作，含证据驱动、去 AI 化 |
| **论文修订** | 新建任务 → revision | 分析稿件 + 审稿意见，生成修改建议 |
| **学术咨询** | 新建任务 → consult | 对稿件章节提问（如"intro 是否清晰"） |
| **稿件管理** | Manuscripts 页面 | 支持 bundle 项目（.tex + .bib + figures） |
| **记忆系统** | Memory 页面 | 论文卡片、知识文档、反思、启发式 |
| **Skill 管理** | Skills 页面 | 24 个学术 skill 的 DAG 可视化 + 编辑 |

### 24 个学术 Skill

| 领域 | Skill |
|------|-------|
| 调研 | autoresearch, literature-search, paper-reading, download-paper |
| 写作 | paper-writing, writing-chapters, writing-core, evidence-driven-writing, experiment-results-planning, brainstorming-research |
| 修订 | paper-revision, peer-review, rebuttal-writer, verification |
| 演示 | paper-presentation, presentation-maker, pptx |
| 综述 | survey-table, survey-writing |
| 元能力 | brainstorming, creative-thinking, prompts-collection, skill-creator |
| 编排 | paper-orchestration |

### 6 个工作流

| 工作流 | 说明 |
|--------|------|
| `research` | LLM Agent 驱动的文献调研（自动翻译中文查询、多轮搜索） |
| `write` | 论文写作（大纲 → 分节起草 → 润色） |
| `revision` | 稿件修订（解析 → 批评 → 改写 → diff） |
| `consult` | 学术咨询（针对稿件章节回答问题） |
| `dag` | PlanDAG 执行（可选的 skill 编排引擎） |
| `demo` | 端到端 smoke 测试 |

## 目录结构

```
academic-agent-framework/
├── backend/                 FastAPI 后端
│   ├── agents/              Agent 实现（ResearchAgent, EvolverAgent）
│   ├── api/routers/         HTTP 路由
│   ├── core/                LLM provider, skill host, rule engine
│   ├── workflows/           工作流（research, write, revision, consult）
│   ├── memory/              五层记忆（vector, knowledge, heuristic, episodic, session）
│   ├── manuscripts/         稿件管理 + bundle 存储
│   ├── tools/               工具（arxiv_search, pdf_parse, MCP）
│   └── tests/               测试
├── frontend/                React 19 + Vite + Tailwind v4 前端
├── skills/                  24 个 L1 学术 Skill
├── rules/                   L2 行为规则
├── data/                    运行时数据（启动后自动创建）
│   ├── runtime/             LLM provider 配置（需手动创建）
│   └── skills/              L3 启发式策略
├── prompts/                 LLM prompt 模板
├── config/                  配置示例
├── deploy/                  Docker 部署文件
├── docs/                    文档
├── .env.laptop.example      环境变量模板
└── Makefile                 常用命令
```

## 常用命令

```bash
make dev-laptop              # 启动后端 + 前端（laptop 模式）
make dev-backend             # 只启动后端
make dev-frontend            # 只启动前端
make test                    # 运行后端测试
make check                   # 完整质量检查（lint + type + test）
make fmt                     # 格式化代码
```

## Docker 部署（可选）

如果需要完整的生产级部署（含 Postgres + Redis）：

```bash
cp .env.example .env         # 编辑填入 API key
make up                      # docker compose up
open http://localhost:8080
```

## 故障排查

| 问题 | 解决 |
|------|------|
| `uv sync` 报错 | 确认 Python ≥ 3.11：`python3 --version` |
| 后端启动报 `ModuleNotFoundError` | 运行 `uv sync --all-extras` |
| 前端白屏 | 运行 `npm --prefix frontend install` |
| 调研任务超时 | arXiv API 偶尔慢，已设 45s 超时 + 自动重试 |
| `provider.yaml` 报错 | 确认 `data/runtime/provider.yaml` 存在且 API key 正确 |
| 端口占用 | `lsof -ti:8000 \| xargs kill; lsof -ti:5173 \| xargs kill` |
