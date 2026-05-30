"""Heuristics (L3 Skills) API.

Lets clients manage the learned-strategy layer:

* ``GET    /api/heuristics``              — list / filter by domain
* ``GET    /api/heuristics/match``        — return top-k for a query
* ``POST   /api/heuristics``              — create a new heuristic
* ``GET    /api/heuristics/{id}``         — read one
* ``PATCH  /api/heuristics/{id}``         — edit description / strategy / trigger
* ``DELETE /api/heuristics/{id}``         — remove
* ``POST   /api/heuristics/{id}/freeze``  — freeze (hide from match)
* ``POST   /api/heuristics/{id}/unfreeze``
* ``POST   /api/heuristics/{id}/bump``    — record success / failure
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.core.errors import MemoryNotFound
from backend.memory.base import HeuristicStore, gen_id
from backend.memory.models import (
    Heuristic,
    HeuristicDomain,
    HeuristicVerdict,
    StrategyBlock,
)

router = APIRouter(prefix="/api/heuristics", tags=["heuristics"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateHeuristicInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str = ""
    domain: HeuristicDomain
    trigger_pattern: str = ""
    strategy: StrategyBlock | None = None
    source_query: str = ""
    source_verdict: HeuristicVerdict = "pass"
    source_run_id: str = ""


class UpdateHeuristicInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    description: str | None = None
    domain: HeuristicDomain | None = None
    trigger_pattern: str | None = None
    strategy: StrategyBlock | None = None


class BumpInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["pass", "fail"] = "pass"


class HeuristicListResponse(BaseModel):
    items: list[Heuristic]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_heuristic(state: AppState) -> HeuristicStore:
    if state.memory is None:
        raise HTTPException(status_code=503, detail="memory subsystem not ready")
    return state.memory.heuristic


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=HeuristicListResponse,
    summary="List heuristics (optionally filtered by domain / frozen state)",
)
async def list_heuristics(
    domain: HeuristicDomain | None = Query(None),
    include_frozen: bool = Query(True),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: AppState = Depends(get_app_state),
) -> HeuristicListResponse:
    store = _require_heuristic(state)
    # Store doesn't expose a "list all" method — synthesize by scanning domains.
    items: list[Heuristic] = []
    domains: tuple[HeuristicDomain, ...] = (
        (domain,) if domain else ("research", "writing", "revision", "rebuttal", "survey")
    )
    seen: set[str] = set()
    for d in domains:
        try:
            chunk = await store.list_by_domain(d)
        except NotImplementedError:  # pragma: no cover
            chunk = []
        for h in chunk:
            if h.id in seen:
                continue
            if not include_frozen and h.frozen:
                continue
            items.append(h)
            seen.add(h.id)
    items.sort(key=lambda h: h.updated_at, reverse=True)
    page = items[offset : offset + limit]
    return HeuristicListResponse(items=page, total=len(items))


@router.get(
    "/match",
    response_model=HeuristicListResponse,
    summary="Return top-k heuristics matching a query (same ranker as Planner)",
)
async def match_heuristics(
    q: str = Query(..., min_length=1, alias="query"),
    domain: HeuristicDomain | None = Query(None),
    top_k: int = Query(3, ge=1, le=50),
    state: AppState = Depends(get_app_state),
) -> HeuristicListResponse:
    store = _require_heuristic(state)
    matches = await store.match(q, domain=domain, top_k=top_k)
    return HeuristicListResponse(items=matches, total=len(matches))


@router.post(
    "",
    response_model=Heuristic,
    status_code=201,
    summary="Create a new heuristic",
)
async def create_heuristic(
    body: CreateHeuristicInput,
    state: AppState = Depends(get_app_state),
) -> Heuristic:
    store = _require_heuristic(state)
    skill = Heuristic(
        id=gen_id(),
        name=body.name,
        description=body.description,
        domain=body.domain,
        trigger_pattern=body.trigger_pattern,
        strategy=body.strategy or StrategyBlock(),
        source_query=body.source_query,
        source_verdict=body.source_verdict,
        source_run_id=body.source_run_id,
    )
    await store.add(skill)
    return skill


@router.get(
    "/{heuristic_id}",
    response_model=Heuristic,
    summary="Get one heuristic",
)
async def get_heuristic(
    heuristic_id: str,
    state: AppState = Depends(get_app_state),
) -> Heuristic:
    store = _require_heuristic(state)
    skill = await store.get(heuristic_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="heuristic not found")
    return skill


@router.patch(
    "/{heuristic_id}",
    response_model=Heuristic,
    summary="Partial update (re-writes the whole record so all backends persist it)",
)
async def update_heuristic(
    heuristic_id: str,
    body: UpdateHeuristicInput,
    state: AppState = Depends(get_app_state),
) -> Heuristic:
    store = _require_heuristic(state)
    existing = await store.get(heuristic_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="heuristic not found")
    # Build updates with the in-memory typed values (strategy stays a
    # StrategyBlock so model_copy doesn't downgrade it to a plain dict).
    updates: dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description
    if body.domain is not None:
        updates["domain"] = body.domain
    if body.trigger_pattern is not None:
        updates["trigger_pattern"] = body.trigger_pattern
    if body.strategy is not None:
        updates["strategy"] = body.strategy
    if not updates:
        return existing
    updated = existing.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
    await store.add(updated)  # add() is upsert semantically on every backend
    final = await store.get(heuristic_id)
    return final or updated


@router.delete(
    "/{heuristic_id}",
    status_code=204,
    summary="Delete a heuristic",
)
async def delete_heuristic(
    heuristic_id: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_heuristic(state)
    deleted = await store.delete(heuristic_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="heuristic not found")
    return Response(status_code=204)


@router.post(
    "/{heuristic_id}/freeze",
    response_model=Heuristic,
    summary="Freeze a heuristic (hidden from match, still editable)",
)
async def freeze_heuristic(
    heuristic_id: str,
    state: AppState = Depends(get_app_state),
) -> Heuristic:
    store = _require_heuristic(state)
    try:
        await store.freeze(heuristic_id)
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    final = await store.get(heuristic_id)
    if final is None:
        raise HTTPException(status_code=404, detail="heuristic not found")
    return final


@router.post(
    "/{heuristic_id}/unfreeze",
    response_model=Heuristic,
    summary="Un-freeze a heuristic",
)
async def unfreeze_heuristic(
    heuristic_id: str,
    state: AppState = Depends(get_app_state),
) -> Heuristic:
    store = _require_heuristic(state)
    existing = await store.get(heuristic_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="heuristic not found")
    if existing.frozen:
        updated = existing.model_copy(update={"frozen": False, "updated_at": datetime.now(UTC)})
        await store.add(updated)
        existing = updated
    return existing


@router.post(
    "/{heuristic_id}/bump",
    response_model=Heuristic,
    summary="Increment success / failure counters",
)
async def bump_heuristic(
    heuristic_id: str,
    body: BumpInput,
    state: AppState = Depends(get_app_state),
) -> Heuristic:
    store = _require_heuristic(state)
    try:
        if body.verdict == "pass":
            await store.bump_success(heuristic_id)
        else:
            await store.bump_failure(heuristic_id)
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    final = await store.get(heuristic_id)
    if final is None:
        raise HTTPException(status_code=404, detail="heuristic not found")
    return final


__all__ = ["router"]
