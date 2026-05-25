"""Paper Ingest pipeline (PLAN §20.8 M7.1).

End-to-end: raw upload (PDF / markdown / metadata) → extract structured
fields → upsert :class:`PaperCard` → mirror to the vector store →
trigger :meth:`PaperMemoryEvolver.evolve_new_paper` → opportunistically
fire ``check_synthesis_trigger`` for the most-frequent new tag.

The pipeline is **idempotent** in the sense that re-ingesting the same
upload writes to the same ``paper_id`` (derived deterministically) and
the evolver's neighbour-bound link logic dedups on ``(target, type)``.
"""

from __future__ import annotations

import time
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import structlog
from pydantic import BaseModel, ConfigDict, Field

from backend.core.errors import ValidationError
from backend.core.text import pdf_to_markdown
from backend.memory.base import MemoryBundle, stable_id
from backend.memory.models import PaperCard, SynthesisNote, TypedLink
from backend.memory.paper_memory import EvolutionResult, PaperMemoryEvolver

from .extractor import ExtractedPaper, PaperExtractor

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


SourceKind = Literal["user_upload", "arxiv", "doi", "manual"]


# ---------------------------------------------------------------------------
# Inputs / outputs
# ---------------------------------------------------------------------------


class IngestInput(BaseModel):
    """Normalised ingest payload.

    Construct from either an HTTP multipart form (``IngestInput.from_upload``)
    or a JSON body (``IngestInput.from_json``). The pipeline doesn't care
    where the bytes came from once we get here.
    """

    model_config = ConfigDict(extra="forbid")

    title: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    summary: str = ""
    abstract: str = ""
    method: str = ""
    findings: str = ""
    tags: list[str] = Field(default_factory=list)
    source_kind: SourceKind = "user_upload"
    source_uri: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)
    trigger_evolution: bool = True
    llm_extract: bool = True

    body_text: str = ""
    """Pre-extracted markdown / plain text. Empty when only metadata supplied."""

    raw_pdf_meta: dict[str, Any] = Field(default_factory=dict)
    """``pdf_to_markdown`` metadata (num_pages / pages_extracted) when applicable."""

    fallback_title: str = ""
    """Used only when neither the user nor the extractor produced a title.

    Typical source: the upload's filename stem. Never overrides an
    extracted or user-supplied title.
    """

    user_id: str | None = None
    session_id: str | None = None


@dataclass
class IngestResult:
    card: PaperCard
    evolution: EvolutionResult
    synthesis: SynthesisNote | None = None
    extracted: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers — input construction
# ---------------------------------------------------------------------------


def _decode_body(raw: bytes, *, filename: str, content_type: str) -> tuple[str, dict[str, Any]]:
    """Best-effort decode of an uploaded file into text + meta."""
    name = (filename or "").lower()
    ct = (content_type or "").lower()

    if name.endswith(".pdf") or "pdf" in ct:
        return pdf_to_markdown(raw)

    if name.endswith((".md", ".markdown", ".txt")) or "text" in ct or "markdown" in ct:
        return raw.decode("utf-8", errors="replace"), {}

    # Last resort: treat as utf-8 text. Callers that mis-upload binary
    # files get a noisy summary, not a 500.
    try:
        return raw.decode("utf-8"), {}
    except UnicodeDecodeError as exc:
        raise ValidationError(
            f"unable to decode upload as text or pdf: {exc}",
            filename=filename,
            content_type=content_type,
        ) from exc


