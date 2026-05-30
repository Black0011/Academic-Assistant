/**
 * Proposals page (M8.1) — gated framework-change proposals.
 *
 * Layout:
 *   - left:   list of proposals with status filter
 *   - right:  detail panel with the diff (read-only Monaco), audit log,
 *             and state-aware action buttons (submit / approve / reject /
 *             apply / withdraw / delete).
 *   - top-right: "New proposal" drawer (title + summary + risk + diff).
 *
 * The page never modifies files. ``apply`` only stamps status — that's
 * the whole M8.1 contract; the diff is the human/CI's input.
 */
import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ClipboardList,
  Clock3,
  FileSymlink,
  GitBranch,
  History,
  Package,
  Plus,
  RefreshCcw,
  ShieldCheck,
  Sparkles,
  Trash2,
  Undo2,
  X,
  XCircle,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { proposalsApi } from "@/lib/proposals";
import type {
  CreateProposalInput,
  Proposal,
  ProposalStatus,
  RiskLevel,
} from "@/types/api";

const STATUS_VARIANT: Record<
  ProposalStatus,
  "primary" | "neutral" | "success" | "warning" | "destructive"
> = {
  draft: "neutral",
  pending: "warning",
  approved: "primary",
  applied: "success",
  rejected: "destructive",
  withdrawn: "neutral",
};

const RISK_VARIANT: Record<
  RiskLevel,
  "neutral" | "warning" | "destructive"
> = {
  low: "neutral",
  medium: "warning",
  high: "destructive",
  tier_d: "destructive",
};

const STATUS_FILTERS: { value: ProposalStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "draft", label: "Draft" },
  { value: "pending", label: "Pending review" },
  { value: "approved", label: "Approved" },
  { value: "applied", label: "Applied" },
  { value: "rejected", label: "Rejected" },
  { value: "withdrawn", label: "Withdrawn" },
];

function isDarkMode(): boolean {
  if (typeof window === "undefined") return false;
  return document.documentElement.classList.contains("dark");
}

function relTime(ts: string | null | undefined): string {
  if (!ts) return "—";
  try {
    return formatDistanceToNow(new Date(ts), { addSuffix: true });
  } catch {
    return ts;
  }
}

