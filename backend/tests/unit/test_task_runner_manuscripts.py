"""Auto-commit manuscript versions on successful write/revision tasks."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.models import CreateManuscriptInput
from backend.manuscripts.store import InMemoryManuscriptStore
from backend.tasks.models import TaskRecord
from backend.tasks.runner import RunnerDeps, execute_task
from backend.tasks.store import InMemoryTaskStore
from backend.workflows.base import BaseWorkflow, WorkflowContext, WorkflowOutput
from backend.workflows.registry import WorkflowRegistry


class _WriteStub(BaseWorkflow):
    """Mimics the production write workflow's result shape."""

    name = "write"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={
                "section": "intro",
                "markdown": "# Intro\n\nGenerated body.",
                "citations": ["paperA", "paperB"],
                "word_count": 3,
            },
        )


class _RevisionStub(BaseWorkflow):
    name = "revision"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={
                "section": "intro",
                "revised": "## Revised text\n\nClearer prose.",
                "change_log": [{"comment_id": "c1", "decision": "addressed"}],
                "citations": ["paperA"],
            },
        )


class _NoopStub(BaseWorkflow):
    """A non-write/revision workflow — must NOT auto-commit anything."""

    name = "demo_noop"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(task_id=ctx.task_id, verdict="ok", results={"answer": 1})


class _ConsultStub(BaseWorkflow):
    """Echoes the pre-read ``input.text`` back out under ``analysis`` so
    we can assert the runner fed the file content into the workflow.

    Mirrors the production consult workflow's result shape (no
    ``revised`` / ``change_log`` — consult never writes back)."""

    name = "consult"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results={
                "section": ctx.input.get("section", ""),
                "original": ctx.input.get("text", ""),
                "analysis": f"Echo: {(ctx.input.get('text') or '')[:80]}",
                "suggestions": [],
                "citations": [],
                "papers": [],
            },
        )


async def _setup(workflow_cls):
    task_store = InMemoryTaskStore()
    await task_store.init()
    ms_store = InMemoryManuscriptStore()
    await ms_store.init()
    reg = WorkflowRegistry()
    reg.register(workflow_cls)
    deps = RunnerDeps(store=task_store, workflows=reg, manuscripts=ms_store)
    return task_store, ms_store, deps


