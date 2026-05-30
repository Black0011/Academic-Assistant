/**
 * UnifiedWorkbenchPage — 学术界的 Cursor.
 *
 * LEFT (240px): manuscripts or file-tree (top) + conversations (bottom)
 * MAIN (flex-1): FilePreviewPanel (collapsible, above) + Chat (below)
 *
 * Agent decides what to do — no forced workflow routing.
 * File selection = context. Query + skills = intent.
 */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  BookOpenText,
  CheckSquare,
  ChevronLeft,
  CheckCircle,
  FileText,
  FolderOpen,
  Layers,
  LayoutPanelTop,
  Loader2,
  MessageSquare,
  PlusCircle,
  Send,
  Sparkles,
  X,
} from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { FilePreviewPanel, type PanelMode } from "@/components/chat/FilePreviewPanel";
import { ResearchSummary } from "@/components/chat/ResearchSummary";
import { BundleFileTree } from "@/components/manuscripts/BundleExplorer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { useTaskStream } from "@/hooks/useTaskStream";
import { api } from "@/lib/api";
import { manuscriptsApi } from "@/lib/manuscripts";
import type {
  CreateTaskResponse,
  Manuscript,
  TaskListResponse,
  TaskRecord,
} from "@/types/api";

// ---------------------------------------------------------------------------
// Entry
// ---------------------------------------------------------------------------

