"""Skill management API (M7.2).

Surface area
------------
``GET    /api/skills``                                    list (active + disabled)
``GET    /api/skills/{name}``                             detail (frontmatter + body)
``GET    /api/skills/{name}/scripts/{script}``            lazy-fetch script source
``POST   /api/skills``                                    install (JSON body)
``PATCH  /api/skills/{name}``                             update (replace body + scripts)
``DELETE /api/skills/{name}``                             soft-delete = disable
``POST   /api/skills/{name}:reload``                      hot-reload single skill
``POST   /api/skills/{name}:enable``                      restore from ``_disabled/``
``POST   /api/skills/{name}:disable``                     same as DELETE; idempotent
``GET    /api/skills/{name}/invocations``                 last N runs
``POST   /api/skills/{name}/scripts/{script}:dry_run``    sandboxed dry-run

Progressive disclosure
----------------------
Cursor / Claude Code reads SKILL.md frontmatter eagerly, body lazily,
script source only when invoked. We mirror that here: list returns just
the frontmatter-derived metadata + invocation stats; detail adds the
SKILL.md body but **does not** include script source; the caller pulls
each script body via the dedicated endpoint when (and only when) the UI
actually needs to display or edit it. This keeps the chatty list cheap
and the detail page incremental.

Auth
----
Read endpoints are open. Write endpoints require admin role unless
``settings.auth_disabled`` is true (open mode). The dependency
:func:`require_admin_or_open_mode` is the gate.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import Path as FastAPIPath
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.core.auth import current_user
from backend.core.auth.models import User
from backend.core.skill_host import SkillHost, SkillInvocation, SkillMeta
from backend.core.skill_host.admin import (
    EdgeOp,
    SkillAdmin,
    SkillAdminError,
    SkillInstallInput,
    SkillSnapshot,
    admin_error_to_status,
)

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/skills", tags=["skills"])


# ---------------------------------------------------------------------------
# Auth gate
# ---------------------------------------------------------------------------


async def require_admin_or_open_mode(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Allow writes when the deployment is in open mode (auth disabled).

    Otherwise insist on the ``admin`` role. ``current_user`` already
    returns a synthetic anonymous user when ``auth_disabled`` is true, so
    we look at the settings flag directly to keep the policy explicit.
    """
    settings = state.settings
    if settings is not None and settings.auth_disabled:
        return user
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class SkillScriptDescriptor(BaseModel):
    """Per-script metadata returned in detail responses (no source)."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    requires_network: bool = False
    max_duration_s: int | None = None
    uses_llm: bool = False
    args_schema: dict | None = None
    size_bytes: int = 0


class SkillSummary(BaseModel):
    """Item shape for ``GET /api/skills``.

    Matches the §20.8 M7.2 contract; numbers default to zero so the UI
    never has to guard against ``None``.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    domain: str | None = None
    triggers: list[str] = Field(default_factory=list)
    version: str = "0.0.0"
    enabled: bool
    scripts: list[str] = Field(default_factory=list)
    uses_llm_any: bool = False
    last_used_at: datetime | None = None
    invocation_count_30d: int = 0
    avg_elapsed_ms: float = 0.0
    version_hash: str = ""
    loaded_from: str = ""


class SkillListResponse(BaseModel):
    items: list[SkillSummary]
    total: int
    generation: int


class SkillDetail(SkillSummary):
    """Detail adds the SKILL.md body and script descriptors (no source)."""

    body_md: str = ""
    scripts_detail: list[SkillScriptDescriptor] = Field(default_factory=list)


class SkillScriptSource(BaseModel):
    name: str
    source: str
    size_bytes: int


class InvocationListResponse(BaseModel):
    items: list[SkillInvocation]
    total: int
    window_days: int = 30


class ReloadResponse(BaseModel):
    name: str | None = None
    generation: int


class DryRunResponse(BaseModel):
    ok: bool
    returncode: int
    duration_ms: float
    timed_out: bool
    stdout: str
    stderr: str


