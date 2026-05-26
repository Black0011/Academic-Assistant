/**
 * UnifiedWorkbenchPage — single conversational interface for both
 * research and writing. Replaces the split ResearchConsole / PaperChat.
 *
 * - No manuscript in URL → manuscript picker + research chat
 * - Manuscript in URL     → existing ChatStudio experience
 */
import { useQuery } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  ArrowRight,
  BookOpenText,
  LayoutPanelTop,
  Loader2,
  PlusCircle,
  Send,
  Sparkles,
} from "lucide-react";
import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusPill } from "@/components/common/StatusPill";
import { TaskError } from "@/components/common/TaskError";
import { ResearchSummary } from "@/components/chat/ResearchSummary";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTaskStream } from "@/hooks/useTaskStream";
import { api } from "@/lib/api";
import { manuscriptsApi } from "@/lib/manuscripts";
import { ChatStudio } from "@/pages/PaperChatPage";
import type { CreateTaskResponse, Manuscript, TaskRecord } from "@/types/api";

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

export function UnifiedWorkbenchPage() {
  const { manuscriptId = "" } = useParams<{ manuscriptId?: string }>();
  const [params] = useSearchParams();
  const target = params.get("target") ?? "";
  const thread = params.get("thread") ?? "";

  if (manuscriptId) {
    return (
      <ChatStudio
        key={manuscriptId}
        manuscriptId={manuscriptId}
        initialTarget={target}
        initialThread={thread}
      />
    );
  }
  return <UnifiedEmptyState />;
}

// ---------------------------------------------------------------------------
// Empty-state workbench — research + manuscript picker
// ---------------------------------------------------------------------------

