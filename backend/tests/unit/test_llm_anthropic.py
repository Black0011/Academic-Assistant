"""Unit tests for AnthropicProvider using httpx MockTransport."""

from __future__ import annotations

import json

import httpx
import pytest

from backend.core.errors import LLMAPIError, LLMAuthError, LLMRateLimit
from backend.core.llm import AnthropicProvider, ChatMessage, ToolCall, ToolSpec, collect_text


def _mk_provider(handler) -> AnthropicProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(
        base_url="https://api.anthropic.com/v1",
        transport=transport,
        headers={"x-api-key": "test", "anthropic-version": "2023-06-01"},
    )
    return AnthropicProvider(
        api_key="test",
        base_url="https://api.anthropic.com/v1",
        default_model="claude-3-5-sonnet-latest",
        client=client,
    )


def _sse(*events: tuple[str, dict]) -> bytes:
    lines: list[str] = []
    for etype, data in events:
        lines.append(f"event: {etype}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_stream_text_deltas_and_system_message_split():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/messages"
        body = json.loads(request.content)
        captured.update(body)
        content = _sse(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 5, "output_tokens": 0}},
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hel"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "lo"},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"input_tokens": 5, "output_tokens": 2},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider = _mk_provider(handler)
    text, _, usage = await collect_text(
        await provider.complete(
            [
                ChatMessage(role="system", content="You are helpful."),
                ChatMessage(role="user", content="hi"),
            ]
        )
    )
    assert text == "Hello"
    # system is lifted into top-level `system`, not a chat message
    assert "system" in captured
    assert captured["system"] == "You are helpful."
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert usage is not None
    assert usage.prompt_tokens == 5
    assert usage.completion_tokens == 2
    await provider.aclose()


@pytest.mark.asyncio
async def test_stream_tool_use_reassembly():
    def handler(request: httpx.Request) -> httpx.Response:
        content = _sse(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 4, "output_tokens": 0}},
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "search",
                        "input": {},
                    },
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"q":'},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '"llm"}'},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"input_tokens": 4, "output_tokens": 0},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider = _mk_provider(handler)
    text, tool_calls, _ = await collect_text(
        await provider.complete([ChatMessage(role="user", content="hi")])
    )
    assert text == ""
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "search"
    assert tool_calls[0].arguments == {"q": "llm"}
    await provider.aclose()


@pytest.mark.asyncio
async def test_tool_result_encodes_as_user_message():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = _sse(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 1, "output_tokens": 0}},
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text", "text": ""},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "done"},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider = _mk_provider(handler)
    messages = [
        ChatMessage(role="user", content="find papers"),
        ChatMessage(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="toolu_1", name="search", arguments={"q": "llm"})],
        ),
        ChatMessage(role="tool", tool_call_id="toolu_1", content="found 3 papers"),
    ]
    await collect_text(await provider.complete(messages))
    # The tool role was converted into a user message with tool_result content
    user_tool_msg = captured["messages"][-1]
    assert user_tool_msg["role"] == "user"
    assert user_tool_msg["content"][0]["type"] == "tool_result"
    assert user_tool_msg["content"][0]["tool_use_id"] == "toolu_1"
    await provider.aclose()


@pytest.mark.asyncio
async def test_tool_spec_sent_with_input_schema():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = _sse(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {"usage": {"input_tokens": 1, "output_tokens": 0}},
                },
            ),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"input_tokens": 1, "output_tokens": 0},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )
        return httpx.Response(200, content=content, headers={"content-type": "text/event-stream"})

    provider = _mk_provider(handler)
    tools = [
        ToolSpec(
            name="search",
            description="Find papers",
            parameters={"type": "object", "properties": {}},
        )
    ]
    await collect_text(
        await provider.complete([ChatMessage(role="user", content="hi")], tools=tools)
    )
    assert captured["tools"][0]["name"] == "search"
    assert "input_schema" in captured["tools"][0]
    await provider.aclose()


@pytest.mark.asyncio
async def test_auth_and_rate_limit_mapping():
    def handler_auth(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"type": "authentication_error"}})

    provider = _mk_provider(handler_auth)
    with pytest.raises(LLMAuthError):
        async for _ in await provider.complete([ChatMessage(role="user", content="hi")]):
            pass
    await provider.aclose()

    def handler_rl(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, json={"error": {"type": "rate_limit"}}, headers={"retry-after": "2"}
        )

    provider2 = _mk_provider(handler_rl)
    with pytest.raises(LLMRateLimit) as ei:
        async for _ in await provider2.complete([ChatMessage(role="user", content="hi")]):
            pass
    assert ei.value.retry_after_s == 2.0
    await provider2.aclose()


@pytest.mark.asyncio
async def test_embed_raises():
    provider = AnthropicProvider(api_key="x", base_url="https://x")
    with pytest.raises(LLMAPIError):
        await provider.embed(["hello"])
    await provider.aclose()
