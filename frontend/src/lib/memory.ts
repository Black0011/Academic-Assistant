/**
 * Memory subsystem API client.
 *
 * Mirrors three routers under `/api/`:
 *   - /api/memory       (stats, snapshot, reflections, sessions, rollback)
 *   - /api/knowledge    (paper cards + synthesis notes)
 *   - /api/heuristics   (L3 strategies)
 *
 * Every call goes through `lib/api.ts` so the auth header is injected.
 */
import { api } from "@/lib/api";
import type {
  CreatePaperCardInput,
  Heuristic,
  HeuristicDomain,
  HeuristicListResponse,
  IngestPaperJSONInput,
  IngestPaperResponse,
  MemoryStats,
  PaperCard,
  PaperListResponse,
  Reflection,
  ReflectionListResponse,
  ReflectionType,
  RollbackResponse,
  StrategyBlock,
  SynthesisListResponse,
  UpdatePaperCardInput,
} from "@/types/api";

function qs(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null || v === "") continue;
    search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
}

// ---------------------------------------------------------------------------
// /api/memory
// ---------------------------------------------------------------------------

export const memoryApi = {
  stats(): Promise<MemoryStats> {
    return api<MemoryStats>("/api/memory/stats");
  },

  listReflections(params: {
    type?: ReflectionType;
    session_id?: string;
    user_id?: string;
    n?: number;
  } = {}): Promise<ReflectionListResponse> {
    return api<ReflectionListResponse>(`/api/memory/reflections${qs(params)}`);
  },

  createReflection(body: {
    type?: ReflectionType;
    content: string;
    tags?: string[];
    user_id?: string | null;
    session_id?: string | null;
    source_run_id?: string | null;
  }): Promise<Reflection> {
    return api<Reflection>("/api/memory/reflections", {
      method: "POST",
      json: body,
    });
  },

  /**
   * P14.A — partial edit. ``content``, ``type``, ``tags`` only;
   * provenance fields (user_id / session_id / source_run_id) are
   * intentionally not mutable through this path.
   */
  updateReflection(
    id: string,
    body: { type?: ReflectionType; content?: string; tags?: string[] },
  ): Promise<Reflection> {
    return api<Reflection>(`/api/memory/reflections/${encodeURIComponent(id)}`, {
      method: "PATCH",
      json: body,
    });
  },

  deleteReflection(id: string): Promise<void> {
    return api<void>(`/api/memory/reflections/${encodeURIComponent(id)}`, {
      method: "DELETE",
    });
  },

  /**
   * P14.A — bulk delete. The backend refuses an unbounded delete (400);
   * caller must supply at least one of ``session_id`` / ``source_run_id``.
   */
  bulkDeleteReflections(params: {
    session_id?: string;
    source_run_id?: string;
  }): Promise<{ deleted: number }> {
    return api<{ deleted: number }>(
      `/api/memory/reflections${qs(params as Record<string, unknown>)}`,
      { method: "DELETE" },
    );
  },

  rollbackRun(runId: string): Promise<RollbackResponse> {
    return api<RollbackResponse>(`/api/memory/rollback/${encodeURIComponent(runId)}`, {
      method: "POST",
    });
  },
};

// ---------------------------------------------------------------------------
// /api/knowledge — paper cards
// ---------------------------------------------------------------------------

export interface ListPapersParams {
  q?: string;
  tag?: string;
  user_id?: string;
  session_id?: string;
  source_run_id?: string;
  k?: number;
  limit?: number;
  offset?: number;
}

