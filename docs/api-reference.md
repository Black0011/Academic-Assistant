# API reference

Generated from the routers under `backend/api/routers/`. Every endpoint
listed below exists in `main` — add a failing test if the docs and the
code disagree.

`/openapi.json` on a running server gives you the full JSON Schema of
every request and response. The SDK (`sdk/python/aaf/`) wraps the same
surface and ships matching Pydantic models.

## Conventions

- All endpoints are mounted under `/api/`.
- Bodies are JSON unless noted (file upload uses `multipart/form-data`).
- SSE endpoints return `Content-Type: text/event-stream`; the API
  reverse-proxy disables buffering for them
  (`deploy/nginx/frontend.conf`).
- Auth: `Authorization: Bearer <jwt>`. When `AUTH_DISABLED=true`, every
  endpoint accepts requests without a header (the runtime substitutes
  the synthetic anonymous user).
- Pagination: `limit` (1–500, default 50) + `offset` (default 0). Lists
  return `{ "items": [...], "total": <count of returned items> }`.

## Health (`backend/api/routers/health.py`)

| Method | Path           | Body | Returns                                         |
|--------|----------------|------|-------------------------------------------------|
| GET    | `/api/health`  | —    | `{"status":"ok"}`                              |
| GET    | `/api/version` | —    | framework version + active LLM/memory wiring    |

`/api/version` payload shape:

```json
{
  "version": "0.1.0",
  "llm_provider": "openai",
  "memory": {
    "vector": "ChromaVectorStore",
    "knowledge": "YamlKnowledgeStore",
    "heuristic": "YamlHeuristicStore",
    "episodic": "SqlEpisodicStore",
    "session": "RedisSessionStore"
  },
  "tools": ["arxiv__search", "semantic_scholar__lookup", "pdf__parse", ...]
}
```

## Auth (`/api/auth/*`)

| Method | Path                | Auth?  | Returns                                                        |
|--------|---------------------|--------|----------------------------------------------------------------|
| GET    | `/api/auth/config`  | none   | `AuthConfig` — `{enabled, allow_signup}` (frontend boots from this) |
| POST   | `/api/auth/login`   | none   | `TokenResponse` — `{access_token, token_type, expires_in, user}` |
| POST   | `/api/auth/register`| none   | `TokenResponse`. 503 when `AUTH_DISABLED`, 403 when signup off, 409 on duplicate email. The first-ever account is auto-promoted to `admin`. |
| GET    | `/api/auth/me`      | bearer | `PublicUser`. 401 on missing/invalid token.                    |
| POST   | `/api/auth/logout`  | none   | 204. Stateless — the client just drops the token.              |

`PublicUser`: `{id, email, display_name, role: "admin"|"user", disabled}`.

## Workflows (`/api/workflows/*`)

| Method | Path                              | Returns                                                  |
|--------|-----------------------------------|----------------------------------------------------------|
| GET    | `/api/workflows`                  | `[{name, description}]` — registry contents              |
| POST   | `/api/workflows/{name}/run`       | `RunResponse` (synchronous, full trace included)         |
| POST   | `/api/workflows/{name}/stream`    | `text/event-stream` of `Event`s; closes on `task.end`    |

Request body for both run + stream:

```json
{
  "query": "Mixture-of-Experts inference systems",
  "input": { "max_papers": 8 },
  "user_id": "u-1",
  "session_id": "s-3",
  "budget_usd": 0.5
}
```

`RunResponse`:

```json
{
  "task_id": "…",
  "verdict": "ok",
  "results": { "outline": "...", "papers": [ ... ] },
  "error": null,
  "budget": { "spent_usd": 0.18, "tokens": 41210 },
  "events": [ { "type": "task.stage_start", "data": { ... } }, ... ]
}
```

The HTTP run holds the connection open until the workflow finishes. For
anything longer than ~30 s prefer the `/api/tasks` flow below.

## Tasks (`/api/tasks/*`)

The durable, queue-backed equivalent of `/api/workflows/.../stream`.

