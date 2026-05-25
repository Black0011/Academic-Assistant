import pytest

from backend.core.errors import LLMAPIError
from backend.core.llm import ChatMessage, MockLLMProvider, collect_text


@pytest.mark.asyncio
async def test_queue_text_deltas_in_order():
    mock = MockLLMProvider()
    mock.queue_text("abc", deltas=["a", "b", "c"])
    chunks = []
    async for c in await mock.complete([ChatMessage(role="user", content="hi")]):
        chunks.append(c)
    delta_chunks = [c for c in chunks if c.type == "delta"]
    assert [c.delta for c in delta_chunks] == ["a", "b", "c"]
    assert chunks[-1].type == "done"
    assert chunks[-1].finish_reason == "stop"


@pytest.mark.asyncio
async def test_queue_tool_call():
    mock = MockLLMProvider()
    mock.queue_tool_call("search", {"q": "llm"})
    chunks = []
    async for c in await mock.complete([ChatMessage(role="user", content="hi")]):
        chunks.append(c)
    assert chunks[0].type == "tool_call"
    assert chunks[0].tool_call is not None
    assert chunks[0].tool_call.name == "search"
    assert chunks[0].tool_call.arguments == {"q": "llm"}
    assert chunks[-1].finish_reason == "tool_calls"


@pytest.mark.asyncio
async def test_queue_error_yields_error_chunk():
    mock = MockLLMProvider().queue_error("boom")
    chunks = []
    async for c in await mock.complete([ChatMessage(role="user", content="x")]):
        chunks.append(c)
    assert len(chunks) == 1
    assert chunks[0].type == "error"
    assert chunks[0].error == "boom"


@pytest.mark.asyncio
async def test_raises_when_queue_empty():
    mock = MockLLMProvider()
    with pytest.raises(LLMAPIError):
        await mock.complete([ChatMessage(role="user", content="x")])


@pytest.mark.asyncio
async def test_records_calls_for_assertions():
    mock = MockLLMProvider()
    mock.queue_text("ok")
    await collect_text(await mock.complete([ChatMessage(role="user", content="hi")]))
    assert len(mock.calls) == 1
    assert mock.calls[0]["messages"][0]["content"] == "hi"


@pytest.mark.asyncio
async def test_embed_deterministic_and_shape():
    mock = MockLLMProvider()
    v1 = await mock.embed(["hello"])
    v2 = await mock.embed(["hello", "world"])
    assert len(v1) == 1
    assert len(v2) == 2
    assert v1[0] == v2[0]  # deterministic
    assert len(v1[0]) == 16
