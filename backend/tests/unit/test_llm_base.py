import pytest

from backend.core.errors import LLMStreamError
from backend.core.llm import (
    ChatMessage,
    CompletionChunk,
    MockLLMProvider,
    TextPart,
    ToolCall,
    Usage,
    collect_text,
)
from backend.core.llm.base import ImagePart


def test_chat_message_text_from_string():
    m = ChatMessage(role="user", content="hi")
    assert m.text() == "hi"


def test_chat_message_text_from_parts():
    m = ChatMessage(
        role="user",
        content=[TextPart(text="Hello "), TextPart(text="world"), ImagePart(url="x://")],
    )
    assert m.text() == "Hello world"


def test_protocol_runtime_check():
    from backend.core.llm.base import LLMProvider

    assert isinstance(MockLLMProvider(), LLMProvider)


def test_chunk_roundtrip():
    c = CompletionChunk(type="tool_call", tool_call=ToolCall(id="1", name="f", arguments={"x": 1}))
    data = c.model_dump()
    assert CompletionChunk(**data) == c


@pytest.mark.asyncio
async def test_collect_text_aggregates():
    mock = MockLLMProvider()
    mock.queue_text("Hello world", deltas=["Hello ", "world"])
    stream = await mock.complete([ChatMessage(role="user", content="hi")])
    text, tool_calls, usage = await collect_text(stream)
    assert text == "Hello world"
    assert tool_calls == []
    assert isinstance(usage, Usage)


@pytest.mark.asyncio
async def test_collect_text_raises_on_error_chunk():
    mock = MockLLMProvider().queue_error("bad")
    stream = await mock.complete([ChatMessage(role="user", content="x")])
    with pytest.raises(LLMStreamError):
        await collect_text(stream)