| Method | Path                              | Status | Returns                                                  |
|--------|-----------------------------------|--------|----------------------------------------------------------|
| POST   | `/api/tasks`                      | 202    | `{task_id, status, workflow}` — enqueues a workflow run  |
| GET    | `/api/tasks`                      | 200    | `{items: TaskRecord[], total}` — `?user_id&task_status&limit&offset` |
| GET    | `/api/tasks/{id}`                 | 200    | `TaskRecord`. 404 when unknown.                          |
| DELETE | `/api/tasks/{id}`                 | 200    | `TaskRecord` after marking it `cancelled` (best-effort). |
| GET    | `/api/tasks/{id}/events`          | 200    | `{items: TaskEventRecord[], next_after_seq}` — `?after_seq&limit` |
| GET    | `/api/tasks/{id}/stream`          | 200    | `text/event-stream`. Replays history from `after_seq`, then tails. |

`POST /api/tasks` body (`CreateTaskInput`):

```json
{
  "workflow": "research",
  "query": "MoE inference systems",
  "input": { "max_papers": 8 },
  "user_id": "u-1",
  "session_id": "s-3",
  "budget_usd": 0.5
}
```

`TaskRecord`:

```json
{
  "id": "f3e7…",
  "workflow": "research",
  "status": "running",                 // queued|running|ok|error|cancelled
  "query": "MoE inference systems",
  "input": { ... },
  "budget": { "max_cost_usd": 0.5, "spent_usd": 0.12 },
  "result": null,                      // populated on terminal ok
  "error": null,                       // populated on terminal error
  "user_id": "u-1",
  "session_id": "s-3",
  "created_at":  "2026-04-25T11:00:00+00:00",
  "started_at":  "2026-04-25T11:00:01+00:00",
  "completed_at": null
}
```

Stream events arrive as named SSE events; data is JSON. Common types:

| `event:`               | When                                   |
|------------------------|----------------------------------------|
| `task.start`           | Worker picked up the run.              |
| `task.stage_start`     | A `ctx.stage(name)` block opened.      |
| `task.stage_end`       | The stage closed cleanly.              |
| `task.end`             | Workflow finished with verdict.        |
| `task.error`           | Workflow raised; `data.error` carries the message. |
| `llm.token_delta`      | One streamed delta from the model.     |
| `llm.usage`            | Usage / cost for one completion.       |
| `tool.invoke` / `result` | A tool call started / completed.    |
| `memory.write`         | A memory store accepted a write.       |
| `skill.invoke`         | A skill script ran.                    |

## Manuscripts (`/api/manuscripts/*`)

| Method | Path                                          | Status | Returns                                       |
|--------|-----------------------------------------------|--------|-----------------------------------------------|
| GET    | `/api/manuscripts`                            | 200    | `{items: Manuscript[], total}` — `?user_id&status&kind&tag&limit&offset` |
| POST   | `/api/manuscripts`                            | 201    | `ManuscriptEnvelope` — `{manuscript, version}` |
| GET    | `/api/manuscripts/{id}`                       | 200    | `Manuscript`                                   |
| PATCH  | `/api/manuscripts/{id}`                       | 200    | `Manuscript` after applying partial update     |
| DELETE | `/api/manuscripts/{id}`                       | 204    | —                                              |
| POST   | `/api/manuscripts/{id}/versions`              | 201    | `ManuscriptVersion` — append-only commit       |
| GET    | `/api/manuscripts/{id}/versions`              | 200    | `{items: ManuscriptVersion[], total}` — `?limit` |
| GET    | `/api/manuscripts/{id}/versions/{version}`    | 200    | `ManuscriptVersion` (full content)             |
| GET    | `/api/manuscripts/{id}/export`                | 200    | `text/markdown` download — `?version` (defaults to latest) |
| POST   | `/api/manuscripts/upload`                     | 201    | `ManuscriptEnvelope`. `multipart/form-data` with `file` (md/markdown/txt/pdf, ≤ 40 MB) + form fields `title`, `kind`, `section`, `topic`, `tags`, `user_id`, `session_id`. |
| GET    | `/api/manuscripts/stats`                      | 200    | counts by status                               |
| POST   | `/api/manuscripts/{id}/bundle`                | 200    | `Manuscript` — promote `single` → `bundle`. Body: `{link_path?, versioning?}`. Empty body ⇒ copy mode (AAF-owned `./data/manuscripts/<id>/work/`); `link_path` ⇒ link mode (must exist + be a directory). |
| GET    | `/api/manuscripts/{id}/tree`                  | 200    | `BundleManifest` — `{manuscript_id, layout, root, link_mode, file_count, total_size, files[]}`. Each `ManuscriptFile`: `{path, size, mime, is_text, sha256, modified_at}`. `?include_hash=true` to compute sha256s; `?include_hidden=true` to surface dotfiles. |
| GET    | `/api/manuscripts/{id}/files/{path:path}`     | 200    | `FileEnvelope` — `{file, encoding: "utf-8" \| "base64", content}`. Text inlined as JSON; small binaries inlined as base64. Use the dedicated download endpoint for large binaries. |
| PUT    | `/api/manuscripts/{id}/files/{path:path}`     | 200    | `ManuscriptFile` — body `{content, encoding: "utf-8"}`. UTF-8 text write. |
| POST   | `/api/manuscripts/{id}/files/{path:path}`     | 201    | `ManuscriptFile` — `multipart/form-data` with `file` field. Binary upload at the given relative path. |
| DELETE | `/api/manuscripts/{id}/files/{path:path}`     | 204    | — Deletes one file (or empty directory).       |
| POST   | `/api/manuscripts/import-folder`              | 201    | `Manuscript` — body `{local_path, mode: "copy" \| "link", title?, kind?, overwrite?, user_id?, session_id?}`. Creates a new bundle by ingesting an on-disk project. |
| POST   | `/api/manuscripts/import-zip`                 | 201    | `Manuscript` — `multipart/form-data` with `file` (`.zip`) + form fields `title`, `kind`, `overwrite`, `user_id`, `session_id`. Defends against zip-slip; rejects symlink entries. |
| GET    | `/api/manuscripts/{id}/export-zip`            | 200    | `application/zip` — packs the bundle. `?subdir=` empty / unset ⇒ auto-detect (`overleaf/` if present, else whole bundle); `?subdir=.` forces whole bundle; `?subdir=<path>` packs only that subdir. Response header `X-Bundle-Subdir: <chosen>`. |
| GET    | `/api/manuscripts/{id}/download/{path:path}`  | 200    | Raw byte stream of one file with `Content-Disposition: attachment`. |

