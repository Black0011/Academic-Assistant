"""Tiny FastMCP stdio server used by ``test_mcp_loader.py``.

Exposes two tools:

* ``echo(text: str) -> str``      — returns ``text`` verbatim.
* ``add(a: int, b: int) -> int``  — returns the integer sum.

The point of this fixture is to drive the *real* :class:`MCPClient`
through a *real* stdio MCP server (subprocess) without dragging in any
network egress — keeps the integration test self-contained.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(name="aaf-echo")


@mcp.tool()
def echo(text: str) -> str:
    return text


@mcp.tool()
def add(a: int, b: int) -> int:
    return a + b


if __name__ == "__main__":
    mcp.run(transport="stdio")
