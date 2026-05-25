import asyncio

import pytest

from backend.core.events import EventType
from backend.workflows.base import WorkflowContext
from backend.workflows.primitives import (
    branch,
    loop_until,
    parallel,
    retry,
    sequential,
)


@pytest.mark.asyncio
async def test_sequential_runs_in_order():
    ctx = WorkflowContext(task_id="t")
    order: list[int] = []

    def mk(i):
        async def _s(_c):
            order.append(i)
            return i

        return _s

    out = await sequential(ctx, [mk(1), mk(2), mk(3)])
    assert out == [1, 2, 3]
    assert order == [1, 2, 3]


@pytest.mark.asyncio
async def test_parallel_runs_concurrently_bounded():
    ctx = WorkflowContext(task_id="t")
    started = 0
    peak = 0
    lock = asyncio.Lock()

    def mk(i):
        async def _s(_c):
            nonlocal started, peak
            async with lock:
                started += 1
                peak = max(peak, started)
            await asyncio.sleep(0.01)
            async with lock:
                started -= 1
            return i

        return _s

    out = await parallel(ctx, [mk(i) for i in range(6)], max_concurrency=2)
    assert sorted(out) == list(range(6))
    assert peak <= 2


@pytest.mark.asyncio
async def test_parallel_empty():
    ctx = WorkflowContext(task_id="t")
    assert await parallel(ctx, []) == []


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt():
    ctx = WorkflowContext(task_id="t")
    attempts = 0

    async def flaky(_c):
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("nope")
        return "ok"

    out = await retry(ctx, flaky, max_attempts=3, backoff_s=0)
    assert out == "ok"
    assert attempts == 2
    assert any(e.type == EventType.TASK_RETRY for e in ctx.trace)


@pytest.mark.asyncio
async def test_retry_gives_up_after_max_attempts():
    ctx = WorkflowContext(task_id="t")

    async def always_fail(_c):
        raise RuntimeError("perm")

    with pytest.raises(RuntimeError, match="perm"):
        await retry(ctx, always_fail, max_attempts=2, backoff_s=0)


@pytest.mark.asyncio
async def test_retry_respects_on_filter():
    ctx = WorkflowContext(task_id="t")

    async def fail_value(_c):
        raise ValueError("once")

    with pytest.raises(ValueError):
        await retry(
            ctx,
            fail_value,
            max_attempts=5,
            backoff_s=0,
            on=lambda e: isinstance(e, RuntimeError),  # not retryable
        )


@pytest.mark.asyncio
async def test_branch_async_predicate():
    ctx = WorkflowContext(task_id="t")

    async def pred(_c):
        return True

    async def yes(_c):
        return "Y"

    async def no(_c):
        return "N"

    assert await branch(ctx, pred, yes, no) == "Y"


@pytest.mark.asyncio
async def test_branch_sync_predicate():
    ctx = WorkflowContext(task_id="t")

    async def yes(_c):
        return "Y"

    async def no(_c):
        return "N"

    assert await branch(ctx, lambda _c: False, yes, no) == "N"


@pytest.mark.asyncio
async def test_loop_until_stops_on_condition():
    ctx = WorkflowContext(task_id="t")
    counter = 0

    async def body(_c):
        nonlocal counter
        counter += 1
        return counter

    def done(r, _c):
        return r >= 2

    out = await loop_until(ctx, body, done, max_iter=10)
    assert out == [1, 2]


@pytest.mark.asyncio
async def test_loop_until_respects_max_iter():
    ctx = WorkflowContext(task_id="t")

    async def body(_c):
        return 0

    out = await loop_until(ctx, body, lambda _r, _c: False, max_iter=3)
    assert out == [0, 0, 0]
