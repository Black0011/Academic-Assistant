"""``/api/proposals/*`` sub-client (M8.1 — Gated Proposals).

Mirrors :mod:`backend.api.routers.proposals`. State transitions go
through dedicated helpers (``submit`` / ``approve`` / ``reject`` /
``apply`` / ``withdraw``) so callers don't have to remember the
``:action`` URL suffix.

`apply` records ``status="applied"`` + an audit entry. The framework
deliberately does NOT modify files; humans / CI take the diff and
apply it. Same security model the HTTP API uses.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .models import (
    Proposal,
    ProposalListResponse,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


def _qs(params: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in params.items() if v not in (None, "", [])}


def _make_payload(
    *,
    title: str,
    summary: str,
    motivation: str,
    risk_level: str,
    target_paths: list[str] | None,
    diff: str,
    tags: list[str] | None,
    proposer_kind: str,
    proposer_id: str,
    extras: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "title": title,
        "summary": summary,
        "motivation": motivation,
        "risk_level": risk_level,
        "target_paths": list(target_paths or []),
        "diff": diff,
        "tags": list(tags or []),
        "proposer_kind": proposer_kind,
        "proposer_id": proposer_id,
        "extras": dict(extras or {}),
    }


class AsyncProposalsAPI:
    """Async sub-client for ``/api/proposals``."""

    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(
        self,
        *,
        status: str | None = None,
        proposer_id: str | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ProposalListResponse:
        body = await self._client.request_json(
            "GET",
            "/api/proposals",
            params=_qs(
                {
                    "status": status,
                    "proposer_id": proposer_id,
                    "tag": tag,
                    "page": page,
                    "page_size": page_size,
                }
            ),
        )
        return ProposalListResponse.model_validate(body or {})

    async def get(self, proposal_id: str) -> Proposal:
        body = await self._client.request_json("GET", f"/api/proposals/{proposal_id}")
        return Proposal.model_validate(body)

    async def create(
        self,
        *,
        title: str,
        summary: str = "",
        motivation: str = "",
        risk_level: str = "low",
        target_paths: list[str] | None = None,
        diff: str = "",
        tags: list[str] | None = None,
        proposer_kind: str = "human",
        proposer_id: str = "",
        extras: dict[str, Any] | None = None,
    ) -> Proposal:
        payload = _make_payload(
            title=title,
            summary=summary,
            motivation=motivation,
            risk_level=risk_level,
            target_paths=target_paths,
            diff=diff,
            tags=tags,
            proposer_kind=proposer_kind,
            proposer_id=proposer_id,
            extras=extras,
        )
        body = await self._client.request_json(
            "POST", "/api/proposals", json_body=payload
        )
        return Proposal.model_validate(body)

    async def patch(
        self,
        proposal_id: str,
        *,
        update: dict[str, Any],
        notes: str = "",
    ) -> Proposal:
        payload = dict(update)
        if notes:
            payload["notes"] = notes
        body = await self._client.request_json(
            "PATCH", f"/api/proposals/{proposal_id}", json_body=payload
        )
        return Proposal.model_validate(body)

    async def submit(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return await self._transition(proposal_id, "submit", notes)

    async def approve(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return await self._transition(proposal_id, "approve", notes)

    async def reject(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return await self._transition(proposal_id, "reject", notes)

    async def apply(self, proposal_id: str, *, notes: str = "") -> Proposal:
        """Stamp ``status="applied"``. Does NOT modify files (M8.1 contract)."""
        return await self._transition(proposal_id, "apply", notes)

    async def withdraw(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return await self._transition(proposal_id, "withdraw", notes)

    async def delete(self, proposal_id: str) -> None:
        await self._client.request_json("DELETE", f"/api/proposals/{proposal_id}")

    async def _transition(self, proposal_id: str, action: str, notes: str) -> Proposal:
        body = await self._client.request_json(
            "POST",
            f"/api/proposals/{proposal_id}:{action}",
            json_body={"notes": notes} if notes else None,
        )
        return Proposal.model_validate(body)


class ProposalsAPI:
    """Sync sub-client for ``/api/proposals``."""

    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(
        self,
        *,
        status: str | None = None,
        proposer_id: str | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> ProposalListResponse:
        body = self._client.request_json(
            "GET",
            "/api/proposals",
            params=_qs(
                {
                    "status": status,
                    "proposer_id": proposer_id,
                    "tag": tag,
                    "page": page,
                    "page_size": page_size,
                }
            ),
        )
        return ProposalListResponse.model_validate(body or {})

    def get(self, proposal_id: str) -> Proposal:
        body = self._client.request_json("GET", f"/api/proposals/{proposal_id}")
        return Proposal.model_validate(body)

    def create(
        self,
        *,
        title: str,
        summary: str = "",
        motivation: str = "",
        risk_level: str = "low",
        target_paths: list[str] | None = None,
        diff: str = "",
        tags: list[str] | None = None,
        proposer_kind: str = "human",
        proposer_id: str = "",
        extras: dict[str, Any] | None = None,
    ) -> Proposal:
        payload = _make_payload(
            title=title,
            summary=summary,
            motivation=motivation,
            risk_level=risk_level,
            target_paths=target_paths,
            diff=diff,
            tags=tags,
            proposer_kind=proposer_kind,
            proposer_id=proposer_id,
            extras=extras,
        )
        body = self._client.request_json("POST", "/api/proposals", json_body=payload)
        return Proposal.model_validate(body)

    def patch(
        self,
        proposal_id: str,
        *,
        update: dict[str, Any],
        notes: str = "",
    ) -> Proposal:
        payload = dict(update)
        if notes:
            payload["notes"] = notes
        body = self._client.request_json(
            "PATCH", f"/api/proposals/{proposal_id}", json_body=payload
        )
        return Proposal.model_validate(body)

    def submit(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return self._transition(proposal_id, "submit", notes)

    def approve(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return self._transition(proposal_id, "approve", notes)

    def reject(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return self._transition(proposal_id, "reject", notes)

    def apply(self, proposal_id: str, *, notes: str = "") -> Proposal:
        """Stamp ``status="applied"``. Does NOT modify files (M8.1 contract)."""
        return self._transition(proposal_id, "apply", notes)

    def withdraw(self, proposal_id: str, *, notes: str = "") -> Proposal:
        return self._transition(proposal_id, "withdraw", notes)

    def delete(self, proposal_id: str) -> None:
        self._client.request_json("DELETE", f"/api/proposals/{proposal_id}")

    def _transition(self, proposal_id: str, action: str, notes: str) -> Proposal:
        body = self._client.request_json(
            "POST",
            f"/api/proposals/{proposal_id}:{action}",
            json_body={"notes": notes} if notes else None,
        )
        return Proposal.model_validate(body)


__all__ = ["AsyncProposalsAPI", "ProposalsAPI"]
