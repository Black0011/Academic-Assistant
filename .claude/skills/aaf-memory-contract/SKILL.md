---
name: aaf-memory-contract
description: >-
  Read/write contracts for the five memory stores (Vector, Knowledge,
  Heuristic, Episodic, Session) and the MemoryBundle facade. Load when
  editing backend/memory/ or any code that touches user data.
domain: engineering
triggers:
  - memory
  - knowledge store
  - heuristic store
  - vector store
  - episodic store
  - session store
  - backend/memory
version: "1.0.0"
---

# AAF Memory — Store Contracts

See `PLAN.md` §11 for conceptual background. This skill is the source of truth for API contracts.

## 1. Ownership rule

**No code outside `backend/memory/` may touch Chroma, YAML files in `data/knowledge/`, YAML files in `data/skills/`, Postgres `episodic`/`sessions` tables, or Redis session keys directly.** Everything goes through `MemoryBundle`.

Violations caught by CI via a simple `rg -l 'chromadb|PyYAML' backend/ | grep -v memory/` check.

## 2. MemoryBundle facade

```python
@dataclass
class MemoryBundle:
    vector: VectorStore
    knowledge: KnowledgeStore
    heuristic: HeuristicStore
    episodic: EpisodicStore
    session: SessionStore

    async def snapshot(self, query: str, *, domain: str, k: int = 5) -> MemorySnapshot:
        ...
```

Instantiate **per-request** in FastAPI dependency `get_memory(user)`. The underlying store clients are singletons.

## 3. VectorStore

Backed by ChromaDB.

```python
class VectorStore:
    async def add(self, id: str, text: str, *,
                  metadata: dict[str, Any] | None = None) -> None: ...
    async def query(self, text: str, *, k: int = 5,
                    where: dict | None = None) -> list[VectorHit]: ...
    async def summary_for(self, query: str, k: int = 5) -> str:
        """Return concatenated summaries of top-k docs (LLM prompt ready)."""
    async def delete(self, id: str) -> None: ...
```

Rules:
- `id` = `paper_id` (for papers) or `note_id` (for reading notes) — globally unique.
- Embedder comes from `LLMProvider.embed(...)` of the configured embedding provider; never hard-code OpenAI here.
- Every `add` is idempotent: re-adding same id overwrites.
- Chroma collection name: `papers` (default). Don't spawn per-user collections yet.

## 4. KnowledgeStore

Backed by YAML files under `data/knowledge/`. This is where paper cards + typed_links + findings live.

```python
class KnowledgeStore:
    async def write_card(self, card: PaperCard) -> None: ...
    async def read_card(self, paper_id: str) -> PaperCard | None: ...
    async def update_card(self, paper_id: str,
                          patch: dict[str, Any]) -> PaperCard: ...
    async def delete_card(self, paper_id: str) -> None: ...
    async def link(self, a_id: str, b_id: str, *,
                   link_type: LinkType, confidence: float) -> None: ...
    async def find_related(self, query: str, *, k: int = 5) -> list[PaperCard]: ...
    async def find_cluster(self, paper_id: str,
                           min_size: int = 5) -> list[PaperCard]: ...
    async def write_findings(self, run_id: str, query: str,
                             findings: list[Finding]) -> str: ...
```

Rules:
- File layout: one `.yaml` per paper at `data/knowledge/notes/<paper_id>.yaml`. Findings batched per-run at `data/knowledge/cases/<run_id>.yaml`.
- Writes must be atomic: temp file + `os.replace`.
- `link(a, b, link_type)` writes BIDIRECTIONALLY in both YAML files.
- `typed_links` schema follows the v2.2 spec in `Academic-Agent/paper_memory.py` — preserve backward compat.
- After `write_card`, the A-Mem hook fires asynchronously (triggered via ARQ background job) to evolve typed_links.

## 5. HeuristicStore (renamed from SkillStore)

Backed by YAML files under `data/skills/<domain>/skill_<id>.yaml` + `_index.yaml`.

