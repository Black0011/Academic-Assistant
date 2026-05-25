"""Integration tests for `/api/tools` routes."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.settings import Settings
from backend.tools.base import BaseTool, ToolResult
from backend.tools.registry import ToolRegistry


class _Echo(BaseTool):
    name = "test__echo"
    description = "Echo back the arguments."
    parameters = {  # noqa: RUF012
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }
    requires_network = False
    requires_paid_api = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data=dict(arguments))


class _Net(BaseTool):
    name = "test__net"
    description = "Needs net"
    requires_network = True

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data="net ok")


@pytest.fixture
async def client():
    reg = ToolRegistry()
    reg.register(_Echo())
    reg.register(_Net())
    state = AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
        tools=reg,
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_list_tools(client):
    r = await client.get("/api/tools")
    assert r.status_code == 200
    body = r.json()
    names = sorted(t["name"] for t in body)
    assert names == ["test__echo", "test__net"]


async def test_invoke_tool(client):
    r = await client.post(
        "/api/tools/test__echo/invoke",
        json={"arguments": {"text": "hi"}},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["data"] == {"text": "hi"}


async def test_invoke_unknown_tool_404(client):
    r = await client.post("/api/tools/missing/invoke", json={"arguments": {}})
    assert r.status_code == 404


async def test_invoke_respects_network_flag(client):
    r = await client.post(
        "/api/tools/test__net/invoke",
        json={"arguments": {}, "allow_network": False},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert "network" in body["error"].lower()
