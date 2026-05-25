"""ManuscriptStore protocol + in-memory implementation.

Design mirrors :mod:`backend.tasks.store` — a tight protocol, a
reference in-memory impl used in tests, and a SQL impl (``sql_store.py``)
that shares the Memory / Tasks engine.
"""

from __future__ import annotations

import asyncio
import builtins
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from .models import (
    CommitVersionInput,
    CreateManuscriptInput,
    Manuscript,
    ManuscriptStatus,
    ManuscriptVersion,
    UpdateManuscriptInput,
)

_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def _word_count(text: str) -> int:
    return len([w for w in _WORD_RE.findall(text or "") if w])


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ManuscriptStore(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...

    async def create(
        self, body: CreateManuscriptInput
    ) -> tuple[Manuscript, ManuscriptVersion | None]: ...
    async def get(self, manuscript_id: str) -> Manuscript | None: ...
    async def list(
        self,
        *,
        user_id: str | None = None,
        status: ManuscriptStatus | None = None,
        kind: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[Manuscript]: ...
    async def update(self, manuscript_id: str, body: UpdateManuscriptInput) -> Manuscript: ...
    async def delete(self, manuscript_id: str) -> bool: ...

    async def commit_version(
        self, manuscript_id: str, body: CommitVersionInput
    ) -> ManuscriptVersion: ...
    async def list_versions(
        self, manuscript_id: str, *, limit: int = 50
    ) -> builtins.list[ManuscriptVersion]: ...
    async def get_version(self, manuscript_id: str, version: int) -> ManuscriptVersion | None: ...

    async def stats(self) -> dict: ...


# ---------------------------------------------------------------------------
# In-memory impl
# ---------------------------------------------------------------------------


class InMemoryManuscriptStore:
    def __init__(self) -> None:
        self._manuscripts: dict[str, Manuscript] = {}
        self._versions: dict[str, list[ManuscriptVersion]] = {}
        self._lock = asyncio.Lock()

    async def init(self) -> None:  # pragma: no cover
        return

    async def close(self) -> None:  # pragma: no cover
        return

    # ---- CRUD --------------------------------------------------------

    async def create(
        self, body: CreateManuscriptInput
    ) -> tuple[Manuscript, ManuscriptVersion | None]:
        manuscript_id = uuid.uuid4().hex[:12]
        record = Manuscript(
            id=manuscript_id,
            title=body.title,
            kind=body.kind,
            status=body.status,
            section=body.section,
            topic=body.topic,
            tags=list(body.tags),
            origin="api",
            user_id=body.user_id,
            session_id=body.session_id,
            meta=dict(body.meta),
            layout=body.layout,
            bundle_link_path=body.bundle_link_path,
            bundle_versioning=body.bundle_versioning,
        )
        async with self._lock:
            self._manuscripts[manuscript_id] = record
            self._versions[manuscript_id] = []
        version: ManuscriptVersion | None = None
        # Single-layout manuscripts may carry inline content for v1; bundles
        # populate themselves through the file-tree API.
        if body.layout == "single" and body.content.strip():
            version = await self.commit_version(
                manuscript_id,
                CommitVersionInput(
                    content=body.content,
                    note=body.note or "initial version",
                    origin="api",
                    citations=list(body.citations),
                ),
            )
        # Re-read to capture current_version bump from commit_version.
        final = await self.get(manuscript_id)
        assert final is not None
        return final, version

    async def get(self, manuscript_id: str) -> Manuscript | None:
        async with self._lock:
            return self._manuscripts.get(manuscript_id)

    async def list(
        self,
        *,
        user_id: str | None = None,
        status: ManuscriptStatus | None = None,
        kind: str | None = None,
        tag: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[Manuscript]:
        async with self._lock:
            out = builtins.list(self._manuscripts.values())
        if user_id is not None:
            out = [m for m in out if m.user_id == user_id]
        if status is not None:
            out = [m for m in out if m.status == status]
        if kind is not None:
            out = [m for m in out if m.kind == kind]
        if tag is not None:
            out = [m for m in out if tag in m.tags]
        out.sort(key=lambda m: m.updated_at, reverse=True)
        return out[offset : offset + limit]

    async def update(self, manuscript_id: str, body: UpdateManuscriptInput) -> Manuscript:
        async with self._lock:
            record = self._manuscripts.get(manuscript_id)
            if record is None:
                raise KeyError(manuscript_id)
            updates: dict = {}
            if body.title is not None:
                updates["title"] = body.title
            if body.status is not None:
                updates["status"] = body.status
            if body.section is not None:
                updates["section"] = body.section
            if body.topic is not None:
                updates["topic"] = body.topic
            if body.tags is not None:
                updates["tags"] = list(body.tags)
            if body.meta is not None:
                merged = dict(record.meta)
                merged.update(body.meta)
                updates["meta"] = merged
            if body.layout is not None:
                updates["layout"] = body.layout
            if body.bundle_link_path is not None:
                # An empty string means "clear the link" (back to copy mode).
                updates["bundle_link_path"] = body.bundle_link_path or None
            if body.bundle_versioning is not None:
                updates["bundle_versioning"] = body.bundle_versioning
            updates["updated_at"] = _now()
            updated = record.model_copy(update=updates)
            self._manuscripts[manuscript_id] = updated
            return updated

    async def delete(self, manuscript_id: str) -> bool:
        async with self._lock:
            removed = self._manuscripts.pop(manuscript_id, None)
            self._versions.pop(manuscript_id, None)
        return removed is not None

    # ---- versions ----------------------------------------------------

    async def commit_version(
        self, manuscript_id: str, body: CommitVersionInput
    ) -> ManuscriptVersion:
        async with self._lock:
            record = self._manuscripts.get(manuscript_id)
            if record is None:
                raise KeyError(manuscript_id)
            versions = self._versions.setdefault(manuscript_id, [])
            next_version = (versions[-1].version if versions else 0) + 1
            version = ManuscriptVersion(
                manuscript_id=manuscript_id,
                version=next_version,
                content=body.content,
                note=body.note,
                produced_by=body.produced_by,
                origin=body.origin,
                citations=list(body.citations),
                reviewer_comments=deepcopy(body.reviewer_comments),
                word_count=_word_count(body.content),
            )
            versions.append(version)
            self._manuscripts[manuscript_id] = record.model_copy(
                update={
                    "current_version": next_version,
                    "updated_at": version.created_at,
                    "origin": body.origin if body.origin != "api" else record.origin,
                }
            )
            return version

    async def list_versions(
        self, manuscript_id: str, *, limit: int = 50
    ) -> builtins.list[ManuscriptVersion]:
        async with self._lock:
            if manuscript_id not in self._manuscripts:
                raise KeyError(manuscript_id)
            versions = builtins.list(reversed(self._versions.get(manuscript_id, [])))
        return versions[: max(1, limit)]

    async def get_version(self, manuscript_id: str, version: int) -> ManuscriptVersion | None:
        async with self._lock:
            versions = self._versions.get(manuscript_id, [])
            for v in versions:
                if v.version == version:
                    return v
        return None

    async def stats(self) -> dict:
        async with self._lock:
            total = len(self._manuscripts)
            version_total = sum(len(v) for v in self._versions.values())
            by_status: dict[str, int] = {}
            for m in self._manuscripts.values():
                by_status[m.status] = by_status.get(m.status, 0) + 1
        return {
            "total": total,
            "versions_total": version_total,
            "by_status": by_status,
        }


__all__ = ["InMemoryManuscriptStore", "ManuscriptStore"]
