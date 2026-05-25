/**
 * Knowledge Library API client (M7.3).
 *
 * Mirrors `backend/api/routers/documents.py`:
 *
 *   POST   /api/documents/ingest           multipart OR JSON
 *   GET    /api/documents
 *   GET    /api/documents/{doc_id}
 *   GET    /api/documents/{doc_id}/chunks
 *   POST   /api/documents/{doc_id}:reindex
 *   DELETE /api/documents/{doc_id}
 *   POST   /api/documents/search
 *
 * The ingest helper has two flavours so callers can drop a file *or*
 * paste raw markdown without thinking about content-type negotiation.
 */
import { api } from "@/lib/api";
import type {
  DocChunkHit,
  DocumentChunkPage,
  DocumentListResponse,
  DocumentSearchResponse,
  DocumentSourceKind,
  IngestDocumentJSONInput,
  IngestDocumentResponse,
  KnowledgeDocument,
  UpdateDocumentInput,
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

const enc = encodeURIComponent;

export interface ListDocumentsParams {
  user_id?: string;
  tag?: string;
  limit?: number;
  offset?: number;
}

export interface IngestDocumentFileArgs {
  file: File;
  title?: string;
  tags?: string[];
  source_kind?: DocumentSourceKind;
  source_uri?: string;
  target_tokens?: number;
  overlap_tokens?: number;
}

export const documentsApi = {
  list(params: ListDocumentsParams = {}): Promise<DocumentListResponse> {
    return api<DocumentListResponse>(
      `/api/documents${qs(params as Record<string, unknown>)}`,
    );
  },

  get(docId: string): Promise<KnowledgeDocument> {
    return api<KnowledgeDocument>(`/api/documents/${enc(docId)}`);
  },

  listChunks(
    docId: string,
    params: { offset?: number; limit?: number } = {},
  ): Promise<DocumentChunkPage> {
    return api<DocumentChunkPage>(
      `/api/documents/${enc(docId)}/chunks${qs(params as Record<string, unknown>)}`,
    );
  },

  ingestJSON(payload: IngestDocumentJSONInput): Promise<IngestDocumentResponse> {
    return api<IngestDocumentResponse>("/api/documents/ingest", {
      method: "POST",
      json: payload,
    });
  },

  ingestFile(args: IngestDocumentFileArgs): Promise<IngestDocumentResponse> {
    const fd = new FormData();
    fd.append("file", args.file);
    if (args.title !== undefined) fd.append("title", args.title);
    if (args.tags && args.tags.length > 0) fd.append("tags", args.tags.join(", "));
    if (args.source_kind) fd.append("source_kind", args.source_kind);
    if (args.source_uri) fd.append("source_uri", args.source_uri);
    if (args.target_tokens !== undefined)
      fd.append("target_tokens", String(args.target_tokens));
    if (args.overlap_tokens !== undefined)
      fd.append("overlap_tokens", String(args.overlap_tokens));
    return api<IngestDocumentResponse>("/api/documents/ingest", {
      method: "POST",
      body: fd,
    });
  },

  reindex(
    docId: string,
    params: { target_tokens?: number; overlap_tokens?: number } = {},
  ): Promise<IngestDocumentResponse> {
    return api<IngestDocumentResponse>(`/api/documents/${enc(docId)}:reindex`, {
      method: "POST",
      json: {
        target_tokens: params.target_tokens ?? 800,
        overlap_tokens: params.overlap_tokens ?? 100,
      },
    });
  },

  delete(docId: string): Promise<void> {
    return api<void>(`/api/documents/${enc(docId)}`, { method: "DELETE" });
  },

  /**
   * P14.B — partial metadata edit. Five fields at most. Does NOT
   * re-chunk or re-embed; for body changes go through ``reindex``
   * (which re-chunks + re-embeds the whole doc).
   *
   * Title changes propagate to chunk-level vector metadata server-side
   * (the chunks denormalise ``doc_title`` for cheap search rendering).
   */
  patchMetadata(docId: string, body: UpdateDocumentInput): Promise<KnowledgeDocument> {
    return api<KnowledgeDocument>(`/api/documents/${enc(docId)}`, {
      method: "PATCH",
      json: body,
    });
  },

  search(
    q: string,
    params: { top_k?: number; filters?: Record<string, unknown> } = {},
  ): Promise<DocumentSearchResponse> {
    return api<DocumentSearchResponse>("/api/documents/search", {
      method: "POST",
      json: {
        q,
        top_k: params.top_k ?? 5,
        filters: params.filters ?? {},
      },
    });
  },
};

export type { DocChunkHit };
