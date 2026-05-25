# backend/memory/AGENTS.md

Six stores, one bundle. The whole subsystem is read/written through
`MemoryBundle`; nothing else is allowed to import a store directly.

## Stores

| Store         | Role                                              | Default backend  |
| ------------- | ------------------------------------------------- | ---------------- |
| `vector`      | Embedding-indexed text (papers, chunks, snippets) | ChromaDB         |
| `knowledge`   | Structured `PaperCard` + `SynthesisNote`          | YAML on disk     |
| `heuristic`   | L3 learned strategies (`Heuristic`)               | YAML on disk     |
| `episodic`    | Reflections + run-tied audit trail                | Postgres / SQLite|
| `session`     | User chat sessions + message history              | Redis / Postgres |
| `documents`   | Free-form `KnowledgeDocument` + `DocChunk` (RAG)  | YAML on disk     | <!-- M7.3 ✅ -->

> M7.3 ships `documents` (`InMemoryDocumentStore` / `YamlDocumentStore` under `data/documents/<doc_id>/`). Every chunk write **also** updates `vector` with `metadata.kind="doc_chunk"` so `MemoryBundle.snapshot()` returns PaperCards and DocChunks side-by-side. Deletes / `rollback_run()` cascade — the `vector.count()` invariant is the canonical leak detector (see `backend/tests/unit/test_document_store.py`).

## Hard invariants

- All public methods are `async`.
- Mutations record a `run_id` so we can roll back via
  `POST /api/memory/rollback/{run_id}`.
- Knowledge cards and synthesis notes are **versioned** (bump, never
  overwrite in place).
- Heuristics support `freeze` / `unfreeze` so a bad strategy can be
  silenced without deletion.
- **Manual editing surfaces deliberately exclude provenance / source-of-truth fields**:
  - `EpisodicStore.update()` will not touch `id` / `user_id` / `session_id` /
    `source_run_id` / `created_at` (these are rely-on facets for rollback +
    session timeline; rewriting them silently breaks two callers).
  - `DocumentStore.update_metadata()` will not touch `raw_text` (changing
    raw text without re-chunking puts the persisted text and the vector
    embeddings out of sync; reindex is the supported path).
  - `EpisodicStore.delete_by()` is **AND-semantics** — empty filter is a
    no-op; the HTTP layer additionally returns 400 to refuse unbounded deletes.
  - `SkillAdmin.update_edges()` rewrites only `compatibility.upstream` /
    `.downstream` (and legacy top-level `downstream_skills`) — body / scripts
    are byte-for-byte preserved. Frontmatter inline `#` comments are lost
    and surfaced via `report.warnings`; we accept the trade-off rather than
    add `ruamel.yaml`.

## Touching the schema

Schema changes = an Alembic migration in
`backend/db/alembic/versions/`. The consistency check fails the build if
a SQLAlchemy model adds columns without a migration referencing them.

```bash
make migrate-new msg="add manuscript word_count"
make migrate                # apply locally
```

## When to write to which store

| Need                                                  | Write to              |
| ----------------------------------------------------- | --------------------- |
| Cite-able fact or paper                               | `knowledge`           |
| Cluster-level synthesis across N papers               | `knowledge.synthesis` |
| "Strategy X works for problem Y" (learned)            | `heuristic`           |
| "Run 1234 failed because Z"                           | `episodic`            |
| A user message in a chat                              | `session`             |
| Raw embedding for retrieval                           | `vector`              |
| Free-form note / PDF / blog post the user uploaded    | `documents` (M7.3)    |

If the same content lands in two stores, you probably want **one** with a
reference, not duplication. The unique key for a `PaperCard` is
`paper_id` (DOI / arXiv id / URL hash); for a `SynthesisNote` it's
`cluster_tag`; for a `Heuristic` it's `id`.

## A-Mem evolution

`PaperMemoryEvolver` runs after each research workflow:

1. Reads recent reflections + new cards.
2. Promotes high-confidence patterns to L3 heuristics.
3. Emits `memory.write` events for the audit trail.

It is **idempotent**. Re-running on the same input is a no-op.

## Tests

- Each store has a unit test parameterised over its in-memory + persistent
  variants (see `tests/unit/test_*_store.py`).
- The `/api/memory/*` integration tests cover the admin surface and are
  the canonical examples for cross-store flows.
