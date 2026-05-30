r"""WriteWorkflow — generate an academic section from a topic.

Produces a publication-style draft of *one* section (introduction,
related work, method, …) grounded in the user's own knowledge base.

Stages:

1. ``recall``   — read :class:`MemorySnapshot`; pick the top-k PaperCards
   that match the topic.
2. ``outline``  — ask the LLM for a tight bullet outline (H2/H3 only);
   parsed into a list of headings. Falls back to a template outline when
   no LLM is wired or the response cannot be parsed.
3. ``draft``    — one LLM call per outline item, constrained to cite only
   the recalled PaperCards. Results are concatenated into a markdown doc.
4. ``reflect``  — writes one episodic reflection summarising the run.

Output shape::

    {
      "section":     "<input.section | default 'section'>",
      "topic":       ctx.query,
      "outline":     ["H1", "H2", ...],
      "markdown":    "<full markdown>",
      "citations":   [paper_id, ...],
      "word_count":  int,
    }

Everything degrades gracefully: with no LLM, we emit the outline template
and stitch PaperCard summaries into a draft. That lets the workflow be
exercised end-to-end in CI without ever touching a model.

P8 — bundle-aware mode (handled outside this module, in
``backend.tasks.runner``):

* When ``input.manuscript_id`` points at a *bundle* manuscript and
  ``input.bundle_target`` is set (e.g.
  ``"overleaf/sections/related-work.tex"``), the runner writes
  ``results.markdown`` to that file *atomically* (size-cap-checked) and
  emits a ``manuscript.bundle_write`` event so the BundleExplorer can
  refresh.
* When ``input.register_in_main`` is true (default false) and the
  bundle has a top-level ``overleaf/main.tex`` whose body contains a
  ``\end{document}`` marker, the runner inserts an ``\input{<rel>}`` line
  immediately before the document end. The relative path is derived
  from ``bundle_target`` (the section path without the leading
  ``overleaf/`` and without the ``.tex`` extension) so it matches LaTeX
  conventions. Failures degrade silently — the section file write
  always succeeds first; main.tex is decorative.
* For *single*-layout manuscripts (the pre-P7 default) the runner falls
  back to the legacy ``store.commit_version`` path and the output is
  appended as a new ``ManuscriptVersion``.

The workflow body itself never reads ``manuscript_id`` /
``bundle_target`` / ``register_in_main`` — they are pure runner
contract.
"""

from __future__ import annotations

import re
from typing import Any

from backend.core.context.history import load_history_block
from backend.core.events import Event, EventType
from backend.memory.models import MemorySnapshot, PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import audit_citations, auto_fix_suspects
from .primitives import sequential

_DEFAULT_SECTION = "section"
_DEFAULT_LENGTH = 600  # words
_DEFAULT_STYLE = "academic"
_DEFAULT_RECALL_K = 8

_OUTLINE_SYSTEM = (
    "You are a senior academic writer drafting one section of a research paper. "
    "Produce a tight, non-repetitive outline — NEVER write prose."
)
_OUTLINE_USER = (
    "Topic: {topic}\nSection: {section}\nTarget length: {length} words\nStyle: {style}\n\n"
    "Return 3 to 6 outline bullets as a plain numbered list (no prose, no sub-bullets). "
    "Each bullet is 6 to 14 words describing one subsection heading.\n\n"
    "Relevant prior literature (use these paper_ids when citing):\n{papers}"
)

_DRAFT_SYSTEM = (
    "You are a senior academic writer drafting one subsection. Write fluent, "
    "grounded prose. Cite only the provided paper_ids using square brackets, "
    "e.g. [aaa111]. Do not invent references."
)
_DRAFT_USER = (
    "Topic: {topic}\nSection: {section}\nSubsection heading: {heading}\n"
    "Approximate length: {length} words.\n\n"
    "Relevant papers:\n{papers}\n\n"
    "Write the subsection in markdown. Start with an `## {heading}` header."
)