export const knowledgeApi = {
  listPapers(params: ListPapersParams = {}): Promise<PaperListResponse> {
    return api<PaperListResponse>(`/api/knowledge/papers${qs(params as Record<string, unknown>)}`);
  },

  getPaper(paperId: string): Promise<PaperCard> {
    return api<PaperCard>(`/api/knowledge/papers/${encodeURIComponent(paperId)}`);
  },

  /**
   * Manual paper-card creation (P13.C). Distinct from ``ingestPaperJSON``:
   * ingest also writes vector/episodic memory and (optionally) triggers
   * evolver. This endpoint just creates the card itself — used by the
   * MemoryPage "New card" drawer where the user knows exactly the
   * metadata they want.
   */
  createPaper(input: CreatePaperCardInput): Promise<PaperCard> {
    return api<PaperCard>("/api/knowledge/papers", {
      method: "POST",
      json: input,
    });
  },

  /**
   * Partial card update (P13.C). Server merges only the fields you send;
   * an empty body is a no-op. Clearing a field is "send empty string"
   * (the PATCH endpoint filters out ``null`` via ``exclude_none=True``).
   */
  updatePaper(paperId: string, input: UpdatePaperCardInput): Promise<PaperCard> {
    return api<PaperCard>(`/api/knowledge/papers/${encodeURIComponent(paperId)}`, {
      method: "PATCH",
      json: input,
    });
  },

  deletePaper(paperId: string): Promise<void> {
    return api<void>(`/api/knowledge/papers/${encodeURIComponent(paperId)}`, {
      method: "DELETE",
    });
  },

  listSyntheses(): Promise<SynthesisListResponse> {
    return api<SynthesisListResponse>("/api/knowledge/syntheses");
  },

  /**
   * Ingest a paper (PDF / markdown / txt) via multipart upload.
   * The backend extracts metadata + text, upserts a `PaperCard`, and
   * (when enabled) triggers `PaperMemoryEvolver`.
   */
  ingestPaperFile(args: {
    file: File;
    title?: string;
    authors?: string[];
    year?: number | null;
    venue?: string;
    tags?: string[];
    source_kind?: "user_upload" | "arxiv" | "doi" | "manual";
    source_uri?: string;
    trigger_evolution?: boolean;
    llm_extract?: boolean;
  }): Promise<IngestPaperResponse> {
    const fd = new FormData();
    fd.append("file", args.file);
    if (args.title !== undefined) fd.append("title", args.title);
    if (args.authors && args.authors.length > 0) fd.append("authors", args.authors.join(", "));
    if (args.year !== undefined && args.year !== null) fd.append("year", String(args.year));
    if (args.venue) fd.append("venue", args.venue);
    if (args.tags && args.tags.length > 0) fd.append("tags", args.tags.join(", "));
    if (args.source_kind) fd.append("source_kind", args.source_kind);
    if (args.source_uri) fd.append("source_uri", args.source_uri);
    if (args.trigger_evolution !== undefined) {
      fd.append("trigger_evolution", args.trigger_evolution ? "true" : "false");
    }
    if (args.llm_extract !== undefined) {
      fd.append("llm_extract", args.llm_extract ? "true" : "false");
    }
    return api<IngestPaperResponse>("/api/knowledge/papers/ingest", {
      method: "POST",
      body: fd,
    });
  },

  /** JSON-mode ingest — caller has already extracted (or hand-supplied) metadata. */
  ingestPaperJSON(input: IngestPaperJSONInput): Promise<IngestPaperResponse> {
    return api<IngestPaperResponse>("/api/knowledge/papers/ingest", {
      method: "POST",
      json: input,
    });
  },
};

// ---------------------------------------------------------------------------
// /api/heuristics
// ---------------------------------------------------------------------------

export interface ListHeuristicsParams {
  domain?: HeuristicDomain;
  include_frozen?: boolean;
  limit?: number;
  offset?: number;
}

export const heuristicsApi = {
  list(params: ListHeuristicsParams = {}): Promise<HeuristicListResponse> {
    return api<HeuristicListResponse>(
      `/api/heuristics${qs(params as Record<string, unknown>)}`,
    );
  },

  match(query: string, opts: { domain?: HeuristicDomain; top_k?: number } = {}): Promise<HeuristicListResponse> {
    return api<HeuristicListResponse>(
      `/api/heuristics/match${qs({ query, domain: opts.domain, top_k: opts.top_k })}`,
    );
  },

  freeze(id: string): Promise<Heuristic> {
    return api<Heuristic>(`/api/heuristics/${encodeURIComponent(id)}/freeze`, {
      method: "POST",
    });
  },

  unfreeze(id: string): Promise<Heuristic> {
    return api<Heuristic>(`/api/heuristics/${encodeURIComponent(id)}/unfreeze`, {
      method: "POST",
    });
  },

  bump(id: string, verdict: "pass" | "fail"): Promise<Heuristic> {
    return api<Heuristic>(`/api/heuristics/${encodeURIComponent(id)}/bump`, {
      method: "POST",
      json: { verdict },
    });
  },

  delete(id: string): Promise<void> {
    return api<void>(`/api/heuristics/${encodeURIComponent(id)}`, { method: "DELETE" });
  },

  update(id: string, body: Partial<{
    name: string;
    description: string;
    domain: HeuristicDomain;
    trigger_pattern: string;
    strategy: StrategyBlock;
  }>): Promise<Heuristic> {
    return api<Heuristic>(`/api/heuristics/${encodeURIComponent(id)}`, {
      method: "PATCH",
      json: body,
    });
  },
};