export function UnifiedWorkbenchPage() {
  const { manuscriptId = "" } = useParams<{ manuscriptId?: string }>();
  const [params, setParams] = useSearchParams();
  const thread = params.get("thread") ?? "";
  const navigate = useNavigate();
  const { t } = useTranslation();

  // Shared state
  const [activeTaskId, setActiveTaskId] = useState<string | null>(thread || null);
  const [query, setQuery] = useState("");
  const [sending, setSending] = useState(false);

  // File selection state (context, not intent)
  const [targetPath, setTargetPath] = useState(params.get("target") ?? "");
  const [checkedFiles, setCheckedFiles] = useState<Set<string>>(new Set());
  const [projectMode, setProjectMode] = useState(false);
  const [batchMode, setBatchMode] = useState(false);

  // Content panel state
  const [panelMode, setPanelMode] = useState<PanelMode>("preview");
  const [panelVisible, setPanelVisible] = useState(true);
  const [panelHeight, setPanelHeight] = useState<number | null>(null);
  const [beforeContent, setBeforeContent] = useState<string | undefined>();
  const [showDiff, setShowDiff] = useState(false);

  // Sidebar resize
  const [sidebarTopPct, setSidebarTopPct] = useState(60); // percentage

  // Conversation threads (like Cursor) — persisted to localStorage
  interface Turn { query: string; taskId: string; answer?: string; summary?: Record<string,unknown>; manuscriptId?: string; status: string; result?: Record<string,unknown>; }
  interface Thread { id: string; title: string; turns: Turn[]; created_at: string; }
  const STORAGE_KEY = "aaf.workbench.threads";
  const [threads, setThreads] = useState<Thread[]>(() => {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
      // Ensure all threads have created_at (migration from old format)
      return raw.map((t: Thread) => ({ ...t, created_at: t.created_at || new Date().toISOString() }));
    } catch { return []; }
  });
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const sortedThreads = [...threads].sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());
  const activeThread = threads.find(t => t.id === activeThreadId);
  const activeTurns = activeThread?.turns ?? [];

  // Persist threads to localStorage on change
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(threads)); } catch { /* quota exceeded */ }
  }, [threads]);

  // Restore threads from backend tasks on first load
  const historyQuery = useQuery({
    queryKey: ["tasks-history"],
    queryFn: () => api<TaskListResponse>("/api/tasks?limit=50&sort_by=created_at&sort_order=desc"),
    refetchInterval: 10_000,
  });
  // Sync running turns with backend — fixes answers lost when navigating away
  useEffect(() => {
    if (!historyQuery.data?.items || threads.length === 0) return;
    const backendTasks = new Map(historyQuery.data.items.map(t => [t.id, t]));
    setThreads(prev => prev.map(th => ({
      ...th,
      turns: th.turns.map(turn => {
        if (turn.status === "ok" || turn.status === "error") return turn;
        const bt = backendTasks.get(turn.taskId);
        if (!bt) return turn;
        const r = (bt.result ?? {}) as Record<string, unknown>;
        const answer = (r.answer as string) || turn.answer || "";
        if (bt.status === "ok" || bt.status === "error") {
          return { ...turn, status: bt.status, answer, result: r, manuscriptId: (r.manuscript_id as string) || turn.manuscriptId };
        }
        return turn;
      })
    })));
  }, [historyQuery.data, threads.length]);

  useEffect(() => {
    if (!historyQuery.data?.items || threads.length > 0) return;
    // Build threads from backend tasks (group by root task)
    const items = historyQuery.data.items.filter(t => t.workflow === "auto");
    const threadMap = new Map<string, { query: string; turns: Turn[] }>();
    for (const t of items.reverse()) {
      const pid = (t.input as Record<string,unknown> | undefined)?.parent_task_id as string | undefined;
      const rootId = pid || t.id;
      if (!threadMap.has(rootId)) threadMap.set(rootId, { query: t.query || "", turns: [] });
      const entry = threadMap.get(rootId)!;
      const ans = ((t.result as Record<string,unknown> | undefined)?.answer as string) || "";
      const summary = ((t.result as Record<string,unknown> | undefined)?.summary as Record<string,unknown>) || undefined;
      entry.turns.push({ query: t.query || "", taskId: t.id, status: t.status, answer: ans, summary });
    }
    const restored: Thread[] = [];
    for (const [id, v] of threadMap) {
      if (v.turns.length > 0) restored.push({ id, title: v.turns[0].query.slice(0, 40), turns: v.turns, created_at: new Date().toISOString() });
    }
    if (restored.length > 0) setThreads(restored);
  }, [historyQuery.data, threads.length]);

  // --- Data ---
  const manuscripts = useQuery({
    queryKey: ["manuscripts", { limit: 100 }],
    queryFn: () => manuscriptsApi.list({ limit: 100 }),
  });

  const manuscriptMeta = useQuery({
    queryKey: ["manuscript", manuscriptId],
    queryFn: () => manuscriptsApi.get(manuscriptId),
    enabled: Boolean(manuscriptId),
  });

  const tree = useQuery({
    queryKey: ["manuscript-tree", manuscriptId],
    queryFn: () => manuscriptsApi.tree(manuscriptId),
    enabled: manuscriptMeta.data?.layout === "bundle",
    staleTime: 30_000,
  });

  // Selected file content
  const fileContent = useQuery({
    queryKey: ["manuscript-file", manuscriptId, targetPath],
    queryFn: () => manuscriptsApi.readFile(manuscriptId, targetPath),
    enabled: Boolean(targetPath) && manuscriptMeta.data?.layout === "bundle",
  });

  // Live SSE streaming for the active task
  const stream = useTaskStream(activeTaskId ?? "", Boolean(activeTaskId));
  const streamEvents = stream.events;

  // Force query refresh when stream ends — show answer immediately
  const streamEndedRef = useRef(false);
  const queryClient = useQueryClient();
  useEffect(() => {
    if ((stream.status === "ok" || stream.status === "error") && !streamEndedRef.current && activeTaskId) {
      streamEndedRef.current = true;
      void queryClient.invalidateQueries({ queryKey: ["task", activeTaskId] });
    }
    if (stream.status === "connecting" || stream.status === "running") {
      streamEndedRef.current = false;
    }
  }, [stream.status, activeTaskId, queryClient]);

  const activeTask = useQuery({
    queryKey: ["task", activeTaskId],
    queryFn: () => api<TaskRecord>(`/api/tasks/${activeTaskId}`),
    enabled: Boolean(activeTaskId),
    refetchInterval: (q) => {
      const data = q.state.data as TaskRecord | undefined;
      if (!data) return 2000;
      return data.status === "ok" || data.status === "error" || data.status === "cancelled" ? false : 2000;
    },
  });

  // --- Task result (must be before handleSend — referenced in useCallback) ---
  const taskResult = activeTask.data as TaskRecord | undefined;
  const isComplete = taskResult?.status === "ok" || taskResult?.status === "error";
  const taskData = (taskResult?.result ?? {}) as Record<string, unknown>;
  const summary = taskData?.summary as Record<string, unknown> | undefined;
  const answer = (taskData?.answer as string | undefined) || (taskData?.prompt as string | undefined);
  const autoManuscriptId = taskData?.manuscript_id as string | undefined;

  // Determine display status for each turn: if taskResult matches, use live data
  const liveTaskId = taskResult?.id;
  const liveStatus = taskResult?.status;
  const liveOk = liveStatus === "ok" || liveStatus === "error";
  const isWaiting = taskResult?.status === "waiting";

  // Persist completed answers + full result to threads
  useEffect(() => {
    if (!liveTaskId || !liveOk) return;
    setThreads(prev => prev.map(th => ({
      ...th,
      turns: th.turns.map(t => t.taskId === liveTaskId && t.status !== "ok"
        ? { ...t, status: liveStatus, answer, summary, manuscriptId: autoManuscriptId || undefined, result: taskData }
        : t)
    })));
  }, [liveTaskId, liveStatus, answer, summary, autoManuscriptId, taskData]);
  // Trigger diff view + refresh file when agent modifies a file
  useEffect(() => {
    if (!isComplete || !liveTaskId) return;
    const fw = taskData?.files_written as string[] | undefined;
    if (fw && fw.length > 0) {
      // Refresh file content for all written files
      for (const f of fw) {
        void queryClient.invalidateQueries({ queryKey: ["manuscript-file", manuscriptId, f] });
      }
      if (targetPath && fw.some(f => f === targetPath || f.endsWith('/' + targetPath) || targetPath.endsWith('/' + f))) {
        if (beforeContent) {
          setShowDiff(true);
          setPanelMode("diff");
        }
      }
    }
  }, [isComplete, liveTaskId, taskData, targetPath, beforeContent, queryClient, manuscriptId]);
  // --- Send ---
  const handleSend = useCallback(async () => {
    const q = query.trim();
    if (!q || sending) return;
    setSending(true);
    // Snapshot current file content for before/after diff
    if (targetPath && fileContent.data?.content) {
      setBeforeContent(fileContent.data.content);
      setShowDiff(false);
    }
    try {
      const inputObj: Record<string, unknown> = {};
      if (manuscriptId) {
        inputObj.manuscript_id = manuscriptId;
        if (projectMode) {
          inputObj.mode = "project";
        } else if (batchMode && checkedFiles.size > 0) {
          inputObj.mode = "batch";
          inputObj.bundle_targets = [...checkedFiles];
          inputObj.edit_mode = true;
        } else if (targetPath) {
          inputObj.bundle_target = targetPath;
          inputObj.edit_mode = true;
        }
      }
      // Build full message chain from all turns in the active thread
      if (activeThreadId) {
        inputObj.parent_task_id = activeTaskId;
        const activeThread = threads.find(t => t.id === activeThreadId);
        if (activeThread) {
          const history: Record<string, unknown>[] = [];
          let turnIdx = 0;
          for (const turn of activeThread.turns) {
            if (turn.status !== "ok" && turn.status !== "error") continue;
            turnIdx++;
            history.push({ role: "user", content: turn.query || "" });
            const r = (turn.result as Record<string, unknown> | undefined) ?? {};
            const ans = r.answer as string | undefined;
            const tc = r.tool_calls as Array<{id?: string; name: string; kind: string; args?: Record<string,unknown>; result_summary?: string}> | undefined;
            if (tc && tc.length > 0) {
              const makeId = (t: {id?: string}, i: number) => t.id ?? `t${turnIdx}_${i}`;
              history.push({
                role: "assistant",
                content: "Let me use the appropriate tools for this request.",
                tool_calls: tc.map((t, i) => ({ id: makeId(t, i), name: t.name, arguments: t.args ?? {} })),
              });
              for (let i = 0; i < tc.length; i++) {
                history.push({
                  role: "tool",
                  content: tc[i].result_summary ?? `Tool ${tc[i].name} completed.`,
                  tool_call_id: makeId(tc[i], i),
                  name: tc[i].name,
                });
              }
            }
            if (ans) history.push({ role: "assistant", content: ans });
          }
          if (history.length > 0) inputObj.history = history;
        }
      }
      const body: Record<string, unknown> = { query: q, workflow: "auto" };
      if (Object.keys(inputObj).length > 0) body.input = inputObj;

      const res = await api<CreateTaskResponse>("/api/tasks", { method: "POST", json: body });
      setActiveTaskId(res.task_id);
      const newTurn: Turn = { query: q, taskId: res.task_id, status: "running" };
      const tid = activeThreadId || res.task_id;
      if (!activeThreadId) setActiveThreadId(tid);
      setThreads(prev => {
        const existing = prev.find(t => t.id === tid);
        if (existing) return prev.map(t => t.id === tid ? { ...t, turns: [...t.turns, newTurn], created_at: new Date().toISOString() } : t);
        return [...prev, { id: tid, title: q.slice(0, 40), turns: [newTurn], created_at: new Date().toISOString() }];
      });
      setQuery("");
    } catch (err: unknown) {
      toast.error(err instanceof Error ? err.message : "Failed to send");
    } finally {
      setSending(false);
    }
  }, [query, sending, manuscriptId, targetPath, checkedFiles, projectMode, batchMode, activeTaskId, taskResult]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); handleSend(); }
    },
    [handleSend],
  );

  // --- Derived ---
  const isBundle = manuscriptMeta.data?.layout === "bundle";
  const exitManuscript = () => navigate("/workbench");
  const handlePickFile = useCallback((path: string) => {
    setTargetPath(path); setPanelMode("preview"); setPanelVisible(true);
    setParams((prev) => { const n = new URLSearchParams(prev); n.set("target", path); return n; }, { replace: true });
  }, [setParams]);

  // =========================================================================
  // RENDER
  // =========================================================================

  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      {/* ─── LEFT SIDEBAR ──────────────────────────────────────────── */}
      <aside className="w-60 shrink-0 border-r bg-[var(--color-card)]/30 flex flex-col">
        {/* Top: manuscripts list OR file tree */}
        <div className="min-h-0 flex flex-col overflow-hidden" style={{ height: `${sidebarTopPct}%` }}>
          <SidebarHeader
            label={manuscriptId ? (manuscriptMeta.data?.title ?? "Untitled") : (t("nav.manuscripts") ?? "Manuscripts")}
            action={manuscriptId ? (
              <button onClick={exitManuscript} className="text-[10px] text-[var(--color-primary)] hover:underline flex items-center gap-0.5">
                <ChevronLeft className="h-3 w-3" />{t("common.back") ?? "Back"}
              </button>
            ) : (
              <Link to="/papers" className="text-[10px] text-[var(--color-primary)] hover:underline">{t("common.viewAll") ?? "View all"}</Link>
            )}
          />

          {manuscriptId ? (
            <div className="flex-1 overflow-y-auto">
              {/* Mode toggles with clear active indicator */}
              <div className="border-b px-2 py-1.5 space-y-1">
                <div className="flex items-center gap-1">
                  <Button variant={!projectMode && !batchMode ? "default" : "ghost"} size="sm" className="h-6 text-[10px] px-2"
                    onClick={() => { setProjectMode(false); setBatchMode(false); }}>
                    <FileText className="h-3 w-3 mr-0.5" />Single File
                  </Button>
                  <Button variant={batchMode ? "default" : "ghost"} size="sm" className="h-6 text-[10px] px-2"
                    onClick={() => { setBatchMode(!batchMode); setProjectMode(false); }}>
                    <CheckSquare className="h-3 w-3 mr-0.5" />Batch
                  </Button>
                  <Button variant={projectMode ? "default" : "ghost"} size="sm" className="h-6 text-[10px] px-2"
                    onClick={() => { setProjectMode(!projectMode); setBatchMode(false); }}>
                    <Layers className="h-3 w-3 mr-0.5" />Project
                  </Button>
                </div>
                {/* Active mode indicator */}
                <div className="text-[10px] text-[var(--color-muted-foreground)] px-1">
                  {projectMode && 'Mode: Project — Agent reads files as needed'}
                  {batchMode && `Mode: Batch — ${checkedFiles.size} files selected`}
                  {!projectMode && !batchMode && (targetPath ? `File: ${targetPath}` : 'Mode: Single File — click a file to preview')}
                </div>
              </div>
              {/* File tree */}
              {isBundle && tree.data ? (
                <BundleFileTree
                  files={tree.data.files}
                  onSelect={batchMode ? () => {} : handlePickFile}
                  selected={targetPath || null}
                  multiSelect={batchMode}
                  checked={batchMode ? checkedFiles : undefined}
                  onCheckChange={batchMode ? setCheckedFiles : undefined}
                />
              ) : (
                <div className="p-3 text-[11px] text-[var(--color-muted-foreground)]">
                  {manuscriptMeta.isLoading ? <Skeleton className="h-4 w-3/4" /> : "Single-file manuscript"}
                </div>
              )}
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto">
              {manuscripts.isLoading ? (
                <div className="p-3 space-y-2"><Skeleton className="h-4 w-3/4" /><Skeleton className="h-4 w-1/2" /></div>
              ) : manuscripts.data?.items.length === 0 ? (
                <p className="p-3 text-[11px] text-[var(--color-muted-foreground)]">No manuscripts yet</p>
              ) : (
                <ul className="divide-y">
                  {manuscripts.data?.items.map((m) => (
                    <li key={m.id}>
                      <button type="button" onClick={() => navigate(`/workbench/${m.id}`)}
                        className="flex w-full items-center justify-between gap-2 p-2.5 text-left hover:bg-[var(--color-muted)] text-xs">
                        <div className="min-w-0">
                          <div className="truncate font-medium">{m.title || "Untitled"}</div>
                          <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">{format(new Date(m.updated_at), "MM-dd")}</div>
                        </div>
                        <Badge variant="neutral" className="shrink-0 text-[10px] px-1.5">{m.status}</Badge>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        {/* Vertical drag handle between top and bottom */}
        <div
          className="h-2 shrink-0 cursor-row-resize bg-[var(--color-border)] hover:bg-[var(--color-primary)]/40 transition-colors flex items-center justify-center"
          onPointerDown={(e) => {
            e.preventDefault(); const el = e.currentTarget; el.setPointerCapture(e.pointerId);
            const sidebar = el.parentElement!;
            const onMove = (ev: PointerEvent) => {
              const rect = sidebar.getBoundingClientRect();
              const pct = ((ev.clientY - rect.top) / rect.height) * 100;
              setSidebarTopPct(Math.max(30, Math.min(85, pct)));
            };
            const onUp = () => { el.releasePointerCapture(e.pointerId); el.removeEventListener("pointermove", onMove); el.removeEventListener("pointerup", onUp); };
            el.addEventListener("pointermove", onMove); el.addEventListener("pointerup", onUp);
          }}
        />

        {/* Bottom: conversation threads */}
        <div className="border-t flex flex-col min-h-[60px] flex-1 overflow-hidden">
          <div className="flex items-center border-b px-3 py-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)] flex items-center gap-1">
              <MessageSquare className="h-3 w-3" />Conversations
            </span>
            <Button variant="ghost" size="icon" className="h-5 w-5 ml-auto" onClick={() => { setActiveThreadId(null); setActiveTaskId(null); }}>
              <PlusCircle className="h-3 w-3" />
            </Button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {sortedThreads.map((th) => (
              <div key={th.id} className={`flex items-center border-b border-[var(--color-border)]/30 ${activeThreadId === th.id ? 'bg-[var(--color-accent)]/30' : ''}`}>
                <button type="button"
                  onClick={() => { setActiveThreadId(th.id); setActiveTaskId(null); }}
                  className="flex-1 text-left p-2 hover:bg-[var(--color-muted)] text-[11px] min-w-0">
                  <div className="truncate font-medium">{th.title}</div>
                  <div className="flex items-center justify-between mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
                    <span>{format(new Date(th.created_at || Date.now()), "MM-dd HH:mm")}</span>
                    <Badge variant="neutral" className="text-[9px] px-1">{th.turns.length}t</Badge>
                  </div>
                </button>
                <button type="button" title="Delete conversation"
                  onClick={(e) => { e.stopPropagation(); setThreads(prev => prev.filter(t => t.id !== th.id)); if (activeThreadId === th.id) setActiveThreadId(null); }}
                  className="shrink-0 p-1 hover:bg-red-100 dark:hover:bg-red-900/30 rounded">
                  <X className="h-3 w-3 text-[var(--color-muted-foreground)] hover:text-red-500" />
                </button>
              </div>
            ))}
          </div>
        </div>
      </aside>

      {/* ─── MAIN ─────────────────────────────────────────────────── */}
      <main className="flex min-w-0 flex-1 flex-col">
        {/* File content panel */}
        {manuscriptId && targetPath && panelVisible && (
          <div style={{ height: panelHeight ?? 200, minHeight: 80, flexShrink: 0 }}>
            <FilePreviewPanel
              filename={targetPath}
              content={fileContent.data?.content ?? ""}
              beforeContent={beforeContent}
              mode={panelMode}
              onModeChange={setPanelMode}
              onCollapse={() => setPanelVisible(false)}
              revisionLabel={showDiff ? "Agent modified this file" : undefined}
              onAcceptDiff={() => {
                setBeforeContent(undefined);
                setShowDiff(false);
                setPanelMode("preview");
                void queryClient.invalidateQueries({ queryKey: ["manuscript-file", manuscriptId, targetPath] });
              }}
              onRejectDiff={async () => {
                if (!beforeContent) return;
                try {
                  await manuscriptsApi.writeTextFile(manuscriptId, targetPath, { content: beforeContent });
                  toast.success("Changes reverted");
                  setBeforeContent(undefined);
                  setShowDiff(false);
                  setPanelMode("preview");
                  void queryClient.invalidateQueries({ queryKey: ["manuscript-file", manuscriptId, targetPath] });
                } catch (err: unknown) {
                  toast.error(`Revert failed: ${err instanceof Error ? err.message : String(err)}`);
                }
              }}
              onSave={async (c) => {
                try { await manuscriptsApi.writeTextFile(manuscriptId, targetPath, { content: c }); toast.success("Saved"); setPanelMode("preview"); }
                catch (err: unknown) { toast.error(`Save failed: ${err instanceof Error ? err.message : String(err)}`); }
              }}
            />
          </div>
        )}
        {manuscriptId && targetPath && panelVisible && (
          <div className="h-2 shrink-0 cursor-row-resize bg-[var(--color-border)] hover:bg-[var(--color-primary)]/40 flex items-center justify-center"
            onPointerDown={(e) => {
              e.preventDefault(); const el = e.currentTarget; el.setPointerCapture(e.pointerId);
              const startY = e.clientY; const startH = panelHeight ?? 200;
              const onMove = (ev: PointerEvent) => setPanelHeight(Math.max(80, startH + (ev.clientY - startY)));
              const onUp = () => { el.releasePointerCapture(e.pointerId); el.removeEventListener("pointermove", onMove); el.removeEventListener("pointerup", onUp); };
              el.addEventListener("pointermove", onMove); el.addEventListener("pointerup", onUp);
            }}
          />
        )}

        {/* Chat — show ALL turns like Cursor */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {activeTurns.length === 0 && (
            <div className="flex flex-col items-center justify-center h-full gap-4 text-[var(--color-muted-foreground)]">
              <Sparkles className="h-12 w-12 text-[var(--color-primary)]/40" />
              <h2 className="text-lg font-semibold">Academic Workbench</h2>
              <p className="text-sm max-w-md text-center">
                {manuscriptId ? "Pick a file to preview, or ask about anything." : "Research papers, draft manuscripts, revise your work."}
              </p>
              {!manuscriptId && (
                <div className="flex gap-3 mt-2">
                  <Card className="border-dashed cursor-pointer hover:bg-[var(--color-muted)]/50" onClick={() => setQuery("Research ")}>
                    <CardContent className="p-3 text-center"><BookOpenText className="mx-auto mb-1 h-4 w-4" /><span className="text-xs font-medium">Research</span></CardContent>
                  </Card>
                  <Card className="border-dashed cursor-pointer hover:bg-[var(--color-muted)]/50" onClick={() => setQuery("Write ")}>
                    <CardContent className="p-3 text-center"><LayoutPanelTop className="mx-auto mb-1 h-4 w-4" /><span className="text-xs font-medium">Write</span></CardContent>
                  </Card>
                </div>
              )}
            </div>
          )}

          {/* Render active thread turns */}
          {activeTurns.map((turn) => {
            const isLive = liveTaskId && turn.taskId === liveTaskId;
            const displayStatus = isLive ? (liveOk ? liveStatus : "running") : turn.status;
            const displayAnswer = isLive ? answer : turn.answer;
            const displaySummary = isLive ? summary : turn.summary;
            return (
            <div key={turn.taskId} className="space-y-2 max-w-3xl">
              <div className="flex justify-end">
                <div className="max-w-[80%] rounded-lg bg-[var(--color-primary)]/10 px-3 py-2 text-sm">{turn.query}</div>
              </div>
              {/* Only show waiting/spinner for the LIVE running task */}
              {isLive && displayStatus === "running" && stream.status !== "ok" && stream.status !== "error" && (
                <div className="flex items-center gap-2 text-sm text-[var(--color-muted-foreground)]">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {streamEvents.length === 0
                    ? "Waiting for agent…"
                    : `Working (${streamEvents.length} event${streamEvents.length !== 1 ? "s" : ""})…`}
                </div>
              )}
              {isLive && displayStatus === "running" && (stream.status === "ok" || stream.status === "error") && (
                <div className="flex items-center gap-2 text-sm text-[var(--color-muted-foreground)]"><Loader2 className="h-4 w-4" />Task completed — loading result…</div>
              )}
              {/* Active Clarification — Agent needs more info */}
              {isLive && displayStatus === "waiting" && displayAnswer && (
                <div className="space-y-2 rounded border border-amber-500/30 bg-amber-500/5 p-3 text-sm">
                  <div className="flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-400">
                    <MessageSquare className="h-3.5 w-3.5" />
                    Agent needs clarification
                  </div>
                  <div className="whitespace-pre-wrap text-[var(--color-foreground)]">{displayAnswer}</div>
                </div>
              )}
              {/* Show answer for completed turns (live or stored) */}
              {(displayStatus === "ok" || (isLive && isComplete && displayAnswer) || (!isLive && turn.answer)) && (
                <>
                  {/* Files written badge with View diff button */}
                  {((turn.result as any)?.files_written?.length > 0) && (
                    <div className="flex items-center gap-2 rounded border border-green-500/30 bg-green-500/10 px-2 py-1 text-[11px] text-green-600 dark:text-green-400">
                      <CheckCircle className="h-3 w-3" />
                      <span>Modified: {(turn.result as any).files_written.join(', ')}</span>
                      {targetPath && (turn.result as any).files_written.includes(targetPath) && (
                        <button
                          type="button"
                          onClick={() => { setPanelMode("diff"); setShowDiff(true); setPanelVisible(true); }}
                          className="ml-1 rounded bg-green-500/20 px-1.5 py-0.5 text-[10px] hover:bg-green-500/30"
                        >
                          View diff
                        </button>
                      )}
                    </div>
                  )}
                  {displaySummary && (<ResearchSummary data={displaySummary as any} />)}
                  {displayAnswer && (<div className="prose prose-sm dark:prose-invert max-w-none text-sm whitespace-pre-wrap">{displayAnswer}</div>)}
                  {turn.manuscriptId && (
                    <Button size="sm" onClick={() => navigate(`/workbench/${turn.manuscriptId}`)}>
                      <LayoutPanelTop className="mr-2 h-3.5 w-3.5" />Open manuscript
                    </Button>
                  )}
                  {!displaySummary && !displayAnswer && displayStatus === "ok" && <div className="text-sm text-[var(--color-muted-foreground)]">Done.</div>}
                </>
              )}
              {displayStatus === "error" && <div className="text-sm text-red-500">Error processing request.</div>}
            </div>
          )})}

          {/* Stream preview for current running task */}
          {taskResult && !isComplete && streamEvents.length > 0 && (
            <div className="rounded-md border bg-[var(--color-card)] p-3 text-sm max-w-3xl">
              <pre className="whitespace-pre-wrap font-mono text-xs">{streamEvents.map((e) => e.data?.delta ?? "").join("")}</pre>
            </div>
          )}
        </div>

        {/* Active Clarification prompt — when Agent needs more info */}
        {isWaiting && answer && (
          <div className="border-t border-amber-500/30 bg-amber-500/5 p-3">
            <div className="mx-auto max-w-3xl space-y-2">
              <div className="flex items-center gap-2 text-sm font-medium text-amber-600 dark:text-amber-400">
                <MessageSquare className="h-4 w-4" />
                Agent needs clarification
              </div>
              <div className="rounded border border-amber-500/20 bg-white dark:bg-gray-900 p-3 text-sm whitespace-pre-wrap">{answer}</div>
            </div>
          </div>
        )}

        {/* Composer + New Chat button */}
        <div className="border-t bg-[var(--color-background)] p-3">
          <div className="mx-auto max-w-3xl flex items-end gap-2">
            <Textarea value={query} onChange={(e) => setQuery(e.target.value)} onKeyDown={handleKeyDown}
              placeholder={
                isWaiting ? "Type your response to the agent's question…"
                : batchMode && checkedFiles.size > 0 ? `Edit ${checkedFiles.size} selected file(s)…`
                : targetPath ? `Edit ${targetPath}…`
                : manuscriptId ? "Ask about this manuscript…"
                : "Ask anything…"
              }
              className="min-h-[44px] flex-1 resize-none text-sm" rows={2} disabled={sending || (!!activeTaskId && !isComplete && !isWaiting)} />
            <Button size="icon" disabled={!query.trim() || sending || (!!activeTaskId && !isComplete && !isWaiting)} onClick={handleSend} aria-label="Send">
              {sending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            </Button>
          </div>
          <div className="flex items-center justify-between mt-1">
            <p className="text-[10px] text-[var(--color-muted-foreground)]/60">Ctrl+Enter to send</p>
            {sortedThreads.length > 0 && (
              <Button variant="ghost" size="sm" className="text-[10px] h-5" onClick={() => { setActiveThreadId(null); setActiveTaskId(null); }}>
                <PlusCircle className="mr-1 h-3 w-3" />New Chat
              </Button>
            )}
          </div>
        </div>
      </main>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sidebar header
// ---------------------------------------------------------------------------

function SidebarHeader({ label, action }: { label: string; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b px-3 py-2">
      <span className="text-[11px] font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)] truncate">{label}</span>
      {action}
    </div>
  );
}
