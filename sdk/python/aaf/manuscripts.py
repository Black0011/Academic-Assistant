"""``/api/manuscripts/*`` sub-client."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, BinaryIO

from .models import (
    Manuscript,
    ManuscriptEnvelope,
    ManuscriptKind,
    ManuscriptStatus,
    ManuscriptVersion,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


def _list_params(
    *,
    user_id: str | None,
    status: ManuscriptStatus | None,
    kind: ManuscriptKind | None,
    tag: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "status": status,
        "kind": kind,
        "tag": tag,
        "limit": limit,
        "offset": offset,
    }


def _create_payload(
    *,
    title: str,
    kind: ManuscriptKind,
    section: str | None,
    topic: str | None,
    tags: list[str] | None,
    user_id: str | None,
    session_id: str | None,
    meta: dict[str, Any] | None,
    content: str | None,
    note: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": title,
        "kind": kind,
        "tags": tags or [],
        "meta": meta or {},
        "note": note,
    }
    if section is not None:
        payload["section"] = section
    if topic is not None:
        payload["topic"] = topic
    if user_id is not None:
        payload["user_id"] = user_id
    if session_id is not None:
        payload["session_id"] = session_id
    if content is not None:
        payload["content"] = content
    return payload


def _commit_payload(
    *,
    content: str,
    note: str,
    produced_by: str | None,
    citations: list[str] | None,
    reviewer_comments: list[dict[str, Any]] | None,
    origin: str | None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "content": content,
        "note": note,
        "citations": citations or [],
        "reviewer_comments": reviewer_comments or [],
    }
    if produced_by is not None:
        payload["produced_by"] = produced_by
    if origin is not None:
        payload["origin"] = origin
    return payload


def _open_upload(
    file: str | Path | BinaryIO,
    *,
    filename: str | None,
    content_type: str | None,
) -> tuple[BinaryIO, str, str, bool]:
    """Resolve a file argument into ``(handle, name, mime, owns_handle)``."""
    if isinstance(file, (str, Path)):
        path = Path(file)
        handle: BinaryIO = path.open("rb")
        return (
            handle,
            filename or path.name,
            content_type or _guess_mime(path.name),
            True,
        )
    if filename is None:
        raise ValueError("filename is required when uploading a binary file object")
    return file, filename, content_type or _guess_mime(filename), False


def _guess_mime(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".pdf"):
        return "application/pdf"
    if lowered.endswith((".md", ".markdown")):
        return "text/markdown"
    return "text/plain"


def _upload_form(
    *,
    title: str,
    kind: ManuscriptKind,
    section: str | None,
    topic: str | None,
    tags: list[str] | None,
    user_id: str | None,
    session_id: str | None,
) -> dict[str, str]:
    form: dict[str, str] = {"title": title, "kind": kind}
    if section is not None:
        form["section"] = section
    if topic is not None:
        form["topic"] = topic
    if tags:
        form["tags"] = ",".join(tags)
    if user_id is not None:
        form["user_id"] = user_id
    if session_id is not None:
        form["session_id"] = session_id
    return form


class AsyncManuscriptsAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(
        self,
        *,
        user_id: str | None = None,
        status: ManuscriptStatus | None = None,
        kind: ManuscriptKind | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Manuscript]:
        body = await self._client.request_json(
            "GET",
            "/api/manuscripts",
            params=_list_params(
                user_id=user_id,
                status=status,
                kind=kind,
                tag=tag,
                limit=limit,
                offset=offset,
            ),
        )
        return [Manuscript.model_validate(item) for item in (body or {}).get("items", [])]

    async def get(self, manuscript_id: str) -> Manuscript:
        body = await self._client.request_json("GET", f"/api/manuscripts/{manuscript_id}")
        return Manuscript.model_validate(body)

    async def create(
        self,
        *,
        title: str,
        kind: ManuscriptKind = "paper",
        section: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        meta: dict[str, Any] | None = None,
        content: str | None = None,
        note: str = "",
    ) -> ManuscriptEnvelope:
        body = await self._client.request_json(
            "POST",
            "/api/manuscripts",
            json_body=_create_payload(
                title=title,
                kind=kind,
                section=section,
                topic=topic,
                tags=tags,
                user_id=user_id,
                session_id=session_id,
                meta=meta,
                content=content,
                note=note,
            ),
        )
        return ManuscriptEnvelope.model_validate(body)

    async def update(
        self,
        manuscript_id: str,
        *,
        title: str | None = None,
        status: ManuscriptStatus | None = None,
        section: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Manuscript:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if status is not None:
            payload["status"] = status
        if section is not None:
            payload["section"] = section
        if topic is not None:
            payload["topic"] = topic
        if tags is not None:
            payload["tags"] = tags
        if meta is not None:
            payload["meta"] = meta
        body = await self._client.request_json(
            "PATCH",
            f"/api/manuscripts/{manuscript_id}",
            json_body=payload,
        )
        return Manuscript.model_validate(body)

    async def delete(self, manuscript_id: str) -> None:
        await self._client.request_json("DELETE", f"/api/manuscripts/{manuscript_id}")

    async def commit_version(
        self,
        manuscript_id: str,
        *,
        content: str,
        note: str = "",
        produced_by: str | None = None,
        citations: list[str] | None = None,
        reviewer_comments: list[dict[str, Any]] | None = None,
        origin: str | None = None,
    ) -> ManuscriptVersion:
        body = await self._client.request_json(
            "POST",
            f"/api/manuscripts/{manuscript_id}/versions",
            json_body=_commit_payload(
                content=content,
                note=note,
                produced_by=produced_by,
                citations=citations,
                reviewer_comments=reviewer_comments,
                origin=origin,
            ),
        )
        return ManuscriptVersion.model_validate(body)

    async def list_versions(
        self,
        manuscript_id: str,
        *,
        limit: int = 50,
    ) -> list[ManuscriptVersion]:
        body = await self._client.request_json(
            "GET",
            f"/api/manuscripts/{manuscript_id}/versions",
            params={"limit": limit},
        )
        return [ManuscriptVersion.model_validate(item) for item in (body or {}).get("items", [])]

    async def get_version(self, manuscript_id: str, version: int) -> ManuscriptVersion:
        body = await self._client.request_json(
            "GET",
            f"/api/manuscripts/{manuscript_id}/versions/{version}",
        )
        return ManuscriptVersion.model_validate(body)

    async def export_markdown(
        self,
        manuscript_id: str,
        *,
        version: int | None = None,
    ) -> str:
        params: Mapping[str, Any] = {"version": version} if version is not None else {}
        body = await self._client.request_json(
            "GET",
            f"/api/manuscripts/{manuscript_id}/export",
            params=params,
        )
        return body if isinstance(body, str) else str(body or "")

    async def upload(
        self,
        file: str | Path | BinaryIO,
        *,
        title: str = "",
        kind: ManuscriptKind = "paper",
        section: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ManuscriptEnvelope:
        handle, resolved_name, mime, owns = _open_upload(
            file, filename=filename, content_type=content_type
        )
        try:
            body = await self._client.request_json(
                "POST",
                "/api/manuscripts/upload",
                files={"file": (resolved_name, handle, mime)},
                data=_upload_form(
                    title=title,
                    kind=kind,
                    section=section,
                    topic=topic,
                    tags=tags,
                    user_id=user_id,
                    session_id=session_id,
                ),
            )
            return ManuscriptEnvelope.model_validate(body)
        finally:
            if owns:
                handle.close()

    async def stats(self) -> dict[str, Any]:
        body = await self._client.request_json("GET", "/api/manuscripts/stats")
        return dict(body or {})


class ManuscriptsAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(
        self,
        *,
        user_id: str | None = None,
        status: ManuscriptStatus | None = None,
        kind: ManuscriptKind | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Manuscript]:
        body = self._client.request_json(
            "GET",
            "/api/manuscripts",
            params=_list_params(
                user_id=user_id,
                status=status,
                kind=kind,
                tag=tag,
                limit=limit,
                offset=offset,
            ),
        )
        return [Manuscript.model_validate(item) for item in (body or {}).get("items", [])]

    def get(self, manuscript_id: str) -> Manuscript:
        body = self._client.request_json("GET", f"/api/manuscripts/{manuscript_id}")
        return Manuscript.model_validate(body)

    def create(
        self,
        *,
        title: str,
        kind: ManuscriptKind = "paper",
        section: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        meta: dict[str, Any] | None = None,
        content: str | None = None,
        note: str = "",
    ) -> ManuscriptEnvelope:
        body = self._client.request_json(
            "POST",
            "/api/manuscripts",
            json_body=_create_payload(
                title=title,
                kind=kind,
                section=section,
                topic=topic,
                tags=tags,
                user_id=user_id,
                session_id=session_id,
                meta=meta,
                content=content,
                note=note,
            ),
        )
        return ManuscriptEnvelope.model_validate(body)

    def update(
        self,
        manuscript_id: str,
        *,
        title: str | None = None,
        status: ManuscriptStatus | None = None,
        section: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        meta: dict[str, Any] | None = None,
    ) -> Manuscript:
        payload: dict[str, Any] = {}
        if title is not None:
            payload["title"] = title
        if status is not None:
            payload["status"] = status
        if section is not None:
            payload["section"] = section
        if topic is not None:
            payload["topic"] = topic
        if tags is not None:
            payload["tags"] = tags
        if meta is not None:
            payload["meta"] = meta
        body = self._client.request_json(
            "PATCH",
            f"/api/manuscripts/{manuscript_id}",
            json_body=payload,
        )
        return Manuscript.model_validate(body)

    def delete(self, manuscript_id: str) -> None:
        self._client.request_json("DELETE", f"/api/manuscripts/{manuscript_id}")

    def commit_version(
        self,
        manuscript_id: str,
        *,
        content: str,
        note: str = "",
        produced_by: str | None = None,
        citations: list[str] | None = None,
        reviewer_comments: list[dict[str, Any]] | None = None,
        origin: str | None = None,
    ) -> ManuscriptVersion:
        body = self._client.request_json(
            "POST",
            f"/api/manuscripts/{manuscript_id}/versions",
            json_body=_commit_payload(
                content=content,
                note=note,
                produced_by=produced_by,
                citations=citations,
                reviewer_comments=reviewer_comments,
                origin=origin,
            ),
        )
        return ManuscriptVersion.model_validate(body)

    def list_versions(
        self,
        manuscript_id: str,
        *,
        limit: int = 50,
    ) -> list[ManuscriptVersion]:
        body = self._client.request_json(
            "GET",
            f"/api/manuscripts/{manuscript_id}/versions",
            params={"limit": limit},
        )
        return [ManuscriptVersion.model_validate(item) for item in (body or {}).get("items", [])]

    def get_version(self, manuscript_id: str, version: int) -> ManuscriptVersion:
        body = self._client.request_json(
            "GET",
            f"/api/manuscripts/{manuscript_id}/versions/{version}",
        )
        return ManuscriptVersion.model_validate(body)

    def export_markdown(
        self,
        manuscript_id: str,
        *,
        version: int | None = None,
    ) -> str:
        params: Mapping[str, Any] = {"version": version} if version is not None else {}
        body = self._client.request_json(
            "GET",
            f"/api/manuscripts/{manuscript_id}/export",
            params=params,
        )
        return body if isinstance(body, str) else str(body or "")

    def upload(
        self,
        file: str | Path | BinaryIO,
        *,
        title: str = "",
        kind: ManuscriptKind = "paper",
        section: str | None = None,
        topic: str | None = None,
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        filename: str | None = None,
        content_type: str | None = None,
    ) -> ManuscriptEnvelope:
        handle, resolved_name, mime, owns = _open_upload(
            file, filename=filename, content_type=content_type
        )
        try:
            body = self._client.request_json(
                "POST",
                "/api/manuscripts/upload",
                files={"file": (resolved_name, handle, mime)},
                data=_upload_form(
                    title=title,
                    kind=kind,
                    section=section,
                    topic=topic,
                    tags=tags,
                    user_id=user_id,
                    session_id=session_id,
                ),
            )
            return ManuscriptEnvelope.model_validate(body)
        finally:
            if owns:
                handle.close()

    def stats(self) -> dict[str, Any]:
        body = self._client.request_json("GET", "/api/manuscripts/stats")
        return dict(body or {})


__all__ = ["AsyncManuscriptsAPI", "ManuscriptsAPI"]