def build_ingest_input_from_upload(
    *,
    raw: bytes,
    filename: str,
    content_type: str,
    title: str = "",
    authors: list[str] | None = None,
    year: int | None = None,
    venue: str | None = None,
    tags: list[str] | None = None,
    source_kind: SourceKind = "user_upload",
    source_uri: str = "",
    trigger_evolution: bool = True,
    llm_extract: bool = True,
    user_id: str | None = None,
    session_id: str | None = None,
) -> IngestInput:
    body_text, pdf_meta = _decode_body(raw, filename=filename, content_type=content_type)
    return IngestInput(
        title=title,
        authors=list(authors or []),
        year=year,
        venue=venue,
        tags=list(tags or []),
        source_kind=source_kind,
        source_uri=source_uri or filename,
        extras={"upload_filename": filename, "upload_bytes": len(raw)},
        trigger_evolution=trigger_evolution,
        llm_extract=llm_extract,
        body_text=body_text,
        raw_pdf_meta=pdf_meta,
        fallback_title=_title_from_filename(filename),
        user_id=user_id,
        session_id=session_id,
    )


def _title_from_filename(filename: str) -> str:
    if not filename:
        return ""
    stem = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if "." in stem:
        stem = stem.rsplit(".", 1)[0]
    return stem.replace("_", " ").replace("-", " ").strip()[:240]


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class PaperIngestor:
    """Orchestrates extract → write_card → evolve → maybe-synthesis.

    Designed for **dependency injection** in tests: pass an in-memory
    :class:`MemoryBundle`, a ``PaperExtractor`` with a mock LLM (or no
    LLM), and a ``PaperMemoryEvolver`` configured for fast paths.
    """

    def __init__(
        self,
        bundle: MemoryBundle,
        *,
        extractor: PaperExtractor | None = None,
        evolver: PaperMemoryEvolver | None = None,
        llm: LLMProvider | None = None,
        run_prefix: str = "ingest",
    ) -> None:
        self.bundle = bundle
        self.llm = llm
        self.extractor = extractor or PaperExtractor(llm=llm)
        self.evolver = evolver or PaperMemoryEvolver(bundle, llm=llm)
        self.run_prefix = run_prefix

    async def ingest(self, payload: IngestInput) -> IngestResult:
        t_extract_start = time.monotonic()
        if payload.body_text and payload.llm_extract is False:
            extractor = PaperExtractor(llm=None)  # honour the per-request opt-out
        else:
            extractor = self.extractor
        extracted = await extractor.extract(
            payload.body_text,
            fallback_title=payload.title or payload.fallback_title,
        )
        # User-supplied metadata wins.
        merged = extracted.merge_metadata(
            override={
                k: v
                for k, v in {
                    "title": payload.title or None,
                    "authors": list(payload.authors) if payload.authors else None,
                    "year": payload.year,
                    "venue": payload.venue,
                    "abstract": payload.abstract or None,
                    "summary": payload.summary or None,
                    "method": payload.method or None,
                    "findings": payload.findings or None,
                    "tags": (
                        sorted({*extracted.tags, *(t.lower() for t in payload.tags)})
                        if payload.tags
                        else None
                    ),
                }.items()
                if v is not None
            }
        )
        if not merged.title:
            raise ValidationError(
                "ingest: could not determine paper title — supply 'title' explicitly",
                source_kind=payload.source_kind,
            )
        extract_ms = int((time.monotonic() - t_extract_start) * 1000)

        paper_id = _derive_paper_id(merged, fallback_uri=payload.source_uri)
        run_id = f"{self.run_prefix}:{paper_id}"
        card = _to_paper_card(
            merged,
            paper_id=paper_id,
            run_id=run_id,
            user_id=payload.user_id,
            session_id=payload.session_id,
            source_kind=payload.source_kind,
            source_uri=payload.source_uri,
            raw_pdf_meta=payload.raw_pdf_meta,
        )

        await self.bundle.knowledge.write_card(card)
        try:
            await self.bundle.vector.add(
                doc_id=card.paper_id,
                text=card.search_text(),
                metadata={
                    "kind": "paper_card",
                    "title": card.title,
                    "year": card.year,
                    "tags": card.tags,
                    "source_run_id": card.source_run_id,
                },
            )
        except Exception as exc:  # pragma: no cover - vector store is best-effort
            log.warning("knowledge.ingest.vector_add_failed", err=str(exc), paper_id=card.paper_id)

        evolve_ms = 0
        if payload.trigger_evolution:
            t_evolve = time.monotonic()
            try:
                evolution = await self.evolver.evolve_new_paper(card, run_id=run_id)
            except Exception as exc:  # pragma: no cover - evolver soft-fails
                log.warning("knowledge.ingest.evolve_failed", err=str(exc), paper_id=card.paper_id)
                evolution = EvolutionResult(
                    paper_id=card.paper_id, mode="skip", reason=f"evolver_error: {exc}"
                )
            evolve_ms = int((time.monotonic() - t_evolve) * 1000)
        else:
            evolution = EvolutionResult(
                paper_id=card.paper_id, mode="skip", reason="trigger_evolution=false"
            )

        synthesis: SynthesisNote | None = None
        if payload.trigger_evolution and card.tags:
            tag = _pick_synthesis_tag(card)
            if tag:
                try:
                    synthesis = await self.evolver.check_synthesis_trigger(tag, run_id=run_id)
                except Exception as exc:  # pragma: no cover
                    log.warning(
                        "knowledge.ingest.synthesis_failed",
                        err=str(exc),
                        cluster_tag=tag,
                    )

        # Re-read the card so the response reflects what evolver wrote
        # (new tags, new typed_links).
        final = await self.bundle.knowledge.get(card.paper_id) or card

        log.info(
            "knowledge.ingest.ok",
            paper_id=card.paper_id,
            method=merged.method_used,
            extract_ms=extract_ms,
            evolve_ms=evolve_ms,
            mode=evolution.mode,
            typed_links=len(evolution.typed_links_added),
            synthesis=bool(synthesis),
        )

        return IngestResult(
            card=final,
            evolution=evolution,
            synthesis=synthesis,
            extracted={
                "method": merged.method_used,
                "extract_ms": extract_ms,
                "evolve_ms": evolve_ms,
                "preview": (payload.body_text or "")[:1000],
                "source_kind": payload.source_kind,
                "raw_pdf_meta": payload.raw_pdf_meta,
            },
        )


