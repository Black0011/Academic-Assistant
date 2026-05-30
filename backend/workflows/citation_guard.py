"""Citation validation helpers for write/revision/consult workflows.

P14.1 — soft-fail audit. Missing citations are reported as
``suspect_citations`` instead of raising ``ValueError``, so the
workflow can finish and the user can decide whether to research
the paper, remove the citation, or keep it after manual verification.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from backend.memory.models import PaperCard

_CITE_RE = re.compile(r"\[([A-Za-z0-9_-]{3,64})\]")
_LATEX_CITE_RE = re.compile(r"\\cite(?:t|p|author|year)?\{([^}]+)\}")
_BIBTEX_KEY_RE = re.compile(r"@\w+\s*\{\s*([^,]+)\s*,")
_NUMERIC_RE = re.compile(r"\d")

# Keys that look like well-known paper mnemonics but aren't verified.
# These are NOT suppressed — the user still sees them in suspect list.
_WELL_KNOWN_PREFIXES = {"gpt", "bert", "llama", "clip", "vit", "resnet"}

# Patterns that look like citations but are actually LaTeX formatting artifacts.
# These are filtered out to avoid false-positive suspect citations.
_FALSE_CITATION_RE = re.compile(
    r"^(\d+(?:\.\d+)?\s*(?:pt|px|em|mm|cm|in|ex|bp|dd|cc|sp|mu)%?$"  # TeX dimensions: 6pt, 3.5mm, 10px
    r"|nosep|noindent|hline|vspace|hspace|smallskip|medskip|bigskip"     # LaTeX commands
    r"|parskip|parindent|baselineskip|leftskip|rightskip"                 # LaTeX lengths
    r"|textwidth|textheight|linewidth|columnwidth"                        # LaTeX dimensions
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CitationAuditResult:
    paper_ids: set[str]
    suspect_citations: list[dict[str, str]] = field(default_factory=list)
    # ^ [{key, reason, suggestion}] — reported to the user so they can
    #   decide whether to research, remove, or keep each citation.


def _split_latex_keys(raw: str) -> list[str]:
    return [k.strip() for k in raw.split(",") if k.strip()]


def _bibtex_key(raw: str | None) -> str | None:
    if not raw:
        return None
    m = _BIBTEX_KEY_RE.search(raw)
    if not m:
        return None
    return m.group(1).strip() or None


def _numeric_near(text: str, start: int, end: int, *, window: int = 80) -> bool:
    left = max(0, start - window)
    right = min(len(text), end + window)
    return bool(_NUMERIC_RE.search(text[left:right]))


def _cite_spans(text: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    for m in _CITE_RE.finditer(text):
        spans.append((m.group(1), m.start(), m.end()))
    for m in _LATEX_CITE_RE.finditer(text):
        keys = _split_latex_keys(m.group(1))
        for key in keys:
            spans.append((key, m.start(), m.end()))
    return spans


def _is_false_citation(key: str) -> bool:
    """Check if a key looks like a LaTeX artifact, not a real citation."""
    return bool(_FALSE_CITATION_RE.match(key))


def _collect_ids(text: str) -> tuple[set[str], set[str]]:
    paper_ids = {m.group(1) for m in _CITE_RE.finditer(text) if not _is_false_citation(m.group(1))}
    latex_keys: set[str] = set()
    for m in _LATEX_CITE_RE.finditer(text):
        for k in _split_latex_keys(m.group(1)):
            if not _is_false_citation(k):
                latex_keys.add(k)
    return paper_ids, latex_keys


def _format_missing(label: str, items: Iterable[str]) -> str:
    joined = ", ".join(sorted(set(items)))
    return f"{label}: {joined}" if joined else ""


async def audit_citations(
    ctx,
    *,
    text: str,
    stage: str,
    attempted: bool = False,
) -> CitationAuditResult:
    """Validate citations against the knowledge store.

    **P14.1 soft-fail**: missing cards / incomplete metadata are collected
    into ``suspect_citations`` instead of raising ``ValueError``. Only a
    truly unavailable ``ctx.memory`` still raises (infrastructure error).

    Returns
    -------
    CitationAuditResult
        ``paper_ids`` — known-good paper ids found in the knowledge store.
        ``suspect_citations`` — list of ``{key, reason, suggestion}`` dicts
        for citations that couldn't be fully verified. The workflow caller
        surfaces these to the user so they can decide next steps.
    """
    if not text or not text.strip():
        return CitationAuditResult(paper_ids=set())
    paper_ids, latex_keys = _collect_ids(text)
    if not paper_ids and not latex_keys:
        return CitationAuditResult(paper_ids=set())
    if ctx.memory is None:
        raise ValueError(
            f"citation audit failed at {stage}: memory subsystem is unavailable"
        )

    knowledge = ctx.memory.knowledge
    suspect: list[dict[str, str]] = []
    missing_ids: list[str] = []
    cards_by_id: dict[str, PaperCard] = {}

    for pid in paper_ids:
        card = await knowledge.get(pid)
        if card is None:
            missing_ids.append(pid)
        else:
            cards_by_id[pid] = card

    missing_keys: list[str] = []
    if latex_keys:
        cards = await knowledge.list_all()
        key_map: dict[str, PaperCard] = {}
        for card in cards:
            key = _bibtex_key(card.citation_bibtex)
            if key:
                key_map[key] = card
        for key in latex_keys:
            card = key_map.get(key)
            if card is None:
                missing_keys.append(key)
            else:
                cards_by_id[card.paper_id] = card

    # ---- P14.1: best-effort auto-research, then warn instead of fail ----
    if (missing_ids or missing_keys) and _should_auto_research(ctx) and not attempted:
        await _research_missing(ctx, missing_ids + missing_keys)
        # Re-check after best-effort research.
        return await audit_citations(ctx, text=text, stage=stage, attempted=True)

    for pid in missing_ids:
        suspect.append({
            "key": pid,
            "reason": "no paper card in knowledge store",
            "suggestion": (
                f"Run a research task for '{pid}', then edit the card to add "
                f"citation_url and citation_bibtex before the next audit."
            ),
        })
    for key in missing_keys:
        suspect.append({
            "key": key,
            "reason": "bibtex key not found in any paper card",
            "suggestion": (
                f"Create a paper card with bibtex key '{key}' via research, "
                f"or replace the \\cite{{{key}}} with a verified paper_id."
            ),
        })

    # ---- Metadata completeness check (with auto-backfill) ----
    cited_cards = list(cards_by_id.values())
    if cited_cards:
        await backfill_missing_metadata(ctx, cited_cards)
        # Refresh cards after backfill to pick up newly-fetched metadata
        for card in cited_cards:
            refreshed = await knowledge.get(card.paper_id)
            if refreshed:
                cards_by_id[card.paper_id] = refreshed

    spans = _cite_spans(text)
    for key, start, end in spans:
        card = cards_by_id.get(key)
        if card is None and len(key) >= 6:
            for resolved in cards_by_id.values():
                if _bibtex_key(resolved.citation_bibtex) == key:
                    card = resolved
                    break
        if card is None:
            continue
        missing = []
        if not (card.url or "").strip():
            missing.append("url")
        if not (card.citation_url or "").strip():
            missing.append("citation_url")
        if not (card.citation_bibtex or "").strip():
            missing.append("citation_bibtex")
        if missing:
            suspect.append({
                "key": card.paper_id,
                "reason": f"card exists but missing: {', '.join(missing)}",
                "suggestion": (
                    f"Edit paper card '{card.paper_id}' to fill the missing "
                    f"metadata field(s)."
                ),
            })
        if _numeric_near(text, start, end) and not (card.experiment_results or "").strip():
            suspect.append({
                "key": card.paper_id,
                "reason": "numeric claim near citation but no experiment_results",
                "suggestion": (
                    f"Add experiment_results to card '{card.paper_id}' or verify "
                    f"the numeric claim against the original paper."
                ),
            })

    return CitationAuditResult(
        paper_ids=set(cards_by_id.keys()),
        suspect_citations=suspect,
    )


def _should_auto_research(ctx) -> bool:
    if not getattr(ctx, "tools", None):
        return False
    if isinstance(getattr(ctx, "input", None), dict):
        return bool(ctx.input.get("auto_research_missing_citations", True))
    return True


async def _research_missing(ctx, keys: list[str]) -> None:
    """Best-effort auto-research for missing citation keys.

    P14.1: tries multiple query variants and sources before giving up.
    Each source is tried independently — one failure doesn't stop the rest.
    """
    tools = getattr(ctx, "tools", None)
    if tools is None or ctx.memory is None:
        return
    from backend.workflows.research import _hit_to_card

    unique = sorted(set(k for k in keys if k))
    semaphore = asyncio.Semaphore(4)  # bound concurrent tool calls

    async def _search_one(key: str) -> None:
        async with semaphore:
            # Query variants: raw key, key with spaces around CamelCase, year-stripped
            variants = [key]
            # Strip year suffix for broader matching (e.g. "chen2024beaver" → "beaver")
            year_stripped = _strip_year_prefix(key)
            if year_stripped and year_stripped != key:
                variants.append(year_stripped)
            # Try camelCase splitting (e.g. "liu2024lostmiddle" → "lost middle")
            camel_split = _split_camel(key)
            if camel_split and camel_split != key:
                variants.append(camel_split)

            for variant in variants[:2]:  # at most 2 queries per key to bound cost
                # Source 1: Google Scholar MCP (broadest coverage)
                gs_tool = "mcp__google-scholar__search_google_scholar_key_words"
                if tools.has(gs_tool):
                    try:
                        result = await tools.call(gs_tool, {"query": variant, "num_results": 3})
                        if result.ok:
                            hits = _parse_mcp_results(result.data)
                            for hit in hits:
                                card = _hit_to_card(hit, None, run_id=f"{ctx.task_id}:cite", user_id=ctx.user_id)
                                await ctx.memory.knowledge.write_card(card)
                                await backfill_card_metadata(ctx, card)
                            if hits:
                                # Enrich top hit with Google Scholar verified metadata + BibTeX
                                await _enrich_with_scholar_metadata(ctx, hits[0], card)
                                return
                    except Exception:
                        pass

                # Source 2: Arxiv
                try:
                    result = await tools.call("arxiv__search", {"query": variant, "max_results": 3})
                    if result.ok:
                        hits = list((result.data or {}).get("results") or [])
                        for hit in hits:
                            card = _hit_to_card(hit, None, run_id=f"{ctx.task_id}:cite", user_id=ctx.user_id)
                            await ctx.memory.knowledge.write_card(card)
                            await backfill_card_metadata(ctx, card)
                        if hits:
                            return
                except Exception:
                    pass

    await asyncio.gather(*(_search_one(k) for k in unique))


async def _enrich_with_scholar_metadata(
    ctx, hit: dict[str, Any], card: PaperCard
) -> None:
    """Populate or update a PaperCard with Google Scholar verified metadata."""
    tools = getattr(ctx, "tools", None)
    if tools is None or ctx.memory is None:
        return
    meta_tool = "mcp__google-scholar__get_citation_metadata"
    bib_tool = "mcp__google-scholar__get_citation_bibtex"
    if not tools.has(meta_tool):
        return

    title = hit.get("title") or card.title
    if not title:
        return

    # Try to get Google Scholar verified metadata
    try:
        result = await tools.call(meta_tool, {"query": title})
        if result.ok and result.data:
            meta = result.data
            # Update card with verified data
            if meta.get("title"):
                card.title = meta["title"]
            if meta.get("year"):
                card.year = int(meta["year"])
            if meta.get("venue"):
                card.venue = meta["venue"]
            if meta.get("url"):
                card.url = meta.get("url", "")
            if meta.get("bibtex"):
                card.citation_bibtex = meta["bibtex"]
            await ctx.memory.knowledge.write_card(card)
            return
    except Exception:
        pass

    # Fallback: just try to get BibTeX
    try:
        result = await tools.call(bib_tool, {"query": title})
        if result.ok and result.data:
            bibtex = str(result.data)
            if bibtex and len(bibtex) > 10:
                card.citation_bibtex = bibtex
                await ctx.memory.knowledge.write_card(card)
    except Exception:
        pass


async def backfill_card_metadata(ctx, card: PaperCard) -> PaperCard:
    """Best-effort backfill of missing citation metadata for a single card.

    Tries to derive ``citation_url`` from the arxiv ID embedded in the
    card's ``url`` or ``paper_id``, then fetches the bibtex entry.
    Returns the card unchanged on failure (soft-fail).
    """
    if not ctx.memory:
        return card

    arxiv_id = _extract_arxiv_id(card)
    if not arxiv_id:
        return card

    needs_url = not (card.citation_url or "").strip()
    needs_bib = not (card.citation_bibtex or "").strip()
    if not needs_url and not needs_bib:
        return card

    citation_url = f"https://arxiv.org/bibtex/{arxiv_id}"
    if needs_url:
        card = card.model_copy(update={"citation_url": citation_url})

    if needs_bib:
        bibtex = await _fetch_arxiv_bibtex(citation_url)
        if bibtex:
            card = card.model_copy(update={"citation_bibtex": bibtex})

    if (needs_url or needs_bib) and ctx.memory:
        try:
            await ctx.memory.knowledge.write_card(card)
        except Exception:
            pass

    return card


def _extract_arxiv_id(card: PaperCard) -> str | None:
    """Extract an arxiv ID from a card's URL or paper_id."""
    import re as _re

    candidates = []
    if card.url:
        candidates.append(card.url)
    if card.citation_url:
        candidates.append(card.citation_url)
    candidates.append(card.paper_id)

    for candidate in candidates:
        # Match explicit arxiv URLs or IDs like "2106.12054" or "hep-th/9901001"
        m = _re.search(r"arxiv\.org/(?:abs|pdf|bibtex)/([^/\s?#]+)", candidate)
        if m:
            return m.group(1)
        # Match naked arxiv ID patterns
        m = _re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", candidate)
        if m:
            return m.group(1)
        # Match old-style arxiv IDs
        m = _re.search(r"([a-z-]+/\d{7}(?:v\d+)?)", candidate)
        if m:
            return m.group(1)
    return None


