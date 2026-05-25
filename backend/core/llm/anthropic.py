"""Anthropic Messages API provider.

Uses raw httpx. No dependency on the `anthropic` SDK.
Handles Anthropic's quirks vs. OpenAI shape:

  1. System messages are NOT chat entries — they go into a top-level `system`
     field.
  2. Tool calls appear as `content[].type == "tool_use"` in assistant
     messages; tool results come back as `role=user` with
     `content[].type == "tool_result"` (NOT role=tool).
  3. Streaming uses named SSE events (`content_block_delta`, etc.) rather
     than `data-only` chunks.

Docs: https://docs.anthropic.com/en/api/messages-streaming
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from backend.core.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMContextWindowError,
    LLMRateLimit,
    LLMStreamError,
    LLMTimeout,
)

from .base import (
    ChatMessage,
    CompletionChunk,
    CostEstimate,
    ToolCall,
    ToolSpec,
    Usage,
)
from .telemetry import estimate_cost_usd, record

_CONTEXT_WINDOWS: dict[str, int] = {
    "claude-3-5-sonnet-latest": 200_000,
    "claude-3-5-haiku-latest": 200_000,
    "claude-3-opus-latest": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
}

_ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider:
    name = "anthropic"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.anthropic.com/v1",
        default_model: str = "claude-3-5-sonnet-latest",
        timeout_s: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_s = timeout_s
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(10.0, timeout_s)),
            headers={
                "x-api-key": api_key,
                "anthropic-version": _ANTHROPIC_VERSION,
                "content-type": "application/json",
            },
        )
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    # ---- Protocol ----------------------------------------------------

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
        system_text, encoded_messages = self._encode_messages(messages)
        body: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": encoded_messages,
            "max_tokens": max_tokens or 8192,
            "temperature": temperature,
            "stream": stream,
        }
        if system_text:
            body["system"] = system_text
        if tools:
            body["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters or {"type": "object", "properties": {}},
                }
                for t in tools
            ]
        return self._stream_completion(body)

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        # Anthropic does not expose an embedding endpoint. Callers should
        # use OpenAICompatProvider.embed or a local embedder.
        raise LLMAPIError(
            "anthropic has no embeddings endpoint; use another provider for embeddings"
        )

    def supports_tools(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def context_window(self, model: str) -> int:
        return _CONTEXT_WINDOWS.get(model, 200_000)

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        tokens = sum(max(1, len(m.text()) // 4) + 3 for m in messages)
        cost = (
            estimate_cost_usd(
                provider=self.name,
                model=model or self._default_model,
                prompt_tokens=tokens,
                completion_tokens=0,
            )
            or 0.0
        )
        return CostEstimate(
            usd=cost,
            input_tokens=tokens,
            output_tokens=None,
            model=model or self._default_model,
            provider=self.name,
        )

    # ---- streaming core ----------------------------------------------

    async def _stream_completion(self, body: dict[str, Any]) -> AsyncIterator[CompletionChunk]:
        stream = body.get("stream", True)
        model = body["model"]
        start = time.monotonic()

        if not stream:
            response = await self._client.post("/messages", json=body)
            _raise_for_status(response)
            data = response.json()
            for block in data.get("content") or []:
                if block.get("type") == "text":
                    text = block.get("text") or ""
                    if text:
                        yield CompletionChunk(type="delta", delta=text)
                elif block.get("type") == "tool_use":
                    yield CompletionChunk(
                        type="tool_call",
                        tool_call=ToolCall(
                            id=block.get("id", "toolu_0"),
                            name=block.get("name", "unnamed"),
                            arguments=block.get("input") or {},
                        ),
                    )
            done_usage = _decode_usage(data.get("usage"))
            yield CompletionChunk(
                type="done", finish_reason=data.get("stop_reason") or "stop", usage=done_usage
            )
            _finalise_telemetry(self.name, model, done_usage, start)
            return

        # Streaming SSE with named events
        tool_use_buffers: dict[int, dict[str, Any]] = {}
        usage: Usage | None = None
        stop_reason: str | None = None

        current_event: str | None = None

        try:
            async with self._client.stream("POST", "/messages", json=body) as response:
                _raise_for_status(response)
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        current_event = line[7:].strip()
                        continue
                    if not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if not payload:
                        continue
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    etype = current_event or event.get("type")
                    if etype == "content_block_start":
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            idx = event.get("index", 0)
                            tool_use_buffers[idx] = {
                                "id": block.get("id", f"toolu_{idx}"),
                                "name": block.get("name", "unnamed"),
                                "arguments_raw": "",
                            }
                    elif etype == "content_block_delta":
                        delta = event.get("delta") or {}
                        idx = event.get("index", 0)
                        if delta.get("type") == "text_delta":
                            text = delta.get("text") or ""
                            if text:
                                yield CompletionChunk(type="delta", delta=text)
                        elif delta.get("type") == "input_json_delta":
                            slot = tool_use_buffers.setdefault(
                                idx, {"id": f"toolu_{idx}", "name": "unnamed", "arguments_raw": ""}
                            )
                            slot["arguments_raw"] += delta.get("partial_json") or ""
                    elif etype == "message_delta":
                        delta = event.get("delta") or {}
                        if "stop_reason" in delta:
                            stop_reason = delta["stop_reason"]
                        if event.get("usage"):
                            # Anthropic sends output_tokens in message_delta, prompt in message_start
                            usage = _merge_usage(usage, event["usage"])
                    elif etype == "message_start":
                        msg = event.get("message") or {}
                        if msg.get("usage"):
                            usage = _merge_usage(usage, msg["usage"])
                    elif etype == "message_stop":
                        break
        except httpx.TimeoutException as e:
            raise LLMTimeout("anthropic timeout", provider=self.name) from e
        except httpx.HTTPError as e:
            raise LLMStreamError(f"anthropic stream error: {e}", provider=self.name) from e
        except OSError as e:
            raise LLMStreamError(
                f"anthropic transport error: {type(e).__name__}: {e}",
                provider=self.name,
            ) from e

        for slot in tool_use_buffers.values():
            try:
                args = json.loads(slot["arguments_raw"]) if slot["arguments_raw"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["arguments_raw"]}
            yield CompletionChunk(
                type="tool_call",
                tool_call=ToolCall(id=slot["id"], name=slot["name"], arguments=args),
            )

        yield CompletionChunk(
            type="done",
            finish_reason=_map_stop_reason(stop_reason),
            usage=usage,
        )
        _finalise_telemetry(self.name, model, usage, start)

    # ---- encoding helpers --------------------------------------------

    def _encode_messages(self, messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
        system_text_parts: list[str] = []
        out: list[dict[str, Any]] = []

        for m in messages:
            if m.role == "system":
                system_text_parts.append(m.text())
                continue

            if m.role == "tool":
                # Anthropic represents tool results as user message with
                # content[].type == "tool_result"
                out.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": m.tool_call_id or "",
                                "content": m.text(),
                            }
                        ],
                    }
                )
                continue

            # assistant with tool_calls → content with tool_use blocks
            if m.role == "assistant" and m.tool_calls:
                content: list[dict[str, Any]] = []
                text_part = m.text()
                if text_part:
                    content.append({"type": "text", "text": text_part})
                for tc in m.tool_calls:
                    content.append(
                        {
                            "type": "tool_use",
                            "id": tc.id,
                            "name": tc.name,
                            "input": tc.arguments,
                        }
                    )
                out.append({"role": "assistant", "content": content})
                continue

            # plain user/assistant with string content
            if isinstance(m.content, str):
                out.append({"role": m.role, "content": m.content})
            else:
                parts: list[dict[str, Any]] = []
                for p in m.content:
                    if p.type == "text":
                        parts.append({"type": "text", "text": p.text})
                    elif p.type == "image":
                        parts.append(
                            {
                                "type": "image",
                                "source": {
                                    "type": "url",
                                    "url": p.url,
                                },
                            }
                        )
                out.append({"role": m.role, "content": parts})

        return "\n\n".join(system_text_parts), out


def _decode_usage(d: dict[str, Any] | None) -> Usage | None:
    if not d:
        return None
    prompt = int(d.get("input_tokens", 0))
    completion = int(d.get("output_tokens", 0))
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _merge_usage(existing: Usage | None, incoming: dict[str, Any]) -> Usage:
    prompt = int(incoming.get("input_tokens", existing.prompt_tokens if existing else 0))
    completion = int(incoming.get("output_tokens", existing.completion_tokens if existing else 0))
    return Usage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
    )


def _map_stop_reason(reason: str | None) -> str:
    if reason == "end_turn":
        return "stop"
    if reason == "tool_use":
        return "tool_calls"
    if reason == "max_tokens":
        return "length"
    return reason or "stop"


def _raise_for_status(response: httpx.Response) -> None:
    status = response.status_code
    if 200 <= status < 300:
        return
    try:
        body_text: str = response.text
    except Exception:
        body_text = ""
    context: dict[str, Any] = {"status": status, "body": body_text[:500]}
    if status in (401, 403):
        raise LLMAuthError(f"auth error ({status})", **context)
    if status == 429:
        retry_after = response.headers.get("retry-after")
        retry_after_s = (
            float(retry_after)
            if retry_after and retry_after.replace(".", "", 1).isdigit()
            else None
        )
        raise LLMRateLimit(f"rate limited ({status})", retry_after_s=retry_after_s, **context)
    if status == 400 and ("context_length" in body_text.lower() or "too long" in body_text.lower()):
        raise LLMContextWindowError("context window exceeded", **context)
    if status in (408, 504):
        raise LLMTimeout(f"upstream timeout ({status})", **context)
    raise LLMAPIError(f"api error ({status})", **context)


def _finalise_telemetry(provider: str, model: str, usage: Usage | None, start: float) -> None:
    duration_ms = (time.monotonic() - start) * 1000.0
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0
    cost = estimate_cost_usd(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    record(
        provider=provider,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        duration_ms=duration_ms,
        cost_usd=cost,
    )


__all__ = ["AnthropicProvider"]
