"""Integration tests for /api/v1/models/* endpoints.

Boots a minimal FastAPI app, runs a couple of LLM calls (one default,
one route-tagged), then asserts the breakdown shows both buckets.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.base import ChatMessage, collect_text
from backend.core.llm.mock import MockLLMProvider
from backend.core.llm.router import (
    RouteSpec,
    RoutingLLMProvider,
    RoutingPolicy,
)
from backend.core.llm.telemetry import recorder
from backend.memory import MemoryBundle
from backend.settings import Settings
from backend.tools.registry import ToolRegistry


@pytest.fixture
def fresh_telemetry():
    recorder().reset()
    yield
    recorder().reset()


@pytest.fixture
async def routing_app_state():
    default_p = MockLLMProvider(default_model="cheap")
    reasoning_p = MockLLMProvider(default_model="strong")
    router = RoutingLLMProvider(
        default=default_p,
        routes={"reasoning": reasoning_p},
        policy=RoutingPolicy(default=RouteSpec(provider="mock", model="cheap")),
    )
    return (
        AppState(
            settings=Settings(),
            memory=MemoryBundle.in_memory(),
            llm=router,
            tools=ToolRegistry(),
        ),
        default_p,
        reasoning_p,
    )


@pytest.fixture
async def client(routing_app_state):
    state, _, _ = routing_app_state
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_models_routes_returns_routing_metadata(client, routing_app_state, fresh_telemetry):
    r = await client.get("/api/v1/models/routes")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["enabled"] is True
    assert body["default_provider"] == "mock"
    assert body["routes"] == ["reasoning"]


async def test_models_usage_groups_records_by_route(client, routing_app_state, fresh_telemetry):
    state, default_p, reasoning_p = routing_app_state
    default_p.queue_text("default-resp")
    reasoning_p.queue_text("reasoning-resp")

    # Default path (no route tag).
    await collect_text(await state.llm.complete([ChatMessage(role="user", content="x")]))
    # Reasoning path (route tag = "reasoning").
    await collect_text(
        await state.llm.for_route("reasoning").complete([ChatMessage(role="user", content="y")])
    )

    r = await client.get("/api/v1/models/usage")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["sample_size"] == 2
    breakdown = body["breakdown"]

    routes_seen = {(b["model"], b["route"]) for b in breakdown}
    assert ("cheap", None) in routes_seen
    assert ("strong", "reasoning") in routes_seen

    totals = body["totals"]
    assert int(totals["calls"]) == 2


async def test_models_usage_filter_by_route(client, routing_app_state, fresh_telemetry):
    state, default_p, reasoning_p = routing_app_state
    default_p.queue_text("d1")
    reasoning_p.queue_text("r1")

    await collect_text(await state.llm.complete([ChatMessage(role="user", content="x")]))
    await collect_text(
        await state.llm.for_route("reasoning").complete([ChatMessage(role="user", content="y")])
    )

    r = await client.get("/api/v1/models/usage?route=reasoning")
    assert r.status_code == 200
    body = r.json()
    assert body["sample_size"] == 1
    assert all(b["route"] == "reasoning" for b in body["breakdown"])

    r2 = await client.get("/api/v1/models/usage?route=none")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["sample_size"] == 1
    assert all(b["route"] is None for b in body2["breakdown"])


async def test_models_routes_when_no_router_wired(fresh_telemetry):
    """A plain (non-router) provider should report enabled=False."""

    state = AppState(
        settings=Settings(),
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(default_model="single"),
        tools=ToolRegistry(),
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        r = await c.get("/api/v1/models/routes")
        assert r.status_code == 200
        body = r.json()
        assert body["enabled"] is False
        assert body["default_provider"] == "mock"
        assert body["routes"] == []