# ---------------------------------------------------------------------------
# P13.B — skill DAG graph
#
# Skills declare relations to each other via the ``compatibility`` block
# in their SKILL.md frontmatter::
#
#     compatibility:
#       upstream:   paper-writing
#       downstream: rebuttal-writer
#
# Both sides may be either a string or a list of strings. The graph
# endpoint normalises that into an explicit ``nodes + edges`` shape so
# the frontend can render a DAG view without re-parsing frontmatter.
#
# ``declared_by`` records whether an edge was declared on the source
# (``downstream:``) side, the target (``upstream:``) side, or both —
# the UI surfaces "asymmetric" declarations (only one side knows the
# relation) as a soft warning so users can keep their SKILL.md files
# in sync.
# ---------------------------------------------------------------------------


class SkillGraphNode(BaseModel):
    """One vertex in the skill DAG."""

    model_config = ConfigDict(extra="forbid")

    name: str
    domain: str | None = None
    version: str = "0.0.0"
    enabled: bool = True
    description: str = ""


class SkillGraphEdge(BaseModel):
    """One directed edge ``source -> target``.

    Semantically: ``target`` consumes (or follows) ``source``. This
    matches the human reading of the frontmatter — "downstream of me"
    means "edge from me to them".
    """

    model_config = ConfigDict(extra="forbid")

    source: str
    target: str
    declared_by: Literal["source", "target", "both"]


class SkillGraphResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nodes: list[SkillGraphNode] = Field(default_factory=list)
    edges: list[SkillGraphEdge] = Field(default_factory=list)
    # Names referenced under compatibility.{upstream,downstream} that
    # don't correspond to any installed skill. UI renders them as hollow
    # placeholder nodes so the relation is visible without pretending
    # the target exists.
    dangling: list[str] = Field(default_factory=list)
    # Each entry is one strongly-connected component (cycle) with > 1
    # node, or a single node with a self-loop. We do NOT refuse to
    # return — the UI renders cycles in amber so the user can see &
    # fix them.
    cycles: list[list[str]] = Field(default_factory=list)
    generation: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_host(state: AppState) -> SkillHost:
    if state.skill_host is None:
        raise HTTPException(status_code=503, detail="skill host not ready")
    return state.skill_host


def _require_admin_layer(state: AppState) -> SkillAdmin:
    if state.skill_admin is None:
        raise HTTPException(status_code=503, detail="skill admin not ready")
    return state.skill_admin


def _raise_admin_error(err: SkillAdminError) -> None:
    code, detail = admin_error_to_status(err)
    raise HTTPException(status_code=code, detail=detail)


async def _summary_for(
    meta: SkillMeta,
    *,
    enabled: bool,
    host: SkillHost,
    admin: SkillAdmin,
) -> SkillSummary:
    stats = await host.invocation_stats(meta.name)
    return SkillSummary(
        name=meta.name,
        description=meta.description,
        domain=meta.domain,
        triggers=meta.triggers,
        version=meta.version,
        enabled=enabled,
        scripts=[s.name for s in meta.scripts],
        uses_llm_any=any(s.uses_llm for s in meta.scripts),
        last_used_at=stats.last_used_at,
        invocation_count_30d=stats.invocation_count_30d,
        avg_elapsed_ms=stats.avg_elapsed_ms,
        version_hash=admin.version_hash(meta.name),
        loaded_from=str(meta.path),
    )


def _summary_for_disabled(
    snapshot: SkillSnapshot,
) -> SkillSummary:
    """Light summary for skills parked under ``_disabled/`` (no SkillMeta)."""
    return SkillSummary(
        name=snapshot.name,
        enabled=False,
        scripts=[s.stem for s in snapshot.scripts],
        version_hash=snapshot.version_hash,
        loaded_from=str(snapshot.loaded_from),
    )


# ---------------------------------------------------------------------------
# Read endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=SkillListResponse,
    summary="List installed skills (active + disabled) with invocation stats",
)
async def list_skills(
    include_disabled: bool = Query(True),
    domain: str | None = Query(None),
    state: AppState = Depends(get_app_state),
) -> SkillListResponse:
    host = _require_host(state)
    admin = _require_admin_layer(state)

    items: list[SkillSummary] = []
    for meta in host.list_skills():
        if domain and meta.domain != domain:
            continue
        items.append(await _summary_for(meta, enabled=True, host=host, admin=admin))
    if include_disabled:
        for name in admin.list_disabled():
            snapshot = admin.snapshot(name)
            if snapshot is not None:
                items.append(_summary_for_disabled(snapshot))
    items.sort(key=lambda s: s.name)
    return SkillListResponse(items=items, total=len(items), generation=host.generation)


