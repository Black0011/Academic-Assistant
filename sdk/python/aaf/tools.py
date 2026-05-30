"""``/api/tools/*`` sub-client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import ToolInfo

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


class AsyncToolsAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(self) -> list[ToolInfo]:
        body = await self._client.request_json("GET", "/api/tools")
        return [ToolInfo.model_validate(item) for item in (body or [])]

    async def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        allow_network: bool = True,
        allow_paid_api: bool = True,
    ) -> dict[str, Any]:
        body = await self._client.request_json(
            "POST",
            f"/api/tools/{name}/invoke",
            json_body={
                "arguments": arguments or {},
                "allow_network": allow_network,
                "allow_paid_api": allow_paid_api,
            },
        )
        return dict(body or {})


class ToolsAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(self) -> list[ToolInfo]:
        body = self._client.request_json("GET", "/api/tools")
        return [ToolInfo.model_validate(item) for item in (body or [])]

    def invoke(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        allow_network: bool = True,
        allow_paid_api: bool = True,
    ) -> dict[str, Any]:
        body = self._client.request_json(
            "POST",
            f"/api/tools/{name}/invoke",
            json_body={
                "arguments": arguments or {},
                "allow_network": allow_network,
                "allow_paid_api": allow_paid_api,
            },
        )
        return dict(body or {})


__all__ = ["AsyncToolsAPI", "ToolsAPI"]
