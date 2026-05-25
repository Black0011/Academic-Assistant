/**
 * Mirrors of the backend Pydantic DTOs we consume.
 *
 * We don't auto-generate from OpenAPI (yet) — the surface is small enough
 * that hand-typed mirrors are clearer + cheaper to keep in sync. If/when
 * the schema explodes we'll switch to `openapi-typescript`.
 */

export type TaskStatus = "queued" | "running" | "ok" | "error" | "cancelled" | "waiting";

export interface TaskRecord {
  id: string;
  workflow: string;
  status: TaskStatus;
  query: string;
  input: Record<string, unknown>;
  budget: Record<string, unknown>;
  result: Record<string, unknown> | null;
  error: string | null;
  user_id: string | null;
  session_id: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  paused_at: string | null;
}

export interface RespondToTaskInput {
  response: string;
  response_data: Record<string, unknown>;
}

export interface AwaitingInputState {
  prompt: string;
  checkpoint: string;
  prompt_data: Record<string, unknown>;
  stage: string;
}

export interface TaskListResponse {
  items: TaskRecord[];
  total: number;
}

export interface TaskEventRecord {
  task_id: string;
  seq: number;
  type: string;
  at: string;
  data: Record<string, unknown>;
}

export interface CreateTaskInput {
  workflow: string;
  query?: string;
  input?: Record<string, unknown>;
  user_id?: string | null;
  session_id?: string | null;
  budget_usd?: number | null;
}

export interface CreateTaskResponse {
  task_id: string;
  status: TaskStatus;
  workflow: string;
}

export interface BuildInfo {
  git_sha: string;
  git_sha_short: string;
  git_dirty: boolean;
  commit_ts: string;
  commit_subject: string;
}

export interface VersionInfo {
  version: string;
  // P12.2 — identity of the running backend process. Lets the TopBar
  // show the user which commit they're talking to and surfaces uncommitted
  // changes ("dirty") so an old/stale backend can't hide.
  build: BuildInfo;
  llm_provider: string | null;
  memory: {
    vector: string | null;
    knowledge: string | null;
    heuristic: string | null;
    episodic: string | null;
    session: string | null;
  };
  tools: string[];
}

export interface MemoryStats {
  vector_count: number | null;
  knowledge_count: number;
  synthesis_count: number;
  heuristic_count: number;
  reflection_count: number | null;
  session_backend: string;
  generated_at_epoch_s?: number | null;
}

export interface WorkflowInfo {
  name: string;
  description?: string;
}

export interface ToolInfo {
  name: string;
  description?: string;
  schema?: Record<string, unknown>;
  capabilities?: string[];
}

export interface ManuscriptStats {
  total: number;
  by_status: Record<string, number>;
}

export type ManuscriptKind = "paper" | "section" | "outline" | "note";
export type ManuscriptStatus = "draft" | "in_revision" | "final" | "archived";
export type ManuscriptOrigin =
  | "user_upload"
  | "write_workflow"
  | "revision_workflow"
  | "ingest"
  | "api";

export interface Manuscript {
  id: string;
  title: string;
  kind: ManuscriptKind;
  status: ManuscriptStatus;
  section: string | null;
  topic: string | null;
  tags: string[];
  current_version: number;
  origin: ManuscriptOrigin;
  user_id: string | null;
  session_id: string | null;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  // P7 — bundle layout fields. Defaults preserve the pre-P7 single-doc shape.
  layout: "single" | "bundle";
  bundle_link_path: string | null;
  bundle_versioning: boolean;
}

export interface ManuscriptVersion {
  manuscript_id: string;
  version: number;
  content: string;
  note: string;
  produced_by: string | null;
  origin: ManuscriptOrigin;
  citations: string[];
  reviewer_comments: Array<Record<string, unknown>>;
  word_count: number;
  created_at: string;
}

export interface ManuscriptListResponse {
  items: Manuscript[];
  total: number;
}

export interface VersionListResponse {
  items: ManuscriptVersion[];
  total: number;
}

