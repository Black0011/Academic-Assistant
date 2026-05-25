"""Canonical Pydantic models for the five memory stores.

These shapes are the on-wire / on-disk contract. Store backends (YAML,
ChromaDB, Postgres, Redis) read and write exactly these models — no
per-backend schema drift.

See PLAN §11.2 / §23.3 / §23.4.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Knowledge — paper cards + typed links (§11, §11.7)
# ---------------------------------------------------------------------------


LinkType = Literal["extends", "contradicts", "applies", "motivated_by", "baseline_of"]


class TypedLink(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_paper_id: str
    link_type: LinkType
    evidence: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


class PaperCard(BaseModel):
    """One knowledge card. Mirrors the YAML layout under ``data/knowledge/``.

    All ``str | None`` fields default to ``None`` for **forward** compat too:
    YAML files written before a field existed simply lack the key, and
    Pydantic resolves to the default. We deliberately do NOT migrate old
    cards on read — the missing-key default is the migration.
    """

    model_config = ConfigDict(extra="forbid")

    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str = ""
    summary: str = ""  # Executor's consolidated reading note
    method: str = ""
    findings: str = ""
    tags: list[str] = Field(default_factory=list)
    typed_links: list[TypedLink] = Field(default_factory=list)
    # ---- P13 manual-CRUD metadata ---------------------------------------
    # ``url`` is the canonical source link (arxiv / doi / pdf / openreview).
    # ``field_major`` / ``field_minor`` form a two-level direction taxonomy
    # that users curate by hand (e.g. "NLP" / "LLM-Agent"). They're indexed
    # by ``search_text`` so a recall query like "找 RLHF 论文" surfaces
    # cards classified under those buckets even when the abstract doesn't
    # spell the term out.
    url: str | None = None
    field_major: str | None = None
    field_minor: str | None = None
    citation_url: str | None = None
    citation_bibtex: str | None = None
    experiment_results: str | None = None
    # ---------------------------------------------------------------------
    source_run_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    def search_text(self) -> str:
        """Concatenation used by keyword / embedding matchers."""
        parts = [
            self.title,
            " ".join(self.authors),
            self.abstract,
            self.summary,
            self.method,
            # category strings — let users find papers by their hand-curated
            # taxonomy even when the abstract doesn't mention the term.
            self.field_major or "",
            self.field_minor or "",
        ]
        return "\n".join(p for p in parts if p).strip()


# ---------------------------------------------------------------------------
# Heuristic — L3 strategies (§8 / §23.3)
# ---------------------------------------------------------------------------


HeuristicDomain = Literal["research", "writing", "revision", "rebuttal", "survey"]
HeuristicVerdict = Literal["pass", "fail"]


class StrategyBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    planning_hints: str = ""
    search_tips: str = ""
    evaluation_criteria: str = ""


class Heuristic(BaseModel):
    """L3 skill. Exactly the YAML schema from PLAN §23.3."""

    model_config = ConfigDict(extra="forbid")

    id: str  # 12-hex canonical; see gen_id()
    name: str
    description: str = ""
    domain: HeuristicDomain
    trigger_pattern: str = ""  # comma-separated keywords
    strategy: StrategyBlock = Field(default_factory=StrategyBlock)
    source_query: str = ""
    source_verdict: HeuristicVerdict = "pass"
    source_run_id: str = ""
    success_count: int = 1
    failure_count: int = 0
    frozen: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @property
    def total_count(self) -> int:
        return self.success_count + self.failure_count

    @property
    def failure_rate(self) -> float:
        total = self.total_count
        return self.failure_count / total if total else 0.0


# ---------------------------------------------------------------------------
# Episodic — reflections / observations / insights (§23.4)
# ---------------------------------------------------------------------------


ReflectionType = Literal["reflection", "observation", "insight"]


class Reflection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: ReflectionType = "reflection"
    content: str
    tags: list[str] = Field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
    source_run_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Session — multi-turn context (§23.4)
# ---------------------------------------------------------------------------


class SessionMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system", "tool"] = "user"
    content: str = ""
    created_at: datetime = Field(default_factory=_utcnow)
    meta: dict = Field(default_factory=dict)


class SessionContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: str
    user_id: str | None = None
    title: str = ""
    state: dict = Field(default_factory=dict)
    messages: list[SessionMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Vector hit — one match result from VectorStore.query()
# ---------------------------------------------------------------------------


class VectorHit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    doc_id: str
    score: float  # [0, 1], higher is better
    text: str = ""
    metadata: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Aggregate snapshot for Planner's one-shot memory read (§11.4)
# ---------------------------------------------------------------------------


class SynthesisNote(BaseModel):
    """Cluster-level synthesis produced by the A-Mem evolver (PLAN §11.7).

    A synthesis note summarises ``N`` papers that share a ``cluster_tag``
    once the cluster crosses a configurable threshold. Multiple
    generations are allowed — ``version`` bumps each time a new
    synthesis supersedes the previous one for the same tag.
    """

    model_config = ConfigDict(extra="forbid")

    cluster_tag: str
    version: int = 1
    paper_ids: list[str] = Field(default_factory=list)
    content: str = ""
    summary: str = ""
    source_run_id: str | None = None
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Document RAG — KnowledgeDocument + DocChunk (M7.3)
# ---------------------------------------------------------------------------


DocumentSourceKind = Literal[
    "pdf_upload",
    "md_upload",
    "txt_upload",
    "note",
    "url",
    "clipboard",
]


class DocChunk(BaseModel):
    """One contiguous slice of a :class:`KnowledgeDocument`.

    ``chunk_id`` is deterministic — ``f"{doc_id}#{idx:04d}"`` — so the
    same chunk always has the same id across re-indexes. The vector store
    keeps an entry per chunk with ``metadata={"kind": "doc_chunk", "doc_id":
    ..., "idx": ..., "section_path": [...], "tags": [...]}``.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    idx: int
    text: str
    char_offset_start: int = 0
    char_offset_end: int = 0
    section_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class KnowledgeDocument(BaseModel):
    """Free-form document ingested for RAG.

    Orthogonal to :class:`PaperCard`: PaperCard is structured "I read this
    paper, here are the takeaways"; KnowledgeDocument is "I dropped this
    blob in, please retrieve relevant chunks when answering questions".
    """

    model_config = ConfigDict(extra="forbid")

    doc_id: str
    title: str
    source_kind: DocumentSourceKind = "note"
    source_uri: str | None = None
    summary: str = ""
    raw_text: str = ""
    tags: list[str] = Field(default_factory=list)
    chunk_ids: list[str] = Field(default_factory=list)
    bytes: int = 0
    user_id: str | None = None
    session_id: str | None = None
    source_run_id: str | None = None
    extras: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class DocChunkHit(BaseModel):
    """One match returned by ``DocumentStore.search_chunks``.

    Carries enough context for callers to render ``doc_title > section_path
    -> snippet`` without a second round-trip.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    doc_id: str
    doc_title: str
    text: str
    score: float
    section_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class MemorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    domain: str = ""
    vector_summary: str = ""
    related_papers: list[PaperCard] = Field(default_factory=list)
    heuristics: list[Heuristic] = Field(default_factory=list)
    recent_reflections: list[Reflection] = Field(default_factory=list)
    doc_chunks: list[DocChunkHit] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)

    def doc_chunks_text(self, *, max_chars: int = 1200) -> str:
        """Flatten ``doc_chunks`` into a prompt slice ready for injection.

        Format: ``- doc_title > Section > Sub: snippet`` (truncated at
        ``max_chars``). Used by workflows when assembling the recall slice
        of the prompt — keeps the output deterministic across runs.
        """
        if not self.doc_chunks:
            return ""
        out: list[str] = []
        used = 0
        for hit in self.doc_chunks:
            crumb = " > ".join([hit.doc_title, *hit.section_path]) if hit.doc_title else ""
            snippet = (hit.text or "").strip().replace("\n", " ")
            line = f"- {crumb}: {snippet}" if crumb else f"- {snippet}"
            if used + len(line) > max_chars:
                out.append(line[: max(0, max_chars - used)] + "...")
                break
            out.append(line)
            used += len(line)
        return "\n".join(out)


__all__ = [
    "DocChunk",
    "DocChunkHit",
    "DocumentSourceKind",
    "Heuristic",
    "HeuristicDomain",
    "HeuristicVerdict",
    "KnowledgeDocument",
    "LinkType",
    "MemorySnapshot",
    "PaperCard",
    "Reflection",
    "ReflectionType",
    "SessionContext",
    "SessionMessage",
    "StrategyBlock",
    "SynthesisNote",
    "TypedLink",
    "VectorHit",
]