# ---------------------------------------------------------------------------
# Graph endpoint
#
# IMPORTANT: this MUST be declared *before* ``GET /{name}`` because
# FastAPI dispatches in declaration order — otherwise ``/graph`` would
# match the ``{name}`` route and 404 "skill 'graph' not found".
# ---------------------------------------------------------------------------


def _as_name_list(v: Any) -> list[str]:
    """Coerce ``compatibility.upstream`` / ``.downstream`` to a list[str].

    Accepts a single string ("paper-writing") or a list of strings — both
    forms appear in the wild SKILL.md files.
    """
    if v is None:
        return []
    if isinstance(v, str):
        s = v.strip()
        return [s] if s else []
    if isinstance(v, list):
        out: list[str] = []
        for item in v:
            s = str(item).strip()
            if s:
                out.append(s)
        return out
    return []


def _find_cycles(adj: dict[str, list[str]]) -> list[list[str]]:
    """Tarjan's strongly-connected components, returning only non-trivial SCCs.

    A "non-trivial" SCC is either:
      * a set of > 1 nodes (genuine cycle), or
      * a single node with a self-loop.

    Tarjan is iterative-friendly but the recursive form is clearer and
    safe for the typical skill-graph size (< 100 nodes). If we ever
    grow to 10k nodes the explicit-stack variant is a drop-in.
    """
    index = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    components: list[list[str]] = []

    def _strongconnect(v: str) -> None:
        indices[v] = index[0]
        lowlinks[v] = index[0]
        index[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, []):
            if w not in indices:
                _strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])
        if lowlinks[v] == indices[v]:
            comp: list[str] = []
            while True:
                w = stack.pop()
                on_stack.discard(w)
                comp.append(w)
                if w == v:
                    break
            if len(comp) > 1:
                components.append(sorted(comp))
            elif comp and comp[0] in adj.get(comp[0], []):
                components.append(comp)

    for v in list(adj.keys()):
        if v not in indices:
            _strongconnect(v)
    return components


def _build_graph(
    metas: list[SkillMeta],
    disabled: list[SkillSnapshot],
) -> SkillGraphResponse:
    """Pure function. Easier to unit-test in isolation than via TestClient."""
    nodes_by_name: dict[str, SkillGraphNode] = {}
    for m in metas:
        nodes_by_name[m.name] = SkillGraphNode(
            name=m.name,
            domain=m.domain,
            version=m.version,
            enabled=True,
            description=m.description,
        )
    for snap in disabled:
        # An installed-then-disabled skill keeps its place in the graph
        # so users can still see / restore its relations. ``SkillSnapshot``
        # only carries ``version_hash`` (not semver), so the displayed
        # ``version`` falls back to the model default — the UI shows the
        # disabled state via the ``enabled`` field anyway.
        if snap.name in nodes_by_name:
            continue
        nodes_by_name[snap.name] = SkillGraphNode(
            name=snap.name,
            enabled=False,
        )

    # Edge side-tracking. Key = (source, target); value = which side
    # declared the relation.
    edge_sides: dict[tuple[str, str], set[str]] = {}
    referenced: set[str] = set()

    for m in metas:
        compat_raw = m.raw_meta.get("compatibility")
        if isinstance(compat_raw, dict):
            for ds in _as_name_list(compat_raw.get("downstream")):
                if ds == m.name:
                    continue  # self-loops via downstream are user error; skip silently
                referenced.add(ds)
                edge_sides.setdefault((m.name, ds), set()).add("source")
            for us in _as_name_list(compat_raw.get("upstream")):
                if us == m.name:
                    continue
                referenced.add(us)
                edge_sides.setdefault((us, m.name), set()).add("target")

        # Also parse top-level ``downstream_skills`` (common in research-writing
        # skills that declare the field outside ``compatibility``).  This must
        # live outside the ``compatibility`` guard so skills that only have
        # ``downstream_skills`` (no ``compatibility`` dict) are still picked up.
        for ds in _as_name_list(m.raw_meta.get("downstream_skills")):
            if ds == m.name:
                continue
            referenced.add(ds)
            edge_sides.setdefault((m.name, ds), set()).add("source")

    edges: list[SkillGraphEdge] = []
    for (src, tgt), sides in edge_sides.items():
        declared_by: Literal["source", "target", "both"]
        if sides == {"source", "target"}:
            declared_by = "both"
        elif "source" in sides:
            declared_by = "source"
        else:
            declared_by = "target"
        edges.append(SkillGraphEdge(source=src, target=tgt, declared_by=declared_by))

    dangling = sorted(name for name in referenced if name not in nodes_by_name)

    # Cycle detection runs on the edge graph (only known nodes).
    adj: dict[str, list[str]] = {}
    for e in edges:
        if e.source in nodes_by_name and e.target in nodes_by_name:
            adj.setdefault(e.source, []).append(e.target)
    cycles = _find_cycles(adj)

    return SkillGraphResponse(
        nodes=sorted(nodes_by_name.values(), key=lambda n: n.name),
        edges=sorted(edges, key=lambda e: (e.source, e.target)),
        dangling=dangling,
        cycles=cycles,
    )