`Manuscript`:

```json
{
  "id": "ms-…",
  "title": "MoE inference survey",
  "kind": "paper",                 // paper|section|outline|note
  "status": "draft",               // draft|in_revision|final|archived
  "section": null,
  "topic": null,
  "tags": ["moe", "survey"],
  "current_version": 3,
  "origin": "user_upload",         // user_upload|write_workflow|revision_workflow|ingest|api
  "user_id": "u-1",
  "session_id": "s-3",
  "meta": { ... },
  "created_at": "...",
  "updated_at": "...",
  "layout": "single",              // P7 — "single" | "bundle"
  "bundle_link_path": null,        // P7 — set only in link mode
  "bundle_versioning": true        // P7 — copy-mode default; ignored for link mode
}
```

**Bundle layout (P7).** A `Manuscript` with `layout: "bundle"` is backed
by a real on-disk directory tree (instead of the single-blob version
chain). The bundle endpoints above (`/bundle`, `/tree`, `/files/...`,
`/import-folder`, `/import-zip`, `/export-zip`, `/download/...`) operate
on that tree. Two physical placements:

- **copy** (`bundle_link_path: null`) — AAF owns
  `./data/manuscripts/<id>/work/`. Self-contained; included in backups;
  packing into a zip is just `export-zip`.
- **link** (`bundle_link_path: "/Users/…/paper-dir"`) — the bundle
  physical root **is** the user-supplied directory. Reads + writes
  happen in place. Useful when the project is already managed by git or
  Overleaf-sync. AAF never deletes a link-mode directory.

Two size caps protect the host: `AAF_MANUSCRIPT_MAX_FILE_MB` (per-file,
default 50) and `AAF_MANUSCRIPT_MAX_BUNDLE_MB` (whole-bundle, default
500). Exceeding either yields HTTP 413 (`manuscript.file_too_large` /
`manuscript.bundle_too_large`).

Bundle-specific error codes:

| Code (RFC 7807) | HTTP | Meaning |
|---|---|---|
| `manuscript.layout_mismatch` | 409 | Bundle endpoint hit on a `single` manuscript (or vice versa). |
| `manuscript.path_invalid`    | 400 | Path containment failed (absolute, `..`, symlink escape, zip-slip). |
| `manuscript.file_too_large`  | 413 | Single file exceeds `MAX_FILE_MB`. |
| `manuscript.bundle_too_large`| 413 | Bundle would exceed `MAX_BUNDLE_MB`. |
| `manuscript.io_error`        | 500 | OS-level error (disk full, permissions, …). |

