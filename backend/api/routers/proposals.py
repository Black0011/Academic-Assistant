"""Gated-proposal API (M8.1) — `/api/proposals`.

Surface (PLAN.md §20.9 M8.1):

* ``GET    /api/proposals``                    list with optional filters
* ``POST   /api/proposals``                    create draft
* ``GET    /api/proposals/{proposal_id}``      fetch
* ``PATCH  /api/proposals/{proposal_id}``      mutate while in draft / pending
* ``POST   /api/proposals/{proposal_id}:submit``    draft  -> pending
* ``POST   /api/proposals/{proposal_id}:approve``   pending -> approved (admin)
* ``POST   /api/proposals/{proposal_id}:reject``    pending -> rejected (admin)
* ``POST   /api/proposals/{proposal_id}:apply``     approved -> applied (admin)
* ``POST   /api/proposals/{proposal_id}:withdraw``  any open -> withdrawn
* ``DELETE /api/proposals/{proposal_id}``           draft / withdrawn (admin)

Safety model: ``apply`` does **not** rewrite files. It stamps
``status="applied"`` and writes an audit entry. Humans / CI take the
``diff`` field and apply the actual change. This matches old design's
ADR-008 (no auto code modification without an explicit gate).
"""

from __future__ import annotations

from typing import Annotated

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from backend.core.app_state import AppState, get_app_state
from backend.core.auth.dependencies import current_user
from backend.core.auth.models import User
from backend.proposals.models import (
    CreateProposalInput,
    Proposal,
    ProposalAction,
    ProposalListResponse,
    ProposalStatus,
    UpdateProposalInput,
)
from backend.proposals.store import IllegalTransitionError, ProposalStore

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/api/proposals", tags=["proposals"])


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


async def require_admin_or_open_mode(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> User:
    """Admin-gate for review actions (approve / reject / apply / delete).

    In ``auth_disabled`` mode every caller passes; in production we
    insist on the ``admin`` role. ``current_user`` already returns a
    synthetic anonymous user when auth is disabled.
    """
    settings = state.settings
    if settings is not None and settings.auth_disabled:
        return user
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="admin role required")
    return user


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_store(state: AppState) -> ProposalStore:
    store = getattr(state, "proposals", None)
    if store is None:
        raise HTTPException(status_code=503, detail="proposals subsystem not ready")
    return store


def _illegal(exc: IllegalTransitionError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=f"illegal transition: cannot {exc.action!r} from status {exc.current!r}",
    )


def _can_modify_owner(user: User, proposal: Proposal, *, settings_open: bool) -> bool:
    if settings_open:
        return True
    if user.role == "admin":
        return True
    return bool(proposal.proposer_id) and proposal.proposer_id == user.id


# ---------------------------------------------------------------------------
# Action body
# ---------------------------------------------------------------------------


class ActionInput(BaseModel):
    """Optional ``notes`` payload for transition endpoints."""

    model_config = ConfigDict(extra="forbid")

    notes: str = Field("", description="Free-form note recorded in audit log.")


class SynthesizeInput(BaseModel):
    """Body for ``POST /api/proposals:synthesize`` (P9.4).

    Pulls the most recent successful task records and asks the
    EvolverAgent to draft a single heuristic proposal that spans them.
    Manual replacement for the pre-P9 "auto-draft per run" behaviour.
    """

    model_config = ConfigDict(extra="forbid")

    workflow: str | None = Field(
        None, description="Filter cases to a single workflow (e.g. 'revision'). Optional."
    )
    max_cases: int = Field(
        5, ge=1, le=50, description="Maximum number of recent successful runs to consider."
    )
    actor: str = Field("", description="Override actor recorded in the proposal's audit log.")


