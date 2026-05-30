"""OpenAI-compatible provider.

Works with OpenAI, Azure OpenAI, Ollama (OpenAI-compat mode), DeepSeek,
Moonshot, SiliconFlow, vLLM, TogetherAI, Groq, local llama.cpp servers, ...
— anything that speaks `/v1/chat/completions` + `/v1/embeddings`.

Uses raw `httpx.AsyncClient` so tests can inject a MockTransport.
No dependency on the `openai` SDK.

Tool-call schema: OpenAI function-calling spec v2 (tools[].function.*).
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import tenacity

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

# Common model → context-window mapping; fall back to 8192 when unknown.
_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1-preview": 128_000,
    "o1-mini": 128_000,
    "deepseek-chat": 64_000,
    "deepseek-reasoner": 64_000,
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
    "moonshot-v1-8k": 8_192,
    "moonshot-v1-32k": 32_768,
    "moonshot-v1-128k": 131_072,
    "llama3.1:8b": 128_000,
    "llama3.1:70b": 128_000,
}


class OpenAICompatProvider:
    """OpenAI-protocol provider over raw httpx."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        default_model: str = "gpt-4o-mini",
        timeout_s: float = 120.0,
        verify_ssl: bool = True,
        client: httpx.AsyncClient | None = None,
        name: str = "openai",
    ) -> None:
        if not api_key and name not in {"ollama", "vllm", "local"}:
            pass
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model
        self._timeout_s = timeout_s
        self.name = name
        # Some providers (notably DeepSeek) fingerprint Python's TLS
        # differently from curl and trigger anti-bot SSL timeouts.
        # ``verify_ssl=False`` lets those providers work when the user
        # opts in via config. Default stays ``True`` — never silently
        # degrade security.
        _verify = True
        if not verify_ssl:
            _verify = False
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(retries=0),
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_s, connect=min(30.0, timeout_s)),
            verify=_verify,
            http2=False,  # httpx HTTP/2 negotiation hangs on some Windows+provider combos
            headers={
                "Authorization": f"Bearer {api_key}" if api_key else "",
            },
        )
        self._owns_client = client is None
        # P10 — embed-endpoint circuit breaker.
        # DeepSeek (and several other OpenAI-compat backends) does not
        # implement ``/embeddings``. Hammering a non-existent endpoint
        # keeps producing 404s at best and connection-pool corruption
        # at worst (we've seen ``BrokenPipeError`` propagate from the
        # second call onwards). Once we observe an unrecoverable signal
        # — 404, repeated transport failures, or BrokenPipe — we lock
        # the provider into "embeddings unsupported" mode for the rest
        # of its lifetime. ``embed`` then returns ``[]`` immediately
        # and callers fall back to keyword scoring.
        self._embed_disabled: bool = False
        self._embed_disabled_reason: str = ""
        self._embed_failure_streak: int = 0

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
        stream: bool = False,  # P17: streaming broken on Windows+DeepSeek, use non-streaming
    ) -> AsyncIterator[CompletionChunk]:
        body: dict[str, Any] = {
            "model": model or self._default_model,
            "messages": [self._encode_message(m) for m in messages],
            "temperature": temperature,
            "stream": stream,
        }
        body["max_tokens"] = max_tokens or 8192
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters or {"type": "object", "properties": {}},
                    },
                }
                for t in tools
            ]

        return self._stream_completion(body)

    # P10 — open the breaker after this many consecutive transport-level
    # failures (network errors, broken pipes, etc). 404 / 405 trip the
    # breaker on the very first response.
    _EMBED_FAILURE_THRESHOLD = 2

    @property
    def embeddings_supported(self) -> bool:
        """False once the breaker has tripped (no more network calls)."""
        return not self._embed_disabled

    @property
    def embeddings_disabled_reason(self) -> str:
        """Human-readable reason if the breaker has tripped, else ''."""
        return self._embed_disabled_reason

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        if self._embed_disabled:
            # Breaker open — short-circuit. Returning ``[]`` matches the
            # contract used by every embedder in the framework when the
            # backend is offline (vector_store falls back to keyword
            # scoring). Crucially: zero network, so we cannot corrupt
            # the connection pool or surface a BrokenPipe.
            return []
        body = {"model": model or "text-embedding-3-small", "input": texts}
        try:
            response = await _with_retry(self._client.post, "/embeddings", json=body)
        except (LLMAPIError, LLMTimeout) as exc:
            self._embed_failure_streak += 1
            if self._embed_failure_streak >= self._EMBED_FAILURE_THRESHOLD:
                self._trip_embed_breaker(
                    f"transport failures ({self._embed_failure_streak}x): {exc}"
                )
            raise
        if response.status_code in (404, 405):
            # Endpoint isn't implemented by this provider. No point
            # ever calling it again on this client lifetime.
            self._trip_embed_breaker(
                f"/embeddings returned {response.status_code} — provider has no embeddings endpoint"
            )
            return []
        _raise_for_status(response)
        # Successful round-trip — reset streak so transient hiccups
        # don't accumulate forever.
        self._embed_failure_streak = 0
        data = response.json()
        return [item["embedding"] for item in data["data"]]

    def _trip_embed_breaker(self, reason: str) -> None:
        if self._embed_disabled:
            return
        self._embed_disabled = True
        self._embed_disabled_reason = reason
        # Use module-level structlog logger via lazy import to avoid an
        # import-time dep at file top.
        import structlog

        structlog.get_logger(__name__).warning(
            "openai_compat.embed.disabled",
            provider=self.name,
            base_url=self._base_url,
            reason=reason,
        )

    def supports_tools(self) -> bool:
        return True

    def supports_streaming(self) -> bool:
        return True

    def context_window(self, model: str) -> int:
        return _CONTEXT_WINDOWS.get(model, 8192)

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        tokens = _approx_tokens(messages)
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
            # non-streaming fallback — single delta emission
            response = await _with_retry(self._client.post, "/chat/completions", json=body)
            _raise_for_status(response)
            data = response.json()
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or None
            if content:
                yield CompletionChunk(type="delta", delta=content)
            for tc in message.get("tool_calls") or []:
                yield CompletionChunk(type="tool_call", tool_call=_decode_tool_call(tc))
            done_usage = _decode_usage(data.get("usage"))
            yield CompletionChunk(
                type="done",
                finish_reason=choice.get("finish_reason") or "stop",
                usage=done_usage,
                reasoning_content=reasoning,
            )
            _finalise_telemetry(self.name, model, done_usage, start)
            return

        # Streaming path — parse SSE "data: {...}" lines
        pending_tool_calls: dict[int, dict[str, Any]] = {}
        usage: Usage | None = None
        finish_reason: str | None = None
        reasoning_content: str | None = None

        try:
            async with self._client.stream("POST", "/chat/completions", json=body) as response:
                _raise_for_status(response)
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data: "):
                        continue
                    payload = line[6:].strip()
                    if payload == "[DONE]":
                        break
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    choice = (event.get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}

                    content = delta.get("content")
                    if content:
                        yield CompletionChunk(type="delta", delta=content)

                    rc = delta.get("reasoning_content")
                    if rc:
                        reasoning_content = (reasoning_content or "") + rc

                    for tc_delta in delta.get("tool_calls") or []:
                        idx = tc_delta.get("index", 0)
                        slot = pending_tool_calls.setdefault(
                            idx,
                            {"id": tc_delta.get("id", f"call_{idx}"), "name": "", "arguments": ""},
                        )
                        if tc_delta.get("id"):
                            slot["id"] = tc_delta["id"]
                        fn = tc_delta.get("function") or {}
                        if fn.get("name"):
                            slot["name"] += fn["name"]
                        if fn.get("arguments"):
                            slot["arguments"] += fn["arguments"]

                    if choice.get("finish_reason"):
                        finish_reason = choice["finish_reason"]

                    if event.get("usage"):
                        usage = _decode_usage(event["usage"])
        except httpx.TimeoutException as e:
            raise LLMTimeout("openai-compat timeout", provider=self.name) from e
        except httpx.HTTPError as e:
            raise LLMStreamError(f"openai-compat stream error: {e}", provider=self.name) from e
        except OSError as e:
            # httpx/httpcore sometimes lets a raw socket error bubble up
            # (notably ``BrokenPipeError``) instead of wrapping it in
            # ``httpx.WriteError``. Treat them like any other transport
            # failure so the caller sees a typed ``LLMStreamError`` (which
            # the workflow then surfaces with retry hints) rather than the
            # opaque ``[Errno 32] Broken pipe`` text.
            raise LLMStreamError(
                f"openai-compat transport error: {type(e).__name__}: {e}",
                provider=self.name,
            ) from e

        # Emit aggregated tool calls
        for slot in pending_tool_calls.values():
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["arguments"]}
            yield CompletionChunk(
                type="tool_call",
                tool_call=ToolCall(id=slot["id"], name=slot["name"] or "unnamed", arguments=args),
            )

        yield CompletionChunk(type="done", finish_reason=finish_reason or "stop", usage=usage, reasoning_content=reasoning_content)
        _finalise_telemetry(self.name, model, usage, start)

    # ---- encoding helpers --------------------------------------------

    def _encode_message(self, m: ChatMessage) -> dict[str, Any]:
        encoded: dict[str, Any] = {"role": m.role}
        if isinstance(m.content, str):
            encoded["content"] = m.content
        else:
            parts: list[dict[str, Any]] = []
            for p in m.content:
                if p.type == "text":
                    parts.append({"type": "text", "text": p.text})
                elif p.type == "image":
                    parts.append({"type": "image_url", "image_url": {"url": p.url}})
            encoded["content"] = parts
        if m.role == "assistant":
            encoded["reasoning_content"] = m.reasoning_content or ""
        if m.tool_calls:
            encoded["tool_calls"] = [
                {
                    "id": tc.get("id", "") if isinstance(tc, dict) else getattr(tc, "id", ""),
                    "type": "function",
                    "function": {
                        "name": tc["name"] if isinstance(tc, dict) else getattr(tc, "name", ""),
                        "arguments": json.dumps(tc["arguments"] if isinstance(tc, dict) else getattr(tc, "arguments", {})),
                    },
                }
                for tc in m.tool_calls
            ]
        if m.tool_call_id is not None:
            encoded["tool_call_id"] = m.tool_call_id
        if m.name is not None:
            encoded["name"] = m.name
        return encoded