`ManuscriptVersion` (from `/versions/{n}`):

```json
{
  "manuscript_id": "ms-…",
  "version": 3,
  "content": "# Heading\n\n…",
  "note": "second pass — added related work",
  "produced_by": "revision",
  "origin": "revision_workflow",
  "citations": ["arXiv:2310.06770", ...],
  "reviewer_comments": [{"line": 12, "comment": "..."}, ...],
  "word_count": 2843,
  "created_at": "..."
}
```

`POST /api/manuscripts` body (`CreateManuscriptInput`): same fields as
the `Manuscript` record (sans `id`/`current_version`/`origin`) plus an
optional initial `content` and `note`.

`POST .../versions` body (`CommitVersionInput`):

```json
{
  "content": "# … updated body …",
  "note": "fix typo",
  "produced_by": "user",
  "citations": [],
  "reviewer_comments": [],
  "origin": "api"
}
```

## Knowledge (`/api/knowledge/*`)

| Method | Path                                          | Status | Returns                                      |
|--------|-----------------------------------------------|--------|----------------------------------------------|
| GET    | `/api/knowledge/papers`                       | 200    | `{items: PaperCard[], total}` — `?q&tag&user_id&session_id&source_run_id&k&limit&offset`. When `q+k` are both set the server uses `find_related` (semantic) instead of substring search. |
| POST   | `/api/knowledge/papers`                       | 201    | `PaperCard` — upserts (server derives a stable id from title/author/year if `paper_id` is omitted) |
| POST   | `/api/knowledge/papers:bulk`                  | 200    | `{created: PaperCard[], failed: [{title, error}]}` — body has `papers: CreatePaperCardInput[]` |
| POST   | `/api/knowledge/papers/ingest`                | 201    | `IngestPaperResponse` — multipart (PDF/MD/TXT + form fields) **or** JSON. Decodes the body, extracts metadata via `PaperExtractor`, upserts the card, and (default) triggers `PaperMemoryEvolver`. See "Ingest pipeline" below. |
| GET    | `/api/knowledge/papers/{id}`                  | 200    | `PaperCard`                                   |
| PATCH  | `/api/knowledge/papers/{id}`                  | 200    | `PaperCard` after partial update              |
| DELETE | `/api/knowledge/papers/{id}`                  | 204    | —                                             |
| POST   | `/api/knowledge/papers/{id}/links`            | 201    | `PaperCard` — body: `{target_paper_id, link_type, evidence, bidirectional}`. `link_type` ∈ `cites|extends|compares|contradicts|applies`. |
| GET    | `/api/knowledge/syntheses`                    | 200    | `{items: SynthesisNote[], total}`             |
| POST   | `/api/knowledge/syntheses`                    | 201    | `SynthesisNote` — body: `{cluster_tag, content, summary, paper_ids, source_run_id}`. Server bumps `version` on every upsert. |
| GET    | `/api/knowledge/syntheses/{cluster_tag}`      | 200    | `SynthesisNote`                                |
| DELETE | `/api/knowledge/syntheses/{cluster_tag}`      | 204    | —                                             |

`PaperCard`:

```json
{
  "paper_id": "abc123",
  "title": "Mixture-of-Experts at Scale",
  "authors": ["Doe, J.", "Smith, K."],
  "year": 2024,
  "venue": "NeurIPS",
  "abstract": "...",
  "summary": "...",
  "method": "...",
  "findings": "...",
  "tags": ["moe", "scaling"],
  "url": "https://arxiv.org/abs/2401.00001",
  "citation_url": "https://scholar.googleusercontent.com/scholar.bib?...",
  "citation_bibtex": "@article{moe2024,...}",
  "experiment_results": "Main result: ...",
  "source_run_id": "run-1",
  "user_id": "u-1",
  "session_id": "s-3",
  "created_at": "...",
  "updated_at": "..."
}
```

### Ingest pipeline (M7.1)

`POST /api/knowledge/papers/ingest` accepts **either** a multipart form
upload or a JSON metadata body. Content-Type decides which path runs.

**Multipart form fields** (`multipart/form-data`):

