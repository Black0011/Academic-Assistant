"""Auto-compact long LLM contexts before they hit the context window.

When :class:`CompactingLLMProvider` wraps an inner provider, every
``complete(...)`` call is intercepted:

1. Estimate the total token count of the incoming messages.
2. Compare against ``inner.context_window(model) * threshold`` (default
   0.7 — leaves headroom for the response and any tool-call overhead).
3. If under the threshold → pass through unchanged (zero overhead).
4. If over the threshold → :func:`compact_messages` rewrites the history
   so that:

   * All ``system`` messages stay verbatim at the front.
   * The most recent ``keep_recent_n`` non-system messages stay verbatim
     at the end (so the model still sees the latest turn-taking exactly
     as the caller wrote it).
   * Everything between is summarised by a single LLM call into one
     compact ``system`` message inserted just before the recent tail.

The summariser call is made on the inner provider, ideally on its
"fast" route (cheaper / faster), so compaction itself doesn't blow the
budget. A contextvar (:data:`_INSIDE_COMPACTION`) prevents the
summariser call from triggering another compaction recursively.

Compaction is **opt-in** via ``AAF_AUTOCOMPACT_ENABLED`` (see
:mod:`backend.settings`). When disabled — the default — this wrapper
is never constructed and behaviour is identical to the un-wrapped
provider.

A ``log.info("llm.compacted", ...)`` line is emitted on every fire so
operators can audit when / how aggressively compaction happened.
"""

from __future__ import annotations

import contextvars
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import structlog

from .base import (
    ChatMessage,
    CompletionChunk,
    CostEstimate,
    LLMProvider,
    ToolSpec,
    collect_text,
)

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Recursion guard
# ---------------------------------------------------------------------------

_INSIDE_COMPACTION: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "aaf.llm.inside_compaction", default=False
)


def is_inside_compaction() -> bool:
    """True when the current async task is in the middle of running the
    summariser call. Adapters / wrappers that don't want to participate
    in compaction can branch on this."""

    return _INSIDE_COMPACTION.get()


# ---------------------------------------------------------------------------
# Token estimation + compaction algorithm
# ---------------------------------------------------------------------------


_CHARS_PER_TOKEN = 4  # Crude char-to-token ratio that's "close enough"
_PER_MESSAGE_OVERHEAD = 4  # role marker + delimiters
_TOOL_CALL_OVERHEAD = 16  # JSON arg overhead per tool_call


