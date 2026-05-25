"""ChromaDB-backed VectorStore (PLAN §11.3).

The dependency (``chromadb``) ships under the ``memory`` extra. When the
package is missing the module still imports — :class:`ChromaVectorStore`
raises a clear :class:`MemoryError` at construction time so callers get a
helpful message rather than an ImportError deep in the stack.

Semantics match :class:`backend.memory.vector_store.InMemoryVectorStore`
bit-for-bit:

* ``add(doc_id, text, metadata=None)``
* ``query(text, k=5, where=None)``  — returns :class:`VectorHit`
* ``get(doc_id)`` / ``delete(doc_id)`` / ``count()``
* ``summary_for(query, k, max_chars)``
* ``set_embedder(llm)`` — swaps the embedder and wipes cached vectors

Chroma supports its own default sentence-transformer embedder; we opt
**out** by passing ``embedding_function=None`` so the whole framework
shares one embedding space driven by :class:`LLMProvider.embed`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.errors import MemoryError as AAFMemoryError
from backend.core.errors import MemoryNotFound

from .models import VectorHit

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


def _load_chromadb() -> Any:
    try:
        import chromadb
    except ImportError as exc:  # pragma: no cover — exercised via tests with skipif
        raise AAFMemoryError(
            "chromadb is not installed. Install with `uv sync --extra memory`.",
        ) from exc
    return chromadb


class ChromaVectorStore:
    """Persistent or ephemeral Chroma collection. Thread-safe for single-process use."""

    def __init__(
        self,
        *,
        collection_name: str = "aaf_memory",
        persist_dir: Path | str | None = None,
        embedder: LLMProvider | None = None,
        embedding_model: str | None = None,
    ) -> None:
        chroma = _load_chromadb()
        if persist_dir:
            persist_path = Path(persist_dir).expanduser()
            persist_path.mkdir(parents=True, exist_ok=True)
            self._client = chroma.PersistentClient(path=str(persist_path))
        else:
            # Ephemeral (in-process) client — great for tests.
            self._client = chroma.EphemeralClient()
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,  # we manage embeddings explicitly
            metadata={"hnsw:space": "cosine"},
        )
        self._embedder = embedder
        self._embedding_model = embedding_model
        self._lock = asyncio.Lock()

    # ---- admin ------------------------------------------------------

    def set_embedder(self, embedder: LLMProvider | None) -> None:
        """Swap the embedder. Wipes the collection because the embedding
        space just changed — refusing to silently mix spaces."""
        self._embedder = embedder
        # Chroma has no "clear by collection" verb; recreate instead.
        name = self._collection.name
        self._client.delete_collection(name)
        self._collection = self._client.get_or_create_collection(
            name=name, embedding_function=None, metadata={"hnsw:space": "cosine"}
        )

    async def count(self) -> int:
        return await asyncio.to_thread(self._collection.count)

    # ---- writes -----------------------------------------------------

    async def add(self, doc_id: str, text: str, *, metadata: dict[str, Any] | None = None) -> None:
        async with self._lock:
            await asyncio.to_thread(self._add_sync, doc_id, text, dict(metadata or {}))

    async def delete(self, doc_id: str) -> bool:
        async with self._lock:
            present = await self.get(doc_id)
            if present is None:
                return False
            await asyncio.to_thread(self._collection.delete, ids=[doc_id])
            return True

    # ---- reads ------------------------------------------------------

    async def get(self, doc_id: str) -> VectorHit | None:
        data = await asyncio.to_thread(
            self._collection.get,
            ids=[doc_id],
            include=["documents", "metadatas"],
        )
        if not data or not data.get("ids") or not data["ids"]:
            return None
        texts = data.get("documents") or [""]
        metas = data.get("metadatas") or [{}]
        return VectorHit(
            doc_id=doc_id,
            score=1.0,
            text=texts[0] if texts else "",
            metadata=metas[0] if metas else {},
        )

    async def query(
        self, text: str, *, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[VectorHit]:
        if k <= 0:
            return []
        query_vec = await self._embed([text])
        if not query_vec:
            # No embedder available — can't query semantically. Return [].
            log.warning("memory.chroma.no_embedder")
            return []
        # Chroma's where filter accepts exact-equality dict directly.
        result = await asyncio.to_thread(
            self._collection.query,
            query_embeddings=query_vec,
            n_results=k,
            where=where or None,
            include=["documents", "metadatas", "distances"],
        )
        return _result_to_hits(result)

    async def summary_for(self, query: str, *, k: int = 5, max_chars: int = 1000) -> str:
        hits = await self.query(query, k=k)
        if not hits:
            return ""
        parts: list[str] = []
        used = 0
        for h in hits:
            snippet = f"- ({h.doc_id}) {h.text}".strip()
            if used + len(snippet) > max_chars:
                parts.append(snippet[: max(0, max_chars - used)] + "…")
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

    def _add_sync(self, doc_id: str, text: str, metadata: dict[str, Any]) -> None:
        # Chroma rejects empty metadata dicts — use a tiny placeholder.
        meta = metadata if metadata else {"_": ""}
        self._collection.upsert(
            ids=[doc_id],
            documents=[text],
            embeddings=self._sync_embed([text]) if self._embedder is not None else None,
            metadatas=[meta],
        )

    async def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if self._embedder is None:
            return None
        try:
            return await self._embedder.embed(texts, model=self._embedding_model)
        except Exception as exc:
            log.warning("memory.chroma.embed_failed", err=str(exc))
            return None

    def _sync_embed(self, texts: list[str]) -> list[list[float]] | None:
        """Bridge: call the async embedder from a sync context (thread pool)."""
        if self._embedder is None:
            return None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
        if loop.is_running():
            # Already inside a loop — the sync path is only used when a thread
            # is already awaiting `_add_sync` via asyncio.to_thread, so we
            # schedule on the same loop using run_coroutine_threadsafe.
            fut = asyncio.run_coroutine_threadsafe(
                self._embedder.embed(texts, model=self._embedding_model), loop
            )
            try:
                return fut.result()
            except Exception as exc:
                log.warning("memory.chroma.embed_failed", err=str(exc))
                return None
        try:
            return loop.run_until_complete(self._embedder.embed(texts, model=self._embedding_model))
        except Exception as exc:
            log.warning("memory.chroma.embed_failed", err=str(exc))
            return None


def _result_to_hits(result: Any) -> list[VectorHit]:
    """Translate a Chroma ``query`` result (list-of-list) into VectorHit[]."""
    if not result:
        return []
    ids = (result.get("ids") or [[]])[0]
    docs = (result.get("documents") or [[]])[0]
    metas = (result.get("metadatas") or [[]])[0]
    dists = (result.get("distances") or [[]])[0]
    hits: list[VectorHit] = []
    for i, doc_id in enumerate(ids):
        text = docs[i] if i < len(docs) else ""
        metadata = metas[i] if i < len(metas) else {}
        # Cosine distance ∈ [0, 2]. Convert to score ∈ [0, 1].
        dist = dists[i] if i < len(dists) else 0.0
        score = max(0.0, min(1.0, 1.0 - dist / 2.0))
        # Drop internal placeholder key.
        if isinstance(metadata, dict) and "_" in metadata and metadata["_"] == "":
            metadata = {k: v for k, v in metadata.items() if k != "_"}
        hits.append(VectorHit(doc_id=doc_id, score=score, text=text or "", metadata=metadata))
    return hits


__all__ = ["ChromaVectorStore"]
