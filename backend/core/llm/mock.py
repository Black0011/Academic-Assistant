"""MockLLMProvider — scripted responses for tests.

Usage:
    mock = MockLLMProvider()
    mock.queue_text("Hello, world!")
    mock.queue_tool_call("search", {"query": "x"})
    mock.queue_text("Final answer")
    async for chunk in mock.complete(messages):
        ...
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from collections.abc import AsyncIterator
from typing import Any

from backend.core.errors import LLMAPIError

from .base import (
    ChatMessage,
    CompletionChunk,
    CostEstimate,
    ToolCall,
    ToolSpec,
    Usage,
)
from .telemetry import record as _telemetry_record


class MockLLMProvider:
    """A scriptable, in-memory LLM for unit tests.

    Each queued response is consumed in order. Tool-call responses set
    `finish_reason="tool_calls"`; text responses set `finish_reason="stop"`.
    """

    name = "mock"

    def __init__(
        self,
        *,
        default_model: str = "mock-1",
        context_window: int = 8192,
        delta_delay_s: float = 0.0,
    ) -> None:
        self.default_model = default_model
        self._context_window = context_window
        self._responses: deque[_MockResponse] = deque()
        self._delta_delay_s = delta_delay_s
        self._embed_dim = 16
        self.calls: list[dict[str, Any]] = []

    # -- scripting ----------------------------------------------------

    def queue_text(
        self, text: str, *, deltas: list[str] | None = None, model: str | None = None
    ) -> MockLLMProvider:
        """Queue a plain-text response.

        If `deltas` is provided, stream yields those deltas in order; otherwise
        the whole text is one delta.
        """
        self._responses.append(
            _MockResponse(
                kind="text",
                text=text,
                deltas=deltas if deltas is not None else [text],
                model=model or self.default_model,
            )
        )
        return self

    def queue_tool_call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        id: str | None = None,
        model: str | None = None,
    ) -> MockLLMProvider:
        """Queue a tool-call response."""
        self._responses.append(
            _MockResponse(
                kind="tool",
                tool_call=ToolCall(
                    id=id or f"call_{uuid.uuid4().hex[:8]}", name=name, arguments=arguments or {}
                ),
                model=model or self.default_model,
            )
        )
        return self

    def queue_error(self, message: str = "mock error") -> MockLLMProvider:
        self._responses.append(_MockResponse(kind="error", error=message))
        return self

    def reset(self) -> None:
        self._responses.clear()
        self.calls.clear()

    def remaining(self) -> int:
        return len(self._responses)

    # -- Protocol -----------------------------------------------------

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[CompletionChunk]:
        self.calls.append(
            {
                "messages": [m.model_dump() for m in messages],
                "tools": [t.model_dump() for t in tools] if tools else None,
                "model": model or self.default_model,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream,
            }
        )

        if not self._responses:
            raise LLMAPIError("MockLLMProvider: no scripted responses left")

        resp = self._responses.popleft()
        return self._emit(resp, messages, model or self.default_model)

    async def _emit(
        self, resp: _MockResponse, messages: list[ChatMessage], model: str
    ) -> AsyncIterator[CompletionChunk]:
        if resp.kind == "error":
            yield CompletionChunk(type="error", error=resp.error or "mock error")
            _telemetry_record(
                provider=self.name,
                model=model,
                error_code="mock.scripted_error",
            )
            return

        prompt_tokens = self._estimate_tokens(messages)
        completion_text: str = ""

        if resp.kind == "text":
            for d in resp.deltas:
                if self._delta_delay_s:
                    await asyncio.sleep(self._delta_delay_s)
                yield CompletionChunk(type="delta", delta=d)
                completion_text += d
            completion_tokens = self._estimate_tokens_text(completion_text)
            yield CompletionChunk(
                type="done",
                finish_reason="stop",
                usage=Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=prompt_tokens + completion_tokens,
                ),
            )
            _telemetry_record(
                provider=self.name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                cost_usd=0.0,
            )
        elif resp.kind == "tool":
            assert resp.tool_call is not None
            yield CompletionChunk(type="tool_call", tool_call=resp.tool_call)
            yield CompletionChunk(
                type="done",
                finish_reason="tool_calls",
                usage=Usage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=0,
                    total_tokens=prompt_tokens,
                ),
            )
            _telemetry_record(
                provider=self.name,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                cost_usd=0.0,
            )

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        """Deterministic embeddings: hash → fixed-length float vector."""
        import hashlib

        vectors: list[list[float]] = []
        for t in texts:
            h = hashlib.sha256(t.encode("utf-8")).digest()
            vec = [((h[i % len(h)]) / 255.0) * 2 - 1 for i in range(self._embed_dim)]
            vectors.append(vec)
        return vectors

    def supports_tools(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def context_window(self, model: str) -> int:
        return self._context_window

    async def estimate_cost(
        self, messages: list[ChatMessage], *, model: str | None = None
    ) -> CostEstimate:
        tokens = self._estimate_tokens(messages)
        return CostEstimate(
            usd=0.0,
            input_tokens=tokens,
            output_tokens=None,
            model=model or self.default_model,
            provider=self.name,
        )

    # -- helpers ------------------------------------------------------

    @staticmethod
    def _estimate_tokens_text(text: str) -> int:
        # Cheap approximation: 4 chars ≈ 1 token.
        return max(1, len(text) // 4)

    def _estimate_tokens(self, messages: list[ChatMessage]) -> int:
        return sum(self._estimate_tokens_text(m.text() or "") for m in messages) + 3 * len(messages)


class _MockResponse:
    __slots__ = ("deltas", "error", "kind", "model", "text", "tool_call")

    def __init__(
        self,
        *,
        kind: str,
        text: str | None = None,
        deltas: list[str] | None = None,
        tool_call: ToolCall | None = None,
        error: str | None = None,
        model: str | None = None,
    ) -> None:
        self.kind = kind
        self.text = text
        self.deltas = deltas or []
        self.tool_call = tool_call
        self.error = error
        self.model = model