| Field               | Required | Notes                                                            |
|---------------------|----------|------------------------------------------------------------------|
| `file`              | yes      | `.pdf` / `.md` / `.markdown` / `.txt`. Hard cap: 25 MB.          |
| `title`             | no       | When omitted, extractor uses the body's H1, then filename stem.  |
| `authors`           | no       | Comma-separated. e.g. `"Doe, J., Smith, K."`                     |
| `year`              | no       | Integer.                                                         |
| `venue`             | no       | Free-form.                                                       |
| `tags`              | no       | Comma-separated.                                                 |
| `source_kind`       | no       | `user_upload` (default) / `arxiv` / `doi` / `manual`.            |
| `source_uri`        | no       | Original URL or local path; defaults to filename.                |
| `trigger_evolution` | no       | `"true"` (default) / `"false"`. Skips the evolver when false.    |
| `llm_extract`       | no       | `"true"` (default) / `"false"`. Force heuristic-only extraction. |

**JSON body** (`application/json`) shape:

```json
{
  "title": "Self-Evolving Agents",
  "authors": ["Alice"],
  "year": 2024,
  "venue": "NeurIPS",
  "abstract": "...",
  "summary": "...",
  "method": "...",
  "findings": "...",
  "tags": ["agent", "memory"],
  "source_kind": "manual",
  "source_uri": "",
  "body_text": "<optional pre-extracted markdown / paper text>",
  "trigger_evolution": true,
  "llm_extract": true,
  "user_id": null,
  "session_id": null
}
```

**`IngestPaperResponse`** shape:

```json
{
  "card": PaperCard,
  "evolution": {
    "paper_id": "abc123",
    "mode": "llm" | "heuristic" | "skip",
    "typed_links_added": [{"target_paper_id":"...","link_type":"applies","evidence":"..."}],
    "tags_added": ["new-tag"],
    "neighbors_considered": 4,
    "reason": ""
  },
  "synthesis": SynthesisNote | null,
  "extracted": {
    "method": "llm" | "heuristic" | "metadata_only",
    "extract_ms": 280,
    "evolve_ms": 920,
    "preview": "first 1 KB of body text",
    "source_kind": "user_upload",
    "raw_pdf_meta": {"pdf_num_pages": 12, "pdf_pages_extracted": 12}
  }
}
```

The new card carries `source_run_id = "ingest:<paper_id>"`, so a single
`POST /api/memory/rollback/ingest:<paper_id>` reverses the entire
ingest (card + typed links + reflections).

## Documents (`/api/documents/*`) — M7.3 RAG library

Free-form document RAG. Pairs a `DocumentStore` with the shared
`VectorStore`: every chunk written here is indexed with
`metadata.kind="doc_chunk"` so `MemoryBundle.snapshot()` can return
`PaperCard`s and `DocChunk`s side-by-side.

| Method | Path                                        | Status | Returns                                                  |
|--------|---------------------------------------------|--------|----------------------------------------------------------|
| POST   | `/api/documents/ingest`                     | 201    | `IngestDocumentResponse` — multipart (file) **or** JSON (`{title?, raw_text, source_kind?, ...}`). Pipeline: decode → chunk (heading-aware sliding window with overlap) → upsert `KnowledgeDocument` → register every chunk in the vector store. |
| GET    | `/api/documents`                            | 200    | `{items: KnowledgeDocument[], total}` — `?user_id&tag&limit&offset` |
| GET    | `/api/documents/{doc_id}`                   | 200    | `KnowledgeDocument` (full `raw_text` included)           |
| GET    | `/api/documents/{doc_id}/chunks`            | 200    | `{items: DocChunk[], total}` — `?offset&limit` (default 100) |
| POST   | `/api/documents/{doc_id}:reindex`           | 200    | `IngestDocumentResponse` — body `{target_tokens?, overlap_tokens?}`. Re-chunks and rebuilds the vector entries (chunk_ids stay deterministic). |
| DELETE | `/api/documents/{doc_id}`                   | 204    | Cascades to the vector store — `vector.count()` decreases by `len(chunk_ids)`. |
| POST   | `/api/documents/search`                     | 200    | `{items: DocChunkHit[], total}` — body `{q, top_k?, filters?}`. Restricted to `kind=doc_chunk`; pass `filters.doc_id=...` to scope to one document. |

`KnowledgeDocument`:

