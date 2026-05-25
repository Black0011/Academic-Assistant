"""Lifecycle wrapper around one MCP ``ClientSession``.

The Anthropic ``mcp`` SDK exposes a session through nested async context
managers (``stdio_client(...) -> read,write`` then ``ClientSession(...)``).
That works fine inside a single ``async with`` block but is a sharp edge
for AAF, which needs to:

* keep many MCP sessions live for the entire app lifespan,
* close them cleanly on shutdown,
* survive the case where one server crashes without taking the rest down.

The first naive design used ``contextlib.AsyncExitStack`` to hold every
session open across many awaits.  That trips the well-known anyio
"Attempted to exit cancel scope in a different task than it was entered
in" error — the SDK's stdio transport opens an ``anyio.TaskGroup`` whose
cancel scope must be entered and exited from the same task, but
``AsyncExitStack`` does not preserve that invariant when the enter and
exit are split across two awaits in different stages of the lifespan.

The fix used here is to put the *entire* enter/exit dance inside one
background task.  The foreground waits on an ``asyncio.Event`` for the
session to be ready (or for an early failure); shutdown is signalled by
setting another event, which lets the background task unwind its own
context managers in its own task.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from mcp import types as mcp_types
from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client

from backend.core.errors import AAFError

from .mcp_config import MCPServerConfig

log = structlog.get_logger(__name__)


class MCPConnectionError(AAFError):
    """Raised when an MCP server cannot be reached or initialised."""

    code = "aaf.mcp.connect_failed"


class MCPCallError(AAFError):
    """Raised when ``call_tool`` fails at the transport / session layer."""

    code = "aaf.mcp.call_failed"


class MCPClient:
    """One live MCP session, scoped to ``self.config.name``.

    Use as ``async with`` or via explicit ``connect()`` / ``aclose()``.
    The async-context-manager flavour exists so :class:`AsyncExitStack`
    consumers (the loader) can drive many clients with one stack — but
    the lifecycle itself runs entirely in a background task, see the
    module docstring for why.
    """

    __slots__ = (
        "_connect_error",
        "_ready",
        "_session",
        "_shutdown",
        "_task",
        "config",
    )

    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config
        self._session: ClientSession | None = None
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self._shutdown = asyncio.Event()
        self._connect_error: BaseException | None = None

    # -- lifecycle -----------------------------------------------------

    async def connect(self) -> ClientSession:
        """Spawn the lifecycle task and wait for the session to come up."""
        if self._session is not None:
            return self._session
        if self._task is not None:
            # connect() already in flight; wait for it.
            await self._ready.wait()
            if self._connect_error is not None:
                raise self._connect_error
            assert self._session is not None
            return self._session

        self._task = asyncio.create_task(
            self._run(), name=f"mcp-client[{self.config.name}]"
        )
        await self._ready.wait()
        if self._connect_error is not None:
            # Make sure the task is fully awaited so its exception is consumed.
            await self._await_task_silently()
            err = self._connect_error
            assert isinstance(err, BaseException)
            if isinstance(err, MCPConnectionError):
                raise err
            raise MCPConnectionError(
                f"failed to connect MCP server '{self.config.name}': {err}"
            ) from err

        assert self._session is not None
        log.info(
            "tools.mcp.connected",
            server=self.config.name,
            transport=self.config.transport,
        )
        return self._session

    async def aclose(self) -> None:
        if self._task is None:
            return
        self._shutdown.set()
        await self._await_task_silently()
        self._task = None
        self._session = None

    async def _await_task_silently(self) -> None:
        if self._task is None:
            return
        try:
            await self._task
        except (OSError, RuntimeError, MCPConnectionError):
            # Lifecycle task already logged the cause; we just don't want
            # awaiting it again to crash the shutdown path.
            log.debug("tools.mcp.lifecycle_task_exited_with_error", server=self.config.name)
        except BaseException:
            log.exception("tools.mcp.lifecycle_task_unexpected", server=self.config.name)
            raise

    async def __aenter__(self) -> MCPClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def _run(self) -> None:
        """Hold the SDK's nested context managers open in one task."""

        try:
            if self.config.transport == "stdio":
                params = StdioServerParameters(
                    command=self.config.command,
                    args=list(self.config.args),
                    env=dict(self.config.env) or None,
                    cwd=self.config.cwd or None,
                )
                async with stdio_client(params) as (read, write):
                    await self._serve(read, write)
            elif self.config.transport == "sse":
                async with sse_client(
                    self.config.url,
                    headers=dict(self.config.headers) or None,
                    timeout=self.config.connect_timeout_s,
                ) as transport:
                    read, write = transport[0], transport[1]
                    await self._serve(read, write)
            else:  # pragma: no cover - exhaustively covered by the Literal
                raise MCPConnectionError(
                    f"unsupported transport '{self.config.transport}' "
                    f"for server '{self.config.name}'"
                )
        except (OSError, RuntimeError, ValueError, MCPConnectionError) as exc:
            self._connect_error = (
                exc
                if isinstance(exc, MCPConnectionError)
                else MCPConnectionError(
                    f"failed to connect MCP server '{self.config.name}': {exc}"
                )
            )
            log.warning(
                "tools.mcp.lifecycle_failed",
                server=self.config.name,
                error=str(exc),
            )
        except BaseException as exc:  # pragma: no cover - last-resort net
            self._connect_error = MCPConnectionError(
                f"unexpected MCP lifecycle error for '{self.config.name}': {exc}"
            )
            log.exception("tools.mcp.lifecycle_unexpected", server=self.config.name)
        finally:
            self._ready.set()

    async def _serve(self, read: object, write: object) -> None:
        """Initialise the session and block until shutdown is signalled."""

        async with ClientSession(read, write) as session:  # type: ignore[arg-type]
            await session.initialize()
            self._session = session
            self._ready.set()
            await self._shutdown.wait()

    # -- session passthroughs -----------------------------------------

    @property
    def session(self) -> ClientSession:
        if self._session is None:
            raise MCPConnectionError(
                f"MCP server '{self.config.name}' is not connected"
            )
        return self._session

    async def list_tools(self) -> list[mcp_types.Tool]:
        """Return the server's tool catalogue, applying ``allow`` filter."""
        result = await self.session.list_tools()
        tools = list(result.tools)
        if self.config.allow is not None:
            allowed = set(self.config.allow)
            tools = [t for t in tools if t.name in allowed]
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mcp_types.CallToolResult:
        """Forward to ``ClientSession.call_tool`` with one error boundary."""
        try:
            return await self.session.call_tool(name, arguments or {})
        except (OSError, RuntimeError, ValueError) as exc:
            raise MCPCallError(
                f"MCP call '{self.config.name}.{name}' failed: {exc}"
            ) from exc


__all__ = ["MCPCallError", "MCPClient", "MCPConnectionError"]
