import { DiffEditor } from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  ArrowRight,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Play,
  Plus,
  RotateCcw,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusPill } from "@/components/common/StatusPill";
import { TaskError } from "@/components/common/TaskError";
import { EventTimeline } from "@/components/research/EventTimeline";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Separator } from "@/components/ui/Separator";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTaskStream } from "@/hooks/useTaskStream";
import { ApiError, api } from "@/lib/api";
import { manuscriptsApi } from "@/lib/manuscripts";
import { useUiStore } from "@/stores/uiStore";
import type {
  CreateTaskInput,
  CreateTaskResponse,
  Manuscript,
  ManuscriptVersion,
} from "@/types/api";

const COMMENT_CATEGORIES = [
  "general",
  "clarity",
  "citation",
  "scope",
  "grammar",
  "novelty",
] as const;
type CommentCategory = (typeof COMMENT_CATEGORIES)[number];

interface DraftComment {
  id: string;
  category: CommentCategory;
  text: string;
}

function nextCommentId(existing: DraftComment[]): string {
  const used = new Set(existing.map((c) => c.id));
  let n = existing.length + 1;
  while (used.has(`c${n}`)) n += 1;
  return `c${n}`;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function RevisionPage() {
  const [params, setParams] = useSearchParams();
  const manuscriptId = params.get("manuscript") ?? "";
  const fromVersion = params.get("from");
  const initialBundleTarget = params.get("bundle_target") ?? null;

  if (!manuscriptId) {
    return <ManuscriptPicker onPick={(id) => setParams({ manuscript: id })} />;
  }
  return (
    <RevisionStudio
      key={`${manuscriptId}::${initialBundleTarget ?? ""}`}
      manuscriptId={manuscriptId}
      initialBaseVersion={fromVersion ? Number(fromVersion) : null}
      initialBundleTarget={initialBundleTarget}
      onChangeManuscript={(id) => setParams(id ? { manuscript: id } : {})}
    />
  );
}

// ---------------------------------------------------------------------------
// Picker
// ---------------------------------------------------------------------------

function ManuscriptPicker({ onPick }: { onPick: (id: string) => void }) {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("revision.title")}
        description={t("revision.description")}
      />
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">Pick a manuscript</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {list.isLoading ? (
            <div className="p-4">
              <Skeleton className="h-24 w-full" />
            </div>
          ) : !list.data || list.data.items.length === 0 ? (
            <div className="p-6">
              <EmptyState
                title="No manuscripts yet"
                description="Upload one from the Manuscripts page or run a Write workflow first."
                action={
                  <Link to="/papers" className="text-sm text-[var(--color-primary)] hover:underline">
                    Go to Manuscripts →
                  </Link>
                }
              />
            </div>
          ) : (
            <ul className="divide-y">
              {list.data.items.map((m) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => onPick(m.id)}
                    className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-[var(--color-muted)]"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {m.title || "Untitled"}
                        </span>
                        <Badge variant="outline">{m.kind}</Badge>
                        <Badge variant="neutral">{m.status}</Badge>
                      </div>
                      <div className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                        v{m.current_version} · updated{" "}
                        {format(new Date(m.updated_at), "yyyy-MM-dd HH:mm")}
                      </div>
                    </div>
                    <ArrowRight className="h-4 w-4 text-[var(--color-muted-foreground)]" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Studio
// ---------------------------------------------------------------------------

interface StudioProps {
  manuscriptId: string;
  initialBaseVersion: number | null;
  initialBundleTarget?: string | null;
  onChangeManuscript: (id: string | null) => void;
}

function RevisionStudio(props: StudioProps) {
  // Dispatch on layout BEFORE either studio is mounted, so each studio
  // can call its own hook set unconditionally (Rules of Hooks).
  const meta = useQuery({
    queryKey: ["manuscript", props.manuscriptId],
    queryFn: () => manuscriptsApi.get(props.manuscriptId),
  });

  if (meta.isLoading || !meta.data) {
    return (
      <div className="space-y-3 p-4">
        <Skeleton className="h-6 w-64" />
        <Skeleton className="h-32 w-full" />
      </div>
    );
  }

  if (meta.data.layout === "bundle") {
    return <BundleRevisionStudio {...props} meta={meta.data} />;
  }
  return <SingleRevisionStudio {...props} meta={meta.data} />;
}

interface InnerStudioProps extends StudioProps {
  meta: Manuscript;
}

function SingleRevisionStudio({
  manuscriptId,
  initialBaseVersion,
  onChangeManuscript,
  meta: metaData,
}: InnerStudioProps) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const themeMode = useUiStore((s) => s.theme);
  const isDark =
    themeMode === "dark" ||
    (themeMode === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches);

  const meta = useQuery({
    queryKey: ["manuscript", manuscriptId],
    queryFn: () => manuscriptsApi.get(manuscriptId),
    initialData: metaData,
  });
  const versions = useQuery({
    queryKey: ["manuscript-versions", manuscriptId],
    queryFn: () => manuscriptsApi.listVersions(manuscriptId, 100),
  });

  // ---- form state -----------------------------------------------------
  const [baseVersion, setBaseVersion] = useState<number | null>(initialBaseVersion);
  const [query, setQuery] = useState("");
  const [section, setSection] = useState("");
  const [goals, setGoals] = useState("");
  const [budget, setBudget] = useState("");
  const [comments, setComments] = useState<DraftComment[]>([
    { id: "c1", category: "general", text: "" },
  ]);

  // Default base version once manuscript meta arrives.
  useEffect(() => {
    if (baseVersion === null && meta.data && meta.data.current_version > 0) {
      setBaseVersion(meta.data.current_version);
    }
  }, [meta.data, baseVersion]);

  const baseVersionQ = useQuery({
    queryKey: ["manuscript-version", manuscriptId, baseVersion],
    queryFn: () => manuscriptsApi.getVersion(manuscriptId, baseVersion!),
    enabled: Boolean(baseVersion),
  });

  // ---- run state ------------------------------------------------------
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [diffRightVersion, setDiffRightVersion] = useState<number | null>(null);

  const taskQ = useQuery({
    queryKey: ["task", activeTaskId],
    queryFn: () => api(`/api/tasks/${activeTaskId}`),
    enabled: Boolean(activeTaskId),
    refetchInterval: (q) => {
      const data = q.state.data as { status?: string } | undefined;
      if (!data) return 1500;
      return data.status === "queued" || data.status === "running" ? 1500 : false;
    },
  });

  const stream = useTaskStream(activeTaskId);

  // After completion, refresh versions and snap the diff to the newest.
  useEffect(() => {
    if (!activeTaskId) return;
    if (stream.status === "ok" || stream.status === "error" || stream.status === "cancelled") {
      void qc.invalidateQueries({ queryKey: ["manuscript", manuscriptId] });
      void qc.invalidateQueries({ queryKey: ["manuscript-versions", manuscriptId] });
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
    }
  }, [stream.status, activeTaskId, manuscriptId, qc]);

  useEffect(() => {
    // When versions list refreshes after a successful run, jump the right
    // pane to the brand-new top version. Only auto-snap once per run.
    if (stream.status !== "ok" || !versions.data) return;
    const newest = versions.data.items[0]?.version ?? null;
    if (newest && newest !== baseVersion) {
      setDiffRightVersion(newest);
    }
  }, [stream.status, versions.data, baseVersion]);

  const rightVersion = diffRightVersion ?? baseVersion;
  const rightVersionQ = useQuery({
    queryKey: ["manuscript-version", manuscriptId, rightVersion],
    queryFn: () => manuscriptsApi.getVersion(manuscriptId, rightVersion!),
    enabled: Boolean(rightVersion),
  });

  // ---- mutations ------------------------------------------------------
  const runMut = useMutation({
    mutationFn: async () => {
      if (!baseVersionQ.data) throw new Error("base version not loaded yet");
      const cleanComments = comments
        .map((c) => ({
          id: c.id.trim() || undefined,
          category: c.category,
          text: c.text.trim(),
        }))
        .filter((c) => c.text);
      const goalsList = goals
        .split("\n")
        .map((g) => g.trim())
        .filter(Boolean);

      const body: CreateTaskInput = {
        workflow: "revision",
        query: query.trim() || "Apply reviewer comments.",
        input: {
          manuscript_id: manuscriptId,
          text: baseVersionQ.data.content,
          comments: cleanComments,
          goals: goalsList,
          ...(section.trim() ? { section: section.trim() } : {}),
        },
      };
      if (budget.trim()) {
        const v = Number(budget);
        if (Number.isFinite(v) && v > 0) body.budget_usd = v;
      }
      return api<CreateTaskResponse>("/api/tasks", { method: "POST", json: body });
    },
    onSuccess: (data) => {
      setActiveTaskId(data.task_id);
      setDiffRightVersion(null);
      toast.success("Revision enqueued", { description: data.task_id.slice(0, 12) });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      toast.error("Failed to enqueue revision", { description: msg });
    },
  });

  function resetRun() {
    setActiveTaskId(null);
    setDiffRightVersion(null);
  }

  // ---- render ---------------------------------------------------------
  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-0 flex-col">
      <RevisionHeader
        meta={meta.data}
        loading={meta.isLoading}
        onSwitch={() => onChangeManuscript(null)}
        onOpen={() => navigate(`/papers/${manuscriptId}`)}
      />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[20rem_1fr]">
        {/* Left: form */}
        <Card className="flex min-h-0 flex-col overflow-y-auto">
          <CardHeader className="p-3">
            <CardTitle className="text-sm">Revision plan</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 p-4 pt-0">
            <div className="space-y-1.5">
              <Label htmlFor="rs-base">Base version</Label>
              <select
                id="rs-base"
                className="h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
                value={baseVersion ?? ""}
                onChange={(e) =>
                  setBaseVersion(e.target.value ? Number(e.target.value) : null)
                }
                disabled={!versions.data || versions.data.items.length === 0}
              >
                {versions.data?.items.map((v) => (
                  <option key={v.version} value={v.version}>
                    v{v.version} · {v.origin} · {format(new Date(v.created_at), "MM-dd HH:mm")}
                  </option>
                ))}
                {(!versions.data || versions.data.items.length === 0) && (
                  <option value="">no versions yet</option>
                )}
              </select>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-query">Instruction</Label>
              <Input
                id="rs-query"
                placeholder="e.g. Address reviewer 2's clarity concerns"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-section">Section (optional)</Label>
              <Input
                id="rs-section"
                placeholder="e.g. Methods, Section 3.2"
                value={section}
                onChange={(e) => setSection(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Reviewer comments</Label>
              <ul className="space-y-2">
                {comments.map((c, i) => (
                  <li
                    key={c.id}
                    className="space-y-1 rounded-md border border-[var(--color-border)] p-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
                        {c.id}
                      </span>
                      <select
                        aria-label={`category for ${c.id}`}
                        value={c.category}
                        onChange={(e) => {
                          const next = [...comments];
                          next[i] = {
                            ...c,
                            category: e.target.value as CommentCategory,
                          };
                          setComments(next);
                        }}
                        className="h-6 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-1 text-[10px]"
                      >
                        {COMMENT_CATEGORIES.map((cat) => (
                          <option key={cat} value={cat}>
                            {cat}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        aria-label={`remove ${c.id}`}
                        onClick={() =>
                          setComments(
                            comments.length > 1 ? comments.filter((_, j) => j !== i) : comments,
                          )
                        }
                        className="ml-auto text-[var(--color-muted-foreground)] hover:text-[var(--color-destructive)]"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                    <Textarea
                      value={c.text}
                      onChange={(e) => {
                        const next = [...comments];
                        next[i] = { ...c, text: e.target.value };
                        setComments(next);
                      }}
                      placeholder="Reviewer 2: 'Equation 3 is unclear; cite [smith2024] for the saddle-point claim.'"
                      className="min-h-16 text-xs"
                    />
                  </li>
                ))}
              </ul>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setComments((s) => [
                    ...s,
                    { id: nextCommentId(s), category: "general", text: "" },
                  ])
                }
              >
                <Plus className="h-3.5 w-3.5" /> Add comment
              </Button>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-goals">Global goals (one per line, optional)</Label>
              <Textarea
                id="rs-goals"
                placeholder={"tighten prose\nadd citations to recent 2023 work"}
                value={goals}
                onChange={(e) => setGoals(e.target.value)}
                className="min-h-20 text-xs"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-budget">Budget (USD, optional)</Label>
              <Input
                id="rs-budget"
                type="number"
                min="0"
                step="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </div>

            <Separator />

            <div className="flex gap-2">
              <Button
                type="button"
                className="flex-1"
                onClick={() => runMut.mutate()}
                disabled={runMut.isPending || !baseVersionQ.data || stream.status === "running"}
              >
                {runMut.isPending || stream.status === "running" ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Running…
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" /> Run revision
                  </>
                )}
              </Button>
              {activeTaskId && (
                <Button type="button" variant="outline" onClick={resetRun}>
                  <RotateCcw className="h-4 w-4" />
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Right: diff + stream */}
        <div className="flex min-h-0 flex-col gap-4">
          <DiffPane
            manuscriptId={manuscriptId}
            isDark={isDark}
            baseVersion={baseVersion}
            baseContent={baseVersionQ.data?.content ?? ""}
            rightVersion={rightVersion}
            rightContent={rightVersionQ.data?.content ?? ""}
            versions={versions.data?.items ?? []}
            onPickRight={(v) => setDiffRightVersion(v)}
            currentVersion={meta.data?.current_version ?? null}
            navigate={navigate}
          />

          {activeTaskId && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-2 p-3">
                <div className="min-w-0">
                  <CardTitle className="font-mono text-xs">{activeTaskId}</CardTitle>
                  <p className="text-[10px] text-[var(--color-muted-foreground)]">
                    {(taskQ.data as { workflow?: string } | undefined)?.workflow ?? "revision"}
                  </p>
                </div>
                <StatusPill status={stream.status} />
              </CardHeader>
              {stream.error && (
                <CardContent className="pt-0">
                  <TaskError error={stream.error} />
                </CardContent>
              )}
              <CardContent className="max-h-72 overflow-y-auto p-3 pt-0">
                <EventTimeline events={stream.events} />
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function RevisionHeader({
  meta,
  loading,
  onSwitch,
  onOpen,
}: {
  meta: Manuscript | undefined;
  loading: boolean;
  onSwitch: () => void;
  onOpen: () => void;
}) {
  const title = useMemo(() => meta?.title || "Untitled manuscript", [meta]);
  return (
    <div className="mb-3 flex flex-wrap items-center gap-3">
      <h1 className="truncate text-base font-semibold tracking-tight">
        Revision Studio · {loading ? <Skeleton className="inline-block h-4 w-40" /> : title}
      </h1>
      {meta && (
        <>
          <Badge variant="outline">{meta.kind}</Badge>
          <Badge variant="neutral">{meta.status}</Badge>
          <span className="text-xs text-[var(--color-muted-foreground)]">
            v{meta.current_version}
          </span>
        </>
      )}
      <div className="ml-auto flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onSwitch}>
          Switch manuscript
        </Button>
        <Button variant="outline" size="sm" onClick={onOpen}>
          <ExternalLink className="h-3.5 w-3.5" /> Open in Writer
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Diff pane
// ---------------------------------------------------------------------------

interface DiffPaneProps {
  manuscriptId: string;
  isDark: boolean;
  baseVersion: number | null;
  baseContent: string;
  rightVersion: number | null;
  rightContent: string;
  versions: ManuscriptVersion[];
  onPickRight: (version: number) => void;
  currentVersion: number | null;
  navigate: (path: string) => void;
}

function DiffPane({
  manuscriptId,
  isDark,
  baseVersion,
  baseContent,
  rightVersion,
  rightContent,
  versions,
  onPickRight,
  currentVersion,
  navigate,
}: DiffPaneProps) {
  const isLatestOnRight =
    currentVersion !== null && rightVersion === currentVersion && rightVersion !== baseVersion;

  return (
    <Card className="flex min-h-0 flex-1 flex-col">
      <CardHeader className="flex flex-row items-center justify-between gap-2 p-3">
        <CardTitle className="text-sm">
          Diff: <span className="font-mono">v{baseVersion ?? "?"}</span>
          <ArrowRight className="mx-1 inline h-3 w-3" />
          <span className="font-mono">v{rightVersion ?? "?"}</span>
          {isLatestOnRight && (
            <span className="ml-2 inline-flex items-center gap-1 text-xs font-normal text-[var(--color-success)]">
              <CheckCircle2 className="h-3 w-3" /> revision committed
            </span>
          )}
        </CardTitle>
        <div className="flex items-center gap-2">
          <Label htmlFor="rs-right" className="text-xs">
            Compare to
          </Label>
          <select
            id="rs-right"
            className="h-7 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-1 text-xs"
            value={rightVersion ?? ""}
            onChange={(e) => onPickRight(Number(e.target.value))}
            disabled={versions.length === 0}
          >
            {versions.map((v) => (
              <option key={v.version} value={v.version}>
                v{v.version} · {v.origin}
              </option>
            ))}
          </select>
          {isLatestOnRight && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => navigate(`/papers/${manuscriptId}`)}
            >
              Open in Writer
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 p-0">
        {baseVersion === null || rightVersion === null ? (
          <div className="p-6">
            <EmptyState
              title="Pick a base version on the left"
              description="The Diff view shows your selected version against the latest committed one."
            />
          </div>
        ) : (
          <DiffEditor
            height="100%"
            language="markdown"
            original={baseContent}
            modified={rightContent}
            theme={isDark ? "vs-dark" : "vs"}
            options={{
              readOnly: true,
              renderSideBySide: true,
              originalEditable: false,
              fontSize: 13,
              wordWrap: "on",
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              padding: { top: 12, bottom: 12 },
            }}
          />
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// P8 Phase D2 — Bundle revision studio
//
// Different mental model from the single-doc one above:
//
//   * No version chain. The revision *overwrites* the bundle file in
//     place; a backup lives in the manuscript page download flow.
//   * Target file is a *path* inside the bundle (e.g.
//     "overleaf/sections/intro.tex"), not a version number.
//   * Diff: before = file content snapshotted right before "Run", after
//     = file content read again once the task finishes. The agent
//     never returns a per-file diff to us; it returns the whole new
//     text and the runner writes it.
//
// Reuses the smaller bits (RevisionHeader, EventTimeline, comment
// editor) but doesn't try to share the version-chain machinery — that
// concept just doesn't apply here.
// ---------------------------------------------------------------------------

function BundleRevisionStudio({
  manuscriptId,
  meta: metaData,
  onChangeManuscript,
  initialBundleTarget,
}: InnerStudioProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const themeMode = useUiStore((s) => s.theme);
  const isDark =
    themeMode === "dark" ||
    (themeMode === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches);

  const meta = useQuery({
    queryKey: ["manuscript", manuscriptId],
    queryFn: () => manuscriptsApi.get(manuscriptId),
    initialData: metaData,
  });

  const tree = useQuery({
    queryKey: ["manuscript-tree", manuscriptId],
    queryFn: () => manuscriptsApi.tree(manuscriptId, { include_hash: false }),
  });

  // Restrict the picker to text-revisable files; binaries / images
  // would only confuse the workflow and are pre-filtered server-side
  // by the workflow's own validation.
  const targetCandidates = useMemo(() => {
    const items = tree.data?.files ?? [];
    return items.filter(
      (f) => f.is_text && /\.(tex|md|txt|rst)$/i.test(f.path),
    );
  }, [tree.data]);

  const [bundleTarget, setBundleTarget] = useState<string>(initialBundleTarget ?? "");
  useEffect(() => {
    if (!bundleTarget && targetCandidates.length > 0) {
      const preferred =
        (initialBundleTarget &&
          targetCandidates.find((f) => f.path === initialBundleTarget)?.path) ||
        targetCandidates[0].path;
      setBundleTarget(preferred);
    }
  }, [bundleTarget, targetCandidates, initialBundleTarget]);

  const [query, setQuery] = useState("");
  const [section, setSection] = useState("");
  const [goals, setGoals] = useState("");
  const [budget, setBudget] = useState("");
  const [comments, setComments] = useState<DraftComment[]>([
    { id: "c1", category: "general", text: "" },
  ]);

  // Snapshot taken right before each Run, so the right-hand pane can
  // show a real before/after diff once the task completes.
  const [beforeText, setBeforeText] = useState<string | null>(null);

  const fileQ = useQuery({
    queryKey: ["manuscript-file", manuscriptId, bundleTarget],
    queryFn: () => manuscriptsApi.readFile(manuscriptId, bundleTarget),
    enabled: Boolean(bundleTarget),
  });

  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const stream = useTaskStream(activeTaskId);

  useEffect(() => {
    if (!activeTaskId) return;
    if (
      stream.status === "ok" ||
      stream.status === "error" ||
      stream.status === "cancelled"
    ) {
      void qc.invalidateQueries({
        queryKey: ["manuscript-file", manuscriptId, bundleTarget],
      });
      void qc.invalidateQueries({ queryKey: ["manuscript-tree", manuscriptId] });
    }
  }, [stream.status, activeTaskId, manuscriptId, bundleTarget, qc]);

  const runMut = useMutation({
    mutationFn: async () => {
      if (!bundleTarget) throw new Error("Pick a target file first.");
      // Snapshot the current text so the diff has a stable "before".
      setBeforeText(fileQ.data?.content ?? "");

      const cleanComments = comments
        .map((c) => ({
          id: c.id.trim() || undefined,
          category: c.category,
          text: c.text.trim(),
        }))
        .filter((c) => c.text);
      const goalsList = goals
        .split("\n")
        .map((g) => g.trim())
        .filter(Boolean);

      const body: CreateTaskInput = {
        workflow: "revision",
        query: query.trim() || "Apply reviewer comments.",
        input: {
          manuscript_id: manuscriptId,
          bundle_target: bundleTarget,
          comments: cleanComments,
          goals: goalsList,
          ...(section.trim() ? { section: section.trim() } : {}),
        },
      };
      if (budget.trim()) {
        const v = Number(budget);
        if (Number.isFinite(v) && v > 0) body.budget_usd = v;
      }
      return api<CreateTaskResponse>("/api/tasks", { method: "POST", json: body });
    },
    onSuccess: (data) => {
      setActiveTaskId(data.task_id);
      toast.success("Revision enqueued", {
        description: data.task_id.slice(0, 12),
      });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      toast.error("Failed to enqueue revision", { description: msg });
    },
  });

  const noTargets = !tree.isLoading && targetCandidates.length === 0;

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-0 flex-col">
      <RevisionHeader
        meta={meta.data}
        loading={meta.isLoading}
        onSwitch={() => onChangeManuscript(null)}
        onOpen={() => navigate(`/papers/${manuscriptId}`)}
      />

      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge variant="primary" className="gap-1">
          {t("revision.bundle.modeBadge")}
        </Badge>
        <span className="text-xs text-[var(--color-muted-foreground)]">
          {t("revision.bundle.targetFileHint")}
        </span>
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[20rem_1fr]">
        <Card className="flex min-h-0 flex-col overflow-y-auto">
          <CardHeader className="p-3">
            <CardTitle className="text-sm">Revision plan</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4 p-4 pt-0">
            <div className="space-y-1.5">
              <Label htmlFor="bundle-target">{t("revision.bundle.targetFile")}</Label>
              {noTargets ? (
                <p className="text-xs text-[var(--color-muted-foreground)]">
                  {t("revision.bundle.noTargetFiles")}
                </p>
              ) : (
                <select
                  id="bundle-target"
                  className="h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm font-mono"
                  value={bundleTarget}
                  onChange={(e) => {
                    setBundleTarget(e.target.value);
                    setBeforeText(null);
                  }}
                >
                  {targetCandidates.map((f) => (
                    <option key={f.path} value={f.path}>
                      {f.path}
                    </option>
                  ))}
                </select>
              )}
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-query">Instruction</Label>
              <Input
                id="rs-query"
                placeholder="e.g. Address reviewer 2's clarity concerns"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-section">Section (optional)</Label>
              <Input
                id="rs-section"
                placeholder="e.g. Methods, Section 3.2"
                value={section}
                onChange={(e) => setSection(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Reviewer comments</Label>
              <ul className="space-y-2">
                {comments.map((c, i) => (
                  <li
                    key={c.id}
                    className="space-y-1 rounded-md border border-[var(--color-border)] p-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
                        {c.id}
                      </span>
                      <select
                        aria-label={`category for ${c.id}`}
                        value={c.category}
                        onChange={(e) => {
                          const next = [...comments];
                          next[i] = {
                            ...c,
                            category: e.target.value as CommentCategory,
                          };
                          setComments(next);
                        }}
                        className="h-6 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-1 text-[10px]"
                      >
                        {COMMENT_CATEGORIES.map((cat) => (
                          <option key={cat} value={cat}>
                            {cat}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        aria-label={`remove ${c.id}`}
                        onClick={() =>
                          setComments(
                            comments.length > 1
                              ? comments.filter((_, j) => j !== i)
                              : comments,
                          )
                        }
                        className="ml-auto text-[var(--color-muted-foreground)] hover:text-[var(--color-destructive)]"
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </div>
                    <Textarea
                      value={c.text}
                      onChange={(e) => {
                        const next = [...comments];
                        next[i] = { ...c, text: e.target.value };
                        setComments(next);
                      }}
                      placeholder="Reviewer 2: '…'"
                      className="min-h-16 text-xs"
                    />
                  </li>
                ))}
              </ul>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setComments((s) => [
                    ...s,
                    { id: nextCommentId(s), category: "general", text: "" },
                  ])
                }
              >
                <Plus className="h-3.5 w-3.5" /> Add comment
              </Button>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-goals">Global goals (one per line, optional)</Label>
              <Textarea
                id="rs-goals"
                placeholder={"tighten prose\nadd citations to recent work"}
                value={goals}
                onChange={(e) => setGoals(e.target.value)}
                className="min-h-20 text-xs"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="rs-budget">Budget (USD, optional)</Label>
              <Input
                id="rs-budget"
                type="number"
                min="0"
                step="0.01"
                value={budget}
                onChange={(e) => setBudget(e.target.value)}
              />
            </div>

            <Separator />

            <div className="flex gap-2">
              <Button
                type="button"
                className="flex-1"
                onClick={() => runMut.mutate()}
                disabled={
                  runMut.isPending ||
                  !bundleTarget ||
                  noTargets ||
                  stream.status === "running"
                }
              >
                {runMut.isPending || stream.status === "running" ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Running…
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" /> Run revision
                  </>
                )}
              </Button>
            </div>

            <p className="text-[11px] text-[var(--color-muted-foreground)]">
              {t("revision.bundle.rerunHint")}
            </p>
          </CardContent>
        </Card>

        <div className="flex min-h-0 flex-col gap-4">
          <Card className="flex min-h-0 flex-1 flex-col">
            <CardHeader className="flex flex-row items-center justify-between gap-2 p-3">
              <CardTitle className="text-sm">
                {bundleTarget ? (
                  <span className="font-mono text-xs">
                    {t("revision.bundle.diffTitle", { path: bundleTarget })}
                  </span>
                ) : (
                  t("revision.bundle.diffEmpty")
                )}
                {stream.status === "ok" && beforeText !== null && (
                  <span className="ml-2 inline-flex items-center gap-1 text-xs font-normal text-[var(--color-success)]">
                    <CheckCircle2 className="h-3 w-3" /> revised
                  </span>
                )}
              </CardTitle>
              {bundleTarget && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => navigate(`/papers/${manuscriptId}`)}
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  {t("revision.bundle.openInExplorer")}
                </Button>
              )}
            </CardHeader>
            <CardContent className="min-h-0 flex-1 p-0">
              {!bundleTarget ? (
                <div className="p-6">
                  <EmptyState
                    title={t("revision.bundle.diffEmpty")}
                    description={t("revision.bundle.targetFileHint")}
                  />
                </div>
              ) : (
                <DiffEditor
                  height="100%"
                  language={
                    bundleTarget.endsWith(".tex") ? "latex" : "markdown"
                  }
                  original={beforeText ?? fileQ.data?.content ?? ""}
                  modified={fileQ.data?.content ?? ""}
                  theme={isDark ? "vs-dark" : "vs"}
                  options={{
                    readOnly: true,
                    renderSideBySide: true,
                    originalEditable: false,
                    fontSize: 13,
                    wordWrap: "on",
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    padding: { top: 12, bottom: 12 },
                  }}
                />
              )}
            </CardContent>
          </Card>

          {activeTaskId && (
            <Card>
              <CardHeader className="flex flex-row items-center justify-between gap-2 p-3">
                <CardTitle className="font-mono text-xs">{activeTaskId}</CardTitle>
                <StatusPill status={stream.status} />
              </CardHeader>
              {stream.error && (
                <CardContent className="pt-0">
                  <TaskError error={stream.error} />
                </CardContent>
              )}
              <CardContent className="max-h-72 overflow-y-auto p-3 pt-0">
                <EventTimeline events={stream.events} />
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
