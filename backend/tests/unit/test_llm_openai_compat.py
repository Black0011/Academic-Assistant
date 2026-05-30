"""Unit tests for OpenAICompatProvider using httpx MockTransport.

No real network; every response is scripted.
"""

from __future__ import annotations

import json

import httpx
import pytest

from backend.core.errors import (
    LLMAPIError,
    LLMAuthError,
    LLMContextWindowError,
    LLMRateLimit,
    LLMStreamError,
)
from backend.core.llm import ChatMessage, OpenAICompatProvider, ToolSpec, collect_text
from backend.core.llm.telemetry import recorder


def _mk_provider(handler) -> OpenAICompatProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        base_url="https://api.example.com/v1",
        transport=transport,
        headers={"Authorization": "Bearer test"},
    )
    return OpenAICompatProvider(
        api_key="test",
        base_url="https://api.example.com/v1",
        default_model="gpt-4o-mini",
        client=client,
        name="openai",
    )


def _sse(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_stream_text_deltas():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        body = json.loads(request.content)
        assert body["messages"][0]["content"] == "hi"
        assert body["stream"] is True
        content = _sse(
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":2,"total_tokens":5}}',
            "data: [DONE]",
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider = _mk_provider(handler)
    text, tool_calls, usage = await collect_text(
        await provider.complete([ChatMessage(role="user", content="hi")])
    )
    assert text == "Hello"
    assert tool_calls == []
    assert usage is not None
    assert usage.total_tokens == 5
    await provider.aclose()


@pytest.mark.asyncio
async def test_stream_tool_call_reassembly():
    def handler(request: httpx.Request) -> httpx.Response:
        content = _sse(
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"id":"call_1","function":{"name":"sea"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"name":"rch"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"{\\"q\\":"}}]}}]}',
            'data: {"choices":[{"delta":{"tool_calls":[{"index":0,"function":{"arguments":"\\"x\\"}"}}]}}]}',
            'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}],"usage":{"prompt_tokens":5,"completion_tokens":0,"total_tokens":5}}',
            "data: [DONE]",
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider = _mk_provider(handler)
    text, tool_calls, _ = await collect_text(
        await provider.complete([ChatMessage(role="user", content="hi")])
    )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "search"
    assert tool_calls[0].arguments == {"q": "x"}
    await provider.aclose()


@pytest.mark.asyncio
async def test_non_streaming_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": "Hello",
                            "tool_calls": [],
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
            },
        )

    provider = _mk_provider(handler)
    text, _, usage = await collect_text(
        await provider.complete([ChatMessage(role="user", content="hi")], stream=False)
    )
    assert text == "Hello"
    assert usage is not None and usage.prompt_tokens == 3
    await provider.aclose()


@pytest.mark.asyncio
async def test_auth_error_mapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    provider = _mk_provider(handler)
    with pytest.raises(LLMAuthError):
        async for _ in await provider.complete([ChatMessage(role="user", content="hi")]):
            pass
    await provider.aclose()


@pytest.mark.asyncio
async def test_rate_limit_with_retry_after():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"message": "slow"}}, headers={"retry-after": "3"}
        )

    provider = _mk_provider(handler)
    with pytest.raises(LLMRateLimit) as ei:
        async for _ in await provider.complete([ChatMessage(role="user", content="hi")]):
            pass
    assert ei.value.retry_after_s == 3.0
    await provider.aclose()


@pytest.mark.asyncio
async def test_context_window_error_mapped():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={"error": {"message": "This model's maximum context length is 8192"}},
        )

    provider = _mk_provider(handler)
    with pytest.raises(LLMContextWindowError):
        async for _ in await provider.complete([ChatMessage(role="user", content="hi")]):
            pass
    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embeddings"
        body = json.loads(request.content)
        assert body["input"] == ["a", "b"]
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.1, 0.2]},
                    {"embedding": [0.3, 0.4]},
                ]
            },
        )

    provider = _mk_provider(handler)
    vectors = await provider.embed(["a", "b"])
    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    await provider.aclose()


@pytest.mark.asyncio
async def test_tool_spec_sent_in_request():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            content=_sse(
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":2,"completion_tokens":1,"total_tokens":3}}',
                "data: [DONE]",
            ),
            headers={"content-type": "text/event-stream"},
        )

    provider = _mk_provider(handler)
    tools = [
        ToolSpec(
            name="search",
            description="Search papers",
            parameters={"type": "object", "properties": {"q": {"type": "string"}}},
        )
    ]
    await collect_text(
        await provider.complete([ChatMessage(role="user", content="hi")], tools=tools)
    )
    assert captured["tools"][0]["function"]["name"] == "search"
    assert captured["tools"][0]["function"]["parameters"]["properties"] == {"q": {"type": "string"}}
    await provider.aclose()


