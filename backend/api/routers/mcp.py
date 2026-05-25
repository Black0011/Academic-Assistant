"""Read-only admin endpoints for the MCP client layer.

Lets the frontend (and ``curl``) introspect:

* which MCP servers were declared in the YAML config,
* whether each connected at boot time,
* which tools each one contributes to the registry.

There is **no** "reload" endpoint in this version — the source of truth
is the YAML file (``AAF_MCP_CONFIG``); changing it and restarting the
backend is the supported flow. We intentionally avoid hot-reload until
there is a real product requirement, because tearing down and rebuilding
multiple stdio subprocesses while requests are in flight is a lot of
operational complexity for a personal-laptop tool.
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
    if not isinstance(raw, list):
        return []
    return [r for r in raw if isinstance(r, MCPRegistration)]


@router.get("/servers", response_model=MCPServersResponse, summary="List MCP servers")
async def list_servers(state: AppState = Depends(get_app_state)) -> MCPServersResponse:
    settings = state.settings
    enabled = bool(getattr(settings, "mcp_enabled", False))
    config_path = str(getattr(settings, "mcp_config", ""))
    outcomes = _outcomes(state)
    return MCPServersResponse(
        enabled=enabled,
        config_path=config_path,
        servers=[
            MCPServerStatus(
                name=o.server,
                transport=o.transport,
                connected=o.connected,
                tools=list(o.tools),
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


__all__ = ["router"]
