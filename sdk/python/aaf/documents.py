"""``/api/documents/*`` sub-client (M7.3 — Knowledge Library / RAG).

Mirrors :mod:`backend.api.routers.documents`. Both async and sync facades
share the same surface; either accept a typed payload or a raw ``dict``
for callers who'd rather not import the DTOs.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .models import (
    DocChunk,
    DocChunkHit,
    IngestDocumentResponse,
    KnowledgeDocument,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


def _qs(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v not in (None, "", [])}


def _multipart_fields(
    *,
    title: str | None,
    tags: list[str] | None,
    source_kind: str | None,
    source_uri: str | None,
    target_tokens: int | None,
    overlap_tokens: int | None,
) -> dict[str, str]:
    out: dict[str, str] = {}
    if title is not None:
        out["title"] = title
    if tags:
        out["tags"] = ", ".join(tags)
    if source_kind:
        out["source_kind"] = source_kind
    if source_uri:
        out["source_uri"] = source_uri
    if target_tokens is not None:
        out["target_tokens"] = str(target_tokens)
    if overlap_tokens is not None:
        out["overlap_tokens"] = str(overlap_tokens)
    return out


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class AsyncDocumentsAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(
        self,
        *,
        user_id: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeDocument]:
        body = await self._client.request_json(
            "GET",
            "/api/documents",
            params=_qs(
                {"user_id": user_id, "tag": tag, "limit": limit, "offset": offset}
            ),
        )
        return [KnowledgeDocument.model_validate(it) for it in (body or {}).get("items", [])]

    async def get(self, doc_id: str) -> KnowledgeDocument:
        body = await self._client.request_json("GET", f"/api/documents/{doc_id}")
        return KnowledgeDocument.model_validate(body)

    async def get_chunks(
        self, doc_id: str, *, offset: int = 0, limit: int = 100
    ) -> list[DocChunk]:
        body = await self._client.request_json(
            "GET",
            f"/api/documents/{doc_id}/chunks",
            params={"offset": offset, "limit": limit},
        )
        return [DocChunk.model_validate(it) for it in (body or {}).get("items", [])]

    async def ingest_text(
        self,
        *,
        title: str = "",
        raw_text: str,
        source_kind: str = "note",
        source_uri: str = "",
        summary: str = "",
        tags: list[str] | None = None,
        target_tokens: int = 800,
        overlap_tokens: int = 100,
    ) -> IngestDocumentResponse:
        payload: dict[str, Any] = {
            "title": title,
            "raw_text": raw_text,
            "source_kind": source_kind,
            "source_uri": source_uri,
            "summary": summary,
            "tags": list(tags or []),
            "target_tokens": target_tokens,
            "overlap_tokens": overlap_tokens,
        }
        body = await self._client.request_json(
            "POST", "/api/documents/ingest", json_body=payload
        )
        return IngestDocumentResponse.model_validate(body)

    async def ingest_file(
        self,
        path: str | Path,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        source_kind: str | None = None,
        source_uri: str | None = None,
        target_tokens: int = 800,
        overlap_tokens: int = 100,
    ) -> IngestDocumentResponse:
        p = Path(path)
        files = {"file": (p.name, p.read_bytes(), _guess_mime(p))}
        body = await self._client.request_json(
            "POST",
            "/api/documents/ingest",
            files=files,
            data=_multipart_fields(
                title=title,
                tags=tags,
                source_kind=source_kind,
                source_uri=source_uri,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
            ),
        )
        return IngestDocumentResponse.model_validate(body)

    async def reindex(
        self, doc_id: str, *, target_tokens: int = 800, overlap_tokens: int = 100
    ) -> IngestDocumentResponse:
        body = await self._client.request_json(
            "POST",
            f"/api/documents/{doc_id}:reindex",
            json_body={"target_tokens": target_tokens, "overlap_tokens": overlap_tokens},
        )
        return IngestDocumentResponse.model_validate(body)

    async def delete(self, doc_id: str) -> None:
        await self._client.request_json("DELETE", f"/api/documents/{doc_id}")

    async def search(
        self,
        q: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[DocChunkHit]:
        body = await self._client.request_json(
            "POST",
            "/api/documents/search",
            json_body={"q": q, "top_k": top_k, "filters": filters or {}},
        )
        return [DocChunkHit.model_validate(it) for it in (body or {}).get("items", [])]


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class DocumentsAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(
        self,
        *,
        user_id: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[KnowledgeDocument]:
        body = self._client.request_json(
            "GET",
            "/api/documents",
            params=_qs(
                {"user_id": user_id, "tag": tag, "limit": limit, "offset": offset}
            ),
        )
        return [KnowledgeDocument.model_validate(it) for it in (body or {}).get("items", [])]

    def get(self, doc_id: str) -> KnowledgeDocument:
        body = self._client.request_json("GET", f"/api/documents/{doc_id}")
        return KnowledgeDocument.model_validate(body)

    def get_chunks(
        self, doc_id: str, *, offset: int = 0, limit: int = 100
    ) -> list[DocChunk]:
        body = self._client.request_json(
            "GET",
            f"/api/documents/{doc_id}/chunks",
            params={"offset": offset, "limit": limit},
        )
        return [DocChunk.model_validate(it) for it in (body or {}).get("items", [])]

    def ingest_text(
        self,
        *,
        title: str = "",
        raw_text: str,
        source_kind: str = "note",
        source_uri: str = "",
        summary: str = "",
        tags: list[str] | None = None,
        target_tokens: int = 800,
        overlap_tokens: int = 100,
    ) -> IngestDocumentResponse:
        body = self._client.request_json(
            "POST",
            "/api/documents/ingest",
            json_body={
                "title": title,
                "raw_text": raw_text,
                "source_kind": source_kind,
                "source_uri": source_uri,
                "summary": summary,
                "tags": list(tags or []),
                "target_tokens": target_tokens,
                "overlap_tokens": overlap_tokens,
            },
        )
        return IngestDocumentResponse.model_validate(body)

    def ingest_file(
        self,
        path: str | Path,
        *,
        title: str | None = None,
        tags: list[str] | None = None,
        source_kind: str | None = None,
        source_uri: str | None = None,
        target_tokens: int = 800,
        overlap_tokens: int = 100,
    ) -> IngestDocumentResponse:
        p = Path(path)
        files = {"file": (p.name, p.read_bytes(), _guess_mime(p))}
        body = self._client.request_json(
            "POST",
            "/api/documents/ingest",
            files=files,
            data=_multipart_fields(
                title=title,
                tags=tags,
                source_kind=source_kind,
                source_uri=source_uri,
                target_tokens=target_tokens,
                overlap_tokens=overlap_tokens,
            ),
        )
        return IngestDocumentResponse.model_validate(body)

    def reindex(
        self, doc_id: str, *, target_tokens: int = 800, overlap_tokens: int = 100
    ) -> IngestDocumentResponse:
        body = self._client.request_json(
            "POST",
            f"/api/documents/{doc_id}:reindex",
            json_body={"target_tokens": target_tokens, "overlap_tokens": overlap_tokens},
        )
        return IngestDocumentResponse.model_validate(body)

    def delete(self, doc_id: str) -> None:
        self._client.request_json("DELETE", f"/api/documents/{doc_id}")

    def search(
        self,
        q: str,
        *,
        top_k: int = 5,
        filters: dict[str, Any] | None = None,
    ) -> list[DocChunkHit]:
        body = self._client.request_json(
            "POST",
            "/api/documents/search",
            json_body={"q": q, "top_k": top_k, "filters": filters or {}},
        )
        return [DocChunkHit.model_validate(it) for it in (body or {}).get("items", [])]


def _guess_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix in {".md", ".markdown"}:
        return "text/markdown"
    return "text/plain"


__all__ = ["AsyncDocumentsAPI", "DocumentsAPI"]
