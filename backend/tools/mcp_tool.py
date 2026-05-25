"""``MCPTool`` — adapt one remote MCP tool into AAF's :class:`Tool` protocol.

Workflows already call tools through :class:`backend.tools.registry.ToolRegistry`
without caring whether the implementation is in-process Python or a
remote MCP server. This adapter is the bridge.

Naming: the registered tool name is ``mcp__<server>__<remote_name>``.
The double-underscore separator matches the existing convention used by
local tools (``arxiv__search``, ``pdf__parse``).
"""

from __future__ import annotations

import copy
import json
from typing import Any

import structlog
from mcp import types as mcp_types

from .base import BaseTool, ToolResult
from .mcp_client import MCPCallError, MCPClient

log = structlog.get_logger(__name__)


def _aaf_tool_name(server: str, remote_name: str) -> str:
    """Project ``(server, remote_name)`` into the AAF tool registry key."""
    return f"mcp__{server}__{remote_name}"


def _flatten_content(content: list[mcp_types.ContentBlock]) -> list[dict[str, Any]]:
    """Collapse MCP content blocks into JSON-safe dicts.

    The MCP spec lets a tool return text / image / embedded-resource blocks.
    For AAF we keep this lossless but typed: every block becomes a dict
    with at least ``type``. Workflows that only care about text can
    inspect ``ok=True`` + ``data["text"]`` (the joined text-block view).
    """

    return [b.model_dump(mode="json", exclude_none=True) for b in content]


def _joined_text(content: list[mcp_types.ContentBlock]) -> str:
    parts: list[str] = []
    for block in content:
        if isinstance(block, mcp_types.TextContent):
            parts.append(block.text)
    return "".join(parts)


def _copy_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Deep copy of the remote tool's input schema.

    The MCP SDK already validates ``inputSchema`` as a ``dict[str, Any]``
    (Pydantic); we then deep-copy it so that mutations on the AAF side
    (e.g. routers projecting it into an OpenAI tool spec, tests
    fiddling with parameters) cannot leak back into the cached remote
    tool descriptor. JSON-Schema is pure data so deepcopy is cheap.
    """
    return copy.deepcopy(schema)


class MCPTool(BaseTool):
    """One AAF tool backed by one remote MCP tool on one server."""

    def __init__(
        self,
        *,
        client: MCPClient,
        remote: mcp_types.Tool,
        requires_network: bool = False,
        requires_paid_api: bool = False,
    ) -> None:
        self._client = client
        self._remote_name = remote.name
        self.name = _aaf_tool_name(client.config.name, remote.name)
        self.description = remote.description or remote.name
        self.parameters = _copy_schema(remote.inputSchema)
        self.requires_network = requires_network
        self.requires_paid_api = requires_paid_api

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        try:
            result = await self._client.call_tool(self._remote_name, arguments)
        except MCPCallError as exc:
            return ToolResult(
                ok=False,
                error=str(exc),
                meta={"code": exc.code, "server": self._client.config.name},
            )

        text = _joined_text(result.content)
        data: dict[str, Any] = {
            "text": text,
            "content": _flatten_content(result.content),
        }
        if result.structuredContent is not None:
            data["structured"] = json.loads(
                json.dumps(result.structuredContent, default=str)
            )

        ok = not bool(result.isError)
        return ToolResult(
            ok=ok,
            data=data,
            error=None if ok else (text or "tool reported isError=true"),
            meta={
                "server": self._client.config.name,
                "remote_name": self._remote_name,
            },
        )


__all__ = ["MCPTool"]
