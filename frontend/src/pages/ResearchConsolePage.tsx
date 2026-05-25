import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  ArrowRight,
  BookOpenText,
  FileText,
  LayoutPanelTop,
  Loader2,
  MessageSquare,
  PencilRuler,
  Play,
  RotateCcw,
  Search,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
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
import { cn } from "@/lib/cn";
import { ApiError, api } from "@/lib/api";
import { manuscriptsApi } from "@/lib/manuscripts";
import type {
  CreateTaskInput,
  CreateTaskResponse,
  Manuscript,
  TaskRecord,
  WorkflowInfo,
} from "@/types/api";

// Two-tab IA (P12.4):
//   - "research" (default) — original research-task console.
//   - "writing"            — list of manuscripts, each linking into the
//                            Workbench. This replaces the standalone
//                            /papers entry in the sidebar.
//
// Tab choice is stored in the URL (?tab=writing) so users can bookmark
// either view and so cross-page links (e.g. from the dashboard) can
// open the right tab directly.
type ConsoleTab = "research" | "writing";

interface FormState {
  workflow: string;
  query: string;
  budget: string; // string so we can leave it blank; coerced to number on submit
}

const DEFAULT_FORM: FormState = {
  workflow: "research",
  query: "",
  budget: "",
};

export function ResearchConsolePage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const tab: ConsoleTab = params.get("tab") === "writing" ? "writing" : "research";
  const setTab = (next: ConsoleTab) => {
    const np = new URLSearchParams(params);
    if (next === "research") np.delete("tab");
    else np.set("tab", next);
    setParams(np, { replace: true });
  };
  const [form, setForm] = useState<FormState>(DEFAULT_FORM);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);

  const workflowsQ = useQuery({
    queryKey: ["workflows"],
    queryFn: () => api<WorkflowInfo[]>("/api/workflows"),
  });

  const taskQ = useQuery({
    queryKey: ["task", activeTaskId],
    queryFn: () => api<TaskRecord>(`/api/tasks/${activeTaskId}`),
    enabled: Boolean(activeTaskId),
    refetchInterval: (q) => {
      const data = q.state.data as TaskRecord | undefined;
      if (!data) return 1500;
      return data.status === "queued" || data.status === "running" ? 1500 : false;
    },
  });

  const stream = useTaskStream(activeTaskId);

  const createMut = useMutation({
    mutationFn: async (body: CreateTaskInput) =>
      api<CreateTaskResponse>("/api/tasks", { method: "POST", json: body }),
    onSuccess: (data) => {
      setActiveTaskId(data.task_id);
      toast.success(t("research.taskEnqueued"), { description: data.task_id.slice(0, 12) });
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      toast.error(t("research.enqueueFailed"), { description: msg });
    },
  });

  useEffect(() => {
    // When the SSE stream sees a terminal event, refresh the cached record
    // so the right-hand panel shows results / errors immediately.
    if (!activeTaskId) return;
    if (stream.status === "ok" || stream.status === "error" || stream.status === "cancelled") {
      void qc.invalidateQueries({ queryKey: ["task", activeTaskId] });
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    }
  }, [stream.status, activeTaskId, qc]);

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const query = form.query.trim();
    if (!query) {
      toast.error(t("research.form.queryRequired"));
      return;
    }
    const body: CreateTaskInput = { workflow: form.workflow, query };
    if (form.budget.trim()) {
      const v = Number(form.budget);
      if (Number.isFinite(v) && v > 0) body.budget_usd = v;
    }
    createMut.mutate(body);
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("research.title")}
        description={t("research.descriptionV2")}
        actions={
          tab === "research" && activeTaskId && (
            <Button variant="outline" onClick={() => setActiveTaskId(null)}>
              <RotateCcw className="h-4 w-4" /> {t("research.newRun")}
            </Button>
          )
        }
      />

      <ConsoleTabs tab={tab} onChange={setTab} />

      {tab === "writing" ? (
        <WritingTab />
      ) : (
      <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_1fr]">
        <Card>
          <CardHeader>
            <CardTitle>{t("research.form.title")}</CardTitle>
          </CardHeader>
          <CardContent>
            <form className="space-y-4" onSubmit={onSubmit}>
              <div className="space-y-1.5">
                <Label htmlFor="workflow">{t("research.form.workflow")}</Label>
                <select
                  id="workflow"
                  className="flex h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]"
                  value={form.workflow}
                  onChange={(e) => setForm((s) => ({ ...s, workflow: e.target.value }))}
                  disabled={workflowsQ.isLoading}
                >
                  {(workflowsQ.data ?? [{ name: "research" }]).map((w) => (
                    <option key={w.name} value={w.name}>
                      {w.name}
                    </option>
                  ))}
                </select>
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="query">{t("research.form.query")}</Label>
                <Textarea
                  id="query"
                  placeholder={t("research.form.queryPlaceholder")}
                  className="min-h-32"
                  value={form.query}
                  onChange={(e) => setForm((s) => ({ ...s, query: e.target.value }))}
                />
              </div>

              <div className="space-y-1.5">
                <Label htmlFor="budget">{t("research.form.budget")}</Label>
                <Input
                  id="budget"
                  type="number"
                  step="0.01"
                  min="0"
                  placeholder={t("research.form.budgetPlaceholder")}
                  value={form.budget}
                  onChange={(e) => setForm((s) => ({ ...s, budget: e.target.value }))}
                />
              </div>

              <Separator />

              <Button type="submit" className="w-full" disabled={createMut.isPending}>
                {createMut.isPending ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> {t("research.form.submitting")}
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" /> {t("research.form.submit")}
                  </>
                )}
              </Button>
            </form>
          </CardContent>
        </Card>

        <div className="space-y-4">
          {!activeTaskId && (
            <Card>
              <CardHeader>
                <CardTitle>{t("research.waitingTitle")}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-[var(--color-muted-foreground)]">
                  {t("research.waitingHint")}
                </p>
              </CardContent>
            </Card>
          )}

          {activeTaskId && (
            <>
              <Card>
                <CardHeader className="flex flex-row items-center justify-between">
                  <div className="space-y-1">
                    <CardTitle className="font-mono text-sm">{activeTaskId}</CardTitle>
                    <p className="text-xs text-[var(--color-muted-foreground)]">
                      {taskQ.data?.workflow ?? "—"} · {taskQ.data?.query ?? ""}
                    </p>
                  </div>
                  <StatusPill status={stream.status} />
                </CardHeader>
                {stream.error && (
                  <CardContent>
                    <TaskError error={stream.error} />
                  </CardContent>
                )}
                {taskQ.data?.result && (
                  <CardContent>
                    <details className="group">
                      <summary className="cursor-pointer text-sm font-medium">
                        {t("research.resultPreview")}
                      </summary>
                      <pre className="mt-2 max-h-96 overflow-auto rounded-md border bg-[var(--color-muted)] p-3 font-mono text-[11px] scrollbar-thin">
                        {JSON.stringify(taskQ.data.result, null, 2)}
                      </pre>
                    </details>
                  </CardContent>
                )}
              </Card>

              {taskQ.data?.status === "ok" && <UseAsContextCard task={taskQ.data} />}

              <EventTimeline events={stream.events} />
            </>
          )}
        </div>
      </div>
      )}

      {/* Cite Research — upload PDF to research all its citations */}
      {tab === "research" && <CiteResearchSection />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Cite Research Section — PDF upload + citation research workflow
// ---------------------------------------------------------------------------

function CiteResearchSection() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [citeTaskId, setCiteTaskId] = useState<string | null>(null);
  const [selectedManuscriptId, setSelectedManuscriptId] = useState<string>("");

  const manuscriptsQ = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  const citeTaskQ = useQuery({
    queryKey: ["task", citeTaskId],
    queryFn: () => api<TaskRecord>(`/api/tasks/${citeTaskId}`),
    enabled: Boolean(citeTaskId),
    refetchInterval: (q) => {
      const data = q.state.data as TaskRecord | undefined;
      if (!data) return 2000;
      return data.status === "queued" || data.status === "running" ? 2000 : false;
    },
  });

  const citeMut = useMutation({
    mutationFn: () =>
      api<CreateTaskResponse>("/api/tasks", {
        method: "POST",
        json: {
          workflow: "citation-research",
          query: "Research all citations in the uploaded paper",
          input: { manuscript_id: selectedManuscriptId || undefined },
        },
      }),
    onSuccess: (data) => {
      setCiteTaskId(data.task_id);
      toast.success("Citation research started");
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (err) => {
      toast.error((err as Error).message);
    },
  });

  const manuscripts = manuscriptsQ.data?.items ?? [];
  const result = (citeTaskQ.data?.result ?? {}) as Record<string, unknown>;
  const found = (result.found as Array<Record<string, unknown>>) ?? [];
  const notFound = (result.not_found as Array<Record<string, unknown>>) ?? [];
  const lowConfidence = (result.low_confidence as Array<Record<string, unknown>>) ?? [];
  const totalRefs = (result.total_refs as number) ?? 0;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileText className="h-4 w-4" />
          Cite Research — Research citations from a paper
        </CardTitle>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          Upload a paper PDF to automatically extract its bibliography, search each reference, and store them as knowledge cards.
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-end gap-3">
          <div className="flex-1 space-y-1.5">
            <Label>Select manuscript (PDF)</Label>
            <select
              className="flex h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-3 text-sm"
              value={selectedManuscriptId}
              onChange={(e) => setSelectedManuscriptId(e.target.value)}
            >
              <option value="">— Select a manuscript —</option>
              {manuscripts.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.title || "(untitled)"} · {m.layout}
                </option>
              ))}
            </select>
          </div>
          <Button
            onClick={() => citeMut.mutate()}
            disabled={!selectedManuscriptId || citeMut.isPending}
          >
            {citeMut.isPending ? (
              <><Loader2 className="mr-1 h-4 w-4 animate-spin" /> Running...</>
            ) : (
              <><Play className="mr-1 h-4 w-4" /> Research Citations</>
            )}
          </Button>
        </div>

        {citeTaskQ.data && (
          <div className="space-y-1 text-xs">
            <div className="flex items-center gap-2">
              <StatusPill status={citeTaskQ.data.status} />
              <span className="font-mono text-[10px]">{citeTaskQ.data.id.slice(0, 12)}</span>
            </div>
            {citeTaskQ.data.status === "ok" && (
              <div className="space-y-1 rounded border bg-[var(--color-muted)]/30 p-2">
                <div className="font-medium">{totalRefs} references processed</div>
                {found.length > 0 && (
                  <div className="text-[var(--color-success)]">Found: {found.length} papers</div>
                )}
                {lowConfidence.length > 0 && (
                  <div className="text-[var(--color-warning)]">Low confidence: {lowConfidence.length}</div>
                )}
                {notFound.length > 0 && (
                  <details>
                    <summary className="cursor-pointer text-[var(--color-muted-foreground)]">
                      Not found: {notFound.length}
                    </summary>
                    <ul className="mt-1 space-y-0.5 pl-3">
                      {notFound.map((r, i) => (
                        <li key={i} className="text-[10px] text-[var(--color-muted-foreground)]">
                          [{r.index}] {String(r.title || "(no title)").slice(0, 60)}
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Tab bar — small inline control instead of a Radix Tabs primitive. We
// only need a-href-style state, so a 2-button row is enough and ships
// without a new dependency.
// ---------------------------------------------------------------------------

interface ConsoleTabsProps {
  tab: ConsoleTab;
  onChange: (next: ConsoleTab) => void;
}

function ConsoleTabs({ tab, onChange }: ConsoleTabsProps) {
  const { t } = useTranslation();
  const items: Array<{ id: ConsoleTab; icon: typeof Search; labelKey: string; hintKey: string }> = [
    { id: "research", icon: BookOpenText, labelKey: "research.tabs.research", hintKey: "research.tabs.researchHint" },
    { id: "writing", icon: LayoutPanelTop, labelKey: "research.tabs.writing", hintKey: "research.tabs.writingHint" },
  ];
  return (
    <div className="flex items-stretch gap-2 border-b">
      {items.map(({ id, icon: Icon, labelKey, hintKey }) => {
        const active = id === tab;
        return (
          <button
            key={id}
            type="button"
            onClick={() => onChange(id)}
            className={cn(
              "group -mb-px flex flex-col items-start gap-0.5 border-b-2 px-3 py-2 text-left transition-colors",
              active
                ? "border-[var(--color-primary)] text-[var(--color-foreground)]"
                : "border-transparent text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]",
            )}
          >
            <div className="flex items-center gap-1.5 text-sm font-medium">
              <Icon className="h-3.5 w-3.5" />
              {t(labelKey)}
            </div>
            <span className="text-[10px] text-[var(--color-muted-foreground)]">{t(hintKey)}</span>
          </button>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Writing tab — manuscript work-items, each opens into the Workbench.
// Replaces the standalone Manuscripts page in the primary sidebar.
// ---------------------------------------------------------------------------

function WritingTab() {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  if (list.isLoading) {
    return (
      <div className="space-y-2">
        <Skeleton className="h-16 w-full" />
        <Skeleton className="h-16 w-full" />
      </div>
    );
  }

  const items = list.data?.items ?? [];
  if (items.length === 0) {
    return (
      <Card>
        <CardContent className="p-6">
          <EmptyState
            title={t("research.writing.empty.title")}
            description={t("research.writing.empty.description")}
            action={
              <Link to="/papers" className="text-sm text-[var(--color-primary)] hover:underline">
                {t("research.writing.empty.cta")} →
              </Link>
            }
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t("research.writing.countLabel", { count: items.length })}
        </p>
        <Link
          to="/papers"
          className="text-xs text-[var(--color-primary)] hover:underline"
        >
          {t("research.writing.manageAll")} →
        </Link>
      </div>
      <ul className="divide-y rounded-md border bg-[var(--color-card)]">
        {items.map((m: Manuscript) => (
          <li key={m.id} className="flex items-center justify-between gap-3 p-4">
            <Link
              to={`/workbench/${encodeURIComponent(m.id)}`}
              className="flex min-w-0 flex-1 items-center gap-3 hover:opacity-80"
            >
              <FileText className="h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-medium">
                    {m.title || t("research.writing.untitled")}
                  </span>
                  <Badge variant="outline">{m.layout}</Badge>
                  <Badge variant="neutral">{m.status}</Badge>
                </div>
                <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
                  v{m.current_version} · {t("research.writing.updated")}{" "}
                  {format(new Date(m.updated_at), "yyyy-MM-dd HH:mm")}
                </div>
              </div>
            </Link>
            <div className="flex shrink-0 items-center gap-1">
              <Link
                to={`/workbench/${encodeURIComponent(m.id)}`}
                className="inline-flex items-center gap-1 rounded border px-2 py-1 text-xs hover:bg-[var(--color-muted)]"
              >
                <LayoutPanelTop className="h-3 w-3" />
                {t("research.writing.openWorkbench")}
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// "Use these papers as context for revising my manuscript" — P11 Phase D
//
// Research workflow already writes each found paper into the knowledge store
// (research.py `knowledge.write_card`), so the consult/revision workflows
// will naturally pick them up at recall time. This card just makes the next
// step obvious: pick a manuscript, jump straight into Paper Chat or
// Revision Studio with that paper pre-selected.
// ---------------------------------------------------------------------------

function UseAsContextCard({ task }: { task: TaskRecord }) {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  // Surface a paper-count badge based on whichever result shape the
  // workflow used (research returns ``papers`` as a list).
  const result = task.result ?? {};
  const papers = Array.isArray((result as Record<string, unknown>).papers)
    ? ((result as Record<string, unknown>).papers as unknown[])
    : [];
  const paperCount = papers.length;

  // Only show for research-like runs that actually produced papers.
  if (task.workflow !== "research" || paperCount === 0) return null;

  const items = list.data?.items ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t("research.useAsContext.title")}</CardTitle>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t("research.useAsContext.hint", { count: paperCount })}
        </p>
      </CardHeader>
      <CardContent>
        {list.isLoading ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("research.useAsContext.loading")}
          </p>
        ) : items.length === 0 ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("research.useAsContext.noManuscripts")}{" "}
            <Link to="/papers" className="text-[var(--color-primary)] hover:underline">
              {t("research.useAsContext.goToManuscripts")} →
            </Link>
          </p>
        ) : (
          <ul className="divide-y">
            {items.slice(0, 8).map((m: Manuscript) => (
              <li
                key={m.id}
                className="flex items-center justify-between gap-2 py-2"
              >
                <div className="min-w-0">
                  <div className="truncate text-xs font-medium">
                    {m.title || t("research.useAsContext.untitled")}
                  </div>
                  <div className="text-[10px] text-[var(--color-muted-foreground)]">
                    {m.layout} · v{m.current_version}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {m.layout === "bundle" && (
                    <Link
                      to={`/workbench/${encodeURIComponent(m.id)}`}
                      className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] hover:bg-[var(--color-muted)]"
                    >
                      <MessageSquare className="h-3 w-3" />
                      {t("research.useAsContext.chat")}
                    </Link>
                  )}
                  <Link
                    to={`/revision?manuscript=${encodeURIComponent(m.id)}`}
                    className="inline-flex items-center gap-1 rounded border px-2 py-0.5 text-[10px] hover:bg-[var(--color-muted)]"
                  >
                    <PencilRuler className="h-3 w-3" />
                    {t("research.useAsContext.revise")}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