@pytest.mark.asyncio
async def test_telemetry_records_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=_sse(
                'data: {"choices":[{"delta":{"content":"ok"}}]}',
                'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}',
                "data: [DONE]",
            ),
            headers={"content-type": "text/event-stream"},
        )

    provider = _mk_provider(handler)
    await collect_text(await provider.complete([ChatMessage(role="user", content="hi")]))
    recs = recorder().records()
    assert len(recs) == 1
    r = recs[0]
    assert r.provider == "openai"
    assert r.prompt_tokens == 3
    assert r.completion_tokens == 1
    # gpt-4o-mini known in prices.yaml → cost should be computed
    assert r.cost_usd is not None
    await provider.aclose()


def test_context_window_lookup():
    provider = OpenAICompatProvider(api_key="k", base_url="http://x", default_model="m")
    assert provider.context_window("gpt-4o") == 128_000
    assert provider.context_window("unknown-model") == 8192


# ---------------------------------------------------------------------------
# P9.0 — raw socket errors must be wrapped into the typed LLM* exceptions
# instead of leaking up as bare ``[Errno 32] Broken pipe``.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_streaming_wraps_broken_pipe_into_llm_stream_error():
    def handler(request: httpx.Request) -> httpx.Response:
        # MockTransport raising OSError bypasses httpx's own error wrappers
        # — this is the exact shape that escaped to the user as
        # ``[Errno 32] Broken pipe`` before P9.0.
        raise BrokenPipeError(32, "Broken pipe")

    provider = _mk_provider(handler)
    with pytest.raises(LLMStreamError) as ei:
        async for _ in await provider.complete([ChatMessage(role="user", content="hi")]):
            pass
    assert "BrokenPipeError" in str(ei.value)
    await provider.aclose()


@pytest.mark.asyncio
async def test_non_streaming_wraps_broken_pipe_into_llm_api_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise BrokenPipeError(32, "Broken pipe")

    provider = _mk_provider(handler)
    with pytest.raises((LLMAPIError, LLMStreamError)) as ei:
        async for _ in await provider.complete(
            [ChatMessage(role="user", content="hi")],
            stream=False,
        ):
            pass
    # Either path must preserve the original exception type in the message
    assert "BrokenPipeError" in str(ei.value) or "Broken pipe" in str(ei.value)
    await provider.aclose()


# ---------------------------------------------------------------------------
# P10 — embed circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_404_trips_breaker_and_subsequent_calls_short_circuit():
    """DeepSeek-style provider: ``/embeddings`` returns 404 → breaker
    trips on the very first response and every later call returns ``[]``
    without touching the network. Prevents the BrokenPipeError storm
    we saw in the wild on revision/research recall."""

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(404, json={"error": "not found"})

    provider = _mk_provider(handler)
    assert provider.embeddings_supported is True

    out = await provider.embed(["hello"])
    assert out == []
    assert provider.embeddings_supported is False
    assert "404" in provider.embeddings_disabled_reason
    assert call_count["n"] == 1

    # Second call must NOT touch the network — that's the whole point.
    out2 = await provider.embed(["world"])
    assert out2 == []
    assert call_count["n"] == 1

    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_repeated_broken_pipe_trips_breaker():
    """Two consecutive transport-level failures (BrokenPipe via OSError)
    open the breaker so we stop hammering a dead pool."""

    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        raise BrokenPipeError(32, "Broken pipe")

    provider = _mk_provider(handler)

    with pytest.raises(LLMAPIError):
        await provider.embed(["x"])
    assert provider.embeddings_supported is True  # one strike, not yet

    with pytest.raises(LLMAPIError):
        await provider.embed(["y"])
    assert provider.embeddings_supported is False
    assert "transport" in provider.embeddings_disabled_reason

    # Third call short-circuits — no third network attempt.
    out = await provider.embed(["z"])
    assert out == []
    assert call_count["n"] == 2

    await provider.aclose()


@pytest.mark.asyncio
async def test_embed_success_resets_failure_streak():
    """A successful round-trip should reset the streak, so transient
    hiccups don't accumulate across an entire process lifetime."""

    state = {"first": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if state["first"]:
            state["first"] = False
            raise BrokenPipeError(32, "Broken pipe")
        return httpx.Response(
            200,
            json={
                "data": [{"embedding": [0.1, 0.2, 0.3]}],
                "model": "x",
                "usage": {"prompt_tokens": 1, "total_tokens": 1},
            },
        )

    provider = _mk_provider(handler)

    with pytest.raises(LLMAPIError):
        await provider.embed(["a"])

    out = await provider.embed(["b"])
    assert out == [[0.1, 0.2, 0.3]]
    assert provider.embeddings_supported is True

    await provider.aclose()
