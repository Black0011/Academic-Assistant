"""Integration test for the MCP client + adapter + loader chain.

We spin up a real :mod:`backend.tests.fixtures.mcp_servers.echo_server`
as a stdio subprocess, hand its config to :func:`register_mcp_servers`,
and assert the discovered tools land in :class:`ToolRegistry` and round-trip
correctly through ``registry.call(...)``.

The test runs at most a few hundred milliseconds — FastMCP starts up
fast, and the two tools (echo / add) are pure Python.
"""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest

from backend.tools.mcp_client import MCPClient
from backend.tools.mcp_config import MCPServerConfig
from backend.tools.mcp_loader import register_mcp_servers
from backend.tools.registry import ToolRegistry

FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "mcp_servers"
    / "echo_server.py"
)


def _config(*, allow: list[str] | None = None) -> MCPServerConfig:
    return MCPServerConfig(
        name="echo",
        transport="stdio",
        command=sys.executable,
        args=[str(FIXTURE)],
        allow=allow,
    )


@pytest.mark.asyncio
async def test_client_lists_and_calls_real_server() -> None:
    async with MCPClient(_config()) as client:
        tools = await client.list_tools()
        names = sorted(t.name for t in tools)
        assert names == ["add", "echo"]

        echo = await client.call_tool("echo", {"text": "hi"})
        # FastMCP wraps scalar return values in a TextContent block.
        assert any(getattr(c, "text", None) == "hi" for c in echo.content)
        assert echo.isError is False


@pytest.mark.asyncio
async def test_loader_registers_namespaced_tools() -> None:
    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        outcomes = await register_mcp_servers(
            registry, [_config()], stack=stack
        )
        assert len(outcomes) == 1
        assert outcomes[0].connected is True
        assert outcomes[0].error is None
        assert sorted(outcomes[0].tools) == ["mcp__echo__add", "mcp__echo__echo"]

        assert "mcp__echo__echo" in registry.names()
        assert "mcp__echo__add" in registry.names()

        result = await registry.call("mcp__echo__echo", {"text": "hello mcp"})
        assert result.ok is True
        assert "hello mcp" in (result.data["text"] or "")
        assert result.meta["server"] == "echo"
        assert result.meta["remote_name"] == "echo"

        sum_result = await registry.call("mcp__echo__add", {"a": 2, "b": 3})
        assert sum_result.ok is True
        # FastMCP serialises the integer return as text in the content blocks.
        assert "5" in (sum_result.data["text"] or "")


@pytest.mark.asyncio
async def test_loader_respects_allow_filter() -> None:
    registry = ToolRegistry()
    async with AsyncExitStack() as stack:
        outcomes = await register_mcp_servers(
            registry, [_config(allow=["echo"])], stack=stack
        )
        assert outcomes[0].tools == ["mcp__echo__echo"]
        assert "mcp__echo__add" not in registry.names()


@pytest.mark.asyncio
async def test_loader_isolates_per_server_failures() -> None:
    """A bogus server entry must not block a healthy one."""

    bad = MCPServerConfig(
        name="dead",
        transport="stdio",
        command=sys.executable,
        args=["-c", "import sys; sys.exit(7)"],
        connect_timeout_s=2.0,
    )
    good = _config()
    registry = ToolRegistry()

    async with AsyncExitStack() as stack:
        outcomes = await register_mcp_servers(registry, [bad, good], stack=stack)

    by_name = {o.server: o for o in outcomes}
    assert by_name["dead"].connected is False
    assert by_name["dead"].error  # populated with the connect failure
    assert by_name["echo"].connected is True
    assert "mcp__echo__echo" in registry.names()
    assert "mcp__dead__echo" not in registry.names()
