"""Memory inspection + admin endpoints.

Read-only reads (``/snapshot``) live here alongside the administrative
surface the UI needs for managing reflections, sessions, and run
rollbacks. Knowledge cards and heuristics have their own dedicated
routers (:mod:`knowledge`, :mod:`heuristics`).
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.core.errors import MemoryNotFound
from backend.memory.base import MemoryBundle, gen_id
from backend.memory.models import (
    MemorySnapshot,
    Reflection,
    ReflectionType,
    SessionContext,
    SessionMessage,
)

router = APIRouter(prefix="/api/memory", tags=["memory"])


# ---------------------------------------------------------------------------
# Snapshot (one-shot read)
# ---------------------------------------------------------------------------


class SnapshotResponse(BaseModel):
    query: str
    domain: str
    vector_summary: str
    related_papers: list[dict[str, Any]]
    heuristics: list[dict[str, Any]]
    recent_reflections: list[dict[str, Any]]

    @classmethod
    def from_snapshot(cls, snap: MemorySnapshot) -> SnapshotResponse:
        return cls(
            query=snap.query,
            domain=snap.domain,
            vector_summary=snap.vector_summary,
            related_papers=[p.model_dump(mode="json") for p in snap.related_papers],
            heuristics=[h.model_dump(mode="json") for h in snap.heuristics],
            recent_reflections=[r.model_dump(mode="json") for r in snap.recent_reflections],
        )


@router.get("/snapshot", response_model=SnapshotResponse, summary="One-shot memory read")
async def snapshot(
    query: str = Query(..., min_length=1, description="What to recall."),
    domain: str = Query("", description="Optional domain filter for heuristics."),
    k: int = Query(5, ge=1, le=50, description="Top-k per store."),
    session_id: str | None = Query(None),
    state: AppState = Depends(get_app_state),
) -> SnapshotResponse:
    bundle = _require_memory(state)
    snap = await bundle.snapshot(query, domain=domain, k=k, session_id=session_id)
    return SnapshotResponse.from_snapshot(snap)


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


class MemoryStats(BaseModel):
    vector_count: int | None = None
    knowledge_count: int
    synthesis_count: int
    heuristic_count: int
    reflection_count: int | None = None
    session_backend: str
    generated_at_epoch_s: float | None = None


@router.get("/stats", response_model=MemoryStats, summary="High-level memory counts")
async def stats(state: AppState = Depends(get_app_state)) -> MemoryStats:
    bundle = _require_memory(state)

    vector_count: int | None = None
    try:
        vector_count = int(await bundle.vector.count())
    except Exception:
        vector_count = None

    cards = await bundle.knowledge.list_all()
    syntheses = await bundle.knowledge.list_synthesis()

    domains = ("research", "writing", "revision", "rebuttal", "survey")
    seen: set[str] = set()
    for d in domains:
        try:
            chunk = await bundle.heuristic.list_by_domain(d)
        except Exception:
            chunk = []
        for h in chunk:
            seen.add(h.id)

    reflection_count: int | None = None
    counter = getattr(bundle.episodic, "count", None)
    if counter is not None:
        try:
            reflection_count = int(await counter())
        except Exception:
            reflection_count = None

    return MemoryStats(
        vector_count=vector_count,
        knowledge_count=len(cards),
        synthesis_count=len(syntheses),
        heuristic_count=len(seen),
        reflection_count=reflection_count,
        session_backend=type(bundle.session).__name__,
    )


# ---------------------------------------------------------------------------
# Reflections
# ---------------------------------------------------------------------------


class CreateReflectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: ReflectionType = "reflection"
    content: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
    source_run_id: str | None = None


class ReflectionListResponse(BaseModel):
    items: list[Reflection]
    total: int


@router.get(
    "/reflections",
    response_model=ReflectionListResponse,
    summary="List recent reflections (newest first)",
)
async def list_reflections(
    type: ReflectionType | None = Query(None),
    session_id: str | None = Query(None),
    user_id: str | None = Query(None),
    n: int = Query(20, ge=1, le=500),
    state: AppState = Depends(get_app_state),
) -> ReflectionListResponse:
    bundle = _require_memory(state)
    items = await bundle.episodic.recent(n=n, type=type, session_id=session_id, user_id=user_id)
    return ReflectionListResponse(items=items, total=len(items))


@router.post(
    "/reflections",
    response_model=Reflection,
    status_code=201,
    summary="Append a reflection / observation / insight",
)
async def create_reflection(
    body: CreateReflectionInput,
    state: AppState = Depends(get_app_state),
) -> Reflection:
    bundle = _require_memory(state)
    record = Reflection(
        id=gen_id(),
        type=body.type,
        content=body.content,
        tags=list(body.tags),
        user_id=body.user_id,
        session_id=body.session_id,
        source_run_id=body.source_run_id,
    )
    await bundle.episodic.append(record)
    return record


# ---------------------------------------------------------------------------
# P14.A — Reflection PATCH / DELETE / bulk delete
#
# The store stays the source of truth; the router just translates the
# Pydantic payload + 404/204 status mapping. All four endpoints honour the
# in-store contract that ``user_id`` / system-managed fields cannot be
# altered through PATCH.
# ---------------------------------------------------------------------------


class UpdateReflectionInput(BaseModel):
    """Partial update — every field is optional, ``None`` means leave alone.

    We deliberately omit ``user_id`` / ``session_id`` / ``source_run_id``
    from the editable surface: those are provenance markers (who/when/which
    run produced the row) and rewriting them would invalidate
    rollback-by-run and the session timeline view.
    """

    model_config = ConfigDict(extra="forbid")

    type: ReflectionType | None = None
    content: str | None = Field(None, min_length=1, max_length=8000)
    tags: list[str] | None = None


class BulkDeleteResponse(BaseModel):
    deleted: int


@router.patch(
    "/reflections/{reflection_id}",
    response_model=Reflection,
    summary="Edit a reflection (content / type / tags)",
)
async def update_reflection(
    reflection_id: str,
    body: UpdateReflectionInput,
    state: AppState = Depends(get_app_state),
) -> Reflection:
    bundle = _require_memory(state)
    updated = await bundle.episodic.update(
        reflection_id,
        type=body.type,
        content=body.content,
        tags=body.tags,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Reflection not found")
    return updated


@router.delete(
    "/reflections/{reflection_id}",
    status_code=204,
    summary="Delete a single reflection",
)
async def delete_reflection(
    reflection_id: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    bundle = _require_memory(state)
    deleted = await bundle.episodic.delete(reflection_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Reflection not found")
    return Response(status_code=204)


@router.delete(
    "/reflections",
    response_model=BulkDeleteResponse,
    summary="Bulk delete reflections by session_id and/or source_run_id",
)
async def bulk_delete_reflections(
    session_id: str | None = Query(None),
    source_run_id: str | None = Query(None),
    state: AppState = Depends(get_app_state),
) -> BulkDeleteResponse:
    if session_id is None and source_run_id is None:
        # Refuse unbounded delete at the HTTP boundary too — defence in
        # depth for the "fat finger curl with no query string" case.
        raise HTTPException(
            status_code=400,
            detail="At least one of session_id / source_run_id is required",
        )
    bundle = _require_memory(state)
    n = await bundle.episodic.delete_by(
        session_id=session_id, source_run_id=source_run_id
    )
    return BulkDeleteResponse(deleted=n)


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


class CreateSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str | None = None
    user_id: str | None = None
    title: str = ""
    state: dict[str, Any] = Field(default_factory=dict)


class UpdateSessionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    state: dict[str, Any] | None = None


class AppendMessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str = ""
    meta: dict[str, Any] = Field(default_factory=dict)


class SessionListResponse(BaseModel):
    items: list[SessionContext]
    total: int


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List sessions for a given user",
)
async def list_sessions(
    user_id: str = Query(..., min_length=1),
    state: AppState = Depends(get_app_state),
) -> SessionListResponse:
    bundle = _require_memory(state)
    items = await bundle.session.list_for_user(user_id)
    return SessionListResponse(items=items, total=len(items))


@router.post(
    "/sessions",
    response_model=SessionContext,
    status_code=201,
    summary="Create a new session",
)
async def create_session(
    body: CreateSessionInput,
    state: AppState = Depends(get_app_state),
) -> SessionContext:
    bundle = _require_memory(state)
    session = SessionContext(
        session_id=body.session_id or gen_id("sess-"),
        user_id=body.user_id,
        title=body.title,
        state=dict(body.state),
    )
    await bundle.session.create(session)
    return session


@router.get(
    "/sessions/{session_id}",
    response_model=SessionContext,
    summary="Read a session with its full message history",
)
async def get_session(
    session_id: str,
    state: AppState = Depends(get_app_state),
) -> SessionContext:
    bundle = _require_memory(state)
    record = await bundle.session.get(session_id)
    if record is None:
        raise HTTPException(status_code=404, detail="session not found")
    return record


@router.patch(
    "/sessions/{session_id}",
    response_model=SessionContext,
    summary="Update session title / state",
)
async def update_session(
    session_id: str,
    body: UpdateSessionInput,
    state: AppState = Depends(get_app_state),
) -> SessionContext:
    bundle = _require_memory(state)
    updates: dict[str, Any] = {}
    if body.title is not None:
        updates["title"] = body.title
    if body.state is not None:
        updates["state"] = body.state
    try:
        return await bundle.session.update(session_id, **updates)
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post(
    "/sessions/{session_id}/messages",
    status_code=201,
    summary="Append a message to a session",
)
async def append_session_message(
    session_id: str,
    body: AppendMessageInput,
    state: AppState = Depends(get_app_state),
) -> SessionMessage:
    bundle = _require_memory(state)
    message = SessionMessage(role=body.role, content=body.content, meta=dict(body.meta))
    try:
        await bundle.session.append_message(session_id, message)
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return message


@router.delete(
    "/sessions/{session_id}",
    status_code=204,
    summary="Delete a session",
)
async def delete_session(
    session_id: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    bundle = _require_memory(state)
    deleted = await bundle.session.delete(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="session not found")
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# Rollback a workflow run
# ---------------------------------------------------------------------------


class RollbackResponse(BaseModel):
    run_id: str
    knowledge_removed: int
    heuristics_removed: int
    reflections_removed: int


@router.post(
    "/rollback/{run_id}",
    response_model=RollbackResponse,
    summary="Remove every memory write tagged with the given run_id",
)
async def rollback(
    run_id: str,
    state: AppState = Depends(get_app_state),
) -> RollbackResponse:
    bundle = _require_memory(state)

    async def _safe(coro: Any) -> int:
        try:
            return int(await coro)
        except Exception:
            return 0

    knowledge_removed = await _safe(bundle.knowledge.rollback_run(run_id))
    heuristics_removed = await _safe(bundle.heuristic.rollback_run(run_id))
    reflections_removed = await _safe(bundle.episodic.rollback_run(run_id))
    return RollbackResponse(
        run_id=run_id,
        knowledge_removed=knowledge_removed,
        heuristics_removed=heuristics_removed,
        reflections_removed=reflections_removed,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_memory(state: AppState) -> MemoryBundle:
    if state.memory is None:
        raise HTTPException(status_code=503, detail="memory subsystem not ready")
    return state.memory


__all__ = ["router"]