export interface ManuscriptEnvelope {
  manuscript: Manuscript;
  version: ManuscriptVersion | null;
}

export interface CreateManuscriptInput {
  title?: string;
  kind?: ManuscriptKind;
  status?: ManuscriptStatus;
  section?: string | null;
  topic?: string | null;
  tags?: string[];
  user_id?: string | null;
  session_id?: string | null;
  meta?: Record<string, unknown>;
  content?: string;
  note?: string;
  citations?: string[];
}

export interface UpdateManuscriptInput {
  title?: string;
  status?: ManuscriptStatus;
  section?: string | null;
  topic?: string | null;
  tags?: string[];
  meta?: Record<string, unknown>;
}

export interface CommitVersionInput {
  content: string;
  note?: string;
  origin?: ManuscriptOrigin;
  produced_by?: string | null;
  citations?: string[];
  reviewer_comments?: Array<Record<string, unknown>>;
}

export interface ListManuscriptsParams {
  user_id?: string;
  status?: ManuscriptStatus;
  kind?: ManuscriptKind;
  tag?: string;
  limit?: number;
  offset?: number;
}

// ---------------------------------------------------------------------------
// Manuscript bundles (P7) — multi-file project layout
// ---------------------------------------------------------------------------

export type ManuscriptLayout = "single" | "bundle";

export interface ManuscriptFile {
  path: string;
  size: number;
  mime: string;
  is_text: boolean;
  sha256: string | null;
  modified_at: string;
  content?: string | null;
}

export interface BundleManifest {
  manuscript_id: string;
  layout: ManuscriptLayout;
  root: string;
  link_mode: boolean;
  file_count: number;
  total_size: number;
  files: ManuscriptFile[];
}

/** Read response envelope for `GET /manuscripts/{id}/files/{path}` (text or
 *  small-binary). Larger binaries should use the dedicated download URL. */
export interface FileEnvelope {
  file: ManuscriptFile;
  encoding: "utf-8" | "base64";
  content: string;
}

export interface BundleConvertInput {
  link_path?: string | null;
  versioning?: boolean;
}

export interface ImportFolderInput {
  local_path: string;
  mode?: "copy" | "link";
  title?: string;
  kind?: ManuscriptKind;
  overwrite?: boolean;
  user_id?: string | null;
  session_id?: string | null;
}

export interface WriteFileInput {
  content: string;
  encoding?: "utf-8";
}

/** Subset of the SSE event types we render. The full canonical list lives
 *  in PLAN §23.5 and `backend/core/events.py:EventType`. */
export const EVENT_TYPES = [
  "task.start",
  "task.end",
  "task.error",
  "task.retry",
  "task.stage_start",
  "task.stage_end",
  "task.checkpoint",
  "task.awaiting_input",
  "task.resume",
  "task.user_input",
  "skill.matched",
  "skill.call",
  "skill.result",
  "llm.call",
  "llm.token",
  "rule.block",
  "memory.read",
  "memory.write",
  "memory.rollback",
] as const;

export type EventType = (typeof EVENT_TYPES)[number];