```json
{
  "doc_id": "1f8e…",
  "title": "Vector databases",
  "source_kind": "md_upload",
  "source_uri": null,
  "summary": "first ~320 chars of the body",
  "raw_text": "# Vector databases\n…",
  "tags": ["rag"],
  "chunk_ids": ["1f8e…#0000", "1f8e…#0001"],
  "bytes": 2048,
  "user_id": null,
  "session_id": null,
  "source_run_id": null,
  "extras": {"format": "text"},
  "created_at": "2026-05-…",
  "updated_at": "2026-05-…"
}
```

`DocChunk`:

```json
{
  "chunk_id": "1f8e…#0000",
  "doc_id": "1f8e…",
  "idx": 0,
  "text": "Vector databases index dense embeddings.",
  "char_offset_start": 0,
  "char_offset_end": 41,
  "section_path": ["Vector databases"],
  "tags": []
}
```

The chunker honours code fences and pipe tables (`|...|...|`) — they are
treated as atomic blocks and never split mid-fence. Defaults:
`target_tokens=800`, `overlap_tokens=100` (chars are estimated as
`tokens × 4`).

## Heuristics (`/api/heuristics/*`)

L3 strategy memory. The Evolver writes most of these; humans curate
with freeze/unfreeze and bump.

| Method | Path                                          | Status | Returns                                      |
|--------|-----------------------------------------------|--------|----------------------------------------------|
| GET    | `/api/heuristics`                             | 200    | `{items: Heuristic[], total}` — `?domain&include_frozen&limit&offset` |
| GET    | `/api/heuristics/match?query=…`               | 200    | `{items: Heuristic[], total}` — same ranker the Planner uses; `?domain&top_k` |
| POST   | `/api/heuristics`                             | 201    | `Heuristic`                                  |
| GET    | `/api/heuristics/{id}`                        | 200    | `Heuristic`                                  |
| PATCH  | `/api/heuristics/{id}`                        | 200    | `Heuristic` after partial update             |
| DELETE | `/api/heuristics/{id}`                        | 204    | —                                            |
| POST   | `/api/heuristics/{id}/freeze`                 | 200    | `Heuristic` (now `frozen: true`)             |
| POST   | `/api/heuristics/{id}/unfreeze`               | 200    | `Heuristic` (now `frozen: false`)            |
| POST   | `/api/heuristics/{id}/bump`                   | 200    | `Heuristic` — body: `{verdict: "pass"|"fail"}`. Increments `success_count` or `failure_count`. |

`Heuristic`:

```json
{
  "id": "heu-…",
  "name": "expand-with-snowball",
  "description": "When initial search returns < 5 papers, …",
  "domain": "research",
  "trigger_pattern": "few-results",
  "strategy": {
    "planning_hints": "…",
    "search_tips": "…",
    "evaluation_criteria": "…"
  },
  "source_query": "MoE inference",
  "source_verdict": "pass",
  "source_run_id": "run-1",
  "success_count": 3,
  "failure_count": 0,
  "frozen": false,
  "created_at": "...",
  "updated_at": "..."
}
```

## Memory (`/api/memory/*`)

Snapshot reads, reflections, sessions, and run-level rollback.

| Method | Path                                          | Status | Returns                                      |
|--------|-----------------------------------------------|--------|----------------------------------------------|
| GET    | `/api/memory/snapshot?query=…`                | 200    | `SnapshotResponse` — vector summary + related papers + heuristics + recent reflections. `?domain&k&session_id` |
| GET    | `/api/memory/stats`                           | 200    | `MemoryStats` — counts per store              |
| GET    | `/api/memory/reflections`                     | 200    | `{items: Reflection[], total}` — `?type&session_id&user_id&n` |
| POST   | `/api/memory/reflections`                     | 201    | `Reflection` — body: `{type, content, tags, user_id, session_id, source_run_id}`. `type` ∈ `reflection|observation|insight`. |
| GET    | `/api/memory/sessions?user_id=…`              | 200    | `{items: SessionContext[], total}`            |
| POST   | `/api/memory/sessions`                        | 201    | `SessionContext` — body: `{session_id?, user_id?, title, state}` |
| GET    | `/api/memory/sessions/{id}`                   | 200    | `SessionContext` (with full message history)  |
| PATCH  | `/api/memory/sessions/{id}`                   | 200    | `SessionContext` — body: `{title?, state?}`   |
| POST   | `/api/memory/sessions/{id}/messages`          | 201    | `SessionMessage` — body: `{role, content, meta}` |
| DELETE | `/api/memory/sessions/{id}`                   | 204    | —                                            |
| POST   | `/api/memory/rollback/{run_id}`               | 200    | `RollbackResponse` — `{run_id, knowledge_removed, heuristics_removed, reflections_removed}` |