@router.get(
    "/graph",
    response_model=SkillGraphResponse,
    summary="Return the skill DAG (nodes + compatibility edges) for the visual editor",
)
async def get_skill_graph(
    state: AppState = Depends(get_app_state),
) -> SkillGraphResponse:
    host = _require_host(state)
    admin = _require_admin_layer(state)

    disabled_snaps: list[SkillSnapshot] = []
    for name in admin.list_disabled():
        snap = admin.snapshot(name)
        if snap is not None:
            disabled_snaps.append(snap)

    graph = _build_graph(host.list_skills(), disabled_snaps)
    graph.generation = host.generation
    return graph


@router.get(
    "/{name}",
    response_model=SkillDetail,
    summary="Get a single skill (SKILL.md body + script descriptors, no script source)",
)
async def get_skill(
    name: Annotated[str, FastAPIPath(min_length=1)],
    state: AppState = Depends(get_app_state),
) -> SkillDetail:
    host = _require_host(state)
    admin = _require_admin_layer(state)

    meta = host.get_skill(name)
    if meta is None:
        snapshot = admin.snapshot(name)
        if snapshot is None:
            raise HTTPException(status_code=404, detail=f"skill {name!r} not found")
        # disabled skill — return what we can
        return SkillDetail(
            name=name,
            enabled=False,
            scripts=[s.stem for s in snapshot.scripts],
            version_hash=snapshot.version_hash,
            loaded_from=str(snapshot.loaded_from),
            body_md=snapshot.body_md,
            scripts_detail=[
                SkillScriptDescriptor(name=s.stem, size_bytes=s.stat().st_size)
                for s in snapshot.scripts
                if s.is_file()
            ],
        )

    summary = await _summary_for(meta, enabled=True, host=host, admin=admin)
    body = (meta.path / "SKILL.md").read_text(encoding="utf-8")
    scripts_detail = [
        SkillScriptDescriptor(
            name=s.name,
            description=s.description,
            requires_network=s.requires_network,
            max_duration_s=s.max_duration_s,
            uses_llm=s.uses_llm,
            args_schema=s.args_schema,
            size_bytes=s.path.stat().st_size if s.path.is_file() else 0,
        )
        for s in meta.scripts
    ]
    return SkillDetail(
        **summary.model_dump(),
        body_md=body,
        scripts_detail=scripts_detail,
    )