function UnifiedEmptyState() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sending, setSending] = useState(false);

  const list = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  const activeTask = useQuery({
    queryKey: ["task", activeTaskId],
    queryFn: () => api<TaskRecord>(`/api/tasks/${activeTaskId}`),
    enabled: Boolean(activeTaskId),
    refetchInterval: (q) => {
      const data = q.state.data as TaskRecord | undefined;
      if (!data) return 2000;
      return data.status === "ok" || data.status === "error" || data.status === "cancelled"
        ? false
        : 2000;
    },
  });

  // Live SSE streaming for the active task
  const stream = useTaskStream(activeTaskId ?? "", Boolean(activeTaskId));

  const handleSend = useCallback(async () => {
    const q = query.trim();
    if (!q || sending) return;
    setSending(true);
    try {
      const body: Record<string, unknown> = {
        query: q,
        workflow: "auto",
      };
      const res = await api<CreateTaskResponse>("/api/tasks", {
        method: "POST",
        body: JSON.stringify(body),
      });
      setActiveTaskId(res.task_id);
      setQuery("");
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : "Failed to send";
      toast.error(msg);
    } finally {
      setSending(false);
    }
  }, [query, sending]);

  // When a research task completes and returns manuscript_id, navigate there
  const taskResult = activeTask.data as TaskRecord | undefined;
  const isComplete = taskResult?.status === "ok" || taskResult?.status === "error";
  const taskData = (taskResult?.result ?? {}) as Record<string, unknown>;
  const summary = taskData?.summary as Record<string, unknown> | undefined;
  const intent = taskData?.intent as string | undefined;
  const autoManuscriptId = taskData?.manuscript_id as string | undefined;

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        handleSend();
      }
    },
    [handleSend],
  );

  return (
    <WorkbenchShell
      left={
        <ManuscriptListPanel
          manuscripts={list.data?.items ?? []}
          isLoading={list.isLoading}
        />
      }
      center={<WelcomePanel onNavigateToManuscript={(id) => navigate(`/workbench/${id}`)} />}
      right={
        <div className="flex h-full flex-col">
          {/* Chat thread area */}
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {!activeTaskId && (
              <div className="flex flex-col items-center justify-center h-full gap-3 text-[var(--color-muted-foreground)]">
                <Sparkles className="h-8 w-8 opacity-40" />
                <p className="text-sm text-center max-w-xs">
                  {t("chat.emptyHint") ?? "Research a topic or ask anything. Pick a manuscript to start writing."}
                </p>
              </div>
            )}

            {/* Active task display */}
            {activeTaskId && activeTask.isLoading && (
              <div className="flex items-center gap-2 text-sm text-[var(--color-muted-foreground)]">
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>{t("common.loading") ?? "Working..."}</span>
              </div>
            )}

            {/* Pending / running state */}
            {taskResult && !isComplete && (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-sm">
                  <StatusPill status={taskResult.status} />
                  <span className="text-[var(--color-muted-foreground)]">
                    {taskResult.query}
                  </span>
                </div>
                {stream.length > 0 && (
                  <div className="rounded-md border bg-[var(--color-card)] p-3 text-sm">
                    <pre className="whitespace-pre-wrap font-mono text-xs">
                      {stream.map((e) => e.data?.delta ?? "").join("")}
                    </pre>
                  </div>
                )}
              </div>
            )}

            {/* Completed research task */}
            {taskResult && isComplete && taskResult.status === "ok" && (
              <div className="space-y-3">
                {/* User message bubble */}
                <div className="flex justify-end">
                  <div className="max-w-[80%] rounded-lg bg-[var(--color-primary)]/10 px-3 py-2 text-sm">
                    {taskResult.query}
                  </div>
                </div>

                {/* Research summary */}
                {summary && (
                  <ResearchSummary
                    data={{
                      narrative: summary.narrative as string,
                      key_findings: summary.key_findings as string[],
                      gaps: summary.gaps as string[],
                      next_steps: summary.next_steps as string[],
                    }}
                  />
                )}

                {/* Paper results */}
                {taskData?.papers && Array.isArray(taskData.papers) && taskData.papers.length > 0 && (
                  <div className="text-xs text-[var(--color-muted-foreground)]">
                    Found {(taskData.papers as unknown[]).length} papers
                  </div>
                )}

                {/* Auto-created manuscript action */}
                {autoManuscriptId && (
                  <Button
                    size="sm"
                    onClick={() => navigate(`/workbench/${autoManuscriptId}`)}
                  >
                    <LayoutPanelTop className="mr-2 h-3.5 w-3.5" />
                    Open draft manuscript
                  </Button>
                )}

                {/* New research button */}
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => setActiveTaskId(null)}
                >
                  <PlusCircle className="mr-2 h-3.5 w-3.5" />
                  New query
                </Button>
              </div>
            )}

            {/* Error state */}
            {taskResult && isComplete && taskResult.status === "error" && (
              <TaskError error={taskResult.error} />
            )}
          </div>

          {/* Composer */}
          <div className="border-t p-3">
            <div className="flex items-end gap-2">
              <Textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={handleKeyDown}
                placeholder={
                  activeTaskId
                    ? (t("chat.followUp") ?? "Ask a follow-up...")
                    : (t("chat.researchPlaceholder") ?? "Research a topic or describe what to write...")
                }
                className="min-h-[44px] flex-1 resize-none text-sm"
                rows={2}
                disabled={sending}
              />
              <Button
                size="icon"
                disabled={!query.trim() || sending}
                onClick={handleSend}
                aria-label={t("chat.send") ?? "Send"}
              >
                {sending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Send className="h-4 w-4" />
                )}
              </Button>
            </div>
            <p className="mt-1 text-[10px] text-[var(--color-muted-foreground)]/60">
              Ctrl+Enter to send · Auto-detects research vs writing
            </p>
          </div>
        </div>
      }
    />
  );
}

// ---------------------------------------------------------------------------
// Left panel — manuscript list
// ---------------------------------------------------------------------------