# ---------------------------------------------------------------------------
# CRUD endpoints
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=ProposalListResponse,
    summary="List proposals with optional filters",
)
async def list_proposals(
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
    status: ProposalStatus | None = Query(None),
    proposer_id: str | None = Query(None),
    tag: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> ProposalListResponse:
    store = _require_store(state)
    items = await store.list_all(status=status, proposer_id=proposer_id, tag=tag)
    total = len(items)
    start = (page - 1) * page_size
    end = start + page_size
    return ProposalListResponse(items=items[start:end], total=total)


@router.post(
    "",
    response_model=Proposal,
    status_code=201,
    summary="Create a new draft proposal",
)
async def create_proposal(
    body: CreateProposalInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> Proposal:
    store = _require_store(state)
    actor = body.proposer_id or user.id
    return await store.create(body, actor=actor)


@router.post(
    ":synthesize",
    response_model=Proposal,
    status_code=201,
    summary="Synthesize a heuristic proposal from recent successful runs (P9.4)",
)
async def synthesize_proposal(
    body: SynthesizeInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
) -> Proposal:
    """Manual replacement for the pre-P9 "auto-draft per successful run" loop.

    Reads up to ``body.max_cases`` most recent ``status == "ok"`` task
    records (optionally filtered by workflow), hands them to the
    :class:`EvolverAgent` and persists the resulting heuristic proposal.

    Returns 404 if the task store has no successful runs matching the
    filter, 503 if the evolver subsystem isn't wired, and 422 if the
    agent produces no proposal (e.g. the LLM declined to synthesize).
    """

    store = _require_store(state)
    task_store = getattr(state, "task_store", None)
    if task_store is None:
        raise HTTPException(status_code=503, detail="task store not ready")
    runner_deps = getattr(state, "runner_deps", None)
    evolver = getattr(runner_deps, "evolver", None) if runner_deps is not None else None
    if evolver is None:
        raise HTTPException(status_code=503, detail="evolver agent not wired")

    records = await task_store.list(status="ok", limit=body.max_cases * 4)
    if body.workflow:
        records = [r for r in records if r.workflow == body.workflow]
    records = records[: body.max_cases]
    if not records:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no successful runs found for synthesis"
                f"{f' (workflow={body.workflow!r})' if body.workflow else ''}"
            ),
        )

    actor = body.actor.strip() or f"synth:{user.id}"
    proposal = await evolver.evolve_from_recent_runs(
        records=records,
        store=store,
        actor=actor,
        scope_label=body.workflow,
    )
    if proposal is None:
        raise HTTPException(
            status_code=422,
            detail="evolver produced no proposal from the supplied cases",
        )
    return proposal


@router.get(
    "/{proposal_id}",
    response_model=Proposal,
    summary="Fetch a single proposal by id",
)
async def get_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> Proposal:
    store = _require_store(state)
    proposal = await store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")
    return proposal


@router.patch(
    "/{proposal_id}",
    response_model=Proposal,
    summary="Mutate fields on a draft / pending proposal",
)
async def patch_proposal(
    proposal_id: str,
    body: UpdateProposalInput,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
) -> Proposal:
    store = _require_store(state)
    current = await store.get(proposal_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")
    settings = state.settings
    settings_open = bool(settings is not None and settings.auth_disabled)
    if current.status not in {"draft", "pending"} and user.role != "admin":
        raise HTTPException(
            status_code=409,
            detail=f"cannot patch a {current.status!r} proposal; only admin can",
        )
    if not _can_modify_owner(user, current, settings_open=settings_open):
        raise HTTPException(status_code=403, detail="only the proposer or an admin can patch")
    try:
        return await store.patch(proposal_id, body, actor=user.id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found") from exc


@router.delete(
    "/{proposal_id}",
    status_code=204,
    summary="Delete a draft / withdrawn proposal (admin only)",
)
async def delete_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
) -> Response:
    store = _require_store(state)
    current = await store.get(proposal_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")
    if current.status not in {"draft", "withdrawn"}:
        raise HTTPException(
            status_code=409,
            detail=f"cannot delete a {current.status!r} proposal; withdraw or revert first",
        )
    await store.delete(proposal_id)
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------


async def _do_transition(
    *,
    state: AppState,
    user: User,
    proposal_id: str,
    action: ProposalAction,
    body: ActionInput | None,
    require_owner: bool = False,
) -> Proposal:
    store = _require_store(state)
    proposal = await store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")
    if require_owner:
        settings = state.settings
        settings_open = bool(settings is not None and settings.auth_disabled)
        if not _can_modify_owner(user, proposal, settings_open=settings_open):
            raise HTTPException(
                status_code=403,
                detail="only the proposer or an admin may perform this action",
            )
    notes = body.notes if body else ""
    try:
        return await store.transition(proposal_id, action, actor=user.id, notes=notes)
    except IllegalTransitionError as exc:
        raise _illegal(exc) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found") from exc


@router.post(
    "/{proposal_id}:submit",
    response_model=Proposal,
    summary="Move a draft proposal into review (proposer)",
)
async def submit_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
    body: ActionInput | None = None,
) -> Proposal:
    return await _do_transition(
        state=state,
        user=user,
        proposal_id=proposal_id,
        action="submit",
        body=body,
        require_owner=True,
    )


@router.post(
    "/{proposal_id}:approve",
    response_model=Proposal,
    summary="Approve a pending proposal (admin)",
)
async def approve_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
    body: ActionInput | None = None,
) -> Proposal:
    return await _do_transition(
        state=state,
        user=user,
        proposal_id=proposal_id,
        action="approve",
        body=body,
    )


