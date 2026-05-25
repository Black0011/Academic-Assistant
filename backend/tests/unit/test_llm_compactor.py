"""Unit tests for :mod:`backend.core.llm.compactor`.

Covers:

* Token estimator monotonicity + per-message overhead.
* `compact_messages` keeps system + the last `keep_recent_n` non-system
  messages verbatim, calls the summariser exactly once for the middle,
  and short-circuits when there is nothing in the middle.
* `CompactingLLMProvider` is a pure pass-through under the threshold.
* Above the threshold, the wrapper compacts before delegating to the
  inner provider.
* Recursion guard: the summariser's own call to `complete()` is *not*
  itself compacted.
* Routing-aware: the wrapper picks the named summariser route from a
  `RoutingLLMProvider` when one is configured.
* Constructor validation: bad `threshold` / `keep_recent_n` raise
  `ValueError` synchronously (no boot-time silent failure).
"""

from __future__ import annotations

import pytest

from backend.core.llm.base import ChatMessage, collect_text
from backend.core.llm.compactor import (
    CompactingLLMProvider,
    compact_messages,
    estimate_message_tokens,
    is_inside_compaction,
)
from backend.core.llm.mock import MockLLMProvider
from backend.core.llm.router import RouteSpec, RoutingLLMProvider, RoutingPolicy

# ---------------------------------------------------------------------------
# estimate_message_tokens
# ---------------------------------------------------------------------------


def test_estimate_tokens_monotonic_in_message_count() -> None:
    one = [ChatMessage(role="user", content="hello world")]
    two = [*one, ChatMessage(role="assistant", content="hi")]
    assert estimate_message_tokens(two) > estimate_message_tokens(one)


def test_estimate_tokens_grows_with_text_length() -> None:
    short = [ChatMessage(role="user", content="x")]
    long = [ChatMessage(role="user", content="x" * 4000)]
    assert estimate_message_tokens(long) > estimate_message_tokens(short) * 10


# ---------------------------------------------------------------------------
# compact_messages
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_messages_keeps_systems_and_recent_tail() -> None:
    summariser = MockLLMProvider()
    summariser.queue_text("[summary of middle]")

    msgs = [
        ChatMessage(role="system", content="be helpful"),
        ChatMessage(role="user", content="msg 1"),
        ChatMessage(role="assistant", content="resp 1"),
        ChatMessage(role="user", content="msg 2"),
        ChatMessage(role="assistant", content="resp 2"),
        ChatMessage(role="user", content="msg 3"),
        ChatMessage(role="assistant", content="resp 3"),
        ChatMessage(role="user", content="msg-recent"),
        ChatMessage(role="assistant", content="resp-recent"),
    ]

    result = await compact_messages(msgs, summariser=summariser, model=None, keep_recent_n=2)

    # System preserved at front
    assert result.compacted[0].role == "system" and result.compacted[0].text() == "be helpful"
    # Single summary system message inserted next
    assert result.compacted[1].role == "system"
    assert "[summary of middle]" in result.compacted[1].text()
    # Last 2 non-system preserved verbatim at end
    assert result.compacted[-2].text() == "msg-recent"
    assert result.compacted[-1].text() == "resp-recent"
    # 6 middle non-system messages were dropped
    assert len(result.dropped) == 6
    assert all(m.text().startswith(("msg ", "resp ")) for m in result.dropped)


@pytest.mark.asyncio
async def test_compact_messages_short_circuits_when_nothing_to_summarise() -> None:
    summariser = MockLLMProvider()
    msgs = [
        ChatMessage(role="system", content="x"),
        ChatMessage(role="user", content="a"),
        ChatMessage(role="assistant", content="b"),
    ]
    # keep_recent_n >= non-system count → nothing to summarise; no LLM call.
    result = await compact_messages(msgs, summariser=summariser, model=None, keep_recent_n=10)
    assert summariser.calls == []
    assert result.compacted == msgs
    assert result.dropped == []


@pytest.mark.asyncio
async def test_compact_messages_rejects_negative_keep_recent() -> None:
    with pytest.raises(ValueError):
        await compact_messages(
            [ChatMessage(role="user", content="a")],
            summariser=MockLLMProvider(),
            model=None,
            keep_recent_n=-1,
        )


# ---------------------------------------------------------------------------
# CompactingLLMProvider — pass-through + fire-on-overflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compacting_provider_is_passthrough_below_threshold() -> None:
    inner = MockLLMProvider(default_model="m", context_window=10_000)
    inner.queue_text("hi")
    wrapped = CompactingLLMProvider(inner=inner, threshold=0.7, keep_recent_n=2)

    text, _, _ = await collect_text(
        await wrapped.complete([ChatMessage(role="user", content="short")])
    )
    assert text == "hi"
    # No summariser call was needed.
    assert len(inner.calls) == 1


