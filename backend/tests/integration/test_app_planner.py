"""Integration tests for ``/api/planner`` (M8.2).

We boot a minimal :class:`AppState` with the in-memory primitives:
``MemoryBundle.in_memory()``, the default ``ToolRegistry``, the
``WorkflowRegistry`` discovery (which auto-registers our new ``dag``
workflow), an in-memory ``TaskStore`` + ``TaskQueue``, and a scripted
mock LLM. This is enough to drive ``compile -> validate -> execute``
end-to-end without touching the network.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory.base import MemoryBundle
from backend.settings import Settings
from backend.tasks.queue import build_task_queue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.tools.registry import build_default_registry as build_tools
from backend.workflows.registry import build_default_registry as build_workflows

_VALID_PLAN_JSON = """
{
  "rationale": "search arxiv, summarise",
  "nodes": [
    {"id": "a", "kind": "memory.read", "args": {"query": "transformers"}},
    {"id": "b", "kind": "llm", "depends_on": ["a"], "description": "summarise"}
  ]
}
"""


@pytest.fixture
async def app_state() -> AsyncIterator[AppState]:
    settings = Settings()  # type: ignore[call-arg]
    bundle = MemoryBundle.in_memory()
    tools = build_tools()
    workflows = build_workflows()
    llm = MockLLMProvider()
    # First call: compile (returns plan JSON). Second call: the LLM node inside dag exec.
    llm.queue_text(_VALID_PLAN_JSON.strip())
    llm.queue_text("final summary")
    task_store = InMemoryTaskStore()
    runner_deps = RunnerDeps(
        store=task_store,
        workflows=workflows,
        memory=bundle,
        llm=llm,
        tools=tools,
        skill_host=None,
        settings=settings,
    )
    queue = await build_task_queue("inmemory", deps=runner_deps, redis_url="")
    state = AppState(
        settings=settings,
        memory=bundle,
        llm=llm,
        tools=tools,
        workflows=workflows,
        task_store=task_store,
        task_queue=queue,
    )
    try:
        yield state
    finally:
        await queue.close()


@pytest.fixture
async def client(app_state: AppState) -> AsyncIterator[AsyncClient]:
    app = create_app(state=app_state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


async def test_skills_for_compile_returns_catalogue(client: AsyncClient) -> None:
    resp = await client.get("/api/planner/skills_for_compile")
    assert resp.status_code == 200
    body = resp.json()
    assert "skills" in body and "tools" in body
    tool_names = {t["name"] for t in body["tools"]}
    assert "arxiv__search" in tool_names


async def test_compile_returns_plan_with_nodes(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/planner/compile",
        json={"query": "transformers"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "transformers"
    assert len(body["nodes"]) >= 1


async def test_validate_rejects_cycle(client: AsyncClient) -> None:
    bad_plan = {
        "plan_id": "x",
        "query": "x",
        "nodes": [
            {"id": "a", "kind": "llm", "depends_on": ["b"], "description": "x"},
            {"id": "b", "kind": "llm", "depends_on": ["a"], "description": "x"},
        ],
    }
    resp = await client.post("/api/planner/validate", json={"plan": bad_plan})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert any("cycle" in err for err in body["errors"])


async def test_execute_enqueues_dag_task(client: AsyncClient, app_state: AppState) -> None:
    plan_dict = json.loads(_VALID_PLAN_JSON)
    plan_dict.update({"plan_id": "p1", "query": "transformers", "nodes": plan_dict["nodes"]})
    resp = await client.post(
        "/api/planner/execute",
        json={"plan": plan_dict, "params": {}},
    )
    assert resp.status_code == 202, resp.text
    body = resp.json()
    task_id = body["task_id"]
    assert body["workflow"] == "dag"
    assert body["plan_id"] == "p1"

    # Wait for the in-memory queue to finish the task.
    for _ in range(50):
        record = await app_state.task_store.get(task_id)  # type: ignore[union-attr]
        if record is not None and record.is_terminal:
            break
        await asyncio.sleep(0.05)
    assert record is not None and record.status == "ok", record


async def test_execute_rejects_invalid_plan(client: AsyncClient) -> None:
    bad_plan = {
        "plan_id": "x",
        "query": "x",
        "nodes": [
            {"id": "a", "kind": "llm", "depends_on": ["a"], "description": "self-loop"},
        ],
    }
    resp = await client.post(
        "/api/planner/execute",
        json={"plan": bad_plan, "params": {}},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["error"] == "plan failed validation"
