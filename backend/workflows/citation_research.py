"""CitationResearchWorkflow — upload a paper PDF, extract all references,
research each one, and store as PaperCard memory cards.

Stages:
1. validate       — check PDF + extract full text via pdf__parse
2. extract_refs   — LLM extracts structured reference list from bibliography
3. research       — search each reference via Google Scholar MCP → arxiv,
                    create PaperCard, backfill bibtex, write to knowledge store
4. reflect        — write episodic memory reflection

Output:
    {
      "paper_title": "...",
      "total_refs": 35,
      "found": [{"paper_id", "title", "confidence"}],
      "not_found": [{"index", "title", "reason"}],
      "low_confidence": [{"paper_id", "matched_title", "original_title"}]
    }
"""

from __future__ import annotations

import asyncio
import re
from difflib import SequenceMatcher
from typing import Any

from backend.core.events import Event, EventType
from backend.memory.base import stable_id
from backend.memory.models import PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .citation_guard import backfill_card_metadata
from .primitives import sequential
from .research import _hit_to_card

_MAX_CONCURRENT = 3
_SIMILARITY_THRESHOLD = 0.6

_EXTRACT_REFS_SYSTEM = (
    "You are a precise academic metadata extractor. "
    "Extract EVERY reference from the bibliography section below. "
    "For each reference, provide: index (1-based), title, authors (as a list), year. "
    "If a field is missing, use null. "
    "Output STRICT JSON array only — no markdown, no explanation."
)

_EXTRACT_REFS_USER = (
    "Extract all references from the following bibliography text. "
    "Return a JSON array where each element has keys: index (int), "
    "title (str|null), authors (list[str]|null), year (int|null).\n\n"
    "Bibliography text:\n---\n{text}\n---"
)


