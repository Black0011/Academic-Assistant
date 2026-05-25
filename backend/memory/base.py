"""Store protocols + MemoryBundle.

Four design rules the framework relies on (PLAN §11.3-§11.5):

1. Every store exposes an **async** protocol; every agent/workflow talks
   only to the protocol, never to a concrete backend.
2. Backends are swappable — dev/test uses in-process impls, prod uses
   ChromaDB + Postgres + Redis variants that ship in M2-S2.
3. The :class:`MemoryBundle` is the only object workflows hold. It owns
   the five stores and implements :meth:`snapshot` for one-shot reads.
4. All writes accept a ``source_run_id`` so rollback stays trivial.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections.abc import Awaitable, Iterable
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from .models import (
    DocChunk,
    DocChunkHit,
    Heuristic,
    KnowledgeDocument,
    MemorySnapshot,
    PaperCard,
    Reflection,
    SessionContext,
    SessionMessage,
    SynthesisNote,
    TypedLink,
    VectorHit,
)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# ID helpers — exported for callers that don't want to invent their own.
# ---------------------------------------------------------------------------


def gen_id(prefix: str = "") -> str:
    """Random hex id; 12 chars + optional prefix. Matches the L3 YAML spec."""
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}{raw}" if prefix else raw


def stable_id(*parts: str) -> str:
    """Deterministic 12-hex id from any inputs (handy for paper_id)."""
    digest = hashlib.sha1("||".join(parts).encode("utf-8")).hexdigest()
    return digest[:12]


# ---------------------------------------------------------------------------
# Store protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class VectorStore(Protocol):
    async def add(
        self, doc_id: str, text: str, *, metadata: dict[str, Any] | None = None
    ) -> None: ...

    async def query(
        self, text: str, *, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[VectorHit]: ...

    async def get(self, doc_id: str) -> VectorHit | None: ...

    async def delete(self, doc_id: str) -> bool: ...

    async def summary_for(self, query: str, *, k: int = 5, max_chars: int = 1000) -> str: ...

    async def count(self) -> int: ...


@runtime_checkable
class KnowledgeStore(Protocol):
    async def write_card(self, card: PaperCard) -> None: ...

    async def get(self, paper_id: str) -> PaperCard | None: ...

    async def list_all(self) -> list[PaperCard]: ...

    async def find_related(self, query: str, *, k: int = 5) -> list[PaperCard]: ...

    async def link(
        self, a: str, b: str, link_type: str, *, evidence: str = "", bidirectional: bool = True
    ) -> None: ...

    async def delete(self, paper_id: str) -> bool: ...

    async def rollback_run(self, run_id: str) -> int: ...

    # ---- synthesis (A-Mem cluster-level notes, PLAN §11.7) -----------

    async def write_synthesis(self, note: SynthesisNote) -> None: ...

    async def get_synthesis(self, cluster_tag: str) -> SynthesisNote | None: ...

    async def list_synthesis(self) -> list[SynthesisNote]: ...

    async def delete_synthesis(self, cluster_tag: str) -> bool: ...


@runtime_checkable
class HeuristicStore(Protocol):
    async def add(self, skill: Heuristic) -> None: ...

    async def get(self, id_: str) -> Heuristic | None: ...

    async def match(
        self, query: str, *, domain: str | None = None, top_k: int = 3
    ) -> list[Heuristic]: ...

    async def bump_success(self, id_: str) -> None: ...

    async def bump_failure(self, id_: str) -> None: ...

    async def freeze(self, id_: str) -> None: ...

    async def delete(self, id_: str) -> bool: ...

    async def list_by_domain(self, domain: str) -> list[Heuristic]: ...

    async def rollback_run(self, run_id: str) -> int: ...


@runtime_checkable
class EpisodicStore(Protocol):
    async def append(self, reflection: Reflection) -> None: ...

    async def recent(
        self,
        *,
        n: int = 3,
        type: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> list[Reflection]: ...

    async def rollback_run(self, run_id: str) -> int: ...

    # P14.A — manual CRUD support. ``get`` powers PATCH-then-return; ``update``
    # is partial (None values mean "leave unchanged"); ``delete`` is single-row;
    # ``delete_by`` is the bulk path keyed on session_id / source_run_id (the
    # two facets users actually want to clean by — never by user_id, that's a
    # rollback-style operation already handled by rollback_run).
    async def get(self, id_: str) -> Reflection | None: ...

    async def update(
        self,
        id_: str,
        *,
        type: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> Reflection | None: ...

    async def delete(self, id_: str) -> bool: ...

    async def delete_by(
        self,
        *,
        session_id: str | None = None,
        source_run_id: str | None = None,
    ) -> int: ...


@runtime_checkable
class DocumentStore(Protocol):
    """Free-form document RAG store (M7.3).

    Each ``write`` chunks the document, persists the :class:`KnowledgeDocument`
    + :class:`DocChunk` rows, **and** registers every chunk with the shared
    :class:`VectorStore` (``kind="doc_chunk"`` metadata) so retrieval is a
    single vector query at recall time.
    """

    async def write(self, document: KnowledgeDocument, chunks: list[DocChunk]) -> None: ...

    async def get(self, doc_id: str) -> KnowledgeDocument | None: ...

    async def get_chunks(self, doc_id: str) -> list[DocChunk]: ...

    async def list_all(self, *, user_id: str | None = None) -> list[KnowledgeDocument]: ...

    async def delete(self, doc_id: str) -> bool: ...

    async def search_chunks(
        self, query: str, *, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[DocChunkHit]: ...

    async def rollback_run(self, run_id: str) -> int: ...

    async def update_metadata(
        self,
        doc_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        tags: list[str] | None = None,
        source_kind: str | None = None,
        source_uri: str | None = None,
    ) -> KnowledgeDocument | None:
        """P14.B — partial metadata update.

        ``None`` per field means "leave alone" (same partial-update
        contract as :meth:`EpisodicStore.update`). We deliberately do
        NOT expose ``raw_text`` mutation through this path:

        1. Editing raw_text without re-chunking would silently desync
           the persisted ``raw_text`` from the vector embeddings — every
           subsequent search_chunks would lie about what's in the doc.
        2. Re-chunking + re-embedding belongs to ``write`` (alias for
           reindex in the docs router); doing it on the side here would
           hide a heavyweight operation behind a "metadata edit" verb.

        Title changes DO cascade to vector metadata (``doc_title`` is
        denormalised into chunk metadata for cheap rendering); the impl
        is responsible for refreshing those entries idempotently.
        """
        ...


@runtime_checkable
class SessionStore(Protocol):
    async def create(self, session: SessionContext) -> None: ...

    async def get(self, session_id: str) -> SessionContext | None: ...

    async def update(self, session_id: str, **updates: Any) -> SessionContext: ...

    async def append_message(self, session_id: str, message: SessionMessage) -> None: ...

    async def delete(self, session_id: str) -> bool: ...

    async def list_for_user(self, user_id: str) -> list[SessionContext]: ...


# ---------------------------------------------------------------------------
# MemoryBundle aggregate
# ---------------------------------------------------------------------------


@dataclass
class MemoryBundle:
    """Single object that workflows hold.

    Concrete backends are injected at construction time (FastAPI lifespan
    wires the right variant based on settings). Tests use
    :meth:`in_memory` for a zero-dependency bundle.
    """

    vector: VectorStore
    knowledge: KnowledgeStore
    heuristic: HeuristicStore
    episodic: EpisodicStore
    session: SessionStore
    documents: DocumentStore | None = None

    async def snapshot(
        self,
        query: str,
        *,
        domain: str = "",
        k: int = 5,
        session_id: str | None = None,
    ) -> MemorySnapshot:
        """Single parallelisable read used by Planner (§11.4).

        M7.3: when a ``DocumentStore`` is wired in, ``doc_chunks`` is populated
        in parallel and merged into the snapshot. Callers can render either
        list or use ``MemorySnapshot.recall_text()`` for a flat prompt slice.

        P10 — defence in depth: each leg runs in its own try/except so a
        single failing store (broken embedder, missing SQL table, etc.)
        cannot abort the whole ``recall`` stage. The user-visible cost
        is one missing recall signal; the cost of letting an exception
        escape is a wholly failed task. The latter is unacceptable.
        """
        import structlog

        log = structlog.get_logger(__name__)

        async def _safe(coro: Awaitable[T], *, leg: str, default: T) -> T:
            try:
                return await coro
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("memory.snapshot.leg_failed", leg=leg, err=str(exc))
                return default

        vector_summary = await _safe(
            self.vector.summary_for(query, k=k), leg="vector", default=""
        )
        related = await _safe(
            self.knowledge.find_related(query, k=k), leg="knowledge", default=[]
        )
        heuristics = await _safe(
            self.heuristic.match(query, domain=domain or None, top_k=3),
            leg="heuristic",
            default=[],
        )
        recent = await _safe(
            self.episodic.recent(n=3, type="reflection", session_id=session_id),
            leg="episodic",
            default=[],
        )
        doc_chunks: list[DocChunkHit] = []
        if self.documents is not None:
            doc_chunks = await _safe(
                self.documents.search_chunks(query, k=k), leg="documents", default=[]
            )
        return MemorySnapshot(
            query=query,
            domain=domain,
            vector_summary=vector_summary,
            related_papers=related,
            heuristics=heuristics,
            recent_reflections=recent,
            doc_chunks=doc_chunks,
        )

    @classmethod
    def in_memory(cls) -> MemoryBundle:
        """Zero-dependency bundle for tests & offline smoke runs."""
        # Local imports to avoid circular (the impls depend on base.py).
        from .document_store import InMemoryDocumentStore
        from .episodic_store import InMemoryEpisodicStore
        from .heuristic_store import InMemoryHeuristicStore
        from .knowledge_store import InMemoryKnowledgeStore
        from .session_store import InMemorySessionStore
        from .vector_store import InMemoryVectorStore

        vector = InMemoryVectorStore()
        return cls(
            vector=vector,
            knowledge=InMemoryKnowledgeStore(),
            heuristic=InMemoryHeuristicStore(),
            episodic=InMemoryEpisodicStore(),
            session=InMemorySessionStore(),
            documents=InMemoryDocumentStore(vector=vector),
        )


# ---------------------------------------------------------------------------
# Shared helpers for backend impls
# ---------------------------------------------------------------------------


def cosine(a: Iterable[float], b: Iterable[float]) -> float:
    av = list(a)
    bv = list(b)
    if not av or not bv or len(av) != len(bv):
        return 0.0
    dot = sum(x * y for x, y in zip(av, bv, strict=False))
    na = sum(x * x for x in av) ** 0.5
    nb = sum(x * x for x in bv) ** 0.5
    if na == 0.0 or nb == 0.0:
        return 0.0
    return (dot / (na * nb) + 1.0) / 2.0  # map [-1, 1] → [0, 1]


def keyword_score(query: str, text: str) -> float:
    """Cheap overlap score used when no embedder is available."""
    import re

    tok = re.compile(r"[A-Za-z\u4e00-\u9fa5]+")
    q = {t.lower() for t in tok.findall(query)}
    if not q:
        return 0.0
    d = {t.lower() for t in tok.findall(text)}
    if not d:
        return 0.0
    overlap = q & d
    return len(overlap) / max(4.0, len(q))


def now_monotonic_ns() -> int:
    return time.monotonic_ns()


__all__ = [
    "DocChunk",  # convenience re-export
    "DocChunkHit",  # convenience re-export
    "DocumentStore",
    "EpisodicStore",
    "HeuristicStore",
    "KnowledgeDocument",  # convenience re-export
    "KnowledgeStore",
    "MemoryBundle",
    "SessionStore",
    "TypedLink",  # convenience re-export
    "VectorStore",
    "cosine",
    "gen_id",
    "keyword_score",
    "stable_id",
]
