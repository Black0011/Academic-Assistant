"""TaskQueue — enqueue a task for execution.

Two implementations:

* :class:`InMemoryTaskQueue` — ``asyncio.create_task`` inside the API
  process. Zero infra; dies with the process. Default for dev / tests.
* :class:`ArqTaskQueue` — pushes the task id into Redis for a separate
  ARQ worker to pick up. The worker runs the very same :func:`execute_task`.

Both implementations share the :class:`TaskQueue` protocol, so the router
never imports either concretely.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

from .runner import RunnerDeps, execute_task

if TYPE_CHECKING:  # pragma: no cover
    from arq.connections import ArqRedis

log = structlog.get_logger(__name__)


@runtime_checkable
class TaskQueue(Protocol):
    async def enqueue(self, task_id: str) -> None: ...
    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# In-memory queue
# ---------------------------------------------------------------------------


class InMemoryTaskQueue:
    """Same-process async queue. Holds strong refs so jobs aren't GC'd."""

    def __init__(self, deps: RunnerDeps) -> None:
        self._deps = deps
        self._jobs: set[asyncio.Task[None]] = set()
        self._closed = False

    async def enqueue(self, task_id: str) -> None:
        if self._closed:
            raise RuntimeError("queue is closed")
        job = asyncio.create_task(self._run(task_id), name=f"aaf-task-{task_id}")
        self._jobs.add(job)
        job.add_done_callback(self._jobs.discard)

    async def _run(self, task_id: str) -> None:
        try:
            await execute_task(task_id, self._deps)
        except Exception:  # belt-and-braces; execute_task shouldn't raise
            log.exception("inmem_queue.execute_failed", task_id=task_id)

    async def drain(self) -> None:
        """Wait for every in-flight job to finish. Test-only convenience."""
        if not self._jobs:
            return
        await asyncio.gather(*list(self._jobs), return_exceptions=True)

    async def close(self) -> None:
        self._closed = True
        for job in list(self._jobs):
            if not job.done():
                job.cancel()
        await self.drain()


# ---------------------------------------------------------------------------
# ARQ queue (optional — module imports arq lazily)
# ---------------------------------------------------------------------------


ARQ_JOB_NAME = "aaf_execute_task"


class ArqTaskQueue:
    """Push task ids into Redis for the ARQ worker.

    The worker is a separate process; it builds its own :class:`RunnerDeps`
    in :mod:`backend.workers.arq_worker`. Here we only need a pool.
    """

    def __init__(self, pool: ArqRedis) -> None:
        self._pool = pool

    @classmethod
    async def from_url(cls, redis_url: str) -> ArqTaskQueue:
        from arq import create_pool
        from arq.connections import RedisSettings

        settings = RedisSettings.from_dsn(redis_url)
        pool = await create_pool(settings)
        return cls(pool)

    async def enqueue(self, task_id: str) -> None:
        await self._pool.enqueue_job(ARQ_JOB_NAME, task_id, _job_id=task_id)

    async def close(self) -> None:
        try:
            await self._pool.aclose()  # arq / redis-py 5+
        except AttributeError:  # pragma: no cover
            close = getattr(self._pool, "close", None)
            if close is not None:
                maybe = close()
                if asyncio.iscoroutine(maybe):
                    await maybe


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def build_task_queue(kind: str, *, deps: RunnerDeps, redis_url: str = "") -> TaskQueue:
    """Build the appropriate queue. ``kind`` is one of: ``inmemory``, ``arq``."""
    if kind == "arq":
        if not redis_url:
            raise ValueError("arq queue requires redis_url")
        return await ArqTaskQueue.from_url(redis_url)
    return InMemoryTaskQueue(deps)


__all__ = [
    "ARQ_JOB_NAME",
    "ArqTaskQueue",
    "InMemoryTaskQueue",
    "TaskQueue",
    "build_task_queue",
]


def _unused(_: Any) -> None: ...  # keep mypy quiet if Any import pruned  # pragma: no cover