def _approx_tokens(messages: list[ChatMessage]) -> int:
    total = 0
    for m in messages:
        total += max(1, len(m.text()) // 4) + 3
    return total


def _decode_usage(d: dict[str, Any] | None) -> Usage | None:
    if not d:
        return None
    return Usage(
        prompt_tokens=int(d.get("prompt_tokens", 0)),
        completion_tokens=int(d.get("completion_tokens", 0)),
        total_tokens=int(d.get("total_tokens", 0)),
    )


def _decode_tool_call(raw: dict[str, Any]) -> ToolCall:
    fn = raw.get("function") or {}
    args_raw = fn.get("arguments") or "{}"
    try:
        args = json.loads(args_raw) if isinstance(args_raw, str) else dict(args_raw)
    except json.JSONDecodeError:
        args = {"_raw": args_raw}
    return ToolCall(id=raw.get("id", "call_0"), name=fn.get("name", "unnamed"), arguments=args)


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
    if status == 400 and "context length" in body_text.lower():
        raise LLMContextWindowError("context window exceeded", **context)
    if status in (408, 504):
        raise LLMTimeout(f"upstream timeout ({status})", **context)
    # Include last 500 chars of request body for debugging
    req_body = context.get("_request_body", "")
    req_snippet = req_body[-500:] if req_body else ""
    raise LLMAPIError(
        f"api error ({status}) body={body_text[:200]!r}", **context
    )


async def _with_retry(fn: Any, *args: Any, **kwargs: Any) -> httpx.Response:
    """Retry transient transport errors only. API-level errors bubble up
    through `_raise_for_status` and are re-raised after the retry decision."""

    @tenacity.retry(
        retry=tenacity.retry_if_exception_type((httpx.TimeoutException, httpx.TransportError)),
        wait=tenacity.wait_exponential_jitter(initial=1, max=10),
        stop=tenacity.stop_after_attempt(3),
        reraise=True,
    )
    async def _do() -> httpx.Response:
        return await fn(*args, **kwargs)

    try:
        return await _do()
    except httpx.TimeoutException as e:
        raise LLMTimeout(str(e) or "timeout") from e
    except httpx.TransportError as e:
        raise LLMAPIError(str(e) or "transport error") from e
    except OSError as e:
        # Raw socket errors that escaped httpx's wrappers — keep the same
        # typed-error contract so callers don't see ``[Errno 32] Broken pipe``.
        raise LLMAPIError(f"{type(e).__name__}: {e}") from e


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


__all__ = ["OpenAICompatProvider"]
