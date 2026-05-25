"""End-to-end HTTP test for ``POST /api/proposals/{id}:apply-to-bundle``.

Exercises the full P8 Phase C2 chain:

    1. Create a *bundle* manuscript with a seed section file.
    2. Run a write workflow targeting that section file (auto-creates
       a bundle file via the runner).
    3. Confirm the EvolverAgent created a draft proposal carrying:
       - ``target_paths == [bundle_target]``
       - a non-empty unified diff in ``proposal.diff``
       - the ``bundle_target`` / ``bundle_after`` apply payload in
         ``extras``.
    4. Manually corrupt the file (simulate "user edited locally"),
       then call ``apply-to-bundle`` with no ``force`` and assert it's
       rejected with 409 (staleness check).
    5. Restore the file, call ``apply-to-bundle`` again — succeeds, the
       file now matches ``proposal.extras["bundle_after"]``, and
       ``proposal.status`` did *not* change (apply-to-bundle is
       intentionally orthogonal to the state machine).
    6. Negative: a non-bundle proposal cannot be applied to bundle
       (400). A linked-bundle manuscript with risk_level="high"
       proposal is refused (403).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.store import InMemoryManuscriptStore
from backend.memory import MemoryBundle
from backend.proposals.models import CreateProposalInput
from backend.proposals.store import InMemoryProposalStore
from backend.settings import Settings
from backend.tasks.queue import InMemoryTaskQueue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry


class _BundleWriteStub(BaseWorkflow):
    """Mimics the production write workflow's result shape — rich enough
    for the EvolverAgent to draft a proposal, simple enough to be
    deterministic across runs."""

    name = "write"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={
                "section": "intro",
                "markdown": "# Intro\n\nNew evolved prose.\n",
                "citations": ["a"],
                "word_count": 4,
            },
        )


@pytest.fixture
async def app_bundle(tmp_path):
    reg = WorkflowRegistry()
    reg.register(_BundleWriteStub)
    task_store = InMemoryTaskStore()
    await task_store.init()
    ms_store = InMemoryManuscriptStore()
    await ms_store.init()
    storage = BundleStorage(
        root=tmp_path / "manuscripts",
        max_file_bytes=1 * 1024 * 1024,
        max_bundle_bytes=4 * 1024 * 1024,
    )
    proposals = InMemoryProposalStore()
    memory = MemoryBundle.in_memory()
    llm = MockLLMProvider()

    deps = RunnerDeps(
        store=task_store,
        workflows=reg,
        memory=memory,
        llm=llm,
        manuscripts=ms_store,
        bundle_storage=storage,
        proposals=proposals,
        evolver_enabled=True,
    )
    queue = InMemoryTaskQueue(deps)
    state = AppState(
        settings=Settings(),
        memory=memory,
        llm=llm,
        workflows=reg,
        task_store=task_store,
        task_queue=queue,
        manuscripts=ms_store,
        bundle_storage=storage,
        proposals=proposals,
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        try:
            yield c, queue, ms_store, storage, proposals
        finally:
            await queue.close()


async def _wait_terminal(http: AsyncClient, tid: str, *, max_wait: float = 2.0) -> dict:
    elapsed = 0.0
    while elapsed < max_wait:
        resp = await http.get(f"/api/tasks/{tid}")
        assert resp.status_code == 200
        body = resp.json()
        if body["status"] in {"ok", "error", "cancelled"}:
            return body
        await asyncio.sleep(0.02)
        elapsed += 0.02
    raise AssertionError(f"task {tid} did not terminate in {max_wait}s")


async def _seed_bundle_with_intro(http: AsyncClient) -> str:
    create = await http.post(
        "/api/manuscripts",
        json={"title": "Bundle paper", "kind": "paper", "layout": "bundle"},
    )
    assert create.status_code == 201, create.text
    mid = create.json()["manuscript"]["id"]
    write = await http.put(
        f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex",
        json={"content": "Original prose.\n"},
    )
    assert write.status_code == 200, write.text
    return mid


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


async def test_full_chain_write_then_apply_to_bundle(app_bundle):
    http, queue, _ms_store, _storage, _proposals = app_bundle
    mid = await _seed_bundle_with_intro(http)

    # --- 1) Run a bundle write task; runner writes the section file
    #     and EvolverAgent drafts a proposal carrying the diff/extras.
    task = await http.post(
        "/api/tasks",
        json={
            "workflow": "write",
            "input": {
                "manuscript_id": mid,
                "bundle_target": "overleaf/sections/intro.tex",
            },
        },
    )
    tid = task.json()["task_id"]
    await queue.drain()
    final = await _wait_terminal(http, tid)
    assert final["status"] == "ok"

    # The runner wrote the file — file content matches workflow markdown.
    fetched = await http.get(f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex")
    assert fetched.json()["content"] == "# Intro\n\nNew evolved prose.\n"

    # The EvolverAgent created at least one draft proposal carrying the diff.
    proposals_resp = await http.get("/api/proposals")
    proposals_list = proposals_resp.json()["items"]
    bundle_proposals = [
        p for p in proposals_list if p["target_paths"] == ["overleaf/sections/intro.tex"]
    ]
    assert len(bundle_proposals) == 1
    proposal = bundle_proposals[0]
    assert proposal["status"] == "draft"
    assert "+New evolved prose." in proposal["diff"]
    assert proposal["extras"]["manuscript_id"] == mid
    assert proposal["extras"]["bundle_target"] == "overleaf/sections/intro.tex"
    assert proposal["extras"]["bundle_before"] == "Original prose.\n"
    assert proposal["extras"]["bundle_after"] == "# Intro\n\nNew evolved prose.\n"

    pid = proposal["proposal_id"]

    # --- 2) Simulate a local edit AFTER the proposal was drafted, then
    #     try to apply: the staleness check must reject.
    await http.put(
        f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex",
        json={"content": "User edited locally.\n"},
    )
    stale = await http.post(f"/api/proposals/{pid}:apply-to-bundle")
    assert stale.status_code == 409, stale.text

    # --- 3) Restore the original content, then apply succeeds.
    await http.put(
        f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex",
        json={"content": "Original prose.\n"},
    )
    applied = await http.post(f"/api/proposals/{pid}:apply-to-bundle")
    assert applied.status_code == 200, applied.text
    body = applied.json()
    # Status MUST stay "draft" — apply-to-bundle does not stamp the
    # state machine; that's the user-approved separation of concerns.
    assert body["status"] == "draft"
    assert "applied_to_bundle_at" in body["extras"]
    assert body["extras"]["applied_to_bundle_size"] == len(
        proposal["extras"]["bundle_after"].encode()
    )

    # File now matches the proposed `after`.
    final_file = await http.get(f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex")
    assert final_file.json()["content"] == proposal["extras"]["bundle_after"]


# ---------------------------------------------------------------------------
# Negative paths
# ---------------------------------------------------------------------------


async def test_apply_to_bundle_rejects_proposal_without_bundle_payload(app_bundle):
    """A handcrafted human proposal without bundle extras → 400."""
    http, _queue, _ms_store, _storage, proposals = app_bundle
    bare = await proposals.create(
        CreateProposalInput(title="manual heuristic", summary="just a note"),
        actor="tester",
    )
    resp = await http.post(f"/api/proposals/{bare.proposal_id}:apply-to-bundle")
    assert resp.status_code == 400
    assert "bundle_target" in resp.text or "bundle_after" in resp.text


async def test_apply_to_bundle_force_overrides_staleness(app_bundle):
    """When the file changed since the proposal was drafted, force=true
    must let admin overwrite anyway."""
    http, queue, _ms_store, _storage, _proposals = app_bundle
    mid = await _seed_bundle_with_intro(http)
    task = await http.post(
        "/api/tasks",
        json={
            "workflow": "write",
            "input": {
                "manuscript_id": mid,
                "bundle_target": "overleaf/sections/intro.tex",
            },
        },
    )
    tid = task.json()["task_id"]
    await queue.drain()
    await _wait_terminal(http, tid)

    proposals_list = (await http.get("/api/proposals")).json()["items"]
    pid = next(
        p["proposal_id"]
        for p in proposals_list
        if p["target_paths"] == ["overleaf/sections/intro.tex"]
    )

    # Edit the file out-of-band, then force.
    await http.put(
        f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex",
        json={"content": "User edited.\n"},
    )
    forced = await http.post(
        f"/api/proposals/{pid}:apply-to-bundle",
        json={"force": True},
    )
    assert forced.status_code == 200, forced.text
    final_file = await http.get(f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex")
    assert final_file.json()["content"] == "# Intro\n\nNew evolved prose.\n"


async def test_apply_to_bundle_rejects_high_risk_on_linked_manuscript(app_bundle, tmp_path):
    """Linked bundles must refuse anything but risk_level='low' (the
    framework will not auto-write into a user-managed external dir for
    higher-risk changes)."""
    http, _queue, _ms_store, _storage, proposals = app_bundle

    external = tmp_path / "external"
    await asyncio.to_thread(external.mkdir)
    await asyncio.to_thread((external / "intro.tex").write_text, "External owned.\n")

    create = await http.post(
        "/api/manuscripts",
        json={
            "title": "Linked",
            "kind": "paper",
            "layout": "bundle",
            "bundle_link_path": str(external),
        },
    )
    assert create.status_code == 201, create.text
    mid = create.json()["manuscript"]["id"]

    # Hand-build a high-risk proposal that targets a linked-manuscript file.
    risky = await proposals.create(
        CreateProposalInput(
            title="risky linked rewrite",
            summary="big change",
            risk_level="high",
            target_paths=["intro.tex"],
            extras={
                "manuscript_id": mid,
                "bundle_target": "intro.tex",
                "bundle_before": "External owned.\n",
                "bundle_after": "Auto-rewritten.\n",
            },
        ),
        actor="agent",
    )
    refused = await http.post(f"/api/proposals/{risky.proposal_id}:apply-to-bundle")
    assert refused.status_code == 403
    contents = await asyncio.to_thread((external / "intro.tex").read_text)
    assert contents == "External owned.\n"
