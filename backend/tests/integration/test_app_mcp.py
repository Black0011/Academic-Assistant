"""Integration tests for ``/api/v1/mcp/*`` admin endpoints."""

from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.settings import Settings
from backend.tools.mcp_config import MCPServerConfig
from backend.tools.mcp_loader import MCPRegistration, register_mcp_servers
from backend.tools.registry import ToolRegistry

ECHO_FIXTURE = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "mcp_servers"
    / "echo_server.py"
)


def _real_outcomes() -> tuple[ToolRegistry, list[MCPRegistration], AsyncExitStack]:
    """Bring up the echo MCP server through the real loader."""
    return ToolRegistry(), [], AsyncExitStack()


@pytest.fixture
async def app_with_real_mcp():
    """An ASGI app whose tool registry contains real MCP-discovered tools.

    We re-use the live ``register_mcp_servers`` path (rather than mocking
    ``state.extras['mcp']``) so the test exercises the same code path
    the lifespan hook does.
    """

    registry = ToolRegistry()
    stack = AsyncExitStack()
    cfg = MCPServerConfig(
        name="echo",
        transport="stdio",
        command=sys.executable,
        args=[str(ECHO_FIXTURE)],
    )
    outcomes = await register_mcp_servers(registry, [cfg], stack=stack)
    state = AppState(
        settings=Settings(),
        tools=registry,
    )
    state.extras["mcp"] = outcomes

    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        try:
            yield http, outcomes
        finally:
            await stack.aclose()


@pytest.mark.asyncio
async def test_list_servers_reports_real_outcome(app_with_real_mcp) -> None:
    http, _outcomes = app_with_real_mcp
    resp = await http.get("/api/v1/mcp/servers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is False  # AAF_MCP_ENABLED default
    assert body["config_path"]
    servers = body["servers"]
    assert len(servers) == 1
    s = servers[0]
    assert s["name"] == "echo"
    assert s["transport"] == "stdio"
    assert s["connected"] is True
    assert s["error"] is None
    assert sorted(s["tools"]) == ["mcp__echo__add", "mcp__echo__echo"]


@pytest.mark.asyncio
async def test_list_server_tools_returns_specs(app_with_real_mcp) -> None:
    http, _ = app_with_real_mcp
    resp = await http.get("/api/v1/mcp/servers/echo/tools")
    assert resp.status_code == 200
    body = resp.json()
    assert body["server"] == "echo"
    names = sorted(t["name"] for t in body["tools"])
    assert names == ["mcp__echo__add", "mcp__echo__echo"]
    echo_spec = next(t for t in body["tools"] if t["name"] == "mcp__echo__echo")
    assert echo_spec["parameters"]["type"] == "object"
    assert "text" in echo_spec["parameters"]["properties"]
    assert echo_spec["requires_network"] is False


@pytest.mark.asyncio
async def test_unknown_server_returns_404(app_with_real_mcp) -> None:
    http, _ = app_with_real_mcp
    resp = await http.get("/api/v1/mcp/servers/nope/tools")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_no_mcp_state_returns_empty_listing() -> None:
    """When MCP was never wired (default boot), the endpoint still works."""
    # Settings has many alias-keyed fields; mypy can't see aliases.
    state = AppState(settings=Settings(), tools=ToolRegistry())  # type: ignore[call-arg]
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.get("/api/v1/mcp/servers")
        assert resp.status_code == 200
        body = resp.json()
        assert body["servers"] == []
        # No servers ⇒ asking for one is a 404.
        resp = await http.get("/api/v1/mcp/servers/anything/tools")
        assert resp.status_code == 404
