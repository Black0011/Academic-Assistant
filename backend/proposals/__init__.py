"""Gated proposals subsystem (M8.1).

Add a "门" between change requests (from human or LLM) and the
framework's own code / skills / rules / configs. A `Proposal` carries a
unified diff or a descriptive change, walks a small state machine
(``draft -> pending -> approved -> applied``), and records every
transition in an audit log.

The framework deliberately does **not** auto-apply diffs in this round.
``apply`` only stamps ``status="applied"`` plus an audit entry; humans
or CI take the diff field and apply it. This matches the old design's
ADR-008 spirit: never rewrite the framework without an explicit gate.

See PLAN.md §20.9 (M8.1) for the full DoD.
"""

from .models import (
    CreateProposalInput,
    Proposal,
    ProposalAction,
    ProposalAuditEvent,
    ProposalListResponse,
    ProposalStatus,
    ProposerKind,
    RiskLevel,
    UpdateProposalInput,
    new_proposal_id,
)
from .store import (
    InMemoryProposalStore,
    ProposalStore,
    YamlProposalStore,
)

__all__ = [
    "CreateProposalInput",
    "InMemoryProposalStore",
    "Proposal",
    "ProposalAction",
    "ProposalAuditEvent",
    "ProposalListResponse",
    "ProposalStatus",
    "ProposalStore",
    "ProposerKind",
    "RiskLevel",
    "UpdateProposalInput",
    "YamlProposalStore",
    "new_proposal_id",
]
