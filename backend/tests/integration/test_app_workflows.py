"""Integration tests for the workflow execution endpoints."""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.settings import Settings
from backend.tools.base import BaseTool, ToolResult
from backend.tools.registry import ToolRegistry


class _FakeArxiv(BaseTool):
    name = "arxiv__search"
    description = "fake arxiv"
    requires_network = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={
                "count": 1,
                "results": [
                    {
                        "paper_id": "zzz999",
                        "arxiv_id": "2401.99999",
                        "entry_id": "http://arxiv.org/abs/2401.99999",
                        "title": "Integration Test Paper",
                        "authors": ["IT Author"],
                        "year": 2024,
                        "summary": "An abstract",
                        "pdf_url": "https://example.test/1.pdf",
                        "categories": ["cs.AI"],
                    }
                ],
            },
        )


class _FakePdf(BaseTool):
    name = "pdf__parse"
    description = "fake pdf"
    requires_network = False

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data={
                "source": {"mode": "url", "url": arguments.get("url", "")},
                "num_pages": 1,
                "pages_extracted": 1,
                "pages": ["body"],
                "text": "body",
            },
        )


def _make_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(_FakeArxiv())
    reg.register(_FakePdf())
    return reg


@pytest.fixture
async def app_state():
    mock = MockLLMProvider()
    mock.queue_text("demo answer", deltas=["demo ", "answer"])
    return AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=mock,
        tools=_make_tool_registry(),
    )


@pytest.fixture
async def client(app_state):
    app = create_app(state=app_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_unknown_workflow_returns_404(client):
    r = await client.post("/api/workflows/nonexistent/run", json={"query": "hi"})
    assert r.status_code == 404
    assert "not found" in r.json()["detail"]


async def test_run_demo_workflow_returns_answer(client, app_state):
    r = await client.post(
        "/api/workflows/demo/run",
        json={"query": "hello world"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "ok"
    assert body["task_id"]
    assert "demo answer" in (body["results"] or "")
    # Trace should include start + end at minimum.
    types = {e["type"] for e in body["events"]}
    assert "task.start" in types
    assert "task.end" in types


async def test_run_invalid_payload_returns_422(client):
    r = await client.post("/api/workflows/demo/run", json={})
    assert r.status_code == 422


async def test_stream_emits_sse_events(client, app_state):
    # Queue a fresh response so the mock LLM doesn't run empty on the
    # second workflow run.
    app_state.llm.queue_text("streamed answer", deltas=["streamed ", "answer"])
    async with client.stream(
        "POST",
        "/api/workflows/demo/stream",
        json={"query": "stream me"},
    ) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        events: list[dict] = []
        async for line in resp.aiter_lines():
            if line.startswith("data:"):
                payload = line[len("data:") :].strip()
                if payload:
                    events.append(json.loads(payload))
    types = [e["type"] for e in events]
    assert types[0] == "task.start"
    assert types[-1] == "task.end"
    assert any(t == "task.stage_start" for t in types)


async def test_run_research_workflow(client, app_state):
    # Evolver needs a few canned replies; keep them empty JSON.
    for _ in range(4):
        app_state.llm.queue_text("{}")
    r = await client.post(
        "/api/workflows/research/run",
        json={"query": "test topic"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["verdict"] == "ok"
    assert body["results"]["count"] == 1
    assert body["results"]["papers"][0]["paper_id"] == "zzz999"
    types = {e["type"] for e in body["events"]}
    assert "skill.call" in types
    assert "skill.result" in types
    assert "memory.write" in types