def estimate_message_tokens(messages: list[ChatMessage]) -> int:
    """Rough upper-bound of how many tokens this conversation will use.

    Cheap by design: no tiktoken dep, no per-model tokenisation. We add
    a fixed per-message overhead to account for role markers and a
    larger per-tool-call overhead for JSON arg structures. Off by ~10%
    in either direction is fine — compaction's threshold default of 0.7
    leaves plenty of headroom.
    """

    total = 0
    for m in messages:
        text = m.text() or ""
        total += max(1, len(text) // _CHARS_PER_TOKEN) + _PER_MESSAGE_OVERHEAD
        if m.tool_calls:
            total += len(m.tool_calls) * _TOOL_CALL_OVERHEAD
            for tc in m.tool_calls:
                # Best-effort approximation of the JSON args size.
                total += max(1, len(repr(tc.arguments)) // _CHARS_PER_TOKEN)
    return total


@dataclass
class CompactionResult:
    compacted: list[ChatMessage]
    dropped: list[ChatMessage]
    summary: str
    original_tokens: int
    compacted_tokens: int


_SUMMARY_SYSTEM = (
    "You are a context-compaction assistant. The user will paste the "
    "middle slice of a longer conversation. Produce a concise summary "
    "that PRESERVES: factual claims, decisions made, IDs / paper-IDs / "
    "filenames mentioned, any open questions, and any tool-call results. "
    "DROP: filler chit-chat, repeated greetings, and your own thinking-"
    "out-loud. Output a single paragraph in third person, ≤ 200 words. "
    "Do not invent details."
)


def _format_history_for_summary(history: list[ChatMessage]) -> str:
    parts: list[str] = []
    for i, m in enumerate(history, 1):
        prefix = f"[{i}] {m.role}"
        if m.tool_calls:
            tc_summary = ", ".join(
                f"{tc.name}({_truncate(repr(tc.arguments), 80)})" for tc in m.tool_calls
            )
            parts.append(f"{prefix} → tool_call({tc_summary})")
        text = (m.text() or "").strip()
        if text:
            parts.append(f"{prefix}: {_truncate(text, 800)}")
    return "\n\n".join(parts)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


async def compact_messages(
    messages: list[ChatMessage],
    *,
    summariser: LLMProvider,
    model: str | None,
    keep_recent_n: int,
) -> CompactionResult:
    """Build a compacted message list using ``summariser`` for the middle.

    Caller is expected to hold :data:`_INSIDE_COMPACTION` so the
    summariser's own ``complete`` call doesn't loop.
    """

    if keep_recent_n < 0:
        raise ValueError("keep_recent_n must be >= 0")

    systems = [m for m in messages if m.role == "system"]
    non_system = [m for m in messages if m.role != "system"]

    if len(non_system) <= keep_recent_n:
        # Nothing in the "middle" to summarise — just return the input
        # unchanged so we don't burn an LLM call for no gain.
        original = estimate_message_tokens(messages)
        return CompactionResult(
            compacted=list(messages),
            dropped=[],
            summary="",
            original_tokens=original,
            compacted_tokens=original,
        )

    middle = non_system[:-keep_recent_n] if keep_recent_n else non_system
    tail = non_system[-keep_recent_n:] if keep_recent_n else []

    summary_prompt = ChatMessage(
        role="user",
        content=(
            "Summarise the following conversation slice. "
            "Output a single paragraph (≤ 200 words):\n\n"
            f"{_format_history_for_summary(middle)}"
        ),
    )

    summary_text, _, _, _ = await collect_text(
        await summariser.complete(
            [
                ChatMessage(role="system", content=_SUMMARY_SYSTEM),
                summary_prompt,
            ],
            model=model,
            temperature=0.0,
            stream=False,
        )
    )
    summary_text = summary_text.strip() or "(summariser returned no text)"

    summary_msg = ChatMessage(
        role="system",
        content=(
            "[Compacted context — earlier portion of this conversation, "
            f"summarised by AAF auto-compactor; original {len(middle)} "
            "messages collapsed into the paragraph below.]\n\n"
            f"{summary_text}"
        ),
    )

    compacted = [*systems, summary_msg, *tail]
    original_tokens = estimate_message_tokens(messages)
    compacted_tokens = estimate_message_tokens(compacted)
    return CompactionResult(
        compacted=compacted,
        dropped=middle,
        summary=summary_text,
        original_tokens=original_tokens,
        compacted_tokens=compacted_tokens,
    )


# ---------------------------------------------------------------------------
# Provider wrapper
# ---------------------------------------------------------------------------


_DEFAULT_FALLBACK_WINDOW = 8192  # used when inner.context_window(...) is unhelpful


class CompactingLLMProvider:
    """LLMProvider wrapper that auto-compacts messages near the limit.

    The wrapper itself satisfies :class:`backend.core.llm.base.LLMProvider`
    — drop it into ``app.state.aaf.llm`` exactly like any other provider.

    Parameters
    ----------
    inner            : the underlying provider (single, routing, mock, …)
    threshold        : fraction of context window that triggers compaction
                       (0.7 = "fire when input occupies ≥70% of window")
    keep_recent_n    : number of trailing non-system messages preserved
                       verbatim around the summary (default 6)
    summariser_route : if ``inner`` exposes ``for_route``, the named route
                       used for the summariser call (default "fast")
    fallback_window  : context window assumed when ``inner.context_window``
                       returns ``0`` or a clearly bogus value

    Pass-through guarantees
    -----------------------
    * Calls below the threshold add **zero overhead** beyond a single
      arithmetic check.
    * When ``inner`` lacks ``for_route``, the summariser call is made on
      ``inner`` itself; no Protocol changes required.
    * Recursion guard ensures the summariser call cannot re-trigger
      compaction.
    """

    name = "compactor"

    def __init__(
        self,
        *,
        inner: LLMProvider,
        threshold: float = 0.7,
        keep_recent_n: int = 6,
        summariser_route: str = "fast",
        fallback_window: int = _DEFAULT_FALLBACK_WINDOW,
    ) -> None:
        if not 0.1 <= threshold <= 0.95:
            raise ValueError(f"threshold must be in [0.1, 0.95], got {threshold}")
        if keep_recent_n < 0:
            raise ValueError("keep_recent_n must be >= 0")
        self._inner = inner
        self._threshold = threshold
        self._keep_recent_n = keep_recent_n
        self._summariser_route = summariser_route
        self._fallback_window = fallback_window

    @property
    def inner(self) -> LLMProvider:
        return self._inner

    # ---- summariser selection ----------------------------------------

    def _summariser(self) -> LLMProvider:
        for_route = getattr(self._inner, "for_route", None)
        if callable(for_route):
            return for_route(self._summariser_route)
        return self._inner

    def _window(self, model: str | None) -> int:
        # context_window() per Protocol returns int; some adapters may
        # raise KeyError for unknown model names. Anything else (e.g.
        # network-talking adapters) is a real bug and must propagate.
        try:
            window = int(self._inner.context_window(model or ""))
        except (KeyError, ValueError):
            window = 0
        return window if window > 0 else self._fallback_window

    # ---- LLMProvider Protocol ----------------------------------------

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = False,
    ) -> AsyncIterator[CompletionChunk]:
        # Recursion guard: skip when the summariser is calling us back.
        if _INSIDE_COMPACTION.get():
            return await self._inner.complete(
                messages,
                tools=tools,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
            )

        original_tokens = estimate_message_tokens(messages)
        window = self._window(model)
        budget = int(window * self._threshold)

        if original_tokens <= budget:
            return await self._inner.complete(
                messages,
                tools=tools,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                stream=stream,
            )

        token = _INSIDE_COMPACTION.set(True)
        started = time.monotonic()
        try:
            result = await compact_messages(
                messages,
                summariser=self._summariser(),
                model=model,
                keep_recent_n=self._keep_recent_n,
            )
        finally:
            _INSIDE_COMPACTION.reset(token)

        log.info(
            "llm.compacted",
            model=model or "(default)",
            window_tokens=window,
            threshold=self._threshold,
            original_tokens=result.original_tokens,
            compacted_tokens=result.compacted_tokens,
            dropped_messages=len(result.dropped),
            duration_ms=int((time.monotonic() - started) * 1000),
        )

        return await self._inner.complete(
            result.compacted,
            tools=tools,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=stream,
        )

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        return await self._inner.embed(texts, model=model)

    def supports_tools(self) -> bool:
        return self._inner.supports_tools()

    def supports_streaming(self) -> bool:
        return self._inner.supports_streaming()

    def context_window(self, model: str) -> int:
        return self._inner.context_window(model)

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        return await self._inner.estimate_cost(messages, model=model)

    # Routing-aware passthrough so workflows can still call
    # ``ctx.llm.for_route("reasoning")`` after compaction is wired in.
    def for_route(self, name: str | None) -> LLMProvider:
        for_route = getattr(self._inner, "for_route", None)
        if callable(for_route):
            result = for_route(name)
            assert isinstance(result, LLMProvider)
            return result
        return self._inner


__all__ = [
    "CompactingLLMProvider",
    "CompactionResult",
    "compact_messages",
    "estimate_message_tokens",
    "is_inside_compaction",
]


def __getattr__(name: str) -> Any:
    if name == "_INSIDE_COMPACTION":
        return _INSIDE_COMPACTION
    raise AttributeError(name)
