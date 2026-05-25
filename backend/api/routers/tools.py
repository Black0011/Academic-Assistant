"""Introspection endpoints for the shared tool registry.

Exposes the *names and specs* of registered tools so operators / the
frontend can render a palette, and an ``invoke`` endpoint used by
debugging UIs and smoke tests. Real agent runs should call tools through
a workflow, not these routes — we expose them here to keep the surface
debuggable without reaching into the Python REPL.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.core.app_state import AppState, get_app_state

router = APIRouter(prefix="/api/tools", tags=["tools"])


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]
    requires_network: bool
    requires_paid_api: bool


class InvokeRequest(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)
    allow_network: bool = True
    allow_paid_api: bool = True


class InvokeResponse(BaseModel):
    ok: bool
    data: Any | None = None
    error: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


@router.get("", summary="List registered tools")
async def list_tools(state: AppState = Depends(get_app_state)) -> list[ToolInfo]:
    if state.tools is None:
        return []
    out: list[ToolInfo] = []
    for name in state.tools.names():
        tool = state.tools.get(name)
        out.append(
            ToolInfo(
                name=tool.name,
                description=tool.description,
                parameters=dict(tool.parameters),
                requires_network=tool.requires_network,
                requires_paid_api=tool.requires_paid_api,
            )
        )
    return out


@router.post("/{name}/invoke", response_model=InvokeResponse, summary="Invoke a tool")
async def invoke(
    name: str,
    req: InvokeRequest,
    state: AppState = Depends(get_app_state),
) -> InvokeResponse:
    if state.tools is None or not state.tools.has(name):
        raise HTTPException(status_code=404, detail=f"tool '{name}' not found")
    result = await state.tools.call(
        name,
        req.arguments,
        allow_network=req.allow_network,
        allow_paid_api=req.allow_paid_api,
    )
    return InvokeResponse(ok=result.ok, data=result.data, error=result.error, meta=result.meta)
