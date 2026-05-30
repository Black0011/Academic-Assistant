"""ProposalStore — protocol + in-memory + YAML implementations.

The store owns the state machine. Routers compose store calls:

* ``create``       (force draft, append ``create`` audit)
* ``patch``        (mutate fields, append ``update`` audit)
* ``transition``   (atomically check old status, set new status, set
                    ``decided_at`` / ``applied_at`` / ``reviewer_id`` as
                    appropriate, append matching audit event)
* ``list_all`` / ``get`` / ``delete``

State-machine table — *anything else returns ``IllegalTransitionError``*:

    draft     -> pending   (submit, by proposer)
    draft     -> withdrawn (withdraw, by proposer)
    pending   -> approved  (approve, by admin)
    pending   -> rejected  (reject, by admin)
    pending   -> withdrawn (withdraw, by proposer)
    approved  -> applied   (apply, by admin)
    approved  -> withdrawn (withdraw, by proposer)

The YAML implementation persists one ``<proposal_id>.yaml`` file per
record under ``<root>/`` with a tmp-then-rename atomic write so a crash
mid-flush cannot leave half-written YAML on disk.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import structlog
import yaml

from .models import (
    CreateProposalInput,
    Proposal,
    ProposalAction,
    ProposalAuditEvent,
    ProposalStatus,
    UpdateProposalInput,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IllegalTransitionError(RuntimeError):
    """Raised on a forbidden status transition. Routers translate to 409."""

    def __init__(self, *, current: ProposalStatus, action: ProposalAction) -> None:
        super().__init__(f"cannot {action!r} a {current!r} proposal")
        self.current = current
        self.action = action


# Map (status, action) -> next status. Anything missing is illegal.
_TRANSITIONS: dict[tuple[ProposalStatus, ProposalAction], ProposalStatus] = {
    ("draft", "submit"): "pending",
    ("draft", "withdraw"): "withdrawn",
    ("pending", "approve"): "approved",
    ("pending", "reject"): "rejected",
    ("pending", "withdraw"): "withdrawn",
    ("approved", "apply"): "applied",
    ("approved", "withdraw"): "withdrawn",
}


def _next_status(current: ProposalStatus, action: ProposalAction) -> ProposalStatus:
    nxt = _TRANSITIONS.get((current, action))
    if nxt is None:
        raise IllegalTransitionError(current=current, action=action)
    return nxt


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProposalStore(Protocol):
    """Async interface used by the FastAPI router and the SDK tests.

    All methods are coroutine functions so SQL / Redis backends can drop
    in without changing call sites.
    """

    async def create(
        self,
        body: CreateProposalInput,
        *,
        actor: str = "",
    ) -> Proposal: ...

    async def get(self, proposal_id: str) -> Proposal | None: ...

    async def list_all(
        self,
        *,
        status: ProposalStatus | None = None,
        proposer_id: str | None = None,
        tag: str | None = None,
    ) -> list[Proposal]: ...

    async def patch(
        self,
        proposal_id: str,
        body: UpdateProposalInput,
        *,
        actor: str = "",
    ) -> Proposal: ...

    async def transition(
        self,
        proposal_id: str,
        action: ProposalAction,
        *,
        actor: str = "",
        notes: str = "",
    ) -> Proposal: ...

    async def delete(self, proposal_id: str) -> bool: ...

    async def close(self) -> None: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _audit(
    *,
    actor: str,
    action: ProposalAction,
    notes: str = "",
    metadata: dict[str, Any] | None = None,
) -> ProposalAuditEvent:
    return ProposalAuditEvent(
        timestamp=datetime.now(UTC),
        actor=actor,
        action=action,
        notes=notes,
        metadata=metadata or {},
    )


def _apply_patch(p: Proposal, body: UpdateProposalInput) -> Proposal:
    update: dict[str, Any] = {}
    if body.title is not None:
        update["title"] = body.title
    if body.summary is not None:
        update["summary"] = body.summary
    if body.motivation is not None:
        update["motivation"] = body.motivation
    if body.risk_level is not None:
        update["risk_level"] = body.risk_level
    if body.target_paths is not None:
        update["target_paths"] = list(body.target_paths)
    if body.diff is not None:
        update["diff"] = body.diff
    if body.tags is not None:
        update["tags"] = list(body.tags)
    if body.extras is not None:
        update["extras"] = dict(body.extras)
    update["updated_at"] = datetime.now(UTC)
    return p.model_copy(update=update)


def _stamp_transition(
    p: Proposal,
    action: ProposalAction,
    nxt: ProposalStatus,
    *,
    actor: str,
) -> Proposal:
    update: dict[str, Any] = {
        "status": nxt,
        "updated_at": datetime.now(UTC),
    }
    if action in {"approve", "reject"}:
        update["reviewer_id"] = actor or p.reviewer_id
        update["decided_at"] = update["updated_at"]
    if action == "apply":
        update["applied_at"] = update["updated_at"]
    return p.model_copy(update=update)


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


class InMemoryProposalStore:
    """Dict-backed store. Used by tests and zero-config local dev."""

    def __init__(self) -> None:
        self._items: dict[str, Proposal] = {}
        self._lock = asyncio.Lock()

    async def create(
        self,
        body: CreateProposalInput,
        *,
        actor: str = "",
    ) -> Proposal:
        proposer = body.proposer_id or actor
        proposal = Proposal(
            title=body.title,
            summary=body.summary,
            motivation=body.motivation,
            risk_level=body.risk_level,
            target_paths=list(body.target_paths),
            diff=body.diff,
            tags=list(body.tags),
            proposer_kind=body.proposer_kind,
            proposer_id=proposer,
            extras=dict(body.extras),
        )
        proposal = proposal.model_copy(
            update={"audit_log": [_audit(actor=actor or proposer, action="create")]},
        )
        async with self._lock:
            self._items[proposal.proposal_id] = proposal
        return proposal

    async def get(self, proposal_id: str) -> Proposal | None:
        return self._items.get(proposal_id)

    async def list_all(
        self,
        *,
        status: ProposalStatus | None = None,
        proposer_id: str | None = None,
        tag: str | None = None,
    ) -> list[Proposal]:
        items = list(self._items.values())
        if status is not None:
            items = [p for p in items if p.status == status]
        if proposer_id is not None:
            items = [p for p in items if p.proposer_id == proposer_id]
        if tag is not None:
            items = [p for p in items if tag in p.tags]
        items.sort(key=lambda p: p.updated_at, reverse=True)
        return items

    async def patch(
        self,
        proposal_id: str,
        body: UpdateProposalInput,
        *,
        actor: str = "",
    ) -> Proposal:
        async with self._lock:
            current = self._items.get(proposal_id)
            if current is None:
                raise KeyError(proposal_id)
            patched = _apply_patch(current, body)
            event = _audit(actor=actor, action="update", notes=body.notes)
            patched = patched.model_copy(
                update={"audit_log": [*patched.audit_log, event]},
            )
            self._items[proposal_id] = patched
            return patched

    async def transition(
        self,
        proposal_id: str,
        action: ProposalAction,
        *,
        actor: str = "",
        notes: str = "",
    ) -> Proposal:
        async with self._lock:
            current = self._items.get(proposal_id)
            if current is None:
                raise KeyError(proposal_id)
            nxt = _next_status(current.status, action)
            stamped = _stamp_transition(current, action, nxt, actor=actor)
            event = _audit(actor=actor, action=action, notes=notes)
            stamped = stamped.model_copy(
                update={"audit_log": [*stamped.audit_log, event]},
            )
            self._items[proposal_id] = stamped
            return stamped

    async def delete(self, proposal_id: str) -> bool:
        async with self._lock:
            return self._items.pop(proposal_id, None) is not None

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# YAML implementation
# ---------------------------------------------------------------------------


def _atomic_write_yaml(path: Path, payload: dict[str, Any]) -> None:
    """Write ``payload`` to ``path`` via a tmp-then-rename pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class YamlProposalStore:
    """File-per-record YAML store under ``<root>/<proposal_id>.yaml``.

    The directory is created on demand. Reads happen on the event loop's
    default executor via :func:`asyncio.to_thread` so a slow disk doesn't
    block other request handlers.
    """

    def __init__(self, root: Path) -> None:
        self._root = Path(root)
        self._lock = asyncio.Lock()

    async def init(self) -> None:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)

    def _path(self, proposal_id: str) -> Path:
        return self._root / f"{proposal_id}.yaml"

    async def _save(self, proposal: Proposal) -> None:
        await asyncio.to_thread(
            _atomic_write_yaml,
            self._path(proposal.proposal_id),
            proposal.model_dump(mode="json"),
        )

    async def _load(self, proposal_id: str) -> Proposal | None:
        path = self._path(proposal_id)

        def _read() -> Proposal | None:
            if not path.is_file():
                return None
            with path.open("r", encoding="utf-8") as fh:
                payload = yaml.safe_load(fh) or {}
            try:
                return Proposal.model_validate(payload)
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("proposals.yaml.parse_failed", id=proposal_id, err=str(exc))
                return None

        return await asyncio.to_thread(_read)

    async def _load_all(self) -> list[Proposal]:
        def _scan() -> list[Proposal]:
            out: list[Proposal] = []
            if not self._root.is_dir():
                return out
            for path in sorted(self._root.glob("*.yaml")):
                try:
                    with path.open("r", encoding="utf-8") as fh:
                        payload = yaml.safe_load(fh) or {}
                    out.append(Proposal.model_validate(payload))
                except Exception as exc:  # pragma: no cover - defensive
                    log.warning("proposals.yaml.parse_failed", path=str(path), err=str(exc))
            return out

        return await asyncio.to_thread(_scan)

    async def create(
        self,
        body: CreateProposalInput,
        *,
        actor: str = "",
    ) -> Proposal:
        proposer = body.proposer_id or actor
        proposal = Proposal(
            title=body.title,
            summary=body.summary,
            motivation=body.motivation,
            risk_level=body.risk_level,
            target_paths=list(body.target_paths),
            diff=body.diff,
            tags=list(body.tags),
            proposer_kind=body.proposer_kind,
            proposer_id=proposer,
            extras=dict(body.extras),
        )
        proposal = proposal.model_copy(
            update={"audit_log": [_audit(actor=actor or proposer, action="create")]},
        )
        async with self._lock:
            await self._save(proposal)
        return proposal

    async def get(self, proposal_id: str) -> Proposal | None:
        return await self._load(proposal_id)

    async def list_all(
        self,
        *,
        status: ProposalStatus | None = None,
        proposer_id: str | None = None,
        tag: str | None = None,
    ) -> list[Proposal]:
        items = await self._load_all()
        if status is not None:
            items = [p for p in items if p.status == status]
        if proposer_id is not None:
            items = [p for p in items if p.proposer_id == proposer_id]
        if tag is not None:
            items = [p for p in items if tag in p.tags]
        items.sort(key=lambda p: p.updated_at, reverse=True)
        return items

    async def patch(
        self,
        proposal_id: str,
        body: UpdateProposalInput,
        *,
        actor: str = "",
    ) -> Proposal:
        async with self._lock:
            current = await self._load(proposal_id)
            if current is None:
                raise KeyError(proposal_id)
            patched = _apply_patch(current, body)
            event = _audit(actor=actor, action="update", notes=body.notes)
            patched = patched.model_copy(
                update={"audit_log": [*patched.audit_log, event]},
            )
            await self._save(patched)
            return patched

    async def transition(
        self,
        proposal_id: str,
        action: ProposalAction,
        *,
        actor: str = "",
        notes: str = "",
    ) -> Proposal:
        async with self._lock:
            current = await self._load(proposal_id)
            if current is None:
                raise KeyError(proposal_id)
            nxt = _next_status(current.status, action)
            stamped = _stamp_transition(current, action, nxt, actor=actor)
            event = _audit(actor=actor, action=action, notes=notes)
            stamped = stamped.model_copy(
                update={"audit_log": [*stamped.audit_log, event]},
            )
            await self._save(stamped)
            return stamped

    async def delete(self, proposal_id: str) -> bool:
        async with self._lock:
            path = self._path(proposal_id)

            def _unlink() -> bool:
                try:
                    path.unlink()
                    return True
                except FileNotFoundError:
                    return False

            return await asyncio.to_thread(_unlink)

    async def close(self) -> None:
        return None


__all__ = [
    "IllegalTransitionError",
    "InMemoryProposalStore",
    "ProposalStore",
    "YamlProposalStore",
]
