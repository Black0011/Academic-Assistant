"""Hand-mirrored DTOs for the AAF HTTP API.

Mirrors a subset of `backend/api/routers/*.py` and the canonical Pydantic
models under `backend.tasks.models`, `backend.manuscripts.models`,
`backend.memory.models`, and `backend.core.auth.models`. We re-declare
them here so the SDK can be installed in environments where the backend
package is not available.

When the schemas drift, regenerate against `/openapi.json` from a running
server — see `aaf.client.AsyncAAFClient.openapi()`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

UserRole = Literal["admin", "user"]


class AuthConfig(BaseModel):
    enabled: bool
    allow_signup: bool


class PublicUser(BaseModel):
    id: str
    email: str
    display_name: str = ""
    role: UserRole = "user"
    disabled: bool = False


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: PublicUser


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------

TaskStatus = Literal["queued", "running", "ok", "error", "cancelled"]


class TaskRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    workflow: str
    status: TaskStatus = "queued"
    query: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in {"ok", "error", "cancelled"}


class CreateTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    workflow: str


class TaskEventRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str
    seq: int
    type: str
    at: datetime
    data: dict[str, Any] = Field(default_factory=dict)


class StreamEvent(BaseModel):
    """One event off the SSE stream — a slimmer cousin of TaskEventRecord
    used by the synthetic events the API emits inline (e.g. errors)."""

    type: str
    task_id: str | None = None
    at: datetime | None = None
    data: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Manuscripts
# ---------------------------------------------------------------------------

ManuscriptKind = Literal["paper", "section", "outline", "note"]
ManuscriptStatus = Literal["draft", "in_revision", "final", "archived"]
ManuscriptOrigin = Literal[
    "user_upload",
    "write_workflow",
    "revision_workflow",
    "ingest",
    "api",
]


class Manuscript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    title: str
    kind: ManuscriptKind
    status: ManuscriptStatus
    section: str | None = None
    topic: str | None = None
    tags: list[str] = Field(default_factory=list)
    current_version: int = 0
    origin: ManuscriptOrigin = "api"
    user_id: str | None = None
    session_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ManuscriptVersion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    manuscript_id: str
    version: int
    content: str
    note: str = ""
    produced_by: str | None = None
    origin: ManuscriptOrigin = "api"
    citations: list[str] = Field(default_factory=list)
    reviewer_comments: list[dict[str, Any]] = Field(default_factory=list)
    word_count: int = 0
    created_at: datetime | None = None


class ManuscriptEnvelope(BaseModel):
    manuscript: Manuscript
    version: ManuscriptVersion | None = None


# ---------------------------------------------------------------------------
# Memory — knowledge cards / heuristics / reflections
# ---------------------------------------------------------------------------

ReflectionType = Literal["reflection", "observation", "insight"]
HeuristicDomain = Literal["research", "writing", "revision", "rebuttal", "survey"]
HeuristicVerdict = Literal["pass", "fail"]


LinkType = Literal["extends", "contradicts", "applies", "motivated_by", "baseline_of"]
SourceKind = Literal["user_upload", "arxiv", "doi", "manual"]


class TypedLink(BaseModel):
    model_config = ConfigDict(extra="ignore")

    target_paper_id: str
    link_type: LinkType
    evidence: str = ""
    created_at: datetime | None = None


class PaperCard(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    abstract: str = ""
    summary: str = ""
    method: str = ""
    findings: str = ""
    tags: list[str] = Field(default_factory=list)
    typed_links: list[TypedLink] = Field(default_factory=list)
    source_run_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SynthesisNote(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cluster_tag: str
    version: int = 1
    paper_ids: list[str] = Field(default_factory=list)
    content: str = ""
    summary: str = ""
    source_run_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class IngestEvolution(BaseModel):
    model_config = ConfigDict(extra="ignore")

    paper_id: str
    mode: str
    typed_links_added: list[TypedLink] = Field(default_factory=list)
    tags_added: list[str] = Field(default_factory=list)
    neighbors_considered: int = 0
    reason: str = ""


class IngestExtracted(BaseModel):
    model_config = ConfigDict(extra="ignore")

    method: str = "heuristic"
    extract_ms: int = 0
    evolve_ms: int = 0
    preview: str = ""
    source_kind: str = ""
    raw_pdf_meta: dict[str, Any] = Field(default_factory=dict)


class IngestPaperResponse(BaseModel):
    """Result of ``KnowledgeAPI.ingest_paper`` (M7.1)."""

    model_config = ConfigDict(extra="ignore")

    card: PaperCard
    evolution: IngestEvolution
    synthesis: SynthesisNote | None = None
    extracted: IngestExtracted


class StrategyBlock(BaseModel):
    planning_hints: str = ""
    search_tips: str = ""
    evaluation_criteria: str = ""


class Heuristic(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str = ""
    domain: HeuristicDomain
    trigger_pattern: str = ""
    strategy: StrategyBlock = Field(default_factory=StrategyBlock)
    source_query: str = ""
    source_verdict: HeuristicVerdict = "pass"
    source_run_id: str = ""
    success_count: int = 1
    failure_count: int = 0
    frozen: bool = False
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Reflection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: ReflectionType = "reflection"
    content: str
    tags: list[str] = Field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
    source_run_id: str | None = None
    created_at: datetime | None = None


class MemoryStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    vector_count: int | None = None
    knowledge_count: int = 0
    synthesis_count: int = 0
    heuristic_count: int = 0
    reflection_count: int | None = None
    session_backend: str = ""


class RollbackResponse(BaseModel):
    run_id: str
    knowledge_removed: int = 0
    heuristics_removed: int = 0
    reflections_removed: int = 0


# ---------------------------------------------------------------------------
# Workflows / Tools / Misc
# ---------------------------------------------------------------------------


class WorkflowInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""


class ToolInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    requires_network: bool = False
    requires_paid_api: bool = False


class VersionInfo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str
    llm_provider: str | None = None
    memory: dict[str, str | None] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Skills (M7.2)
# ---------------------------------------------------------------------------


SkillInvocationStatus = Literal["success", "error", "timeout", "dry_run"]


class SkillScriptDescriptor(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    requires_network: bool = False
    max_duration_s: int | None = None
    uses_llm: bool = False
    args_schema: dict[str, Any] | None = None
    size_bytes: int = 0


class SkillSummary(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    domain: str | None = None
    triggers: list[str] = Field(default_factory=list)
    version: str = "0.0.0"
    enabled: bool = True
    scripts: list[str] = Field(default_factory=list)
    uses_llm_any: bool = False
    last_used_at: datetime | None = None
    invocation_count_30d: int = 0
    avg_elapsed_ms: float = 0.0
    version_hash: str = ""
    loaded_from: str = ""


class SkillDetail(SkillSummary):
    body_md: str = ""
    scripts_detail: list[SkillScriptDescriptor] = Field(default_factory=list)


class SkillScriptSource(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    source: str
    size_bytes: int = 0


class SkillInvocation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skill: str
    script: str
    tool_name: str = ""
    task_id: str = ""
    status: SkillInvocationStatus
    started_at: datetime
    duration_ms: float = 0.0
    args_summary: str = ""
    result_preview: str = ""
    error: str = ""


class SkillScriptInput(BaseModel):
    name: str
    content: str


class SkillInstallInput(BaseModel):
    name: str
    body_md: str
    scripts: list[SkillScriptInput] = Field(default_factory=list)
    overwrite: bool = False


class SkillReloadResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    generation: int = 0


class SkillDryRunResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool
    returncode: int = 0
    duration_ms: float = 0.0
    timed_out: bool = False
    stdout: str = ""
    stderr: str = ""


# ---------------------------------------------------------------------------
# Documents (M7.3) — KnowledgeDocument / DocChunk / DocChunkHit
# ---------------------------------------------------------------------------


DocumentSourceKind = Literal[
    "pdf_upload", "md_upload", "txt_upload", "note", "url", "clipboard"
]


class DocChunk(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str
    idx: int
    text: str = ""
    char_offset_start: int = 0
    char_offset_end: int = 0
    section_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class KnowledgeDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")

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
    extras: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DocChunkHit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chunk_id: str
    doc_id: str
    doc_title: str = ""
    text: str = ""
    score: float = 0.0
    section_path: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class IngestDocumentResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    document: KnowledgeDocument
    chunks_indexed: int = 0
    indexer_ms: int = 0


# ---------------------------------------------------------------------------
# Proposals (M8.1) — gated proposal subsystem
# ---------------------------------------------------------------------------

ProposalStatus = Literal[
    "draft", "pending", "approved", "rejected", "applied", "withdrawn"
]
RiskLevel = Literal["low", "medium", "high", "tier_d"]
ProposerKind = Literal["human", "llm", "agent"]
ProposalAction = Literal[
    "create", "update", "submit", "approve", "reject", "apply", "withdraw", "comment"
]


class ProposalAuditEvent(BaseModel):
    model_config = ConfigDict(extra="ignore")

    timestamp: datetime
    actor: str = ""
    action: ProposalAction
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="ignore")

    proposal_id: str
    title: str
    summary: str = ""
    motivation: str = ""
    risk_level: RiskLevel = "low"
    target_paths: list[str] = Field(default_factory=list)
    diff: str = ""
    status: ProposalStatus = "draft"
    proposer_id: str = ""
    proposer_kind: ProposerKind = "human"
    reviewer_id: str | None = None
    review_notes: str = ""
    tags: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    decided_at: datetime | None = None
    applied_at: datetime | None = None
    audit_log: list[ProposalAuditEvent] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)


class ProposalListResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    items: list[Proposal] = Field(default_factory=list)
    total: int = 0


# ---------------------------------------------------------------------------
# Planner (M8.2) — DAG compile / validate / execute
# ---------------------------------------------------------------------------

NodeKind = Literal["llm", "tool", "skill", "memory.read", "memory.write"]
OnFailure = Literal["abort", "skip", "continue"]
NodeStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


class PlanNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    kind: NodeKind
    name: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str = ""
    expected_output: str = ""
    on_failure: OnFailure = "abort"
    retries: int = 0


class PlanDAG(BaseModel):
    model_config = ConfigDict(extra="ignore")

    plan_id: str
    query: str
    domain: str = ""
    nodes: list[PlanNode] = Field(default_factory=list)
    rationale: str = ""
    estimated_steps: int = 0
    created_at: datetime | None = None
    llm_provider: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class ValidatePlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NodeOutcome(BaseModel):
    model_config = ConfigDict(extra="ignore")

    node_id: str
    kind: NodeKind
    name: str = ""
    status: NodeStatus = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    attempts: int = 0


class SkillForCompile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    domain: str = ""
    triggers: list[str] = Field(default_factory=list)
    invocation_modes: list[str] = Field(default_factory=list)


class ToolForCompile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class SkillsForCompileResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skills: list[SkillForCompile] = Field(default_factory=list)
    tools: list[ToolForCompile] = Field(default_factory=list)


class ExecutePlanResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str
    status: TaskStatus = "queued"
    workflow: str = "dag"
    plan_id: str
    node_count: int = 0


__all__ = [
    "AuthConfig",
    "CreateTaskResponse",
    "DocChunk",
    "DocChunkHit",
    "DocumentSourceKind",
    "ExecutePlanResponse",
    "Heuristic",
    "HeuristicDomain",
    "HeuristicVerdict",
    "IngestDocumentResponse",
    "IngestEvolution",
    "IngestExtracted",
    "IngestPaperResponse",
    "KnowledgeDocument",
    "LinkType",
    "Manuscript",
    "ManuscriptEnvelope",
    "ManuscriptKind",
    "ManuscriptOrigin",
    "ManuscriptStatus",
    "ManuscriptVersion",
    "MemoryStats",
    "NodeKind",
    "NodeOutcome",
    "NodeStatus",
    "OnFailure",
    "PaperCard",
    "PlanDAG",
    "PlanNode",
    "Proposal",
    "ProposalAction",
    "ProposalAuditEvent",
    "ProposalListResponse",
    "ProposalStatus",
    "ProposerKind",
    "PublicUser",
    "Reflection",
    "ReflectionType",
    "RiskLevel",
    "RollbackResponse",
    "SkillDetail",
    "SkillDryRunResponse",
    "SkillForCompile",
    "SkillInstallInput",
    "SkillInvocation",
    "SkillInvocationStatus",
    "SkillReloadResponse",
    "SkillScriptDescriptor",
    "SkillScriptInput",
    "SkillScriptSource",
    "SkillSummary",
    "SkillsForCompileResponse",
    "SourceKind",
    "StrategyBlock",
    "StreamEvent",
    "SynthesisNote",
    "TaskEventRecord",
    "TaskRecord",
    "TaskStatus",
    "ToolForCompile",
    "ToolInfo",
    "TokenResponse",
    "TypedLink",
    "UserRole",
    "ValidatePlanResponse",
    "VersionInfo",
    "WorkflowInfo",
]