async def _fetch_arxiv_bibtex(url: str) -> str | None:
    """Fetch bibtex entry from arxiv's bibtex endpoint. Soft-fail."""
    import asyncio as _asyncio
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError

    def _sync() -> str | None:
        try:
            req = Request(url, method="GET", headers={"User-Agent": "aaf/0.1"})
            with urlopen(req, timeout=15) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception:
            return None

    try:
        return await _asyncio.to_thread(_sync)
    except Exception:
        return None


async def auto_fix_suspects(ctx, suspect_citations: list[dict[str, str]]) -> list[dict[str, str]]:
    """Auto-research missing citations and remove those that are found.

    Called by workflows after audit to fix remaining suspect citations.
    Returns the list of suspects that could NOT be fixed.
    """
    if not suspect_citations:
        return []

    missing_keys = [s["key"] for s in suspect_citations if s.get("reason") and "no paper card" in s["reason"]]
    incomplete_keys = [s["key"] for s in suspect_citations if "missing:" in s.get("reason", "")]

    # Research missing papers
    if missing_keys:
        await _research_missing(ctx, missing_keys)

    # For existing but incomplete cards, enrich with Google Scholar metadata
    if incomplete_keys and ctx.memory:
        for key in incomplete_keys:
            card = await ctx.memory.knowledge.get(key)
            if card and card.title:
                fake_hit = {"title": card.title}
                await _enrich_with_scholar_metadata(ctx, fake_hit, card)

    # Re-check: which keys now have cards?
    still_missing: list[dict[str, str]] = []
    knowledge = ctx.memory.knowledge if ctx.memory else None
    for s in suspect_citations:
        key = s["key"]
        if "no paper card" in s.get("reason", ""):
            if knowledge:
                card = await knowledge.get(key)
                if card is not None:
                    continue
        if "missing:" in s.get("reason", ""):
            if knowledge:
                card = await knowledge.get(key)
                if card and card.citation_bibtex:
                    continue  # Now has bibtex — resolved
        still_missing.append(s)

    return still_missing


