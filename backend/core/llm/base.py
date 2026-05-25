"""LLM provider Protocol and canonical data shapes.

Every adapter (OpenAI-compatible, Anthropic, Ollama, Mock, …) must satisfy
the `LLMProvider` Protocol. Data passed across the adapter boundary uses the
Pydantic models here — never vendor-native dicts.

Contract frozen by rule aaf-llm-provider.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import (
    Any,
    Literal,
    Protocol,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Message / content parts
# ---------------------------------------------------------------------------


class TextPart(BaseModel):
    type: Literal["text"] = "text"
    text: str


class ImagePart(BaseModel):
    type: Literal["image"] = "image"
    url: str
    mime_type: str | None = None


ContentPart = TextPart | ImagePart


class ToolCall(BaseModel):
    """One function/tool invocation requested by the model."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ChatMessage(BaseModel):
    """A single turn in a chat. Canonical across providers."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[ContentPart] = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None
    reasoning_content: str | None = None

    def text(self) -> str:
        """Return the plain-text content, concatenating text parts if needed."""
        if isinstance(self.content, str):
            return self.content
        return "".join(p.text for p in self.content if isinstance(p, TextPart))


# ---------------------------------------------------------------------------
# Tool specs
# ---------------------------------------------------------------------------


class ToolSpec(BaseModel):
    """A callable tool exposed to the LLM."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any] = Field(default_factory=lambda: {"type": "object", "properties": {}})


# ---------------------------------------------------------------------------
# Streaming chunks
# ---------------------------------------------------------------------------


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class CompletionChunk(BaseModel):
    """One event in a streaming completion."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["delta", "tool_call", "done", "error"]
    delta: str | None = None
    tool_call: ToolCall | None = None
    finish_reason: str | None = None
    usage: Usage | None = None
    error: str | None = None
    reasoning_content: str | None = None


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------


class CostEstimate(BaseModel):
    usd: float
    input_tokens: int
    output_tokens: int | None = None
    model: str
    provider: str


# ---------------------------------------------------------------------------
# Provider Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class LLMProvider(Protocol):
    """Every LLM adapter must implement this Protocol.

    Attributes
    ----------
    name : short identifier used in the registry ("openai", "anthropic", ...)
    """

    name: str

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
        """Run a chat completion. Always returns an async iterator.

        When `stream=False`, implementations SHOULD still return one or more
        `delta` chunks followed by a `done` chunk — callers always iterate.
        """
        ...

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Return one embedding vector per input text."""
        ...

    def supports_tools(self) -> bool: ...

    def supports_streaming(self) -> bool: ...

    def context_window(self, model: str) -> int:
        """Return the max total tokens for the given model (best-effort)."""
        ...

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate: ...


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def collect_text(
    stream: AsyncIterator[CompletionChunk],
) -> tuple[str, list[ToolCall], Usage | None, str | None]:
    """Consume a completion stream and return (full_text, tool_calls, usage, reasoning_content).

    Utility for callers that don't need streaming — always safe.
    reasoning_content is the model's internal reasoning (used by DeepSeek V4).
    """
    text_parts: list[str] = []
    tool_calls: list[ToolCall] = []
    usage: Usage | None = None
    reasoning: str | None = None
    async for chunk in stream:
        if chunk.type == "delta" and chunk.delta:
            text_parts.append(chunk.delta)
        elif chunk.type == "tool_call" and chunk.tool_call:
            tool_calls.append(chunk.tool_call)
        elif chunk.type == "done":
            usage = chunk.usage
            reasoning = chunk.reasoning_content
        elif chunk.type == "error":
            from backend.core.errors import LLMStreamError
            raise LLMStreamError(chunk.error or "unknown stream error")
    return "".join(text_parts), tool_calls, usage, reasoning


__all__ = [
    "ChatMessage",
    "CompletionChunk",
    "ContentPart",
    "CostEstimate",
    "ImagePart",
    "LLMProvider",
    "TextPart",
    "ToolCall",
    "ToolSpec",
    "Usage",
    "collect_text",
]
