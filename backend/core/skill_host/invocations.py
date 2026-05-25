"""Skill invocation history.

Every time the :class:`SkillExecutor` runs a script (real, dry-run, or a
matcher-driven research workflow call), it records a small envelope here.
The history surfaces in two places:

1. ``GET /api/skills/{name}/invocations`` — UI shows the timeline.
2. ``GET /api/skills`` — list view aggregates the same store into
   ``invocation_count_30d`` / ``avg_elapsed_ms`` / ``last_used_at``.

Design notes
------------
* In-memory only by default — bounded ring buffer per skill so the history
  never grows unbounded. Production deployments that need durability will
  ship a SQL backend in a follow-up; the protocol below is the boundary.
* The store is async to keep the protocol future-proof, even though the
  in-memory implementation is synchronous under the hood.
* Invocations are **append-only**. Editing is not a use case — wrong
  history is more useful than missing history when debugging.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

InvocationStatus = Literal["success", "error", "timeout", "dry_run"]


class SkillInvocation(BaseModel):
    """One row in the skill invocation log.

    All durations are milliseconds. ``args_summary`` and ``error`` are
    truncated by the caller to keep the row small.
    """

    model_config = ConfigDict(extra="forbid")

    skill: str
    script: str
    tool_name: str = ""  # ``<skill>__<script>`` once available
    task_id: str = ""
    status: InvocationStatus
    started_at: datetime
    duration_ms: float = 0.0
    args_summary: str = ""
    result_preview: str = ""
    error: str = ""

    def matches(self, since: datetime | None) -> bool:
        if since is None:
            return True
        return self.started_at >= since


@dataclass(frozen=True)
class InvocationStats:
    """Aggregate over a rolling window for one skill."""

    invocation_count_30d: int = 0
    avg_elapsed_ms: float = 0.0
    last_used_at: datetime | None = None
    last_status: InvocationStatus | None = None


class SkillInvocationStore(Protocol):
    """Boundary between the host and any persistence backend.

    Implementations must be safe to call from multiple coroutines.
    """

    async def record(self, inv: SkillInvocation) -> None: ...

    async def list_for(
        self,
        skill: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[SkillInvocation]: ...

    async def stats(self, skill: str, *, window_days: int = 30) -> InvocationStats: ...


class InMemorySkillInvocationStore:
    """Bounded ring buffer keyed by skill name.

    Capacity is per-skill (not global) so a chatty skill cannot evict the
    quieter ones' history. The default keeps the last 200 calls per skill,
    which is well within the "30-day" window we report on for any skill
    that is not being benchmark-spammed.
    """

    def __init__(self, *, max_per_skill: int = 200) -> None:
        self._max = max_per_skill
        self._buckets: dict[str, deque[SkillInvocation]] = {}

    async def record(self, inv: SkillInvocation) -> None:
        bucket = self._buckets.get(inv.skill)
        if bucket is None:
            bucket = deque(maxlen=self._max)
            self._buckets[inv.skill] = bucket
        bucket.append(inv)

    async def list_for(
        self,
        skill: str,
        *,
        limit: int = 50,
        since: datetime | None = None,
    ) -> list[SkillInvocation]:
        bucket = self._buckets.get(skill)
        if not bucket:
            return []
        rows = [inv for inv in bucket if inv.matches(since)]
        rows.sort(key=lambda r: r.started_at, reverse=True)
        return rows[: max(0, limit)]

    async def stats(self, skill: str, *, window_days: int = 30) -> InvocationStats:
        bucket = self._buckets.get(skill)
        if not bucket:
            return InvocationStats()
        cutoff = datetime.now(UTC) - timedelta(days=max(1, window_days))
        windowed = [inv for inv in bucket if inv.started_at >= cutoff]
        if not windowed:
            # Fall back to most-recent so the UI still has *something* to show.
            latest = max(bucket, key=lambda r: r.started_at)
            return InvocationStats(last_used_at=latest.started_at, last_status=latest.status)
        avg = sum(inv.duration_ms for inv in windowed) / float(len(windowed))
        latest = max(windowed, key=lambda r: r.started_at)
        return InvocationStats(
            invocation_count_30d=len(windowed),
            avg_elapsed_ms=avg,
            last_used_at=latest.started_at,
            last_status=latest.status,
        )


# ---------------------------------------------------------------------------
# Helpers used by the executor / admin
# ---------------------------------------------------------------------------


_PREVIEW_MAX = 280


def _short(text: str, *, limit: int = _PREVIEW_MAX) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def make_invocation(
    *,
    skill: str,
    script: str,
    tool_name: str,
    task_id: str,
    status: InvocationStatus,
    started_at: float,
    duration_ms: float,
    args: dict | None = None,
    result_text: str = "",
    error: str = "",
) -> SkillInvocation:
    """Build a :class:`SkillInvocation` with sane defaults + truncation.

    ``started_at`` is a ``time.time()`` float captured at the start of the
    call so callers don't have to import :class:`datetime` themselves.
    """

    started = datetime.fromtimestamp(started_at, tz=UTC)
    args_summary = ""
    if args:
        try:
            args_summary = ", ".join(f"{k}={_short(str(v), limit=40)}" for k, v in args.items())
            args_summary = _short(args_summary)
        except Exception:  # pragma: no cover - defensive
            args_summary = "<unrepr>"
    return SkillInvocation(
        skill=skill,
        script=script,
        tool_name=tool_name,
        task_id=task_id,
        status=status,
        started_at=started,
        duration_ms=duration_ms,
        args_summary=args_summary,
        result_preview=_short(result_text),
        error=_short(error),
    )


def now_seconds() -> float:
    """Indirection so tests can monkeypatch the clock if needed."""
    return time.time()


__all__ = [
    "InMemorySkillInvocationStore",
    "InvocationStats",
    "InvocationStatus",
    "SkillInvocation",
    "SkillInvocationStore",
    "make_invocation",
    "now_seconds",
]
