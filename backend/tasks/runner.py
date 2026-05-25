"""Workflow runner — runs one task, persisting events and final state.

Callers:
* :class:`InMemoryTaskQueue` — schedules this via ``asyncio.create_task``.
* The ARQ worker (see :mod:`backend.workers.arq_worker`) — schedules this
  via ARQ's job function.

The runner knows **nothing** about HTTP or SSE; it only writes to a
:class:`TaskStore`. Clients watching a task poll the store's event log.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.budget import Budget
from backend.core.events import Event, EventType
from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.models import CommitVersionInput, ManuscriptOrigin
from backend.manuscripts.store import ManuscriptStore
from backend.proposals.store import ProposalStore
from backend.workflows.base import WorkflowContext, WorkflowOutput
from backend.workflows.bundle_adapter import BundleAdapter
from backend.workflows.registry import WorkflowRegistry

if TYPE_CHECKING:
    # Imported lazily inside ``RunnerDeps.__init__`` to break the cycle
    # ``backend.agents.evolver`` → ``backend.tasks.models`` →
    # ``backend.tasks.__init__`` → ``backend.tasks.queue`` →
    # ``backend.tasks.runner`` → ``backend.agents``.
    from backend.agents import EvolverAgent

from .models import TaskRecord, TaskStatus
from .store import TaskStore

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class BundleChange:
    """Snapshot of a bundle write performed by the runner during a task.

    Plumbed from :func:`_maybe_commit_manuscript` to
    :func:`_maybe_run_evolver` so the EvolverAgent can attach a
    file-level diff to the proposal it drafts. Carries everything the
    later ``apply-to-bundle`` endpoint needs for a deterministic +
    staleness-checked re-application.
    """

    manuscript_id: str
    target_path: str
    before: str
    after: str
    workflow: str


class RunnerDeps:
    """Everything a runner needs — passed through from the app / worker.

    The queue layer hides this so callers don't have to construct it
    themselves; :class:`InMemoryTaskQueue` builds one from ``AppState``,
    and the ARQ worker builds one from its own context dict.
    """

    __slots__ = (
        "bundle_storage",
        "default_budget_usd",
        "evolver",
        "evolver_enabled",
        "llm",
        "manuscripts",
        "memory",
        "proposals",
        "settings",
        "skill_host",
        "store",
        "tools",
        "workflows",
    )

    def __init__(
        self,
        *,
        store: TaskStore,
        workflows: WorkflowRegistry,
        memory: Any = None,
        llm: Any = None,
        tools: Any = None,
        manuscripts: ManuscriptStore | None = None,
        bundle_storage: BundleStorage | None = None,
        skill_host: Any = None,
        settings: Any = None,
        default_budget_usd: float = 2.0,
        proposals: ProposalStore | None = None,
        evolver_enabled: bool = False,
        evolver: EvolverAgent | None = None,
    ) -> None:
        self.store = store
        self.workflows = workflows
        self.memory = memory
        self.llm = llm
        self.tools = tools
        self.manuscripts = manuscripts
        self.bundle_storage = bundle_storage
        self.skill_host = skill_host
        self.settings = settings
        self.default_budget_usd = default_budget_usd
        self.proposals = proposals
        self.evolver_enabled = evolver_enabled
        self.evolver: EvolverAgent | None
        if evolver is not None:
            self.evolver = evolver
        elif proposals is not None:
            # P9.4: the agent itself is created whenever a proposal store
            # is wired — even with auto-fire (evolver_enabled) off — so
            # the manual ``POST /api/proposals:synthesize`` endpoint
            # always has somewhere to dispatch. The auto-fire path is
            # still gated separately inside ``_maybe_run_evolver``.
            from backend.agents import EvolverAgent as _EvolverAgent

            self.evolver = _EvolverAgent(llm=llm)
        else:
            self.evolver = None


async def execute_task(task_id: str, deps: RunnerDeps) -> None:
    """Run the workflow bound to *task_id*. Persists every event.

    Never raises. Any exception is captured on the task record and a
    ``task.error`` event is appended.
    """
    store = deps.store
    record = await store.get(task_id)
    if record is None:
        log.warning("task.runner.missing", task_id=task_id)
        return
    if record.is_terminal:
        log.info("task.runner.already_terminal", task_id=task_id, status=record.status)
        return

    workflow_name = record.workflow
    if not deps.workflows.has(workflow_name):
        err = f"workflow '{workflow_name}' not registered on this worker"
        await _record_error(
            store, task_id, record, err, Event(EventType.TASK_ERROR, data={"error": err})
        )
        return

    workflow = deps.workflows.instantiate(workflow_name)

    budget_usd = record.budget.get("max_cost_usd") if record.budget else None
    budget = Budget(max_cost_usd=budget_usd or deps.default_budget_usd)

    bundle_adapter = await BundleAdapter.maybe_build(
        manuscript_id=(record.input or {}).get("manuscript_id"),
        manuscripts=deps.manuscripts,
        storage=deps.bundle_storage,
    )

    workflow_input = dict(record.input or {})
    # P8 — bundle-aware revision: when ``bundle_target`` is set on a bundle
    # manuscript, the runner pre-reads that file into ``input.text`` so the
    # workflow body itself stays unchanged (it still consumes ``text``).
    # Pre-read failures get surfaced as a *task* error (not a workflow
    # error) so the user sees a precise diagnostic instead of the
    # downstream ``revision requires input.text`` from the workflow body.
    #
    # P11 — ``consult`` joins the bundle-pre-read club. It only *reads*
    # the file (never writes), so we extend the pre-read path but
    # *not* the write-back path below.
    #
    # P14.2 — multi-file batch review: when ``bundle_targets`` (plural)
    # is a list of paths, pre-read all of them and concatenate with
    # ``<section-marker>`` headings before writing into ``input.text``.
    #
    # P15 — ``peer-review``: when no specific targets are given, pre-read
    # ALL text files from the bundle (auto-project-audit mode).
    # P16 — ``project-consult``: agent-driven file exploration.
    # The runner injects the file tree listing + bundle_adapter reference,
    # then the workflow lets the LLM decide which files to read round-by-round.
    if (
        bundle_adapter is not None
        and workflow_name in {"project-consult", "project-revision"}
        and not workflow_input.get("text")
    ):
        try:
            manifest = await bundle_adapter.list_tree()
            tree = [
                {"path": f.path, "size": f.size, "is_text": f.is_text, "mime": f.mime}
                for f in manifest.files
            ]
            workflow_input["bundle_tree"] = tree
            log.info(
                "task.runner.project_consult_tree",
                task_id=task_id,
                file_count=len(tree),
            )
        except Exception as exc:
            log.exception(
                "task.runner.project_consult_tree_failed",
                task_id=task_id,
                error=str(exc),
            )

    if (
        bundle_adapter is not None
        and workflow_name in {"revision", "consult", "peer-review", "project-revision", "research"}
        and not workflow_input.get("text")
    ):
        targets: list[str] = []
        single = workflow_input.get("bundle_target")
        multi = workflow_input.get("bundle_targets")
        if single:
            targets = [str(single)]
        elif isinstance(multi, list) and multi:
            targets = [str(t) for t in multi]

        # P15 — peer-review / project-consult auto-collect: when no
        # explicit targets are given, read ALL text files from the bundle.
        if not targets and workflow_name in {"peer-review", "consult"}:
            try:
                manifest = await bundle_adapter.list_tree()
                text_exts = {".tex", ".md", ".txt", ".rst", ".bib"}
                targets = sorted(
                    f.path for f in manifest.files
                    if any(f.path.endswith(ext) for ext in text_exts) and f.is_text
                )
                log.info(
                    "task.runner.peer_review_auto_collect",
                    task_id=task_id,
                    file_count=len(targets),
                )
            except Exception as exc:
                log.exception(
                    "task.runner.peer_review_manifest_failed",
                    task_id=task_id,
                    error=str(exc),
                )

        if targets:
            parts: list[str] = []
            failed: list[str] = []
            for tgt in targets:
                try:
                    content = await bundle_adapter.read_text(tgt)
                    if len(targets) > 1:
                        parts.append(f"%%% BEGIN FILE: {tgt} %%%\n\n{content}\n\n%%% END FILE: {tgt} %%%")
                    else:
                        parts.append(content)
                except Exception as exc:
                    failed.append(f"{tgt}: {type(exc).__name__}: {exc}")
            if not parts:
                err = (
                    f"bundle pre-read failed for {workflow_name}: manuscript="
                    f"{bundle_adapter.manuscript.id} all targets failed → "
                    f"{'; '.join(failed)}"
                )
                log.exception(
                    "task.runner.bundle_preread_failed",
                    task_id=task_id,
                    manuscript_id=bundle_adapter.manuscript.id,
                    path=",".join(targets),
                )
                await _record_error(
                    store, task_id, record, err, Event(EventType.TASK_ERROR, data={"error": err})
                )
                return
            workflow_input["text"] = "\n\n".join(parts)
            if failed:
                log.warning(
                    "task.runner.bundle_preread_partial",
                    task_id=task_id,
                    failed=len(failed),
                    succeeded=len(parts),
                )

    ctx = WorkflowContext(
        task_id=task_id,
        query=record.query,
        input=workflow_input,
        user_id=record.user_id,
        session_id=record.session_id,
        llm=deps.llm,
        memory=deps.memory,
        tools=deps.tools,
        skill_host=deps.skill_host,
        bundle=bundle_adapter,
        store=store,
        budget=budget,
    )

    # P16: for project-consult, also inject the file tree into ctx.state
    # so the workflow doesn't need to re-fetch it.
    bundle_tree = workflow_input.pop("bundle_tree", None)
    if bundle_tree is not None:
        ctx.state["bundle_tree"] = bundle_tree

    async def sink(event: Event) -> None:
        try:
            await store.append_event(task_id, event)
        except Exception:
            log.exception("task.runner.event_append_failed", task_id=task_id, type=event.type)

    ctx.with_sink(sink)

    await store.mark_started(task_id)
    try:
        out = await workflow.run(ctx)
    except Exception as exc:
        log.exception("task.runner.crash", task_id=task_id)
        await sink(Event(EventType.TASK_ERROR, task_id=task_id, data={"error": str(exc)}))
        await store.mark_completed(
            task_id,
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            budget=budget.snapshot(),
        )
        return

    # ---- waiting (paused for user input) -------------------------------
    if out.verdict == "waiting":
        # The workflow already wrote status="waiting" via ctx.store.
        # We just emit the SSE event and return — no DB write needed.
        results = out.results if out.results is not None else {}
        await sink(Event(
            EventType.TASK_AWAITING_INPUT,
            task_id=task_id,
            data={
                "prompt": results.get("prompt", ""),
                "checkpoint": results.get("checkpoint", ""),
                "prompt_data": results.get("prompt_data", {}),
                "stage": results.get("stage", ""),
            },
        ))
        return

    # ---- ok / error ---------------------------------------------------
    final_status: TaskStatus = "error" if out.verdict == "error" else "ok"
    results = out.results if out.results is not None else {}
    bundle_change: BundleChange | None = None
    if final_status == "ok" and deps.manuscripts is not None:
        try:
            bundle_change = await _maybe_commit_manuscript(
                deps.manuscripts,
                bundle=bundle_adapter,
                task_id=task_id,
                workflow=workflow_name,
                record=record,
                results=results,
                sink=sink,
            )
        except Exception:  # manuscript persistence must never abort the task
            log.exception("task.runner.manuscript_commit_failed", task_id=task_id)
    if final_status == "ok":
        # Self-evolution hook: ask EvolverAgent to draft a heuristic
        # proposal from the run. The agent itself is contractually
        # safe-to-call (returns None on any internal failure), but we
        # still wrap in try/except so a bug in the agent can never
        # corrupt the task's terminal status.
        try:
            await _maybe_run_evolver(deps, record=record, output=out, bundle_change=bundle_change)
        except Exception:
            log.exception("task.runner.evolver_failed", task_id=task_id)
    await store.mark_completed(
        task_id,
        status=final_status,
        result=results,
        error=out.error,
        budget=out.budget,
    )


async def _maybe_commit_manuscript(
    store: ManuscriptStore,
    *,
    bundle: BundleAdapter | None,
    task_id: str,
    workflow: str,
    record: TaskRecord,
    results: dict,
    sink: Any,
) -> BundleChange | None:
    """Auto-persist workflow output to the right surface.

    Two surfaces, picked by manuscript layout — opt-in via
    ``input.manuscript_id``:

    * **Single layout (pre-P7 default).** Append a new ``ManuscriptVersion``
      row via ``store.commit_version`` (unchanged from M4). Supports
      ``write`` (``results.markdown``) and ``revision`` (``results.revised``).

    * **Bundle layout (P7+).** Write the same content to a bundle file
      path resolved from the task input. Both branches require
      ``input.bundle_target`` to be set; missing target ⇒ logged skip.
      - ``revision`` → writes ``results.revised`` to ``bundle_target``.
      - ``write``    → writes ``results.markdown`` to ``bundle_target``,
        and (when ``input.register_in_main`` is true) inserts an
        ``\\input{<rel>}`` line above ``\\end{document}`` in
        ``overleaf/main.tex``. The register step is best-effort and never
        fails the task — the section file is the actual deliverable.

      A ``manuscript.bundle_write`` event is emitted to the task SSE
      stream so the UI can refresh the file tree without polling.

    Silently no-ops for other workflows or when the layout / target
    combination doesn't match a supported case.
    """
    manuscript_id = (record.input or {}).get("manuscript_id")
    if not manuscript_id:
        return None

    # ---- Bundle branch -------------------------------------------------
    if bundle is not None and workflow in {"revision", "write", "project-revision"}:
        input_dict = record.input or {}

        # P18: project-revision writes multiple files
        if workflow == "project-revision":
            changes = results.get("changes") or []
            if not changes:
                log.info("task.runner.bundle_skip_empty_changes", task_id=task_id)
                return None
            first_change: BundleChange | None = None
            for ch in changes:
                path = str(ch.get("path") or "").strip()
                after = str(ch.get("after") or "")
                before = str(ch.get("before") or "")
                if not path or not after.strip():
                    continue
                try:
                    await bundle.write_text(path, after)
                    await sink(Event(EventType.TASK_PROGRESS, task_id=task_id, data={
                        "stage": "writeback", "path": path, "status": "ok",
                    }))
                except Exception as exc:
                    log.exception("task.runner.bundle_multi_write_failed", task_id=task_id, path=path)
                    await sink(Event(EventType.TASK_WARNING, task_id=task_id, data={
                        "stage": "writeback", "path": path, "error": str(exc)[:200],
                    }))
                    continue
                if first_change is None:
                    first_change = BundleChange(
                        manuscript_id=manuscript_id,
                        target_path=path,
                        before=before,
                        after=after,
                        workflow=workflow,
                    )
            log.info("task.runner.project_revision_committed", task_id=task_id, files=len(changes))
            return first_change

        bundle_target = str(input_dict.get("bundle_target") or "").strip()
        if workflow == "revision":
            content = str(results.get("revised") or "")
        else:  # write
            content = str(results.get("markdown") or "")
        if not bundle_target:
            log.info(
                "task.runner.bundle_skip_no_target",
                task_id=task_id,
                manuscript_id=manuscript_id,
                workflow=workflow,
            )
            return None
        if not content.strip():
            log.info("task.runner.bundle_skip_empty", task_id=task_id)
            return None
        try:
            before_text = await bundle.read_text(bundle_target)
        except Exception:
            before_text = ""
        try:
            meta = await bundle.write_text(bundle_target, content)
        except Exception:
            log.exception(
                "task.runner.bundle_write_failed",
                task_id=task_id,
                manuscript_id=manuscript_id,
                path=bundle_target,
            )
            return None
        log.info(
            "task.runner.bundle_written",
            task_id=task_id,
            manuscript_id=manuscript_id,
            path=meta.path,
            size=meta.size,
            workflow=workflow,
        )

        # Optional: register a freshly written write-workflow section in
        # overleaf/main.tex via \input{...}. Off by default so we don't
        # mutate main.tex when the user didn't ask. Failures here NEVER
        # affect the section write — the section file is the deliverable;
        # main.tex registration is decorative convenience.
        if (
            workflow == "write"
            and bool(input_dict.get("register_in_main"))
            and bundle_target.startswith("overleaf/")
        ):
            try:
                await _maybe_register_in_main(bundle, bundle_target=bundle_target, task_id=task_id)
            except Exception:
                log.exception(
                    "task.runner.bundle_register_in_main_failed",
                    task_id=task_id,
                    manuscript_id=manuscript_id,
                )

        # Best-effort SSE event so the BundleExplorer can invalidate its
        # tree query without polling. Sink failures are swallowed by sink().
        await sink(
            Event(
                EventType.MEMORY_WRITE,
                task_id=task_id,
                data={
                    "kind": "manuscript.bundle_write",
                    "manuscript_id": manuscript_id,
                    "path": meta.path,
                    "size": meta.size,
                    "workflow": workflow,
                },
            )
        )
        return BundleChange(
            manuscript_id=manuscript_id,
            target_path=bundle_target,
            before=before_text,
            after=content,
            workflow=workflow,
        )

    # ---- Single-doc branch (legacy, unchanged) -------------------------
    origin: ManuscriptOrigin
    if workflow == "write":
        content = str(results.get("markdown") or "").strip()
        origin = "write_workflow"
        note = f"write workflow · section={results.get('section', '')}"
        citations = list(results.get("citations", []))
        reviewer_comments: list = []
    elif workflow == "revision":
        content = str(results.get("revised") or "").strip()
        origin = "revision_workflow"
        note = "revision workflow"
        citations = list(results.get("citations", []))
        reviewer_comments = list((record.input or {}).get("comments", []) or [])
    else:
        return None

    if not content:
        log.info("task.runner.manuscript_skip_empty", task_id=task_id)
        return None

    try:
        version = await store.commit_version(
            manuscript_id,
            CommitVersionInput(
                content=content,
                note=note,
                origin=origin,
                produced_by=task_id,
                citations=citations,
                reviewer_comments=reviewer_comments,
            ),
        )
        log.info(
            "task.runner.manuscript_committed",
            task_id=task_id,
            manuscript_id=manuscript_id,
            version=version.version,
        )
    except KeyError:
        log.warning(
            "task.runner.manuscript_missing",
            task_id=task_id,
            manuscript_id=manuscript_id,
        )
    return None


async def _maybe_register_in_main(
    bundle: BundleAdapter,
    *,
    bundle_target: str,
    task_id: str,
) -> None:
    r"""Idempotently insert ``\input{<rel>}`` above ``\end{document}`` in
    ``overleaf/main.tex``.

    Called only by the bundle/write branch of :func:`_maybe_commit_manuscript`
    when the caller opts in via ``input.register_in_main = True``.

    Heuristics intentionally narrow:
    * ``bundle_target`` must already start with ``overleaf/`` (caller
      checked) and end with ``.tex`` — otherwise we silently skip.
    * The relative path used inside ``\input{...}`` is the LaTeX-style
      sibling reference: drop the ``overleaf/`` prefix and the ``.tex``
      suffix. So ``overleaf/sections/related-work.tex`` becomes
      ``\input{sections/related-work}``.
    * Idempotent: if a line containing the same ``\input{<rel>}`` already
      exists, the function returns without rewriting.
    * If ``main.tex`` is missing or has no ``\end{document}`` line, we
      skip — we never *create* main.tex from the runner.
    """

    if not bundle_target.endswith(".tex"):
        return
    rel = bundle_target[len("overleaf/") :]
    rel = rel[: -len(".tex")]
    if not rel:
        return
    input_line = f"\\input{{{rel}}}"

    try:
        main_text = await bundle.read_text("overleaf/main.tex")
    except Exception:
        # main.tex absent / unreadable — that's fine, no-op.
        log.debug(
            "task.runner.bundle_register_main_missing",
            task_id=task_id,
            bundle_target=bundle_target,
        )
        return

    if input_line in main_text:
        return  # already registered, skip silently

    end_marker = "\\end{document}"
    end_idx = main_text.rfind(end_marker)
    if end_idx == -1:
        log.info(
            "task.runner.bundle_register_main_no_end",
            task_id=task_id,
        )
        return

    # Find the start of the line that holds \end{document} so we insert
    # *immediately above* it on its own line.
    line_start = main_text.rfind("\n", 0, end_idx) + 1
    inserted = main_text[:line_start] + input_line + "\n" + main_text[line_start:]
    await bundle.write_text("overleaf/main.tex", inserted)
    log.info(
        "task.runner.bundle_register_main_ok",
        task_id=task_id,
        input_line=input_line,
    )


async def _maybe_run_evolver(
    deps: RunnerDeps,
    *,
    record: TaskRecord,
    output: WorkflowOutput,
    bundle_change: BundleChange | None = None,
) -> None:
    """Fire the EvolverAgent against a finished workflow run.

    P9.4 gating model (replaces the pre-P9 "every successful run drafts
    a proposal" behaviour, which was generating proposal noise that
    interfered with day-to-day usage):

    1. ``bundle_change is not None``  →  auto-draft proposal. This is
       the P8 "the agent just wrote a file in your bundle; review it
       before applying" path, which the user explicitly opted into by
       running a write/revision workflow against a bundle manuscript.
    2. ``bundle_change is None``      →  *no* automatic proposal. Pure
       heuristic / self-evolution proposals are now manual-only via
       ``POST /api/proposals:synthesize``, which lets the user decide
       *when* (and across how many cases) self-evolution kicks in.

    Either path still requires ``deps.evolver_enabled`` to be true and
    a wired ``ProposalStore`` + ``EvolverAgent``. Otherwise this is a
    no-op.

    The agent itself is contractually safe-to-call (returns ``None``
    on any internal failure); this wrapper exists purely to keep
    ``execute_task`` readable and to enforce the gating rule above.
    """

    if not deps.evolver_enabled or deps.proposals is None or deps.evolver is None:
        return
    if bundle_change is None:
        # P9.4: skip pure heuristic auto-drafting. The case is still
        # implicitly captured in ``aaf_tasks`` (TaskStore) so the
        # synthesize endpoint can read it back later.
        log.debug(
            "task.runner.evolver_skipped_no_bundle_change",
            task_id=record.id,
            workflow=record.workflow,
        )
        return
    proposal = await deps.evolver.evolve_from_run(
        record=record,
        output=output,
        store=deps.proposals,
        bundle_change=bundle_change,
    )
    if proposal is not None:
        log.info(
            "task.runner.evolver_proposal",
            task_id=record.id,
            workflow=record.workflow,
            proposal_id=proposal.proposal_id,
            target_paths=proposal.target_paths,
        )


async def _record_error(
    store: TaskStore,
    task_id: str,
    record: TaskRecord,
    err: str,
    event: Event,
) -> None:
    try:
        await store.append_event(task_id, event)
    finally:
        await store.mark_completed(task_id, status="error", error=err)


__all__ = ["BundleChange", "RunnerDeps", "execute_task"]