async def test_write_task_auto_commits_new_version():
    task_store, ms_store, deps = await _setup(_WriteStub)
    manuscript, _ = await ms_store.create(CreateManuscriptInput(title="Paper"))

    rec = await task_store.create(
        TaskRecord(
            id="t-write",
            workflow="write",
            input={"manuscript_id": manuscript.id, "section": "intro"},
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None and final.status == "ok"

    versions = await ms_store.list_versions(manuscript.id)
    assert len(versions) == 1
    v = versions[0]
    assert v.version == 1
    assert "Generated body" in v.content
    assert v.origin == "write_workflow"
    assert v.produced_by == rec.id
    assert v.citations == ["paperA", "paperB"]


async def test_revision_task_auto_commits_with_reviewer_comments():
    task_store, ms_store, deps = await _setup(_RevisionStub)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Paper", content="initial body", note="seed")
    )

    rec = await task_store.create(
        TaskRecord(
            id="t-rev",
            workflow="revision",
            input={
                "manuscript_id": manuscript.id,
                "comments": [{"id": "c1", "category": "clarity", "text": "Sharpen this."}],
            },
        )
    )
    await execute_task(rec.id, deps)

    versions = await ms_store.list_versions(manuscript.id)
    assert [v.version for v in versions] == [2, 1]

    new_v = versions[0]
    assert new_v.origin == "revision_workflow"
    assert new_v.produced_by == rec.id
    assert "Revised text" in new_v.content
    assert new_v.reviewer_comments == [{"id": "c1", "category": "clarity", "text": "Sharpen this."}]


async def test_no_manuscript_id_means_no_commit():
    task_store, ms_store, deps = await _setup(_WriteStub)
    rec = await task_store.create(
        TaskRecord(id="t-x", workflow="write", input={"section": "intro"})
    )
    await execute_task(rec.id, deps)

    stats = await ms_store.stats()
    assert stats["total"] == 0
    assert stats["versions_total"] == 0


async def test_unknown_workflow_skips_commit():
    task_store, ms_store, deps = await _setup(_NoopStub)
    manuscript, _ = await ms_store.create(CreateManuscriptInput(title="P"))
    rec = await task_store.create(
        TaskRecord(
            id="t-noop",
            workflow="demo_noop",
            input={"manuscript_id": manuscript.id},
        )
    )
    await execute_task(rec.id, deps)

    versions = await ms_store.list_versions(manuscript.id)
    assert versions == []  # no auto-commit for unrecognized workflow


async def test_missing_manuscript_does_not_fail_task():
    task_store, _ms_store, deps = await _setup(_WriteStub)
    rec = await task_store.create(
        TaskRecord(
            id="t-missing",
            workflow="write",
            input={"manuscript_id": "ghost"},
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None
    # Hook failure must NOT bubble up — task stays ok.
    assert final.status == "ok"


# ---------------------------------------------------------------------------
# P8 Phase B — bundle-aware revision branch
# ---------------------------------------------------------------------------


async def _setup_with_bundle(workflow_cls, tmp_path: Path):
    task_store = InMemoryTaskStore()
    await task_store.init()
    ms_store = InMemoryManuscriptStore()
    await ms_store.init()
    storage = BundleStorage(
        root=tmp_path / "manuscripts",
        max_file_bytes=1 * 1024 * 1024,
        max_bundle_bytes=4 * 1024 * 1024,
    )
    reg = WorkflowRegistry()
    reg.register(workflow_cls)
    deps = RunnerDeps(
        store=task_store,
        workflows=reg,
        manuscripts=ms_store,
        bundle_storage=storage,
    )
    return task_store, ms_store, storage, deps


async def test_revision_writes_to_bundle_target_when_layout_is_bundle(tmp_path):
    task_store, ms_store, storage, deps = await _setup_with_bundle(_RevisionStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    # Seed an intro file directly through storage (this is what the user/UI does).
    await storage.write_text(manuscript, "overleaf/sections/intro.tex", "Original prose.")

    rec = await task_store.create(
        TaskRecord(
            id="t-bundle-rev",
            workflow="revision",
            input={
                "manuscript_id": manuscript.id,
                "bundle_target": "overleaf/sections/intro.tex",
                "comments": [{"id": "c1", "text": "Sharpen this."}],
            },
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None and final.status == "ok"

    # Bundle file content was rewritten to the workflow's `revised` output.
    written = await storage.read_text(manuscript, "overleaf/sections/intro.tex")
    assert "Revised text" in written

    # No version chain row was appended (bundles don't use it).
    versions = await ms_store.list_versions(manuscript.id)
    assert versions == []


async def test_revision_bundle_no_target_skips_write(tmp_path):
    """Bundle layout + no `bundle_target` ⇒ runner skips persistence cleanly."""
    task_store, ms_store, storage, deps = await _setup_with_bundle(_RevisionStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    await storage.write_text(manuscript, "overleaf/sections/intro.tex", "Untouched.")

    rec = await task_store.create(
        TaskRecord(
            id="t-bundle-no-target",
            workflow="revision",
            input={
                "manuscript_id": manuscript.id,
                # no bundle_target on purpose
                "comments": [{"id": "c1", "text": "Sharpen this."}],
            },
        )
    )
    await execute_task(rec.id, deps)
    assert (await task_store.get(rec.id)).status == "ok"

    # File untouched, no version chain entry.
    assert await storage.read_text(manuscript, "overleaf/sections/intro.tex") == "Untouched."
    assert (await ms_store.list_versions(manuscript.id)) == []


async def test_single_layout_revision_path_unchanged_with_bundle_storage_present(tmp_path):
    """Even with bundle_storage wired, single-layout manuscripts still take the
    legacy commit_version path. This protects pre-P7 callers from any
    accidental routing change."""
    task_store, ms_store, _storage, deps = await _setup_with_bundle(_RevisionStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Single doc", content="initial body", note="seed")
    )
    rec = await task_store.create(
        TaskRecord(
            id="t-single-rev",
            workflow="revision",
            input={
                "manuscript_id": manuscript.id,
                "comments": [{"id": "c1", "text": "Sharpen this."}],
            },
        )
    )
    await execute_task(rec.id, deps)

    versions = await ms_store.list_versions(manuscript.id)
    assert [v.version for v in versions] == [2, 1]
    assert "Revised text" in versions[0].content
    assert versions[0].origin == "revision_workflow"


# ---------------------------------------------------------------------------
# P8 Phase C1 — write workflow bundle target (+ optional main.tex registration)
# ---------------------------------------------------------------------------


async def test_write_to_bundle_target_and_register_in_main(tmp_path):
    task_store, ms_store, storage, deps = await _setup_with_bundle(_WriteStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    # Seed a main.tex that has a real \end{document} marker.
    main_tex_initial = (
        "\\documentclass{article}\n\\begin{document}\n\\input{sections/intro}\n\\end{document}\n"
    )
    await storage.write_text(manuscript, "overleaf/main.tex", main_tex_initial)

    rec = await task_store.create(
        TaskRecord(
            id="t-write-bundle",
            workflow="write",
            input={
                "manuscript_id": manuscript.id,
                "bundle_target": "overleaf/sections/related-work.tex",
                "register_in_main": True,
                "section": "related-work",
            },
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None and final.status == "ok"

    # Section file exists with the workflow's markdown body.
    written = await storage.read_text(manuscript, "overleaf/sections/related-work.tex")
    assert "Generated body" in written

    # main.tex now references the new section right above \end{document}.
    main_after = await storage.read_text(manuscript, "overleaf/main.tex")
    assert "\\input{sections/related-work}" in main_after
    # The pre-existing intro \input must remain.
    assert "\\input{sections/intro}" in main_after
    # No version chain entry was created.
    assert (await ms_store.list_versions(manuscript.id)) == []


async def test_write_to_bundle_register_in_main_off_by_default(tmp_path):
    task_store, ms_store, storage, deps = await _setup_with_bundle(_WriteStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    main_tex = "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"
    await storage.write_text(manuscript, "overleaf/main.tex", main_tex)

    rec = await task_store.create(
        TaskRecord(
            id="t-write-no-register",
            workflow="write",
            input={
                "manuscript_id": manuscript.id,
                "bundle_target": "overleaf/sections/related-work.tex",
                # register_in_main omitted ⇒ false
            },
        )
    )
    await execute_task(rec.id, deps)

    written = await storage.read_text(manuscript, "overleaf/sections/related-work.tex")
    assert "Generated body" in written
    main_after = await storage.read_text(manuscript, "overleaf/main.tex")
    assert "\\input{sections/related-work}" not in main_after  # untouched


async def test_write_to_bundle_register_in_main_is_idempotent(tmp_path):
    """Running the same write twice must not duplicate the \\input line."""
    task_store, ms_store, storage, deps = await _setup_with_bundle(_WriteStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    main_tex = "\\documentclass{article}\n\\begin{document}\n\\end{document}\n"
    await storage.write_text(manuscript, "overleaf/main.tex", main_tex)

    common_input = {
        "manuscript_id": manuscript.id,
        "bundle_target": "overleaf/sections/intro.tex",
        "register_in_main": True,
    }
    rec1 = await task_store.create(TaskRecord(id="t-w1", workflow="write", input=common_input))
    await execute_task(rec1.id, deps)
    rec2 = await task_store.create(TaskRecord(id="t-w2", workflow="write", input=common_input))
    await execute_task(rec2.id, deps)

    main_after = await storage.read_text(manuscript, "overleaf/main.tex")
    assert main_after.count("\\input{sections/intro}") == 1


async def test_write_to_bundle_without_target_skips_persist(tmp_path):
    task_store, ms_store, storage, deps = await _setup_with_bundle(_WriteStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )

    rec = await task_store.create(
        TaskRecord(
            id="t-write-no-target",
            workflow="write",
            input={"manuscript_id": manuscript.id},  # no bundle_target
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None and final.status == "ok"
    # Tree should be empty: we created no files.
    tree = await storage.list_tree(manuscript)
    assert tree.files == []


async def test_single_layout_write_path_unchanged_with_bundle_storage_present(tmp_path):
    task_store, ms_store, _storage, deps = await _setup_with_bundle(_WriteStub, tmp_path)
    manuscript, _ = await ms_store.create(CreateManuscriptInput(title="Single doc"))
    rec = await task_store.create(
        TaskRecord(
            id="t-single-write",
            workflow="write",
            input={"manuscript_id": manuscript.id, "section": "intro"},
        )
    )
    await execute_task(rec.id, deps)

    versions = await ms_store.list_versions(manuscript.id)
    assert [v.version for v in versions] == [1]
    assert "Generated body" in versions[0].content
    assert versions[0].origin == "write_workflow"


# ---------------------------------------------------------------------------
# P9.0 — friendly pre-read failure: when ``bundle_target`` points at a file
# that doesn't exist, the runner records a precise task error instead of
# silently falling through to the workflow body and producing
# ``revision workflow requires input.text``.
# ---------------------------------------------------------------------------


async def test_revision_bundle_preread_missing_file_surfaces_task_error(tmp_path):
    task_store, ms_store, _storage, deps = await _setup_with_bundle(_RevisionStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    # Note: do *not* seed the file — the pre-read will fail.

    rec = await task_store.create(
        TaskRecord(
            id="t-bundle-preread-miss",
            workflow="revision",
            input={
                "manuscript_id": manuscript.id,
                "bundle_target": "overleaf/sections/does-not-exist.tex",
                "comments": [{"id": "c1", "text": "n/a"}],
            },
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None
    assert final.status == "error"
    assert "bundle pre-read failed" in (final.error or "")
    assert "overleaf/sections/does-not-exist.tex" in (final.error or "")
    # The misleading "requires input.text" must NOT appear here.
    assert "requires input.text" not in (final.error or "")


# ---------------------------------------------------------------------------
# P11 — consult workflow joins the bundle-pre-read path but never writes back.
# ---------------------------------------------------------------------------


async def test_consult_bundle_preread_feeds_text_to_workflow(tmp_path):
    """When ``consult`` is dispatched with manuscript_id + bundle_target,
    the runner pre-reads the file into ``input.text`` — same shape as
    revision — so the workflow body doesn't need to talk to disk."""

    task_store, ms_store, storage, deps = await _setup_with_bundle(_ConsultStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )
    await storage.write_text(manuscript, "overleaf/sections/abstract.tex", "Abstract under review.")

    rec = await task_store.create(
        TaskRecord(
            id="t-bundle-consult",
            workflow="consult",
            input={
                "manuscript_id": manuscript.id,
                "bundle_target": "overleaf/sections/abstract.tex",
            },
            query="too AI-sounding?",
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None and final.status == "ok"
    assert final.result is not None
    # The pre-read fed the file content into the stub, which echoed it.
    assert "Abstract under review" in final.result["analysis"]
    # File on disk is unchanged — consult is read-only by contract.
    assert (
        await storage.read_text(manuscript, "overleaf/sections/abstract.tex")
        == "Abstract under review."
    )


async def test_consult_bundle_preread_missing_file_surfaces_task_error(tmp_path):
    """Symmetry with the P9.0 revision case: a missing bundle_target on
    consult also produces an explicit pre-read error (with the workflow
    name in the message so a glance tells you which path failed)."""

    task_store, ms_store, _storage, deps = await _setup_with_bundle(_ConsultStub, tmp_path)
    manuscript, _ = await ms_store.create(
        CreateManuscriptInput(title="Bundle paper", layout="bundle")
    )

    rec = await task_store.create(
        TaskRecord(
            id="t-bundle-consult-miss",
            workflow="consult",
            input={
                "manuscript_id": manuscript.id,
                "bundle_target": "overleaf/sections/does-not-exist.tex",
            },
            query="any thoughts?",
        )
    )
    await execute_task(rec.id, deps)

    final = await task_store.get(rec.id)
    assert final is not None
    assert final.status == "error"
    assert "bundle pre-read failed for consult" in (final.error or "")
