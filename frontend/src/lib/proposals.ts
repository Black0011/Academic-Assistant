/**
 * Gated Proposals API client (M8.1 + P8 Phase C2 bundle additions).
 *
 * Mirrors `backend/api/routers/proposals.py`:
 *
 *   GET    /api/proposals
 *   POST   /api/proposals                              (draft)
 *   GET    /api/proposals/{proposal_id}
 *   PATCH  /api/proposals/{proposal_id}
 *   POST   /api/proposals/{proposal_id}:submit
 *   POST   /api/proposals/{proposal_id}:approve
 *   POST   /api/proposals/{proposal_id}:reject
 *   POST   /api/proposals/{proposal_id}:apply          (status only)
 *   POST   /api/proposals/{proposal_id}:apply-to-bundle (P8 — writes file)
 *   POST   /api/proposals/{proposal_id}:withdraw
 *   DELETE /api/proposals/{proposal_id}
 *
 * `apply` does NOT modify files. Use `:apply-to-bundle` to actually
 * write a bundle proposal back to the manuscript file (admin only).
 */
import { api } from "@/lib/api";
import type {
  CreateProposalInput,
  Proposal,
  ProposalListResponse,
  ProposalStatus,
  UpdateProposalInput,
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

export interface ListProposalsParams {
  status?: ProposalStatus;
  proposer_id?: string;
  tag?: string;
  page?: number;
  page_size?: number;
}

async function transition(
  id: string,
  action: "submit" | "approve" | "reject" | "apply" | "withdraw",
  notes?: string,
): Promise<Proposal> {
  return api<Proposal>(`/api/proposals/${enc(id)}:${action}`, {
    method: "POST",
    json: notes ? { notes } : null,
  });
}

export const proposalsApi = {
  list(params: ListProposalsParams = {}): Promise<ProposalListResponse> {
    return api<ProposalListResponse>(
      `/api/proposals${qs(params as Record<string, unknown>)}`,
    );
  },

  get(proposalId: string): Promise<Proposal> {
    return api<Proposal>(`/api/proposals/${enc(proposalId)}`);
  },

  create(payload: CreateProposalInput): Promise<Proposal> {
    return api<Proposal>("/api/proposals", { method: "POST", json: payload });
  },

  patch(proposalId: string, payload: UpdateProposalInput): Promise<Proposal> {
    return api<Proposal>(`/api/proposals/${enc(proposalId)}`, {
      method: "PATCH",
      json: payload,
    });
  },

  submit(proposalId: string, notes?: string): Promise<Proposal> {
    return transition(proposalId, "submit", notes);
  },

  approve(proposalId: string, notes?: string): Promise<Proposal> {
    return transition(proposalId, "approve", notes);
  },

  reject(proposalId: string, notes?: string): Promise<Proposal> {
    return transition(proposalId, "reject", notes);
  },

  apply(proposalId: string, notes?: string): Promise<Proposal> {
    return transition(proposalId, "apply", notes);
  },

  /**
   * Re-apply a bundle proposal's recorded `bundle_after` content back
   * to the manuscript file (P8 Phase C2). Distinct from `apply()`,
   * which only stamps `status="applied"`. This call:
   *   - resolves manuscript via body.manuscript_id ?? proposal.extras.manuscript_id
   *   - 409 if the on-disk file changed since the proposal was drafted
   *     unless `force` is true
   *   - 403 if the manuscript is *linked* (external dir) and the
   *     proposal's risk_level is not "low"
   *   - on success: rewrites the file + patches `proposal.extras` with
   *     applied_to_bundle_at/by/size, but does NOT change status.
   */
  applyToBundle(
    proposalId: string,
    body: { manuscript_id?: string; force?: boolean; notes?: string } = {},
  ): Promise<Proposal> {
    return api<Proposal>(`/api/proposals/${enc(proposalId)}:apply-to-bundle`, {
      method: "POST",
      json: body,
    });
  },

  withdraw(proposalId: string, notes?: string): Promise<Proposal> {
    return transition(proposalId, "withdraw", notes);
  },

  delete(proposalId: string): Promise<void> {
    return api<void>(`/api/proposals/${enc(proposalId)}`, { method: "DELETE" });
  },

  /**
   * P9.4 — manually synthesise a heuristic proposal from the last N
   * successful task records. Replaces the pre-P9 behaviour where every
   * successful run auto-drafted a proposal.
   */
  synthesize(body: {
    workflow?: string;
    max_cases?: number;
    actor?: string;
  } = {}): Promise<Proposal> {
    return api<Proposal>("/api/proposals:synthesize", {
      method: "POST",
      json: body,
    });
  },
};
