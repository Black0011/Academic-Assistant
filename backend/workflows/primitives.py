"""Tiny async orchestration primitives — our 5-function replacement for a
graph DSL. Each primitive is a plain async function; you can also skip
them and write straight-line Python — the choice is deliberate.

See PLAN §10.2.3.
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from backend.core.events import Event, EventType

from .base import WorkflowContext

T = TypeVar("T")

Stage = Callable[[WorkflowContext], Awaitable[T]]
Predicate = Callable[[WorkflowContext], Awaitable[bool] | bool]
UntilFn = Callable[[Any, WorkflowContext], Awaitable[bool] | bool]


async def sequential(ctx: WorkflowContext, stages: list[Stage[Any]]) -> list[Any]:
    """Run each stage in order, collecting results. Abort on first error."""
    out: list[Any] = []
    for s in stages:
        out.append(await s(ctx))
    return out


async def parallel(
    ctx: WorkflowContext,
    stages: list[Stage[Any]],
    *,
    max_concurrency: int = 4,
    return_exceptions: bool = False,
) -> list[Any]:
    """Run stages concurrently bounded by ``max_concurrency``.

    Uses a semaphore rather than `asyncio.gather(...)` alone so we cap
    the pool size — important for skill execution that may fork many
    subprocesses.
    """
    if not stages:
        return []
    sem = asyncio.Semaphore(max(1, max_concurrency))

    async def _guarded(s: Stage[Any]) -> Any:
        async with sem:
            return await s(ctx)

    return await asyncio.gather(*[_guarded(s) for s in stages], return_exceptions=return_exceptions)


async def retry(
    ctx: WorkflowContext,
    fn: Stage[T],
    *,
    max_attempts: int = 2,
    on: Callable[[BaseException], bool] = lambda _e: True,
    backoff_s: float = 0.1,
    backoff_factor: float = 2.0,
) -> T:
    """Call ``fn`` up to ``max_attempts`` times with exponential backoff.

    ``on(exc)`` decides whether the exception type is retryable — defaults
    to "retry everything". An emitted ``task.retry`` event lets consumers
    observe the decision.
    """
    last: BaseException | None = None
    attempt = 0
    while attempt < max_attempts:
        attempt += 1
        try:
            return await fn(ctx)
        except BaseException as exc:
            last = exc
            if attempt >= max_attempts or not on(exc):
                raise
            await ctx.emit(
                Event(
                    EventType.TASK_RETRY,
                    data={
                        "attempt": attempt,
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                )
            )
            await asyncio.sleep(backoff_s * (backoff_factor ** (attempt - 1)))
    assert last is not None  # for type checker; unreachable
    raise last


async def branch(
    ctx: WorkflowContext,
    predicate: Predicate,
    if_true: Stage[T],
    if_false: Stage[T],
) -> T:
    """Async-aware if/else."""
    cond = await _call_maybe_async(predicate, ctx)
    chosen = if_true if cond else if_false
    return await chosen(ctx)


async def loop_until(
    ctx: WorkflowContext,
    fn: Stage[T],
    until: UntilFn,
    *,
    max_iter: int = 3,
) -> list[T]:
    """Run ``fn`` until ``until(result, ctx)`` is truthy (or iter exhausted).

    Returns every intermediate result in order — handy for evaluator loops
    that want to report convergence history.
    """
    results: list[T] = []
    for _ in range(max(1, max_iter)):
        r = await fn(ctx)
        results.append(r)
        done = await _call_maybe_async(until, r, ctx)
        if done:
            break
    return results


# ---- helpers --------------------------------------------------------------


async def _call_maybe_async(fn: Callable[..., Any], *args: Any) -> Any:
    if inspect.iscoroutinefunction(fn):
        return await fn(*args)
    result = fn(*args)
    if inspect.isawaitable(result):
        return await result
    return result


__all__ = ["branch", "loop_until", "parallel", "retry", "sequential"]