## Tools (`/api/tools/*`)

Mostly for introspection and debugging; agent runs invoke tools through
workflows.

| Method | Path                              | Status | Returns                                      |
|--------|-----------------------------------|--------|----------------------------------------------|
| GET    | `/api/tools`                      | 200    | `ToolInfo[]` — `[{name, description, parameters, requires_network, requires_paid_api}]` |
| POST   | `/api/tools/{name}/invoke`        | 200    | `InvokeResponse` — `{ok, data, error, meta}`. Body: `{arguments, allow_network, allow_paid_api}` |

## Proposals (`/api/proposals/*`) · M8.1 + P8 (`apply-to-bundle`)

Gated change proposals for the framework's own code, skills, rules, or
configs. **`apply` records status only** — the diff field is the input
for humans / CI; the API never edits files itself for M8.1-style
proposals. State machine: `draft → pending → approved → applied`, with
`withdraw` allowed from any non-terminal state and `reject` from
`pending`.

| Method | Path                                              | Status | Returns                                                                  |
|--------|---------------------------------------------------|--------|--------------------------------------------------------------------------|
| GET    | `/api/proposals`                                  | 200    | `ProposalListResponse` — `?status&proposer_id&tag&page&page_size`        |
| POST   | `/api/proposals`                                  | 201    | `Proposal` (status=draft). Body: `CreateProposalInput`                   |
| GET    | `/api/proposals/{id}`                             | 200    | `Proposal`                                                               |
| PATCH  | `/api/proposals/{id}`                             | 200    | `Proposal` (only allowed in `draft` / `pending`). Body: `UpdateProposalInput` |
| POST   | `/api/proposals/{id}:submit`                      | 200    | `Proposal` (status=pending)                                              |
| POST   | `/api/proposals/{id}:approve`                     | 200    | `Proposal` (status=approved). Admin-only when auth is enabled            |
| POST   | `/api/proposals/{id}:reject`                      | 200    | `Proposal` (status=rejected). Admin-only when auth is enabled            |
| POST   | `/api/proposals/{id}:apply`                       | 200    | `Proposal` (status=applied). **Records status only — does not edit files** |
| POST   | `/api/proposals/{id}:apply-to-bundle` (P8)        | 200    | `Proposal` with `extras += applied_to_bundle_at/by/size`. Writes the bundle file. **Status NOT changed.** |
| POST   | `/api/proposals/{id}:withdraw`                    | 200    | `Proposal` (status=withdrawn)                                            |
| DELETE | `/api/proposals/{id}`                             | 204    | — (only in `draft` / `withdrawn`; admin-only when auth is enabled)       |

Illegal state transitions return **409 Conflict**. Every transition (and
every PATCH) appends a `ProposalAuditEvent` (`actor`, `action`,
`timestamp`, `notes`) to the proposal's audit log.

### `apply-to-bundle` (P8 Phase C2)

For *bundle* proposals — proposals drafted by the EvolverAgent after a
successful bundle write, which carry a unified diff in `Proposal.diff`
and a deterministic apply payload in `Proposal.extras`:

```jsonc
{
  // ... standard Proposal fields ...
  "diff": "--- a/overleaf/sections/intro.tex\n+++ b/overleaf/...\n@@ ...",
  "target_paths": ["overleaf/sections/intro.tex"],
  "extras": {
    "manuscript_id": "ms_xyz",
    "bundle_target": "overleaf/sections/intro.tex",
    "bundle_before": "...content snapshot before workflow ran...",
    "bundle_after":  "...content snapshot after workflow ran...",
    "workflow": "revision",
    // populated only after a successful apply-to-bundle:
    "applied_to_bundle_at":   "2026-05-11T02:13:09+00:00",
    "applied_to_bundle_by":   "user@example.com",
    "applied_to_bundle_size": 4123
  }
}
```

**Body** (`ApplyToBundleInput`):

| Field           | Type           | Default | Notes                                                                |
|-----------------|----------------|---------|----------------------------------------------------------------------|
| `manuscript_id` | `string \| null` | `null` | Override; defaults to `extras.manuscript_id` written by EvolverAgent |
| `force`         | `bool`         | `false` | Skip the staleness check that compares the on-disk file against `extras.bundle_before` |
| `notes`         | `string`       | `""`    | Appended to the audit-log entry                                      |