async def backfill_missing_metadata(ctx, cards: list[PaperCard]) -> None:
    """Proactively backfill citation metadata for a batch of cards.

    Runs with bounded concurrency so a single slow fetch doesn't stall
    the whole audit.
    """
    semaphore = asyncio.Semaphore(6)
    if not ctx.memory:
        return

    async def _backfill_one(card: PaperCard) -> None:
        async with semaphore:
            await backfill_card_metadata(ctx, card)

    needs_backfill = [
        c for c in cards
        if not (c.citation_bibtex or "").strip() or not (c.citation_url or "").strip()
    ]
    if needs_backfill:
        await asyncio.gather(*(_backfill_one(c) for c in needs_backfill))


def _parse_mcp_results(data: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Convert Google Scholar MCP results to the format _hit_to_card expects."""
    if not data:
        return []
    results = data.get("results") or data.get("content") or []
    if isinstance(results, str):
        return []
    converted: list[dict[str, Any]] = []
    for r in results:
        if not isinstance(r, dict):
            continue
        converted.append({
            "paper_id": "",
            "title": r.get("Title") or r.get("title", ""),
            "authors": _parse_author_string(r.get("Authors") or r.get("authors", "")),
            "year": None,
            "summary": r.get("Abstract") or r.get("abstract", ""),
            "entry_id": r.get("URL") or r.get("url", ""),
            "pdf_url": "",
            "citation_url": "",
            "categories": [],
        })
    return converted


def _parse_author_string(raw: str) -> list[str]:
    """Parse 'LastName, FirstName; ...' or 'Name1, Name2, ...' into a list."""
    if not raw:
        return []
    parts = [p.strip() for p in raw.replace(";", ",").split(",")]
    return [p for p in parts if p]


def _strip_year_prefix(key: str) -> str:
    """Remove a 4-digit year from the start of a key if present.

    >>> _strip_year_prefix("chen2024beaver")
    'chenbeaver'
    """
    m = re.match(r"^(.+?)(19|20)\d{2}(.+)$", key)
    if m:
        return m.group(1) + m.group(3)
    return key


def _split_camel(key: str) -> str:
    """Insert spaces at camelCase boundaries for broader search.

    >>> _split_camel("lostMiddle")
    'lost Middle'
    """
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", key)
    return " ".join(p for p in parts if p and not p.isdigit()) if parts else key
