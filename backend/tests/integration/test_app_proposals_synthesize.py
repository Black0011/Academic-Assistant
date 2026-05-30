"""Integration tests for ``POST /api/proposals:synthesize`` (P9.4).

The endpoint is the manual replacement for the pre-P9 "auto-draft on
every successful run" loop. It reads up to N recent successful task
records (optionally filtered by workflow) and asks the EvolverAgent
to synthesize a single heuristic proposal across them.

Scenarios covered here:

1. *Happy path*: with two ``ok`` task records seeded into the store,
   synthesize returns a proposal tagged ``self-evolution`` +
   ``synthesis``, listing both task ids in ``extras.task_ids``.
2. *Workflow filter*: ``workflow=revision`` only considers revision
   runs even when a research run was the most recent.
3. *No data*: 404 when no ``ok`` runs match the filter.
4. *Evolver not wired*: 503 when ``runner_deps`` has no evolver
   (proposals store missing).
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.proposals.store import InMemoryProposalStore
from backend.settings import Settings
from backend.tasks.models import TaskRecord
from backend.tasks.queue import InMemoryTaskQueue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.registry import WorkflowRegistry


async def _build(*, with_proposals: bool = True):
    reg = WorkflowRegistry()
    task_store = InMemoryTaskStore()
    await task_store.init()
    proposals = InMemoryProposalStore() if with_proposals else None
    llm = MockLLMProvider()
    deps = RunnerDeps(
        store=task_store,
        workflows=reg,
        llm=llm,
        proposals=proposals,
        evolver_enabled=False,  # P9.4 — synth works even when auto-fire is off
    )
    queue = InMemoryTaskQueue(deps)
    state = AppState(
        settings=Settings(),  # type: ignore[call-arg]
        llm=llm,
        workflows=reg,
        task_store=task_store,
        task_queue=queue,
        proposals=proposals,
        runner_deps=deps,
    )
    app = create_app(state=state)
    return app, task_store, proposals


async def _seed_ok_task(store: InMemoryTaskStore, *, workflow: str, query: str, tid: str) -> None:
    rec = TaskRecord(id=tid, workflow=workflow, query=query)
    await store.create(rec)
    await store.mark_started(tid)
    await store.mark_completed(
        tid,
        status="ok",
        result={"section": "intro", "word_count": 200},
        budget={"cost_usd": 0.001},
    )


@pytest.mark.asyncio
async def test_synthesize_happy_path_uses_recent_runs() -> None:
    app, task_store, proposals = await _build()
    await _seed_ok_task(task_store, workflow="revision", query="tighten intro", tid="t1")
    await _seed_ok_task(task_store, workflow="write", query="draft methods", tid="t2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.post(
            "/api/proposals:synthesize",
            json={"max_cases": 5},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()

        assert body["status"] == "draft"
        assert body["proposer_kind"] == "agent"
        assert "self-evolution" in body["tags"]
        assert "synthesis" in body["tags"]
        # extras carry which tasks fed the synthesis
        extras = body["extras"]
        assert extras["synthesis"] is True
        assert set(extras["task_ids"]) == {"t1", "t2"}
        assert sorted(extras["workflows"]) == ["revision", "write"]

    # Proposal persisted in the store
    assert proposals is not None
    persisted = await proposals.list_all()
    assert len(persisted) == 1
    assert persisted[0].proposal_id == body["proposal_id"]


@pytest.mark.asyncio
async def test_synthesize_workflow_filter() -> None:
    app, task_store, _proposals = await _build()
    await _seed_ok_task(task_store, workflow="research", query="agent memory", tid="r1")
    await _seed_ok_task(task_store, workflow="revision", query="tighten claims", tid="rev1")
    await _seed_ok_task(task_store, workflow="revision", query="add citation", tid="rev2")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.post(
            "/api/proposals:synthesize",
            json={"workflow": "revision", "max_cases": 10},
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        extras = body["extras"]
        # research run must be excluded
        assert set(extras["task_ids"]) == {"rev1", "rev2"}
        assert extras["workflows"] == ["revision"]


@pytest.mark.asyncio
async def test_synthesize_404_when_no_matching_runs() -> None:
    app, _task_store, _proposals = await _build()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.post(
            "/api/proposals:synthesize",
            json={"workflow": "revision", "max_cases": 5},
        )
        assert resp.status_code == 404
        assert "no successful runs" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_synthesize_503_when_evolver_not_wired() -> None:
    # Building without a proposal store leaves RunnerDeps.evolver = None
    # which is the trigger for the 503.
    app, task_store, _ = await _build(with_proposals=False)
    await _seed_ok_task(task_store, workflow="revision", query="x", tid="t1")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        resp = await http.post(
            "/api/proposals:synthesize",
            json={"max_cases": 5},
        )
        # Either the proposals store guard fires (503 "proposals subsystem
        # not ready") OR the evolver guard fires (503 "evolver agent not
        # wired"). Both signal an incomplete server config to the caller,
        # which is what we want.
        assert resp.status_code == 503
        assert "ready" in resp.json()["detail"] or "wired" in resp.json()["detail"]