@router.post(
    "/{proposal_id}:reject",
    response_model=Proposal,
    summary="Reject a pending proposal (admin)",
)
async def reject_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
    body: ActionInput | None = None,
) -> Proposal:
    return await _do_transition(
        state=state,
        user=user,
        proposal_id=proposal_id,
        action="reject",
        body=body,
    )


@router.post(
    "/{proposal_id}:apply",
    response_model=Proposal,
    summary="Mark an approved proposal as applied (admin) — does not modify files",
)
async def apply_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
    body: ActionInput | None = None,
) -> Proposal:
    """Stamp `status=applied` and append an audit entry.

    The framework deliberately never rewrites files. The recorded
    ``diff`` is the contract; humans or CI apply it. This boundary keeps
    the gate auditable and reversible (see PLAN.md §20.9 M8.1).
    """
    return await _do_transition(
        state=state,
        user=user,
        proposal_id=proposal_id,
        action="apply",
        body=body,
    )


@router.post(
    "/{proposal_id}:withdraw",
    response_model=Proposal,
    summary="Withdraw a proposal (proposer or admin)",
)
async def withdraw_proposal(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(current_user)],
    body: ActionInput | None = None,
) -> Proposal:
    return await _do_transition(
        state=state,
        user=user,
        proposal_id=proposal_id,
        action="withdraw",
        body=body,
        require_owner=True,
    )


# ---------------------------------------------------------------------------
# P8 Phase C2 — apply a bundle proposal to the actual manuscript files.
#
# Distinct from ``:apply`` (which only stamps status). This action:
#
#   1. reads ``proposal.extras["bundle_after"]`` (deterministic payload
#      attached by EvolverAgent at proposal-creation time),
#   2. checks staleness against ``proposal.extras["bundle_before"]``
#      unless ``force=true`` is set,
#   3. resolves the manuscript via either the request body's
#      ``manuscript_id`` or ``proposal.extras["manuscript_id"]``,
#   4. refuses link-mode bundles unless ``risk_level == "low"`` (the
#      framework will not auto-write into a user-managed external
#      directory for non-low-risk changes),
#   5. writes the file via :class:`BundleStorage` (atomic, size-cap
#      enforced, path-safety enforced),
#   6. patches the proposal's ``extras`` with ``applied_to_bundle_at``
#      and an audit note. Does NOT change ``status`` — call ``:apply``
#      separately if/when you want the state machine stamped too.
# ---------------------------------------------------------------------------


