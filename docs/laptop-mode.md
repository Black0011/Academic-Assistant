# Laptop mode — single-user, zero-ops AAF

This page is for one specific situation: **you want to run AAF on your
own laptop as a personal academic assistant, no Postgres, no Redis, no
docker if you don't want it.** Everything below is opt-in; the
production stack in `docker-compose.yml` is unchanged.

## What "laptop mode" gets you

| Subsystem        | Production preset           | Laptop preset                |
|------------------|-----------------------------|------------------------------|
| Task store       | Postgres (`SqlTaskStore`)   | SQLite file (`./data/aaf.db`)|
| Manuscript store | Postgres                    | SQLite (same db)             |
| Episodic memory  | Postgres                    | SQLite                       |
| Vector memory    | Chroma persisted to disk    | In-memory (`MEMORY_VECTOR_BACKEND=memory`) |
| Session memory   | Redis                       | In-memory                    |
| Task queue       | ARQ + Redis worker          | In-memory (`AAF_TASK_QUEUE_BACKEND=inmemory`) |
| Knowledge / heuristic | YAML on disk (same)    | YAML on disk (same)          |
| Auth             | JWT (`AUTH_DISABLED=false`) | Single user (`AUTH_DISABLED=true`) |
| LLM              | Real provider               | Mock fallback if no key set  |
| Auto-compaction  | Off by default              | On (`AAF_AUTOCOMPACT_ENABLED=true`) |
| MCP servers      | Off by default              | Off (flip `AAF_MCP_ENABLED=true` per host) |
| Self-evolution   | Off                         | Off (turn on once you trust the queue) |
| Parallelism cap  | 4 tasks                     | 2 tasks                      |
| Budget cap       | $2/run                      | $0.5/run                     |

Boot footprint on a typical macOS laptop: **one Python process,
~250 MB RAM, ~3 s cold start, no background workers**.

## Two ways to run it

### A. Local (no docker) — fastest iteration

```bash
cp .env.laptop.example .env.laptop          # then edit OPENAI_API_KEY etc.
make dev-laptop                             # backend + vite, both reload
```

`make dev-laptop` boots:

- backend on `http://127.0.0.1:8000` reading `.env.laptop`
- frontend on `http://127.0.0.1:5173` (proxies `/api` → :8000)

Hit `http://127.0.0.1:5173`. The CLI / SDK clients also work against
:8000 just like in the full stack.

### B. Docker (`docker-compose.lite.yml`) — same isolation, no host Python

```bash
cp .env.laptop.example .env.laptop          # same env file
make up-lite                                # backend + frontend containers only
open http://localhost:8080
make down-lite
```

This compose file ships **only** `backend` + `frontend` (no postgres,
no redis, no worker). The host's `./data/` directory is mounted into
the backend container, so the SQLite db, knowledge YAML, and proposals
survive `down-lite` / restarts.

## Wiring real models

The preset boots fine with no API keys (deterministic mock provider, so
you can click around the UI and inspect skills / planner DAGs / tool
catalog). To get real answers, edit `.env.laptop`:

```bash
DEFAULT_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_DEFAULT_MODEL=gpt-4o-mini
```

For DeepSeek (or any OpenAI-compatible endpoint):

```bash
DEFAULT_LLM_PROVIDER=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_DEFAULT_MODEL=deepseek-chat
```

For local Ollama (no key required):

```bash
DEFAULT_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

### Going fully offline (no outbound API calls at all)

Ollama covers chat, but `LLMProvider.embed()` on the Ollama route
returns 404 (Ollama doesn't expose an embeddings endpoint), so the
vector store silently degrades to keyword matching. To get real
semantic search without any network call:

```bash
uv sync --extra offline                       # pulls sentence-transformers + torch
cp .env.offline.example .env.laptop           # ships AAF_EMBEDDING_BACKEND=local
make dev-laptop
```

This swaps the embedder slot for an in-process
`LocalSentenceTransformerEmbedder` (default
`BAAI/bge-small-en-v1.5`, 133 MB, 384-dim) while keeping chat on
Ollama. First boot downloads the embedding model into HuggingFace's
cache (`~/.cache/huggingface` by default; override with
`AAF_LOCAL_EMBEDDING_CACHE_FOLDER`); subsequent boots are instant.

Requirements:
- ~250 MB RAM extra for the loaded ST model
- CPU is fine (encode ~200 texts/s on M1 / modern x86); set
  `AAF_LOCAL_EMBEDDING_DEVICE=mps` or `cuda` if you want hardware
  acceleration
- Optional `offline` extra is **not** installed by default; the only
  way to forget is to set `AAF_EMBEDDING_BACKEND=local` without it,
  which surfaces a clear `ConfigError` on the first vector query
  pointing at the `uv sync` command that fixes it

## Per-task model routing on the laptop

Workflows can opt into a different model per task with
`ctx.llm.for_route("fast" | "reasoning")`. Wire it by dropping a
`config/model_routing.yaml` (start from
`config/model_routing.example.yaml`); the laptop preset already sets
`AAF_MODEL_ROUTING_CONFIG=./config/model_routing.yaml`. Cheap routes
go to the flash/chat model, expensive routes to the reasoning model —
free token savings on long writing sessions.

The auto-compaction wrapper picks `fast` (= flash/chat) as the
summariser when routing is wired, so the fast model also pays the
context-trimming bill.

## Adding MCP servers later

Set `AAF_MCP_ENABLED=true` in `.env.laptop` and drop a
`config/mcp_servers.yaml` (start from
`config/mcp_servers.example.yaml`). Each declared server is launched
on backend boot; failures are isolated per server (the rest of AAF
still boots). Inspect status from the UI at `/mcp` or via
`GET /api/v1/mcp/servers`.

Cost: roughly one extra Python/Node process per stdio MCP server.
Don't add 20 of them on a laptop.

## What you give up vs. the full stack

- **No background worker process.** Long-running tasks share the API
  process. That's fine for one user, will not scale to many.
- **No Redis pub/sub.** Live SSE streams still work (in-memory
  fan-out), but only within one backend instance.
- **No Chroma persistence.** Vector memory is rebuilt on every boot.
  If you want the vector memory durable, set
  `MEMORY_VECTOR_BACKEND=chroma` and `CHROMA_PERSIST_DIR=./data/chroma`
  — chromadb is already in `pyproject.toml`'s extras.
- **No multi-user accounts.** `AUTH_DISABLED=true` treats every
  request as the same anonymous local user.

If you outgrow any of these, switch back to the full stack (`make up`)
— the data formats are designed so a SQLite db can be migrated into
Postgres later without lossy conversion (M9 work).
