/**
 * Universal task detail view (P9.2).
 *
 * Visible at ``/tasks/:taskId``. Designed so the user can answer the
 * three questions raised in the P9 feedback regardless of which
 * workflow ran:
 *
 *  1. *What did the agent do?*  →  EventTimeline (process)
 *  2. *What did it produce?*    →  Result panel (workflow-aware)
 *  3. *What changed?*           →  Before/After diff panel (when the
 *                                  workflow shape carries both)
 *
 * The result panel branches on ``task.workflow`` so each common shape
 * (research / write / revision / dag / generic) is rendered in the way
 * the user expects. Anything we don't recognise falls back to a JSON
 * dump so power users still have something to read.
 */

import { DiffEditor } from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import { ArrowLeft, ExternalLink, Loader2, MessageCircleMore, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { PageHeader } from "@/components/common/PageHeader";
import { StatusPill } from "@/components/common/StatusPill";
import { TaskError } from "@/components/common/TaskError";
import { EventTimeline } from "@/components/research/EventTimeline";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Input";
import { LinkButton } from "@/components/ui/LinkButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTaskStream } from "@/hooks/useTaskStream";
import { api } from "@/lib/api";
import { useUiStore } from "@/stores/uiStore";
import type { CreateTaskResponse, TaskListResponse, TaskRecord } from "@/types/api";

interface PaperResult {
  paper_id?: string;
  title?: string;
  authors?: string[];
  abstract?: string;
  summary?: string;
  tags?: string[];
  pdf_url?: string;
}

interface ResearchResults {
  query?: string;
  count?: number;
  papers?: PaperResult[];
}

interface WriteResults {
  section?: string;
  topic?: string;
  markdown?: string;
  outline?: unknown;
  citations?: string[];
  word_count?: number;
}

interface RevisionResults {
  section?: string;
  original?: string;
  revised?: string;
  change_log?: Array<Record<string, unknown>>;
  comments_addressed?: string[];
  comments_open?: string[];
  citations?: string[];
}

export function TaskDetailPage() {
  const { taskId = "" } = useParams<{ taskId: string }>();
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const theme = useUiStore((s) => s.theme);
  const monacoTheme = theme === "dark" ? "vs-dark" : "vs";

  const taskQ = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api<TaskRecord>(`/api/tasks/${taskId}`),
    enabled: Boolean(taskId),
    refetchInterval: (q) => {
      const data = q.state.data as TaskRecord | undefined;
      if (!data) return 2000;
      if (data.status === "ok" || data.status === "error" || data.status === "cancelled") {
        return false;
      }
      return 2000;
    },
  });

  const stream = useTaskStream(taskQ.data && taskQ.data.status !== "ok" && taskQ.data.status !== "error" && taskQ.data.status !== "cancelled" ? taskId : null);

  const task = taskQ.data;

  // ---- P9.3: thread view (children) ---------------------------------
  // List tasks that name this one as their parent. Cheap to fetch
  // because the backend filters server-side on input.parent_task_id.
  const childrenQ = useQuery({
    queryKey: ["task-children", taskId],
    queryFn: () =>
      api<TaskListResponse>(
        `/api/tasks?parent_task_id=${encodeURIComponent(taskId)}&limit=50`,
      ),
    enabled: Boolean(taskId),
    refetchInterval: 4000,
  });
  const children = childrenQ.data?.items ?? [];

  // ---- P9.3: follow-up composer -------------------------------------
  const [followUpQuery, setFollowUpQuery] = useState("");
  const followUpMut = useMutation({
    mutationFn: (query: string) =>
      api<CreateTaskResponse>(`/api/tasks/${taskId}/follow-up`, {
        method: "POST",
        json: { query },
      }),
    onSuccess: (data) => {
      setFollowUpQuery("");
      void queryClient.invalidateQueries({ queryKey: ["task-children", taskId] });
      void queryClient.invalidateQueries({ queryKey: ["tasks"] });
      navigate(`/tasks/${data.task_id}`);
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t("tasks.detail.followUpFailed")}: ${message}`);
    },
  });

  if (taskQ.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton className="h-10 w-64" />
        <Skeleton className="h-32 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  if (!task) {
    return (
      <div className="space-y-3">
        <Link to="/tasks" className="inline-flex items-center gap-1 text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]">
          <ArrowLeft className="h-3 w-3" />
          {t("tasks.detail.back")}
        </Link>
        <p className="text-sm text-[var(--color-destructive)]">Task {taskId} not found.</p>
      </div>
    );
  }

  const finalStatus = task.status;
  // Prefer the live stream events while running, otherwise show whatever
  // the runner persisted in the task store.
  const events = stream.events.length > 0 ? stream.events : [];
  const isTerminal = finalStatus === "ok" || finalStatus === "error" || finalStatus === "cancelled";
  const parentTaskId = (task.input?.parent_task_id as string | undefined) ?? "";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <Link
          to="/tasks"
          className="inline-flex items-center gap-1 text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
        >
          <ArrowLeft className="h-3 w-3" />
          {t("tasks.detail.back")}
        </Link>
        {parentTaskId && (
          <Link
            to={`/tasks/${parentTaskId}`}
            className="inline-flex items-center gap-1 rounded border border-[var(--color-border)] px-2 py-0.5 text-[11px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
          >
            <MessageCircleMore className="h-3 w-3" />
            {t("tasks.detail.openParent")}
            <span className="ml-1 font-mono">{parentTaskId.slice(0, 12)}</span>
          </Link>
        )}
      </div>

      <PageHeader
        title={t("tasks.detail.title", { id: task.id.slice(0, 12) })}
        description={task.query || ""}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-[10px]">{task.workflow}</Badge>
            <StatusPill status={finalStatus} />
          </div>
        }
      />

      {task.error && <TaskError error={task.error} />}

      {/* Process timeline ------------------------------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("tasks.detail.process")}</CardTitle>
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("tasks.detail.processHint")}
          </p>
        </CardHeader>
        <CardContent>
          {events.length === 0 && isTerminal ? (
            <p className="text-xs italic text-[var(--color-muted-foreground)]">
              {t("tasks.detail.noEvents")}
            </p>
          ) : (
            <EventTimeline events={events} />
          )}
        </CardContent>
      </Card>

      {/* Workflow-specific result panel ----------------------------------- */}
      <ResultPanel task={task} monacoTheme={monacoTheme} />

      {/* Inputs (always visible for debuggability) ------------------------ */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("tasks.detail.input")}</CardTitle>
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("tasks.detail.inputHint")}
          </p>
        </CardHeader>
        <CardContent>
          <pre className="overflow-x-auto rounded bg-[var(--color-muted)]/40 p-3 font-mono text-[11px] text-[var(--color-foreground)]/85">
            {JSON.stringify(task.input, null, 2)}
          </pre>
          {task.created_at && (
            <p className="mt-2 text-[10px] text-[var(--color-muted-foreground)]">
              created {format(new Date(task.created_at), "yyyy-MM-dd HH:mm:ss")}
              {task.completed_at && ` · finished ${format(new Date(task.completed_at), "yyyy-MM-dd HH:mm:ss")}`}
            </p>
          )}
        </CardContent>
      </Card>

      {/* Conversation thread (P9.3) -------------------------------------- */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("tasks.detail.thread")}</CardTitle>
        </CardHeader>
        <CardContent>
          {children.length === 0 ? (
            <p className="text-xs italic text-[var(--color-muted-foreground)]">
              {t("tasks.detail.threadEmpty")}
            </p>
          ) : (
            <ul className="space-y-2">
              {children.map((child) => (
                <li key={child.id}>
                  <Link
                    to={`/tasks/${child.id}`}
                    className="flex items-start justify-between gap-3 rounded border border-[var(--color-border)] p-2 hover:bg-[var(--color-muted)]/30"
                  >
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="font-mono text-[10px]">
                          {child.id.slice(0, 12)}
                        </Badge>
                        <StatusPill status={child.status} />
                      </div>
                      <p className="mt-1 truncate text-xs text-[var(--color-foreground)]/85">
                        {child.query || "(no query)"}
                      </p>
                      {child.error && (
                        <div className="mt-1">
                          <TaskError error={child.error} density="compact" />
                        </div>
                      )}
                    </div>
                    {child.created_at && (
                      <span className="shrink-0 text-[10px] text-[var(--color-muted-foreground)]">
                        {format(new Date(child.created_at), "MM-dd HH:mm")}
                      </span>
                    )}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      {/* Follow-up composer (P9.3) --------------------------------------- */}
      {isTerminal && (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm">{t("tasks.detail.followUp")}</CardTitle>
            <p className="text-xs text-[var(--color-muted-foreground)]">
              {t("tasks.detail.followUpHint")}
            </p>
          </CardHeader>
          <CardContent>
            <Textarea
              value={followUpQuery}
              onChange={(e) => setFollowUpQuery(e.target.value)}
              placeholder={t("tasks.detail.followUpPlaceholder")}
              rows={3}
              disabled={followUpMut.isPending}
              className="font-mono text-xs"
            />
            <div className="mt-2 flex items-center justify-end">
              <Button
                type="button"
                size="sm"
                disabled={followUpMut.isPending || followUpQuery.trim().length === 0}
                onClick={() => followUpMut.mutate(followUpQuery.trim())}
              >
                {followUpMut.isPending ? (
                  <>
                    <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                    {t("tasks.detail.followUpSending")}
                  </>
                ) : (
                  <>
                    <Send className="mr-1 h-3 w-3" />
                    {t("tasks.detail.followUpSend")}
                  </>
                )}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

interface ResultPanelProps {
  task: TaskRecord;
  monacoTheme: string;
}

function ResultPanel({ task, monacoTheme }: ResultPanelProps) {
  const { t } = useTranslation();

  if (task.status === "queued" || task.status === "running") {
    return null;
  }

  if (task.workflow === "research") {
    return <ResearchResultPanel task={task} />;
  }
  if (task.workflow === "write") {
    return <WriteResultPanel task={task} />;
  }
  if (task.workflow === "revision") {
    return <RevisionResultPanel task={task} monacoTheme={monacoTheme} />;
  }

  // Generic / dag / unknown fallback: pretty-print the result JSON so the
  // user at least sees what the workflow returned.
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t("tasks.detail.result")}</CardTitle>
      </CardHeader>
      <CardContent>
        {task.result == null || (typeof task.result === "object" && Object.keys(task.result).length === 0) ? (
          <p className="text-xs italic text-[var(--color-muted-foreground)]">
            {t("tasks.detail.resultEmpty")}
          </p>
        ) : (
          <pre className="overflow-x-auto rounded bg-[var(--color-muted)]/40 p-3 font-mono text-[11px] text-[var(--color-foreground)]/85">
            {JSON.stringify(task.result, null, 2)}
          </pre>
        )}
      </CardContent>
    </Card>
  );
}

function ResearchResultPanel({ task }: { task: TaskRecord }) {
  const { t } = useTranslation();
  const results = (task.result ?? {}) as ResearchResults;
  const papers = results.papers ?? [];

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t("tasks.detail.result")}</CardTitle>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t("tasks.detail.papersFound", { count: papers.length })}
        </p>
      </CardHeader>
      <CardContent>
        {papers.length === 0 ? (
          <p className="text-xs italic text-[var(--color-muted-foreground)]">
            {t("tasks.detail.noPapers")}
          </p>
        ) : (
          <ul className="space-y-3">
            {papers.map((p, i) => (
              <li key={p.paper_id ?? i} className="rounded border border-[var(--color-border)] p-3">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">{p.title ?? p.paper_id ?? "(untitled)"}</div>
                    {p.authors && p.authors.length > 0 && (
                      <div className="mt-0.5 text-[11px] text-[var(--color-muted-foreground)]">
                        {p.authors.slice(0, 4).join(", ")}
                        {p.authors.length > 4 && " et al."}
                      </div>
                    )}
                  </div>
                  {p.pdf_url && (
                    <a href={p.pdf_url} target="_blank" rel="noreferrer" className="text-[11px] text-[var(--color-primary)] hover:underline inline-flex items-center gap-1">
                      PDF <ExternalLink className="h-3 w-3" />
                    </a>
                  )}
                </div>
                {p.summary && (
                  <p className="mt-2 text-xs text-[var(--color-foreground)]/85">{p.summary}</p>
                )}
                {!p.summary && p.abstract && (
                  <p className="mt-2 text-xs text-[var(--color-muted-foreground)] line-clamp-3">{p.abstract}</p>
                )}
                {p.tags && p.tags.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {p.tags.map((tag) => (
                      <Badge key={tag} variant="neutral" className="text-[10px]">{tag}</Badge>
                    ))}
                  </div>
                )}
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function WriteResultPanel({ task }: { task: TaskRecord }) {
  const { t } = useTranslation();
  const results = (task.result ?? {}) as WriteResults;
  const markdown = results.markdown ?? "";
  const manuscriptId = (task.input?.manuscript_id as string | undefined) ?? "";

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm">{t("tasks.detail.result")}</CardTitle>
            {results.word_count != null && (
              <p className="text-xs text-[var(--color-muted-foreground)]">
                {t("tasks.detail.wordCount", { count: results.word_count })}
              </p>
            )}
          </div>
          {manuscriptId && (
            <LinkButton to={`/papers/${manuscriptId}`} variant="outline" size="sm">
              {t("tasks.detail.openWriter")} <ExternalLink className="ml-1 h-3 w-3" />
            </LinkButton>
          )}
        </div>
      </CardHeader>
      <CardContent>
        {markdown ? (
          <pre className="overflow-x-auto rounded bg-[var(--color-muted)]/40 p-3 font-mono text-[11px] text-[var(--color-foreground)]/85 whitespace-pre-wrap">
            {markdown}
          </pre>
        ) : (
          <p className="text-xs italic text-[var(--color-muted-foreground)]">
            {t("tasks.detail.resultEmpty")}
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function RevisionResultPanel({ task, monacoTheme }: { task: TaskRecord; monacoTheme: string }) {
  const { t } = useTranslation();
  const results = (task.result ?? {}) as RevisionResults;
  const original = useMemo(() => results.original ?? (task.input?.text as string | undefined) ?? "", [results.original, task.input]);
  const revised = results.revised ?? "";
  const manuscriptId = (task.input?.manuscript_id as string | undefined) ?? "";
  const bundleTarget = (task.input?.bundle_target as string | undefined) ?? "";

  if (!revised && !original) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("tasks.detail.result")}</CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-xs italic text-[var(--color-muted-foreground)]">
            {t("tasks.detail.resultEmpty")}
          </p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="text-sm">{t("tasks.detail.compare")}</CardTitle>
            <p className="text-xs text-[var(--color-muted-foreground)]">
              {t("tasks.detail.compareHint")}
              {bundleTarget && <span className="ml-2 font-mono">· {bundleTarget}</span>}
            </p>
          </div>
          {manuscriptId && (
            <LinkButton
              to={`/revision?manuscript_id=${encodeURIComponent(manuscriptId)}${bundleTarget ? `&bundle_target=${encodeURIComponent(bundleTarget)}` : ""}`}
              variant="outline"
              size="sm"
            >
              {t("tasks.detail.openRevision")} <ExternalLink className="ml-1 h-3 w-3" />
            </LinkButton>
          )}
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-[480px] w-full overflow-hidden rounded border border-[var(--color-border)]">
          <DiffEditor
            original={original || ""}
            modified={revised || ""}
            language={bundleTarget?.endsWith(".tex") ? "latex" : "markdown"}
            theme={monacoTheme}
            options={{
              readOnly: true,
              renderSideBySide: true,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 12,
              wordWrap: "on",
            }}
          />
        </div>
        <div className="mt-2 grid grid-cols-2 gap-2 text-[10px] text-[var(--color-muted-foreground)]">
          <span>← {t("tasks.detail.compareBefore")}</span>
          <span className="text-right">{t("tasks.detail.compareAfter")} →</span>
        </div>
      </CardContent>
    </Card>
  );
}