class WriteWorkflow(BaseWorkflow):
    """Four-stage generator for one paper section."""

    name = "write"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [self._recall, self._outline, self._draft, self._reflect],
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

        results: dict[str, Any] = {
            "section": ctx.input.get("section", _DEFAULT_SECTION),
            "topic": ctx.query,
            "outline": ctx.state.get("outline", []),
            "markdown": ctx.state.get("markdown", ""),
            "citations": sorted(ctx.state.get("citations", set())),
            "word_count": _word_count(ctx.state.get("markdown", "")),
            "suspect_citations": ctx.state.get("suspect_citations", []),
        }
        await ctx.emit(
            Event(
                EventType.TASK_END,
                data={"verdict": "ok", "word_count": results["word_count"]},
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

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            k = int(c.input.get("recall_k") or _DEFAULT_RECALL_K)
            # Soft-fail safety net: empty snapshot + empty papers set
            # *before* the network call so a transient recall outage
            # degrades gracefully to "no recalled context" instead of
            # aborting the write task.
            c.state["recall"] = MemorySnapshot(query=c.query)
            c.state["papers"] = []
            if c.memory is None:
                return
            snap = await c.memory.snapshot(
                c.query,
                domain=c.input.get("domain", "writing"),
                k=k,
                session_id=c.session_id,
            )
            c.state["recall"] = snap
            c.state["papers"] = list(snap.related_papers[:k])
            await c.emit(
                Event(
                    EventType.MEMORY_READ,
                    data={
                        "papers": len(snap.related_papers),
                        "heuristics": len(snap.heuristics),
                        "doc_chunks": len(snap.doc_chunks),
                    },
                )
            )

        await self.stage_soft(ctx, "recall", inner)

    async def _outline(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            section = c.input.get("section", _DEFAULT_SECTION)
            length = int(c.input.get("length") or _DEFAULT_LENGTH)
            style = c.input.get("style", _DEFAULT_STYLE)
            papers: list[PaperCard] = c.state.get("papers", [])

            outline: list[str] | None = None
            if c.llm is not None:
                try:
                    raw = await _ask(
                        c,
                        system=_OUTLINE_SYSTEM,
                        user=_OUTLINE_USER.format(
                            topic=c.query,
                            section=section,
                            length=length,
                            style=style,
                            papers=_format_papers(papers),
                        ),
                        # Outlining is a structured planning step — opt into the
                        # reasoning route when available; falls back to default
                        # for deployments that don't define it.
                        route="reasoning",
                    )
                    outline = _parse_outline(raw)
                except Exception as exc:  # LLM can legitimately refuse
                    await c.emit(
                        Event(
                            EventType.TASK_RETRY,
                            data={
                                "stage": "outline",
                                "fallback": "template",
                                "message": str(exc),
                            },
                        )
                    )
            if not outline:
                outline = _template_outline(section, papers)
            c.state["outline"] = outline

        await self.stage(ctx, "outline", inner)

    async def _draft(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            section = c.input.get("section", _DEFAULT_SECTION)
            length = int(c.input.get("length") or _DEFAULT_LENGTH)
            outline: list[str] = c.state.get("outline", [])
            papers: list[PaperCard] = c.state.get("papers", [])
            per_heading = max(80, length // max(1, len(outline) or 1))
            papers_block = _format_papers(papers)

            parts: list[str] = [f"# {section.title()}: {c.query}\n"]
            for heading in outline:
                text = ""
                if c.llm is not None:
                    try:
                        text = await _ask(
                            c,
                            system=_DRAFT_SYSTEM,
                            user=_DRAFT_USER.format(
                                topic=c.query,
                                section=section,
                                heading=heading,
                                length=per_heading,
                                papers=papers_block,
                            ),
                            # Drafting prose with citation discipline is the
                            # most quality-sensitive step in this workflow —
                            # explicitly opt into the reasoning route.
                            route="reasoning",
                        )
                    except Exception as exc:
                        await c.emit(
                            Event(
                                EventType.TASK_RETRY,
                                data={
                                    "stage": "draft",
                                    "heading": heading,
                                    "message": str(exc),
                                },
                            )
                        )
                if not text.strip():
                    text = _template_subsection(heading, papers)
                parts.append(text.strip())

            markdown = "\n\n".join(parts).strip() + "\n"
            c.state["markdown"] = markdown
            audit = await audit_citations(c, text=markdown, stage="write:draft")
            c.state["citations"] = audit.paper_ids
            suspects = list(audit.suspect_citations)
            if suspects:
                suspects = await auto_fix_suspects(c, suspects)
            c.state["suspect_citations"] = suspects

        await self.stage(ctx, "draft", inner)

    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query,
                outcomes={
                    "verdict": "ok",
                    "kind": "write",
                    "section": c.input.get("section", _DEFAULT_SECTION),
                    "word_count": _word_count(c.state.get("markdown", "")),
                    "outline": c.state.get("outline", []),
                    "citations": sorted(c.state.get("citations", set())),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
            await c.emit(Event(EventType.MEMORY_WRITE, data={"kind": "reflection"}))

        # P12.1: best-effort write — the draft has already been
        # produced and surfacing it matters more than recording the
        # reflection. Soft-fail keeps the task in "ok" verdict.
        await self.stage_soft(ctx, "reflect", inner)


# ---------------------------------------------------------------------------
# Helpers — public enough for tests
# ---------------------------------------------------------------------------


async def _ask(
    ctx: WorkflowContext,
    *,
    system: str,
    user: str,
    route: str | None = None,
) -> str:
    """Collect a streaming completion into a single string.

    When ``route`` is given AND ``ctx.llm`` is a router that exposes
    ``for_route``, the call is delegated to the named sub-provider so
    that telemetry tags it with the route name. Plain providers ignore
    ``route`` (degrade to default behaviour) — the caller never has to
    know whether routing is enabled.
    """

    from backend.core.errors import LLMAPIError
    from backend.core.llm.base import ChatMessage

    if ctx.llm is None:
        raise LLMAPIError("no LLM provider wired on this workflow context")
    provider = ctx.llm
    if route is not None:
        for_route = getattr(provider, "for_route", None)
        if callable(for_route):
            provider = for_route(route)
    messages = [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=user),
    ]
    stream = await provider.complete(messages)
    parts: list[str] = []
    async for chunk in stream:
        if chunk.type == "delta" and chunk.delta:
            parts.append(chunk.delta)
            # Emit streaming progress so the UI can show real-time generation
            await ctx.emit(Event(
                EventType.TASK_PROGRESS,
                data={"stage": "llm_stream", "delta": chunk.delta},
            ))
        elif chunk.type == "error":
            raise LLMAPIError(chunk.error or "llm error")
        elif chunk.type == "done" and chunk.usage is not None:
            ctx.budget.accrue_llm(
                prompt_tokens=chunk.usage.prompt_tokens or 0,
                completion_tokens=chunk.usage.completion_tokens or 0,
            )
    return "".join(parts)


_BULLET_RE = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*(.+?)\s*$")


def _parse_outline(raw: str) -> list[str]:
    items: list[str] = []
    for line in (raw or "").splitlines():
        m = _BULLET_RE.match(line)
        if m:
            heading = m.group(1).strip().strip("`*_")
            if heading:
                items.append(heading)
    return items[:8]


def _template_outline(section: str, papers: list[PaperCard]) -> list[str]:
    sec = section.lower()
    if "intro" in sec:
        return ["Motivation and problem setting", "Prior work and gaps", "Our contribution"]
    if "related" in sec:
        tags = _dominant_tags(papers)[:3]
        if tags:
            return [f"Line of work: {t}" for t in tags] + ["Positioning of our work"]
        return ["Foundational methods", "Recent advances", "Open questions"]
    if "method" in sec or "approach" in sec:
        return ["Overview", "Formulation", "Algorithm", "Implementation details"]
    if "experiment" in sec or "eval" in sec:
        return ["Setup", "Baselines", "Main results", "Ablations"]
    return ["Overview", "Key points", "Summary"]


def _template_subsection(heading: str, papers: list[PaperCard]) -> str:
    evidence = ""
    if papers:
        sample = papers[0]
        evidence = f" Prior work such as *{sample.title}* [{sample.paper_id}] motivates this line."
    return f"## {heading}\n\nTBD — {heading.lower()}.{evidence}"


def _format_papers(papers: list[PaperCard]) -> str:
    if not papers:
        return "(no prior papers recalled)"
    lines: list[str] = []
    for p in papers[:8]:
        snippet = (p.summary or p.abstract or "").replace("\n", " ")[:280]
        lines.append(f"- {{paper:{p.paper_id}}} {p.title} ({p.year or '?'}) — {snippet}")
    return "\n".join(lines)


def _dominant_tags(papers: list[PaperCard]) -> list[str]:
    counts: dict[str, int] = {}
    for p in papers:
        for t in p.tags:
            counts[t] = counts.get(t, 0) + 1
    return sorted(counts, key=lambda t: counts[t], reverse=True)


_CITE_RE = re.compile(r"\[([0-9a-f]{6,16})\]")


def _extract_citations(markdown: str, papers: list[PaperCard]) -> set[str]:
    valid = {p.paper_id for p in papers}
    return {m.group(1) for m in _CITE_RE.finditer(markdown) if m.group(1) in valid}


def _word_count(text: str) -> int:
    return len([w for w in re.findall(r"\b[\w'-]+\b", text or "") if w])


__all__ = ["WriteWorkflow"]
