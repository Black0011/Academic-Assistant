"""TaskStore — protocol + in-memory implementation.

The store owns:

* the **record** (status, result, timings) — mutable, replaced atomically
  via :meth:`update_status` / :meth:`mark_started` / :meth:`mark_completed`;
* the **event log** — append-only, ordered by ``seq`` (1-based, per task).

Why a protocol? Pluggable backends. Tests and the ARQ-less dev flow use
:class:`InMemoryTaskStore`; production runs :class:`SqlTaskStore` (see
``sql_store.py``). Either can be injected into :func:`execute_task`.
"""

from __future__ import annotations

import asyncio
import builtins
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from backend.core.events import Event

from .models import TaskEventRecord, TaskRecord, TaskStatus


@runtime_checkable
class TaskStore(Protocol):
    async def init(self) -> None: ...
    async def close(self) -> None: ...

    async def create(self, record: TaskRecord) -> TaskRecord: ...
    async def get(self, task_id: str) -> TaskRecord | None: ...
    async def list(
        self,
        *,
        user_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[TaskRecord]: ...

    async def mark_started(self, task_id: str) -> None: ...
    async def mark_completed(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        result: dict | None = None,
        error: str | None = None,
        budget: dict | None = None,
    ) -> None: ...

    async def delete(self, task_id: str) -> None: ...
    async def append_event(self, task_id: str, event: Event) -> TaskEventRecord: ...
    async def events(
        self, task_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> builtins.list[TaskEventRecord]: ...


# ---------------------------------------------------------------------------
# In-memory implementation — zero-dep, suitable for dev/test and same-process ARQ.
# ---------------------------------------------------------------------------


class InMemoryTaskStore:
    """Thread-safe in-memory :class:`TaskStore`. Data dies with the process."""

    def __init__(self) -> None:
        self._records: dict[str, TaskRecord] = {}
        self._events: dict[str, list[TaskEventRecord]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def init(self) -> None:  # pragma: no cover — nothing to do
        return

    async def close(self) -> None:  # pragma: no cover
        return

    # ---- CRUD --------------------------------------------------------

    async def create(self, record: TaskRecord) -> TaskRecord:
        async with self._lock:
            if not record.id:
                record = record.model_copy(update={"id": uuid.uuid4().hex})
            if record.id in self._records:
                raise ValueError(f"task '{record.id}' already exists")
            self._records[record.id] = record
            return record

    async def get(self, task_id: str) -> TaskRecord | None:
        async with self._lock:
            return self._records.get(task_id)

    async def delete(self, task_id: str) -> None:
        async with self._lock:
            self._records.pop(task_id, None)
            self._events.pop(task_id, None)

    async def list(
        self,
        *,
        user_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> builtins.list[TaskRecord]:
        async with self._lock:
            records = builtins.list(self._records.values())
        if user_id is not None:
            records = [r for r in records if r.user_id == user_id]
        if status is not None:
            records = [r for r in records if r.status == status]
        records.sort(key=lambda r: r.created_at, reverse=True)
        return records[offset : offset + limit]

    async def mark_started(self, task_id: str) -> None:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(task_id)
            self._records[task_id] = record.model_copy(
                update={"status": "running", "started_at": _now()}
            )

    async def mark_completed(
        self,
        task_id: str,
        *,
        status: TaskStatus,
        result: dict | None = None,
        error: str | None = None,
        budget: dict | None = None,
    ) -> None:
        async with self._lock:
            record = self._records.get(task_id)
            if record is None:
                raise KeyError(task_id)
            updates: dict = {
                "status": status,
                "completed_at": _now(),
            }
            if result is not None:
                updates["result"] = result
            if error is not None:
                updates["error"] = error
            if budget is not None:
                updates["budget"] = budget
            self._records[task_id] = record.model_copy(update=updates)

    # ---- events ------------------------------------------------------

    async def append_event(self, task_id: str, event: Event) -> TaskEventRecord:
        async with self._lock:
            log = self._events[task_id]
            seq = len(log) + 1
            rec = TaskEventRecord(
                task_id=task_id,
                seq=seq,
                type=event.type,
                at=event.at,
                data=dict(event.data),
            )
            log.append(rec)
            return rec

    async def events(
        self, task_id: str, *, after_seq: int = 0, limit: int = 200
    ) -> builtins.list[TaskEventRecord]:
        async with self._lock:
            log = builtins.list(self._events.get(task_id, ()))
        return _after_seq(log, after_seq, limit)


def _after_seq(
    log: Iterable[TaskEventRecord], after_seq: int, limit: int
) -> builtins.list[TaskEventRecord]:
    out: list[TaskEventRecord] = []
    for rec in log:
        if rec.seq > after_seq:
            out.append(rec)
            if len(out) >= limit:
                break
    return out


def _now() -> datetime:
    return datetime.now(UTC)


__all__ = ["InMemoryTaskStore", "TaskStore"]