**Behaviour**:

1. **400** when the proposal lacks `extras.bundle_target` or `extras.bundle_after` (i.e. it's a hand-written M8.1 proposal, not a bundle one).
2. **404** when the resolved manuscript is missing.
3. **409** when the manuscript layout is not `bundle`.
4. **403** when the manuscript is *linked* (external dir) AND `proposal.risk_level != "low"`.
5. **409** when the on-disk file no longer matches `extras.bundle_before` and `force=false` (staleness guard).
6. **200** on success: writes `extras.bundle_after` to `extras.bundle_target` via `BundleStorage` (atomic, size-cap, path-safety), patches `proposal.extras` with `applied_to_bundle_at` / `_by` / `_size`. **`proposal.status` is NOT changed** — call `:apply` separately if you also want to stamp the state machine.

Distinct from `:apply` by design: status transitions and filesystem
writes are kept orthogonal so admins can choose either independently.

## Planner DAG (`/api/planner/*`) · M8.2

Optional planner agent — compile a natural-language query into a
declarative `PlanDAG` of skill / tool / memory / LLM nodes, validate it,
and execute it through the standard Task system. Execution returns
`task_id` so the existing SSE timeline (`/api/tasks/{id}/stream`)
renders node-level events for free.

| Method | Path                                  | Status | Returns                                                                |
|--------|---------------------------------------|--------|------------------------------------------------------------------------|
| GET    | `/api/planner/skills_for_compile`     | 200    | `SkillsForCompileResponse` — curated skill / tool list with parameters |
| POST   | `/api/planner/compile`                | 200    | `PlanDAG`. Body: `CompilePlanInput`. LLM-driven with heuristic fallback |
| POST   | `/api/planner/validate`               | 200    | `ValidatePlanResponse` — `{ok, errors, warnings}`. Body: `{plan}`      |
| POST   | `/api/planner/execute`                | 202    | `ExecutePlanResponse` — `{task_id, status, workflow:"dag", plan_id, node_count}`. Body: `ExecutePlanInput` |

Once executing, follow `/api/tasks/{task_id}/stream` for node-level
`task.stage_start` / `task.stage_end` events with the payload shape:

```jsonc
// task.stage_start
{ "stage": "node:<id>", "node_id": "<id>", "kind": "tool|skill|llm|memory.read|memory.write",
  "name": "...", "description": "..." }

// task.stage_end
{ "stage": "node:<id>", "node_id": "<id>",
  "status": "succeeded|failed|skipped",
  "attempts": 1, "duration_ms": 42, "error": "" }
```

`PlanNode.on_failure` controls fan-out on failure: `abort` (default,
fails the DAG), `skip` (descendants only), `continue` (descendants run
with empty upstream output).

## Status codes

| Code | Means                                                                                  |
|------|----------------------------------------------------------------------------------------|
| 200  | Standard success.                                                                      |
| 201  | Created (POST returning a new resource).                                              |
| 202  | Accepted (`POST /api/tasks` only — the run hasn't started yet).                       |
| 204  | Success, no body (deletes / logout / session deletion).                               |
| 401  | Missing or invalid bearer token (or login failed).                                    |
| 403  | Authenticated but not allowed (e.g. signup closed, admin-only route).                 |
| 404  | Unknown id (task / manuscript / paper card / heuristic / synthesis).                  |
| 409  | Conflict (e.g. duplicate email on register).                                          |
| 413  | Request entity too large (manuscript upload above the 40 MB cap).                     |
| 415  | Unsupported file type for manuscript upload (only md/markdown/txt/pdf).               |
| 422  | Pydantic validation error (or unparseable PDF / non-utf8 markdown).                   |
| 503  | Subsystem not ready (no memory bundle, no task store/queue, auth disabled, …).        |

## Generating an OpenAPI client

If you need a client in another language, point your generator at the
running server:

```bash
curl http://localhost:8000/openapi.json > openapi.json
openapi-generator-cli generate -i openapi.json -g typescript-fetch -o client/
```

The Python SDK in `sdk/python/aaf/` is hand-written rather than
generated so it can present a more idiomatic surface (typed
sub-clients, sync facade, custom SSE iterator).
