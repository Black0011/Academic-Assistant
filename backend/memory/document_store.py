"""DocumentStore — free-form RAG over user-uploaded blobs (M7.3).

Two implementations sharing the same protocol:

* :class:`InMemoryDocumentStore` — dict-backed, used for tests and the
  ``MemoryBundle.in_memory()`` factory.
* :class:`YamlDocumentStore`     — persists ``KnowledgeDocument`` and
  ``DocChunk`` rows under ``<root>/<doc_id>/document.yaml`` plus
  ``<root>/<doc_id>/chunks.yaml`` with atomic tmp+rename writes.

Both implementations **require** a :class:`VectorStore` at construction
time. Every chunk written here is mirrored into the vector store with
``metadata={"kind": "doc_chunk", "doc_id": ..., ...}`` so the existing
recall paths see chunks alongside paper cards via the shared embedder.
``delete()`` and ``rollback_run()`` clean up vector entries too — the
tests for `vector_store.count()` after deletion are the gate for that
invariant (see PLAN §20.8 M7.3 DoD).
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog
import yaml

from .base import keyword_score
from .models import DocChunk, DocChunkHit, KnowledgeDocument

if TYPE_CHECKING:
    from .base import VectorStore

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Helpers shared by both backends
# ---------------------------------------------------------------------------


def make_chunk_id(doc_id: str, idx: int) -> str:
    return f"{doc_id}#{idx:04d}"


def _vector_metadata(doc: KnowledgeDocument, chunk: DocChunk) -> dict[str, Any]:
    return {
        "kind": "doc_chunk",
        "doc_id": doc.doc_id,
        "doc_title": doc.title,
        "idx": chunk.idx,
        "section_path": list(chunk.section_path),
        "tags": sorted({*doc.tags, *chunk.tags}),
        "source_kind": doc.source_kind,
        "source_run_id": doc.source_run_id,
        "user_id": doc.user_id,
    }


def _hit_from_vector(
    *,
    chunk_id: str,
    doc_title: str,
    text: str,
    score: float,
    metadata: dict[str, Any],
) -> DocChunkHit:
    raw_path = metadata.get("section_path") or []
    section_path = [str(s) for s in raw_path] if isinstance(raw_path, list) else []
    raw_tags = metadata.get("tags") or []
    tags = [str(t) for t in raw_tags] if isinstance(raw_tags, list) else []
    return DocChunkHit(
        chunk_id=chunk_id,
        doc_id=str(metadata.get("doc_id") or ""),
        doc_title=doc_title or str(metadata.get("doc_title") or ""),
        text=text,
        score=float(score),
        section_path=section_path,
        tags=tags,
    )


# ---------------------------------------------------------------------------
# In-memory impl
# ---------------------------------------------------------------------------


class InMemoryDocumentStore:
    """Dict-backed store for tests and the zero-dep bundle."""

    def __init__(self, *, vector: VectorStore) -> None:
        self._docs: dict[str, KnowledgeDocument] = {}
        self._chunks: dict[str, list[DocChunk]] = {}
        self._vector = vector
        self._lock = asyncio.Lock()

    async def write(self, document: KnowledgeDocument, chunks: list[DocChunk]) -> None:
        async with self._lock:
            existing = self._docs.get(document.doc_id)
            if existing is not None:
                # Re-index path: drop previous chunks from the vector store
                # so we don't accumulate stale entries.
                for old in self._chunks.get(document.doc_id, []):
                    await self._vector.delete(old.chunk_id)
                document = document.model_copy(
                    update={
                        "created_at": existing.created_at,
                        "updated_at": datetime.now(UTC),
                    }
                )
            self._docs[document.doc_id] = document
            self._chunks[document.doc_id] = list(chunks)
            for chunk in chunks:
                await self._vector.add(
                    chunk.chunk_id,
                    chunk.text,
                    metadata=_vector_metadata(document, chunk),
                )

    async def get(self, doc_id: str) -> KnowledgeDocument | None:
        return self._docs.get(doc_id)

    async def get_chunks(self, doc_id: str) -> list[DocChunk]:
        return list(self._chunks.get(doc_id, []))

    async def list_all(self, *, user_id: str | None = None) -> list[KnowledgeDocument]:
        docs = list(self._docs.values())
        if user_id is not None:
            docs = [d for d in docs if d.user_id == user_id]
        docs.sort(key=lambda d: d.updated_at, reverse=True)
        return docs

    async def delete(self, doc_id: str) -> bool:
        async with self._lock:
            doc = self._docs.pop(doc_id, None)
            chunks = self._chunks.pop(doc_id, [])
            if doc is None and not chunks:
                return False
            for chunk in chunks:
                await self._vector.delete(chunk.chunk_id)
            return True

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
        async with self._lock:
            existing = self._docs.get(doc_id)
            if existing is None:
                return None
            updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
            if title is not None:
                updates["title"] = title
            if summary is not None:
                updates["summary"] = summary
            if tags is not None:
                updates["tags"] = list(tags)
            if source_kind is not None:
                updates["source_kind"] = source_kind
            if source_uri is not None:
                updates["source_uri"] = source_uri
            updated = existing.model_copy(update=updates)
            self._docs[doc_id] = updated

            # Vector metadata refresh: title + tags + source_kind are
            # denormalised into chunk metadata. Re-emit each entry with
            # the new metadata. ``vector.add`` is idempotent on chunk_id
            # — overwrite semantics — so this is safe to repeat.
            if any(k in updates for k in ("title", "tags", "source_kind")):
                for chunk in self._chunks.get(doc_id, []):
                    await self._vector.add(
                        chunk.chunk_id,
                        chunk.text,
                        metadata=_vector_metadata(updated, chunk),
                    )
            return updated

    async def search_chunks(
        self, query: str, *, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[DocChunkHit]:
        scope = {"kind": "doc_chunk", **(where or {})}
        try:
            hits = await self._vector.query(query, k=k, where=scope)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("memory.documents.search_failed", err=str(exc))
            return []
        out: list[DocChunkHit] = []
        for hit in hits:
            doc_id = str(hit.metadata.get("doc_id") or "")
            doc_title = str(hit.metadata.get("doc_title") or "")
            if not doc_title:
                doc = self._docs.get(doc_id)
                doc_title = doc.title if doc else ""
            out.append(
                _hit_from_vector(
                    chunk_id=hit.doc_id,
                    doc_title=doc_title,
                    text=hit.text,
                    score=hit.score,
                    metadata=hit.metadata,
                )
            )
        return out

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            victims = [d.doc_id for d in self._docs.values() if d.source_run_id == run_id]
            for doc_id in victims:
                doc = self._docs.pop(doc_id, None)
                chunks = self._chunks.pop(doc_id, [])
                for chunk in chunks:
                    await self._vector.delete(chunk.chunk_id)
                if doc is None:
                    continue
            return len(victims)


# ---------------------------------------------------------------------------
# YAML-backed impl
# ---------------------------------------------------------------------------


class YamlDocumentStore:
    """Persistent store. Each document lives under ``<root>/<doc_id>/``.

    Layout::

        <root>/<doc_id>/document.yaml      # KnowledgeDocument
                       /chunks.yaml        # list[DocChunk]

    Reads are cached with ``asyncio.to_thread`` to keep the event loop
    unblocked. Writes use atomic tmp+rename so a crash mid-write leaves
    either the old document or the new one — never half of each.
    """

    def __init__(self, root: Path, *, vector: VectorStore) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._vector = vector
        self._lock = asyncio.Lock()

    # ---- writes -----------------------------------------------------

    async def write(self, document: KnowledgeDocument, chunks: list[DocChunk]) -> None:
        async with self._lock:
            existing = await asyncio.to_thread(self._read_document, document.doc_id)
            if existing is not None:
                for old in await asyncio.to_thread(self._read_chunks, document.doc_id):
                    await self._vector.delete(old.chunk_id)
                document = document.model_copy(
                    update={
                        "created_at": existing.created_at,
                        "updated_at": datetime.now(UTC),
                    }
                )
            await asyncio.to_thread(self._write_atomic, document, chunks)
            for chunk in chunks:
                await self._vector.add(
                    chunk.chunk_id,
                    chunk.text,
                    metadata=_vector_metadata(document, chunk),
                )

    async def delete(self, doc_id: str) -> bool:
        async with self._lock:
            chunks = await asyncio.to_thread(self._read_chunks, doc_id)
            removed = await asyncio.to_thread(self._delete_dir, doc_id)
            if not removed and not chunks:
                return False
            for chunk in chunks:
                await self._vector.delete(chunk.chunk_id)
            return True

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
        async with self._lock:
            existing = await asyncio.to_thread(self._read_document, doc_id)
            if existing is None:
                return None
            updates: dict[str, Any] = {"updated_at": datetime.now(UTC)}
            if title is not None:
                updates["title"] = title
            if summary is not None:
                updates["summary"] = summary
            if tags is not None:
                updates["tags"] = list(tags)
            if source_kind is not None:
                updates["source_kind"] = source_kind
            if source_uri is not None:
                updates["source_uri"] = source_uri
            updated = existing.model_copy(update=updates)
            chunks = await asyncio.to_thread(self._read_chunks, doc_id)
            # Atomic write keeps the on-disk doc + chunks consistent.
            await asyncio.to_thread(self._write_atomic, updated, chunks)

            if any(k in updates for k in ("title", "tags", "source_kind")):
                for chunk in chunks:
                    await self._vector.add(
                        chunk.chunk_id,
                        chunk.text,
                        metadata=_vector_metadata(updated, chunk),
                    )
            return updated

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            victims = await asyncio.to_thread(self._collect_run_victims, run_id)
            for doc_id in victims:
                chunks = await asyncio.to_thread(self._read_chunks, doc_id)
                await asyncio.to_thread(self._delete_dir, doc_id)
                for chunk in chunks:
                    await self._vector.delete(chunk.chunk_id)
            return len(victims)

    # ---- reads ------------------------------------------------------

    async def get(self, doc_id: str) -> KnowledgeDocument | None:
        return await asyncio.to_thread(self._read_document, doc_id)

    async def get_chunks(self, doc_id: str) -> list[DocChunk]:
        return await asyncio.to_thread(self._read_chunks, doc_id)

    async def list_all(self, *, user_id: str | None = None) -> list[KnowledgeDocument]:
        docs = await asyncio.to_thread(self._list_sync)
        if user_id is not None:
            docs = [d for d in docs if d.user_id == user_id]
        docs.sort(key=lambda d: d.updated_at, reverse=True)
        return docs

    async def search_chunks(
        self, query: str, *, k: int = 5, where: dict[str, Any] | None = None
    ) -> list[DocChunkHit]:
        scope = {"kind": "doc_chunk", **(where or {})}
        try:
            hits = await self._vector.query(query, k=k, where=scope)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("memory.documents.search_failed", err=str(exc))
            return []
        out: list[DocChunkHit] = []
        for hit in hits:
            doc_id = str(hit.metadata.get("doc_id") or "")
            doc_title = str(hit.metadata.get("doc_title") or "")
            if not doc_title and doc_id:
                doc = await self.get(doc_id)
                doc_title = doc.title if doc else ""
            out.append(
                _hit_from_vector(
                    chunk_id=hit.doc_id,
                    doc_title=doc_title,
                    text=hit.text,
                    score=hit.score,
                    metadata=hit.metadata,
                )
            )
        return out

    # ---- sync helpers ----------------------------------------------

    def _doc_dir(self, doc_id: str) -> Path:
        return self._root / doc_id

    def _read_document(self, doc_id: str) -> KnowledgeDocument | None:
        path = self._doc_dir(doc_id) / "document.yaml"
        if not path.exists():
            return None
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return KnowledgeDocument.model_validate(data)
        except Exception as exc:
            log.warning("memory.documents.bad_yaml", path=str(path), err=str(exc))
            return None

    def _read_chunks(self, doc_id: str) -> list[DocChunk]:
        path = self._doc_dir(doc_id) / "chunks.yaml"
        if not path.exists():
            return []
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            return [DocChunk.model_validate(item) for item in raw]
        except Exception as exc:
            log.warning("memory.documents.bad_chunks_yaml", path=str(path), err=str(exc))
            return []

    def _write_atomic(self, document: KnowledgeDocument, chunks: list[DocChunk]) -> None:
        d = self._doc_dir(document.doc_id)
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write_yaml(d / "document.yaml", document.model_dump(mode="json"))
        _atomic_write_yaml(
            d / "chunks.yaml",
            [c.model_dump(mode="json") for c in chunks],
        )

    def _delete_dir(self, doc_id: str) -> bool:
        path = self._doc_dir(doc_id)
        if not path.exists():
            return False
        for child in sorted(path.glob("*"), reverse=True):
            child.unlink(missing_ok=True)
        try:
            path.rmdir()
        except OSError:
            return False
        return True

    def _list_sync(self) -> list[KnowledgeDocument]:
        if not self._root.exists():
            return []
        out: list[KnowledgeDocument] = []
        for child in sorted(self._root.glob("*")):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue
            doc = self._read_document(child.name)
            if doc is not None:
                out.append(doc)
        return out

    def _collect_run_victims(self, run_id: str) -> list[str]:
        victims: list[str] = []
        for doc in self._list_sync():
            if doc.source_run_id == run_id:
                victims.append(doc.doc_id)
        return victims


# ---------------------------------------------------------------------------
# Free-standing helpers
# ---------------------------------------------------------------------------


def _atomic_write_yaml(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=".aaf-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        os.replace(tmp_path, path)
    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise


def heuristic_summary(text: str, *, max_chars: int = 320) -> str:
    """Cheap fallback summary used when no LLM is wired in.

    Picks the first ~max_chars of meaningful (non-blank, non-heading)
    text. Good enough for the UI list; the workflow may upgrade later.
    """
    out: list[str] = []
    used = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        chunk = stripped if used == 0 else " " + stripped
        if used + len(chunk) > max_chars:
            out.append(chunk[: max(0, max_chars - used)] + "…")
            break
        out.append(chunk)
        used += len(chunk)
    return "".join(out)


# Re-export the keyword scorer so callers don't have to reach into base.
__all__ = [
    "InMemoryDocumentStore",
    "YamlDocumentStore",
    "heuristic_summary",
    "keyword_score",
    "make_chunk_id",
]