# ---------------------------------------------------------------------------
# Helpers — id derivation, tag picking, card building
# ---------------------------------------------------------------------------


def _derive_paper_id(extracted: ExtractedPaper, *, fallback_uri: str = "") -> str:
    seed = extracted.title.lower()
    first_author = extracted.authors[0] if extracted.authors else ""
    year = str(extracted.year) if extracted.year else ""
    if seed:
        return stable_id(seed, first_author, year)
    return stable_id("uri", fallback_uri or "anon", year)


def _to_paper_card(
    extracted: ExtractedPaper,
    *,
    paper_id: str,
    run_id: str,
    user_id: str | None,
    session_id: str | None,
    source_kind: SourceKind,
    source_uri: str,
    raw_pdf_meta: dict[str, Any],
) -> PaperCard:
    return PaperCard(
        paper_id=paper_id,
        title=extracted.title,
        authors=list(extracted.authors),
        year=extracted.year,
        venue=extracted.venue,
        abstract=extracted.abstract,
        summary=extracted.summary or extracted.abstract[:600],
        method=extracted.method,
        findings=extracted.findings,
        tags=list(dict.fromkeys(extracted.tags)),
        typed_links=[],
        url=source_uri or None,
        source_run_id=run_id,
        user_id=user_id,
        session_id=session_id,
    )


def _pick_synthesis_tag(card: PaperCard) -> str | None:
    """Pick the tag most likely to be cluster-worthy.

    The evolver itself decides whether to actually generate a note (it
    needs ``synthesis_threshold`` papers in the cluster); we just give
    it the most popular tag on this new card so it gets a chance.
    """
    if not card.tags:
        return None
    counts: Counter[str] = Counter(t.lower() for t in card.tags if t)
    tag, _ = counts.most_common(1)[0]
    return tag


def _typed_link_to_dto(link: TypedLink) -> dict[str, Any]:  # pragma: no cover - thin
    return link.model_dump(mode="json")


__all__ = [
    "IngestInput",
    "IngestResult",
    "PaperIngestor",
    "build_ingest_input_from_upload",
]