@router.get(
    "/{name}/scripts/{script}",
    response_model=SkillScriptSource,
    summary="Fetch a single script's source on demand (progressive disclosure)",
)
async def get_skill_script(
    name: Annotated[str, FastAPIPath(min_length=1)],
    script: Annotated[str, FastAPIPath(min_length=1)],
    state: AppState = Depends(get_app_state),
) -> SkillScriptSource:
    host = _require_host(state)
    admin = _require_admin_layer(state)
    meta = host.get_skill(name)
    if meta is not None:
        chosen = next((s for s in meta.scripts if s.name == script), None)
        if chosen is None:
            raise HTTPException(status_code=404, detail=f"script {script!r} not in skill {name!r}")
        text = chosen.path.read_text(encoding="utf-8")
        return SkillScriptSource(name=script, source=text, size_bytes=len(text))
    # disabled skill — read directly from snapshot
    snapshot = admin.snapshot(name)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"skill {name!r} not found")
    chosen_path = next((p for p in snapshot.scripts if p.stem == script), None)
    if chosen_path is None:
        raise HTTPException(status_code=404, detail=f"script {script!r} not in skill {name!r}")
    text = chosen_path.read_text(encoding="utf-8")
    return SkillScriptSource(name=script, source=text, size_bytes=len(text))


@router.get(
    "/{name}/invocations",
    response_model=InvocationListResponse,
    summary="Recent invocations of a skill (last N within window_days)",
)
async def list_skill_invocations(
    name: Annotated[str, FastAPIPath(min_length=1)],
    limit: int = Query(50, ge=1, le=500),
    window_days: int = Query(30, ge=1, le=365),
    state: AppState = Depends(get_app_state),
) -> InvocationListResponse:
    host = _require_host(state)
    since = datetime.now(UTC) - timedelta(days=window_days)
    rows = await host.list_invocations(name, limit=limit, since=since)
    return InvocationListResponse(items=rows, total=len(rows), window_days=window_days)


# ---------------------------------------------------------------------------
# Mutating endpoints (admin-only when auth is enabled)
# ---------------------------------------------------------------------------