class ApplyToBundleInput(BaseModel):
    """Body for ``POST /api/proposals/{id}:apply-to-bundle``."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str | None = Field(
        default=None,
        description=(
            "Optional override; defaults to "
            "``proposal.extras['manuscript_id']`` written by EvolverAgent."
        ),
    )
    force: bool = Field(
        default=False,
        description=(
            "When true, skip the staleness check that compares the "
            "bundle file's current content against the snapshot taken "
            "at proposal-creation time. Use only when you know the "
            "drift is intentional."
        ),
    )
    notes: str = ""


@router.post(
    "/{proposal_id}:apply-to-bundle",
    response_model=Proposal,
    summary="Write a bundle proposal's recorded after-content back to the manuscript file (admin)",
)
async def apply_proposal_to_bundle(
    proposal_id: str,
    state: Annotated[AppState, Depends(get_app_state)],
    user: Annotated[User, Depends(require_admin_or_open_mode)],
    body: ApplyToBundleInput | None = None,
) -> Proposal:
    body = body or ApplyToBundleInput()
    store = _require_store(state)

    proposal = await store.get(proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found")

    extras = proposal.extras or {}
    bundle_target = str(extras.get("bundle_target") or "").strip()
    bundle_after = extras.get("bundle_after")
    if not bundle_target or not isinstance(bundle_after, str):
        raise HTTPException(
            status_code=400,
            detail=(
                "proposal does not carry a bundle change "
                "(missing extras.bundle_target or extras.bundle_after)"
            ),
        )

    bundle_storage = getattr(state, "bundle_storage", None)
    manuscripts = getattr(state, "manuscripts", None)
    if bundle_storage is None or manuscripts is None:
        raise HTTPException(status_code=503, detail="manuscript subsystem not ready")

    manuscript_id = (body.manuscript_id or extras.get("manuscript_id") or "").strip()
    if not manuscript_id:
        raise HTTPException(
            status_code=400,
            detail="manuscript_id required (not in proposal.extras and not in body)",
        )

    manuscript = await manuscripts.get(manuscript_id)
    if manuscript is None:
        raise HTTPException(status_code=404, detail=f"manuscript {manuscript_id!r} not found")

    if manuscript.layout != "bundle":
        raise HTTPException(
            status_code=409,
            detail="manuscript layout must be 'bundle' to apply a bundle proposal",
        )

    # Linked bundles point at user-managed external directories; refuse
    # auto-writes unless the change is explicitly low-risk.
    if manuscript.bundle_link_path and proposal.risk_level != "low":
        raise HTTPException(
            status_code=403,
            detail=(
                "linked bundles only accept apply-to-bundle for "
                "risk_level='low' proposals "
                f"(this proposal: {proposal.risk_level!r})"
            ),
        )

    # Staleness check against the snapshot the EvolverAgent recorded.
    bundle_before_recorded = extras.get("bundle_before")
    if bundle_before_recorded is not None and not body.force:
        try:
            current_text = await bundle_storage.read_text(manuscript, bundle_target)
        except Exception:
            current_text = ""
        if current_text != bundle_before_recorded:
            raise HTTPException(
                status_code=409,
                detail=(
                    "bundle file has changed since the proposal was drafted; "
                    "re-run the workflow or pass force=true to override"
                ),
            )

    try:
        meta = await bundle_storage.write_text(manuscript, bundle_target, bundle_after)
    except Exception as exc:
        log.exception(
            "proposals.apply_to_bundle.write_failed",
            proposal_id=proposal_id,
            manuscript_id=manuscript_id,
            path=bundle_target,
        )
        raise HTTPException(
            status_code=500,
            detail=f"bundle write failed: {type(exc).__name__}: {exc}",
        ) from exc

    new_extras = dict(extras)
    new_extras["applied_to_bundle_at"] = meta.modified_at.isoformat()
    new_extras["applied_to_bundle_by"] = user.id
    new_extras["applied_to_bundle_size"] = meta.size

    note = (
        f"applied to bundle file {bundle_target!r} of manuscript {manuscript_id!r} "
        f"({meta.size} bytes)"
    )
    if body.notes:
        note = f"{note} — {body.notes}"

    try:
        return await store.patch(
            proposal_id,
            UpdateProposalInput(extras=new_extras, notes=note),
            actor=user.id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id!r} not found") from exc


__all__ = ["router"]
