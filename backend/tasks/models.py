"""Pydantic DTOs for the task subsystem.

`TaskRecord` is what routers expose. `TaskEventRecord` is one row of the
per-task event log — used both for SSE replay and for polling.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal["queued", "running", "ok", "error", "cancelled", "waiting"]

TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({"ok", "error", "cancelled"})

NON_TERMINAL_STATUSES: frozenset[TaskStatus] = frozenset({"queued", "running", "waiting"})


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CreateTaskInput(BaseModel):
    """Body of ``POST /api/tasks``."""

    workflow: str = Field(..., min_length=1)
    query: str = Field("", max_length=10000)
    input: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None
    session_id: str | None = None
    budget_usd: float | None = Field(default=None, ge=0)


class TaskRecord(BaseModel):
    """Durable representation of a task."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    workflow: str
    status: TaskStatus = "queued"
    query: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    created_at: datetime = Field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    paused_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class TaskEventRecord(BaseModel):
    """One row of the task's event log."""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    seq: int
    type: str
    at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "TERMINAL_STATUSES",
    "NON_TERMINAL_STATUSES",
    "CreateTaskInput",
    "TaskEventRecord",
    "TaskRecord",
    "TaskStatus",
]
