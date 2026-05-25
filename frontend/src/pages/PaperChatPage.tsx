/**
 * PaperChatPage (P11, refactored into the workbench in P12.3) —
 * conversational paper assistant. Despite the legacy filename, this is
 * now the Writing Workbench — a cursor-style 3-pane shell with a file
 * tree, a Monaco preview, and a chat thread.
 *
 * Route: ``/workbench/:manuscriptId?target=<path>&thread=<rootId>``
 *
 * ``/chat/:manuscriptId`` is preserved as an alias so any existing
 * bookmarks keep working — see ``routes/index.tsx``.
 *
 * Mental model
 * ------------
 * Each turn in a conversation is a backend task. We use the existing
 * ``input.parent_task_id`` plumbing (P9.3) to chain turns into a thread
 * — the thread id is just the *root* task's id.
 *
 * Modes:
 * - ``consult`` (default) → asks the agent a question about the passage
 *   without rewriting anything. Output is prose markdown.
 * - ``revision`` → applies a rewrite, persists the new text to the
 *   bundle file (existing P8 path). The user explicitly opts in via the
 *   mode toggle or the "Apply this rewrite" button on a consult reply.
 *
 * The composer keeps both modes in one URL so power-users can flow
 * "ask → discuss → revise" inside a single thread.
 *
 * Why a dedicated page instead of bolting onto /revision?
 * - The reviewer-comments flow on RevisionPage is structured and
 *   batch-oriented; users coming with a single natural-language question
 *   shouldn't have to fight that UI.
 * - We keep that page as the "power" surface and let /workbench be the
 *   one-question-at-a-time conversational surface.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { loader } from "@monaco-editor/react";
import Editor, { DiffEditor } from "@monaco-editor/react";
import { format } from "date-fns";

// Load Monaco from local Vite-served path (not CDN)
loader.config({ paths: { vs: "/monaco-vs" } });
import {
  ArrowRight,
  AlertTriangle,
  Bot,
  CheckSquare,
  ClipboardCheck,
  Copy,
  FileText,
  Loader2,
  MessageSquare,
  Pencil,
  PlusCircle,
  Save,
  Send,
  Sparkles,
  User2,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusPill } from "@/components/common/StatusPill";
import { TaskError } from "@/components/common/TaskError";
import { WorkbenchShell } from "@/components/layout/WorkbenchShell";
import { BundleFileTree } from "@/components/manuscripts/BundleExplorer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { AgentQuestion } from "@/components/chat/AgentQuestion";
import { useTaskStream } from "@/hooks/useTaskStream";
import { api } from "@/lib/api";
import { manuscriptsApi } from "@/lib/manuscripts";
import { useUiStore } from "@/stores/uiStore";
import type {
  BundleManifest,
  CreateTaskResponse,
  Manuscript,
  ManuscriptFile,
  TaskListResponse,
  TaskRecord,
} from "@/types/api";

type ChatMode = "consult" | "revision";

// ---------------------------------------------------------------------------
// Entry — dispatch into picker / studio
// ---------------------------------------------------------------------------

export function PaperChatPage() {
  const { manuscriptId = "" } = useParams<{ manuscriptId?: string }>();
  const [params, setParams] = useSearchParams();
  const target = params.get("target") ?? "";
  const thread = params.get("thread") ?? "";

  if (!manuscriptId) {
    return <ChatManuscriptPicker />;
  }
  return (
    <ChatStudio
      key={manuscriptId}
      manuscriptId={manuscriptId}
      initialTarget={target}
      initialThread={thread}
    />
  );
}

// ---------------------------------------------------------------------------
// Picker — when no manuscript is in the URL
// ---------------------------------------------------------------------------

function ChatManuscriptPicker() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const list = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  return (
    <div className="space-y-6">
      <PageHeader title={t("chat.title")} description={t("chat.description")} />
      <Card>
        <CardHeader>
          <CardTitle className="text-sm">{t("chat.pickManuscript")}</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {list.isLoading ? (
            <div className="p-4">
              <Skeleton className="h-24 w-full" />
            </div>
          ) : !list.data || list.data.items.length === 0 ? (
            <div className="p-6">
              <EmptyState
                title={t("chat.noManuscripts")}
                description={t("chat.noManuscriptsHint")}
                action={
                  <Link
                    to="/papers"
                    className="text-sm text-[var(--color-primary)] hover:underline"
                  >
                    {t("chat.goToManuscripts")} →
                  </Link>
                }
              />
            </div>
          ) : (
            <ul className="divide-y">
              {list.data.items.map((m: Manuscript) => (
                <li key={m.id}>
                  <button
                    type="button"
                    onClick={() => navigate(`/workbench/${m.id}`)}
                    className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-[var(--color-muted)]"
                  >
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-sm font-medium">
                          {m.title || t("chat.untitled")}
                        </span>
                        <Badge variant="outline">{m.layout}</Badge>
                        <Badge variant="neutral">{m.status}</Badge>
                      </div>
                      <div className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                        v{m.current_version} · {t("chat.updated")}{" "}
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
// Studio — full chat experience for a given manuscript (+ optional target)
// ---------------------------------------------------------------------------

interface ChatStudioProps {
  manuscriptId: string;
  initialTarget: string;
  initialThread: string;
}

function ChatStudio({
  manuscriptId,
  initialTarget,
  initialThread,
}: ChatStudioProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const theme = useUiStore((s) => s.theme);
  const monacoTheme = theme === "dark" ? "vs-dark" : "vs";

  // P16: workspace-persistent state — synced to URL for bookmarking,
  // but NOT used as React key, so mode/target switches don't unmount.
  const [params, setParams] = useSearchParams();
  const [targetPath, setTargetPath] = useState(initialTarget);
  const [threadId, setThreadId] = useState(initialThread);

  // Sync initial URL params into state on first mount / manuscript change.
  useEffect(() => {
    setTargetPath(initialTarget);
    setThreadId(initialThread);
  }, [initialTarget, initialThread]);

  // Keep URL in sync with state (for bookmarkability).
  const updateUrl = useCallback((opts: { target?: string; thread?: string }) => {
    const next = new URLSearchParams(params);
    if (opts.target !== undefined) {
      if (opts.target) next.set("target", opts.target);
      else next.delete("target");
    }
    if (opts.thread !== undefined) {
      if (opts.thread) next.set("thread", opts.thread);
      else next.delete("thread");
    }
    setParams(next, { replace: true });
  }, [params, setParams]);

  // Manuscript metadata
  const meta = useQuery({
    queryKey: ["manuscript", manuscriptId],
    queryFn: () => manuscriptsApi.get(manuscriptId),
  });

  // Bundle file tree (only for bundle-layout manuscripts)
  const tree = useQuery({
    queryKey: ["manuscript-tree", manuscriptId],
    queryFn: () => manuscriptsApi.tree(manuscriptId),
    enabled: meta.data?.layout === "bundle",
    staleTime: 30_000,
  });

  // Currently selected file's content (preview pane)
  const file = useQuery({
    queryKey: ["manuscript-file", manuscriptId, targetPath],
    queryFn: () => manuscriptsApi.readFile(manuscriptId, targetPath),
    enabled: Boolean(targetPath) && meta.data?.layout === "bundle",
  });

  // Thread: the root task and its children
  const rootTask = useQuery({
    queryKey: ["task", threadId],
    queryFn: () => api<TaskRecord>(`/api/tasks/${threadId}`),
    enabled: Boolean(threadId),
    refetchInterval: (q) => {
      const data = q.state.data as TaskRecord | undefined;
      if (!data) return 2000;
      return data.status === "ok" || data.status === "error" || data.status === "cancelled"
        ? false
        : 2000;
    },
  });

  const children = useQuery({
    queryKey: ["task-children", threadId],
    queryFn: () =>
      api<TaskListResponse>(`/api/tasks?parent_task_id=${threadId}&limit=200`),
    enabled: Boolean(threadId),
    refetchInterval: 3000,
  });

  // All turns in chronological order. The root task is the seed.
  const turns: TaskRecord[] = useMemo(() => {
    const out: TaskRecord[] = [];
    if (rootTask.data) out.push(rootTask.data);
    if (children.data?.items) {
      const sorted = [...children.data.items].sort(
        (a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      );
      out.push(...sorted);
    }
    return out;
  }, [rootTask.data, children.data]);

  // Live stream the *latest* task so the user sees stage progress.
  const latest = turns.length > 0 ? turns[turns.length - 1] : null;
  const streamingId =
    latest && latest.status !== "ok" && latest.status !== "error" && latest.status !== "cancelled"
      ? latest.id
      : null;
  const stream = useTaskStream(streamingId);

  // Composer state
  const [pending, setPending] = useState("");
  const [mode, setMode] = useState<ChatMode>("consult");
  const composerRef = useRef<HTMLTextAreaElement>(null);

  // P14.2: batch multi-file review
  const [batchMode, setBatchMode] = useState(false);
  const [checkedFiles, setCheckedFiles] = useState<Set<string>>(new Set());

  // P15: project mode — chat with the entire paper without picking files
  const [projectMode, setProjectMode] = useState(false);

  // P18: track recently modified files for tree highlighting
  const [recentlyModified, setRecentlyModified] = useState<Set<string>>(new Set());
  const [lastRevisionChanges, setLastRevisionChanges] = useState<Array<{path: string; before: string; after: string}>>([]);

  // P16: file selection helpers — keep conversation alive across switches
  const handlePickTarget = useCallback((path: string) => {
    setTargetPath(path);
    setProjectMode(false);
    setBatchMode(false);
    updateUrl({ target: path });
  }, [updateUrl]);

  const handleSetThread = useCallback((tid: string) => {
    setThreadId(tid);
    updateUrl({ thread: tid });
  }, [updateUrl]);

  // Auto-scroll thread on new turns
  const threadRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (threadRef.current) {
      threadRef.current.scrollTop = threadRef.current.scrollHeight;
    }
  }, [turns.length, stream.events.length]);

  // P18: when a revision completes, refresh tree + highlight modified files
  useEffect(() => {
    if (stream.status !== "ok") return;
    const latestTurn = turns[turns.length - 1];
    if (!latestTurn) return;
    const r = (latestTurn.result ?? {}) as Record<string, unknown>;
    const modifiedPaths: string[] = [];

    if (latestTurn.workflow === "project-revision") {
      // Multi-file: extract from files_modified
      const fm = (r.files_modified as string[] | undefined) ?? [];
      modifiedPaths.push(...fm);
      // Save changes for editor banner use
      const ch = (r.changes as Array<{path: string; before: string; after: string}> | undefined) ?? [];
      if (ch.length > 0) setLastRevisionChanges(ch);
    } else if (latestTurn.workflow === "revision") {
      // Single-file: extract bundle_target from input
      const target = (latestTurn.input?.bundle_target as string | undefined);
      if (target) modifiedPaths.push(target);
    }

    // Also pick up MEMORY_WRITE events for manuscript.bundle_write
    for (const ev of stream.events) {
      if (ev.type === "MEMORY_WRITE" && (ev.data as Record<string, unknown>)?.kind === "manuscript.bundle_write") {
        const p = (ev.data as Record<string, unknown>)?.path as string | undefined;
        if (p && !modifiedPaths.includes(p)) modifiedPaths.push(p);
      }
    }

    if (modifiedPaths.length > 0) {
      setRecentlyModified(new Set(modifiedPaths));
      void queryClient.invalidateQueries({ queryKey: ["manuscript-tree", manuscriptId] });
      const timer = setTimeout(() => setRecentlyModified(new Set()), 30_000);
      return () => clearTimeout(timer);
    }
  }, [stream.status, turns.length]);

  // POST a new turn — handles both first turn (creates thread) and follow-ups.
  const send = useMutation({
    mutationFn: async (params: { query: string; mode: ChatMode }) => {
      // Build history from prior assistant replies so consult can keep
      // context. Each turn's "assistant message" is the analysis or
      // revised text from its result.
      const history: Array<{ role: "user" | "assistant"; content: string }> = [];
      for (const tr of turns) {
        if (tr.status !== "ok") continue;
        history.push({ role: "user", content: tr.query || "" });
        const r = (tr.result ?? {}) as Record<string, unknown>;
        const reply =
          (r.analysis as string | undefined) ||
          (r.plan as string | undefined) ||
          (r.revised as string | undefined) ||
          "";
        if (reply) history.push({ role: "assistant", content: reply });
      }

      // P18: clear modified-file highlights on new send
      setRecentlyModified(new Set());
      setLastRevisionChanges([]);

      // P16/P18: route to project workflows when in project mode or
      // batch multi-file revision (project-revision handles per-file writeback).
      const isMultiFileRevision = batchMode && checkedFiles.size > 1 && params.mode === "revision";
      const effectiveWorkflow = (projectMode || isMultiFileRevision)
        ? params.mode === "revision" ? "project-revision" : "project-consult"
        : params.mode;
      // Truncate query to 10000 chars (backend limit)
      const safeQuery = params.query.slice(0, 10000);
      const body = {
        workflow: effectiveWorkflow,
        query: safeQuery,
        input: {
          manuscript_id: manuscriptId,
          // project-revision gets bundle_tree from runner; single-file targets only for non-project
          ...(effectiveWorkflow === "project-revision" || effectiveWorkflow === "project-consult"
            ? {}
            : batchMode && checkedFiles.size > 1
              ? { bundle_targets: [...checkedFiles] }
              : targetPath
                ? { bundle_target: targetPath }
                : {}),
          ...(threadId ? { parent_task_id: threadId } : {}),
          ...(history.length > 0
            ? { history }
            : {}),
        },
      };
      return api<CreateTaskResponse>(`/api/tasks`, {
        method: "POST",
        json: body,
      });
    },
    onSuccess: (data) => {
      setPending("");
      if (batchMode) setCheckedFiles(new Set());
      // If we didn't have a thread yet, this task IS the thread root.
      if (!threadId) {
        handleSetThread(data.task_id);
      } else {
        void queryClient.invalidateQueries({ queryKey: ["task-children", threadId] });
      }
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t("chat.sendFailed")}: ${message}`);
    },
  });

  const canSend = !send.isPending && (
    projectMode || (batchMode ? checkedFiles.size > 0 : Boolean(targetPath))
  );

  // P15: Peer Review — auto-audit the whole project
  const sendPeerReview = useMutation({
    mutationFn: async () => {
      const body = {
        workflow: "peer-review",
        query: "Run a structured pre-submission peer review on the entire paper project.",
        input: {
          manuscript_id: manuscriptId,
          ...(threadId ? { parent_task_id: threadId } : {}),
        },
      };
      return api<CreateTaskResponse>(`/api/tasks`, {
        method: "POST",
        json: body,
      });
    },
    onSuccess: (data) => {
      if (!threadId) {
        handleSetThread(data.task_id);
      } else {
        void queryClient.invalidateQueries({ queryKey: ["task-children", threadId] });
      }
      toast.success(t("chat.peerReviewStarted") ?? "Peer review started");
    },
    onError: (err: unknown) => {
      const message = err instanceof Error ? err.message : String(err);
      toast.error(`${t("chat.sendFailed")}: ${message}`);
    },
  });

  // Bundle file list (already filtered to text-only on the picker; here
  // we keep all files so users can navigate via the tree, but selecting
  // a binary file is a no-op (file query disabled).
  //
  // NOTE: this useMemo MUST sit above the early-return branches below.
  // React's Rules of Hooks count by call order, and the picker / single-
  // layout branches return before reaching the workbench JSX — if this
  // hook lived under those branches, the bundle workbench render path
  // would have one more hook than the picker render path and React would
  // throw "Rendered fewer hooks than expected" on the very next render.
  const treeFiles = useMemo(
    () => (tree.data?.files ?? []).filter((f: ManuscriptFile) => f.is_text),
    [tree.data],
  );

  // Bundle picker (no target selected yet) — with batch-mode + project-mode support
  if (meta.data && meta.data.layout === "bundle" && !targetPath && !batchMode && !projectMode) {
    return (
      <ChatTargetPicker
        manuscript={meta.data}
        tree={tree.data}
        loading={tree.isLoading}
        onPick={handlePickTarget}
        onBatchPick={(paths) => {
          setBatchMode(true);
          setCheckedFiles(new Set(paths));
        }}
        onProjectMode={() => setProjectMode(true)}
        onBack={() => navigate("/workbench")}
      />
    );
  }

  // Single-layout manuscripts: no file picker. We pass the latest
  // version's content via input.text from the task creation side, but
  // for now we surface a friendly hint — single manuscripts are better
  // handled by /revision. This keeps PaperChat focused on bundle flows
  // (the user's actual ask).
  if (meta.data && meta.data.layout === "single") {
    return (
      <SingleLayoutHint manuscript={meta.data} onBack={() => navigate("/workbench")} />
    );
  }

  // ---- toolbar (always-visible bar at the top of the workbench) ----
  const toolbar = (
    <>
      <FileText className="h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />
      <span className="truncate text-xs font-medium">
        {meta.data?.title || t("chat.untitled")}
      </span>
      <span className="text-[var(--color-muted-foreground)]">·</span>
      <code className="truncate rounded bg-[var(--color-muted)] px-1 font-mono text-[10px]">
        {projectMode
          ? "entire project"
          : batchMode && checkedFiles.size > 0
            ? `${checkedFiles.size} files`
            : targetPath}
      </code>
      {/* P15: Peer Review — full-project audit */}
      <div className="ml-auto flex items-center gap-2">
        {projectMode ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setProjectMode(false)}
          >
            Exit project mode
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={sendPeerReview.isPending}
              onClick={() => {
                if (window.confirm(t("chat.peerReviewConfirm", { title: meta.data?.title || "" }) ?? "Audit the entire paper project? This may take a few minutes.")) {
                  sendPeerReview.mutate();
                }
              }}
              title={t("chat.peerReviewHint") ?? "Run a structured peer review on the whole project"}
            >
              {sendPeerReview.isPending ? (
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
              ) : (
                <ClipboardCheck className="mr-1 h-3 w-3" />
              )}
              {sendPeerReview.isPending ? "Reviewing…" : "Peer Review"}
            </Button>
          </>
        )}
        {batchMode ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => { setBatchMode(false); setCheckedFiles(new Set()); }}
          >
            Exit batch
          </Button>
        ) : (
          <Button type="button" variant="outline" size="sm" onClick={() => handlePickTarget("")}>
            {t("chat.changeTarget")}
          </Button>
        )}
        <Link
          to={`/revision?manuscript=${manuscriptId}${
            targetPath ? `&bundle_target=${encodeURIComponent(targetPath)}` : ""
          }`}
          className="text-xs text-[var(--color-primary)] hover:underline"
        >
          {t("chat.openRevisionStudio")} →
        </Link>
      </div>
    </>
  );

  // ---- left pane: conversations + file tree ----
  const leftPane = (
    <div className="flex h-full flex-col">
      {/* P18: Conversation list */}
      <ConversationList
        manuscriptId={manuscriptId}
        activeThreadId={threadId}
        onSelectThread={(tid) => {
          setThreadId(tid);
          updateUrl({ thread: tid });
        }}
        onNewThread={() => {
          setThreadId("");
          setTargetPath("");
          setProjectMode(false);
          setBatchMode(false);
          setCheckedFiles(new Set());
          updateUrl({ thread: "", target: "" });
        }}
      />
      <div className="flex-1 overflow-y-auto border-t py-1">
        <span className="text-[10px] text-[var(--color-muted-foreground)]">
          {projectMode
            ? "Project mode — entire paper"
            : batchMode && checkedFiles.size > 0
              ? `${checkedFiles.size} files selected`
              : batchMode
                ? "Select files to review"
                : "Single file mode"}
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => {
              setProjectMode(!projectMode);
              setBatchMode(false);
              setCheckedFiles(new Set());
            }}
            className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition ${
              projectMode
                ? "bg-[var(--color-success)] text-white"
                : "hover:bg-[var(--color-muted)]"
            }`}
            title="Chat with the entire paper project"
          >
            <FileText className="h-3 w-3" />
            Project
          </button>
          <button
            type="button"
            onClick={() => {
              setBatchMode(!batchMode);
              setProjectMode(false);
              setCheckedFiles(new Set());
            }}
            className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition ${
              batchMode
                ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                : "hover:bg-[var(--color-muted)]"
            }`}
          >
            <CheckSquare className="h-3 w-3" />
            Batch
          </button>
        </div>
      <BundleFileTree
        files={treeFiles}
        selected={batchMode ? null : (targetPath || null)}
        onSelect={batchMode ? () => {} : handlePickTarget}
        multiSelect={batchMode}
        checked={checkedFiles}
        onCheckChange={setCheckedFiles}
        recentlyModified={recentlyModified}
      />
      </div>
    </div>
  );

  // ---- center pane: read-only Monaco preview of the selected file ----
  const editorLanguage = targetPath.endsWith(".tex")
    ? "latex"
    : targetPath.endsWith(".md") || targetPath.endsWith(".markdown")
      ? "markdown"
      : targetPath.endsWith(".yaml") || targetPath.endsWith(".yml")
        ? "yaml"
        : targetPath.endsWith(".json")
          ? "json"
          : "plaintext";
  const centerPane = projectMode ? (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
      <FileText className="h-8 w-8 text-[var(--color-success)]" />
      <span className="text-sm font-medium">Project Mode</span>
      <p className="text-xs text-[var(--color-muted-foreground)]">
        The agent will read the entire paper project and answer your questions.
        Type your question in the chat panel → press Send.
      </p>
    </div>
  ) : !targetPath ? (
    <div className="flex flex-1 items-center justify-center p-6 text-sm text-[var(--color-muted-foreground)]">
      {t("bundle.selectFileHint")}
    </div>
  ) : file.isLoading ? (
    <div className="p-4">
      <Skeleton className="h-64 w-full" />
    </div>
  ) : file.isError ? (
    <div className="p-4 text-xs text-[var(--color-destructive)]">
      {(file.error as Error)?.message || "Failed to load file"}
    </div>
  ) : file.data ? (
    <EditableFilePreview
      manuscriptId={manuscriptId}
      targetPath={targetPath}
      content={file.data.content ?? ""}
      language={editorLanguage}
      monacoTheme={monacoTheme}
      isRecentlyModified={recentlyModified.has(targetPath)}
      revisionChange={lastRevisionChanges.find(c => c.path === targetPath)}
      onSaved={() => {
        void queryClient.invalidateQueries({ queryKey: ["manuscript-file", manuscriptId, targetPath] });
        void queryClient.invalidateQueries({ queryKey: ["manuscript-tree", manuscriptId] });
        setRecentlyModified(prev => { const next = new Set(prev); next.delete(targetPath); return next; });
        setLastRevisionChanges(prev => prev.filter(c => c.path !== targetPath));
      }}
    />
  ) : (
    <div className="p-6">
      <p className="text-xs italic text-[var(--color-muted-foreground)]">{t("chat.noPreview")}</p>
    </div>
  );

  // ---- right pane: chat thread + composer (unchanged behaviour) ----
  const rightPane = (
    <div className="flex h-full min-h-0 flex-col">
      <div className="shrink-0 border-b px-3 py-2">
        <div className="text-xs font-medium">{t("chat.conversation")}</div>
        <p className="text-[10px] text-[var(--color-muted-foreground)]">
          {turns.length === 0
            ? t("chat.startHint")
            : t("chat.turnsCount", { count: turns.length })}
        </p>
      </div>
      <div ref={threadRef} className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto p-3">
        {turns.length === 0 ? (
          <EmptyState
            title={t("chat.empty.title")}
            description={t("chat.empty.description")}
          />
        ) : (
          turns.map((task) => (
            <ChatTurn
              key={task.id}
              task={task}
              isStreaming={task.id === streamingId}
              stream={task.id === streamingId ? stream : null}
              monacoTheme={monacoTheme}
              onRewriteFromThis={(content) => {
                setMode("revision");
                setPending(
                  t("chat.applyRewritePrefill", { suggestion: content.slice(0, 200) }),
                );
                composerRef.current?.focus();
              }}
              onTaskResponded={() => {
                void queryClient.invalidateQueries({ queryKey: ["task-children", threadId] });
              }}
            />
          ))
        )}
      </div>
      <div className="shrink-0 border-t p-3">
        <div className="mb-2 flex items-center justify-between text-xs">
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setMode("consult")}
              className={`flex items-center gap-1 rounded px-2 py-1 transition ${
                mode === "consult"
                  ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                  : "hover:bg-[var(--color-muted)]"
              }`}
            >
              <MessageSquare className="h-3 w-3" /> {t("chat.modeConsult")}
            </button>
            <button
              type="button"
              onClick={() => setMode("revision")}
              className={`flex items-center gap-1 rounded px-2 py-1 transition ${
                mode === "revision"
                  ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                  : "hover:bg-[var(--color-muted)]"
              }`}
              title={projectMode ? "Revise the entire project" : "Revise the selected file"}
            >
              <Pencil className="h-3 w-3" /> {t("chat.modeRevise")}
            </button>
          </div>
          <span className="text-[10px] text-[var(--color-muted-foreground)]">
            {mode === "consult" ? t("chat.modeConsultHint") : t("chat.modeReviseHint")}
          </span>
        </div>
        <Textarea
          ref={composerRef}
          value={pending}
          onChange={(e) => setPending(e.target.value)}
          placeholder={
            projectMode
              ? "Ask anything about the entire paper…"
              : batchMode && checkedFiles.size > 0
                ? `Ask about ${checkedFiles.size} selected files…`
                : targetPath
                  ? t("chat.composerPlaceholder")
                  : t("chat.pickFileFirst")
          }
          rows={3}
          disabled={send.isPending || (!projectMode && !targetPath && !(batchMode && checkedFiles.size > 0))}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && canSend) {
              e.preventDefault();
              send.mutate({ query: pending.trim(), mode });
            }
          }}
          className="font-mono text-xs"
        />
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className={`text-[10px] ${pending.length > 10000 ? "text-[var(--color-destructive)] font-medium" : "text-[var(--color-muted-foreground)]"}`}>
            {pending.length > 10000 ? `⚠ ${pending.length}/10000 (will be truncated)` : `${pending.length}/10000`}
          </span>
          <span className="text-[10px] text-[var(--color-muted-foreground)]">⌘/Ctrl + Enter</span>
          <Button
            type="button"
            size="sm"
            disabled={!canSend}
            onClick={() => send.mutate({ query: pending.trim(), mode })}
          >
            {send.isPending ? (
              <>
                <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                {t("chat.sending")}
              </>
            ) : (
              <>
                <Send className="mr-1 h-3 w-3" />
                {mode === "consult" ? t("chat.ask") : t("chat.rewrite")}
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  );

  return (
    <WorkbenchShell
      toolbar={toolbar}
      left={leftPane}
      center={centerPane}
      right={rightPane}
      leftTitle="workbench.leftPane"
      centerTitle="workbench.centerPane"
      rightTitle="workbench.rightPane"
    />
  );
}

