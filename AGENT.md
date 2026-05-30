# Academic Agent Framework (AAF)

An autonomous academic assistant powered by LLM tool-calling and a skill ecosystem.
Supports paper search, structured reading, writing, peer review, and revision.

## Architecture

```
User Query → AutoWorkflow (agent loop)
               ├─ System prompt: presets/chat.md
               ├─ Tools: arxiv, MCP, memory, read_file, write_file
               └─ Skills (pull-mode): 24 skills listed, LLM calls use_skill__<name>
                    └─ Skill body returned, sub-tools registered dynamically
```

- **Workflows**: `auto` (chat agent), `peer-review`, `write`, `revision`, `research`, `consult`
- **Skills**: 24 domain-specific modules under `skills/` (SKILL.md frontmatter + scripts)
- **Memory**: vector + knowledge graph + episodic + heuristic stores
- **Frontend**: React + Vite + Monaco editor, at `frontend/`

## Quick Start

```bash
# One-click install
install.bat

# Launch (or double-click AAF-Start on desktop)
scripts/windows/start_aaf.cmd

# Open browser
http://127.0.0.1:5173
```

## Key Files

| File | Purpose |
|------|---------|
| `AGENT.md` | This file — project overview for Claude Code / Cursor |
| `presets/chat.md` | Default system prompt for the auto chat agent |
| `presets/peer-review.md` | System prompt for peer review workflow |
| `backend/app.py` | FastAPI application factory + lifespan |
| `backend/workflows/auto.py` | Main agent loop — tool calling + skill discovery |
| `backend/workflows/peer_review.py` | Structured peer review pipeline |
| `backend/core/llm/` | LLM provider adapters (OpenAI-compat, Anthropic) |
| `backend/core/skill_host/` | Skill loading, matching, execution |
| `backend/core/context/` | Conversation context + compaction |
| `skills/*/SKILL.md` | Skill definitions (YAML frontmatter + Markdown body) |
| `frontend/src/` | React frontend |

## Skill System

Skills are defined in `skills/<name>/SKILL.md` with YAML frontmatter:

```yaml
---
name: peer-review
description: Pre-submission self-audit and reviewer-style critique...
triggers: [投稿前自审, pre-submission review]
domain: revision
---
# Peer Review Skill Body...
```

The agent sees skill names + descriptions in its system prompt.
When it needs a skill, it calls `use_skill__<name>` to load the full body.
This is Claude Code's pull-mode skill discovery.

## Adding a New Skill

1. Create `skills/<name>/SKILL.md` with frontmatter + body
2. The skill is auto-discovered on next backend restart
3. Add triggers for keyword matching (optional)
4. Add scripts under `skills/<name>/` if the skill needs subprocess execution

## Configuration

- `.env` — API keys and model config
- `AGENT.md` — this overview (editable via Settings page)
- Settings page: `http://127.0.0.1:5173/settings` — LLM provider, Agent rules
