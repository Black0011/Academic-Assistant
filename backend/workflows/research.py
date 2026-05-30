"""End-to-end Research workflow with LLM-driven Agent loop.

Stages:

1. ``recall``        — read :class:`MemorySnapshot` for the query (best-effort).
2. ``agent_search``  — **Agent loop**: LLM plans search strategy, calls tools
   (``arxiv__search``, ``pdf__parse``) in a multi-round loop, collects results.
   Falls back to the legacy direct-search pipeline when no LLM is available.
3. ``ingest``        — build :class:`PaperCard` per paper and write them to
   ``KnowledgeStore`` + ``VectorStore``.
4. ``evolve``        — let :class:`PaperMemoryEvolver` add typed links / tags.
5. ``reflect``       — write one episodic reflection summarising the run.

The workflow runs entirely through the protocols injected on
:class:`WorkflowContext` (``tools``, ``memory``, ``llm``), so tests can
swap every collaborator for a mock.

Returns ``WorkflowOutput.results = {papers: [PaperCard.model_dump()], …}``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from backend.core.context.history import load_history_block
from backend.core.events import Event, EventType
from backend.memory.base import gen_id, stable_id
from backend.memory.models import PaperCard

from .base import BaseWorkflow, WorkflowContext, WorkflowOutput
from .primitives import sequential
from .write import _ask  # reused for LLM summarisation


class ResearchWorkflow(BaseWorkflow):
    name = "research"
    version = "0.2.0"

    # Public knobs — overridable via `ctx.input`.
    default_max_results: int = 5
    default_max_parse: int = 3
    default_pdf_pages: int = 8

    async def run(self, ctx: WorkflowContext) -> WorkflowOutput:
        await ctx.emit(Event(EventType.TASK_START, data={"query": ctx.query}))
        try:
            await sequential(
                ctx,
                [
                    self._recall,
                    self._agent_search,
                    self._ingest,
                    self._evolve,
                    self._reflect,
                    self._summarize,
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

        papers: list[PaperCard] = ctx.state.get("papers", [])
        summary = ctx.state.get("summary")
        results: dict[str, Any] = {
            "query": ctx.query,
            "count": len(papers),
            "papers": [p.model_dump(mode="json") for p in papers],
        }
        if summary:
            results["summary"] = summary
        verdict = "ok" if papers else "empty"
        await ctx.emit(Event(EventType.TASK_END, data={"verdict": verdict, "count": len(papers)}))
        return WorkflowOutput(
            task_id=ctx.task_id,
            verdict=verdict,
            results=results,
            trace=list(ctx.trace),
            budget=ctx.budget.snapshot(),
        )

    # ---- stages -----------------------------------------------------

    async def _recall(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            # Soft-fail default: research tolerates "no recalled context"
            # — it'll just go fetch fresh papers from the external search
            # tools without prior context. Better than failing the whole
            # discovery task because the vector store hiccupped.
            c.state.setdefault("memory_snapshot", None)
            if c.memory is None:
                return
            snap = await c.memory.snapshot(
                c.query,
                domain=c.input.get("domain", "research"),
                session_id=c.session_id,
            )
            c.state["memory_snapshot"] = snap
            await c.emit(
                Event(
                    EventType.MEMORY_READ,
                    data={
                        "papers": len(snap.related_papers),
                        "heuristics": len(snap.heuristics),
                        "reflections": len(snap.recent_reflections),
                        "doc_chunks": len(snap.doc_chunks),
                    },
                )
            )

        await self.stage_soft(ctx, "recall", inner)

    async def _agent_search(self, ctx: WorkflowContext) -> None:
        """LLM-driven search with legacy fallback.

        When ``ctx.llm`` and ``ctx.tools`` are both available, delegates to
        :class:`ResearchAgent` which uses the LLM to plan search strategy
        (translating non-English queries into English keywords), execute
        multi-round tool calls, and iteratively refine results.

        Without an LLM the legacy path runs: a single ``arxiv__search``
        with the raw query followed by ``pdf__parse`` on the top hits.
        """

        async def inner(c: WorkflowContext) -> None:
            if c.llm is not None and c.tools is not None:
                # Agent path — LLM plans and executes searches
                from backend.agents.research_agent import ResearchAgent

                max_rounds = int(c.input.get("max_rounds") or 5)
                agent = ResearchAgent(
                    llm=c.llm,
                    tools=c.tools,
                    max_rounds=max_rounds,
                    max_results_per_search=int(
                        c.input.get("max_results") or self.default_max_results
                    ),
                )
                hits = await agent.run(
                    c.query,
                    c.state.get("memory_snapshot"),
                    budget=c.budget,
                    emit=c.emit,
                )
                c.state["search_hits"] = hits
                # Agent handles its own PDF parsing via tool calls, so
                # ``parsed`` is populated from the tool results.
                c.state["parsed"] = []
                await c.emit(
                    Event(
                        "task.agent_search",
                        data={
                            "stage": "agent_search",
                            "mode": "agent",
                            "hits": len(hits),
                        },
                    )
                )
            else:
                # Legacy fallback — direct tool calls without LLM planning
                await self._search_legacy_inner(c)
                await self._parse_legacy_inner(c)
                await c.emit(
                    Event(
                        "task.agent_search",
                        data={
                            "stage": "agent_search",
                            "mode": "legacy",
                            "hits": len(c.state.get("search_hits", [])),
                        },
                    )
                )

        await self.stage(ctx, "agent_search", inner)

    # ---- legacy search / parse (fallback when no LLM) ------------------

    async def _search_legacy_inner(self, c: WorkflowContext) -> None:
        """Direct arxiv__search without LLM planning."""
        if c.tools is None:
            raise RuntimeError("research workflow requires a ToolRegistry on ctx.tools")
        max_results = int(c.input.get("max_results") or self.default_max_results)

        async def sink(event_type: str, data: dict[str, Any]) -> None:
            await c.emit(Event(event_type, data=data))

        result = await c.tools.call(
            "arxiv__search",
            {"query": c.query, "max_results": max_results},
            sink=sink,
        )
        if not result.ok:
            raise RuntimeError(f"arxiv search failed: {result.error}")
        data = result.data or {}
        hits = list(data.get("results") or [])
        c.state["search_hits"] = hits

    async def _parse_legacy_inner(self, c: WorkflowContext) -> None:
        """Parse top PDFs without LLM decision-making."""
        tools = c.tools
        assert tools is not None
        hits = c.state.get("search_hits", [])
        max_parse = int(c.input.get("max_parse") or self.default_max_parse)
        max_pages = int(c.input.get("pdf_pages") or self.default_pdf_pages)
        targets = [h for h in hits if h.get("pdf_url")][:max_parse]

        async def sink(event_type: str, data: dict[str, Any]) -> None:
            await c.emit(Event(event_type, data=data))

        async def parse_one(hit: dict[str, Any]) -> dict[str, Any]:
            res = await tools.call(
                "pdf__parse",
                {"url": hit["pdf_url"], "max_pages": max_pages},
                sink=sink,
            )
            return {"hit": hit, "ok": res.ok, "data": res.data, "error": res.error}

        results = await asyncio.gather(
            *[parse_one(h) for h in targets],
            return_exceptions=True,
        ) if targets else []

        parsed = []
        for result in results:
            if isinstance(result, Exception):
                await c.emit(
                    Event(
                        EventType.TASK_WARNING,
                        data={
                            "stage": "parse",
                            "message": f"PDF parse failed: {result}",
                            "type": type(result).__name__,
                            "recoverable": True,
                        },
                    )
                )
            else:
                parsed.append(result)
        c.state["parsed"] = parsed

    async def _ingest(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                c.state["papers"] = []
                return
            hits = c.state.get("search_hits", [])
            parsed_map: dict[str, dict[str, Any]] = {}
            for rec in c.state.get("parsed", []):
                pid = rec["hit"].get("paper_id", "")
                if pid:
                    parsed_map[pid] = rec

            cards: list[PaperCard] = []
            for hit in hits:
                parsed = parsed_map.get(hit.get("paper_id", ""))
                card = _hit_to_card(hit, parsed, run_id=c.task_id, user_id=c.user_id)
                # Skip cards with obviously invalid metadata
                if not _is_valid_card(card):
                    continue
                await c.memory.knowledge.write_card(card)
                await c.memory.vector.add(
                    doc_id=card.paper_id,
                    text=card.search_text(),
                    metadata={
                        "title": card.title,
                        "year": card.year,
                        "source_run_id": card.source_run_id,
                    },
                )
                cards.append(card)
                await c.emit(
                    Event(
                        EventType.MEMORY_WRITE,
                        data={"kind": "paper_card", "paper_id": card.paper_id},
                    )
                )
            c.state["papers"] = cards

        await self.stage(ctx, "ingest", inner)

    async def _evolve(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            cards: list[PaperCard] = c.state.get("papers", [])
            if not cards or c.memory is None:
                return
            # Lazy import keeps this stage free of circular memory deps.
            from backend.memory.paper_memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            summaries: list[dict[str, Any]] = []
            for card in cards:
                evo = await evolver.evolve_new_paper(card, run_id=c.task_id)
                summaries.append(
                    {
                        "paper_id": card.paper_id,
                        "mode": evo.mode,
                        "typed_links": len(evo.typed_links_added),
                        "tags_added": list(evo.tags_added),
                    }
                )
            c.state["evolution"] = summaries

        await self.stage(ctx, "evolve", inner)

    async def _reflect(self, ctx: WorkflowContext) -> None:
        async def inner(c: WorkflowContext) -> None:
            if c.memory is None:
                return
            cards: list[PaperCard] = c.state.get("papers", [])
            if not cards:
                return
            from backend.memory.paper_memory import PaperMemoryEvolver

            evolver = PaperMemoryEvolver(c.memory, llm=c.llm)
            await evolver.write_session_reflection(
                task_id=c.task_id,
                query=c.query,
                outcomes={
                    "verdict": "ok",
                    "paper_ids": [card.paper_id for card in cards],
                    "evolution": c.state.get("evolution", []),
                },
                session_id=c.session_id,
                user_id=c.user_id,
            )
            await c.emit(Event(EventType.MEMORY_WRITE, data={"kind": "reflection"}))

        # P12.1: reflection write is best-effort — losing it doesn't
        # invalidate the search/ingest work that already succeeded.
        await self.stage_soft(ctx, "reflect", inner)

    async def _summarize(self, ctx: WorkflowContext) -> None:
        """Generate a structured meta-summary of the entire research round.

        Calls the LLM with paper titles + abstracts and asks for a
        narrative synthesis. Best-effort via ``stage_soft``: a summary
        failure must not invalidate the paper results already persisted.
        The summary is a transient chat artefact — it is NOT written to
        PaperCard or Knowledge memory.
        """

        async def inner(c: WorkflowContext) -> None:
            papers: list[PaperCard] = c.state.get("papers", [])
            if not papers or c.llm is None:
                c.state["summary"] = None
                return

            paper_briefs = _format_paper_briefs(papers)
            system = (
                "You are a research assistant synthesising results from a "
                "literature search. Produce a structured summary in the "
                "same language as the user's original query. Output ONLY "
                "valid JSON with these keys:\n"
                '  "narrative"   — 2-3 paragraph synthesis of the research landscape\n'
                '  "key_findings" — list of 3-6 thematic findings across papers\n'
                '  "gaps"        — list of 2-4 gaps or open questions identified\n'
                '  "next_steps"  — list of 2-4 recommended next actions for the researcher\n'
            )
            user = (
                f"Research query: {c.query}\n\n"
                f"Papers found ({len(papers)}):\n{paper_briefs}\n\n"
                "Synthesise these into a structured research summary."
            )
            raw = await _ask(c, system=system, user=user, route="reasoning")
            import json as _json

            try:
                parsed = _json.loads(raw)
            except _json.JSONDecodeError:
                parsed = {"narrative": raw, "key_findings": [], "gaps": [], "next_steps": []}
            c.state["summary"] = parsed

        await self.stage_soft(ctx, "summarize", inner)


def _format_paper_briefs(papers: list[PaperCard]) -> str:
    parts: list[str] = []
    for p in papers:
        title = p.title or "Untitled"
        authors = ", ".join(p.authors[:3]) if p.authors else "Unknown"
        year = f" ({p.year})" if p.year else ""
        abstract = (p.abstract or "")[:400]
        parts.append(f"- {title}{year} by {authors}\n  {abstract}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _hit_to_card(
    hit: dict[str, Any],
    parsed: dict[str, Any] | None,
    *,
    run_id: str,
    user_id: str | None,
) -> PaperCard:
    paper_id = hit.get("paper_id") or stable_id("arxiv", hit.get("arxiv_id", gen_id()))
    abstract = (hit.get("summary") or "").strip()
    method = ""
    findings = ""
    summary = abstract[:800]
    if parsed and parsed.get("ok"):
        data = parsed.get("data") or {}
        pages = data.get("pages") or []
        full_text = (data.get("text") or "").strip()
        if pages:
            method = "\n".join(pages[:2])[:1200]
        if full_text:
            summary = (abstract[:300] + "\n\n" + full_text[:1500]).strip()
        findings = _last_page(pages)[:1000]

    return PaperCard(
        paper_id=paper_id,
        title=hit.get("title", ""),
        authors=list(hit.get("authors", [])),
        year=hit.get("year"),
        venue="arXiv",
        abstract=abstract,
        summary=summary,
        method=method,
        findings=findings,
        tags=list(hit.get("categories", [])),
        url=(hit.get("entry_id") or hit.get("pdf_url")),
        citation_url=hit.get("citation_url"),
        citation_bibtex=hit.get("bibtex"),
        source_run_id=run_id,
        user_id=user_id,
    )


def _is_valid_card(card: PaperCard) -> bool:
    """Reject cards with obviously invalid metadata (empty title, no content)."""
    if not card.title or not card.title.strip():
        return False
    # Title that looks like a raw arXiv ID only
    if len(card.title) <= 20 and card.title.strip().count(".") <= 1 and not any(c.isalpha() for c in card.title):
        return False
    return True


def _last_page(pages: list[str]) -> str:
    for page in reversed(pages):
        if page and page.strip():
            return page
    return ""


__all__ = ["ResearchWorkflow"]
