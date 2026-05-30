"""SQL-backed :class:`TaskStore`.

Shares a DB URL with :class:`backend.memory.episodic_sql.SqlEpisodicStore`
— the two can reuse a single Postgres / SQLite engine when wired through
the memory factory. The model classes live in
:mod:`backend.memory.sql_schema`.
"""

from __future__ import annotations

import builtins
import uuid
from datetime import UTC, datetime

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.core.events import Event
from backend.memory.sql_schema import Base, TaskEventRow, TaskRow

from .models import TaskEventRecord, TaskRecord, TaskStatus

log = structlog.get_logger(__name__)


class SqlTaskStore:
    """Async SQLAlchemy :class:`TaskStore`."""

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine
        self._sessionmaker: async_sessionmaker[AsyncSession] = async_sessionmaker(
            engine, expire_on_commit=False
        )

    @classmethod
    def from_url(cls, url: str, *, echo: bool = False) -> SqlTaskStore:
        return cls(create_async_engine(url, echo=echo, future=True))

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    # ---- CRUD --------------------------------------------------------

    async def create(self, record: TaskRecord) -> TaskRecord:
        if not record.id:
            record = record.model_copy(update={"id": uuid.uuid4().hex})
        row = _record_to_row(record)
        async with self._sessionmaker() as session, session.begin():
            session.add(row)
        return record

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._sessionmaker() as session:
            row = await session.get(TaskRow, task_id)
            return _row_to_record(row) if row is not None else None

    async def delete(self, task_id: str) -> None:
        from sqlalchemy import delete as sqla_delete
        async with self._sessionmaker() as session:
            await session.execute(sqla_delete(TaskRow).where(TaskRow.id == task_id))
            await session.execute(sqla_delete(TaskEventRow).where(TaskEventRow.task_id == task_id))
            await session.commit()

    async def list(
        self,
        *,
        user_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[TaskRecord]:
        stmt = select(TaskRow).order_by(TaskRow.created_at.desc()).offset(offset).limit(limit)
        if user_id is not None:
            stmt = stmt.where(TaskRow.user_id == user_id)
        if status is not None:
            stmt = stmt.where(TaskRow.status == status)
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_row_to_record(r) for r in rows]

    async def mark_started(self, task_id: str) -> None:
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            row.status = "running"
            row.started_at = _now()

    async def mark_completed(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        result: dict | None = None,
        error: str | None = None,
        budget: dict | None = None,
    ) -> None:
        async with self._sessionmaker() as session, session.begin():
            row = await session.get(TaskRow, task_id)
            if row is None:
                raise KeyError(task_id)
            row.status = status
            row.completed_at = _now()
            if result is not None:
                row.result = result
            if error is not None:
                row.error = error
            if budget is not None:
                row.budget = budget

    # ---- events ------------------------------------------------------

    async def append_event(self, task_id: str, event: Event) -> TaskEventRecord:
        async with self._sessionmaker() as session, session.begin():
            next_seq = await session.scalar(
                select(func.coalesce(func.max(TaskEventRow.seq), 0)).where(
                    TaskEventRow.task_id == task_id
                )
            )
            seq = int(next_seq or 0) + 1
            row = TaskEventRow(
                task_id=task_id,
                seq=seq,
                type=event.type,
                at=event.at,
                data=dict(event.data),
            )
            session.add(row)
        return TaskEventRecord(
            task_id=task_id, seq=seq, type=event.type, at=event.at, data=dict(event.data)
        )

    async def events(
        self, task_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> builtins.list[TaskEventRecord]:
        stmt = (
            select(TaskEventRow)
            .where(TaskEventRow.task_id == task_id, TaskEventRow.seq > after_seq)
            .order_by(TaskEventRow.seq.asc())
            .limit(limit)
        )
        async with self._sessionmaker() as session:
            rows = (await session.execute(stmt)).scalars().all()
        return [_event_row_to_record(r) for r in rows]


# ---------------------------------------------------------------------------
# Converters
# ---------------------------------------------------------------------------


def _record_to_row(r: TaskRecord) -> TaskRow:
    return TaskRow(
        id=r.id,
        workflow=r.workflow,
        status=r.status,
        query=r.query,
        input=dict(r.input),
        budget=dict(r.budget),
        result=dict(r.result) if r.result is not None else None,
        error=r.error,
        user_id=r.user_id,
        session_id=r.session_id,
        created_at=r.created_at,
        started_at=r.started_at,
        completed_at=r.completed_at,
    )


def _row_to_record(r: TaskRow) -> TaskRecord:
    return TaskRecord(
        id=r.id,
        workflow=r.workflow,
        status=r.status,  # type: ignore[arg-type]
        query=r.query,
        input=dict(r.input or {}),
        budget=dict(r.budget or {}),
        result=dict(r.result) if r.result is not None else None,
        error=r.error,
        user_id=r.user_id,
        session_id=r.session_id,
        created_at=r.created_at,
        started_at=r.started_at,
        completed_at=r.completed_at,
    )


def _event_row_to_record(r: TaskEventRow) -> TaskEventRecord:
    return TaskEventRecord(
        task_id=r.task_id, seq=r.seq, type=r.type, at=r.at, data=dict(r.data or {})
    )


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["SqlTaskStore"]
