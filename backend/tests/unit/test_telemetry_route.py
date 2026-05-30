"""Tests for the route-tagging contextvar and Record.route plumbing.

Covers two related properties:

1. The contextvar set by ``set_active_route`` flows through any
   ``record(...)`` call made on the same async task — adapters that
   already call ``record`` without knowing about routing get tagged
   automatically.
2. An explicit ``route="..."`` argument to ``record()`` always wins
   over the contextvar (so callers that already know the route name
   stay deterministic).
"""

from __future__ import annotations

import asyncio

from backend.core.llm.telemetry import (
    active_route,
    record,
    recorder,
    reset_active_route,
    set_active_route,
)


def setup_function() -> None:
    recorder().reset()


def test_active_route_defaults_to_none() -> None:
    assert active_route() is None


def test_record_inherits_active_route_from_contextvar() -> None:
    token = set_active_route("reasoning")
    try:
        record(provider="mock", model="m1", prompt_tokens=1, completion_tokens=2, cost_usd=0.0)
    finally:
        reset_active_route(token)

    records = recorder().records()
    assert len(records) == 1
    assert records[0].route == "reasoning"
    # contextvar is reset cleanly
    assert active_route() is None


def test_explicit_route_arg_wins_over_contextvar() -> None:
    token = set_active_route("reasoning")
    try:
        record(
            provider="mock",
            model="m1",
            prompt_tokens=1,
            completion_tokens=1,
            cost_usd=0.0,
            route="fast",
        )
    finally:
        reset_active_route(token)

    records = recorder().records()
    assert records[-1].route == "fast"


def test_route_isolation_across_tasks() -> None:
    """Each asyncio Task gets its own contextvar copy — set in task A
    must not leak into task B."""

    async def runner() -> tuple[str | None, str | None]:
        results: dict[str, str | None] = {}

        async def task_a() -> None:
            token = set_active_route("reasoning")
            try:
                # let task B run while we hold the tag
                await asyncio.sleep(0)
                results["a"] = active_route()
            finally:
                reset_active_route(token)

        async def task_b() -> None:
            await asyncio.sleep(0)
            results["b"] = active_route()

        await asyncio.gather(task_a(), task_b())
        return results.get("a"), results.get("b")

    a_route, b_route = asyncio.run(runner())
    assert a_route == "reasoning"
    assert b_route is None
