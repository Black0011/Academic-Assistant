"""SQL-backed :class:`ManuscriptStore`.

Shares an engine URL with the memory and task SQL stores. All three sit
on :mod:`backend.memory.sql_schema`, so a single migration / create_all
lights up every subsystem.
"""

from __future__ import annotations

import builtins
import re
import uuid
from copy import deepcopy
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.memory.sql_schema import Base, ManuscriptRow, ManuscriptVersionRow

from .models import (
    CommitVersionInput,
    CreateManuscriptInput,
    Manuscript,
    ManuscriptLayout,
    ManuscriptStatus,
    ManuscriptVersion,
    UpdateManuscriptInput,
)

# ---------------------------------------------------------------------------
# Layout fields are stored inside ``meta`` under reserved underscore keys.
# Keeping them out of the SQL schema means we can extend the bundle layout
# without an Alembic migration, and rows produced by the pre-P7 code keep
# loading (defaults kick in).
# ---------------------------------------------------------------------------

_META_LAYOUT_KEY = "_layout"
_META_LINK_PATH_KEY = "_bundle_link_path"
_META_VERSIONING_KEY = "_bundle_versioning"


def _pack_layout_into_meta(
    meta: dict,
    *,
    layout: ManuscriptLayout | None,
    bundle_link_path: str | None,
    bundle_versioning: bool | None,
) -> dict:
    """Embed bundle-layout fields into a meta dict in-place + return it.

    ``None`` arguments mean "don't touch" so this is safe for partial updates.
    A blank ``bundle_link_path`` ("") is treated as "clear the link" and
    drops the key entirely (Pydantic then defaults back to ``None``).
    """
    out = dict(meta)
    if layout is not None:
        out[_META_LAYOUT_KEY] = layout
    if bundle_link_path is not None:
        if bundle_link_path:
            out[_META_LINK_PATH_KEY] = bundle_link_path
        else:
            out.pop(_META_LINK_PATH_KEY, None)
    if bundle_versioning is not None:
        out[_META_VERSIONING_KEY] = bool(bundle_versioning)
    return out


def _unpack_layout_from_meta(
    meta: dict,
) -> tuple[ManuscriptLayout, str | None, bool, dict]:
    """Pull the layout fields out so they can be set as first-class on Pydantic.

    Returns ``(layout, link_path, versioning, clean_meta)`` where
    ``clean_meta`` is the original dict minus the reserved keys (so the
    user-facing ``meta`` is untainted).
    """
    layout_raw = meta.get(_META_LAYOUT_KEY, "single")
    layout: ManuscriptLayout = "bundle" if layout_raw == "bundle" else "single"
    link_path_raw = meta.get(_META_LINK_PATH_KEY)
    link_path: str | None = link_path_raw if isinstance(link_path_raw, str) else None
    versioning_raw = meta.get(_META_VERSIONING_KEY, True)
    versioning = bool(versioning_raw) if not isinstance(versioning_raw, str) else True
    clean = {
        k: v
        for k, v in meta.items()
        if k not in {_META_LAYOUT_KEY, _META_LINK_PATH_KEY, _META_VERSIONING_KEY}
    }
    return layout, link_path, versioning, clean


log = structlog.get_logger(__name__)

_WORD_RE = re.compile(r"\b[\w'-]+\b", re.UNICODE)


def _word_count(text: str) -> int:
    return len([w for w in _WORD_RE.findall(text or "") if w])


def _now() -> datetime:
    return datetime.now(UTC)


