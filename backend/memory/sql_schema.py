"""SQLAlchemy schema for memory persistence.

Single source of truth for the DB layout mentioned in PLAN §23.4. We
deliberately use portable types (``String`` for ids, ``JSON`` for list
fields) so the same models run on SQLite (dev/test) and Postgres
(production) without branching.

Embedding columns are deferred to a future stage: pgvector is Postgres
specific and the vector is already the VectorStore's concern.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for every ORM model in the framework."""


class EpisodicRow(Base):
    __tablename__ = "aaf_episodic"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True, default="reflection")
    content: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class SessionRow(Base):
    __tablename__ = "aaf_sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), default="")
    state: Mapped[dict] = mapped_column(JSON, default=dict)
    messages: Mapped[list[dict]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class TaskRow(Base):
    """Persistent record for a long-running workflow execution.

    The task row carries the *command* (workflow + input + budget) and
    the *summary* (status + result/error + timings). Fine-grained events
    live in :class:`TaskEventRow` — one row per emitted event — so
    SSE replay and polling work across worker/API processes.
    """

    __tablename__ = "aaf_tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workflow: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(16), index=True, default="queued")
    query: Mapped[str] = mapped_column(Text, default="")
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    budget: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TaskEventRow(Base):
    """Append-only event log for a task. ``seq`` is per-task monotonic."""

    __tablename__ = "aaf_task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("aaf_tasks.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, index=True)
    type: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ManuscriptRow(Base):
    """Metadata for one tracked paper / section.

    Content lives in :class:`ManuscriptVersionRow`; this row carries the
    *latest* version pointer plus indexed metadata for listing.
    """

    __tablename__ = "aaf_manuscripts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(500), default="")
    kind: Mapped[str] = mapped_column(String(16), index=True, default="section")
    status: Mapped[str] = mapped_column(String(16), index=True, default="draft")
    section: Mapped[str | None] = mapped_column(String(64), nullable=True)
    topic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_version: Mapped[int] = mapped_column(Integer, default=0)
    origin: Mapped[str] = mapped_column(String(32), default="api")
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class ManuscriptVersionRow(Base):
    """Immutable manuscript snapshot. ``version`` is monotonic per manuscript."""

    __tablename__ = "aaf_manuscript_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    manuscript_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("aaf_manuscripts.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, index=True)
    content: Mapped[str] = mapped_column(Text, default="")
    note: Mapped[str] = mapped_column(Text, default="")
    produced_by: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    origin: Mapped[str] = mapped_column(String(32), default="api")
    citations: Mapped[list[str]] = mapped_column(JSON, default=list)
    reviewer_comments: Mapped[list[dict]] = mapped_column(JSON, default=list)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


__all__ = [
    "Base",
    "EpisodicRow",
    "ManuscriptRow",
    "ManuscriptVersionRow",
    "SessionRow",
    "TaskEventRow",
    "TaskRow",
]
