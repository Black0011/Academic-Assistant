"""Integration test for the EvolverAgent's runner hook.

P9.4 — the auto-fire gate has been narrowed: a successful run *without*
a bundle change no longer auto-drafts a proposal even when
``evolver_enabled=True``. Pure heuristic proposals are now created on
demand via ``POST /api/proposals:synthesize`` (covered separately in
``test_app_proposals_synthesize.py``).

What this file still validates:

1. ``evolver_enabled=True`` AND no bundle change ⇒ **no** proposal is
   created. The auto-fire path is now reserved for runs that produced
   a bundle change (covered in ``test_app_proposals_apply_to_bundle.py``).
2. ``evolver_enabled=False`` ⇒ no proposal is created (unchanged from
   pre-P9.4 default).
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.memory import MemoryBundle
from backend.proposals.store import InMemoryProposalStore
from backend.settings import Settings
from backend.tasks.queue import InMemoryTaskQueue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry


class _EvolverTestWorkflow(BaseWorkflow):
    """Workflow whose results match the template path in EvolverAgent."""

    name = "evolver_test"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        from backend.core.events import Event, EventType

        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        await ctx.emit(Event(EventType.TASK_END, data={"verdict": "ok"}))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={
                "section": "introduction",
                "word_count": 412,
                "citations": ["a"],
            },
            budget={"cost_usd": 0.001},
        )


def _build_app(*, evolver_enabled: bool):
    reg = WorkflowRegistry()
    reg.register(_EvolverTestWorkflow)
    store = InMemoryTaskStore()
    proposals = InMemoryProposalStore()
    deps = RunnerDeps(
        store=store,
        workflows=reg,
        memory=MemoryBundle.in_memory(),
        llm=MockLLMProvider(),
        proposals=proposals,
        evolver_enabled=evolver_enabled,
    )
    queue = InMemoryTaskQueue(deps)
    state = AppState(
        # Settings has many alias-keyed fields; mypy can't see aliases.
        settings=Settings(),  # type: ignore[call-arg]
        memory=deps.memory,
        llm=deps.llm,
        workflows=reg,
        task_store=store,
        task_queue=queue,
        proposals=proposals,
    )
    return create_app(state=state), store, queue, proposals


async def _wait_terminal(http: AsyncClient, task_id: str, *, max_wait: float = 2.0) -> dict:
    elapsed = 0.0
    while elapsed < max_wait:
        resp = await http.get(f"/api/tasks/{task_id}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in {"ok", "error", "cancelled"}:
            return body
        await asyncio.sleep(0.02)
        elapsed += 0.02
    raise AssertionError(f"task {task_id} did not terminate in {max_wait}s")


@pytest.mark.asyncio
async def test_runner_skips_proposal_for_non_bundle_run_even_when_evolver_enabled() -> None:
    """P9.4 — auto-fire is now gated to bundle changes only.

    Before P9.4 this test asserted that ``evolver_enabled=True`` would
    auto-create one proposal per successful run; that behaviour
    generated proposal noise that interfered with day-to-day usage. The
    new gate only auto-drafts when the runner actually wrote into a
    bundle (covered in ``test_app_proposals_apply_to_bundle.py``).
    """

    app, store, queue, proposals = _build_app(evolver_enabled=True)
    await store.init()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        try:
            resp = await http.post(
                "/api/tasks",
                json={"workflow": "evolver_test", "query": "draft intro section"},
            )
            assert resp.status_code == 202
            tid = resp.json()["task_id"]

            await queue.drain()
            final = await _wait_terminal(http, tid)
            assert final["status"] == "ok"

            # No automatic proposal — synthesize endpoint is the only
            # way to turn a non-bundle run into a heuristic proposal.
            assert await proposals.list_all() == []
        finally:
            await queue.close()


@pytest.mark.asyncio
async def test_runner_skips_evolver_when_disabled() -> None:
    app, store, queue, proposals = _build_app(evolver_enabled=False)
    await store.init()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        try:
            resp = await http.post(
                "/api/tasks",
                json={"workflow": "evolver_test", "query": "draft intro section"},
            )
            tid = resp.json()["task_id"]
            await queue.drain()
            final = await _wait_terminal(http, tid)
            assert final["status"] == "ok"

            assert await proposals.list_all() == []
        finally:
            await queue.close()
