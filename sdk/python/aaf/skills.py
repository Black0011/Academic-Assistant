"""``/api/skills/*`` sub-client (M7.2).

Mirrors :mod:`backend.api.routers.skills` and exposes the same surface
both async and sync. Sub-clients accept either ``SkillInstallInput`` (a
typed payload) or a raw ``dict`` for callers who'd rather not import the
DTOs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import (
    SkillDetail,
    SkillDryRunResponse,
    SkillInstallInput,
    SkillInvocation,
    SkillReloadResponse,
    SkillScriptSource,
    SkillSummary,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


def _coerce_payload(payload: SkillInstallInput | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, SkillInstallInput):
        return payload.model_dump()
    return dict(payload)


class _SkillsListEnvelope:
    """Internal helper — mirrors the router envelope without exposing it.

    The router returns ``{"items": [...], "total": ..., "generation": ...}``
    but the SDK's other sub-clients have settled on returning the items
    list directly. We keep the envelope reachable via ``raw`` when
    callers want the metadata.
    """

    __slots__ = ("items", "total", "generation")

    def __init__(self, items: list[SkillSummary], total: int, generation: int) -> None:
        self.items = items
        self.total = total
        self.generation = generation


class AsyncSkillsAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(
        self,
        *,
        include_disabled: bool = True,
        domain: str | None = None,
    ) -> list[SkillSummary]:
        params: dict[str, Any] = {"include_disabled": include_disabled}
        if domain:
            params["domain"] = domain
        body = await self._client.request_json("GET", "/api/skills", params=params)
        return [SkillSummary.model_validate(item) for item in (body or {}).get("items", [])]

    async def get(self, name: str) -> SkillDetail:
        body = await self._client.request_json("GET", f"/api/skills/{name}")
        return SkillDetail.model_validate(body)

    async def get_script(self, name: str, script: str) -> SkillScriptSource:
        body = await self._client.request_json(
            "GET", f"/api/skills/{name}/scripts/{script}"
        )
        return SkillScriptSource.model_validate(body)

    async def invocations(
        self,
        name: str,
        *,
        limit: int = 50,
        window_days: int = 30,
    ) -> list[SkillInvocation]:
        body = await self._client.request_json(
            "GET",
            f"/api/skills/{name}/invocations",
            params={"limit": limit, "window_days": window_days},
        )
        return [SkillInvocation.model_validate(it) for it in (body or {}).get("items", [])]

    async def install(
        self, payload: SkillInstallInput | dict[str, Any]
    ) -> SkillDetail:
        body = await self._client.request_json(
            "POST", "/api/skills", json_body=_coerce_payload(payload)
        )
        return SkillDetail.model_validate(body)

    async def update(
        self, name: str, payload: SkillInstallInput | dict[str, Any]
    ) -> SkillDetail:
        body = await self._client.request_json(
            "PATCH", f"/api/skills/{name}", json_body=_coerce_payload(payload)
        )
        return SkillDetail.model_validate(body)

    async def delete(self, name: str) -> None:
        await self._client.request_json("DELETE", f"/api/skills/{name}")

    async def disable(self, name: str) -> SkillSummary:
        body = await self._client.request_json("POST", f"/api/skills/{name}:disable")
        return SkillSummary.model_validate(body)

    async def enable(self, name: str) -> SkillSummary:
        body = await self._client.request_json("POST", f"/api/skills/{name}:enable")
        return SkillSummary.model_validate(body)

    async def reload(self, name: str) -> SkillReloadResponse:
        body = await self._client.request_json("POST", f"/api/skills/{name}:reload")
        return SkillReloadResponse.model_validate(body)

    async def dry_run(
        self,
        name: str,
        script: str,
        args: dict[str, Any] | None = None,
    ) -> SkillDryRunResponse:
        body = await self._client.request_json(
            "POST",
            f"/api/skills/{name}/scripts/{script}:dry_run",
            json_body=args or {},
        )
        return SkillDryRunResponse.model_validate(body)


class SkillsAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(
        self,
        *,
        include_disabled: bool = True,
        domain: str | None = None,
    ) -> list[SkillSummary]:
        params: dict[str, Any] = {"include_disabled": include_disabled}
        if domain:
            params["domain"] = domain
        body = self._client.request_json("GET", "/api/skills", params=params)
        return [SkillSummary.model_validate(item) for item in (body or {}).get("items", [])]

    def get(self, name: str) -> SkillDetail:
        body = self._client.request_json("GET", f"/api/skills/{name}")
        return SkillDetail.model_validate(body)

    def get_script(self, name: str, script: str) -> SkillScriptSource:
        body = self._client.request_json("GET", f"/api/skills/{name}/scripts/{script}")
        return SkillScriptSource.model_validate(body)

    def invocations(
        self,
        name: str,
        *,
        limit: int = 50,
        window_days: int = 30,
    ) -> list[SkillInvocation]:
        body = self._client.request_json(
            "GET",
            f"/api/skills/{name}/invocations",
            params={"limit": limit, "window_days": window_days},
        )
        return [SkillInvocation.model_validate(it) for it in (body or {}).get("items", [])]

    def install(
        self, payload: SkillInstallInput | dict[str, Any]
    ) -> SkillDetail:
        body = self._client.request_json(
            "POST", "/api/skills", json_body=_coerce_payload(payload)
        )
        return SkillDetail.model_validate(body)

    def update(
        self, name: str, payload: SkillInstallInput | dict[str, Any]
    ) -> SkillDetail:
        body = self._client.request_json(
            "PATCH", f"/api/skills/{name}", json_body=_coerce_payload(payload)
        )
        return SkillDetail.model_validate(body)

    def delete(self, name: str) -> None:
        self._client.request_json("DELETE", f"/api/skills/{name}")

    def disable(self, name: str) -> SkillSummary:
        body = self._client.request_json("POST", f"/api/skills/{name}:disable")
        return SkillSummary.model_validate(body)

    def enable(self, name: str) -> SkillSummary:
        body = self._client.request_json("POST", f"/api/skills/{name}:enable")
        return SkillSummary.model_validate(body)

    def reload(self, name: str) -> SkillReloadResponse:
        body = self._client.request_json("POST", f"/api/skills/{name}:reload")
        return SkillReloadResponse.model_validate(body)

    def dry_run(
        self,
        name: str,
        script: str,
        args: dict[str, Any] | None = None,
    ) -> SkillDryRunResponse:
        body = self._client.request_json(
            "POST",
            f"/api/skills/{name}/scripts/{script}:dry_run",
            json_body=args or {},
        )
        return SkillDryRunResponse.model_validate(body)


__all__ = ["AsyncSkillsAPI", "SkillsAPI"]
