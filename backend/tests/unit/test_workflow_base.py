import pytest

from backend.core.budget import Budget
from backend.core.errors import BudgetExceededError, InfrastructureError
from backend.core.events import Event, EventType
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput


class _NoopWorkflow(BaseWorkflow):
    name = "_noop"

    async def run(self, ctx):
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok")


@pytest.mark.asyncio
async def test_emit_appends_to_trace():
    ctx = WorkflowContext(task_id="t1")
    await ctx.emit(Event("foo"))
    assert len(ctx.trace) == 1
    assert ctx.trace[0].task_id == "t1"  # auto-filled


@pytest.mark.asyncio
async def test_emit_forwards_to_sink():
    received: list[Event] = []

    async def sink(e: Event) -> None:
        received.append(e)

    ctx = WorkflowContext(task_id="t1").with_sink(sink)
    await ctx.emit(Event("bar"))
    assert received and received[0].type == "bar"


@pytest.mark.asyncio
async def test_emit_survives_sink_failure():
    async def broken(_e):
        raise RuntimeError("sink down")

    ctx = WorkflowContext(task_id="t1").with_sink(broken)
    await ctx.emit(Event("x"))  # must not raise
    assert len(ctx.trace) == 1


@pytest.mark.asyncio
async def test_stage_emits_start_end_and_returns_value():
    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(c):
        return 42

    out = await wf.stage(ctx, "plan", body)
    assert out == 42
    types = [e.type for e in ctx.trace]
    assert EventType.TASK_STAGE_START in types
    assert EventType.TASK_STAGE_END in types


@pytest.mark.asyncio
async def test_stage_emits_error_and_reraises():
    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(_c):
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        await wf.stage(ctx, "plan", body)

    error_events = [e for e in ctx.trace if e.type == EventType.TASK_ERROR]
    assert error_events
    assert error_events[0].data["stage"] == "plan"


@pytest.mark.asyncio
async def test_stage_enforces_budget_before_work():
    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1", budget=Budget(max_prompt_tokens=10))
    ctx.budget.accrue_llm(prompt_tokens=20)  # already over

    async def body(_c):
        raise AssertionError("should not run")

    with pytest.raises(BudgetExceededError):
        await wf.stage(ctx, "plan", body)


@pytest.mark.asyncio
async def test_checkpoint_noop_when_disabled():
    ctx = WorkflowContext(task_id="t1", checkpoint_enabled=False)
    # No checkpointer wired → must not raise.
    await ctx.checkpoint("label")


# ---------------------------------------------------------------------------
# P12.1 — stdlib-error normalisation + stage_soft
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stage_normalises_os_error_to_infrastructure_error():
    """A raw ``BrokenPipeError`` slipping out of a stage body must surface
    to the caller as a typed :class:`InfrastructureError` whose
    ``source_type`` records the original class name.

    This is the last-resort net behind the provider/store-level wrappers
    — without it the workflow's outer ``except`` would format the error
    as the raw stdlib name, which confuses users (and groups badly in
    observability dashboards)."""

    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(_c):
        raise BrokenPipeError(32, "Broken pipe")

    with pytest.raises(InfrastructureError) as info:
        await wf.stage(ctx, "recall", body)

    err = info.value
    assert err.source_type == "BrokenPipeError"
    assert err.http_status == 502
    assert err.retryable is True
    assert "Broken pipe" in str(err)

    # And the emitted task.error carries the normalised type, not "BrokenPipeError".
    error_events = [e for e in ctx.trace if e.type == EventType.TASK_ERROR]
    assert error_events, "stage should still emit task.error on failure"
    assert error_events[0].data["type"] == "InfrastructureError"
    assert error_events[0].data["source_type"] == "BrokenPipeError"
    assert error_events[0].data["stage"] == "recall"


@pytest.mark.asyncio
async def test_stage_leaves_non_os_errors_unchanged():
    """Only stdlib ``OSError`` family is normalised; AAF errors and other
    library exceptions must bubble through with their original type so
    higher layers can dispatch on them."""

    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(_c):
        raise ValueError("nope")

    with pytest.raises(ValueError, match="nope"):
        await wf.stage(ctx, "plan", body)

    error_events = [e for e in ctx.trace if e.type == EventType.TASK_ERROR]
    assert error_events
    assert error_events[0].data["type"] == "ValueError"


@pytest.mark.asyncio
async def test_stage_soft_swallows_exception_and_emits_warning():
    """``stage_soft`` is the recall/optional-stage variant: on failure it
    must NOT raise and must emit ``task.warning`` (not ``task.error``)
    so the workflow's outer loop keeps running."""

    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(_c):
        raise ConnectionResetError("upstream gone")

    out = await wf.stage_soft(ctx, "recall", body)
    assert out is None

    warnings = [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    errors = [e for e in ctx.trace if e.type == EventType.TASK_ERROR]
    assert warnings, "stage_soft must emit task.warning on failure"
    assert not errors, "stage_soft must NOT emit task.error on failure"
    w = warnings[0].data
    assert w["stage"] == "recall"
    assert w["source_type"] == "ConnectionResetError"
    assert w["type"] == "InfrastructureError"
    assert w["recoverable"] is True

    # stage_end is still emitted (with degraded=True) so timing telemetry
    # and the "this stage is done" signal stay consistent.
    end = [e for e in ctx.trace if e.type == EventType.TASK_STAGE_END]
    assert end and end[0].data.get("degraded") is True


@pytest.mark.asyncio
async def test_stage_soft_returns_value_on_success():
    """Happy path: ``stage_soft`` must behave exactly like ``stage`` when
    the body succeeds — no warning, returns the value, stage_end clean."""

    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(_c):
        return {"papers": 3}

    out = await wf.stage_soft(ctx, "recall", body)
    assert out == {"papers": 3}
    assert not [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    end = [e for e in ctx.trace if e.type == EventType.TASK_STAGE_END]
    assert end and "degraded" not in end[0].data


@pytest.mark.asyncio
async def test_stage_soft_normalises_non_os_errors_too():
    """Non-OS errors still get warned (no raise) — but the type field is
    the original class name, only the OS family is renamed to
    InfrastructureError."""

    wf = _NoopWorkflow()
    ctx = WorkflowContext(task_id="t1")

    async def body(_c):
        raise RuntimeError("recall path broken")

    await wf.stage_soft(ctx, "recall", body)
    warnings = [e for e in ctx.trace if e.type == EventType.TASK_WARNING]
    assert warnings
    assert warnings[0].data["type"] == "RuntimeError"
    assert warnings[0].data["source_type"] == "RuntimeError"


@pytest.mark.asyncio
async def test_checkpoint_calls_injected_checkpointer():
    class Memo:
        def __init__(self):
            self.saves = []

        async def save(self, task_id, label, state):
            self.saves.append((task_id, label, dict(state)))

        async def load(self, task_id):
            return None

    memo = Memo()
    ctx = WorkflowContext(task_id="t1", checkpoint_enabled=True).with_checkpointer(memo)
    ctx.state["x"] = 1
    await ctx.checkpoint("s1")
    assert memo.saves == [("t1", "s1", {"x": 1})]
    # And we emitted a checkpoint event.
    assert any(e.type == EventType.TASK_CHECKPOINT for e in ctx.trace)
