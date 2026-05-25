"""LLM usage telemetry endpoints (`/api/v1/models/...`).

Reads from the in-process :class:`backend.core.llm.telemetry.TelemetryRecorder`
ring buffer. Exposes:

* ``GET /api/v1/models/usage`` — totals + a per-(provider, model, route)
  breakdown so the Settings page can chart "which route ate the budget".
* ``GET /api/v1/models/routes`` — names of routes the active LLM provider
  knows about (drawn from :class:`backend.core.llm.router.RoutingLLMProvider`
  when present). Useful for the frontend to show route badges.

The data is intentionally non-persistent for M1: the telemetry recorder
is a bounded in-memory ring buffer (default 1000 records). Persistence
moves to Postgres in a later milestone (see PLAN §9.4).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.core.llm.router import RoutingLLMProvider
from backend.core.llm.telemetry import recorder

router = APIRouter(prefix="/api/v1/models", tags=["models"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class UsageBreakdown(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    route: str | None = Field(
        default=None,
        description=(
            "Workflow-declared route name (e.g. 'reasoning' / 'fast'). "
            "`null` means the call ran without an explicit route."
        ),
    )
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float = 0.0
    errors: int = 0


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    totals: dict[str, float]
    breakdown: list[UsageBreakdown]
    sample_size: int = Field(
        description=(
            "Number of records currently held in the in-memory ring "
            "buffer (capped at the recorder's max_records, default 1000)."
        ),
    )


class RoutesResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(description="True iff a RoutingLLMProvider is wired.")
    default_provider: str | None
    routes: list[str] = Field(
        default_factory=list,
        description="Sorted route names declared by the active routing policy.",
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/usage",
    response_model=UsageResponse,
    summary="LLM token / cost usage breakdown",
)
async def usage(
    route: Annotated[
        str | None,
        Query(
            description=(
                "If set, restrict the breakdown to records tagged with this "
                "route name. Use the literal string 'none' to filter for "
                "untagged (default-route) calls only."
            ),
        ),
    ] = None,
) -> UsageResponse:
    rec = recorder()
    totals = rec.totals()
    records = rec.records()

    if route is not None:
        target: str | None = None if route == "none" else route
        records = [r for r in records if r.route == target]

    grouped: dict[tuple[str, str, str | None], dict[str, float]] = defaultdict(
        lambda: {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "errors": 0,
        }
    )
    for r in records:
        key = (r.provider, r.model, r.route)
        bucket = grouped[key]
        bucket["calls"] += 1
        bucket["prompt_tokens"] += r.prompt_tokens
        bucket["completion_tokens"] += r.completion_tokens
        if r.cost_usd is not None:
            bucket["cost_usd"] += r.cost_usd
        if r.error_code is not None:
            bucket["errors"] += 1

    breakdown = [
        UsageBreakdown(
            provider=p,
            model=m,
            route=rt,
            calls=int(b["calls"]),
            prompt_tokens=int(b["prompt_tokens"]),
            completion_tokens=int(b["completion_tokens"]),
            cost_usd=b["cost_usd"],
            errors=int(b["errors"]),
        )
        for (p, m, rt), b in sorted(
            grouped.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2] or "")
        )
    ]

    return UsageResponse(
        totals=totals,
        breakdown=breakdown,
        sample_size=len(records),
    )


@router.get(
    "/routes",
    response_model=RoutesResponse,
    summary="Routes declared by the active routing policy",
)
async def routes(state: Annotated[AppState, Depends(get_app_state)]) -> RoutesResponse:
    llm = state.llm
    if isinstance(llm, RoutingLLMProvider):
        return RoutesResponse(
            enabled=True,
            default_provider=getattr(llm.default_provider, "name", None),
            routes=llm.route_names(),
        )
    return RoutesResponse(
        enabled=False,
        default_provider=getattr(llm, "name", None) if llm else None,
        routes=[],
    )
