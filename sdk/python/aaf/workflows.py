"""``/api/workflows/*`` sub-client.

For long-running runs you almost certainly want :class:`aaf.tasks.AsyncTasksAPI`
instead — it goes through the ARQ-backed task queue. The endpoints here
are useful for tests and short workflows where holding an SSE connection
end-to-end is acceptable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from typing import TYPE_CHECKING, Any

from .models import StreamEvent, WorkflowInfo

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


def _payload(
    *,
    query: str,
    input: dict[str, Any] | None,
    user_id: str | None,
    session_id: str | None,
    budget_usd: float | None,
) -> dict[str, Any]:
    return {
        "query": query,
        "input": input or {},
        "user_id": user_id,
        "session_id": session_id,
        "budget_usd": budget_usd,
    }


class AsyncWorkflowsAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(self) -> list[WorkflowInfo]:
        body = await self._client.request_json("GET", "/api/workflows")
        return [WorkflowInfo.model_validate(item) for item in (body or [])]

    async def run(
        self,
        name: str,
        *,
        query: str,
        input: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        budget_usd: float | None = None,
    ) -> dict[str, Any]:
        body = await self._client.request_json(
            "POST",
            f"/api/workflows/{name}/run",
            json_body=_payload(
                query=query,
                input=input,
                user_id=user_id,
                session_id=session_id,
                budget_usd=budget_usd,
            ),
        )
        return dict(body or {})

    async def stream(
        self,
        name: str,
        *,
        query: str,
        input: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        budget_usd: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in self._client.stream_sse(
            f"/api/workflows/{name}/stream",
            method="POST",
            json_body=_payload(
                query=query,
                input=input,
                user_id=user_id,
                session_id=session_id,
                budget_usd=budget_usd,
            ),
        ):
            yield event


class WorkflowsAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(self) -> list[WorkflowInfo]:
        body = self._client.request_json("GET", "/api/workflows")
        return [WorkflowInfo.model_validate(item) for item in (body or [])]

    def run(
        self,
        name: str,
        *,
        query: str,
        input: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        budget_usd: float | None = None,
    ) -> dict[str, Any]:
        body = self._client.request_json(
            "POST",
            f"/api/workflows/{name}/run",
            json_body=_payload(
                query=query,
                input=input,
                user_id=user_id,
                session_id=session_id,
                budget_usd=budget_usd,
            ),
        )
        return dict(body or {})

    def stream(
        self,
        name: str,
        *,
        query: str,
        input: dict[str, Any] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        budget_usd: float | None = None,
    ) -> Iterator[StreamEvent]:
        return self._client.stream_sse(
            f"/api/workflows/{name}/stream",
            method="POST",
            json_body=_payload(
                query=query,
                input=input,
                user_id=user_id,
                session_id=session_id,
                budget_usd=budget_usd,
            ),
        )


__all__ = ["AsyncWorkflowsAPI", "WorkflowsAPI"]