export function ProposalsPage() {
  const { t } = useTranslation();
  const { proposalId } = useParams<{ proposalId?: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<ProposalStatus | "all">(
    "all",
  );
  const [showDrawer, setShowDrawer] = useState(false);

  const listKey = ["proposals", "list", statusFilter] as const;
  const list = useQuery({
    queryKey: listKey,
    queryFn: () =>
      proposalsApi.list(
        statusFilter === "all" ? {} : { status: statusFilter },
      ),
  });

  const items = list.data?.items ?? [];
  const selected = useMemo(
    () => items.find((p) => p.proposal_id === proposalId) ?? null,
    [items, proposalId],
  );

  const detail = useQuery({
    queryKey: ["proposals", "detail", proposalId ?? ""],
    queryFn: () => proposalsApi.get(proposalId as string),
    enabled: Boolean(proposalId),
  });

  const proposal = detail.data ?? selected;

  function refreshAll() {
    qc.invalidateQueries({ queryKey: ["proposals"] });
  }

  // P9.4 — manual synthesis of a heuristic proposal from the last N
  // successful task records. Replaces the pre-P9 "auto-draft per run"
  // behaviour that was interfering with normal usage.
  const synthesize = useMutation({
    mutationFn: () => proposalsApi.synthesize({ max_cases: 5 }),
    onSuccess: (p) => {
      toast.success(t("proposals.synthesize.success"));
      refreshAll();
      navigate(`/proposals/${p.proposal_id}`);
    },
    onError: (err) => {
      const msg = err instanceof Error ? err.message : String(err);
      toast.error(`${t("proposals.synthesize.failed")}: ${msg}`);
    },
  });

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("proposals.title")}
        description={t("proposals.description")}
        actions={
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => list.refetch()}
              disabled={list.isFetching}
            >
              <RefreshCcw
                className={cn("h-4 w-4", list.isFetching && "animate-spin")}
              />
              Refresh
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => synthesize.mutate()}
              disabled={synthesize.isPending}
              title={t("proposals.synthesize.hint")}
            >
              <Sparkles className={cn("h-4 w-4", synthesize.isPending && "animate-pulse")} />
              {t("proposals.synthesize.button")}
            </Button>
            <Button size="sm" onClick={() => setShowDrawer(true)}>
              <Plus className="h-4 w-4" /> New proposal
            </Button>
          </div>
        }
      />

      <div className="flex flex-1 gap-4 overflow-hidden">
        <div className="flex w-80 shrink-0 flex-col gap-3 overflow-hidden">
          <div className="flex flex-wrap gap-1">
            {STATUS_FILTERS.map((s) => (
              <button
                key={s.value}
                type="button"
                onClick={() => setStatusFilter(s.value)}
                className={cn(
                  "rounded-md border px-2 py-1 text-[11px] transition-colors",
                  statusFilter === s.value
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)]/10"
                    : "border-[var(--color-border)] hover:bg-[var(--color-accent)]/40",
                )}
              >
                {s.label}
              </button>
            ))}
          </div>
          <ProposalList
            items={items}
            isLoading={list.isLoading}
            selectedId={proposal?.proposal_id ?? null}
            onSelect={(p) => navigate(`/proposals/${p.proposal_id}`)}
          />
        </div>

        <div className="flex flex-1 flex-col overflow-hidden rounded-lg border bg-[var(--color-card)]">
          {!proposal ? (
            <EmptyState
              icon={ShieldCheck}
              title="No proposal selected"
              description="Pick a proposal from the left, or create a new one."
            />
          ) : (
            <ProposalDetail proposal={proposal} onChanged={refreshAll} />
          )}
        </div>
      </div>

      {showDrawer && (
        <CreateProposalDrawer
          onClose={() => setShowDrawer(false)}
          onCreated={(p) => {
            setShowDrawer(false);
            refreshAll();
            navigate(`/proposals/${p.proposal_id}`);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

interface ProposalListProps {
  items: Proposal[];
  isLoading: boolean;
  selectedId: string | null;
  onSelect: (p: Proposal) => void;
}

function ProposalList({
  items,
  isLoading,
  selectedId,
  onSelect,
}: ProposalListProps) {
  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-[var(--color-muted-foreground)]">
        Loading...
      </div>
    );
  }
  if (!items.length) {
    return (
      <EmptyState
        icon={ClipboardList}
        title="No proposals"
        description="Submit a draft to start the review flow."
      />
    );
  }
  return (
    <ul className="flex-1 space-y-1 overflow-y-auto rounded-md border bg-[var(--color-card)] p-1">
      {items.map((p) => (
        <li key={p.proposal_id}>
          <button
            type="button"
            onClick={() => onSelect(p)}
            className={cn(
              "block w-full rounded-md px-3 py-2 text-left transition-colors",
              p.proposal_id === selectedId
                ? "bg-[var(--color-accent)]"
                : "hover:bg-[var(--color-accent)]/60",
            )}
          >
            <div className="flex items-center gap-2">
              <span className="truncate text-sm font-medium">{p.title}</span>
              <Badge variant={STATUS_VARIANT[p.status]}>{p.status}</Badge>
            </div>
            <div className="mt-1 flex items-center gap-2 text-[11px] text-[var(--color-muted-foreground)]">
              <Badge variant={RISK_VARIANT[p.risk_level]}>
                {p.risk_level}
              </Badge>
              <span>· {p.proposer_kind}</span>
              <span>· {relTime(p.updated_at)}</span>
            </div>
            {p.summary && (
              <p className="mt-1 line-clamp-2 text-xs text-[var(--color-muted-foreground)]">
                {p.summary}
              </p>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

interface ProposalDetailProps {
  proposal: Proposal;
  onChanged: () => void;
}

function ProposalDetail({ proposal, onChanged }: ProposalDetailProps) {
  const { t } = useTranslation();
  const dark = isDarkMode();
  const transition = useMutation({
    mutationFn: async ({
      action,
      notes,
    }: {
      action: "submit" | "approve" | "reject" | "apply" | "withdraw";
      notes?: string;
    }) => {
      switch (action) {
        case "submit":
          return proposalsApi.submit(proposal.proposal_id, notes);
        case "approve":
          return proposalsApi.approve(proposal.proposal_id, notes);
        case "reject":
          return proposalsApi.reject(proposal.proposal_id, notes);
        case "apply":
          return proposalsApi.apply(proposal.proposal_id, notes);
        case "withdraw":
          return proposalsApi.withdraw(proposal.proposal_id, notes);
      }
    },
    onSuccess: (_data, vars) => {
      toast.success(`Proposal ${vars.action}ed`);
      onChanged();
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  const applyToBundle = useMutation({
    mutationFn: ({ force }: { force?: boolean }) =>
      proposalsApi.applyToBundle(proposal.proposal_id, { force }),
    onSuccess: () => {
      toast.success(t("proposals.actions.applyToBundle"));
      onChanged();
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  const remove = useMutation({
    mutationFn: () => proposalsApi.delete(proposal.proposal_id),
    onSuccess: () => {
      toast.success("Proposal deleted");
      onChanged();
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  const extras = (proposal.extras ?? {}) as Record<string, unknown>;
  const bundleTarget =
    typeof extras.bundle_target === "string" ? extras.bundle_target : null;
  const bundleManuscriptId =
    typeof extras.manuscript_id === "string" ? extras.manuscript_id : null;
  const bundleAppliedAt =
    typeof extras.applied_to_bundle_at === "string"
      ? extras.applied_to_bundle_at
      : null;
  const isBundleProposal = Boolean(bundleTarget);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-start justify-between gap-3 border-b p-4">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h2 className="truncate text-lg font-semibold">{proposal.title}</h2>
            <Badge variant={STATUS_VARIANT[proposal.status]}>
              {proposal.status}
            </Badge>
            <Badge variant={RISK_VARIANT[proposal.risk_level]}>
              risk · {proposal.risk_level}
            </Badge>
            {isBundleProposal && (
              <Badge variant="primary" className="gap-1">
                <Package className="h-3 w-3" />
                {t("proposals.bundle.badge")}
              </Badge>
            )}
          </div>
          <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
            #{proposal.proposal_id} · proposer {proposal.proposer_id || "anonymous"}{" "}
            ({proposal.proposer_kind}) · updated {relTime(proposal.updated_at)}
          </p>
          {proposal.summary && (
            <p className="mt-2 text-sm">{proposal.summary}</p>
          )}
        </div>

        <ActionButtons
          status={proposal.status}
          onAction={(action) => transition.mutate({ action })}
          onDelete={() => remove.mutate()}
          busy={transition.isPending || remove.isPending}
        />
      </div>

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-[2fr_1fr]">
        <div className="flex min-h-0 flex-col gap-3 overflow-hidden">
          {proposal.target_paths.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <GitBranch className="h-4 w-4" />
                  Target paths
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ul className="space-y-1 text-xs font-mono">
                  {proposal.target_paths.map((p) => (
                    <li key={p}>{p}</li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {proposal.motivation && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Motivation</CardTitle>
              </CardHeader>
              <CardContent>
                <pre className="whitespace-pre-wrap text-xs leading-relaxed">
                  {proposal.motivation}
                </pre>
              </CardContent>
            </Card>
          )}

          {isBundleProposal && (
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-sm">
                  <Package className="h-4 w-4" />
                  {t("proposals.bundle.badge")}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-xs">
                <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1">
                  <dt className="text-[var(--color-muted-foreground)]">
                    {t("proposals.bundle.targetPath")}
                  </dt>
                  <dd className="font-mono">{bundleTarget}</dd>
                  <dt className="text-[var(--color-muted-foreground)]">
                    {t("proposals.bundle.manuscriptId")}
                  </dt>
                  <dd className="font-mono">{bundleManuscriptId ?? "—"}</dd>
                  {bundleAppliedAt && (
                    <>
                      <dt className="text-[var(--color-muted-foreground)]">
                        <FileSymlink className="inline h-3 w-3" />
                      </dt>
                      <dd>
                        {t("proposals.bundle.appliedAt", {
                          when: relTime(bundleAppliedAt),
                        })}
                      </dd>
                    </>
                  )}
                </dl>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    onClick={() => applyToBundle.mutate({ force: false })}
                    disabled={applyToBundle.isPending}
                  >
                    <FileSymlink className="h-4 w-4" />
                    {t("proposals.actions.applyToBundle")}
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      if (
                        window.confirm(
                          t("proposals.actions.forceHint") + "\n\n— OK?",
                        )
                      ) {
                        applyToBundle.mutate({ force: true });
                      }
                    }}
                    disabled={applyToBundle.isPending}
                  >
                    {t("proposals.actions.force")}
                  </Button>
                  <span className="text-[11px] text-[var(--color-muted-foreground)]">
                    {t("proposals.actions.applyToBundleHint")}
                  </span>
                </div>
              </CardContent>
            </Card>
          )}

          <Card className="flex min-h-0 flex-1 flex-col">
            <CardHeader className="shrink-0">
              <CardTitle className="text-sm">Diff</CardTitle>
            </CardHeader>
            <CardContent className="min-h-0 flex-1">
              <Editor
                height="100%"
                defaultLanguage="diff"
                language="diff"
                value={proposal.diff || "(no diff supplied)"}
                theme={dark ? "vs-dark" : "vs"}
                options={{
                  readOnly: true,
                  minimap: { enabled: false },
                  fontSize: 12,
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                }}
              />
            </CardContent>
          </Card>
        </div>

        <Card className="min-h-0 overflow-hidden">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-sm">
              <History className="h-4 w-4" />
              Audit log
            </CardTitle>
          </CardHeader>
          <CardContent className="overflow-y-auto">
            <ol className="space-y-3">
              {proposal.audit_log.map((ev, idx) => (
                <li
                  key={idx}
                  className="flex gap-3 border-l-2 border-[var(--color-border)] pl-3"
                >
                  <Clock3 className="mt-0.5 h-3 w-3 shrink-0 text-[var(--color-muted-foreground)]" />
                  <div className="min-w-0 flex-1 text-xs">
                    <div className="flex items-center gap-2 font-medium">
                      <Badge variant="outline">{ev.action}</Badge>
                      <span className="text-[var(--color-muted-foreground)]">
                        by {ev.actor || "anonymous"} · {relTime(ev.timestamp)}
                      </span>
                    </div>
                    {ev.notes && (
                      <p className="mt-1 text-[var(--color-muted-foreground)]">
                        {ev.notes}
                      </p>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// State-aware action buttons
// ---------------------------------------------------------------------------

type ActionId = "submit" | "approve" | "reject" | "apply" | "withdraw";

interface ActionButtonsProps {
  status: ProposalStatus;
  onAction: (action: ActionId) => void;
  onDelete: () => void;
  busy: boolean;
}

function ActionButtons({ status, onAction, onDelete, busy }: ActionButtonsProps) {
  const buttons: { id: ActionId | "delete"; label: string; icon: typeof Check; variant?: "outline" | "primary" | "destructive" }[] = [];
  if (status === "draft") {
    buttons.push({ id: "submit", label: "Submit", icon: ClipboardList });
    buttons.push({ id: "withdraw", label: "Withdraw", icon: Undo2, variant: "outline" });
    buttons.push({ id: "delete", label: "Delete", icon: Trash2, variant: "destructive" });
  } else if (status === "pending") {
    buttons.push({ id: "approve", label: "Approve", icon: CheckCircle2 });
    buttons.push({ id: "reject", label: "Reject", icon: XCircle, variant: "destructive" });
    buttons.push({ id: "withdraw", label: "Withdraw", icon: Undo2, variant: "outline" });
  } else if (status === "approved") {
    buttons.push({ id: "apply", label: "Mark applied", icon: Check });
    buttons.push({ id: "withdraw", label: "Withdraw", icon: Undo2, variant: "outline" });
  } else if (status === "withdrawn") {
    buttons.push({ id: "delete", label: "Delete", icon: Trash2, variant: "destructive" });
  }

  if (!buttons.length) {
    return (
      <p className="text-xs text-[var(--color-muted-foreground)]">
        Terminal state — no actions left.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {buttons.map((b) => (
        <Button
          key={b.id}
          size="sm"
          variant={b.variant === "outline" ? "outline" : b.variant === "destructive" ? "destructive" : "primary"}
          disabled={busy}
          onClick={() => (b.id === "delete" ? onDelete() : onAction(b.id))}
        >
          <b.icon className="h-4 w-4" />
          {b.label}
        </Button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// New-proposal drawer
// ---------------------------------------------------------------------------

interface CreateProposalDrawerProps {
  onClose: () => void;
  onCreated: (p: Proposal) => void;
}

function CreateProposalDrawer({ onClose, onCreated }: CreateProposalDrawerProps) {
  const dark = isDarkMode();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [motivation, setMotivation] = useState("");
  const [risk, setRisk] = useState<RiskLevel>("low");
  const [paths, setPaths] = useState("");
  const [tags, setTags] = useState("");
  const [diff, setDiff] = useState("");
  const submit = useMutation({
    mutationFn: async () => {
      const payload: CreateProposalInput = {
        title: title.trim(),
        summary: summary.trim(),
        motivation: motivation.trim(),
        risk_level: risk,
        target_paths: paths
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        tags: tags
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        diff,
        proposer_kind: "human",
      };
      if (!payload.title) throw new Error("title is required");
      return proposalsApi.create(payload);
    },
    onSuccess: (p) => {
      toast.success("Proposal created");
      onCreated(p);
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="flex-1 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden
      />
      <aside className="flex w-[40rem] max-w-full flex-col gap-4 overflow-y-auto bg-[var(--color-card)] p-6 shadow-xl">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">New proposal</h2>
          <Button size="sm" variant="ghost" onClick={onClose}>
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="space-y-3">
          <div>
            <Label htmlFor="title">Title</Label>
            <Input
              id="title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Add memory exporter skill"
              autoFocus
            />
          </div>
          <div>
            <Label htmlFor="summary">Summary</Label>
            <Input
              id="summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="one-line description"
            />
          </div>
          <div>
            <Label htmlFor="motivation">Motivation</Label>
            <textarea
              id="motivation"
              value={motivation}
              onChange={(e) => setMotivation(e.target.value)}
              rows={3}
              className="block w-full rounded-md border bg-[var(--color-background)] px-3 py-2 text-sm"
              placeholder="why we want this change"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="risk">Risk level</Label>
              <select
                id="risk"
                className="block w-full rounded-md border bg-[var(--color-background)] px-3 py-2 text-sm"
                value={risk}
                onChange={(e) => setRisk(e.target.value as RiskLevel)}
              >
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
                <option value="tier_d">tier_d</option>
              </select>
            </div>
            <div>
              <Label htmlFor="tags">Tags</Label>
              <Input
                id="tags"
                value={tags}
                onChange={(e) => setTags(e.target.value)}
                placeholder="memory, skill"
              />
            </div>
          </div>
          <div>
            <Label htmlFor="paths">Target paths (one per line)</Label>
            <textarea
              id="paths"
              value={paths}
              onChange={(e) => setPaths(e.target.value)}
              rows={3}
              className="block w-full rounded-md border bg-[var(--color-background)] px-3 py-2 text-sm font-mono"
              placeholder="skills/aaf-memory-exporter/SKILL.md"
            />
          </div>
          <div>
            <Label>Diff</Label>
            <div className="h-64 rounded-md border">
              <Editor
                height="100%"
                language="diff"
                theme={dark ? "vs-dark" : "vs"}
                value={diff}
                onChange={(v) => setDiff(v ?? "")}
                options={{
                  minimap: { enabled: false },
                  fontSize: 12,
                  scrollBeyondLastLine: false,
                  wordWrap: "on",
                }}
              />
            </div>
            <p className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
              Paste a unified diff or describe the change. The framework
              never edits files automatically.
            </p>
          </div>
        </div>

        <div className="mt-auto flex justify-end gap-2 border-t pt-4">
          <Button variant="outline" onClick={onClose}>
            <X className="h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={() => submit.mutate()}
            disabled={!title.trim() || submit.isPending}
          >
            {submit.isPending ? <AlertTriangle className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            Create draft
          </Button>
        </div>
      </aside>
    </div>
  );
}
