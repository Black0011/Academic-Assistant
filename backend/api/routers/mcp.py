"""MCP admin endpoints — introspect and reload MCP server connections.

- ``GET  /api/v1/mcp/servers``       — list all configured servers
- ``GET  /api/v1/mcp/servers/{name}/tools`` — tools from one server
- ``POST /api/v1/mcp/reload``        — hot-reload MCP config without restart
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.tools.mcp_loader import MCPRegistration

router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])


class MCPServerStatus(BaseModel):
    """Per-server boot outcome surfaced from ``AppState.extras['mcp']``."""

    model_config = ConfigDict(extra="forbid")

    name: str
    transport: str
    connected: bool
    tools: list[str] = Field(default_factory=list)
    error: str | None = None


class MCPServersResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool
    config_path: str
    servers: list[MCPServerStatus] = Field(default_factory=list)


class MCPToolInfo(BaseModel):
    """One AAF-registered tool that came from this MCP server."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, object] = Field(default_factory=dict)
    requires_network: bool
    requires_paid_api: bool


class MCPToolsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    server: str
    tools: list[MCPToolInfo] = Field(default_factory=list)


def _outcomes(state: AppState) -> list[MCPRegistration]:
    raw = state.extras.get("mcp") if state else None
    if raw is None:
        return []
    # New structure: {"servers_list": [...], ...}
    if isinstance(raw, dict):
        return raw.get("servers_list", [])
    # Old structure: [...]
    if isinstance(raw, list):
        return [r for r in raw if isinstance(r, MCPRegistration)]
    return []


@router.get("/servers", response_model=MCPServersResponse, summary="List MCP servers")
async def list_servers(state: AppState = Depends(get_app_state)) -> MCPServersResponse:
    settings = state.settings
    enabled = bool(getattr(settings, "mcp_enabled", False))
    config_path = str(getattr(settings, "mcp_config", ""))
    outcomes = _outcomes(state)
    # Query live tool registry for MCP tools (more accurate than saved outcomes)
    live_tools: dict[str, list[str]] = {}
    if state.tools is not None:
        for name in state.tools.names():
            if name.startswith("mcp__"):
                parts = name.split("__", 2)
                server = parts[1] if len(parts) > 1 else "unknown"
                live_tools.setdefault(server, []).append(name)

    return MCPServersResponse(
        enabled=enabled,
        config_path=config_path,
        servers=[
            MCPServerStatus(
                name=o.server,
                transport=o.transport,
                connected=o.connected,
                tools=live_tools.get(o.server, list(o.tools)),  # prefer live registry
                error=o.error,
            )
            for o in outcomes
        ],
    )


@router.get(
    "/servers/{name}/tools",
    response_model=MCPToolsResponse,
    summary="List tools contributed by one MCP server",
)
async def list_server_tools(
    name: str,
    state: AppState = Depends(get_app_state),
) -> MCPToolsResponse:
    outcomes = _outcomes(state)
    match = next((o for o in outcomes if o.server == name), None)
    if match is None:
        raise HTTPException(
            status_code=404, detail=f"MCP server '{name}' not registered"
        )
    if state.tools is None:
        return MCPToolsResponse(server=name, tools=[])
    items: list[MCPToolInfo] = []
    for tool_name in match.tools:
        if not state.tools.has(tool_name):
            continue
        tool = state.tools.get(tool_name)
        items.append(
            MCPToolInfo(
                name=tool.name,
                description=tool.description,
                parameters=dict(tool.parameters),
                requires_network=tool.requires_network,
                requires_paid_api=tool.requires_paid_api,
            )
        )
    return MCPToolsResponse(server=name, tools=items)


class MCPReloadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    servers: int
    tools: int
    message: str = ""


@router.post(
    "/reload",
    response_model=MCPReloadResponse,
    summary="Hot-reload MCP configuration without restarting the backend",
)
async def reload_mcp_config(
    state: AppState = Depends(get_app_state),
) -> MCPReloadResponse:
    """Tear down existing MCP connections and re-register from config.

    Supports both AAF YAML (``config/mcp_servers.yaml``) and Claude Code
    compatible ``.mcp.json`` format.
    """
    mcp_extra: dict = state.extras.get("mcp", {})
    reload_fn = mcp_extra.get("_reload_fn")
    if reload_fn is None:
        raise HTTPException(
            status_code=501,
            detail="MCP reload not configured. Set AAF_MCP_ENABLED=true and restart once.",
        )
    try:
        result = await reload_fn()
        return MCPReloadResponse(
            ok=True,
            servers=result.get("servers", 0),
            tools=result.get("tools", 0),
            message=f"Reloaded {result.get('servers', 0)} servers, {result.get('tools', 0)} tools",
        )
    except Exception as exc:
        return MCPReloadResponse(
            ok=False, servers=0, tools=0, message=f"Reload failed: {exc}"
        )


__all__ = ["router"]
