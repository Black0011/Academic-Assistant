"""End-to-end HTTP test for the revision workflow.

Verifies the *full* path:

    POST /api/manuscripts (seed v1)
      -> POST /api/tasks {workflow: revision, input: {manuscript_id, text, comments}}
      -> queue.drain()
      -> GET /api/tasks/{id}             (terminal "ok")
      -> GET /api/manuscripts/{id}/versions  (auto-committed v2 with revision_workflow origin)

This locks in the contract between RevisionWorkflow's results, the runner's
``_maybe_commit_manuscript`` hook, and the manuscript subsystem — the seam
where M3 (workflows + tasks) meets M4 (manuscripts).
"""

from __future__ import annotations

import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.store import InMemoryManuscriptStore
from backend.memory import MemoryBundle
from backend.settings import Settings
from backend.tasks.queue import InMemoryTaskQueue
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.registry import WorkflowRegistry
from backend.workflows.revision import RevisionWorkflow


@pytest.fixture
async def client(tmp_path):
    reg = WorkflowRegistry()
    reg.register(RevisionWorkflow)

    task_store = InMemoryTaskStore()
    await task_store.init()

    ms_store = InMemoryManuscriptStore()
    await ms_store.init()

    memory = MemoryBundle.in_memory()
    llm = MockLLMProvider()  # template fallback inside revision workflow
    bundle_storage = BundleStorage(
        root=tmp_path / "manuscripts",
        max_file_bytes=2 * 1024 * 1024,
        max_bundle_bytes=8 * 1024 * 1024,
    )

    deps = RunnerDeps(
        store=task_store,
        workflows=reg,
        memory=memory,
        llm=llm,
        manuscripts=ms_store,
        bundle_storage=bundle_storage,
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
        bundle_storage=bundle_storage,
    )
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        try:
            yield c, queue
        finally:
            await queue.close()


async def _wait_terminal(http: AsyncClient, task_id: str, *, max_wait: float = 3.0) -> dict:
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


async def test_revision_workflow_auto_commits_new_manuscript_version(client):
    http, queue = client

    # Seed manuscript with v1
    create = await http.post(
        "/api/manuscripts",
        json={
            "title": "Method section",
            "content": "Our method works because it is fast.",
            "tags": ["draft"],
            "note": "seed",
        },
    )
    assert create.status_code == 201
    body = create.json()
    mid = body["manuscript"]["id"]
    assert body["manuscript"]["current_version"] == 1
    base_text = body["version"]["content"]

    # Kick off revision workflow
    task_resp = await http.post(
        "/api/tasks",
        json={
            "workflow": "revision",
            "query": "Tighten the prose and address reviewer comments",
            "input": {
                "manuscript_id": mid,
                "text": base_text,
                "section": "method",
                "comments": [
                    {"id": "c1", "category": "clarity", "text": "Define 'fast' precisely."},
                    {"id": "c2", "category": "scope", "text": "Compare with prior work."},
                ],
            },
        },
    )
    assert task_resp.status_code == 202
    tid = task_resp.json()["task_id"]

    await queue.drain()
    final = await _wait_terminal(http, tid)
    assert final["status"] == "ok", final

    # Workflow result must surface revised text + change_log
    result = final["result"]
    assert isinstance(result, dict)
    assert result["section"] == "method"
    assert isinstance(result["revised"], str) and result["revised"].strip()
    change_log = result["change_log"]
    assert {entry["comment_id"] for entry in change_log} >= {"c1", "c2"}

    # Manuscript should now expose a v2 produced by the revision workflow
    versions_resp = await http.get(f"/api/manuscripts/{mid}/versions")
    assert versions_resp.status_code == 200
    versions = versions_resp.json()["items"]
    assert [v["version"] for v in versions] == [2, 1]

    new_v = versions[0]
    assert new_v["origin"] == "revision_workflow"
    assert new_v["produced_by"] == tid
    assert new_v["content"].strip() == result["revised"].strip()
    # reviewer comments should be persisted alongside the version
    persisted_ids = sorted(c["id"] for c in (new_v.get("reviewer_comments") or []))
    assert persisted_ids == ["c1", "c2"]

    # current_version should bump on the manuscript header
    head = await http.get(f"/api/manuscripts/{mid}")
    assert head.status_code == 200
    assert head.json()["current_version"] == 2


async def test_revision_workflow_without_manuscript_id_does_not_commit(client):
    """Sanity check: revision is only auto-committed when a manuscript_id is provided."""
    http, queue = client

    seed = await http.post(
        "/api/manuscripts",
        json={"title": "Other", "content": "Some original prose.", "note": "seed"},
    )
    mid = seed.json()["manuscript"]["id"]

    task_resp = await http.post(
        "/api/tasks",
        json={
            "workflow": "revision",
            "query": "Polish",
            "input": {
                # NB: no manuscript_id
                "text": "Some original prose.",
                "comments": [{"id": "c1", "text": "Be concise."}],
            },
        },
    )
    assert task_resp.status_code == 202
    tid = task_resp.json()["task_id"]
    await queue.drain()
    final = await _wait_terminal(http, tid)
    assert final["status"] == "ok"

    # The seeded manuscript must remain at v1 — runner did NOT auto-commit
    versions = (await http.get(f"/api/manuscripts/{mid}/versions")).json()["items"]
    assert [v["version"] for v in versions] == [1]


