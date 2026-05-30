"""High-level entrypoint for booting MCP servers and registering their tools.

Usage from ``backend.app`` lifespan::

    stack = AsyncExitStack()
    await stack.enter_async_context(
        register_mcp_servers(registry, configs, stack=app_lifespan_stack)
    )

Behaviour:

* Each :class:`MCPServerConfig` becomes one :class:`MCPClient`.
* Per-server failures are isolated — one bad server cannot prevent the
  app from booting; we log + skip + keep going. This is essential for
  the laptop-as-personal-assistant use case where a stale config from
  yesterday's experiment shouldn't break today's startup.
* Every successful tool is registered into the supplied
  :class:`ToolRegistry` under ``mcp__<server>__<tool>`` and the registered
  count is logged so operators can verify wiring.
* Returned :class:`AsyncExitStack` (the one passed in) closes every
  client in LIFO order on app shutdown.
"""

from __future__ import annotations

from contextlib import AsyncExitStack
from dataclasses import dataclass

import structlog

from .mcp_client import MCPClient, MCPConnectionError
from .mcp_config import MCPServerConfig
from .mcp_tool import MCPTool
from .registry import ToolRegistry

log = structlog.get_logger(__name__)


@dataclass
class MCPRegistration:
    """Per-server outcome — useful for /api/v1/tools observability."""

    server: str
    transport: str
    connected: bool
    tools: list[str]
    error: str | None = None


async def register_mcp_servers(
    registry: ToolRegistry,
    configs: list[MCPServerConfig],
    *,
    stack: AsyncExitStack,
) -> list[MCPRegistration]:
    """Connect every server in ``configs`` and register its tools.

    Per the design notes above, failures are absorbed per-server. The
    aggregated :class:`MCPRegistration` list lets the caller surface
    boot diagnostics without parsing logs.
    """

    outcomes: list[MCPRegistration] = []
    for cfg in configs:
        outcome = await _register_one(registry=registry, cfg=cfg, stack=stack)
        outcomes.append(outcome)
    return outcomes


async def _register_one(
    *,
    registry: ToolRegistry,
    cfg: MCPServerConfig,
    stack: AsyncExitStack,
) -> MCPRegistration:
    client = MCPClient(cfg)
    try:
        await stack.enter_async_context(client)
    except MCPConnectionError as exc:
        log.warning(
            "tools.mcp.connect_skipped",
            server=cfg.name,
            transport=cfg.transport,
            error=str(exc),
        )
        return MCPRegistration(
            server=cfg.name,
            transport=cfg.transport,
            connected=False,
            tools=[],
            error=str(exc),
        )

    try:
        remote_tools = await client.list_tools()
    except (MCPConnectionError, OSError, RuntimeError, ValueError) as exc:
        log.exception("tools.mcp.list_tools_failed", server=cfg.name)
        return MCPRegistration(
            server=cfg.name,
            transport=cfg.transport,
            connected=True,
            tools=[],
            error=f"list_tools failed: {exc}",
        )

    registered: list[str] = []
    for remote in remote_tools:
        tool = MCPTool(
            client=client,
            remote=remote,
            requires_network=cfg.requires_network,
            requires_paid_api=cfg.requires_paid_api,
        )
        try:
            registry.register(tool)
        except Exception:
            # Name collision is the realistic case here (two servers
            # exposing the same tool name AND server name — should be
            # impossible because mcp_config.load_mcp_config rejects
            # duplicate server names; but defensive log + skip is cheap).
            log.exception("tools.mcp.register_failed", tool=tool.name)
            continue
        registered.append(tool.name)

    log.info(
        "tools.mcp.registered",
        server=cfg.name,
        transport=cfg.transport,
        count=len(registered),
        tools=registered,
    )
    return MCPRegistration(
        server=cfg.name,
        transport=cfg.transport,
        connected=True,
        tools=registered,
    )


__all__ = ["MCPRegistration", "register_mcp_servers"]
