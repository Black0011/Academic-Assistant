"""RevisionWorkflow — rewrite a passage in response to reviewer comments.

Input contract (via ``ctx.input``):

* ``text``     — original passage (markdown or plain text). **Required.**
* ``comments`` — list of reviewer comments, each ``{id?, category?, text}``.
  Free-form strings are accepted too and auto-wrapped.
* ``goals``    — optional list of global goals (e.g. "tighten prose",
  "add citations to recent 2023 work").
* ``section``  — optional hint, propagated to reflection.

``ctx.query`` is an optional one-liner instruction summarising the
revision intent; it's used by the LLM prompts when present, falling back
to "Apply reviewer comments" otherwise.

Stages: ``recall → analyze → revise → reflect``. Every LLM step has a
templated fallback, so the workflow stays runnable in CI without keys.

Output::

    {
      "section":           "...",
      "original":          original text,
      "revised":           revised text,
      "change_log":        [{comment_id, summary, before, after}],
      "comments_addressed":[ids],
      "comments_open":     [ids],
      "citations":         [paper_ids cited in `revised`],
    }

P8 — bundle-aware mode (handled outside this module, in
``backend.tasks.runner``):

* When ``input.manuscript_id`` points at a *bundle* manuscript and
  ``input.bundle_target`` is set (e.g. ``"overleaf/sections/intro.tex"``),
  the runner pre-reads that file's content into ``input.text`` *before*
  invoking this workflow — so the workflow body itself stays unchanged.
* After a successful run the runner writes ``results.revised`` back to
  the same ``bundle_target`` (atomic, size-cap-checked) instead of
  appending a ``ManuscriptVersion`` row.
* For *single*-layout manuscripts (the pre-P7 default) the runner falls
  back to the legacy ``store.commit_version`` path, so existing tests +
  callers behave identically.

This keeps the workflow itself ignorant of layout — the only contract
addition is the optional ``bundle_target`` input field, documented here
so callers know when to set it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from backend.core.events import Event, EventType
from backend.memory.models import PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import audit_citations, auto_fix_suspects
from .primitives import sequential
from .write import _CITE_RE, _ask, _format_papers

_ANALYZE_SYSTEM = (
    "You are a senior academic revising a paper. For each reviewer comment, "
    "decide (a) whether to accept, partially accept, or defer; (b) a short "
    "action plan. Respond with STRICT JSON only."
)
_ANALYZE_USER = (
    "Instruction: {instruction}\nSection: {section}\n\n"
    "Reviewer comments:\n{comments}\n\n"
    "Original passage (verbatim):\n---\n{text}\n---\n\n"
    'Return JSON: {{"plan": [{{"comment_id": "<id>", '
    '"decision": "accept|partial|defer", "action": "<one-line>"}}]}}'
)

_REVISE_SYSTEM = (
    "You are a senior academic rewriting a passage. Keep the author's voice. "
    "Address every accepted/partial comment. Cite only the supplied paper_ids "
    "in square brackets (e.g. [aaa111]). Output the revised passage only — "
    "no preface, no explanation."
)
_REVISE_USER = (
    "Instruction: {instruction}\nSection: {section}\nGlobal goals: {goals}\n\n"
    "Reviewer plan:\n{plan}\n\n"
    "Relevant papers (for citations):\n{papers}\n\n"
    "Original passage:\n---\n{text}\n---"
)


# ---------------------------------------------------------------------------
# Comment normalisation
# ---------------------------------------------------------------------------


@dataclass
class ReviewerComment:
    id: str
    category: str
    text: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "category": self.category, "text": self.text}


def _normalise_comments(raw: Any) -> list[ReviewerComment]:
    if raw is None:
        return []
    if isinstance(raw, str):
        raw = [raw]
    out: list[ReviewerComment] = []
    for idx, item in enumerate(raw):
        if isinstance(item, str):
            out.append(ReviewerComment(id=f"c{idx + 1}", category="general", text=item))
            continue
        if isinstance(item, dict):
            cid = str(item.get("id") or f"c{idx + 1}")
            category = str(item.get("category") or "general")
            text = str(item.get("text") or "").strip()
            if text:
                out.append(ReviewerComment(id=cid, category=category, text=text))
    return out


# ---------------------------------------------------------------------------
# Workflow
# ---------------------------------------------------------------------------


class RevisionWorkflow(BaseWorkflow):
    name = "revision"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [self._validate, self._audit_original, self._recall, self._analyze, self._revise, self._reflect],
            )
        except Exception as exc:
            await ctx.emit(Event(EventType.TASK_END, data={"verdict": "error"}))
            return WorkflowOutput(
                task_id=ctx.task_id,
                verdict="error",
                trace=list(ctx.trace),
                budget=ctx.budget.snapshot(),
                error=f"{type(exc).__name__}: {exc}",
            )

        change_log = ctx.state.get("change_log", [])
        addressed = [c["comment_id"] for c in change_log if c.get("decision") != "defer"]
        deferred = [c["comment_id"] for c in change_log if c.get("decision") == "defer"]
        results: dict[str, Any] = {
            "section": ctx.input.get("section", ""),
            "original": ctx.state.get("original", ""),
            "revised": ctx.state.get("revised", ""),
            "change_log": change_log,
            "comments_addressed": addressed,
            "comments_open": deferred,
            "citations": sorted(ctx.state.get("citations", set())),
            "suspect_citations": ctx.state.get("suspect_citations", []),
        }
        await ctx.emit(
            Event(
                EventType.TASK_END,
                data={"verdict": "ok", "addressed": len(addressed), "open": len(deferred)},
            )
        )
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ---- stages ------------------------------------------------------

    async def _validate(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.input.get("text") or "").strip()
            if not text:
                manuscript_id = c.input.get("manuscript_id") or ""
                bundle_target = c.input.get("bundle_target") or ""
                if bundle_target and not manuscript_id:
                    raise ValueError(
                        "revision: bundle_target was set but manuscript_id is empty — "
                        "pick a manuscript first, or send raw input.text."
                    )
                if manuscript_id and not bundle_target:
                    raise ValueError(
                        "revision: manuscript_id was set but bundle_target is empty — "
                        "either select a target file inside the bundle, or send input.text."
                    )
                if manuscript_id and bundle_target:
                    raise ValueError(
                        "revision: target file is empty after pre-read "
                        f"(manuscript={manuscript_id}, bundle_target={bundle_target}). "
                        "The file may be missing or empty; create/seed it first."
                    )
                raise ValueError(
                    "revision needs input.text, or input.manuscript_id + bundle_target."
                )
            comments = _normalise_comments(c.input.get("comments"))
            if not comments:
                # An empty comments list is legal but we record one synthetic
                # comment so the change-log always has something to match.
                comments = [
                    ReviewerComment(
                        id="c1", category="general", text=c.query or "Polish the prose."
                    )
                ]
            c.state["original"] = text
            c.state["comments"] = [cm.to_dict() for cm in comments]

        await self.stage(ctx, "validate", inner)

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            # Soft-fail safety net: empty default before the network call
            # so a recall outage degrades to "no related papers in prompt"
            # instead of failing the whole revision task.
            c.state["papers"] = []
            if c.memory is None:
                return
            # Combine the instruction with the passage for a richer recall cue.
            cue = f"{c.query or ''}\n{c.state.get('original', '')[:400]}".strip()
            snap = await c.memory.snapshot(
                cue,
                domain=c.input.get("domain", "revision"),
                k=int(c.input.get("recall_k") or 6),
                session_id=c.session_id,
            )
            c.state["papers"] = list(snap.related_papers)
            await c.emit(
                Event(
                    EventType.MEMORY_READ,
                    data={
                        "papers": len(snap.related_papers),
                        "doc_chunks": len(snap.doc_chunks),
                    },
                )
            )

        await self.stage_soft(ctx, "recall", inner)

    async def _audit_original(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            audit = await audit_citations(c, text=c.state.get("original", ""), stage="revision:original")
            c.state["_audit_original_suspect"] = list(audit.suspect_citations)

        await self.stage(ctx, "audit_original", inner)

    async def _analyze(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            comments = c.state.get("comments", [])
            plan: list[dict[str, str]] = []
            raw_json: dict[str, Any] | None = None
            if c.llm is not None:
                try:
                    raw = await _ask(
                        c,
                        system=_ANALYZE_SYSTEM,
                        user=_ANALYZE_USER.format(
                            instruction=c.query or "Apply reviewer comments.",
                            section=c.input.get("section", ""),
                            comments=_format_comments(comments),
                            text=c.state["original"],
                        ),
                        # Reviewer-comment triage is structured planning —
                        # opt into the reasoning route when available.
                        route="reasoning",
                    )
                    raw_json = _extract_json_object(raw)
                except Exception as exc:
                    await c.emit(
                        Event(
                            EventType.TASK_RETRY,
                            data={"stage": "analyze", "fallback": "template", "message": str(exc)},
                        )
                    )
            if isinstance(raw_json, dict):
                candidates = raw_json.get("plan") or []
                for item in candidates if isinstance(candidates, list) else []:
                    if not isinstance(item, dict):
                        continue
                    cid = str(item.get("comment_id") or "")
                    decision = str(item.get("decision") or "accept")
                    action = str(item.get("action") or "").strip()
                    if cid:
                        plan.append({"comment_id": cid, "decision": decision, "action": action})
            if not plan:
                plan = [
                    {"comment_id": cm["id"], "decision": "accept", "action": cm["text"]}
                    for cm in comments
                ]
            c.state["plan"] = plan

        await self.stage(ctx, "analyze", inner)

    async def _revise(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            plan = c.state.get("plan", [])
            comments_by_id = {cm["id"]: cm for cm in c.state.get("comments", [])}
            papers: list[PaperCard] = c.state.get("papers", [])
            goals = c.input.get("goals") or []

            revised = ""
            if c.llm is not None:
                try:
                    revised = await _ask(
                        c,
                        system=_REVISE_SYSTEM,
                        user=_REVISE_USER.format(
                            instruction=c.query or "Apply reviewer comments.",
                            section=c.input.get("section", ""),
                            goals=", ".join(goals) if goals else "(none)",
                            plan=_format_plan(plan, comments_by_id),
                            papers=_format_papers(papers),
                            text=c.state["original"],
                        ),
                        # Actually rewriting the manuscript while honouring
                        # reviewer asks + citation discipline is the most
                        # quality-sensitive step in this workflow.
                        route="reasoning",
                    )
                except Exception as exc:
                    await c.emit(
                        Event(
                            EventType.TASK_RETRY,
                            data={"stage": "revise", "fallback": "template", "message": str(exc)},
                        )
                    )
            if not revised.strip():
                revised = _template_revision(
                    original=c.state["original"], plan=plan, comments=comments_by_id
                )

            c.state["revised"] = revised.strip() + "\n"
            c.state["change_log"] = _build_change_log(
                plan=plan,
                comments=comments_by_id,
                original=c.state["original"],
                revised=c.state["revised"],
            )
            audit = await audit_citations(c, text=c.state["revised"], stage="revision:revised")
            c.state["citations"] = audit.paper_ids
            # P14.1: merge suspect citations
            orig_suspect: list[dict[str, str]] = c.state.get("_audit_original_suspect", [])
            all_suspect = orig_suspect + list(audit.suspect_citations)
            seen: set[str] = set()
            deduped: list[dict[str, str]] = []
            for s in all_suspect:
                if s["key"] not in seen:
                    seen.add(s["key"])
                    deduped.append(s)
            # Auto-fix: research missing papers
            if deduped:
                deduped = await auto_fix_suspects(c, deduped)
            c.state["suspect_citations"] = deduped

        await self.stage(ctx, "revise", inner)


    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query or "Revision",
                outcomes={
                    "verdict": "ok",
                    "kind": "revision",
                    "section": c.input.get("section", ""),
                    "comments_addressed": [
                        cl["comment_id"]
                        for cl in c.state.get("change_log", [])
                        if cl.get("decision") != "defer"
                    ],
                    "comments_open": [
                        cl["comment_id"]
                        for cl in c.state.get("change_log", [])
                        if cl.get("decision") == "defer"
                    ],
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
            await c.emit(Event(EventType.MEMORY_WRITE, data={"kind": "reflection"}))

        # P12.1: reflections are best-effort writes. A memory outage
        # shouldn't roll back the revision result the user is about to
        # see — degrade to a warning instead.
        await self.stage_soft(ctx, "reflect", inner)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_comments(comments: list[dict[str, str]]) -> str:
    return "\n".join(f"- [{c['id']} | {c['category']}] {c['text']}" for c in comments)


def _format_plan(plan: list[dict[str, str]], comments_by_id: dict[str, dict[str, str]]) -> str:
    lines: list[str] = []
    for item in plan:
        cid = item["comment_id"]
        orig = comments_by_id.get(cid, {}).get("text", "")
        lines.append(
            f"- [{cid}] decision={item['decision']} — action: {item['action']} (comment: {orig})"
        )
    return "\n".join(lines) if lines else "(no plan)"


def _template_revision(
    *, original: str, plan: list[dict[str, str]], comments: dict[str, dict[str, str]]
) -> str:
    notes = []
    for item in plan:
        cid = item["comment_id"]
        txt = comments.get(cid, {}).get("text", "")
        if item.get("decision") == "defer":
            continue
        notes.append(f"- ({cid}) {item.get('action') or txt}")
    appendix = "\n".join(notes)
    if appendix:
        return (
            f"{original.strip()}\n\n"
            f"_Revision notes (template fallback — no LLM wired):_\n{appendix}\n"
        )
    return original


def _build_change_log(
    *,
    plan: list[dict[str, str]],
    comments: dict[str, dict[str, str]],
    original: str,
    revised: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in plan:
        cid = item["comment_id"]
        comment_text = comments.get(cid, {}).get("text", "")
        out.append(
            {
                "comment_id": cid,
                "comment": comment_text,
                "decision": item.get("decision", "accept"),
                "action": item.get("action", ""),
                "changed": original.strip() != revised.strip(),
            }
        )
    return out


def _citations_in(text: str, papers: list[PaperCard]) -> set[str]:
    valid = {p.paper_id for p in papers}
    return {m.group(1) for m in _CITE_RE.finditer(text or "") if m.group(1) in valid}


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    stripped = text.strip()
    for candidate in (stripped, *(m.group(1) for m in _JSON_FENCE_RE.finditer(stripped))):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj
    # Last resort: find first balanced { ... } block.
    start = stripped.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(stripped[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return obj if isinstance(obj, dict) else None
    return None


__all__ = ["RevisionWorkflow"]
