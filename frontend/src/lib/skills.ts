/**
 * Skills sub-system API client (M7.2).
 *
 * Mirrors `backend/api/routers/skills.py`. Read endpoints are open;
 * write endpoints require admin role unless the deployment runs in
 * `auth_disabled` mode (the default for local dev). The corresponding
 * SDK lives in `sdk/python/aaf/skills.py`.
 *
 * Progressive disclosure on purpose:
 *
 *   - `list()`        →  frontmatter + invocation stats per skill
 *   - `get(name)`     →  + SKILL.md body and script descriptors (no source)
 *   - `getScript(...)` →  full script source on demand (lazy)
 */
import { api } from "@/lib/api";
import type {
  SkillDetail,
  SkillDryRunResponse,
  SkillEdgesUpdateInput,
  SkillEdgesUpdateResponse,
  SkillGraphResponse,
  SkillInstallInput,
  SkillInvocationListResponse,
  SkillListResponse,
  SkillReloadResponse,
  SkillScriptSource,
  SkillSummary,
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

export interface ListSkillsParams {
  include_disabled?: boolean;
  domain?: string;
}

export const skillsApi = {
  list(params: ListSkillsParams = {}): Promise<SkillListResponse> {
    const merged = {
      include_disabled: params.include_disabled ?? true,
      domain: params.domain,
    };
    return api<SkillListResponse>(`/api/skills${qs(merged as Record<string, unknown>)}`);
  },

  /** P13.B graph view — nodes + compatibility edges. */
  getGraph(): Promise<SkillGraphResponse> {
    return api<SkillGraphResponse>("/api/skills/graph");
  },

  get(name: string): Promise<SkillDetail> {
    return api<SkillDetail>(`/api/skills/${enc(name)}`);
  },

  getScript(name: string, script: string): Promise<SkillScriptSource> {
    return api<SkillScriptSource>(`/api/skills/${enc(name)}/scripts/${enc(script)}`);
  },

  invocations(
    name: string,
    params: { limit?: number; window_days?: number } = {},
  ): Promise<SkillInvocationListResponse> {
    return api<SkillInvocationListResponse>(
      `/api/skills/${enc(name)}/invocations${qs(params as Record<string, unknown>)}`,
    );
  },

  install(payload: SkillInstallInput): Promise<SkillDetail> {
    return api<SkillDetail>("/api/skills", {
      method: "POST",
      json: payload,
    });
  },

  update(name: string, payload: SkillInstallInput): Promise<SkillDetail> {
    return api<SkillDetail>(`/api/skills/${enc(name)}`, {
      method: "PATCH",
      json: payload,
    });
  },

  delete(name: string): Promise<void> {
    return api<void>(`/api/skills/${enc(name)}`, { method: "DELETE" });
  },

  disable(name: string): Promise<SkillSummary> {
    return api<SkillSummary>(`/api/skills/${enc(name)}:disable`, { method: "POST" });
  },

  enable(name: string): Promise<SkillSummary> {
    return api<SkillSummary>(`/api/skills/${enc(name)}:enable`, { method: "POST" });
  },

  reload(name: string): Promise<SkillReloadResponse> {
    return api<SkillReloadResponse>(`/api/skills/${enc(name)}:reload`, { method: "POST" });
  },

  dryRun(
    name: string,
    script: string,
    args: Record<string, unknown> = {},
  ): Promise<SkillDryRunResponse> {
    return api<SkillDryRunResponse>(
      `/api/skills/${enc(name)}/scripts/${enc(script)}:dry_run`,
      {
        method: "POST",
        json: args,
      },
    );
  },

  /**
   * P14.C — frontmatter-only edge edit. Used by the graph view for
   * drag-to-connect and right-click-delete. Only mutates the source
   * skill's compatibility.{kind} (or legacy ``downstream_skills`` for
   * removes); body and scripts are untouched. See backend route
   * docstring for the full contract.
   */
  updateEdges(
    name: string,
    payload: SkillEdgesUpdateInput,
  ): Promise<SkillEdgesUpdateResponse> {
    return api<SkillEdgesUpdateResponse>(`/api/skills/${enc(name)}:edges`, {
      method: "POST",
      json: payload,
    });
  },
};
