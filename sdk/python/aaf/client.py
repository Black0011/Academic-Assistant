"""HTTP client for the AAF backend.

Two facades:

* :class:`AsyncAAFClient` — the canonical, async-first implementation.
* :class:`AAFClient`      — a thin sync wrapper for users who don't want
  asyncio. Backed by ``httpx.Client``.

Both share sub-clients (``client.tasks``, ``client.manuscripts``, …) that
expose the matching backend API surface.

Usage
-----

Async:

    from aaf import AsyncAAFClient

    async with AsyncAAFClient("http://localhost:8000") as cli:
        await cli.login("admin@example.com", "secret")
        task = await cli.tasks.create(workflow="research", query="MoE survey")
        async for event in cli.tasks.stream(task.task_id):
            print(event.type, event.data)

Sync:

    from aaf import AAFClient

    with AAFClient("http://localhost:8000", token=os.environ["AAF_TOKEN"]) as cli:
        for ms in cli.manuscripts.list():
            print(ms.title)
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Any

import httpx

from ._version import __version__
from .auth import AsyncAuthAPI, AuthAPI
from .exceptions import raise_for_status
from .manuscripts import AsyncManuscriptsAPI, ManuscriptsAPI
from .memory import (
    AsyncHeuristicsAPI,
    AsyncKnowledgeAPI,
    AsyncMemoryAPI,
    HeuristicsAPI,
    KnowledgeAPI,
    MemoryAPI,
)
from .documents import AsyncDocumentsAPI, DocumentsAPI
from .models import StreamEvent, VersionInfo
from .planner import AsyncPlannerAPI, PlannerAPI
from .proposals import AsyncProposalsAPI, ProposalsAPI
from .skills import AsyncSkillsAPI, SkillsAPI
from .tasks import AsyncTasksAPI, TasksAPI
from .tools import AsyncToolsAPI, ToolsAPI
from .workflows import AsyncWorkflowsAPI, WorkflowsAPI

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=60.0, pool=5.0)
SSE_TIMEOUT = httpx.Timeout(connect=5.0, read=None, write=60.0, pool=5.0)
USER_AGENT = f"aaf-sdk-python/{__version__}"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _strip_base_url(base_url: str) -> str:
    return base_url.rstrip("/")


def _decode_json(response: httpx.Response) -> Any:
    if not response.content:
        return None
    ctype = response.headers.get("content-type", "")
    if "json" not in ctype.lower():
        return response.text
    try:
        return response.json()
    except ValueError:
        return response.text


def _build_headers(token: str | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def parse_sse_block(block: str) -> StreamEvent | None:
    """Parse a single ``\\n``-separated SSE block into a :class:`StreamEvent`.

    Returns ``None`` for blocks that contain only comments / heartbeats.
    """
    event_name = "message"
    data_lines: list[str] = []
    for raw_line in block.splitlines():
        line = raw_line.rstrip("\r")
        if not line or line.startswith(":"):
            continue
        if line.startswith("event:"):
            event_name = line[6:].strip() or event_name
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
        # `id:` and `retry:` are ignored — we don't replay client-side.
    if not data_lines and event_name == "message":
        return None
    raw = "\n".join(data_lines).strip()
    payload: dict[str, Any]
    if raw:
        try:
            decoded = json.loads(raw)
            payload = decoded if isinstance(decoded, dict) else {"value": decoded}
        except ValueError:
            payload = {"raw": raw}
    else:
        payload = {}
    return StreamEvent(
        type=event_name,
        task_id=payload.get("task_id"),
        at=payload.get("at"),
        data=payload.get("data", payload) if "data" in payload else payload,
    )


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class AsyncAAFClient(AbstractAsyncContextManager["AsyncAAFClient"]):
    """Async-first AAF HTTP client.

    Parameters
    ----------
    base_url : root URL of the AAF backend (e.g. ``http://localhost:8000``).
               Trailing slash is stripped. Don't include ``/api``.
    token    : pre-existing JWT. May also be set via :meth:`set_token` /
               populated by :meth:`login`.
    timeout  : ``httpx.Timeout``; the SDK uses a separate, no-read-timeout
               policy for SSE endpoints automatically.
    transport: optional ``httpx.AsyncBaseTransport`` for tests
               (``respx`` / ``httpx.MockTransport``).
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        token: str | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.AsyncBaseTransport | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = _strip_base_url(base_url)
        self._token: str | None = token
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers=_build_headers(self._token),
            transport=transport,
        )
        if not self._owns_client:
            self._sync_authorization()
        self._sse_timeout = SSE_TIMEOUT

        self.auth = AsyncAuthAPI(self)
        self.tasks = AsyncTasksAPI(self)
        self.manuscripts = AsyncManuscriptsAPI(self)
        self.workflows = AsyncWorkflowsAPI(self)
        self.tools = AsyncToolsAPI(self)
        self.knowledge = AsyncKnowledgeAPI(self)
        self.heuristics = AsyncHeuristicsAPI(self)
        self.memory = AsyncMemoryAPI(self)
        self.skills = AsyncSkillsAPI(self)
        self.documents = AsyncDocumentsAPI(self)
        self.proposals = AsyncProposalsAPI(self)
        self.planner = AsyncPlannerAPI(self)

    # -- lifecycle ------------------------------------------------------

    async def __aenter__(self) -> AsyncAAFClient:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # -- auth -----------------------------------------------------------

    @property
    def token(self) -> str | None:
        return self._token

    def set_token(self, token: str | None) -> None:
        """Set the bearer token used for all subsequent requests."""
        self._token = token
        self._sync_authorization()

    def _sync_authorization(self) -> None:
        headers = self._client.headers
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif "Authorization" in headers:
            del headers["Authorization"]

    async def login(self, email: str, password: str) -> str:
        """Convenience: call ``/api/auth/login`` and stash the JWT."""
        response = await self.auth.login(email, password)
        self.set_token(response.access_token)
        return response.access_token

    # -- core HTTP helpers ---------------------------------------------

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: Mapping[str, str] | None = None,
        files: Any | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Any:
        response = await self._client.request(
            method.upper(),
            path,
            params=_compact_params(params),
            json=json_body,
            headers=dict(headers) if headers else None,
            files=files,
            data=data,
        )
        body = _decode_json(response)
        raise_for_status(response.status_code, body)
        return body

    async def stream_sse(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "GET",
        json_body: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        merged_headers = {"Accept": "text/event-stream"}
        if headers:
            merged_headers.update(headers)
        async with self._client.stream(
            method.upper(),
            path,
            params=_compact_params(params),
            json=json_body,
            headers=merged_headers,
            timeout=self._sse_timeout,
        ) as response:
            if response.status_code >= 400:
                content = await response.aread()
                try:
                    body = json.loads(content)
                except ValueError:
                    body = content.decode("utf-8", errors="replace")
                raise_for_status(response.status_code, body)
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = parse_sse_block(block)
                    if event is not None:
                        yield event
            tail = buffer.strip()
            if tail:
                event = parse_sse_block(tail)
                if event is not None:
                    yield event

    # -- misc -----------------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def http(self) -> httpx.AsyncClient:
        """Escape hatch for direct httpx access (e.g. uploads)."""
        return self._client

    async def health(self) -> dict[str, Any]:
        body = await self.request_json("GET", "/api/health")
        return dict(body or {})

    async def version(self) -> VersionInfo:
        body = await self.request_json("GET", "/api/version")
        return VersionInfo.model_validate(body or {})

    async def openapi(self) -> dict[str, Any]:
        return await self.request_json("GET", "/openapi.json")


# ---------------------------------------------------------------------------
# Sync facade
# ---------------------------------------------------------------------------


class AAFClient(AbstractContextManager["AAFClient"]):
    """Synchronous facade for callers that don't want asyncio.

    Wraps an ``httpx.Client``; the surface mirrors :class:`AsyncAAFClient`
    but every method is sync. Streaming endpoints return regular generators.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        token: str | None = None,
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
        transport: httpx.BaseTransport | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._base_url = _strip_base_url(base_url)
        self._token: str | None = token
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=_build_headers(self._token),
            transport=transport,
        )
        if not self._owns_client:
            self._sync_authorization()

        self.auth = AuthAPI(self)
        self.tasks = TasksAPI(self)
        self.manuscripts = ManuscriptsAPI(self)
        self.workflows = WorkflowsAPI(self)
        self.tools = ToolsAPI(self)
        self.knowledge = KnowledgeAPI(self)
        self.heuristics = HeuristicsAPI(self)
        self.memory = MemoryAPI(self)
        self.skills = SkillsAPI(self)
        self.documents = DocumentsAPI(self)
        self.proposals = ProposalsAPI(self)
        self.planner = PlannerAPI(self)

    def __enter__(self) -> AAFClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    @property
    def token(self) -> str | None:
        return self._token

    def set_token(self, token: str | None) -> None:
        self._token = token
        self._sync_authorization()

    def _sync_authorization(self) -> None:
        headers = self._client.headers
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        elif "Authorization" in headers:
            del headers["Authorization"]

    def login(self, email: str, password: str) -> str:
        response = self.auth.login(email, password)
        self.set_token(response.access_token)
        return response.access_token

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        headers: Mapping[str, str] | None = None,
        files: Any | None = None,
        data: Mapping[str, Any] | None = None,
    ) -> Any:
        response = self._client.request(
            method.upper(),
            path,
            params=_compact_params(params),
            json=json_body,
            headers=dict(headers) if headers else None,
            files=files,
            data=data,
        )
        body = _decode_json(response)
        raise_for_status(response.status_code, body)
        return body

    def stream_sse(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        method: str = "GET",
        json_body: Any | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Iterator[StreamEvent]:
        merged_headers = {"Accept": "text/event-stream"}
        if headers:
            merged_headers.update(headers)
        with self._client.stream(
            method.upper(),
            path,
            params=_compact_params(params),
            json=json_body,
            headers=merged_headers,
            timeout=SSE_TIMEOUT,
        ) as response:
            if response.status_code >= 400:
                content = response.read()
                try:
                    body = json.loads(content)
                except ValueError:
                    body = content.decode("utf-8", errors="replace")
                raise_for_status(response.status_code, body)
            buffer = ""
            for chunk in response.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = parse_sse_block(block)
                    if event is not None:
                        yield event
            tail = buffer.strip()
            if tail:
                event = parse_sse_block(tail)
                if event is not None:
                    yield event

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def http(self) -> httpx.Client:
        return self._client

    def health(self) -> dict[str, Any]:
        return dict(self.request_json("GET", "/api/health") or {})


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _compact_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Drop ``None`` values so we don't ship ``?foo=None`` to the server."""
    if params is None:
        return None
    return {k: v for k, v in params.items() if v is not None}


__all__ = [
    "DEFAULT_TIMEOUT",
    "SSE_TIMEOUT",
    "USER_AGENT",
    "AAFClient",
    "AsyncAAFClient",
    "parse_sse_block",
]
