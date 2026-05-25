/**
 * Manuscripts API client. Mirrors `/api/manuscripts` from
 * `backend/api/routers/manuscripts.py`. All calls go through `lib/api.ts`
 * so the consistency check (no inline fetch) stays green.
 */
import { api, apiUrl } from "@/lib/api";
import type {
  BundleConvertInput,
  BundleManifest,
  CommitVersionInput,
  CreateManuscriptInput,
  FileEnvelope,
  ImportFolderInput,
  ListManuscriptsParams,
  Manuscript,
  ManuscriptEnvelope,
  ManuscriptFile,
  ManuscriptKind,
  ManuscriptListResponse,
  ManuscriptStats,
  ManuscriptVersion,
  UpdateManuscriptInput,
  VersionListResponse,
  WriteFileInput,
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

export const manuscriptsApi = {
  list(params: ListManuscriptsParams = {}): Promise<ManuscriptListResponse> {
    return api<ManuscriptListResponse>(
      `/api/manuscripts${qs(params as Record<string, unknown>)}`,
    );
  },

  stats(): Promise<ManuscriptStats> {
    return api<ManuscriptStats>(`/api/manuscripts/stats`);
  },

  get(id: string): Promise<Manuscript> {
    return api<Manuscript>(`/api/manuscripts/${id}`);
  },

  create(body: CreateManuscriptInput): Promise<ManuscriptEnvelope> {
    return api<ManuscriptEnvelope>(`/api/manuscripts`, {
      method: "POST",
      json: body,
    });
  },

  update(id: string, body: UpdateManuscriptInput): Promise<Manuscript> {
    return api<Manuscript>(`/api/manuscripts/${id}`, {
      method: "PATCH",
      json: body,
    });
  },

  delete(id: string): Promise<void> {
    return api<void>(`/api/manuscripts/${id}`, { method: "DELETE" });
  },

  listVersions(id: string, limit = 50): Promise<VersionListResponse> {
    return api<VersionListResponse>(`/api/manuscripts/${id}/versions${qs({ limit })}`);
  },

  getVersion(id: string, version: number): Promise<ManuscriptVersion> {
    return api<ManuscriptVersion>(`/api/manuscripts/${id}/versions/${version}`);
  },

  commitVersion(id: string, body: CommitVersionInput): Promise<ManuscriptVersion> {
    return api<ManuscriptVersion>(`/api/manuscripts/${id}/versions`, {
      method: "POST",
      json: body,
    });
  },

  /** Builds an export URL we can drop into an `<a href>` for download. */
  exportUrl(id: string, version?: number): string {
    return `/api/manuscripts/${id}/export${qs({ version })}`;
  },

  upload(payload: {
    file: File;
    title?: string;
    kind?: ManuscriptKind;
    section?: string;
    topic?: string;
    tags?: string;
  }): Promise<ManuscriptEnvelope> {
    const fd = new FormData();
    fd.set("file", payload.file);
    if (payload.title) fd.set("title", payload.title);
    if (payload.kind) fd.set("kind", payload.kind);
    if (payload.section) fd.set("section", payload.section);
    if (payload.topic) fd.set("topic", payload.topic);
    if (payload.tags) fd.set("tags", payload.tags);
    return api<ManuscriptEnvelope>(`/api/manuscripts/upload`, {
      method: "POST",
      body: fd,
    });
  },

  // -------- P7 bundle endpoints ------------------------------------

  convertToBundle(id: string, body: BundleConvertInput = {}): Promise<Manuscript> {
    return api<Manuscript>(`/api/manuscripts/${id}/bundle`, {
      method: "POST",
      json: body,
    });
  },

  tree(id: string, opts: { include_hash?: boolean; include_hidden?: boolean; with_content?: boolean; max_content_size?: number } = {})
    : Promise<BundleManifest> {
    return api<BundleManifest>(
      `/api/manuscripts/${id}/tree${qs(opts as Record<string, unknown>)}`,
    );
  },

  readFile(id: string, path: string, opts: { text?: boolean } = {})
    : Promise<FileEnvelope> {
    return api<FileEnvelope>(
      `/api/manuscripts/${id}/files/${encodePath(path)}${qs(opts as Record<string, unknown>)}`,
    );
  },

  writeTextFile(id: string, path: string, body: WriteFileInput): Promise<ManuscriptFile> {
    return api<ManuscriptFile>(
      `/api/manuscripts/${id}/files/${encodePath(path)}`,
      { method: "PUT", json: body },
    );
  },

  uploadBundleFile(id: string, path: string, file: File): Promise<ManuscriptFile> {
    const fd = new FormData();
    fd.set("file", file);
    return api<ManuscriptFile>(
      `/api/manuscripts/${id}/files/${encodePath(path)}`,
      { method: "POST", body: fd },
    );
  },

  deleteFile(id: string, path: string): Promise<void> {
    return api<void>(`/api/manuscripts/${id}/files/${encodePath(path)}`, {
      method: "DELETE",
    });
  },

  importFolder(body: ImportFolderInput): Promise<Manuscript> {
    return api<Manuscript>(`/api/manuscripts/import-folder`, {
      method: "POST",
      json: body,
    });
  },

  importZip(payload: {
    file: File;
    title?: string;
    kind?: ManuscriptKind;
    overwrite?: boolean;
  }): Promise<Manuscript> {
    const fd = new FormData();
    fd.set("file", payload.file);
    if (payload.title) fd.set("title", payload.title);
    if (payload.kind) fd.set("kind", payload.kind);
    if (payload.overwrite !== undefined) fd.set("overwrite", String(payload.overwrite));
    return api<Manuscript>(`/api/manuscripts/import-zip`, {
      method: "POST",
      body: fd,
    });
  },

  /** URL for `<a href>` zip download (auto-detects overleaf/ subdir). */
  exportZipUrl(id: string, opts: { subdir?: string; include_hidden?: boolean } = {}): string {
    return apiUrl(`/api/manuscripts/${id}/export-zip${qs(opts as Record<string, unknown>)}`);
  },

  /** URL for downloading a single bundle file as raw bytes. */
  downloadFileUrl(id: string, path: string): string {
    return apiUrl(`/api/manuscripts/${id}/download/${encodePath(path)}`);
  },
};

/** Encode a relative bundle path while preserving `/` separators so the
 *  FastAPI `{path:path}` matcher can still see the directory structure. */
function encodePath(path: string): string {
  return path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}
