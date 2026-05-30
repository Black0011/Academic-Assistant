"""Pydantic schemas for the gated-proposal subsystem.

Schema decisions (see PLAN.md §20.9 M8.1):

* ``proposal_id`` is a 12-hex token so it slots into URL paths directly.
* ``status`` is a string Literal so the wire format never drifts from
  the state-machine table in the PLAN.
* ``audit_log`` is append-only: callers never mutate it directly; the
  store layer is the only writer. The list lives on the model so a
  single GET round-trip carries the full history.
* ``diff`` is opaque to the framework — we store and ship it as-is so
  external diff viewers / appliers can consume it.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ProposalStatus = Literal[
    "draft",
    "pending",
    "approved",
    "rejected",
    "applied",
    "withdrawn",
]
RiskLevel = Literal["low", "medium", "high", "tier_d"]
ProposerKind = Literal["human", "llm", "agent"]
ProposalAction = Literal[
    "create",
    "update",
    "submit",
    "approve",
    "reject",
    "apply",
    "withdraw",
    "comment",
]


def new_proposal_id() -> str:
    """12-hex random token. Kept short for URLs; collision-safe at this scale."""
    return secrets.token_hex(6)


class ProposalAuditEvent(BaseModel):
    """One immutable line in a proposal's audit log."""

    model_config = ConfigDict(extra="forbid")

    timestamp: datetime
    actor: str = ""
    action: ProposalAction
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    """A gated change request for the framework's own code or assets."""

    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(default_factory=new_proposal_id)
    title: str
    summary: str = ""
    motivation: str = ""
    risk_level: RiskLevel = "low"
    target_paths: list[str] = Field(default_factory=list)
    diff: str = ""
    status: ProposalStatus = "draft"
    proposer_id: str = ""
    proposer_kind: ProposerKind = "human"
    reviewer_id: str | None = None
    review_notes: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    decided_at: datetime | None = None
    applied_at: datetime | None = None
    audit_log: list[ProposalAuditEvent] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class CreateProposalInput(BaseModel):
    """Body for ``POST /api/proposals``."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    summary: str = ""
    motivation: str = ""
    risk_level: RiskLevel = "low"
    target_paths: list[str] = Field(default_factory=list)
    diff: str = ""
    tags: list[str] = Field(default_factory=list)
    proposer_kind: ProposerKind = "human"
    proposer_id: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class UpdateProposalInput(BaseModel):
    """Body for ``PATCH /api/proposals/{id}``.

    Every field is optional; a field absent from the JSON body leaves the
    stored value untouched. ``notes`` is recorded in the audit log only.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    summary: str | None = None
    motivation: str | None = None
    risk_level: RiskLevel | None = None
    target_paths: list[str] | None = None
    diff: str | None = None
    tags: list[str] | None = None
    extras: dict[str, Any] | None = None
    notes: str = ""


class ProposalListResponse(BaseModel):
    items: list[Proposal]
    total: int


__all__ = [
    "CreateProposalInput",
    "Proposal",
    "ProposalAction",
    "ProposalAuditEvent",
    "ProposalListResponse",
    "ProposalStatus",
    "ProposerKind",
    "RiskLevel",
    "UpdateProposalInput",
    "new_proposal_id",
]