function ManuscriptListPanel({
  manuscripts,
  isLoading,
}: {
  manuscripts: Manuscript[];
  isLoading: boolean;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (isLoading) {
    return (
      <div className="p-4 space-y-3">
        <Skeleton className="h-4 w-2/3" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-4 py-3">
        <span className="text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
          {t("nav.manuscripts") ?? "Manuscripts"}
        </span>
        <Link
          to="/papers"
          className="text-[10px] text-[var(--color-primary)] hover:underline"
        >
          {t("common.viewAll") ?? "View all"} →
        </Link>
      </div>
      <div className="flex-1 overflow-y-auto">
        {manuscripts.length === 0 ? (
          <div className="p-4">
            <EmptyState
              title={t("chat.noManuscripts") ?? "No manuscripts"}
              description={t("chat.noManuscriptsHint") ?? "Create one to start writing"}
            />
          </div>
        ) : (
          <ul className="divide-y">
            {manuscripts.map((m) => (
              <li key={m.id}>
                <button
                  type="button"
                  onClick={() => navigate(`/workbench/${m.id}`)}
                  className="flex w-full items-center justify-between gap-2 p-3 text-left hover:bg-[var(--color-muted)] text-sm"
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">
                      {m.title || (t("chat.untitled") ?? "Untitled")}
                    </div>
                    <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
                      v{m.current_version} ·{" "}
                      {format(new Date(m.updated_at), "yyyy-MM-dd")}
                    </div>
                  </div>
                  <Badge variant="neutral" className="shrink-0 text-[10px]">
                    {m.status}
                  </Badge>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Center panel — welcome state
// ---------------------------------------------------------------------------

function WelcomePanel({
  onNavigateToManuscript,
}: {
  onNavigateToManuscript: (id: string) => void;
}) {
  const { t } = useTranslation();

  const recentManuscripts = useQuery({
    queryKey: ["manuscripts", { limit: 5 }],
    queryFn: () => manuscriptsApi.list({ limit: 5 }),
  });

  return (
    <div className="flex h-full items-center justify-center p-8">
      <div className="max-w-md space-y-6 text-center">
        <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl bg-[var(--color-primary)]/10">
          <Sparkles className="h-8 w-8 text-[var(--color-primary)]" />
        </div>

        <div className="space-y-2">
          <h2 className="text-xl font-semibold tracking-tight">
            {t("workbench.welcome") ?? "Academic Workbench"}
          </h2>
          <p className="text-sm text-[var(--color-muted-foreground)]">
            Research papers, draft manuscripts, or revise your work — all in one
            conversational interface.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <Card className="border-dashed text-left">
            <CardContent className="p-4">
              <BookOpenText className="mb-2 h-5 w-5 text-[var(--color-primary)]" />
              <h3 className="text-sm font-semibold">
                {t("workbench.researchAction") ?? "Research"}
              </h3>
              <p className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
                Search arXiv papers and get a synthesized summary
              </p>
            </CardContent>
          </Card>

          <Card className="border-dashed text-left">
            <CardContent className="p-4">
              <LayoutPanelTop className="mb-2 h-5 w-5 text-[var(--color-primary)]" />
              <h3 className="text-sm font-semibold">
                {t("workbench.writeAction") ?? "Write"}
              </h3>
              <p className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
                Generate a manuscript draft from your topic
              </p>
            </CardContent>
          </Card>
        </div>

        {/* Recent manuscripts */}
        {recentManuscripts.data && recentManuscripts.data.items.length > 0 && (
          <div className="space-y-2 text-left">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
              {t("workbench.recentManuscripts") ?? "Recent manuscripts"}
            </h4>
            <ul className="space-y-1">
              {recentManuscripts.data.items.slice(0, 4).map((m: Manuscript) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => onNavigateToManuscript(m.id)}
                    className="flex w-full items-center gap-2 rounded-md px-3 py-2 text-left text-sm hover:bg-[var(--color-muted)]"
                  >
                    <ArrowRight className="h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />
                    <span className="truncate">
                      {m.title || (t("chat.untitled") ?? "Untitled")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </div>
  );
}
