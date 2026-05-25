"""Turn raw paper text + optional metadata into a structured ``ExtractedPaper``.

Two paths, tried in order:

1. **LLM** — ``LLMProvider.complete()`` is asked for a strict JSON schema.
   Decoded via ``backend.memory.paper_memory.extract_json`` so the
   response is tolerant of fences / leading prose.
2. **Heuristic** — pure-Python regex over the document. Used when no
   LLM is wired, when the LLM raises, or when the JSON parse fails.

The output is always the same dataclass shape, so downstream code (the
:class:`PaperIngestor`) doesn't care which path produced it. A
``method`` string ("llm" / "heuristic" / "metadata_only") is recorded
for telemetry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog

from backend.memory.paper_memory import extract_json

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


_TITLE_MAX_LEN = 240
_ABSTRACT_MAX_LEN = 2000
_SUMMARY_MAX_LEN = 800


# ---------------------------------------------------------------------------
# Output dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExtractedPaper:
    """Result of one :meth:`PaperExtractor.extract` call.

    Fields are best-effort: any may be empty / None when neither path
    could fill them. Callers should treat them as hints, not guarantees.
    """

    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str = ""
    summary: str = ""
    method: str = ""
    findings: str = ""
    tags: list[str] = field(default_factory=list)
    method_used: str = "heuristic"  # "llm" | "heuristic" | "metadata_only"

    def merge_metadata(self, *, override: dict[str, Any]) -> ExtractedPaper:
        """Apply user-supplied metadata on top of extracted values.

        User-provided values always win — even if they're empty strings,
        callers that mean "leave unchanged" must omit the key entirely.
        """
        out = ExtractedPaper(
            title=self.title,
            authors=list(self.authors),
            year=self.year,
            venue=self.venue,
            abstract=self.abstract,
            summary=self.summary,
            method=self.method,
            findings=self.findings,
            tags=list(self.tags),
            method_used=self.method_used,
        )
        for key, value in override.items():
            if value is None:
                continue
            if hasattr(out, key):
                setattr(out, key, value)
        return out


# ---------------------------------------------------------------------------
# Extractor
# ---------------------------------------------------------------------------


_EXTRACT_SYSTEM = (
    "You are a paper-metadata extraction agent. Extract structured fields "
    "from the supplied paper text. Respond with STRICT JSON only — no "
    "markdown fences, no prose."
)


_EXPECTED_KEYS: tuple[str, ...] = (
    "title",
    "authors",
    "year",
    "venue",
    "abstract",
    "summary",
    "method",
    "findings",
    "tags",
)


class PaperExtractor:
    """LLM-with-fallback extractor.

    Parameters
    ----------
    llm:
        Optional :class:`LLMProvider`. When ``None``, the extractor goes
        straight to the heuristic path.
    model:
        Override forwarded to ``llm.complete``.
    max_input_chars:
        Cap on the body fed to the LLM (full text is still kept on the
        ``ExtractedPaper`` side via the caller, who has the original).
    """

    def __init__(
        self,
        *,
        llm: LLMProvider | None = None,
        model: str | None = None,
        max_input_chars: int = 12_000,
    ) -> None:
        self.llm = llm
        self.model = model
        self.max_input_chars = max(1024, max_input_chars)

    async def extract(self, body: str, *, fallback_title: str = "") -> ExtractedPaper:
        body = (body or "").strip()
        if not body:
            return ExtractedPaper(title=fallback_title, method_used="metadata_only")

        if self.llm is not None:
            try:
                parsed = await self._call_llm(body)
                if isinstance(parsed, dict):
                    extracted = _coerce_payload(parsed)
                    if extracted.title or extracted.abstract or extracted.summary:
                        extracted.method_used = "llm"
                        return _enforce_caps(extracted)
            except Exception as exc:  # pragma: no cover - logged + fallback
                log.warning("knowledge.extractor.llm_failed", err=str(exc))

        heur = _heuristic_extract(body, fallback_title=fallback_title)
        heur.method_used = "heuristic"
        return _enforce_caps(heur)

    async def _call_llm(self, body: str) -> dict[str, Any] | None:
        from backend.core.llm.base import ChatMessage

        assert self.llm is not None
        snippet = body[: self.max_input_chars]
        prompt = (
            "Extract the following fields from the paper text. Use null "
            "when a field is not stated.\n\n"
            "Required JSON shape:\n"
            "{\n"
            '  "title": str,\n'
            '  "authors": [str, ...],\n'
            '  "year": int | null,\n'
            '  "venue": str | null,\n'
            '  "abstract": str,\n'
            '  "summary": str,        # <= 600 chars, your own consolidation\n'
            '  "method": str,         # short methods sentence\n'
            '  "findings": str,       # short findings sentence\n'
            '  "tags": [str, ...]     # 1-6 lowercase keyword tags\n'
            "}\n\n"
            f"Paper text (truncated):\n---\n{snippet}\n---"
        )
        messages = [
            ChatMessage(role="system", content=_EXTRACT_SYSTEM),
            ChatMessage(role="user", content=prompt),
        ]
        from backend.memory.paper_memory import _collect_completion

        raw = await _collect_completion(self.llm, messages, model=self.model)
        parsed = extract_json(raw)
        return parsed if isinstance(parsed, dict) else None


# ---------------------------------------------------------------------------
# Heuristic + payload helpers
# ---------------------------------------------------------------------------


_RE_PAGE_HEADING = re.compile(r"^##\s+Page\s+\d+\s*$", re.MULTILINE)
_RE_FIRST_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_RE_YEAR = re.compile(r"\b(19[8-9]\d|20[0-3]\d)\b")
_RE_ABSTRACT_BLOCK = re.compile(
    r"(?:^|\n)\s*(?:#{1,6}\s*)?(?:Abstract|ABSTRACT)\b[:\s]*\n+(?P<body>.+?)"
    r"(?=\n\s*(?:#{1,6}\s|Introduction\b|INTRODUCTION\b|"
    r"1[\.\s]+Introduction|Keywords\s*:))",
    re.DOTALL,
)


def _heuristic_extract(body: str, *, fallback_title: str) -> ExtractedPaper:
    cleaned = _strip_page_markers(body)
    title = _heuristic_title(cleaned) or fallback_title
    year = _heuristic_year(cleaned)
    abstract = _heuristic_abstract(cleaned)
    summary = _heuristic_summary(cleaned, abstract)
    return ExtractedPaper(
        title=title,
        authors=[],
        year=year,
        abstract=abstract,
        summary=summary,
        tags=[],
    )


def _strip_page_markers(text: str) -> str:
    return _RE_PAGE_HEADING.sub("", text).strip()


def _heuristic_title(text: str) -> str:
    m = _RE_FIRST_HEADING.search(text)
    if m:
        return m.group(1).strip()
    # Fallback: first non-empty line, trimmed.
    for line in text.splitlines():
        line = line.strip()
        if line and len(line) >= 6:
            return line[:_TITLE_MAX_LEN]
    return ""


def _heuristic_year(text: str) -> int | None:
    m = _RE_YEAR.search(text[:4000])
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None


def _heuristic_abstract(text: str) -> str:
    m = _RE_ABSTRACT_BLOCK.search(text)
    if not m:
        return ""
    body = re.sub(r"\s+", " ", m.group("body")).strip()
    return body[:_ABSTRACT_MAX_LEN]


def _heuristic_summary(text: str, abstract: str) -> str:
    if abstract:
        return abstract[:_SUMMARY_MAX_LEN]
    flat = re.sub(r"\s+", " ", text).strip()
    return flat[:_SUMMARY_MAX_LEN]


def _coerce_payload(parsed: dict[str, Any]) -> ExtractedPaper:
    def _get_str(key: str) -> str:
        v = parsed.get(key)
        return str(v).strip() if isinstance(v, str) else ""

    def _get_list(key: str) -> list[str]:
        v = parsed.get(key)
        if not isinstance(v, list):
            return []
        out = []
        for item in v:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out

    year_raw = parsed.get("year")
    year: int | None = None
    if isinstance(year_raw, int):
        year = year_raw
    elif isinstance(year_raw, str):
        m = _RE_YEAR.search(year_raw)
        if m:
            try:
                year = int(m.group(1))
            except ValueError:
                year = None

    venue_raw = parsed.get("venue")
    venue = venue_raw.strip() if isinstance(venue_raw, str) and venue_raw.strip() else None

    return ExtractedPaper(
        title=_get_str("title"),
        authors=_get_list("authors"),
        year=year,
        venue=venue,
        abstract=_get_str("abstract"),
        summary=_get_str("summary"),
        method=_get_str("method"),
        findings=_get_str("findings"),
        tags=[t.lower() for t in _get_list("tags")],
    )


def _enforce_caps(p: ExtractedPaper) -> ExtractedPaper:
    p.title = p.title[:_TITLE_MAX_LEN]
    p.abstract = p.abstract[:_ABSTRACT_MAX_LEN]
    p.summary = p.summary[:_SUMMARY_MAX_LEN]
    return p


__all__ = [
    "ExtractedPaper",
    "PaperExtractor",
]
