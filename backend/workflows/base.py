"""WorkflowContext + BaseWorkflow + WorkflowOutput.

This is the load-bearing wiring of the whole framework: every pipeline
runs by constructing a :class:`WorkflowContext`, passing it to
``workflow.run(ctx)``, and observing events pushed into ``ctx.trace``.

Design notes (see PLAN §10.2):

* ``WorkflowContext`` is a *dataclass*, not a Pydantic model — Pydantic
  would force us to revalidate the entire `state` dict on every mutation,
  and workflows mutate it per stage.
* ``BaseWorkflow.stage()`` is the single place where we enforce budget,
  emit start/end events, checkpoint, and funnel errors into
  ``task.error`` events. Concrete workflows should not bypass it.
* ``checkpoint`` uses an injected ``Checkpointer`` protocol; when no
  checkpointer is wired or ``checkpoint_enabled`` is False, the call is a
  no-op — zero cost in the common case.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, TypeVar, runtime_checkable

from backend.core.budget import Budget
from backend.core.errors import InfrastructureError
from backend.core.events import Event, EventType
from backend.core.pause import CheckpointSnapshot, WorkflowAwaitingInput

T = TypeVar("T")

EventSink = Callable[[Event], Awaitable[None]]


@runtime_checkable
class Checkpointer(Protocol):
    async def save(self, task_id: str, label: str, state: dict[str, Any]) -> None: ...
    async def load(self, task_id: str) -> dict[str, Any] | None: ...


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass
class WorkflowContext:
    """Per-run state. Passed explicitly everywhere — no globals."""

    task_id: str
    query: str = ""
    input: dict[str, Any] = field(default_factory=dict)
    user_id: str | None = None
    session_id: str | None = None

    # Injected dependencies. Typed as `Any` to avoid import cycles and to
    # let tests stub out individual collaborators.
    llm: Any | None = None
    memory: Any | None = None
    skill_host: Any | None = None
    rule_engine: Any | None = None
    tools: Any | None = None

    # P8 — manuscript-bound bundle facade. Only populated when the task's
    # ``input.manuscript_id`` resolves to a bundle-layout manuscript. For
    # single-layout (or no manuscript) tasks this stays ``None`` and the
    # legacy code path runs unchanged. Adapter type kept as ``Any`` for
    # the same import-cycle reason as the other slots above.
    bundle: Any | None = None
    store: Any | None = None  # TaskStore — for writing waiting status

    budget: Budget = field(default_factory=Budget)
    state: dict[str, Any] = field(default_factory=dict)
    trace: list[Event] = field(default_factory=list)

    checkpoint_enabled: bool = False
    _sink: EventSink | None = None
    _checkpointer: Checkpointer | None = None

    # ---- construction helpers ---------------------------------------

    def with_sink(self, sink: EventSink | None) -> WorkflowContext:
        self._sink = sink
        return self

    def with_checkpointer(self, checkpointer: Checkpointer | None) -> WorkflowContext:
        self._checkpointer = checkpointer
        return self

    # ---- emit / checkpoint ------------------------------------------

    async def emit(self, event: Event) -> None:
        """Append to trace and best-effort forward to the sink.

        Sink failures are swallowed with a warning so an SSE hiccup can't
        crash the workflow. Trace is always recorded.
        """
        # Fill in task_id if omitted
        if not event.task_id:
            event = Event(type=event.type, task_id=self.task_id, at=event.at, data=event.data)
        self.trace.append(event)
        if self._sink is None:
            return
        try:
            await self._sink(event)
        except Exception:
            import structlog

            structlog.get_logger(__name__).warning(
                "workflow.sink_failed", type=event.type, task_id=event.task_id
            )

    async def checkpoint(self, label: str) -> None:
        if not self.checkpoint_enabled or self._checkpointer is None:
            return
        await self._checkpointer.save(self.task_id, label, dict(self.state))
        await self.emit(Event(EventType.TASK_CHECKPOINT, data={"label": label}))

    async def ask_user(
        self,
        prompt: str,
        *,
        checkpoint: str = "",
        prompt_data: dict[str, Any] | None = None,
        stage: str = "",
    ) -> dict[str, Any]:
        """Ask the user a question and wait for their response.

        On the first call (no resume marker in ``input``): emits a
        ``TASK_AWAITING_INPUT`` event and raises ``WorkflowAwaitingInput``.
        The runner catches it, stores the snapshot, and marks the task as
        ``"waiting"``.

        On the resume call (``_resume_checkpoint`` in ``input`` matches
        ``checkpoint``): restores ``self.state`` from the saved snapshot
        and returns the user's response dict. The workflow continues
        transparently from the same stage.

        Returns the user's response dict: ``{prompt: str, data: {...}}``.
        """
        resume_checkpoint = self.input.get("_resume_checkpoint", "")
        if resume_checkpoint == checkpoint:
            # Resume path — restore state and return user response
            saved_state = self.input.get("_resume_state", {})
            if saved_state:
                self.state.update(saved_state)
            return self.input.get("_user_response", {})
        # First-run path — emit event and set pause marker on state.
        # We deliberately do NOT raise an exception because exceptions
        # corrupt SQLite/aiosqlite sessions, causing "no active connection"
        # errors on subsequent writes. Instead, we set a flag so the
        # workflow can return a "waiting" verdict on the normal path.
        await self.emit(Event(
            EventType.TASK_AWAITING_INPUT,
            data={
                "prompt": prompt,
                "checkpoint": checkpoint,
                "prompt_data": prompt_data or {},
                "stage": stage,
            },
        ))
        self.state["_paused"] = True
        self.state["_pause_checkpoint"] = checkpoint
        self.state["_pause_prompt"] = prompt
        self.state["_pause_prompt_data"] = prompt_data or {}
        self.state["_pause_stage"] = stage
        self.state["_pause_budget"] = (
            self.budget.snapshot() if hasattr(self.budget, "snapshot") else {}
        )
        # Return empty — caller should check _paused and exit cleanly.
        return {}


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------


@dataclass
class WorkflowOutput:
    task_id: str
    verdict: str = "unknown"
    score: float | None = None
    results: Any = None
    trace: list[Event] = field(default_factory=list)
    budget: dict[str, float | int] = field(default_factory=dict)
    error: str | None = None


# ---------------------------------------------------------------------------
# Base workflow
# ---------------------------------------------------------------------------


class BaseWorkflow(ABC):
    """All concrete workflows subclass this and implement :meth:`run`.

    The discovery layer (``backend.workflows.registry`` in a later stage)
    walks ``backend.workflows`` and registers every subclass under its
    ``name``. Keep ``name`` URL-safe.
    """

    name: ClassVar[str] = ""
    version: ClassVar[str] = "1.0.0"

    @abstractmethod
    async def run(self, ctx: WorkflowContext) -> WorkflowOutput: ...

    # ---- infrastructure helpers -------------------------------------

    async def stage(
        self,
        ctx: WorkflowContext,
        name: str,
        fn: Callable[[WorkflowContext], Awaitable[T]],
    ) -> T:
        """Run a named unit of work with budget-check + event emission.

        Failure path always emits ``task.error`` and re-raises — the
        surrounding ``run()`` method decides whether to swallow, retry, or
        translate into a ``WorkflowOutput``.

        P12.1 — defence in depth: any *stdlib* environmental exception
        (``OSError`` / ``EnvironmentError`` family — ``BrokenPipeError``,
        ``ConnectionResetError``, ``IsADirectoryError`` …) is normalised
        into :class:`InfrastructureError` before being re-raised, so the
        emitted ``task.error`` carries a typed AAF error rather than a
        raw stdlib name. Adapter/provider layers should still catch these
        at their boundary; this is the last-resort net so a missed catch
        somewhere deep doesn't show up to the user as
        ``"BrokenPipeError: [Errno 32] Broken pipe"``.
        """
        ctx.budget.assert_ok()
        await ctx.emit(Event(EventType.TASK_STAGE_START, data={"stage": name}))
        started = time.monotonic()
        try:
            out = await fn(ctx)
        except OSError as exc:
            # OSError covers all the BrokenPipe/ConnectionReset/IsADirectory
            # family. Normalise *before* emitting so trace + DB carry the
            # typed name. Chain via ``from`` to preserve traceback.
            wrapped = InfrastructureError(
                f"{type(exc).__name__}: {exc}",
                source_type=type(exc).__name__,
            )
            await ctx.emit(
                Event(
                    EventType.TASK_ERROR,
                    data={
                        "stage": name,
                        "message": str(wrapped),
                        "type": type(wrapped).__name__,
                        "source_type": wrapped.source_type,
                    },
                )
            )
            raise wrapped from exc
        except Exception as exc:
            await ctx.emit(
                Event(
                    EventType.TASK_ERROR,
                    data={"stage": name, "message": str(exc), "type": type(exc).__name__},
                )
            )
            raise
        duration_ms = int((time.monotonic() - started) * 1000)
        await ctx.emit(
            Event(EventType.TASK_STAGE_END, data={"stage": name, "duration_ms": duration_ms})
        )
        if ctx.checkpoint_enabled:
            await ctx.checkpoint(label=name)
        return out

    async def stage_soft(
        self,
        ctx: WorkflowContext,
        name: str,
        fn: Callable[[WorkflowContext], Awaitable[T]],
    ) -> T | None:
        """Like :meth:`stage` but **never raises** — on failure emits a
        ``task.warning`` event and returns ``None``.

        Use this for stages where the workflow can degrade gracefully
        (e.g. ``recall``: an empty memory snapshot is strictly worse than
        a populated one, but a *failed task* is much worse than missing
        context). The convention is for the stage's ``fn`` to set safe
        defaults on ``ctx.state`` *before* the risky call so partial
        progress survives — see :class:`ConsultWorkflow._recall` for the
        canonical pattern.

        The emitted ``task.warning`` event carries the same fields as
        ``task.error`` so the UI can render either with one component.
        """
        ctx.budget.assert_ok()
        await ctx.emit(Event(EventType.TASK_STAGE_START, data={"stage": name}))
        started = time.monotonic()
        try:
            out = await fn(ctx)
        except Exception as exc:
            # Same normalisation as ``stage`` so the warning payload is
            # comparable to an error payload one level up.
            if isinstance(exc, OSError):
                source_type = type(exc).__name__
                message = f"{source_type}: {exc}"
                err_type = "InfrastructureError"
            else:
                source_type = type(exc).__name__
                message = str(exc)
                err_type = source_type
            await ctx.emit(
                Event(
                    EventType.TASK_WARNING,
                    data={
                        "stage": name,
                        "message": message,
                        "type": err_type,
                        "source_type": source_type,
                        # ``recoverable: true`` distinguishes a soft fail from
                        # a hard one. The frontend keys off this to colour the
                        # banner amber rather than red.
                        "recoverable": True,
                    },
                )
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            await ctx.emit(
                Event(
                    EventType.TASK_STAGE_END,
                    data={"stage": name, "duration_ms": duration_ms, "degraded": True},
                )
            )
            return None
        duration_ms = int((time.monotonic() - started) * 1000)
        await ctx.emit(
            Event(EventType.TASK_STAGE_END, data={"stage": name, "duration_ms": duration_ms})
        )
        if ctx.checkpoint_enabled:
            await ctx.checkpoint(label=name)
        return out


__all__ = [
    "BaseWorkflow",
    "Checkpointer",
    "EventSink",
    "WorkflowContext",
    "WorkflowOutput",
]
