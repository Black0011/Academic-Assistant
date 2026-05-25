"""EpisodicStore backed by async SQLAlchemy.

Works with **any** DB URL that SQLAlchemy can resolve — tested on
``sqlite+aiosqlite:///:memory:`` and ``postgresql+asyncpg://...``. The
schema comes from :mod:`backend.memory.sql_schema` so Alembic migrations
and ORM queries share one definition.

Protocol parity with :class:`backend.memory.episodic_store.InMemoryEpisodicStore`:
new queries landing there should land here too.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from .models import Reflection
from .sql_schema import Base, EpisodicRow

if TYPE_CHECKING:
    pass

log = structlog.get_logger(__name__)


class SqlEpisodicStore:
    """Async SQLAlchemy-backed episodic store."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )

    # ---- construction helpers --------------------------------------

    @classmethod
    def from_url(cls, url: str, *, echo: bool = False) -> SqlEpisodicStore:
        """Shortcut for test / dev wiring."""
        return cls(create_async_engine(url, echo=echo, future=True))

    async def init(self) -> None:
        """Create tables if absent. Alembic owns migrations in production."""
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    # ---- protocol ---------------------------------------------------

    async def append(self, reflection: Reflection) -> None:
        async with self._sessionmaker() as session, session.begin():
            session.add(_to_row(reflection))

    async def recent(
        self,
        *,
        n: int = 3,
        type: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> list[Reflection]:
        if n <= 0:
            return []
        stmt = select(EpisodicRow).order_by(EpisodicRow.created_at.desc()).limit(n)
        if type is not None:
            stmt = stmt.where(EpisodicRow.type == type)
        if session_id is not None:
            stmt = stmt.where(EpisodicRow.session_id == session_id)
        if user_id is not None:
            stmt = stmt.where(EpisodicRow.user_id == user_id)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_to_model(r) for r in rows]

    async def rollback_run(self, run_id: str) -> int:
        stmt = delete(EpisodicRow).where(EpisodicRow.source_run_id == run_id)
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(stmt)
        # rowcount on CursorResult; mypy sees generic Result — cast deliberately.
        return int(getattr(result, "rowcount", 0) or 0)

    async def count(self) -> int:
        async with self._sessionmaker() as session:
            rows = (await session.execute(select(EpisodicRow.id))).scalars().all()
        return len(rows)

    async def clear(self) -> None:
        async with self._sessionmaker() as session, session.begin():
            await session.execute(delete(EpisodicRow))

    # ---- P14.A manual CRUD ---------------------------------------------

    async def get(self, id_: str) -> Reflection | None:
        async with self._sessionmaker() as session:
            row = (
                await session.execute(select(EpisodicRow).where(EpisodicRow.id == id_))
            ).scalar_one_or_none()
        return _to_model(row) if row is not None else None

    async def update(
        self,
        id_: str,
        *,
        type: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> Reflection | None:
        async with self._sessionmaker() as session, session.begin():
            row = (
                await session.execute(select(EpisodicRow).where(EpisodicRow.id == id_))
            ).scalar_one_or_none()
            if row is None:
                return None
            if type is not None:
                row.type = type
            if content is not None:
                row.content = content
            if tags is not None:
                row.tags = list(tags)
            # ``session.begin()`` flushes on exit — no explicit add needed
            # for an attached row.
        # Read-back outside the write transaction for a clean snapshot.
        return await self.get(id_)

    async def delete(self, id_: str) -> bool:
        stmt = delete(EpisodicRow).where(EpisodicRow.id == id_)
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0) > 0

    async def delete_by(
        self,
        *,
        session_id: str | None = None,
        source_run_id: str | None = None,
    ) -> int:
        if session_id is None and source_run_id is None:
            # Refuse the unbounded delete — same contract as the in-memory store.
            return 0
        stmt = delete(EpisodicRow)
        if session_id is not None:
            stmt = stmt.where(EpisodicRow.session_id == session_id)
        if source_run_id is not None:
            stmt = stmt.where(EpisodicRow.source_run_id == source_run_id)
        async with self._sessionmaker() as session, session.begin():
            result = await session.execute(stmt)
        return int(getattr(result, "rowcount", 0) or 0)


# ---------------------------------------------------------------------------
# Conversion helpers
# ---------------------------------------------------------------------------


def _to_row(r: Reflection) -> EpisodicRow:
    return EpisodicRow(
        id=r.id,
        type=r.type,
        content=r.content,
        tags=list(r.tags),
        user_id=r.user_id,
        session_id=r.session_id,
        source_run_id=r.source_run_id,
        created_at=r.created_at,
    )


def _to_model(r: EpisodicRow) -> Reflection:
    return Reflection(
        id=r.id,
        type=r.type,  # type: ignore[arg-type]
        content=r.content,
        tags=list(r.tags or []),
        user_id=r.user_id,
        session_id=r.session_id,
        source_run_id=r.source_run_id,
        created_at=r.created_at,
    )


__all__ = ["SqlEpisodicStore"]
