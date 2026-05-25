"""Long-running task subsystem — persistence, queue, runner.

See PLAN §10.3 / §18.3. The public API is small by design:

* :class:`TaskRecord` / :class:`TaskEventRecord` — Pydantic DTOs.
* :class:`TaskStore` — persistence protocol (in-memory + SQL impls).
* :class:`TaskQueue` — enqueue protocol (in-memory + ARQ impls).
* :func:`execute_task` — the function any worker ultimately calls.
"""

from __future__ import annotations

from .models import CreateTaskInput, TaskEventRecord, TaskRecord, TaskStatus
from .queue import InMemoryTaskQueue, TaskQueue
from .runner import execute_task
from .store import InMemoryTaskStore, TaskStore

__all__ = [
    "CreateTaskInput",
    "InMemoryTaskQueue",
    "InMemoryTaskStore",
    "TaskEventRecord",
    "TaskQueue",
    "TaskRecord",
    "TaskStatus",
    "TaskStore",
    "execute_task",
]
