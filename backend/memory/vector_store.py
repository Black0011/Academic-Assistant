"""In-process VectorStore — cosine similarity with keyword fallback.

Real ChromaDB-backed store ships in M2 stage 2. This impl exists so the
whole framework can boot, run DemoWorkflow, and execute integration tests
with zero external dependencies.

Contract (protocol in backend/memory/base.py):
    * ``add``      — store (doc_id, text, metadata); recompute embedding lazily
    * ``query``    — top-k by cosine(query, doc) or keyword_score fallback
    * ``summary_for`` — concat of top-k texts, capped at ``max_chars``
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.errors import MemoryNotFound

from .base import cosine, keyword_score
from .models import VectorHit

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


class InMemoryVectorStore:
    """Dict-backed vector store — tests, offline dev, and small corpora.

    An optional :class:`LLMProvider` embedder enables real semantic search.
    When no embedder is wired the store degrades gracefully to keyword
    overlap so callers still get sensible results.
    """

    def __init__(
        self,
        *,
        embedder: LLMProvider | None = None,
        embedding_model: str | None = None,
    ) -> None:
        self._docs: dict[str, dict[str, Any]] = {}
        self._vectors: dict[str, list[float]] = {}
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._lock = asyncio.Lock()

    # ---- admin ------------------------------------------------------

    def set_embedder(self, embedder: LLMProvider | None) -> None:
        self._embedder = embedder
        # Invalidate — new embedder implies new embedding space.
        self._vectors.clear()

    async def count(self) -> int:
        return len(self._docs)

    # ---- writes -----------------------------------------------------

    async def add(self, doc_id: str, text: str, *, metadata: dict[str, Any] | None = None) -> None:
        async with self._lock:
            self._docs[doc_id] = {"text": text, "metadata": dict(metadata or {})}
            # Drop any stale embedding; it's re-computed on next query.
            self._vectors.pop(doc_id, None)

    async def delete(self, doc_id: str) -> bool:
        async with self._lock:
            present = doc_id in self._docs
            self._docs.pop(doc_id, None)
            self._vectors.pop(doc_id, None)
            return present

    # ---- reads ------------------------------------------------------

    async def get(self, doc_id: str) -> VectorHit | None:
        entry = self._docs.get(doc_id)
        if entry is None:
            return None
        return VectorHit(doc_id=doc_id, score=1.0, text=entry["text"], metadata=entry["metadata"])

    async def query(
        self, text: str, *, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[VectorHit]:
        if not self._docs:
            return []

        candidates = self._filter(where)
        if not candidates:
            return []

        scores: list[tuple[str, float]] = []
        if self._embedder is not None:
            await self._ensure_embeddings(candidates)
            try:
                query_vec = (await self._embedder.embed([text], model=self._embedding_model))[0]
            except Exception as exc:
                log.warning("memory.vector.embed_query_failed", err=str(exc))
                query_vec = None
            if query_vec is not None:
                for doc_id in candidates:
                    v = self._vectors.get(doc_id)
                    scores.append((doc_id, cosine(query_vec, v) if v else 0.0))
        if not scores:
            for doc_id in candidates:
                scores.append((doc_id, keyword_score(text, self._docs[doc_id]["text"])))

        scores.sort(key=lambda s: s[1], reverse=True)
        top = scores[: max(0, k)]
        return [
            VectorHit(
                doc_id=doc_id,
                score=score,
                text=self._docs[doc_id]["text"],
                metadata=self._docs[doc_id]["metadata"],
            )
            for doc_id, score in top
        ]

    async def summary_for(self, query: str, *, k: int = 5, max_chars: int = 1000) -> str:
        hits = await self.query(query, k=k)
        if not hits:
            return ""
        parts: list[str] = []
        used = 0
        for h in hits:
            snippet = f"- ({h.doc_id}) {h.text}".strip()
            if used + len(snippet) > max_chars:
                snippet = snippet[: max(0, max_chars - used)] + "…"
                parts.append(snippet)
                break
            parts.append(snippet)
            used += len(snippet)
        return "\n".join(parts)

    async def require(self, doc_id: str) -> VectorHit:
        hit = await self.get(doc_id)
        if hit is None:
            raise MemoryNotFound(f"vector doc not found: {doc_id}", store="vector", id=doc_id)
        return hit

    # ---- internals --------------------------------------------------

    def _filter(self, where: dict[str, Any] | None) -> list[str]:
        if not where:
            return list(self._docs.keys())
        matching: list[str] = []
        for doc_id, entry in self._docs.items():
            meta = entry["metadata"]
            if all(meta.get(k) == v for k, v in where.items()):
                matching.append(doc_id)
        return matching

    async def _ensure_embeddings(self, doc_ids: list[str]) -> None:
        if self._embedder is None:
            return
        missing = [doc_id for doc_id in doc_ids if doc_id not in self._vectors]
        if not missing:
            return
        texts = [self._docs[doc_id]["text"] for doc_id in missing]
        try:
            vectors = await self._embedder.embed(texts, model=self._embedding_model)
        except Exception as exc:
            log.warning("memory.vector.embed_docs_failed", err=str(exc), count=len(missing))
            return
        for doc_id, vec in zip(missing, vectors, strict=False):
            self._vectors[doc_id] = vec


__all__ = ["InMemoryVectorStore"]
