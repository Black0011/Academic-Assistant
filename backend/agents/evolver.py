"""EvolverAgent — proposes heuristic drafts from finished workflow runs.

The agent is the trigger for AAF's self-evolution loop:

    workflow finishes (ok)          ─┐
        │                            │
        ▼                            │  EvolverAgent
    EvolverAgent.evolve_from_run    ─┤  (this file)
        │                            │
        ▼                            │
    ProposalStore.create  (draft)   ─┘
        │
        ▼
    Human review via /proposals → approve → apply
        │
        ▼
    HeuristicStore (separate apply step, owned by M8.1's apply flow)

Design tenets (rule aaf-agent-workflow):

* **Stateless.** No per-run mutable state on the instance.
* **Never writes to HeuristicStore directly.** Only the gated apply
  flow may do that — the evolver's job stops at "draft proposal".
* **Cheap by default.** Without an LLM, the agent uses a deterministic
  template — never blocks the runner waiting on a model.
* **Safe-to-skip.** Errors / partial verdicts produce ``None``.
  Workflows can opt out of one specific run by setting
  ``output.results["evolve"] = False``.
* **Routing-aware.** When given an LLM provider that exposes
  ``for_route``, the drafting call uses ``"reasoning"`` (the same
  route the write/revision workflows use for their planning steps).
"""

from __future__ import annotations

import difflib
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.errors import LLMError
from backend.core.llm.base import ChatMessage, LLMProvider, collect_text
from backend.proposals.models import CreateProposalInput, Proposal
from backend.proposals.store import ProposalStore
from backend.tasks.models import TaskRecord
from backend.workflows.base import WorkflowOutput

if TYPE_CHECKING:
    from backend.tasks.runner import BundleChange

log = structlog.get_logger(__name__)


_DRAFT_SYSTEM = (
    "You are AAF's self-evolution proposer. Given the outcome of one "
    "workflow run, draft a SINGLE heuristic that future runs of the "
    "same workflow could re-use to do better. Output a JSON object "
    'with three string fields: "title" (≤ 60 chars, imperative voice), '
    '"summary" (1 sentence ≤ 140 chars), "motivation" (≤ 280 chars, '
    "explain *why* this heuristic helps; cite concrete numbers from "
    "the run when possible). Do NOT propose code changes — only the "
    "human-reviewable description. If no useful heuristic emerges, "
    'output exactly the JSON: {"skip": true}.'
)


