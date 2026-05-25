"""``/api/tasks/*`` sub-client.

Long-running workflow runs land on this surface. Highlights:

* :meth:`AsyncTasksAPI.create` enqueues a workflow.
* :meth:`AsyncTasksAPI.stream` yields one :class:`StreamEvent` per server
  event using SSE.
* :meth:`AsyncTasksAPI.wait` polls until the task is terminal — handy
  for synchronous-feeling scripts.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

from .exceptions import APIError
from .models import (
    CreateTaskResponse,
    StreamEvent,
    TaskEventRecord,
    TaskRecord,
    TaskStatus,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


class AsyncTasksAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        workflow: str,
        query: str = "",
        input: dict[str, Any] | None = None,
        budget_usd: float | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> CreateTaskResponse:
        body = await self._client.request_json(
            "POST",
            "/api/tasks",
            json_body={
                "workflow": workflow,
                "query": query,
                "input": input or {},
                "budget_usd": budget_usd,
                "user_id": user_id,
                "session_id": session_id,
            },
        )
        return CreateTaskResponse.model_validate(body)

    async def get(self, task_id: str) -> TaskRecord:
        body = await self._client.request_json("GET", f"/api/tasks/{task_id}")
        return TaskRecord.model_validate(body)

    async def list_all(
        self,
        *,
        user_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRecord]:
        body = await self._client.request_json(
            "GET",
            "/api/tasks",
            params={
                "user_id": user_id,
                "task_status": status,
                "limit": limit,
                "offset": offset,
            },
        )
        return [TaskRecord.model_validate(item) for item in (body or {}).get("items", [])]

    async def cancel(self, task_id: str) -> TaskRecord:
        body = await self._client.request_json("DELETE", f"/api/tasks/{task_id}")
        return TaskRecord.model_validate(body)

    async def events(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> tuple[list[TaskEventRecord], int]:
        body = await self._client.request_json(
            "GET",
            f"/api/tasks/{task_id}/events",
            params={"after_seq": after_seq, "limit": limit},
        )
        items = [TaskEventRecord.model_validate(item) for item in (body or {}).get("items", [])]
        next_after = int((body or {}).get("next_after_seq", after_seq))
        return items, next_after

    async def stream(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        async for event in self._client.stream_sse(
            f"/api/tasks/{task_id}/stream",
            params={"after_seq": after_seq},
        ):
            yield event

    async def wait(
        self,
        task_id: str,
        *,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.5,
    ) -> TaskRecord:
        """Poll until the task reaches a terminal status or `timeout_s` lapses.

        Polling avoids holding an SSE connection open across the entire
        run; for live progress prefer :meth:`stream`.
        """
        deadline = asyncio.get_event_loop().time() + timeout_s
        while True:
            record = await self.get(task_id)
            if record.is_terminal:
                return record
            now = asyncio.get_event_loop().time()
            if now >= deadline:
                raise TimeoutError(f"task {task_id} did not terminate within {timeout_s}s")
            await asyncio.sleep(min(poll_interval_s, deadline - now))


class TasksAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def create(
        self,
        *,
        workflow: str,
        query: str = "",
        input: dict[str, Any] | None = None,
        budget_usd: float | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> CreateTaskResponse:
        body = self._client.request_json(
            "POST",
            "/api/tasks",
            json_body={
                "workflow": workflow,
                "query": query,
                "input": input or {},
                "budget_usd": budget_usd,
                "user_id": user_id,
                "session_id": session_id,
            },
        )
        return CreateTaskResponse.model_validate(body)

    def get(self, task_id: str) -> TaskRecord:
        body = self._client.request_json("GET", f"/api/tasks/{task_id}")
        return TaskRecord.model_validate(body)

    def list_all(
        self,
        *,
        user_id: str | None = None,
        status: TaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRecord]:
        body = self._client.request_json(
            "GET",
            "/api/tasks",
            params={
                "user_id": user_id,
                "task_status": status,
                "limit": limit,
                "offset": offset,
            },
        )
        return [TaskRecord.model_validate(item) for item in (body or {}).get("items", [])]

    def cancel(self, task_id: str) -> TaskRecord:
        body = self._client.request_json("DELETE", f"/api/tasks/{task_id}")
        return TaskRecord.model_validate(body)

    def events(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 200,
    ) -> tuple[list[TaskEventRecord], int]:
        body = self._client.request_json(
            "GET",
            f"/api/tasks/{task_id}/events",
            params={"after_seq": after_seq, "limit": limit},
        )
        items = [TaskEventRecord.model_validate(item) for item in (body or {}).get("items", [])]
        next_after = int((body or {}).get("next_after_seq", after_seq))
        return items, next_after

    def stream(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
    ) -> Iterator[StreamEvent]:
        return self._client.stream_sse(
            f"/api/tasks/{task_id}/stream",
            params={"after_seq": after_seq},
        )

    def wait(
        self,
        task_id: str,
        *,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.5,
    ) -> TaskRecord:
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                record = self.get(task_id)
            except APIError as exc:
                if exc.status_code == 404:
                    raise
                raise
            if record.is_terminal:
                return record
            now = time.monotonic()
            if now >= deadline:
                raise TimeoutError(f"task {task_id} did not terminate within {timeout_s}s")
            time.sleep(min(poll_interval_s, deadline - now))


__all__ = ["AsyncTasksAPI", "TasksAPI"]