@pytest.mark.asyncio
async def test_compacting_provider_fires_compaction_above_threshold() -> None:
    """Stage a small context window so 4 modest messages overflow."""

    inner = MockLLMProvider(default_model="m", context_window=200)
    # Inner's own complete sees: (1) summariser pass first, then
    # (2) the real call with the compacted messages.
    inner.queue_text("[summary]")
    inner.queue_text("real-resp")

    wrapped = CompactingLLMProvider(
        inner=inner, threshold=0.5, keep_recent_n=1, fallback_window=200
    )

    msgs = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="x" * 200),
        ChatMessage(role="assistant", content="y" * 200),
        ChatMessage(role="user", content="x" * 200),
        ChatMessage(role="assistant", content="kept"),
    ]

    text, _, _ = await collect_text(await wrapped.complete(msgs))
    assert text == "real-resp"

    # Two inner.complete calls: (1) summariser, (2) the real one.
    assert len(inner.calls) == 2
    real_call_msgs = inner.calls[1]["messages"]
    # The real call sees the system + the summary + the recent tail (1).
    roles = [m["role"] for m in real_call_msgs]
    assert roles[0] == "system"  # original sys
    assert roles[1] == "system"  # injected summary
    assert roles[-1] == "assistant"  # the kept tail
    assert real_call_msgs[-1]["content"] == "kept"


@pytest.mark.asyncio
async def test_recursion_guard_blocks_nested_compaction() -> None:
    """The summariser's own complete() call must not re-trigger compaction."""

    seen_inside: list[bool] = []

    class _ProbingProvider(MockLLMProvider):
        async def complete(self, messages, **kwargs):
            seen_inside.append(is_inside_compaction())
            return await super().complete(messages, **kwargs)

    inner = _ProbingProvider(default_model="m", context_window=200)
    inner.queue_text("[summary]")
    inner.queue_text("real-resp")
    wrapped = CompactingLLMProvider(
        inner=inner, threshold=0.5, keep_recent_n=1, fallback_window=200
    )

    msgs = [
        ChatMessage(role="user", content="x" * 200),
        ChatMessage(role="assistant", content="y" * 200),
        ChatMessage(role="user", content="x" * 200),
        ChatMessage(role="assistant", content="kept"),
    ]
    await collect_text(await wrapped.complete(msgs))

    # Two inner calls: first inside compaction (True), second outside (False).
    assert seen_inside == [True, False]
    # And the contextvar was reset cleanly when we returned.
    assert is_inside_compaction() is False


# ---------------------------------------------------------------------------
# Routing interaction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compactor_uses_named_route_for_summariser() -> None:
    """When `inner` exposes for_route, summariser flows through that route."""

    default_p = MockLLMProvider(default_model="cheap", context_window=200)
    fast_p = MockLLMProvider(default_model="cheap-fast", context_window=200)
    fast_p.queue_text("[summary via fast route]")
    default_p.queue_text("real-resp")

    router = RoutingLLMProvider(
        default=default_p,
        routes={"fast": fast_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="cheap")),
    )
    wrapped = CompactingLLMProvider(
        inner=router,
        threshold=0.5,
        keep_recent_n=1,
        summariser_route="fast",
        fallback_window=200,
    )

    msgs = [
        ChatMessage(role="system", content="be terse"),
        ChatMessage(role="user", content="x" * 200),
        ChatMessage(role="assistant", content="y" * 200),
        ChatMessage(role="user", content="x" * 200),
        ChatMessage(role="assistant", content="kept"),
    ]

    text, _, _ = await collect_text(await wrapped.complete(msgs))
    assert text == "real-resp"
    # Summariser hit the "fast" route's provider.
    assert len(fast_p.calls) == 1
    assert "[summary via fast route]" in default_p.calls[0]["messages"][1]["content"]
    # The default provider got the *real* call.
    assert len(default_p.calls) == 1


def test_compactor_for_route_passes_through_router() -> None:
    inner = MockLLMProvider()
    router = RoutingLLMProvider(
        default=inner,
        routes={"reasoning": inner},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="m")),
    )
    wrapped = CompactingLLMProvider(inner=router)
    # for_route on the wrapper should return the router's tagged sub-provider.
    p = wrapped.for_route("reasoning")
    # The router returns a _RouteTaggedProvider wrapping the mock.
    from backend.core.llm.router import _RouteTaggedProvider

    assert isinstance(p, _RouteTaggedProvider)
    assert p.route == "reasoning"


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_compactor_rejects_bad_threshold() -> None:
    with pytest.raises(ValueError):
        CompactingLLMProvider(inner=MockLLMProvider(), threshold=0.05)
    with pytest.raises(ValueError):
        CompactingLLMProvider(inner=MockLLMProvider(), threshold=1.2)


def test_compactor_rejects_bad_keep_recent() -> None:
    with pytest.raises(ValueError):
        CompactingLLMProvider(inner=MockLLMProvider(), keep_recent_n=-1)