class EvolverAgent:
    """Stateless agent that drafts heuristic proposals from runs."""

    def __init__(
        self,
        *,
        llm: LLMProvider | None = None,
        max_summary_chars: int = 200,
    ) -> None:
        self._llm = llm
        self._max_summary_chars = max_summary_chars

    async def evolve_from_run(
        self,
        *,
        record: TaskRecord,
        output: WorkflowOutput,
        store: ProposalStore,
        actor: str | None = None,
        bundle_change: BundleChange | None = None,
    ) -> Proposal | None:
        """Inspect ``output`` and create a draft :class:`Proposal`.

        Returns the persisted proposal on success, or ``None`` when no
        proposal is warranted (error verdict, opt-out flag, etc.).

        Never raises — failure paths are logged and swallowed so the
        runner can keep moving.

        ``bundle_change`` (P8 Phase C2): when the runner actually wrote
        a bundle file during this run, the resulting :class:`Proposal`
        is enriched with:

        * ``target_paths = [bundle_change.target_path]``
        * ``diff``        = unified diff (``difflib.unified_diff``) of
          ``before`` → ``after`` with ``a/<path>`` / ``b/<path>``
          headers, so the UI can render it with any standard diff
          viewer.
        * ``extras["manuscript_id"] / ["bundle_target"] /
          ["bundle_before"] / ["bundle_after"]``: the deterministic
          payload used by the ``apply-to-bundle`` endpoint to re-apply
          the same change with a staleness check (``bundle_before``
          must still match the on-disk content unless ``force=true``).

        The diff itself is informational; the apply path uses
        ``bundle_after`` directly so we never need a real diff applier.
        """

        if output.verdict != "ok":
            return None

        results = output.results if isinstance(output.results, Mapping) else {}
        if results.get("evolve") is False:
            log.debug(
                "agents.evolver.opt_out",
                task_id=record.id,
                workflow=record.workflow,
            )
            return None

        try:
            body = await self._draft(record=record, output=output, results=results)
        except (LLMError, OSError, ValueError):
            # _draft's LLM path is already narrow internally; this outer
            # net catches the residual Pydantic ValidationError / weird
            # bytes-to-str OSError. Anything broader is a real bug and
            # should propagate via the runner's own crash handler.
            log.exception(
                "agents.evolver.draft_failed",
                task_id=record.id,
                workflow=record.workflow,
            )
            return None

        if body is None:
            return None

        if bundle_change is not None:
            body = self._enrich_with_bundle_change(body, bundle_change)

        try:
            proposal = await store.create(
                body,
                actor=actor or f"evolver:{record.workflow}",
            )
        except OSError:
            # YAML backend can fail on disk/permissions; in-memory backend
            # raises nothing. Either way, we don't want to abort the
            # runner just because the proposal couldn't be persisted —
            # the workflow's actual deliverable is already saved.
            log.exception(
                "agents.evolver.persist_failed",
                task_id=record.id,
                workflow=record.workflow,
            )
            return None

        log.info(
            "agents.evolver.proposal_created",
            task_id=record.id,
            workflow=record.workflow,
            proposal_id=proposal.proposal_id,
            via_llm=self._llm is not None,
        )
        return proposal

    # ------------------------------------------------------------------
    # Drafting paths
    # ------------------------------------------------------------------

    async def _draft(
        self,
        *,
        record: TaskRecord,
        output: WorkflowOutput,
        results: Mapping[str, Any],
    ) -> CreateProposalInput | None:
        if self._llm is not None:
            llm_body = await self._draft_with_llm(record, results)
            if llm_body is not None:
                return llm_body
            # If the LLM declined, still fall back to the template so
            # observability captures *that the run finished* even if the
            # model thinks the heuristic is uninteresting.
        return self._draft_template(record=record, output=output, results=results)

    def _draft_template(
        self,
        *,
        record: TaskRecord,
        output: WorkflowOutput,
        results: Mapping[str, Any],
    ) -> CreateProposalInput:
        title = f"heuristic from {record.workflow} · {record.id[:8]}"
        summary = self._template_summary(record=record, results=results)
        motivation = (
            f"Auto-drafted by EvolverAgent after a successful "
            f"{record.workflow} run (task {record.id}). Verdict: "
            f"{output.verdict}. Budget used: "
            f"{output.budget.get('cost_usd', 0):.4f} USD."
        )
        return CreateProposalInput(
            title=title[:120],
            summary=summary[: self._max_summary_chars],
            motivation=motivation,
            risk_level="low",
            tags=["self-evolution", record.workflow],
            proposer_kind="agent",
            proposer_id="evolver",
            extras={
                "task_id": record.id,
                "workflow": record.workflow,
                "verdict": output.verdict,
                "via_llm": False,
            },
        )

    async def _draft_with_llm(
        self,
        record: TaskRecord,
        results: Mapping[str, Any],
    ) -> CreateProposalInput | None:
        provider = self._llm
        assert provider is not None
        for_route = getattr(provider, "for_route", None)
        if callable(for_route):
            provider = for_route("reasoning")

        user_prompt = (
            f"Workflow: {record.workflow}\n"
            f"Task ID: {record.id}\n"
            f"Query: {record.query}\n\n"
            f"Run result keys: {sorted(results.keys())}\n"
            f"Run result preview: {self._preview(results)}\n\n"
            "Draft the heuristic JSON now."
        )

        try:
            text, _, _, _ = await collect_text(
                await provider.complete(
                    [
                        ChatMessage(role="system", content=_DRAFT_SYSTEM),
                        ChatMessage(role="user", content=user_prompt),
                    ],
                    temperature=0.0,
                    stream=False,
                )
            )
        except (LLMError, OSError):
            # Treat any LLM / network failure as "no proposal this run" —
            # the runner has already finished its real work and the user
            # should not be punished by a noisy crash trace just because
            # the heuristic-drafter LLM was unavailable.
            log.exception(
                "agents.evolver.llm_call_failed",
                task_id=record.id,
                workflow=record.workflow,
            )
            return None

        parsed = self._extract_json_object(text)
        if parsed is None:
            log.warning(
                "agents.evolver.bad_llm_json",
                task_id=record.id,
                snippet=text[:200],
            )
            return None
        if parsed.get("skip"):
            return None

        title = str(parsed.get("title") or "").strip()
        summary = str(parsed.get("summary") or "").strip()
        motivation = str(parsed.get("motivation") or "").strip()
        if not title or not summary:
            return None

        return CreateProposalInput(
            title=title[:120],
            summary=summary[: self._max_summary_chars],
            motivation=motivation,
            risk_level="low",
            tags=["self-evolution", record.workflow, "llm-drafted"],
            proposer_kind="agent",
            proposer_id="evolver",
            extras={
                "task_id": record.id,
                "workflow": record.workflow,
                "via_llm": True,
            },
        )

    # ------------------------------------------------------------------
    # Batched / manual synthesis (P9.4)
    # ------------------------------------------------------------------

    async def evolve_from_recent_runs(
        self,
        *,
        records: list[TaskRecord],
        store: ProposalStore,
        actor: str | None = None,
        scope_label: str | None = None,
    ) -> Proposal | None:
        """Draft a single heuristic proposal from a batch of recent runs.

        Unlike :meth:`evolve_from_run`, this is the *manual-trigger*
        synthesis path (P9.4). It exists so a human (or a scheduled
        admin job) can periodically ask AAF "here are the last N runs;
        what one heuristic would help us next time?" instead of getting
        one proposal per successful task.

        Implementation notes:

        * Drops error/cancelled/empty records up-front so the prompt
          stays focused on useful cases.
        * Builds a single LLM prompt that lists every record's
          workflow + query + result preview. Same JSON contract as
          :meth:`_draft_with_llm` (``title`` / ``summary`` /
          ``motivation``).
        * Falls back to a deterministic template summary if there's no
          LLM wired (mock provider / offline mode), so the endpoint
          still produces a useful proposal in tests / on a laptop.
        * Never raises — same contract as ``evolve_from_run``.
        """

        cases = [r for r in records if r.status == "ok"]
        if not cases:
            return None

        try:
            body = await self._draft_synthesis(cases=cases, scope_label=scope_label)
        except (LLMError, OSError, ValueError):
            log.exception(
                "agents.evolver.synth_draft_failed",
                count=len(cases),
                scope=scope_label,
            )
            return None

        if body is None:
            return None

        try:
            proposal = await store.create(
                body,
                actor=actor or "evolver:synthesis",
            )
        except OSError:
            log.exception(
                "agents.evolver.synth_persist_failed",
                count=len(cases),
            )
            return None

        log.info(
            "agents.evolver.synth_proposal_created",
            proposal_id=proposal.proposal_id,
            count=len(cases),
            via_llm=self._llm is not None,
        )
        return proposal

    async def _draft_synthesis(
        self,
        *,
        cases: list[TaskRecord],
        scope_label: str | None,
    ) -> CreateProposalInput | None:
        if self._llm is not None:
            llm_body = await self._draft_synthesis_with_llm(cases=cases, scope_label=scope_label)
            if llm_body is not None:
                return llm_body
        return self._draft_synthesis_template(cases=cases, scope_label=scope_label)

    def _draft_synthesis_template(
        self,
        *,
        cases: list[TaskRecord],
        scope_label: str | None,
    ) -> CreateProposalInput:
        workflows = sorted({c.workflow for c in cases})
        scope = scope_label or (workflows[0] if len(workflows) == 1 else "mixed")
        title = f"synthesised heuristic from {len(cases)} {scope} runs"
        summary = (
            f"Reviewing {len(cases)} successful runs across {len(workflows)} "
            f"workflow(s) ({', '.join(workflows)}); capture a shared pattern "
            "so future runs can reuse it."
        )
        motivation_lines = [
            "Auto-synthesised by EvolverAgent from the following runs:",
        ]
        for c in cases[:8]:
            preview = (c.query or "").strip().replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:77] + "..."
            motivation_lines.append(f"- {c.workflow} · {c.id[:8]} · {preview or '(no query)'}")
        if len(cases) > 8:
            motivation_lines.append(f"... and {len(cases) - 8} more.")

        return CreateProposalInput(
            title=title[:120],
            summary=summary[: self._max_summary_chars],
            motivation="\n".join(motivation_lines)[:1000],
            risk_level="low",
            tags=["self-evolution", "synthesis", scope],
            proposer_kind="agent",
            proposer_id="evolver",
            extras={
                "task_ids": [c.id for c in cases],
                "workflows": workflows,
                "via_llm": False,
                "synthesis": True,
            },
        )

    async def _draft_synthesis_with_llm(
        self,
        *,
        cases: list[TaskRecord],
        scope_label: str | None,
    ) -> CreateProposalInput | None:
        provider = self._llm
        assert provider is not None
        for_route = getattr(provider, "for_route", None)
        if callable(for_route):
            provider = for_route("reasoning")

        workflows = sorted({c.workflow for c in cases})
        scope = scope_label or (workflows[0] if len(workflows) == 1 else "mixed")
        body_lines = [
            f"You are reviewing {len(cases)} successful workflow run(s) "
            f"(scope={scope}). For each, the query and a result preview is "
            "shown. Draft ONE heuristic that would help future runs of the "
            "same type. Output JSON as specified.\n",
        ]
        for i, c in enumerate(cases[:12], start=1):
            preview = self._preview(c.result or {}, limit=300)
            body_lines.append(
                f"[{i}] workflow={c.workflow} id={c.id[:8]}\n"
                f"    query: {(c.query or '').strip()[:200]}\n"
                f"    result: {preview}\n"
            )
        user_prompt = "\n".join(body_lines) + "\nDraft the heuristic JSON now."

        try:
            text, _, _, _ = await collect_text(
                await provider.complete(
                    [
                        ChatMessage(role="system", content=_DRAFT_SYSTEM),
                        ChatMessage(role="user", content=user_prompt),
                    ],
                    temperature=0.0,
                    stream=False,
                )
            )
        except (LLMError, OSError):
            log.exception("agents.evolver.synth_llm_call_failed", count=len(cases))
            return None

        parsed = self._extract_json_object(text)
        if parsed is None or parsed.get("skip"):
            return None
        title = str(parsed.get("title") or "").strip()
        summary = str(parsed.get("summary") or "").strip()
        motivation = str(parsed.get("motivation") or "").strip()
        if not title or not summary:
            return None

        return CreateProposalInput(
            title=title[:120],
            summary=summary[: self._max_summary_chars],
            motivation=motivation,
            risk_level="low",
            tags=["self-evolution", "synthesis", "llm-drafted", scope],
            proposer_kind="agent",
            proposer_id="evolver",
            extras={
                "task_ids": [c.id for c in cases],
                "workflows": workflows,
                "via_llm": True,
                "synthesis": True,
            },
        )

    # ------------------------------------------------------------------
    # Bundle enrichment (P8 Phase C2)
    # ------------------------------------------------------------------

    @staticmethod
    def _enrich_with_bundle_change(
        body: CreateProposalInput,
        change: BundleChange,
    ) -> CreateProposalInput:
        """Return a copy of ``body`` carrying bundle diff + extras.

        Pure function, never raises: ``difflib.unified_diff`` cannot
        fail on str input, and Pydantic copies are always safe.
        """
        diff_lines = difflib.unified_diff(
            change.before.splitlines(keepends=True),
            change.after.splitlines(keepends=True),
            fromfile=f"a/{change.target_path}",
            tofile=f"b/{change.target_path}",
            n=3,
        )
        diff_text = "".join(diff_lines)

        extras = dict(body.extras)
        extras["manuscript_id"] = change.manuscript_id
        extras["bundle_target"] = change.target_path
        extras["bundle_before"] = change.before
        extras["bundle_after"] = change.after
        extras["workflow"] = change.workflow

        # Pydantic v2: model_copy(update=...) keeps validation contract.
        return body.model_copy(
            update={
                "target_paths": [change.target_path],
                "diff": diff_text,
                "extras": extras,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _template_summary(self, *, record: TaskRecord, results: Mapping[str, Any]) -> str:
        if record.workflow == "write":
            section = results.get("section", "section")
            wc = results.get("word_count", 0)
            citations = len(results.get("citations") or [])
            return (
                f"After writing the {section} section ({wc} words, "
                f"{citations} citations), capture what worked so the "
                "next write run can re-use the recipe."
            )
        if record.workflow == "revision":
            cl = len(results.get("change_log") or [])
            return (
                f"After applying {cl} reviewer-comment changes, capture "
                "the rewrite pattern so future revisions can converge "
                "faster."
            )
        if record.workflow == "research":
            return (
                "After this research run, capture the search / synthesis "
                "approach as a heuristic so similar queries can re-use it."
            )
        return (
            f"Heuristic auto-drafted from a successful {record.workflow} "
            "run; review and edit before approving."
        )

    @staticmethod
    def _preview(results: Mapping[str, Any], limit: int = 600) -> str:
        text = repr(dict(results))
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    @staticmethod
    def _extract_json_object(text: str) -> dict[str, Any] | None:
        """Parse the first balanced JSON object out of ``text``.

        Mirrors the helper in ``backend/workflows/revision.py`` so
        evolver doesn't need a hard dependency on it; kept private here
        because the prompt is also private to this module.
        """

        import json

        text = (text or "").strip()
        if not text:
            return None
        # Strip code fences if the model returns ```json ... ```.
        if text.startswith("```"):
            text = text.strip("`")
            text = text.split("\n", 1)[1] if "\n" in text else ""
            text = text.rsplit("```", 1)[0]
        try:
            value = json.loads(text)
        except ValueError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                value = json.loads(text[start : end + 1])
            except ValueError:
                return None
        return value if isinstance(value, dict) else None
