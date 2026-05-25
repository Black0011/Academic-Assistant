"""Unit tests for MCPTool — the adapter that projects an MCP remote tool
into AAF's :class:`Tool` protocol.

We mock the :class:`MCPClient` here; tests that exercise the real
client/transport live in ``backend/tests/integration/test_mcp_loader.py``.
"""

from __future__ import annotations

from typing import Any

import pytest
from mcp import types as mcp_types

from backend.tools.mcp_client import MCPCallError, MCPClient
from backend.tools.mcp_config import MCPServerConfig
from backend.tools.mcp_tool import MCPTool, _aaf_tool_name


class _FakeClient:
    """Quacks like MCPClient — only the surface MCPTool actually uses."""

    def __init__(
        self,
        *,
        name: str = "demo",
        result: mcp_types.CallToolResult | None = None,
        raises: Exception | None = None,
    ) -> None:
        self.config = MCPServerConfig(
            name=name, transport="stdio", command="true"
        )
        self._result = result or mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="hello")],
            isError=False,
        )
        self._raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> mcp_types.CallToolResult:
        self.calls.append((name, dict(arguments or {})))
        if self._raises is not None:
            raise self._raises
        return self._result


def _remote(
    name: str = "echo",
    *,
    description: str | None = "echo back",
    schema: dict[str, Any] | None = None,
) -> mcp_types.Tool:
    return mcp_types.Tool(
        name=name,
        description=description,
        inputSchema=schema or {"type": "object", "properties": {"x": {"type": "string"}}},
    )


def test_aaf_tool_name_format() -> None:
    assert _aaf_tool_name("fs", "read_file") == "mcp__fs__read_file"


def test_adapter_exposes_protocol_surface() -> None:
    fake = _FakeClient(name="fs")
    tool = MCPTool(client=fake, remote=_remote("read_file"))  # type: ignore[arg-type]
    assert tool.name == "mcp__fs__read_file"
    assert tool.description == "echo back"
    assert tool.parameters["type"] == "object"
    assert tool.requires_network is False
    assert tool.requires_paid_api is False


def test_adapter_capability_flags_propagate() -> None:
    fake = _FakeClient()
    tool = MCPTool(
        client=fake,  # type: ignore[arg-type]
        remote=_remote(),
        requires_network=True,
        requires_paid_api=True,
    )
    assert tool.requires_network is True
    assert tool.requires_paid_api is True


def test_adapter_copies_schema_defensively() -> None:
    """Mutating the AAF-side schema must not affect the cached remote tool."""
    fake = _FakeClient()
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    remote = mcp_types.Tool(name="x", description="", inputSchema=schema)
    tool = MCPTool(client=fake, remote=remote)  # type: ignore[arg-type]
    tool.parameters["properties"]["y"] = {"type": "string"}
    assert "y" not in remote.inputSchema["properties"]


@pytest.mark.asyncio
async def test_call_returns_text_view() -> None:
    fake = _FakeClient(
        result=mcp_types.CallToolResult(
            content=[
                mcp_types.TextContent(type="text", text="part1"),
                mcp_types.TextContent(type="text", text="-part2"),
            ],
            isError=False,
        )
    )
    tool = MCPTool(client=fake, remote=_remote())  # type: ignore[arg-type]
    result = await tool.call({"x": "y"})
    assert result.ok is True
    assert result.error is None
    assert result.data["text"] == "part1-part2"
    assert len(result.data["content"]) == 2
    assert fake.calls == [("echo", {"x": "y"})]
    assert result.meta["server"] == "demo"
    assert result.meta["remote_name"] == "echo"


@pytest.mark.asyncio
async def test_call_propagates_is_error() -> None:
    fake = _FakeClient(
        result=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="boom")],
            isError=True,
        )
    )
    tool = MCPTool(client=fake, remote=_remote())  # type: ignore[arg-type]
    result = await tool.call({})
    assert result.ok is False
    assert result.error == "boom"


@pytest.mark.asyncio
async def test_call_returns_failure_on_mcp_call_error() -> None:
    fake = _FakeClient(raises=MCPCallError("transport blew up"))
    tool = MCPTool(client=fake, remote=_remote())  # type: ignore[arg-type]
    result = await tool.call({})
    assert result.ok is False
    assert "transport blew up" in (result.error or "")
    assert result.meta["code"] == "aaf.mcp.call_failed"
    assert result.meta["server"] == "demo"


@pytest.mark.asyncio
async def test_call_includes_structured_content() -> None:
    fake = _FakeClient(
        result=mcp_types.CallToolResult(
            content=[mcp_types.TextContent(type="text", text="ok")],
            structuredContent={"rows": [1, 2, 3]},
            isError=False,
        )
    )
    tool = MCPTool(client=fake, remote=_remote())  # type: ignore[arg-type]
    result = await tool.call({})
    assert result.ok is True
    assert result.data["structured"] == {"rows": [1, 2, 3]}


# Sanity: a real MCPClient cannot be replaced with `_FakeClient` at type
# level (we use type: ignore at the call sites). Confirm the fake at
# least implements `call_tool` with the same shape so a future refactor
# of the protocol catches drift.
def test_fake_client_matches_real_call_signature() -> None:
    import inspect

    real = inspect.signature(MCPClient.call_tool)
    fake = inspect.signature(_FakeClient.call_tool)
    assert list(real.parameters.keys())[:3] == list(fake.parameters.keys())[:3]
