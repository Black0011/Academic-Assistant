"""PeerReviewWorkflow — structured pre-submission audit of an entire paper project.

Follows the three-stage process defined in ``skills/peer-review/SKILL.md``:

1. **Preliminary** — 5 key questions, elevator-pitch summary
2. **Section-by-section** — Abstract, Introduction, Methods, Results, Discussion,
   Reproducibility, each scored ✓ / ⚠ / ❌
3. **Methodology & Bias/Fallacy** — statistical rigour, 4 bias types, 5 fallacy types

Input contract (via ``ctx.input``):
* ``manuscript_id`` — bundle manuscript to audit.
* ``text`` — pre-read by the runner from all bundle text files (concatenated with
  file markers). The workflow itself only consumes ``text``.

Output::

    {
      "preliminary":     { "summary": "...", "verdict_guess": "..." },
      "section_review":  [ { "section": "...", "score": "✓|⚠|❌", "notes": "..." } ],
      "major_issues":    [ { "location": "...", "finding": "...", "impact": "...", "fix": "..." } ],
      "minor_issues":    [ { "location": "...", "finding": "...", "fix": "..." } ],
      "bias_audit":      [ { "type": "...", "location": "...", "finding": "...", "fix": "..." } ],
      "fallacy_audit":   [ { "type": "...", "location": "...", "finding": "...", "fix": "..." } ],
      "rating":          1–10,
      "verdict":         "Accept | Minor Revision | Major Revision | Reject",
      "strategic_advice": { "p1": [...], "p2": [...], "p3": [...] },
      "citations":       [...],
      "suspect_citations": [...],
    }
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.events import Event, EventType
from backend.memory.models import PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import audit_citations
from .primitives import sequential
from .write import _ask, _format_papers

# ── prompt templates ────────────────────────────────────────────────────────

_PRELIMINARY_SYSTEM = (
    "You are a senior PC member for a top-tier CS/NLP conference. "
    "Read the following paper and answer 5 key questions concisely. "
    "Be critical but constructive. Output STRICT JSON only."
)

_PRELIMINARY_USER = (
    "Paper text:\n---\n{text}\n---\n\n"
    "Answer these 5 questions in JSON:\n"
    '{{\n'
    '  "research_question": "1. Core research question or hypothesis?",\n'
    '  "main_findings": "2. Main findings and conclusions?",\n'
    '  "significance": "3. Is the work scientifically sound and meaningful?",\n'
    '  "venue_fit": "4. Is it suitable for its target venue?",\n'
    '  "fatal_flaws": "5. Any obvious major flaws?",\n'
    '  "elevator_pitch": "2–3 sentence summary"\n'
    '}}'
)

_SECTION_SYSTEM = (
    "You are a senior academic reviewer performing a section-by-section audit. "
    "For each section, score ✓ (pass), ⚠ (minor issues), or ❌ (major issues). "
    "If ❌, the issue MUST be upgraded to a Major finding. "
    "Output STRICT JSON only."
)

_SECTION_USER = (
    "Paper text:\n---\n{text}\n---\n\n"
    "Audit these sections. For each, return score and specific notes.\n"
    'Return JSON:\n'
    '{{\n'
    '  "sections": [\n'
    '    {{"section": "Abstract & Title", "score": "✓|⚠|❌", '
    '"notes": "Is the abstract accurate? Is the title specific and informative?"}},\n'
    '    {{"section": "Introduction", "score": "✓|⚠|❌", '
    '"notes": "Background adequate? Research gap clearly motivated? Citations ≥5 recent?"}},\n'
    '    {{"section": "Methods", "score": "✓|⚠|❌", '
    '"notes": "Reproducible from description? Methods appropriate? Statistical methods correct?"}},\n'
    '    {{"section": "Results", "score": "✓|⚠|❌", '
    '"notes": "Results logically presented? Figures clear? All relevant results included?"}},\n'
    '    {{"section": "Discussion", "score": "✓|⚠|❌", '
    '"notes": "Conclusions data-supported? Limitations acknowledged? Speculation vs observation clear?"}},\n'
    '    {{"section": "Reproducibility", "score": "✓|⚠|❌", '
    '"notes": "Data/code available? Key parameters reported?"}}\n'
    '  ]\n'
    '}}'
)

_METHOD_SYSTEM = (
    "You are a senior methodologist auditing statistical rigour and experimental design. "
    "Check every claim for evidence support. Flag anything that would make a reviewer "
    "question the paper's validity. Output STRICT JSON only."
)

_METHOD_USER = (
    "Paper text:\n---\n{text}\n---\n\n"
    "Audit methodology and produce two lists (empty arrays if none found).\n"
    'Return JSON:\n'
    '{{\n'
    '  "major": [\n'
    '    {{"location": "section / paragraph hint", "finding": "objective description", '
    '"impact": "why a reviewer would question this", '
    '"fix": "concrete actionable suggestion"}}\n'
    '  ],\n'
    '  "minor": [\n'
    '    {{"location": "section / paragraph hint", "finding": "objective description", '
    '"fix": "concrete actionable suggestion"}}\n'
    '  ]\n'
    '}}'
)

_BIAS_SYSTEM = (
    "You are a research-integrity auditor. Check the paper for 4 bias types and "
    "5 logical fallacy types. Only flag issues that are clearly present — do not "
    "invent problems. Output STRICT JSON only."
)

_BIAS_USER = (
    "Paper text:\n---\n{text}\n---\n\n"
    "Check for these 4 bias types and 5 fallacy types. "
    "For each finding, give: type, location, finding (quote or paraphrase), "
    "impact (why it matters), fix (actionable suggestion). "
    "Use empty arrays if none found.\n\n"
    "### Bias types\n"
    "- confirmation: only emphasising supporting evidence, ignoring negative results\n"
    "- selection: sample not representative of target population\n"
    "- publication: missing null/neutral results\n"
    "- p_hacking: multiple analyses until significant result found\n\n"
    "### Fallacy types\n"
    "- post_hoc: B follows A, therefore A caused B (without ablation)\n"
    "- correlation_causation: confusing correlation with causation\n"
    "- hasty_generalisation: small sample → broad claim\n"
    "- cherry_picking: only showing supportive evidence\n"
    "- straw_man: attacking a position the original source never held\n\n"
    'Return JSON:\n'
    '{{\n'
    '  "bias": [\n'
    '    {{"type": "confirmation|selection|publication|p_hacking", '
    '"location": "...", "finding": "...", "impact": "...", "fix": "..."}}\n'
    '  ],\n'
    '  "fallacy": [\n'
    '    {{"type": "post_hoc|correlation_causation|hasty_generalisation|cherry_picking|straw_man", '
    '"location": "...", "finding": "...", "impact": "...", "fix": "..."}}\n'
    '  ]\n'
    '}}'
)

_VERDICT_SYSTEM = (
    "You are a senior PC member making a final acceptance decision. "
    "Based on the audit results below, assign a rating (1–10) and verdict. "
    "Output STRICT JSON only."
)

_VERDICT_USER = (
    "Audit summary:\n"
    "Preliminary: {preliminary}\n"
    "Section scores: {sections}\n"
    "Major issues ({major_count}): {major}\n"
    "Minor issues ({minor_count}): {minor}\n"
    "Bias findings ({bias_count}): {bias}\n"
    "Fallacy findings ({fallacy_count}): {fallacy}\n\n"
    "Rating scale:\n"
    "9–10: Top accept, 0 fatal + ≥2 substantial innovations + thorough experiments\n"
    "7–8: Accept, 0 fatal + ≥1 substantial innovation + adequate experiments\n"
    "5–6: Borderline, 1–2 fixable fatal + moderate innovation\n"
    "3–4: Reject (revisable), ≥3 fatal or thin innovation\n"
    "1–2: Hard reject, fundamental methodological errors or data fabrication risk\n\n"
    "≥1 fatal flaw → rating MUST be ≤7.\n\n"
    'Return JSON:\n'
    '{{\n'
    '  "rating": <int 1-10>,\n'
    '  "verdict": "Accept|Minor Revision|Major Revision|Reject",\n'
    '  "strategic_advice": {{\n'
    '    "p1": ["must fix before submission"],\n'
    '    "p2": ["should fix or reviewer will penalise"],\n'
    '    "p3": ["nice to fix if time permits"]\n'
    '  }}\n'
    '}}'
)

# ── helpers ─────────────────────────────────────────────────────────────────

def _safe_json(text: str) -> dict[str, Any]:
    """Extract JSON from LLM output, tolerating markdown fences."""
    text = (text or "").strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass
    return {}


class PeerReviewWorkflow(BaseWorkflow):
    """Structured pre-submission peer review of an entire paper project.

    Stages: recall → preliminary → section_review → methodology → bias_fallacy → verdict → reflect.
    """

    name = "peer-review"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [
                    self._recall,
                    self._preliminary,
                    self._section_review,
                    self._methodology,
                    self._bias_fallacy,
                    self._verdict,
                    self._reflect,
                ],
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

        text_all = ctx.state.get("text", "")
        audit = await audit_citations(ctx, text=text_all, stage="peer-review:full")
        ctx.state["citations"] = sorted(audit.paper_ids)
        ctx.state["suspect_citations"] = list(audit.suspect_citations)

        results: dict[str, Any] = {
            "preliminary": ctx.state.get("preliminary", {}),
            "section_review": ctx.state.get("section_review", []),
            "major_issues": ctx.state.get("major_issues", []),
            "minor_issues": ctx.state.get("minor_issues", []),
            "bias_audit": ctx.state.get("bias_audit", []),
            "fallacy_audit": ctx.state.get("fallacy_audit", []),
            "rating": ctx.state.get("rating"),
            "verdict": ctx.state.get("verdict", ""),
            "strategic_advice": ctx.state.get("strategic_advice", {}),
            "citations": sorted(ctx.state.get("citations", set())),
            "suspect_citations": ctx.state.get("suspect_citations", []),
        }
        await ctx.emit(
            Event(
                EventType.TASK_END,
                data={
                    "verdict": "ok",
                    "rating": results["rating"],
                    "major_count": len(results["major_issues"]),
                },
            )
        )
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict="ok",
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ── stages ──────────────────────────────────────────────────────────

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            c.state["papers"] = []
            if c.memory is None:
                return
            cue = (c.state.get("text", "") or "")[:800]
            if not cue.strip():
                return
            snap = await c.memory.snapshot(
                cue,
                domain="revision",
                k=10,
                session_id=c.session_id,
            )
            c.state["papers"] = list(snap.related_papers)
        await self.stage_soft(ctx, "recall", inner)

    async def _preliminary(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.state.get("text", "") or "")[:24000]  # cap for context
            if c.llm is None:
                c.state["preliminary"] = {"elevator_pitch": "[No LLM wired — template mode]"}
                return
            raw = await _ask(
                c,
                system=_PRELIMINARY_SYSTEM,
                user=_PRELIMINARY_USER.format(text=text),
                route="reasoning",
            )
            c.state["preliminary"] = _safe_json(raw)
        await self.stage(ctx, "preliminary", inner)

    async def _section_review(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.state.get("text", "") or "")[:24000]
            if c.llm is None:
                c.state["section_review"] = []
                return
            raw = await _ask(
                c,
                system=_SECTION_SYSTEM,
                user=_SECTION_USER.format(text=text),
                route="reasoning",
            )
            parsed = _safe_json(raw)
            c.state["section_review"] = parsed.get("sections", [])
            # Any ❌ in section review should feed into major issues
            for sec in c.state["section_review"]:
                if sec.get("score") == "❌":
                    existing = c.state.get("major_issues", [])
                    existing.append({
                        "location": sec.get("section", ""),
                        "finding": sec.get("notes", ""),
                        "impact": f"Section {sec.get('section', '')} scored ❌ — needs revision before submission.",
                        "fix": f"Address the issues noted in {sec.get('section', '')}.",
                    })
                    c.state["major_issues"] = existing
        await self.stage(ctx, "section_review", inner)

    async def _methodology(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.state.get("text", "") or "")[:24000]
            if c.llm is None:
                c.state["major_issues"] = []
                c.state["minor_issues"] = []
                return
            raw = await _ask(
                c,
                system=_METHOD_SYSTEM,
                user=_METHOD_USER.format(text=text),
                route="reasoning",
            )
            parsed = _safe_json(raw)
            existing_major = c.state.get("major_issues", [])
            existing_major.extend(parsed.get("major", []))
            c.state["major_issues"] = existing_major
            c.state["minor_issues"] = parsed.get("minor", [])
        await self.stage(ctx, "methodology", inner)

    async def _bias_fallacy(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.state.get("text", "") or "")[:24000]
            if c.llm is None:
                c.state["bias_audit"] = []
                c.state["fallacy_audit"] = []
                return
            raw = await _ask(
                c,
                system=_BIAS_SYSTEM,
                user=_BIAS_USER.format(text=text),
                route="reasoning",
            )
            parsed = _safe_json(raw)
            c.state["bias_audit"] = parsed.get("bias", [])
            c.state["fallacy_audit"] = parsed.get("fallacy", [])
            # Bias/fallacy findings with severity also go into major issues
            for item in c.state["bias_audit"]:
                if item.get("finding"):
                    existing = c.state.get("major_issues", [])
                    existing.append({
                        "location": item.get("location", ""),
                        "finding": f"[{item.get('type', 'bias')}] {item.get('finding', '')}",
                        "impact": item.get("impact", ""),
                        "fix": item.get("fix", ""),
                    })
                    c.state["major_issues"] = existing
        await self.stage(ctx, "bias_fallacy", inner)

    async def _verdict(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.llm is None:
                c.state["rating"] = None
                c.state["verdict"] = "Unable to rate — no LLM wired"
                c.state["strategic_advice"] = {}
                return
            major = c.state.get("major_issues", [])
            minor = c.state.get("minor_issues", [])
            bias = c.state.get("bias_audit", [])
            fallacy = c.state.get("fallacy_audit", [])
            raw = await _ask(
                c,
                system=_VERDICT_SYSTEM,
                user=_VERDICT_USER.format(
                    preliminary=json.dumps(c.state.get("preliminary", {}), ensure_ascii=False),
                    sections=json.dumps(c.state.get("section_review", []), ensure_ascii=False),
                    major_count=len(major),
                    major=json.dumps(major[:5], ensure_ascii=False),
                    minor_count=len(minor),
                    minor=json.dumps(minor[:5], ensure_ascii=False),
                    bias_count=len(bias),
                    bias=json.dumps(bias, ensure_ascii=False),
                    fallacy_count=len(fallacy),
                    fallacy=json.dumps(fallacy, ensure_ascii=False),
                ),
                route="reasoning",
            )
            parsed = _safe_json(raw)
            c.state["rating"] = parsed.get("rating")
            c.state["verdict"] = parsed.get("verdict", "")
            c.state["strategic_advice"] = parsed.get("strategic_advice", {})
        await self.stage(ctx, "verdict", inner)

    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query or "Peer Review",
                outcomes={
                    "verdict": "ok",
                    "kind": "peer-review",
                    "rating": c.state.get("rating"),
                    "decision": c.state.get("verdict", ""),
                    "major_count": len(c.state.get("major_issues", [])),
                    "minor_count": len(c.state.get("minor_issues", [])),
                    "bias_count": len(c.state.get("bias_audit", [])),
                    "fallacy_count": len(c.state.get("fallacy_audit", [])),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
        await self.stage_soft(ctx, "reflect", inner)


__all__ = ["PeerReviewWorkflow"]
