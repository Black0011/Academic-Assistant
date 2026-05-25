"""Unit tests for `ToolRegistry` — registration, gating, dispatch."""

from __future__ import annotations

from typing import Any

import pytest

from backend.core.errors import ConfigError, NotFoundError
from backend.tools.base import BaseTool, ToolResult
from backend.tools.registry import ToolRegistry


class _Echo(BaseTool):
    name = "test__echo"
    description = "Echo args back"
    parameters = {"type": "object", "properties": {"text": {"type": "string"}}}  # noqa: RUF012
    requires_network = False
    requires_paid_api = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data=dict(arguments))


class _NetTool(BaseTool):
    name = "test__net"
    description = "needs net"
    requires_network = True

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data="net ok")


class _PaidTool(BaseTool):
    name = "test__paid"
    description = "needs paid"
    requires_paid_api = True

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(ok=True, data="paid ok")


class _Boom(BaseTool):
    name = "test__boom"
    description = "raises"

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        raise RuntimeError("kaboom")


async def test_register_and_get():
    reg = ToolRegistry()
    reg.register(_Echo())
    assert reg.has("test__echo")
    assert reg.names() == ["test__echo"]
    assert reg.get("test__echo").name == "test__echo"


async def test_register_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_Echo())
    with pytest.raises(ConfigError):
        reg.register(_Echo())
    # overwrite=True is allowed
    reg.register(_Echo(), overwrite=True)


async def test_get_unknown_raises_not_found():
    reg = ToolRegistry()
    with pytest.raises(NotFoundError):
        reg.get("missing")


async def test_call_dispatches_and_collects_events():
    reg = ToolRegistry()
    reg.register(_Echo())
    events: list[tuple[str, dict[str, Any]]] = []

    async def sink(evt: str, data: dict[str, Any]) -> None:
        events.append((evt, data))

    result = await reg.call("test__echo", {"text": "hi"}, sink=sink)
    assert result.ok is True
    assert result.data == {"text": "hi"}
    assert [e[0] for e in events] == ["skill.call", "skill.result"]
    assert events[0][1]["tool"] == "test__echo"
    assert events[1][1]["ok"] is True


async def test_call_redacts_sensitive_arguments():
    reg = ToolRegistry()
    reg.register(_Echo())
    events: list[tuple[str, dict[str, Any]]] = []

    async def sink(evt: str, data: dict[str, Any]) -> None:
        events.append((evt, data))

    await reg.call("test__echo", {"api_key": "secret", "text": "hi"}, sink=sink)
    call_event = next(e for e in events if e[0] == "skill.call")
    assert call_event[1]["arguments"]["api_key"] == "<redacted>"
    assert call_event[1]["arguments"]["text"] == "hi"


async def test_call_unknown_returns_error_result():
    reg = ToolRegistry()
    res = await reg.call("missing")
    assert res.ok is False
    assert "missing" in (res.error or "")


async def test_call_network_gate():
    reg = ToolRegistry()
    reg.register(_NetTool())
    res = await reg.call("test__net", allow_network=False)
    assert res.ok is False
    assert "network" in (res.error or "")
    # Allowed by default
    res2 = await reg.call("test__net")
    assert res2.ok is True


async def test_call_paid_gate():
    reg = ToolRegistry()
    reg.register(_PaidTool())
    res = await reg.call("test__paid", allow_paid_api=False)
    assert res.ok is False
    assert "paid" in (res.error or "")


async def test_call_wraps_exceptions_into_result():
    reg = ToolRegistry()
    reg.register(_Boom())
    res = await reg.call("test__boom")
    assert res.ok is False
    assert "kaboom" in (res.error or "")
    assert res.meta.get("code") == "aaf.tool_error"


async def test_list_for_injection_filters_by_capability():
    reg = ToolRegistry()
    reg.register(_Echo())
    reg.register(_NetTool())
    reg.register(_PaidTool())

    specs = reg.list_for_injection(allow_network=False, allow_paid_api=False)
    names = {s.name for s in specs}
    assert names == {"test__echo"}

    specs_all = reg.list_for_injection()
    assert {s.name for s in specs_all} == {"test__echo", "test__net", "test__paid"}

    only = reg.list_for_injection(only=["test__net"])
    assert [s.name for s in only] == ["test__net"]