// ---------------------------------------------------------------------------
// One turn rendering — consult prose OR revision diff
// ---------------------------------------------------------------------------

interface ChatTurnProps {
  task: TaskRecord;
  isStreaming: boolean;
  stream: ReturnType<typeof useTaskStream> | null;
  monacoTheme: string;
  onRewriteFromThis: (suggestion: string) => void;
  onTaskResponded: () => void;
}

function ChatTurn({ task, isStreaming, stream, monacoTheme, onRewriteFromThis, onTaskResponded }: ChatTurnProps) {
  const { t } = useTranslation();
  const r = (task.result ?? {}) as Record<string, unknown>;
  const analysis = (r.analysis as string | undefined) ?? "";
  const revised = (r.revised as string | undefined) ?? "";
  const original = (r.original as string | undefined) ?? "";
  const suggestions = (r.suggestions as string[] | undefined) ?? [];
  const suspectCitations = (r.suspect_citations as Array<{key: string; reason: string; suggestion: string}> | undefined) ?? [];

  // P15/P16/P18: workflow-specific result shapes
  const isPeerReview = task.workflow === "peer-review" && task.status === "ok";
  const isProjectConsult = task.workflow === "project-consult" && task.status === "ok";
  const isProjectRevision = task.workflow === "project-revision" && task.status === "ok";
  const filesRead = (r.files_read as string[] | undefined) ?? [];
  const explorationLog = (r.exploration_log as Array<Record<string, unknown>> | undefined) ?? [];
  const changes = (r.changes as Array<{path: string; before: string; after: string; summary: string}> | undefined) ?? [];
  const plan = (r.plan as string) ?? "";
  const filesModified = (r.files_modified as string[] | undefined) ?? [];
  const changeLog = (r.change_log as Array<{comment_id: string; decision: string; action: string; changed: boolean}> | undefined) ?? [];
  const commentsAddressed = (r.comments_addressed as string[] | undefined) ?? [];
  const commentsOpen = (r.comments_open as string[] | undefined) ?? [];
  const researched = (r.researched as string[] | undefined) ?? [];
  const researchFailures = (r.research_failures as string[] | undefined) ?? [];

  const [copied, setCopied] = useState<"user" | "agent" | null>(null);
  const [appliedChanges, setAppliedChanges] = useState<Set<string>>(new Set());
  const copyText = (what: "user" | "agent", text: string) => {
    navigator.clipboard.writeText(text).catch(() => {});
    setCopied(what);
    setTimeout(() => setCopied(null), 1500);
  };
  const applyChange = (path: string) => {
    setAppliedChanges(prev => { const next = new Set(prev); next.add(path); return next; });
    toast.success(`Applied ${path}`);
  };

  return (
    <div className="space-y-2">
      {/* User message bubble */}
      <div className="flex justify-end">
        <div className="max-w-[80%] rounded-lg bg-[var(--color-primary)] px-3 py-2 text-[var(--color-primary-foreground)]">
          <div className="mb-1 flex items-center gap-1 text-[10px] opacity-80">
            <User2 className="h-3 w-3" />
            <span>{t("chat.user")}</span>
            <span>·</span>
            <Badge variant="outline" className="bg-transparent text-[9px] font-mono">
              {task.workflow}
            </Badge>
            <button
              type="button"
              className="ml-auto opacity-40 hover:opacity-100 transition-opacity"
              onClick={() => copyText("user", task.query || "")}
              title="Copy question"
            >
              {copied === "user" ? <ClipboardCheck className="h-3 w-3 text-[var(--color-success)]" /> : <Copy className="h-3 w-3" />}
            </button>
          </div>
          <div className="whitespace-pre-wrap text-xs">{task.query || "(empty)"}</div>
        </div>
      </div>

      {/* Agent message bubble */}
      <div className="flex justify-start">
        <div className="max-w-[90%] space-y-2 rounded-lg bg-[var(--color-muted)]/60 px-3 py-2">
          <div className="flex items-center gap-1 text-[10px] text-[var(--color-muted-foreground)]">
            <Bot className="h-3 w-3" />
            <span>{t("chat.agent")}</span>
            <span>·</span>
            <StatusPill status={task.status} />
            <span>·</span>
            <span>{format(new Date(task.created_at), "HH:mm:ss")}</span>
            <button
              type="button"
              className="ml-auto mr-1 opacity-40 hover:opacity-100 transition-opacity"
              onClick={() => copyText("agent", revised || analysis || plan || "")}
              title="Copy response"
            >
              {copied === "agent" ? <ClipboardCheck className="h-3 w-3 text-[var(--color-success)]" /> : <Copy className="h-3 w-3" />}
            </button>
            <Link
              to={`/tasks/${task.id}`}
              className="text-[10px] text-[var(--color-primary)] hover:underline"
            >
              {t("chat.openDetail")} →
            </Link>
          </div>

          {/* Live stream — accumulated LLM output in real-time */}
          {isStreaming && stream && (
            <StreamingPreview events={stream.events} />
          )}

          {/* Error display */}
          {task.error && <TaskError error={task.error} density="compact" />}

          {/* Agent question — task is waiting for user input */}
          {task.status === "waiting" && stream?.awaitingInput && (
            <AgentQuestion
              taskId={task.id}
              prompt={stream.awaitingInput.prompt}
              checkpoint={stream.awaitingInput.checkpoint}
              promptData={stream.awaitingInput.prompt_data}
              monacoTheme={monacoTheme}
              onResponded={() => onTaskResponded()}
            />
          )}

          {/* P19: Auto-research results */}
          {(researched.length > 0 || researchFailures.length > 0) && (
            <div className="rounded border border-[var(--color-primary)]/30 bg-[var(--color-primary)]/5 p-2 text-[10px]">
              <div className="mb-1 font-medium">Citation Research Results</div>
              {researched.length > 0 && (
                <div className="text-[var(--color-success)]">
                  Researched & added to memory: {researched.length} papers
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {researched.map((id) => (
                      <Badge key={id} variant="outline" className="font-mono text-[9px]">{id.slice(0, 12)}</Badge>
                    ))}
                  </div>
                </div>
              )}
              {researchFailures.length > 0 && (
                <div className="mt-1 text-[var(--color-warning)]">
                  Not found: {researchFailures.length} papers
                  <div className="mt-0.5 flex flex-wrap gap-1">
                    {researchFailures.map((k) => (
                      <Badge key={k} variant="outline" className="font-mono text-[9px]">{k}</Badge>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* P14.1: suspect citations warning */}
          {suspectCitations.length > 0 && (
            <div className="rounded border border-[var(--color-warning)]/40 bg-[var(--color-warning)]/10 p-2">
              <div className="mb-1 flex items-center gap-1 text-[10px] font-medium text-[var(--color-warning)]">
                <AlertTriangle className="h-3 w-3" />
                {t("chat.suspectCitations", { count: suspectCitations.length })}
                <span className="text-[var(--color-muted-foreground)]">(auto-fix will research these on next follow-up)</span>
              </div>
              <ul className="space-y-1 text-[10px]">
                {suspectCitations.slice(0, 5).map((s, i) => (
                  <li key={i} className="text-[var(--color-muted-foreground)]">
                    <code className="rounded bg-[var(--color-muted)] px-1 font-mono">{s.key}</code>
                    {" "}— {s.reason}
                  </li>
                ))}
                {suspectCitations.length > 5 && (
                  <li className="text-[var(--color-muted-foreground)]">
                    …and {suspectCitations.length - 5} more
                  </li>
                )}
              </ul>
            </div>
          )}

          {/* P15: Peer Review result — structured report */}
          {isPeerReview && (
            <PeerReviewResult result={r} />
          )}

          {/* P18: Project Revision — file changes with diffs */}
          {isProjectRevision && (
            <div className="space-y-2 text-xs">
              {changes.length > 0 ? (
                <>
              <div className="flex items-center gap-2">
                <Badge variant="primary">{changes.length} files modified</Badge>
                {plan && <span className="text-[var(--color-muted-foreground)]">{plan}</span>}
              </div>
              {changes.map((ch, i) => {
                const applied = appliedChanges.has(ch.path);
                const isFirstUnapplied = !applied && !changes.slice(0, i).some(c => !appliedChanges.has(c.path));
                return (
                <details key={i} className="rounded border border-[var(--color-border)]" open={isFirstUnapplied}>
                  <summary className="cursor-pointer p-2 font-mono text-[11px] hover:bg-[var(--color-muted)]">
                    {ch.path} — {ch.summary || "modified"}
                  </summary>
                  <div className="border-t p-2">
                    <DiffEditor
                      height="200px"
                      original={ch.before || ""}
                      modified={ch.after || ""}
                      language={ch.path.endsWith(".tex") ? "latex" : "markdown"}
                      theme={monacoTheme}
                      options={{
                        readOnly: true,
                        renderSideBySide: false,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 11,
                        wordWrap: "on",
                      }}
                    />
                    <div className="mt-2 flex items-center justify-end">
                      {applied ? (
                        <span className="inline-flex items-center gap-1 text-[10px] text-[var(--color-success)]">
                          <ClipboardCheck className="h-3 w-3" />
                          Applied
                        </span>
                      ) : (
                        <Button size="sm" className="h-6 text-[10px]" onClick={() => applyChange(ch.path)}>
                          Apply changes
                        </Button>
                      )}
                    </div>
                  </div>
                </details>
              )})}
                </>
              ) : (
                <div className="rounded border border-[var(--color-muted)] p-2 text-[10px] text-[var(--color-muted-foreground)]">
                  {plan ? <div>Plan: {plan}</div> : <div>No changes were needed.</div>}
                  {(r.verified_citations as string[] | undefined)?.length ? (
                    <div className="mt-1 text-[var(--color-success)]">
                      Verified {String((r.verified_citations as string[]).length)} citations
                    </div>
                  ) : null}
                  {(r.suspect_citations as Array<{key: string}> | undefined)?.length ? (
                    <div className="mt-1 text-[var(--color-warning)]">
                      {String((r.suspect_citations as Array<{key: string}>).length)} suspect citations remain
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          )}

          {/* P16: Project Consult — file exploration summary */}
          {isProjectConsult && filesRead.length > 0 && (
            <div className="rounded border border-[var(--color-border)] p-2 text-[10px]">
              <div className="mb-1 font-medium">Files explored ({filesRead.length})</div>
              <div className="flex flex-wrap gap-1">
                {filesRead.map((f) => (
                  <Badge key={f} variant="outline" className="font-mono text-[9px]">{f}</Badge>
                ))}
              </div>
              {explorationLog.length > 0 && (
                <div className="mt-1 text-[var(--color-muted-foreground)]">
                  {explorationLog.length} rounds of exploration
                </div>
              )}
            </div>
          )}

          {/* Citation Research results */}
          {task.workflow === "citation-research" && task.status === "ok" && (
            <CitationResearchResult result={r} />
          )}

          {/* Research results — papers found via arxiv/Google Scholar search */}
          {task.workflow === "research" && task.status === "ok" && (
            <ResearchResult result={r} />
          )}

          {/* Consult prose */}
          {analysis && (
            <div className="prose prose-sm max-w-none">
              <pre className="whitespace-pre-wrap rounded bg-[var(--color-background)] p-2 font-mono text-[11px] leading-relaxed text-[var(--color-foreground)]">
                {analysis}
              </pre>
            </div>
          )}

          {/* Revision: change_log summary */}
          {changeLog.length > 0 && task.workflow === "revision" && task.status === "ok" && (
            <div className="space-y-1 rounded border border-[var(--color-border)] bg-[var(--color-background)] p-2 text-[10px]">
              <div className="flex items-center gap-2 font-medium">
                <span>Revision Plan</span>
                <Badge variant="success" className="text-[9px]">{commentsAddressed.length} addressed</Badge>
                {commentsOpen.length > 0 && <Badge variant="outline" className="text-[9px]">{commentsOpen.length} deferred</Badge>}
              </div>
              <ul className="space-y-1">
                {changeLog.map((entry, i) => (
                  <li key={i} className="flex items-start gap-2">
                    <span className={`mt-0.5 shrink-0 rounded px-1 font-mono text-[8px] ${
                      entry.decision === "accept" ? "bg-[var(--color-success)]/20 text-[var(--color-success)]" :
                      entry.decision === "partial" ? "bg-[var(--color-warning)]/20 text-[var(--color-warning)]" :
                      "bg-[var(--color-muted)] text-[var(--color-muted-foreground)]"
                    }`}>
                      {entry.decision}
                    </span>
                    <span className="text-[var(--color-muted-foreground)]">{entry.action}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {/* Revision diff */}
          {revised && original && task.workflow === "revision" && (
            <div className="space-y-1">
              <div className="text-[10px] text-[var(--color-muted-foreground)]">
                {t("chat.diffLabel")}
              </div>
              <div className="h-[320px] w-full overflow-hidden rounded border border-[var(--color-border)]">
                <DiffEditor
                  original={original}
                  modified={revised}
                  language={
                    (task.input?.bundle_target as string | undefined)?.endsWith(".tex")
                      ? "latex"
                      : "markdown"
                  }
                  theme={monacoTheme}
                  options={{
                    readOnly: true,
                    renderSideBySide: false,
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    fontSize: 11,
                    wordWrap: "on",
                  }}
                />
              </div>
            </div>
          )}

          {/* "Apply this suggestion" — clickable fix-actions */}
          {suggestions.length > 0 && task.status === "ok" && task.workflow === "consult" && (
            <div className="space-y-1 pt-1">
              <div className="text-[10px] font-medium text-[var(--color-muted-foreground)]">
                点击下方建议，按此修改：
              </div>
              <div className="flex flex-wrap gap-1">
                {suggestions.map((s, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => onRewriteFromThis(s)}
                    title={s}
                    className="inline-flex items-center gap-1 rounded bg-[var(--color-background)] px-2 py-0.5 text-[10px] hover:bg-[var(--color-primary)]/10 hover:text-[var(--color-primary)] transition-colors"
                  >
                    <Pencil className="h-3 w-3" />
                    <span className="max-w-[320px] truncate">{s}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {analysis && task.workflow === "consult" && task.status === "ok" && (
            <div className="pt-1">
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onRewriteFromThis(analysis)}
              >
                <Pencil className="mr-1 h-3 w-3" />
                {t("chat.rewriteBasedOnThis")}
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Helper pages
// ---------------------------------------------------------------------------

function ChatTargetPicker({
  manuscript,
  tree,
  loading,
  onPick,
  onBatchPick,
  onProjectMode,
  onBack,
}: {
  manuscript: Manuscript;
  tree: BundleManifest | undefined;
  loading: boolean;
  onPick: (path: string) => void;
  onBatchPick?: (paths: string[]) => void;
  onProjectMode?: () => void;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  const files = (tree?.files ?? []).filter((f: ManuscriptFile) => f.is_text);

  // P14.2: local multi-select state for batch review picker
  const [batchChecked, setBatchChecked] = useState<Set<string>>(new Set());
  const [batchModeLocal, setBatchModeLocal] = useState(false);

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("chat.pickTarget")}
        description={manuscript.title || t("chat.untitled")}
        actions={
          <Button type="button" variant="outline" size="sm" onClick={onBack}>
            {t("chat.back")}
          </Button>
        }
      />
      <Card>
        <CardContent className="p-0">
          {loading ? (
            <div className="p-4">
              <Skeleton className="h-32 w-full" />
            </div>
          ) : files.length === 0 ? (
            <div className="p-6">
              <EmptyState
                title={t("chat.noFiles")}
                description={t("chat.noFilesHint")}
              />
            </div>
          ) : (
            <div className="py-2">
              <div className="flex items-center justify-between px-3 pb-1">
                <span className="text-[10px] text-[var(--color-muted-foreground)]">
                  {batchModeLocal
                    ? batchChecked.size > 0
                      ? `${batchChecked.size} files selected`
                      : "Check files to batch-review"
                    : t("chat.pickTargetHint")}
                </span>
                <div className="flex items-center gap-1">
                  {onProjectMode && (
                    <button
                      type="button"
                      onClick={onProjectMode}
                      className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] text-[var(--color-success)] hover:bg-[var(--color-muted)]"
                    >
                      <FileText className="h-3 w-3" />
                      Project
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => {
                      setBatchModeLocal(!batchModeLocal);
                      setBatchChecked(new Set());
                    }}
                    className={`flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition ${
                      batchModeLocal
                        ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                        : "hover:bg-[var(--color-muted)]"
                    }`}
                  >
                    <CheckSquare className="h-3 w-3" />
                    Batch
                  </button>
                  {batchModeLocal && batchChecked.size > 0 && onBatchPick && (
                    <Button
                      type="button"
                      size="sm"
                      onClick={() => onBatchPick([...batchChecked])}
                    >
                      Review {batchChecked.size} files →
                    </Button>
                  )}
                </div>
              </div>
              <BundleFileTree
                files={files}
                selected={batchModeLocal ? null : null}
                onSelect={batchModeLocal ? () => {} : onPick}
                multiSelect={batchModeLocal}
                checked={batchChecked}
                onCheckChange={setBatchChecked}
              />
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function SingleLayoutHint({
  manuscript,
  onBack,
}: {
  manuscript: Manuscript;
  onBack: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="space-y-4">
      <PageHeader
        title={manuscript.title || t("chat.untitled")}
        actions={
          <Button type="button" variant="outline" size="sm" onClick={onBack}>
            {t("chat.back")}
          </Button>
        }
      />
      <Card>
        <CardContent>
          <EmptyState
            title={t("chat.singleLayoutTitle")}
            description={t("chat.singleLayoutHint")}
            action={
              <Link
                to={`/revision?manuscript=${manuscript.id}`}
                className="text-sm text-[var(--color-primary)] hover:underline"
              >
                {t("chat.openRevisionStudio")} →
              </Link>
            }
          />
        </CardContent>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// P15: Peer Review structured result display
// ---------------------------------------------------------------------------

function PeerReviewResult({ result }: { result: Record<string, unknown> }) {
  const { t } = useTranslation();
  const preliminary = (result.preliminary as Record<string, string> | undefined) ?? {};
  const sections = (result.section_review as Array<Record<string, string>> | undefined) ?? [];
  const major = (result.major_issues as Array<Record<string, string>> | undefined) ?? [];
  const minor = (result.minor_issues as Array<Record<string, string>> | undefined) ?? [];
  const bias = (result.bias_audit as Array<Record<string, string>> | undefined) ?? [];
  const fallacy = (result.fallacy_audit as Array<Record<string, string>> | undefined) ?? [];
  const rating = result.rating as number | null | undefined;
  const verdict = (result.verdict as string) ?? "";
  const advice = (result.strategic_advice as Record<string, string[]> | undefined) ?? {};

  const scoreIcon = (score: string) => {
    if (score === "✓" || score === "✅") return <span className="text-[var(--color-success)]">{score}</span>;
    if (score === "⚠" || score === "⚠️") return <span className="text-[var(--color-warning)]">{score}</span>;
    if (score === "❌") return <span className="text-[var(--color-destructive)]">{score}</span>;
    return score;
  };

  const ratingColor = rating !== null && rating !== undefined
    ? rating >= 8 ? "text-[var(--color-success)]"
    : rating >= 5 ? "text-[var(--color-warning)]"
    : "text-[var(--color-destructive)]"
    : "";

  return (
    <div className="space-y-3 text-xs">
      {/* Header: rating + verdict */}
      <div className="flex items-center gap-3 rounded border border-[var(--color-border)] p-2">
        <div className="text-lg font-bold">
          {(rating !== null && rating !== undefined) ? (
            <span className={ratingColor}>{rating}/10</span>
          ) : "—"}
        </div>
        <div>
          <span className="font-medium">{verdict}</span>
          {preliminary.elevator_pitch && (
            <p className="mt-0.5 text-[var(--color-muted-foreground)]">{preliminary.elevator_pitch}</p>
          )}
        </div>
      </div>

      {/* Section scores */}
      {sections.length > 0 && (
        <div>
          <div className="mb-1 font-medium">Section-by-Section</div>
          <div className="space-y-0.5 rounded border border-[var(--color-border)] p-2">
            {sections.map((s, i) => (
              <div key={i} className="flex items-start gap-2">
                <span className="w-5 shrink-0">{scoreIcon(s.score ?? "")}</span>
                <span className="font-mono text-[10px] w-24 shrink-0">{s.section}</span>
                <span className="text-[var(--color-muted-foreground)]">{s.notes}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Major issues */}
      {major.length > 0 && (
        <div>
          <div className="mb-1 font-medium text-[var(--color-destructive)]">Major Issues ({major.length})</div>
          <ol className="space-y-2">
            {major.slice(0, 8).map((m, i) => (
              <li key={i} className="rounded border border-[var(--color-border)] p-2">
                <div className="font-mono text-[10px] text-[var(--color-muted-foreground)]">{m.location}</div>
                <div className="mt-0.5">{m.finding}</div>
                {m.fix && (
                  <div className="mt-1 text-[var(--color-primary)]">Fix: {m.fix}</div>
                )}
              </li>
            ))}
          </ol>
        </div>
      )}

      {/* Minor issues */}
      {minor.length > 0 && (
        <div>
          <div className="mb-1 font-medium text-[var(--color-warning)]">Minor Issues ({minor.length})</div>
          <ul className="space-y-1">
            {minor.slice(0, 6).map((m, i) => (
              <li key={i} className="text-[var(--color-muted-foreground)]">
                <span className="font-mono text-[10px]">{m.location}</span>: {m.finding}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Bias & Fallacy audit */}
      {(bias.length > 0 || fallacy.length > 0) && (
        <div className="rounded border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-2">
          <div className="mb-1 font-medium">Bias & Fallacy Audit</div>
          {bias.map((b, i) => (
            <div key={`b-${i}`} className="mt-1 flex items-start gap-2">
              <Badge variant="outline" className="shrink-0 text-[9px]">{b.type}</Badge>
              <span>{b.finding}</span>
            </div>
          ))}
          {fallacy.map((f, i) => (
            <div key={`f-${i}`} className="mt-1 flex items-start gap-2">
              <Badge variant="outline" className="shrink-0 text-[9px]">{f.type}</Badge>
              <span>{f.finding}</span>
            </div>
          ))}
        </div>
      )}

      {/* Strategic advice */}
      {Object.keys(advice).length > 0 && (
        <div>
          <div className="mb-1 font-medium">Strategic Advice</div>
          {advice.p1 && advice.p1.length > 0 && (
            <div className="mt-1">
              <span className="text-[var(--color-destructive)] font-medium">P1 (Must fix):</span>
              <ul className="list-disc pl-4 text-[var(--color-muted-foreground)]">
                {advice.p1.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {advice.p2 && advice.p2.length > 0 && (
            <div className="mt-1">
              <span className="text-[var(--color-warning)] font-medium">P2 (Should fix):</span>
              <ul className="list-disc pl-4 text-[var(--color-muted-foreground)]">
                {advice.p2.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
          {advice.p3 && advice.p3.length > 0 && (
            <div className="mt-1">
              <span className="text-[var(--color-muted-foreground)] font-medium">P3 (Nice to fix):</span>
              <ul className="list-disc pl-4 text-[var(--color-muted-foreground)]">
                {advice.p3.map((a, i) => <li key={i}>{a}</li>)}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// P18: Streaming preview — real-time LLM output
// ---------------------------------------------------------------------------

function StreamingPreview({ events }: { events: Array<{ type: string; data: Record<string, unknown> }> }) {
  const { t } = useTranslation();
  const [displayText, setDisplayText] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let text = "";
    for (const e of events) {
      if (e.type === "task.progress" && e.data?.stage === "llm_stream" && typeof e.data?.delta === "string") {
        text += e.data.delta;
      }
    }
    setDisplayText(text);
  }, [events]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [displayText]);

  if (!displayText) {
    const lastEvent = events[events.length - 1];
    return (
      <div className="rounded border border-dashed border-[var(--color-border)] p-2">
        <div className="mb-1 flex items-center gap-1 text-[10px] text-[var(--color-muted-foreground)]">
          <Loader2 className="h-3 w-3 animate-spin" />
          {lastEvent?.type === "task.progress"
            ? lastEvent.data?.action === "plan"
              ? `Agent selecting files…`
              : `Agent reading files…`
            : t("chat.thinking")}
        </div>
      </div>
    );
  }

  return (
    <div className="rounded border border-[var(--color-primary)]/30 bg-[var(--color-background)] p-2">
      <div className="mb-1 flex items-center gap-1 text-[10px] text-[var(--color-primary)]">
        <Loader2 className="h-3 w-3 animate-spin" />
        Generating…
      </div>
      <pre className="max-h-80 overflow-y-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-[var(--color-foreground)]">
        {displayText}
      </pre>
      <div ref={endRef} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// P18: Conversation list — like Cursor's session management
// ---------------------------------------------------------------------------

function ConversationList({
  manuscriptId,
  activeThreadId,
  onSelectThread,
  onNewThread,
}: {
  manuscriptId: string;
  activeThreadId: string;
  onSelectThread: (threadId: string) => void;
  onNewThread: () => void;
}) {
  const { t } = useTranslation();

  const threadsQuery = useQuery({
    queryKey: ["threads", manuscriptId],
    queryFn: async () => {
      const data = await api<TaskListResponse>(
        `/api/tasks?manuscript_id=${encodeURIComponent(manuscriptId)}&limit=50`
      );
      // Root tasks (threads) are those without parent_task_id
      return data.items.filter(
        (t) => !t.input || !t.input.parent_task_id
      );
    },
    enabled: Boolean(manuscriptId),
    refetchInterval: 10_000,
  });

  const threads = threadsQuery.data ?? [];

  return (
    <div className="shrink-0 border-b">
      <div className="flex items-center justify-between px-2 py-1.5">
        <span className="text-[10px] font-medium text-[var(--color-muted-foreground)]">
          Conversations
        </span>
        <button
          type="button"
          onClick={onNewThread}
          className="rounded p-0.5 text-[var(--color-muted-foreground)] hover:bg-[var(--color-muted)] hover:text-[var(--color-foreground)]"
          title="New conversation"
        >
          <PlusCircle className="h-3.5 w-3.5" />
        </button>
      </div>
      {threads.length > 0 ? (
        <div className="max-h-40 overflow-y-auto">
          {threads.map((thread) => (
            <button
              key={thread.id}
              type="button"
              onClick={() => onSelectThread(thread.id)}
              className={`w-full truncate px-2 py-1 text-left text-[10px] transition ${
                thread.id === activeThreadId
                  ? "bg-[var(--color-accent)] font-medium"
                  : "hover:bg-[var(--color-muted)]"
              }`}
            >
              <div className="truncate">{thread.query || "New conversation"}</div>
              <div className="flex items-center gap-1 text-[9px] text-[var(--color-muted-foreground)]">
                <span>{thread.workflow}</span>
                <span>·</span>
                <span>{format(new Date(thread.created_at), "MM-dd HH:mm")}</span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <p className="px-2 pb-1 text-[9px] text-[var(--color-muted-foreground)]">
          {threadsQuery.isLoading ? "Loading…" : "No conversations yet"}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Research result — papers found via arxiv/Google Scholar search
// ---------------------------------------------------------------------------

function ResearchResult({ result }: { result: Record<string, unknown> }) {
  const count = (result.count as number) ?? 0;
  const papers = (result.papers as Array<{paper_id: string; title: string; authors: string[]; year: number | null}>) ?? [];
  const query = (result.query as string) ?? "";

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2 font-medium">
        <FileText className="h-4 w-4 text-[var(--color-primary)]" />
        <span>Research Results</span>
        <Badge variant="primary">{count} papers</Badge>
      </div>
      {query && <div className="text-[10px] text-[var(--color-muted-foreground)]">Query: {query}</div>}
      {papers.length > 0 ? (
        <div className="max-h-80 space-y-1 overflow-y-auto rounded border border-[var(--color-border)] p-2">
          {papers.map((p, i) => (
            <div key={p.paper_id || i} className="flex items-start gap-2 border-b border-[var(--color-border)] py-1 text-[10px] last:border-b-0">
              <span className="shrink-0 font-mono text-[var(--color-muted-foreground)]">{i + 1}.</span>
              <div className="min-w-0">
                <div className="truncate font-medium">{p.title || "(untitled)"}</div>
                <div className="text-[var(--color-muted-foreground)]">
                  {(p.authors || []).slice(0, 3).join(", ")}{(p.authors || []).length > 3 ? " et al." : ""}
                  {p.year ? ` (${p.year})` : ""}
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="text-[var(--color-muted-foreground)]">No papers found.</div>
      )}
    </div>
  );
}

// Citation Research result — found / not_found / low_confidence lists
// ---------------------------------------------------------------------------

function CitationResearchResult({ result }: { result: Record<string, unknown> }) {
  const found = (result.found as Array<{paper_id: string; title: string; confidence: string; source: string}> | undefined) ?? [];
  const notFound = (result.not_found as Array<{index: number; title: string; reason: string}> | undefined) ?? [];
  const lowConfidence = (result.low_confidence as Array<{paper_id: string; title: string; matched_title: string; source: string}> | undefined) ?? [];
  const totalRefs = (result.total_refs as number) ?? 0;
  const paperTitle = (result.paper_title as string) ?? "";

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2 font-medium">
        <FileText className="h-4 w-4 text-[var(--color-primary)]" />
        <span>Citation Research Results</span>
        <Badge variant="primary">{totalRefs} refs total</Badge>
      </div>
      {paperTitle && <div className="text-[10px] text-[var(--color-muted-foreground)]">Paper: {paperTitle}</div>}

      {/* Found */}
      {found.length > 0 && (
        <div className="rounded border border-[var(--color-success)]/30 bg-[var(--color-success)]/5 p-2">
          <div className="mb-1 font-medium text-[var(--color-success)]">Found {found.length} papers</div>
          <ul className="space-y-1">
            {found.map((p) => (
              <li key={p.paper_id} className="flex items-center gap-2 text-[10px]">
                <Badge variant="outline" className="font-mono text-[8px]">{p.confidence}</Badge>
                <span className="truncate">{p.title}</span>
                <span className="shrink-0 text-[var(--color-muted-foreground)]">{p.source}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Low confidence */}
      {lowConfidence.length > 0 && (
        <div className="rounded border border-[var(--color-warning)]/30 bg-[var(--color-warning)]/5 p-2">
          <div className="mb-1 font-medium text-[var(--color-warning)]">Low confidence matches ({lowConfidence.length})</div>
          <ul className="space-y-1">
            {lowConfidence.map((p, i) => (
              <li key={i} className="text-[10px]">
                <span className="text-[var(--color-muted-foreground)]">Matched: </span>
                <span className="truncate">{p.matched_title}</span>
                <br />
                <span className="text-[var(--color-muted-foreground)]">Original: </span>
                <span className="truncate">{p.title}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Not found */}
      {notFound.length > 0 && (
        <details className="rounded border border-[var(--color-muted)] p-2">
          <summary className="cursor-pointer text-[var(--color-muted-foreground)]">Not found ({notFound.length})</summary>
          <ul className="mt-1 space-y-0.5">
            {notFound.map((r) => (
              <li key={r.index} className="text-[10px] text-[var(--color-muted-foreground)]">
                [{r.index}] {r.title || "(no title)"} — {r.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

// P18: Editable file preview — edit + save in the workbench center pane
// ---------------------------------------------------------------------------

function EditableFilePreview({
  manuscriptId,
  targetPath,
  content,
  language,
  monacoTheme,
  isRecentlyModified,
  revisionChange,
  onSaved,
}: {
  manuscriptId: string;
  targetPath: string;
  content: string;
  language: string;
  monacoTheme: string;
  isRecentlyModified?: boolean;
  revisionChange?: { path: string; before: string; after: string } | undefined;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const containerRef = useRef<HTMLDivElement>(null);
  const [draft, setDraft] = useState(content);
  const [editorHeight, setEditorHeight] = useState(400);
  const [showDiff, setShowDiff] = useState(false);
  const initialRef = useRef(content);

  useEffect(() => {
    setDraft(content);
    initialRef.current = content;
  }, [content, targetPath]);

  // Measure available height, capped to viewport
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => {
      const rect = el.getBoundingClientRect();
      const maxH = window.innerHeight - rect.top - 12; // leave bottom margin
      const h = Math.min(rect.height, maxH);
      if (h > 100) setEditorHeight(h);
    };
    measure();
    const obs = new ResizeObserver(measure);
    window.addEventListener("resize", measure);
    obs.observe(el);
    return () => {
      obs.disconnect();
      window.removeEventListener("resize", measure);
    };
  }, []);

  const dirty = draft !== initialRef.current;

  const saveMut = useMutation({
    mutationFn: () =>
      manuscriptsApi.writeTextFile(manuscriptId, targetPath, { content: draft }),
    onSuccess: () => {
      initialRef.current = draft;
      onSaved();
      toast.success(t("bundle.saved"));
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if ((e.ctrlKey || e.metaKey) && e.key === "s") {
      e.preventDefault();
      if (dirty) saveMut.mutate();
    }
  };

  return (
    <div ref={containerRef} className="flex min-h-0 flex-1 flex-col" onKeyDown={handleKeyDown}>
      <div className="flex shrink-0 items-center justify-between border-b px-3 py-1">
        <span className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
          {targetPath}
        </span>
        <Button
          size="sm"
          disabled={!dirty || saveMut.isPending}
          onClick={() => saveMut.mutate()}
          className="h-6 text-[10px]"
        >
          {saveMut.isPending ? (
            <Loader2 className="mr-1 h-3 w-3 animate-spin" />
          ) : (
            <Save className="mr-1 h-3 w-3" />
          )}
          {dirty ? "Save (Ctrl+S)" : "Saved"}
        </Button>
      </div>
      {/* Revision change banner */}
      {isRecentlyModified && revisionChange && (
        <div className="shrink-0 flex items-center gap-2 border-b bg-[var(--color-primary)]/8 px-3 py-1.5 text-[11px]">
          <Pencil className="h-3 w-3 text-[var(--color-primary)]" />
          <span className="text-[var(--color-primary)] font-medium">This file was modified by revision</span>
          <div className="ml-auto flex items-center gap-1">
            <Button
              size="sm"
              variant="outline"
              className="h-5 text-[10px]"
              onClick={() => setShowDiff(!showDiff)}
            >
              {showDiff ? "Hide diff" : "View diff"}
            </Button>
            <Button
              size="sm"
              className="h-5 text-[10px]"
              onClick={() => { onSaved(); setShowDiff(false); }}
            >
              Keep changes
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="h-5 text-[10px]"
              onClick={() => {
                setDraft(revisionChange.before);
                initialRef.current = revisionChange.before;
                setShowDiff(false);
              }}
            >
              Revert
            </Button>
          </div>
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-hidden">
        {showDiff && revisionChange ? (
          <DiffEditor
            height={Math.max(200, editorHeight - 56)}
            original={revisionChange.before || ""}
            modified={draft}
            language={language}
            theme={monacoTheme}
            options={{
              readOnly: true,
              renderSideBySide: false,
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              fontSize: 12,
              wordWrap: "on",
            }}
          />
        ) : (
          <Editor
            height={Math.max(200, editorHeight - 28)}
            value={draft}
            language={language}
            onChange={(v) => setDraft(v ?? "")}
            theme={monacoTheme}
            loading={<Skeleton className="h-64 w-full" />}
            options={{
              minimap: { enabled: false },
              fontSize: 12,
              wordWrap: "on",
              scrollBeyondLastLine: false,
            }}
          />
        )}
      </div>
    </div>
  );
}
