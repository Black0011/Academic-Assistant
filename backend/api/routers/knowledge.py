"""Knowledge base API — manage :class:`PaperCard`s and their links.

This is the framework's read/write surface over :class:`KnowledgeStore`:

* ``POST   /api/knowledge/papers``           — create / upsert one card
* ``POST   /api/knowledge/papers:bulk``      — batch create
* ``POST   /api/knowledge/papers/ingest``    — full ingest pipeline (M7.1):
                                              decode PDF/MD → extract →
                                              upsert card → evolve memory.
* ``GET    /api/knowledge/papers``           — list / filter / search
* ``GET    /api/knowledge/papers/{id}``      — read one card
* ``PATCH  /api/knowledge/papers/{id}``      — partial update
* ``DELETE /api/knowledge/papers/{id}``      — remove (links scrubbed)
* ``POST   /api/knowledge/papers/{id}/links`` — attach a typed link
* ``GET    /api/knowledge/syntheses``        — list cluster-level synthesis notes
* ``POST   /api/knowledge/syntheses``        — upsert a synthesis note
* ``GET    /api/knowledge/syntheses/{tag}``
* ``DELETE /api/knowledge/syntheses/{tag}``
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
)
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from backend.core.app_state import AppState, get_app_state
from backend.core.errors import MemoryNotFound
from backend.core.errors import ValidationError as AAFValidationError
from backend.knowledge import IngestInput, IngestResult, PaperIngestor
from backend.knowledge.ingest import build_ingest_input_from_upload
from backend.memory.base import KnowledgeStore, stable_id
from backend.memory.models import (
    LinkType,
    PaperCard,
    SynthesisNote,
    TypedLink,
)

log = structlog.get_logger(__name__)

# Hard cap on a single uploaded paper. Aligned with manuscripts upload
# (40 MB) — most arXiv PDFs are well under this.
MAX_INGEST_BYTES = 25 * 1024 * 1024  # 25 MB

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreatePaperCardInput(BaseModel):
    """Create or upsert a paper card.

    ``paper_id`` is optional — if omitted, a stable id is derived from
    ``(title, authors[0]?, year?)`` so the same paper never gets a
    duplicate row.
    """

    model_config = ConfigDict(extra="forbid")

    paper_id: str | None = None
    title: str = Field(..., min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str = ""
    summary: str = ""
    method: str = ""
    findings: str = ""
    tags: list[str] = Field(default_factory=list)
    # P13 — manual-CRUD metadata. Mirrors PaperCard fields of the same
    # name; kept ``str | None`` so a clear-out PATCH (``url: null``)
    # round-trips correctly through the store.
    url: str | None = None
    field_major: str | None = None
    field_minor: str | None = None
    citation_url: str | None = None
    citation_bibtex: str | None = None
    experiment_results: str | None = None
    source_run_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None


class UpdatePaperCardInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    authors: list[str] | None = None
    year: int | None = None
    venue: str | None = None
    abstract: str | None = None
    summary: str | None = None
    method: str | None = None
    findings: str | None = None
    tags: list[str] | None = None
    # P13 — same trio as CreatePaperCardInput, exposed on the partial-
    # update endpoint so the new UI's edit drawer can drop them.
    url: str | None = None
    field_major: str | None = None
    field_minor: str | None = None
    citation_url: str | None = None
    citation_bibtex: str | None = None
    experiment_results: str | None = None


class BulkCreateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    papers: list[CreatePaperCardInput] = Field(default_factory=list, max_length=500)


class AttachLinkInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_paper_id: str
    link_type: LinkType
    evidence: str = ""
    bidirectional: bool = True


class WriteSynthesisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cluster_tag: str = Field(..., min_length=1)
    content: str = ""
    summary: str = ""
    paper_ids: list[str] = Field(default_factory=list)
    source_run_id: str | None = None


class PaperListResponse(BaseModel):
    items: list[PaperCard]
    total: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_knowledge(state: AppState) -> KnowledgeStore:
    if state.memory is None:
        raise HTTPException(status_code=503, detail="memory subsystem not ready")
    return state.memory.knowledge


def _derive_paper_id(body: CreatePaperCardInput) -> str:
    if body.paper_id:
        return body.paper_id.strip()
    seed = body.title.lower()
    first_author = body.authors[0] if body.authors else ""
    year = str(body.year) if body.year is not None else ""
    return stable_id(seed, first_author, year)


def _body_to_card(body: CreatePaperCardInput, *, paper_id: str) -> PaperCard:
    return PaperCard(
        paper_id=paper_id,
        title=body.title,
        authors=list(body.authors),
        year=body.year,
        venue=body.venue,
        abstract=body.abstract,
        summary=body.summary,
        method=body.method,
        findings=body.findings,
        tags=list(body.tags),
        # P13 — new manual-CRUD fields. Pass-through with no normalisation:
        # the model itself accepts ``None`` so a missing key in the create
        # body leaves the card unclassified.
        url=body.url,
        field_major=body.field_major,
        field_minor=body.field_minor,
        citation_url=body.citation_url,
        citation_bibtex=body.citation_bibtex,
        experiment_results=body.experiment_results,
        source_run_id=body.source_run_id,
        user_id=body.user_id,
        session_id=body.session_id,
    )


def _filter_cards(
    cards: list[PaperCard],
    *,
    q: str | None,
    tag: str | None,
    user_id: str | None,
    session_id: str | None,
    source_run_id: str | None,
) -> list[PaperCard]:
    out = cards
    if user_id is not None:
        out = [c for c in out if c.user_id == user_id]
    if session_id is not None:
        out = [c for c in out if c.session_id == session_id]
    if source_run_id is not None:
        out = [c for c in out if c.source_run_id == source_run_id]
    if tag is not None:
        out = [c for c in out if tag in c.tags]
    if q:
        needle = q.lower()
        out = [c for c in out if needle in c.search_text().lower()]
    return out


# ---------------------------------------------------------------------------
# Paper card endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/papers",
    response_model=PaperListResponse,
    summary="List paper cards (filter by tag / user / session / run / full-text)",
)
async def list_papers(
    q: str | None = Query(None, description="Substring search over title + abstract + summary."),
    tag: str | None = Query(None),
    user_id: str | None = Query(None),
    session_id: str | None = Query(None),
    source_run_id: str | None = Query(None),
    k: int | None = Query(None, ge=1, le=200, description="Semantic find_related top-k."),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    state: AppState = Depends(get_app_state),
) -> PaperListResponse:
    store = _require_knowledge(state)

    if q and k:
        results = await store.find_related(q, k=k)
        filtered = _filter_cards(
            results,
            q=None,
            tag=tag,
            user_id=user_id,
            session_id=session_id,
            source_run_id=source_run_id,
        )
    else:
        cards = await store.list_all()
        filtered = _filter_cards(
            cards,
            q=q,
            tag=tag,
            user_id=user_id,
            session_id=session_id,
            source_run_id=source_run_id,
        )
        filtered.sort(key=lambda c: c.updated_at, reverse=True)

    page = filtered[offset : offset + limit]
    return PaperListResponse(items=page, total=len(filtered))


@router.post(
    "/papers",
    response_model=PaperCard,
    status_code=201,
    summary="Create or upsert one paper card",
)
async def create_paper(
    body: CreatePaperCardInput,
    state: AppState = Depends(get_app_state),
) -> PaperCard:
    store = _require_knowledge(state)
    paper_id = _derive_paper_id(body)
    card = _body_to_card(body, paper_id=paper_id)
    await store.write_card(card)
    final = await store.get(paper_id)
    if final is None:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail="write_card did not persist")
    return final


@router.post(
    "/papers:bulk",
    summary="Bulk-create paper cards; returns one result per entry",
)
async def bulk_create_papers(
    body: BulkCreateInput,
    state: AppState = Depends(get_app_state),
) -> dict[str, Any]:
    store = _require_knowledge(state)
    created: list[PaperCard] = []
    failed: list[dict[str, Any]] = []
    for entry in body.papers:
        try:
            pid = _derive_paper_id(entry)
            card = _body_to_card(entry, paper_id=pid)
            await store.write_card(card)
            final = await store.get(pid)
            if final is not None:
                created.append(final)
        except Exception as exc:
            failed.append({"title": entry.title, "error": str(exc)})
    return {"created": [c.model_dump(mode="json") for c in created], "failed": failed}


# ---------------------------------------------------------------------------
# Ingest pipeline (M7.1)
# ---------------------------------------------------------------------------


SourceKindLiteral = Literal["user_upload", "arxiv", "doi", "manual"]


class IngestPaperJSONInput(BaseModel):
    """JSON-mode ingest body — caller supplies metadata / pre-extracted text."""

    model_config = ConfigDict(extra="forbid")

    title: str = Field(..., min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str = ""
    summary: str = ""
    method: str = ""
    findings: str = ""
    tags: list[str] = Field(default_factory=list)
    source_kind: SourceKindLiteral = "manual"
    source_uri: str = ""
    body_text: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)
    trigger_evolution: bool = True
    llm_extract: bool = True
    user_id: str | None = None
    session_id: str | None = None


class IngestEvolutionDTO(BaseModel):
    paper_id: str
    mode: str
    typed_links_added: list[TypedLink] = Field(default_factory=list)
    tags_added: list[str] = Field(default_factory=list)
    neighbors_considered: int = 0
    reason: str = ""


class IngestExtractedDTO(BaseModel):
    method: str
    extract_ms: int
    evolve_ms: int
    preview: str = ""
    source_kind: str = ""
    raw_pdf_meta: dict[str, Any] = Field(default_factory=dict)


class IngestPaperResponse(BaseModel):
    card: PaperCard
    evolution: IngestEvolutionDTO
    synthesis: SynthesisNote | None = None
    extracted: IngestExtractedDTO


def _build_ingestor(state: AppState) -> PaperIngestor:
    if state.memory is None:
        raise HTTPException(status_code=503, detail="memory subsystem not ready")
    return PaperIngestor(state.memory, llm=state.llm)


def _ingest_to_response(result: IngestResult) -> IngestPaperResponse:
    return IngestPaperResponse(
        card=result.card,
        evolution=IngestEvolutionDTO(
            paper_id=result.evolution.paper_id,
            mode=result.evolution.mode,
            typed_links_added=list(result.evolution.typed_links_added),
            tags_added=list(result.evolution.tags_added),
            neighbors_considered=result.evolution.neighbors_considered,
            reason=result.evolution.reason,
        ),
        synthesis=result.synthesis,
        extracted=IngestExtractedDTO(
            method=str(result.extracted.get("method", "heuristic")),
            extract_ms=int(result.extracted.get("extract_ms", 0) or 0),
            evolve_ms=int(result.extracted.get("evolve_ms", 0) or 0),
            preview=str(result.extracted.get("preview", "") or ""),
            source_kind=str(result.extracted.get("source_kind", "") or ""),
            raw_pdf_meta=dict(result.extracted.get("raw_pdf_meta", {}) or {}),
        ),
    )


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _bool_form(value: str | bool | None, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int_form(value: str | int | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _payload_from_multipart(request: Request) -> IngestInput:
    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "read"):
        raise HTTPException(status_code=400, detail="multipart ingest requires a 'file' field")

    raw = await file.read()
    if not isinstance(raw, bytes) or len(raw) == 0:
        raise HTTPException(status_code=400, detail="empty upload")
    if len(raw) > MAX_INGEST_BYTES:
        raise HTTPException(status_code=413, detail="file too large")

    def _str(name: str) -> str:
        v = form.get(name)
        if isinstance(v, str):
            return v
        return ""

    return build_ingest_input_from_upload(
        raw=raw,
        filename=getattr(file, "filename", "") or "",
        content_type=getattr(file, "content_type", "") or "",
        title=_str("title"),
        authors=_split_csv(_str("authors")),
        year=_int_form(_str("year")),
        venue=_str("venue") or None,
        tags=_split_csv(_str("tags")),
        source_kind=_str("source_kind") or "user_upload",  # type: ignore[arg-type]
        source_uri=_str("source_uri"),
        trigger_evolution=_bool_form(_str("trigger_evolution"), default=True),
        llm_extract=_bool_form(_str("llm_extract"), default=True),
    )


async def _payload_from_json(request: Request) -> IngestInput:
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid json body: {exc}") from exc
    try:
        parsed = IngestPaperJSONInput.model_validate(body)
    except PydanticValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    return IngestInput(
        title=parsed.title,
        authors=list(parsed.authors),
        year=parsed.year,
        venue=parsed.venue,
        abstract=parsed.abstract,
        summary=parsed.summary,
        method=parsed.method,
        findings=parsed.findings,
        tags=list(parsed.tags),
        source_kind=parsed.source_kind,
        source_uri=parsed.source_uri,
        extras=dict(parsed.extras),
        trigger_evolution=parsed.trigger_evolution,
        llm_extract=parsed.llm_extract,
        body_text=parsed.body_text,
        raw_pdf_meta={},
        user_id=parsed.user_id,
        session_id=parsed.session_id,
    )


@router.post(
    "/papers/ingest",
    response_model=IngestPaperResponse,
    status_code=201,
    summary=(
        "Ingest a paper (PDF / MD / TXT or pure metadata): extract → upsert "
        "PaperCard → trigger memory evolution. Multipart and JSON bodies "
        "are both accepted (Content-Type decides)."
    ),
)
async def ingest_paper(
    request: Request,
    state: AppState = Depends(get_app_state),
) -> IngestPaperResponse:
    content_type = (request.headers.get("content-type") or "").lower()
    ingestor = _build_ingestor(state)

    try:
        if "multipart/form-data" in content_type:
            payload = await _payload_from_multipart(request)
        elif "application/json" in content_type:
            payload = await _payload_from_json(request)
        else:
            raise HTTPException(
                status_code=415,
                detail=(
                    "Content-Type must be 'multipart/form-data' (with a 'file' field) "
                    "or 'application/json' (with a metadata body)"
                ),
            )

        result = await ingestor.ingest(payload)
    except AAFValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        log.error("knowledge.ingest.failed", err=str(exc))
        raise HTTPException(status_code=500, detail=f"ingest failed: {exc}") from exc

    return _ingest_to_response(result)


@router.get(
    "/papers/{paper_id}",
    response_model=PaperCard,
    summary="Get one paper card",
)
async def get_paper(
    paper_id: str,
    state: AppState = Depends(get_app_state),
) -> PaperCard:
    store = _require_knowledge(state)
    card = await store.get(paper_id)
    if card is None:
        raise HTTPException(status_code=404, detail="paper not found")
    return card


@router.patch(
    "/papers/{paper_id}",
    response_model=PaperCard,
    summary="Partial update of a paper card (fields you omit are left alone)",
)
async def update_paper(
    paper_id: str,
    body: UpdatePaperCardInput,
    state: AppState = Depends(get_app_state),
) -> PaperCard:
    store = _require_knowledge(state)
    existing = await store.get(paper_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="paper not found")
    updates: dict[str, Any] = {
        k: v for k, v in body.model_dump(exclude_none=True).items() if v is not None
    }
    if not updates:
        return existing
    updated = existing.model_copy(update={**updates, "updated_at": datetime.now(UTC)})
    await store.write_card(updated)
    final = await store.get(paper_id)
    if final is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="update failed")
    return final


@router.delete(
    "/papers/{paper_id}",
    status_code=204,
    summary="Delete a paper card",
)
async def delete_paper(
    paper_id: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_knowledge(state)
    deleted = await store.delete(paper_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="paper not found")
    return Response(status_code=204)


@router.post(
    "/papers/{paper_id}/links",
    response_model=PaperCard,
    status_code=201,
    summary="Attach a typed link from this paper to another",
)
async def attach_link(
    paper_id: str,
    body: AttachLinkInput,
    state: AppState = Depends(get_app_state),
) -> PaperCard:
    store = _require_knowledge(state)
    try:
        await store.link(
            paper_id,
            body.target_paper_id,
            body.link_type,
            evidence=body.evidence,
            bidirectional=body.bidirectional,
        )
    except MemoryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    final = await store.get(paper_id)
    if final is None:  # pragma: no cover
        raise HTTPException(status_code=404, detail="paper not found")
    return final


# ---------------------------------------------------------------------------
# Synthesis endpoints
# ---------------------------------------------------------------------------


@router.get(
    "/syntheses",
    summary="List cluster-level synthesis notes",
)
async def list_syntheses(state: AppState = Depends(get_app_state)) -> dict[str, Any]:
    store = _require_knowledge(state)
    items = await store.list_synthesis()
    items.sort(key=lambda n: n.updated_at, reverse=True)
    return {
        "items": [n.model_dump(mode="json") for n in items],
        "total": len(items),
    }


@router.post(
    "/syntheses",
    response_model=SynthesisNote,
    status_code=201,
    summary="Upsert a synthesis note",
)
async def write_synthesis(
    body: WriteSynthesisInput,
    state: AppState = Depends(get_app_state),
) -> SynthesisNote:
    store = _require_knowledge(state)
    existing = await store.get_synthesis(body.cluster_tag)
    next_version = 1 if existing is None else existing.version + 1
    note = SynthesisNote(
        cluster_tag=body.cluster_tag,
        version=next_version,
        paper_ids=list(body.paper_ids),
        content=body.content,
        summary=body.summary,
        source_run_id=body.source_run_id,
    )
    await store.write_synthesis(note)
    final = await store.get_synthesis(body.cluster_tag)
    if final is None:  # pragma: no cover
        raise HTTPException(status_code=500, detail="synthesis persistence failed")
    return final


@router.get(
    "/syntheses/{cluster_tag}",
    response_model=SynthesisNote,
    summary="Read one synthesis note",
)
async def get_synthesis(
    cluster_tag: str,
    state: AppState = Depends(get_app_state),
) -> SynthesisNote:
    store = _require_knowledge(state)
    note = await store.get_synthesis(cluster_tag)
    if note is None:
        raise HTTPException(status_code=404, detail="synthesis not found")
    return note


@router.delete(
    "/syntheses/{cluster_tag}",
    status_code=204,
    summary="Delete a synthesis note",
)
async def delete_synthesis(
    cluster_tag: str,
    state: AppState = Depends(get_app_state),
) -> Response:
    store = _require_knowledge(state)
    deleted = await store.delete_synthesis(cluster_tag)
    if not deleted:
        raise HTTPException(status_code=404, detail="synthesis not found")
    return Response(status_code=204)


__all__ = ["TypedLink", "router"]