@router.post(
    "",
    response_model=SkillDetail,
    status_code=201,
    summary="Install a new skill (staging dir → atomic mv → reload)",
)
async def install_skill(
    body: SkillInstallInput,
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> SkillDetail:
    admin = _require_admin_layer(state)
    try:
        await admin.install(body)
    except SkillAdminError as exc:
        _raise_admin_error(exc)
    return await get_skill(body.name, state=state)


@router.patch(
    "/{name}",
    response_model=SkillDetail,
    summary="Update an installed skill (replace body + scripts)",
)
async def update_skill(
    name: Annotated[str, FastAPIPath(min_length=1)],
    body: SkillInstallInput,
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> SkillDetail:
    admin = _require_admin_layer(state)
    try:
        await admin.update(name, body)
    except SkillAdminError as exc:
        _raise_admin_error(exc)
    return await get_skill(name, state=state)


@router.delete(
    "/{name}",
    status_code=204,
    summary="Soft-delete: disable the skill (movable back via :enable)",
)
async def delete_skill(
    name: Annotated[str, FastAPIPath(min_length=1)],
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> Response:
    admin = _require_admin_layer(state)
    try:
        await admin.disable(name)
    except SkillAdminError as exc:
        _raise_admin_error(exc)
    return Response(status_code=204)


@router.post(
    "/{name}:disable",
    response_model=SkillSummary,
    summary="Idempotent disable (alias for DELETE that returns the snapshot)",
)
async def disable_skill(
    name: Annotated[str, FastAPIPath(min_length=1)],
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> SkillSummary:
    admin = _require_admin_layer(state)
    try:
        snap = await admin.disable(name)
    except SkillAdminError as exc:
        _raise_admin_error(exc)
        raise  # unreachable, satisfies mypy
    return _summary_for_disabled(snap)


@router.post(
    "/{name}:enable",
    response_model=SkillSummary,
    summary="Restore a disabled skill from ``_disabled/``",
)
async def enable_skill(
    name: Annotated[str, FastAPIPath(min_length=1)],
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> SkillSummary:
    admin = _require_admin_layer(state)
    try:
        await admin.enable(name)
    except SkillAdminError as exc:
        _raise_admin_error(exc)
    host = _require_host(state)
    meta = host.get_skill(name)
    if meta is None:  # pragma: no cover - just enabled
        raise HTTPException(status_code=500, detail="enable succeeded but skill not visible")
    return await _summary_for(meta, enabled=True, host=host, admin=admin)


@router.post(
    "/{name}:reload",
    response_model=ReloadResponse,
    summary="Force a single-skill reload (filesystem-driven hot-reload)",
)
async def reload_skill(
    name: Annotated[str, FastAPIPath(min_length=1)],
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> ReloadResponse:
    admin = _require_admin_layer(state)
    gen = await admin.reload(name)
    return ReloadResponse(name=name, generation=gen)


# ---------------------------------------------------------------------------
# P14.C — :edges (graph view's drag-to-connect / right-click-delete path)
#
# Why a dedicated endpoint instead of overloading PATCH /api/skills/{name}?
# -----------------------------------------------------------------------
# PATCH replaces the entire SKILL.md body + scripts payload. Using it for
# "wire two nodes together" would require the frontend to:
#   1. fetch the whole body,
#   2. surgically rewrite frontmatter in JS (parser drift risk),
#   3. roundtrip every script.
# That's a 5x blast radius for a 2-line YAML edit. The :edges path stays
# scoped — backend owns the YAML surgery; frontend just declares intent.
# ---------------------------------------------------------------------------


class EdgeOpInput(BaseModel):
    """One edge mutation declaration in :class:`EdgesUpdateInput`.

    ``kind="downstream"`` ⇒ append to ``source.compatibility.downstream``;
    ``kind="upstream"``   ⇒ append to ``source.compatibility.upstream``.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["downstream", "upstream"] = "downstream"
    target: str = Field(..., min_length=1, max_length=64)


class EdgesUpdateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    add: list[EdgeOpInput] = Field(default_factory=list)
    remove: list[EdgeOpInput] = Field(default_factory=list)


class EdgesUpdateResponse(BaseModel):
    """What the UI gets back. ``warnings`` is the place where the
    backend tells the user about lossy operations (e.g. lost frontmatter
    comments) so the toast layer can surface them once."""

    name: str
    body_md: str
    added: list[tuple[str, str]] = Field(default_factory=list)
    removed: list[tuple[str, str]] = Field(default_factory=list)
    skipped_dup: list[tuple[str, str]] = Field(default_factory=list)
    skipped_missing: list[tuple[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@router.post(
    "/{name}:edges",
    response_model=EdgesUpdateResponse,
    summary=(
        "Add / remove ``compatibility.{up,down}stream`` edges in this skill's "
        "frontmatter. Body and scripts are not touched. Used by the graph view."
    ),
)
async def update_skill_edges(
    name: Annotated[str, FastAPIPath(min_length=1)],
    body: EdgesUpdateInput,
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
) -> EdgesUpdateResponse:
    if not body.add and not body.remove:
        raise HTTPException(
            status_code=400,
            detail="At least one of ``add`` / ``remove`` must be non-empty",
        )
    admin = _require_admin_layer(state)
    try:
        snap, report = await admin.update_edges(
            name,
            add=[EdgeOp(kind=op.kind, target=op.target) for op in body.add],
            remove=[EdgeOp(kind=op.kind, target=op.target) for op in body.remove],
        )
    except SkillAdminError as exc:
        _raise_admin_error(exc)
        raise  # unreachable
    return EdgesUpdateResponse(
        name=snap.name,
        body_md=snap.body_md,
        added=report.added,
        removed=report.removed,
        skipped_dup=report.skipped_dup,
        skipped_missing=report.skipped_missing,
        warnings=report.warnings,
    )


@router.post(
    "/{name}/scripts/{script}:dry_run",
    response_model=DryRunResponse,
    summary="Run a script with a tight timeout and a sandboxed env (admin only)",
)
async def dry_run_skill_script(
    name: Annotated[str, FastAPIPath(min_length=1)],
    script: Annotated[str, FastAPIPath(min_length=1)],
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[User, Depends(require_admin_or_open_mode)],
    args: dict | None = None,
) -> DryRunResponse:
    admin = _require_admin_layer(state)
    settings = state.settings
    timeout = settings.skill_dry_run_timeout_s if settings is not None else 5
    try:
        result = await admin.dry_run(name, script, args or {}, timeout_s=timeout)
    except SkillAdminError as exc:
        _raise_admin_error(exc)
        raise  # unreachable, satisfies mypy
    return DryRunResponse(**result)


__all__ = ["router"]
