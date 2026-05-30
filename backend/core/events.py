"""Event dataclass shared by workflows, SSE layer, and memory writers.

Events are immutable. Emitters only care about `type` / `data`; the SSE
encoder and persistence layers read `at` for ordering and `task_id` for
routing. Keep the surface tiny — anything fancier belongs in the consumer.

See PLAN §10.2.4 and §23.5 for the canonical type table.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Event:
    """Immutable workflow event.

    `data` is an arbitrary JSON-serialisable dict. Callers are responsible
    for keeping values JSON-safe; the SSE encoder only does a best-effort
    `json.dumps(default=str)`.
    """

    type: str
    task_id: str = ""
    at: datetime = field(default_factory=_utc_now)
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "task_id": self.task_id,
            "at": self.at.isoformat(),
            "data": dict(self.data),
        }


class EventType:
    """Canonical event-type strings. See PLAN §23.5."""

    # Task lifecycle
    TASK_START = "task.start"
    TASK_END = "task.end"
    TASK_ERROR = "task.error"
    # Soft-recoverable degradation. Emitted when a stage fails but the
    # workflow can keep running with a default value (e.g. recall failed
    # → continue with empty memory snapshot). The UI should surface it
    # as an inline notice ("memory unavailable, results lack history")
    # rather than terminate the task.
    TASK_WARNING = "task.warning"
    TASK_PROGRESS = "task.progress"
    TASK_RETRY = "task.retry"
    TASK_STAGE_START = "task.stage_start"
    TASK_STAGE_END = "task.stage_end"
    TASK_CHECKPOINT = "task.checkpoint"
    TASK_AWAITING_INPUT = "task.awaiting_input"

    # Skill / tool
    SKILL_MATCHED = "skill.matched"
    SKILL_CALL = "skill.call"
    SKILL_RESULT = "skill.result"

    # LLM
    LLM_CALL = "llm.call"
    LLM_TOKEN = "llm.token"

    # Rule
    RULE_BLOCK = "rule.block"

    # Memory
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_ROLLBACK = "memory.rollback"


__all__ = ["Event", "EventType"]