```python
class HeuristicStore:
    async def match(self, query: str, *, domain: str | None = None,
                    top_k: int = 3) -> list[HeuristicSkill]: ...
    async def add(self, skill: HeuristicSkill) -> str: ...
    async def bump_success(self, id: str) -> None: ...
    async def bump_failure(self, id: str) -> None: ...
    async def freeze(self, id: str) -> None: ...
    async def delete(self, id: str) -> None: ...    # soft delete → _trash/
    async def rollback_run(self, run_id: str) -> int: ...  # returns count
```

Rules:
- `domain` in {`research`, `writing`, `revision`, `rebuttal`, `survey`}.
- `match` uses the same embedding+keyword scoring as L1 Skill Matcher.
- `add` generates a deterministic 12-hex id from `(name + description).md5[:12]`.
- `delete` moves the YAML to `data/skills/_trash/<domain>/`, never rm.
- `_index.yaml` kept in sync; if stale, `rebuild_index()` regenerates from YAML files.

**Never store L1 skill definitions here.** L1 = `skills/<name>/`. Different layer entirely.

## 6. EpisodicStore

Backed by Postgres table `episodic`. Optional pgvector column.

```python
class EpisodicStore:
    async def append(self, *, type: str, content: str,
                     session_id: str | None = None,
                     metadata: dict | None = None) -> str: ...
    async def recent(self, *, n: int = 5,
                     filter: dict | None = None) -> list[Episode]: ...
    async def search(self, query: str, *, k: int = 5) -> list[Episode]: ...
```

Types: `reflection` | `observation` | `insight`. Extend by adding to `backend/memory/episodic_types.py`.

## 7. SessionStore

Backed by Redis (hot) + Postgres (`sessions`, `messages`) for cold.

```python
class SessionStore:
    async def create(self, user_id: str,
                     title: str | None = None) -> Session: ...
    async def get(self, session_id: str) -> Session | None: ...
    async def append_message(self, session_id: str,
                             msg: Message) -> None: ...
    async def history(self, session_id: str, *,
                      limit: int = 50) -> list[Message]: ...
```

Rules:
- Hot window (last N messages) stays in Redis keyed `session:{id}:hot` with TTL 24h.
- Every append also writes to Postgres `messages`.
- On session resume > 24h later, `history()` falls back to Postgres.

## 8. Consistency rules

- **Knowledge + Vector double-write**: sequence `knowledge.write_card` FIRST, then `vector.add`. If vector write fails, log and let the nightly `rebuild_chroma.py` recover.
- **Heuristic write**: YAML first (atomic), `_index.yaml` second. No transaction — tolerant of partial failure (index rebuilds fix).
- **Cross-store transactions are forbidden.** Never start a Postgres transaction that spans more than one store.

## 9. Observability

Every write must call `log.info("memory.<store>.<op>", id=..., ...)` for audit. Don't log secrets (there shouldn't be any, but still).

## 10. Testing

- In-memory fakes: `InMemoryVectorStore`, `FakeKnowledgeStore` (dict-backed), etc., in `backend/tests/helpers/memory.py`.
- Every test gets its own `MemoryBundle` built from fakes or `tmp_path`-backed real implementations.
- No CI test hits real Chroma or Postgres (use ephemeral services in integration suite only).

## 11. Migrating data from Academic-Agent

When someone reports a data-shape mismatch with the old repo, check:

1. `Academic-Agent/memory/knowledge_store.py` → `backend/memory/knowledge_store.py` — should be 90% same code.
2. `Academic-Agent/memory/skill_store.py` → `backend/memory/heuristic_store.py` — renamed.
3. `Academic-Agent/memory/paper_memory.py` → `backend/memory/paper_memory.py` — move; keep A-Mem logic intact.
4. `Academic-Agent/memory/vector_store.py` → `backend/memory/vector_store.py` — replace bespoke embedder call with `LLMProvider.embed`.

See `PLAN.md` §11.3 for the authoritative migration table.

## 12. Rollback pattern

When deleting data, prefer soft delete (move to `_trash/`) for 30 days. Hard delete only through an explicit admin job.
