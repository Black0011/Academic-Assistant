# Academic Agent Framework

[English](#) | 中文

An open-source, local-first academic agent framework. LLM-powered literature research,
paper writing, revision, peer review, and citation management — with a 24-skill ecosystem.
Works with DeepSeek, OpenAI, Anthropic, and local models via Ollama.

开源的本地优先学术智能体框架。LLM 驱动的文献调研、论文写作、修订、同行评审和引用管理，
内置 24 个学术 Skill。兼容 DeepSeek、OpenAI、Anthropic 及 Ollama 本地模型。

---

## What's New

- **24-Skill ecosystem** — progressive pull-mode: Agent reads skill descriptions, calls `use_skill__<name>` on its own judgment (Claude Code model)
- **Full conversation history** — cross-turn context with complete message chain (user → assistant+tool_calls → tool results), like ChatGPT / Claude Code
- **Editable system prompt** — `presets/chat.md` editable from Settings page, changes take effect immediately
- **AGENT.md** — project overview for Claude Code / Cursor
- **Desktop shortcuts** — AAF-Start / AAF-Stop for one-click launch/stop
- **Process + Result split** — task detail page shows execution timeline and final answer as separate cards
- **code-map.md** — complete project structure reference

---

## Requirements

- Python 3.11+
- Node.js 18+ / npm
- (Optional) uv for faster Python package installs

---

## Quick Start

### One-Click (Windows)

**For non-technical users — no command line needed.**

1. Install Python 3.11+ from https://www.python.org/downloads/ (check "Add to PATH")
2. Install Node.js from https://nodejs.org/
3. Download this project and double-click **`install.bat`**
4. Edit `.env` to add your API key (DeepSeek recommended: https://platform.deepseek.com)
5. Double-click **`start.bat`** — browser opens automatically at http://127.0.0.1:5173
6. To stop: double-click **`stop.bat`**

Desktop shortcuts are created automatically during install — look for **AAF-Start** and **AAF-Stop** on your desktop.

### Manual (macOS / Linux / advanced)

```bash
git clone https://github.com/Black0011/Academic-Assistant.git
cd Academic-Assistant

# Backend
python -m venv .venv
.venv/Scripts/pip install -e .          # Windows
# or: uv sync --all-extras
.venv/Scripts/pip install mcp scholarly requests beautifulsoup4

# Frontend
npm --prefix frontend install

# Configure
cp .env.example .env   # Add your API key
```

### Configuration

Edit `.env`:
```ini
OPENAI_API_KEY=sk-your-key
OPENAI_BASE_URL=https://api.deepseek.com/v1   # DeepSeek (recommended for CN users)
OPENAI_DEFAULT_MODEL=deepseek-v4-flash
```

For Chinese users behind GFW with a VPN (Clash, V2Ray):
```ini
AAF_HTTPS_PROXY=http://127.0.0.1:7890
```
Or the framework auto-detects Windows system proxy on startup.

### Run

```bash
# Backend (terminal 1)
.venv/Scripts/python -m uvicorn backend.app:create_app --factory --host 127.0.0.1 --port 8000

# Frontend (terminal 2)
npm --prefix frontend run dev -- --host 127.0.0.1 --port 5173
```

Open **http://127.0.0.1:5173** in your browser.

---

## Architecture

```
User Query → AutoWorkflow (agent loop)
               ├─ System prompt: presets/chat.md (editable via Settings page)
               ├─ Tools: arxiv, MCP, memory, read_file, write_file, expand_tool_result
               └─ Skills (pull-mode): 24 skills, LLM calls use_skill__<name>
                    └─ Skill body returned, sub-tools registered dynamically

Conversation Model (Claude Code / ChatGPT style):
  [user] review this paper
  [assistant] tool_calls=[use_skill__peer-review]
  [tool] ## Skill: peer-review ...
  [assistant] tool_calls=[read_file]
  [tool] File: sections/intro.tex ...
  [assistant] Review results: ...
  [user] what tools did you use?        ← full context preserved
```

See [code-map.md](code-map.md) for the complete project structure.

---

## Features

| Feature | Description |
|---------|-------------|
| **24-Skill Ecosystem** | Domain-specific skills for research, writing, revision, presentation. Agent reads descriptions, chooses autonomously (Claude Code pull-mode) |
| **11 Workflows** | auto (main agent), consult, project-consult, revision, project-revision, write, research, peer-review, citation-research, dag, demo |
| **Conversation History** | Full message chain across turns (user → assistant+tool_calls → tool results → answer), like ChatGPT / Claude Code |
| **Research** | Multi-round agent searches arxiv + Google Scholar MCP, creates PaperCards with auto-backfilled bibtex |
| **Citation Research** | Upload PDF → LLM extracts references → researches each → stores as memory cards |
| **Write** | Draft paper sections with citation discipline |
| **Revision** | Comment-driven rewriting with change_log and per-file diffs |
| **Peer Review** | Full-project 3-stage structured review (preliminary → section-by-section → methodology + bias audit) |
| **Knowledge Store** | Paper cards with bibtex, typed links, vector search |
| **MCP Servers** | Google Scholar built-in; add any MCP server via YAML config |
| **Editable System Prompt** | `presets/chat.md` — customize agent behavior from Settings page |
| **Planner** | Compile natural-language tasks into executable Plan DAGs with parallel fan-out |
| **Memory System** | 5 stores: Vector, Knowledge, Heuristic, Episodic, Session — SQLite or Postgres |
| **Desktop Shortcuts** | AAF-Start / AAF-Stop for one-click Windows launch/stop |
| **Proxy Auto-detect** | Reads Windows system proxy for arxiv/Google Scholar access behind firewalls |
| **Docker Support** | Full stack: Postgres + Redis + Backend + Worker + Frontend + MinIO |

---

## Workflows (11 total)

| Workflow | Description | History |
|----------|-------------|:---:|
| `auto` | **Main agent loop** — tool calling, skill discovery, conversation | ✅ |
| `consult` | Ask about a single file | ✅ |
| `project-consult` | Explore and ask about an entire project | ✅ |
| `project-revision` | Multi-file project editing | ✅ |
| `revision` | Rewrite based on reviewer comments | ✅ |
| `write` | Draft a paper section | ✅ |
| `research` | Search for papers via arxiv/Google Scholar | ✅ |
| `peer-review` | Full project structured review (3-stage) | ✅ |
| `citation-research` | Upload PDF → extract & research all citations | ✅ |
| `dag` | Plan DAG compilation (used by Planner) | — |
| `demo` | Test / smoke-test workflow | — |

---

## Skill System

24 domain-specific skills under `skills/`. Each is a `SKILL.md` file with YAML frontmatter + Markdown body.

| Domain | Skills |
|--------|--------|
| **Research** | autoresearch, literature-search, paper-reading, download-paper |
| **Writing** | paper-writing, writing-chapters, writing-core, evidence-driven-writing |
| **Revision** | paper-revision, peer-review, rebuttal-writer |
| **Planning** | paper-orchestration, brainstorming-research, experiment-results-planning |
| **Presentation** | paper-presentation, presentation-maker, pptx |
| **Meta** | skill-creator, prompts-collection, verification |
| **Other** | brainstorming, creative-thinking, survey-table, survey-writing |

**How it works (Claude Code pull-mode):**
1. Agent sees all skill names + descriptions in its system prompt
2. When a skill matches the user's request, Agent calls `use_skill__<name>`
3. Skill body is returned as a tool result with sub-tools registered
4. Agent executes the skill's workflow using its instructions

**Adding skills:** Drop any Claude Code-format `SKILL.md` into `skills/<name>/` — auto-discovered on restart.

---

## Configuration Files

| File | Purpose |
|------|---------|
| `.env` | API keys, model config, database backend |
| `AGENT.md` | Project overview for Claude Code / Cursor |
| `presets/chat.md` | Agent system prompt — editable from Settings page |
| `config/mcp_servers.yaml` | MCP server configuration |
| `config/model_routing.example.yaml` | Per-task model routing rules |
| `code-map.md` | Complete project structure reference |

---

## Tips

- **API Key**: Register at https://platform.deepseek.com (cheap, works in China without VPN)
- **VPN/Proxy**: If arXiv/Google Scholar are blocked, the framework auto-detects Clash/V2Ray system proxy. Or set `AAF_HTTPS_PROXY=http://127.0.0.1:7890` in `.env`
- **Stopping**: Double-click `AAF-Stop` on desktop, or run `stop.bat`
- **Data**: All papers and manuscripts live in the `data/` folder. Back it up
- **Customizing Agent**: Edit `presets/chat.md` from Settings page (http://127.0.0.1:5173/settings)

---

## License

MIT