export interface StreamEvent {
  type: string;
  task_id: string;
  at: string;
  data: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Auth (M5)
// ---------------------------------------------------------------------------

export type UserRole = "admin" | "user";

export interface AuthConfig {
  enabled: boolean;
  allow_signup: boolean;
}

export interface PublicUser {
  id: string;
  email: string;
  display_name: string;
  role: UserRole;
  disabled: boolean;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: PublicUser;
}

export interface LoginInput {
  email: string;
  password: string;
}

export interface RegisterInput {
  email: string;
  password: string;
  display_name?: string;
}

// ---------------------------------------------------------------------------
// Memory Explorer (M5)
// ---------------------------------------------------------------------------

export type ReflectionType = "reflection" | "observation" | "insight";
export type HeuristicDomain = "research" | "writing" | "revision" | "rebuttal" | "survey";
export type HeuristicVerdict = "pass" | "fail";
export type LinkType = "extends" | "contradicts" | "applies" | "motivated_by" | "baseline_of";

export interface TypedLink {
  target_paper_id: string;
  link_type: LinkType;
  evidence: string;
  created_at: string;
}

/** Mirrors `backend.memory.models.PaperCard`. */
export interface PaperCard {
  paper_id: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  abstract: string;
  summary: string;
  method: string;
  findings: string;
  tags: string[];
  typed_links: TypedLink[];
  // P13 — manual-CRUD metadata. ``url`` is the canonical source link;
  // ``field_major`` / ``field_minor`` form a two-level taxonomy the user
  // maintains by hand. All three are nullable on legacy cards.
  url: string | null;
  field_major: string | null;
  field_minor: string | null;
  citation_url: string | null;
  citation_bibtex: string | null;
  experiment_results: string | null;
  source_run_id: string | null;
  user_id: string | null;
  session_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface PaperListResponse {
  items: PaperCard[];
  total: number;
}

/** Mirrors `backend.api.routers.knowledge.CreatePaperCardInput` (P13.C). */
export interface CreatePaperCardInput {
  paper_id?: string;
  title: string;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  abstract?: string;
  summary?: string;
  method?: string;
  findings?: string;
  tags?: string[];
  url?: string | null;
  field_major?: string | null;
  field_minor?: string | null;
  citation_url?: string | null;
  citation_bibtex?: string | null;
  experiment_results?: string | null;
  source_run_id?: string | null;
  user_id?: string | null;
  session_id?: string | null;
}

/** Mirrors `backend.api.routers.knowledge.UpdatePaperCardInput` (P13.C).
 *
 * All fields optional — the server merges via ``exclude_none=True``.
 * Clear a field by passing an empty string (``null`` is treated as
 * "leave unchanged" per the backend convention). */
export interface UpdatePaperCardInput {
  title?: string;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  abstract?: string;
  summary?: string;
  method?: string;
  findings?: string;
  tags?: string[];
  url?: string | null;
  field_major?: string | null;
  field_minor?: string | null;
  citation_url?: string | null;
  citation_bibtex?: string | null;
  experiment_results?: string | null;
}

export interface SynthesisNote {
  cluster_tag: string;
  version: number;
  paper_ids: string[];
  content: string;
  summary: string;
  source_run_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface SynthesisListResponse {
  items: SynthesisNote[];
  total: number;
}

// ---------------------------------------------------------------------------
// Paper ingest (M7.1)  — POST /api/knowledge/papers/ingest
// ---------------------------------------------------------------------------

export type IngestSourceKind = "user_upload" | "arxiv" | "doi" | "manual";

export interface IngestEvolution {
  paper_id: string;
  mode: string;
  typed_links_added: TypedLink[];
  tags_added: string[];
  neighbors_considered: number;
  reason: string;
}

export interface IngestExtracted {
  method: string;
  extract_ms: number;
  evolve_ms: number;
  preview: string;
  source_kind: string;
  raw_pdf_meta: Record<string, unknown>;
}

export interface IngestPaperResponse {
  card: PaperCard;
  evolution: IngestEvolution;
  synthesis: SynthesisNote | null;
  extracted: IngestExtracted;
}

export interface IngestPaperJSONInput {
  title: string;
  authors?: string[];
  year?: number | null;
  venue?: string | null;
  abstract?: string;
  summary?: string;
  method?: string;
  findings?: string;
  tags?: string[];
  source_kind?: IngestSourceKind;
  source_uri?: string;
  body_text?: string;
  trigger_evolution?: boolean;
  llm_extract?: boolean;
}

export interface StrategyBlock {
  planning_hints: string;
  search_tips: string;
  evaluation_criteria: string;
}

/** Mirrors `backend.memory.models.Heuristic`. */
export interface Heuristic {
  id: string;
  name: string;
  description: string;
  domain: HeuristicDomain;
  trigger_pattern: string;
  strategy: StrategyBlock;
  source_query: string;
  source_verdict: HeuristicVerdict;
  source_run_id: string;
  success_count: number;
  failure_count: number;
  frozen: boolean;
  created_at: string;
  updated_at: string;
}

export interface HeuristicListResponse {
  items: Heuristic[];
  total: number;
}

export interface Reflection {
  id: string;
  type: ReflectionType;
  content: string;
  tags: string[];
  user_id: string | null;
  session_id: string | null;
  source_run_id: string | null;
  created_at?: string;
}

export interface ReflectionListResponse {
  items: Reflection[];
  total: number;
}

export interface RollbackResponse {
  run_id: string;
  knowledge_removed: number;
  heuristics_removed: number;
  reflections_removed: number;
}

// ---------------------------------------------------------------------------
// Skills (M7.2)  — /api/skills/*
// ---------------------------------------------------------------------------

export type SkillInvocationStatus = "success" | "error" | "timeout" | "dry_run";

export interface SkillScriptDescriptor {
  name: string;
  description: string;
  requires_network: boolean;
  max_duration_s: number | null;
  uses_llm: boolean;
  args_schema: Record<string, unknown> | null;
  size_bytes: number;
}

export interface SkillSummary {
  name: string;
  description: string;
  domain: string | null;
  triggers: string[];
  version: string;
  enabled: boolean;
  scripts: string[];
  uses_llm_any: boolean;
  last_used_at: string | null;
  invocation_count_30d: number;
  avg_elapsed_ms: number;
  version_hash: string;
  loaded_from: string;
}

export interface SkillListResponse {
  items: SkillSummary[];
  total: number;
  generation: number;
}

export interface SkillDetail extends SkillSummary {
  body_md: string;
  scripts_detail: SkillScriptDescriptor[];
}

// P13.B — GET /api/skills/graph.
//
// Mirrors `backend.api.routers.skills.SkillGraphResponse`. Each edge is a
// directed flow ``source -> target``; ``declared_by`` carries whether
// the relation lived on the source side (downstream), target side
// (upstream), or both. Cycles + dangling references are surfaced so the
// UI can highlight them, not so the backend pre-emptively refuses.
export interface SkillGraphNode {
  name: string;
  domain: string | null;
  version: string;
  enabled: boolean;
  description: string;
}

export interface SkillGraphEdge {
  source: string;
  target: string;
  declared_by: "source" | "target" | "both";
}

export interface SkillGraphResponse {
  nodes: SkillGraphNode[];
  edges: SkillGraphEdge[];
  dangling: string[];
  cycles: string[][];
  generation: number;
}

// ---------------------------------------------------------------------------
// P14.C — POST /api/skills/{name}:edges (graph-view drag/delete editor)
// ---------------------------------------------------------------------------
//
// One op declares "this edge mutation is scoped to ``<source>``'s
// frontmatter". Removing a both-sides-declared edge requires two calls,
// one to each end — the backend deliberately doesn't auto-cascade so
// that the UI stays in control of which side declares which.

export type SkillEdgeKind = "downstream" | "upstream";

export interface SkillEdgeOp {
  kind: SkillEdgeKind;
  target: string;
}

export interface SkillEdgesUpdateInput {
  add?: SkillEdgeOp[];
  remove?: SkillEdgeOp[];
}

export interface SkillEdgesUpdateResponse {
  name: string;
  body_md: string;
  // Tuples are (kind, target). Kept as plain arrays so the JSON wire
  // format matches Python's ``list[tuple[str, str]]`` exactly.
  added: [SkillEdgeKind, string][];
  removed: [SkillEdgeKind, string][];
  skipped_dup: [SkillEdgeKind, string][];
  skipped_missing: [SkillEdgeKind, string][];
  warnings: string[];
}

export interface SkillScriptSource {
  name: string;
  source: string;
  size_bytes: number;
}

export interface SkillInvocation {
  skill: string;
  script: string;
  tool_name: string;
  task_id: string;
  status: SkillInvocationStatus;
  started_at: string;
  duration_ms: number;
  args_summary: string;
  result_preview: string;
  error: string;
}

export interface SkillInvocationListResponse {
  items: SkillInvocation[];
  total: number;
  window_days: number;
}

export interface SkillScriptInput {
  name: string;
  content: string;
}

export interface SkillInstallInput {
  name: string;
  body_md: string;
  scripts: SkillScriptInput[];
  overwrite?: boolean;
}

export interface SkillReloadResponse {
  name: string | null;
  generation: number;
}

export interface SkillDryRunResponse {
  ok: boolean;
  returncode: number;
  duration_ms: number;
  timed_out: boolean;
  stdout: string;
  stderr: string;
}

// ---------------------------------------------------------------------------
// Documents (M7.3) — /api/documents/*
// ---------------------------------------------------------------------------

export type DocumentSourceKind =
  | "pdf_upload"
  | "md_upload"
  | "txt_upload"
  | "note"
  | "url"
  | "clipboard";

export interface DocChunk {
  chunk_id: string;
  doc_id: string;
  idx: number;
  text: string;
  char_offset_start: number;
  char_offset_end: number;
  section_path: string[];
  tags: string[];
}

export interface KnowledgeDocument {
  doc_id: string;
  title: string;
  source_kind: DocumentSourceKind;
  source_uri: string | null;
  summary: string;
  raw_text: string;
  tags: string[];
  chunk_ids: string[];
  bytes: number;
  user_id: string | null;
  session_id: string | null;
  source_run_id: string | null;
  extras: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocChunkHit {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  text: string;
  score: number;
  section_path: string[];
  tags: string[];
}

export interface IngestDocumentResponse {
  document: KnowledgeDocument;
  chunks_indexed: number;
  indexer_ms: number;
}

export interface DocumentListResponse {
  items: KnowledgeDocument[];
  total: number;
}

export interface DocumentChunkPage {
  items: DocChunk[];
  total: number;
}

export interface DocumentSearchResponse {
  items: DocChunkHit[];
  total: number;
}

export interface IngestDocumentJSONInput {
  title?: string;
  raw_text: string;
  source_kind?: DocumentSourceKind;
  source_uri?: string;
  summary?: string;
  tags?: string[];
  target_tokens?: number;
  overlap_tokens?: number;
}

/**
 * P14.B — partial-update payload for ``PATCH /api/documents/{id}``.
 *
 * ``raw_text`` is intentionally absent: editing the body without
 * re-chunking would silently desync persisted text from vector
 * embeddings. For body changes call ``reindex`` instead.
 *
 * Every field optional ⇒ ``None`` (or omitted) means "leave alone";
 * the backend's ``extra="forbid"`` rejects unknown keys.
 */
export interface UpdateDocumentInput {
  title?: string;
  summary?: string;
  tags?: string[];
  source_kind?: DocumentSourceKind;
  source_uri?: string;
}

// ---------------------------------------------------------------------------
// Proposals (M8.1)
// ---------------------------------------------------------------------------

export type ProposalStatus =
  | "draft"
  | "pending"
  | "approved"
  | "rejected"
  | "applied"
  | "withdrawn";
export type RiskLevel = "low" | "medium" | "high" | "tier_d";
export type ProposerKind = "human" | "llm" | "agent";
export type ProposalAction =
  | "create"
  | "update"
  | "submit"
  | "approve"
  | "reject"
  | "apply"
  | "withdraw"
  | "comment";

export interface ProposalAuditEvent {
  timestamp: string;
  actor: string;
  action: ProposalAction;
  notes: string;
  metadata: Record<string, unknown>;
}

export interface Proposal {
  proposal_id: string;
  title: string;
  summary: string;
  motivation: string;
  risk_level: RiskLevel;
  target_paths: string[];
  diff: string;
  status: ProposalStatus;
  proposer_id: string;
  proposer_kind: ProposerKind;
  reviewer_id: string | null;
  review_notes: string;
  tags: string[];
  created_at: string;
  updated_at: string;
  decided_at: string | null;
  applied_at: string | null;
  audit_log: ProposalAuditEvent[];
  extras: Record<string, unknown>;
}

export interface ProposalListResponse {
  items: Proposal[];
  total: number;
}

export interface CreateProposalInput {
  title: string;
  summary?: string;
  motivation?: string;
  risk_level?: RiskLevel;
  target_paths?: string[];
  diff?: string;
  tags?: string[];
  proposer_kind?: ProposerKind;
  proposer_id?: string;
  extras?: Record<string, unknown>;
}

export interface UpdateProposalInput {
  title?: string;
  summary?: string;
  motivation?: string;
  risk_level?: RiskLevel;
  target_paths?: string[];
  diff?: string;
  tags?: string[];
  extras?: Record<string, unknown>;
  notes?: string;
}

// ---------------------------------------------------------------------------
// Planner (M8.2)
// ---------------------------------------------------------------------------

export type NodeKind =
  | "llm"
  | "tool"
  | "skill"
  | "memory.read"
  | "memory.write";
export type OnFailure = "abort" | "skip" | "continue";
export type NodeStatus =
  | "pending"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped";

export interface PlanNode {
  id: string;
  kind: NodeKind;
  name: string;
  args: Record<string, unknown>;
  depends_on: string[];
  description: string;
  expected_output: string;
  on_failure: OnFailure;
  retries: number;
}

export interface PlanDAG {
  plan_id: string;
  query: string;
  domain: string;
  nodes: PlanNode[];
  rationale: string;
  estimated_steps: number;
  created_at: string;
  llm_provider: string;
  extras: Record<string, unknown>;
}

export interface ValidatePlanResponse {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

export interface NodeOutcome {
  node_id: string;
  kind: NodeKind;
  name: string;
  status: NodeStatus;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number;
  output: Record<string, unknown>;
  error: string;
  attempts: number;
}

export interface SkillForCompile {
  name: string;
  description: string;
  domain: string;
  triggers: string[];
  invocation_modes: string[];
}

export interface ToolForCompile {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
}

export interface SkillsForCompileResponse {
  skills: SkillForCompile[];
  tools: ToolForCompile[];
}

export interface CompilePlanInput {
  query: string;
  domain?: string;
  hints?: string[];
  only_skills?: string[] | null;
  only_tools?: string[] | null;
  max_nodes?: number;
}

export interface ExecutePlanInput {
  plan: PlanDAG;
  params?: Record<string, unknown>;
  dry_run?: boolean;
  user_id?: string;
  session_id?: string;
}

export interface ExecutePlanResponse {
  task_id: string;
  status: string;
  workflow: string;
  plan_id: string;
  node_count: number;
}

// ---------------------------------------------------------------------------
// MCP admin (matches backend/api/routers/mcp.py)
// ---------------------------------------------------------------------------

export interface McpServerStatus {
  name: string;
  transport: string;
  connected: boolean;
  tools: string[];
  error: string | null;
}

export interface McpServersResponse {
  enabled: boolean;
  config_path: string;
  servers: McpServerStatus[];
}

export interface McpToolInfo {
  name: string;
  description: string;
  parameters: Record<string, unknown>;
  requires_network: boolean;
  requires_paid_api: boolean;
}

export interface McpToolsResponse {
  server: string;
  tools: McpToolInfo[];
}

// ---------------------------------------------------------------------------
// Runtime LLM provider (Settings → LLM panel)
// ---------------------------------------------------------------------------

export type LLMProviderName = "openai" | "anthropic" | "ollama" | "mock";

export interface LLMProviderResponse {
  provider: LLMProviderName;
  api_key_masked: string;
  api_key_set: boolean;
  base_url: string;
  default_model: string;
  timeout_s: number;
  source: "runtime" | "env";
  warns_arq_worker: boolean;
}

export interface LLMProviderInput {
  provider: LLMProviderName;
  /** Empty string ⇒ keep current. Non-empty ⇒ replace. */
  api_key: string;
  base_url?: string;
  default_model?: string;
  timeout_s?: number;
}

export interface LLMTestResponse {
  ok: boolean;
  provider: string;
  model: string;
  latency_ms: number;
  error: string | null;
}

export interface ProvidersResponse {
  items: LLMProviderName[];
}