class SqlManuscriptStore:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )

    @classmethod
    def from_url(cls, url: str, *, echo: bool = False) -> SqlManuscriptStore:
        return cls(create_async_engine(url, echo=echo, future=True))

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    # ---- CRUD --------------------------------------------------------

    async def create(
        self, body: CreateManuscriptInput
    ) -> tuple[Manuscript, ManuscriptVersion | None]:
        now = _now()
        manuscript_id = uuid.uuid4().hex[:12]
        meta_with_layout = _pack_layout_into_meta(
            dict(body.meta),
            layout=body.layout,
            bundle_link_path=body.bundle_link_path,
            bundle_versioning=body.bundle_versioning,
        )
        row = ManuscriptRow(
            id=manuscript_id,
            title=body.title,
            kind=body.kind,
            status=body.status,
            section=body.section,
            topic=body.topic,
            tags=list(body.tags),
            current_version=0,
            origin="api",
            user_id=body.user_id,
            session_id=body.session_id,
            meta=meta_with_layout,
            created_at=now,
            updated_at=now,
        )
        async with self._sessionmaker() as session, session.begin():
            session.add(row)

        version: ManuscriptVersion | None = None
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
        final = await self.get(manuscript_id)
        assert final is not None
        return final, version

    async def get(self, manuscript_id: str) -> Manuscript | None:
        async with self._sessionmaker() as session:
            row = await session.get(ManuscriptRow, manuscript_id)
        return _row_to_manuscript(row) if row is not None else None

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
        stmt = (
            select(ManuscriptRow)
            .order_by(ManuscriptRow.updated_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if user_id is not None:
            stmt = stmt.where(ManuscriptRow.user_id == user_id)
        if status is not None:
            stmt = stmt.where(ManuscriptRow.status == status)
        if kind is not None:
            stmt = stmt.where(ManuscriptRow.kind == kind)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
        records = [_row_to_manuscript(r) for r in rows]
        if tag is not None:
            records = [m for m in records if tag in m.tags]
        return records

    async def update(self, manuscript_id: str, body: UpdateManuscriptInput) -> Manuscript:
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(ManuscriptRow, manuscript_id)
            if row is None:
                raise KeyError(manuscript_id)
            if body.title is not None:
                row.title = body.title
            if body.status is not None:
                row.status = body.status
            if body.section is not None:
                row.section = body.section
            if body.topic is not None:
                row.topic = body.topic
            if body.tags is not None:
                row.tags = list(body.tags)
            merged_meta = dict(row.meta or {})
            if body.meta is not None:
                merged_meta.update(body.meta)
            # Layout fields ride along inside ``meta`` so we don't have to
            # alter the SQL schema. ``_pack_layout_into_meta`` is a no-op
            # when its kwargs are all None.
            merged_meta = _pack_layout_into_meta(
                merged_meta,
                layout=body.layout,
                bundle_link_path=body.bundle_link_path,
                bundle_versioning=body.bundle_versioning,
            )
            row.meta = merged_meta
            row.updated_at = _now()
            result = _row_to_manuscript(row)
        return result

    async def delete(self, manuscript_id: str) -> bool:
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(ManuscriptRow, manuscript_id)
            if row is None:
                return False
            await session.delete(row)
        return True

    # ---- versions ----------------------------------------------------

    async def commit_version(
        self, manuscript_id: str, body: CommitVersionInput
    ) -> ManuscriptVersion:
        now = _now()
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(ManuscriptRow, manuscript_id)
            if row is None:
                raise KeyError(manuscript_id)
            current_max = await session.scalar(
                select(func.coalesce(func.max(ManuscriptVersionRow.version), 0)).where(
                    ManuscriptVersionRow.manuscript_id == manuscript_id
                )
            )
            next_version = int(current_max or 0) + 1
            v_row = ManuscriptVersionRow(
                manuscript_id=manuscript_id,
                version=next_version,
                content=body.content,
                note=body.note,
                produced_by=body.produced_by,
                origin=body.origin,
                citations=list(body.citations),
                reviewer_comments=deepcopy(body.reviewer_comments),
                word_count=_word_count(body.content),
                created_at=now,
            )
            session.add(v_row)
            row.current_version = next_version
            row.updated_at = now
            if body.origin != "api":
                row.origin = body.origin
            version_model = _row_to_version(v_row)
        return version_model

    async def list_versions(
        self, manuscript_id: str, *, limit: int = 50
    ) -> builtins.list[ManuscriptVersion]:
        async with self._sessionmaker() as session:
            # Ensure manuscript exists (raises KeyError for missing ids, parity with in-mem).
            if (await session.get(ManuscriptRow, manuscript_id)) is None:
                raise KeyError(manuscript_id)
            stmt = (
                select(ManuscriptVersionRow)
                .where(ManuscriptVersionRow.manuscript_id == manuscript_id)
                .order_by(ManuscriptVersionRow.version.desc())
                .limit(max(1, limit))
            )
            rows = (await session.execute(stmt)).scalars().all()
        return [_row_to_version(r) for r in rows]

    async def get_version(self, manuscript_id: str, version: int) -> ManuscriptVersion | None:
        stmt = select(ManuscriptVersionRow).where(
            ManuscriptVersionRow.manuscript_id == manuscript_id,
            ManuscriptVersionRow.version == version,
        )
        async with self._sessionmaker() as session:
            row = (await session.execute(stmt)).scalar_one_or_none()
        return _row_to_version(row) if row is not None else None

    async def stats(self) -> dict:
        async with self._sessionmaker() as session:
            total = int(await session.scalar(select(func.count()).select_from(ManuscriptRow)) or 0)
            v_total = int(
                await session.scalar(select(func.count()).select_from(ManuscriptVersionRow)) or 0
            )
            status_rows = (
                await session.execute(
                    select(ManuscriptRow.status, func.count(ManuscriptRow.id)).group_by(
                        ManuscriptRow.status
                    )
                )
            ).all()
        by_status = {str(status): int(count) for status, count in status_rows}
        return {"total": total, "versions_total": v_total, "by_status": by_status}


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def _row_to_manuscript(r: ManuscriptRow) -> Manuscript:
    raw_meta = dict(r.meta or {})
    layout, link_path, versioning, clean_meta = _unpack_layout_from_meta(raw_meta)
    return Manuscript(
        id=r.id,
        title=r.title or "",
        kind=r.kind,  # type: ignore[arg-type]
        status=r.status,  # type: ignore[arg-type]
        section=r.section,
        topic=r.topic,
        tags=list(r.tags or []),
        current_version=int(r.current_version or 0),
        origin=r.origin,  # type: ignore[arg-type]
        user_id=r.user_id,
        session_id=r.session_id,
        meta=clean_meta,
        created_at=r.created_at,
        updated_at=r.updated_at,
        layout=layout,
        bundle_link_path=link_path,
        bundle_versioning=versioning,
    )


def _row_to_version(r: ManuscriptVersionRow) -> ManuscriptVersion:
    return ManuscriptVersion(
        manuscript_id=r.manuscript_id,
        version=int(r.version),
        content=r.content or "",
        note=r.note or "",
        produced_by=r.produced_by,
        origin=r.origin,  # type: ignore[arg-type]
        citations=list(r.citations or []),
        reviewer_comments=list(r.reviewer_comments or []),
        word_count=int(r.word_count or 0),
        created_at=r.created_at,
    )


__all__ = ["SqlManuscriptStore"]