# ---------------------------------------------------------------------------
# P8 Phase B — bundle-aware revision
# ---------------------------------------------------------------------------


async def _create_bundle_with_section(http: AsyncClient) -> tuple[str, str]:
    """Helper: create an empty bundle manuscript + seed a `intro.tex` file.

    Returns ``(manuscript_id, original_text)``.
    """
    create = await http.post(
        "/api/manuscripts",
        json={
            "title": "DataAgent eval",
            "kind": "paper",
            "layout": "bundle",
            "tags": ["bundle"],
        },
    )
    assert create.status_code == 201, create.text
    mid = create.json()["manuscript"]["id"]

    seed_text = "Our approach is fast. We measure throughput on one workload."
    write = await http.put(
        f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex",
        json={"content": seed_text},
    )
    assert write.status_code == 200, write.text
    return mid, seed_text


async def test_revision_writes_back_to_bundle_target_file(client):
    http, queue = client
    mid, original = await _create_bundle_with_section(http)

    task_resp = await http.post(
        "/api/tasks",
        json={
            "workflow": "revision",
            "query": "Address reviewer comments on the intro",
            "input": {
                "manuscript_id": mid,
                "bundle_target": "overleaf/sections/intro.tex",
                # NB: no `text` — runner pre-reads from bundle
                "section": "intro",
                "comments": [
                    {"id": "c1", "category": "clarity", "text": "Define 'fast' precisely."},
                    {"id": "c2", "category": "scope", "text": "Compare with prior work."},
                ],
            },
        },
    )
    assert task_resp.status_code == 202
    tid = task_resp.json()["task_id"]

    await queue.drain()
    final = await _wait_terminal(http, tid)
    assert final["status"] == "ok", final

    result = final["result"]
    revised = result["revised"]
    assert isinstance(revised, str) and revised.strip()
    assert revised != original  # workflow actually rewrote it

    # The bundle file must now hold the revised text — written by the runner.
    fetched = await http.get(f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex")
    assert fetched.status_code == 200
    body = fetched.json()
    assert body["encoding"] == "utf-8"
    assert body["content"].strip() == revised.strip()

    # The other unrelated path (main.tex) must NOT exist (we never created it
    # and the runner must scope its writes to bundle_target only).
    other = await http.get(f"/api/manuscripts/{mid}/files/overleaf/main.tex")
    assert other.status_code == 404

    # Bundle manuscripts have no version chain; current_version stays 0.
    head = (await http.get(f"/api/manuscripts/{mid}")).json()
    assert head["layout"] == "bundle"
    assert head["current_version"] == 0


async def test_revision_on_bundle_without_target_is_a_safe_noop(client):
    """If bundle_target is missing the runner skips persistence — task still ok."""
    http, queue = client
    mid, original = await _create_bundle_with_section(http)

    task_resp = await http.post(
        "/api/tasks",
        json={
            "workflow": "revision",
            "query": "Polish without picking a file",
            "input": {
                "manuscript_id": mid,
                "text": original,  # explicit text, no bundle_target
                "comments": [{"id": "c1", "text": "Be concise."}],
            },
        },
    )
    tid = task_resp.json()["task_id"]
    await queue.drain()
    final = await _wait_terminal(http, tid)
    assert final["status"] == "ok"

    # File must be untouched.
    fetched = await http.get(f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex")
    assert fetched.json()["content"] == original


async def test_revision_with_bad_bundle_target_fails_gracefully(client):
    """A path-traversal attempt in bundle_target must NOT write anywhere; the
    task itself must terminate cleanly (the runner swallows the read failure
    so the workflow runs on an empty `text`, hitting the validate stage)."""
    http, queue = client
    mid, original = await _create_bundle_with_section(http)

    task_resp = await http.post(
        "/api/tasks",
        json={
            "workflow": "revision",
            "input": {
                "manuscript_id": mid,
                "bundle_target": "../../etc/escape.tex",
                "comments": [{"id": "c1", "text": "Whatever."}],
            },
        },
    )
    tid = task_resp.json()["task_id"]
    await queue.drain()
    final = await _wait_terminal(http, tid)
    # Either workflow validation rejects empty text (verdict=error) or the
    # workflow runs on empty text and produces empty revised — both are
    # acceptable; the *important* invariant is that nothing escaped to disk.
    assert final["status"] in {"ok", "error"}

    # The original file is untouched.
    fetched = await http.get(f"/api/manuscripts/{mid}/files/overleaf/sections/intro.tex")
    assert fetched.json()["content"] == original
