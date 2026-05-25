"""``/api/planner/*`` sub-client (M8.2 — Planner DAG).

Mirrors :mod:`backend.api.routers.planner`. Each compile / validate /
execute call accepts either a typed :class:`PlanDAG` payload or a plain
``dict``; the sync and async facades have identical surface.

Typical workflow:

    plan = await client.planner.compile(query="...")
    result = await client.planner.validate(plan)
    if result.ok:
        task = await client.planner.execute(plan)
        # then stream task events through the existing tasks API
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import (
    ExecutePlanResponse,
    PlanDAG,
    SkillsForCompileResponse,
    ValidatePlanResponse,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


def _coerce_plan(plan: PlanDAG | dict[str, Any]) -> dict[str, Any]:
    if isinstance(plan, dict):
        return plan
    return plan.model_dump(mode="json")


class AsyncPlannerAPI:
    """Async sub-client for ``/api/planner``."""

    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def skills_for_compile(self) -> SkillsForCompileResponse:
        body = await self._client.request_json(
            "GET", "/api/planner/skills_for_compile"
        )
        return SkillsForCompileResponse.model_validate(body or {})

    async def compile(
        self,
        *,
        query: str,
        domain: str = "",
        hints: list[str] | None = None,
        only_skills: list[str] | None = None,
        only_tools: list[str] | None = None,
        max_nodes: int = 30,
    ) -> PlanDAG:
        payload = {
            "query": query,
            "domain": domain,
            "hints": list(hints or []),
            "only_skills": only_skills,
            "only_tools": only_tools,
            "max_nodes": max_nodes,
        }
        body = await self._client.request_json(
            "POST", "/api/planner/compile", json_body=payload
        )
        return PlanDAG.model_validate(body)

    async def validate(
        self,
        plan: PlanDAG | dict[str, Any],
    ) -> ValidatePlanResponse:
        body = await self._client.request_json(
            "POST",
            "/api/planner/validate",
            json_body={"plan": _coerce_plan(plan)},
        )
        return ValidatePlanResponse.model_validate(body)

    async def execute(
        self,
        plan: PlanDAG | dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        dry_run: bool = False,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> ExecutePlanResponse:
        body = await self._client.request_json(
            "POST",
            "/api/planner/execute",
            json_body={
                "plan": _coerce_plan(plan),
                "params": dict(params or {}),
                "dry_run": dry_run,
                "user_id": user_id,
                "session_id": session_id,
            },
        )
        return ExecutePlanResponse.model_validate(body)


class PlannerAPI:
    """Sync sub-client for ``/api/planner``."""

    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def skills_for_compile(self) -> SkillsForCompileResponse:
        body = self._client.request_json("GET", "/api/planner/skills_for_compile")
        return SkillsForCompileResponse.model_validate(body or {})

    def compile(
        self,
        *,
        query: str,
        domain: str = "",
        hints: list[str] | None = None,
        only_skills: list[str] | None = None,
        only_tools: list[str] | None = None,
        max_nodes: int = 30,
    ) -> PlanDAG:
        payload = {
            "query": query,
            "domain": domain,
            "hints": list(hints or []),
            "only_skills": only_skills,
            "only_tools": only_tools,
            "max_nodes": max_nodes,
        }
        body = self._client.request_json(
            "POST", "/api/planner/compile", json_body=payload
        )
        return PlanDAG.model_validate(body)

    def validate(
        self,
        plan: PlanDAG | dict[str, Any],
    ) -> ValidatePlanResponse:
        body = self._client.request_json(
            "POST",
            "/api/planner/validate",
            json_body={"plan": _coerce_plan(plan)},
        )
        return ValidatePlanResponse.model_validate(body)

    def execute(
        self,
        plan: PlanDAG | dict[str, Any],
        *,
        params: dict[str, Any] | None = None,
        dry_run: bool = False,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> ExecutePlanResponse:
        body = self._client.request_json(
            "POST",
            "/api/planner/execute",
            json_body={
                "plan": _coerce_plan(plan),
                "params": dict(params or {}),
                "dry_run": dry_run,
                "user_id": user_id,
                "session_id": session_id,
            },
        )
        return ExecutePlanResponse.model_validate(body)


__all__ = ["AsyncPlannerAPI", "PlannerAPI"]