def _title_similarity(a: str, b: str) -> float:
    """Case-insensitive title similarity score."""
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _best_match(ref_title: str, results: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Pick the best matching result by title similarity."""
    if not results:
        return None
    scored = sorted(
        results,
        key=lambda r: _title_similarity(ref_title, r.get("Title", "")),
        reverse=True,
    )
    best = scored[0]
    score = _title_similarity(ref_title, best.get("Title", ""))
    best["_match_score"] = round(score, 3)
    return best if score >= _SIMILARITY_THRESHOLD else None


class CitationResearchWorkflow(BaseWorkflow):
    name = "citation-research"
    version = "0.1.0"

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [self._validate, self._extract_refs, self._research, self._reflect],
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
            "paper_title": ctx.state.get("paper_title", ""),
            "total_refs": len(ctx.state.get("refs", [])),
            "found": ctx.state.get("found", []),
            "not_found": ctx.state.get("not_found", []),
            "low_confidence": ctx.state.get("low_confidence", []),
        }
        verdict = "ok" if results["found"] else "empty"
        await ctx.emit(Event(EventType.TASK_END, data={
            "verdict": verdict,
            "found": len(results["found"]),
            "not_found": len(results["not_found"]),
        }))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict=verdict,
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ---- stages ----------------------------------------------------------

    async def _validate(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            text = (c.input.get("text") or "").strip()
            if not text:
                # Try to get PDF text from manuscript bundle
                bundle_target = c.input.get("bundle_target") or ""
                if bundle_target and c.bundle:
                    try:
                        text = await c.bundle.read_text(bundle_target)
                    except Exception:
                        pass
                if not text:
                    raise ValueError(
                        "citation-research needs input.text (PDF full text) "
                        "or input.bundle_target pointing to a PDF file in the manuscript."
                    )
            # Extract bibliography section for LLM processing
            bib_text = _extract_bibliography_section(text)
            c.state["full_text"] = text
            c.state["bib_text"] = bib_text
            c.state["refs"] = []
            c.state["found"] = []
            c.state["not_found"] = []
            c.state["low_confidence"] = []
        await self.stage(ctx, "validate", inner)

    async def _extract_refs(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.llm is None:
                raise ValueError("citation-research requires an LLM for reference extraction")
            bib_text = c.state.get("bib_text", "")
            if not bib_text:
                c.state["refs"] = []
                return

            # Use LLM to parse references
            from backend.core.llm.base import ChatMessage
            import json as _json

            messages = [
                ChatMessage(role="system", content=_EXTRACT_REFS_SYSTEM),
                ChatMessage(role="user", content=_EXTRACT_REFS_USER.format(text=bib_text[:32000])),
            ]
            raw = ""
            try:
                stream = await c.llm.complete(messages, temperature=0.1)
                async for chunk in stream:
                    if chunk.type == "delta" and chunk.delta:
                        raw += chunk.delta
                await c.emit(Event(EventType.TASK_PROGRESS, data={
                    "stage": "extract_refs", "raw_length": len(raw),
                }))
            except Exception as exc:
                await c.emit(Event(EventType.TASK_WARNING, data={
                    "stage": "extract_refs", "error": f"{type(exc).__name__}: {exc}",
                }))
                c.state["refs"] = []
                return

            # Parse JSON array from LLM output
            m = re.search(r"\[[\s\S]*\]", raw)
            refs: list[dict[str, Any]] = []
            if m:
                try:
                    refs = _json.loads(m.group(0))
                except _json.JSONDecodeError:
                    pass
            c.state["refs"] = refs
            await c.emit(Event(EventType.TASK_PROGRESS, data={
                "stage": "extract_refs", "count": len(refs),
            }))
        await self.stage(ctx, "extract_refs", inner)

    async def _research(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            refs: list[dict[str, Any]] = c.state.get("refs", [])
            if not refs:
                return
            if c.tools is None:
                await c.emit(Event(EventType.TASK_WARNING, data={
                    "stage": "research", "error": "No tool registry available",
                }))
                return
            if c.memory is None:
                await c.emit(Event(EventType.TASK_WARNING, data={
                    "stage": "research", "error": "No memory subsystem available",
                }))
                return

            semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
            found: list[dict[str, Any]] = []
            not_found: list[dict[str, Any]] = []
            low_confidence: list[dict[str, Any]] = []
            cards: list[PaperCard] = []

            async def _research_one(ref: dict[str, Any]) -> None:
                async with semaphore:
                    idx = ref.get("index", 0)
                    title = (ref.get("title") or "").strip()
                    authors = ref.get("authors") or []
                    year = ref.get("year")

                    if not title:
                        not_found.append({"index": idx, "title": title or "(no title)", "reason": "no title"})
                        return

                    # Build search query
                    first_author = authors[0] if authors else ""
                    query = f"{title} {first_author}"
                    if year:
                        query += f" {year}"

                    # Search: try Google Scholar MCP first, then arxiv
                    search_results: list[dict[str, Any]] = []
                    source = "none"

                    # Try Google Scholar MCP
                    if c.tools.has("mcp__google-scholar__search_google_scholar_key_words"):
                        try:
                            result = await c.tools.call(
                                "mcp__google-scholar__search_google_scholar_key_words",
                                {"query": query, "num_results": 3},
                            )
                            if result.ok and result.data:
                                search_results = list(result.data.get("results", []))
                                source = "google-scholar"
                        except Exception:
                            pass

                    # Fallback to arxiv
                    if not search_results and c.tools.has("arxiv__search"):
                        try:
                            result = await c.tools.call(
                                "arxiv__search",
                                {"query": title[:200], "max_results": 3},
                            )
                            if result.ok and result.data:
                                hits = list(result.data.get("results") or [])
                                # Convert arxiv format to match Google Scholar format
                                search_results = [
                                    {
                                        "Title": h.get("title", ""),
                                        "Authors": ", ".join(h.get("authors", [])),
                                        "Abstract": h.get("summary", ""),
                                        "URL": h.get("entry_id", ""),
                                    }
                                    for h in hits
                                ]
                                source = "arxiv"
                        except Exception:
                            pass

                    if not search_results:
                        not_found.append({
                            "index": idx, "title": title, "reason": "no search results",
                        })
                        return

                    # Match best result
                    match = _best_match(title, search_results)
                    if match is None:
                        not_found.append({
                            "index": idx, "title": title, "reason": "no good match",
                        })
                        return

                    score = match.get("_match_score", 0)
                    confidence = "high" if score >= 0.85 else "low"

                    # Create PaperCard
                    matched_title = match.get("Title", "")
                    matched_authors = match.get("Authors", "")
                    matched_abstract = match.get("Abstract", "")
                    paper_id = stable_id("gs", matched_title or title, first_author, year)

                    card = PaperCard(
                        paper_id=paper_id,
                        title=matched_title or title,
                        authors=[a.strip() for a in matched_authors.split(",") if a.strip()] if matched_authors else authors,
                        year=int(year) if year else None,
                        abstract=matched_abstract,
                        summary=matched_abstract[:800],
                        url=match.get("URL", ""),
                        source_run_id=f"{c.task_id}:cite",
                        user_id=c.user_id,
                    )

                    # Write to knowledge store + backfill bibtex
                    try:
                        await c.memory.knowledge.write_card(card)
                        card = await backfill_card_metadata(c, card)
                        cards.append(card)
                    except Exception:
                        pass

                    entry = {
                        "paper_id": card.paper_id,
                        "title": card.title,
                        "matched_title": matched_title,
                        "confidence": confidence,
                        "source": source,
                    }
                    if confidence == "high":
                        found.append(entry)
                    else:
                        low_confidence.append(entry)

                    await c.emit(Event(EventType.TASK_PROGRESS, data={
                        "stage": "research", "ref": idx, "match_score": score, "source": source,
                    }))

            await asyncio.gather(*(_research_one(ref) for ref in refs))

            c.state["found"] = found
            c.state["not_found"] = not_found
            c.state["low_confidence"] = low_confidence
            c.state["papers"] = cards
        await self.stage(ctx, "research", inner)

    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver
            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query or "Citation Research",
                outcomes={
                    "verdict": "ok",
                    "kind": "citation-research",
                    "found": len(c.state.get("found", [])),
                    "not_found": len(c.state.get("not_found", [])),
                    "low_confidence": len(c.state.get("low_confidence", [])),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
        await self.stage_soft(ctx, "reflect", inner)


def _extract_bibliography_section(text: str) -> str:
    """Heuristic: extract the bibliography/references section from full text."""
    patterns = [
        # Start patterns (case-insensitive)
        (r"(?im)^\s*(?:References|Bibliography|REFERENCES|BIBLIOGRAPHY)\s*$", None),
        (r"(?im)^\s*\[\d+\]\s+.*", None),  # [1] style
    ]

    # Try to find explicit section headers
    ref_patterns = [
        r"(?im)^\s*(?:References|Bibliography|REFERENCES|BIBLIOGRAPHY)\s*$\n",
        r"(?im)^\s*REFERENCES\b",
        r"(?im)^\s*Bibliography\b",
        r"(?im)^\s*Literature\s*Cited\b",
    ]

    best_start = len(text)  # default: last 30% of text
    for pat in ref_patterns:
        m = re.search(pat, text)
        if m and m.start() < best_start:
            best_start = m.start()

    if best_start >= len(text):
        # Fallback: use last 30% of the text
        best_start = int(len(text) * 0.7)

    bib = text[best_start:]
    # Cap at 16000 chars — enough for a typical reference list
    return bib[:16000]
