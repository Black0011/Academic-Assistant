"""Pause/resume protocol for interactive workflows.

When a workflow needs user input, it calls ``ctx.ask_user()`` which either:
- (first run) raises ``WorkflowAwaitingInput`` with a ``CheckpointSnapshot``,
  caught by the runner to mark the task as ``"waiting"``.
- (resume run) restores ``ctx.state`` from the saved snapshot and returns
  the user's response dict, so the workflow continues transparently.

The runner stores the snapshot in the *parent* task's ``result`` field.
When the user responds via ``POST /api/tasks/{id}/respond``, a *child* task
is created with ``_resume_state`` / ``_resume_checkpoint`` / ``_user_response``
in its ``input``, inheriting the parent's context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CheckpointSnapshot:
    """Serializable snapshot of workflow state at a pause point.

    Stored in the parent task's ``result`` field so the child task can
    restore it on resume.
    """

    state: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    checkpoint: str = ""
    prompt: str = ""
    prompt_data: dict[str, Any] = field(default_factory=dict)
    stage: str = ""


class WorkflowAwaitingInput(Exception):
    """Controlled halt — caught by the runner, not treated as an error.

    The runner stores ``snapshot`` in the task record and sets status to
    ``"waiting"``. The SSE stream stays open so the frontend can render
    the question UI.
    """

    def __init__(self, snapshot: CheckpointSnapshot) -> None:
        super().__init__(
            f"Workflow awaiting user input at checkpoint '{snapshot.checkpoint}'"
        )
        self.snapshot = snapshot


__all__ = ["CheckpointSnapshot", "WorkflowAwaitingInput"]
