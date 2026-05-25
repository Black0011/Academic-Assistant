import Editor, { type OnMount } from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { format } from "date-fns";
import {
  ArrowLeft,
  Bot,
  CheckCircle2,
  Download,
  GitCommit,
  Loader2,
  PencilRuler,
  Save,
  User,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { BundleExplorer } from "@/components/manuscripts/BundleExplorer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { useUiStore } from "@/stores/uiStore";
import { manuscriptsApi } from "@/lib/manuscripts";
import type {
  CommitVersionInput,
  Manuscript,
  ManuscriptOrigin,
  ManuscriptVersion,
} from "@/types/api";

const ORIGIN_VARIANT: Record<ManuscriptOrigin, "neutral" | "primary" | "warning"> = {
  user_upload: "neutral",
  write_workflow: "primary",
  revision_workflow: "warning",
  ingest: "neutral",
  api: "neutral",
};

const ORIGIN_ICON: Record<ManuscriptOrigin, typeof Bot> = {
  user_upload: User,
  write_workflow: Bot,
  revision_workflow: Bot,
  ingest: User,
  api: User,
};

export function PaperWriterPage() {
  const { manuscriptId = "" } = useParams<{ manuscriptId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const themeMode = useUiStore((s) => s.theme);
  const isDark =
    themeMode === "dark" ||
    (themeMode === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches);

  const meta = useQuery({
    queryKey: ["manuscript", manuscriptId],
    queryFn: () => manuscriptsApi.get(manuscriptId),
    enabled: Boolean(manuscriptId),
  });

  const versions = useQuery({
    queryKey: ["manuscript-versions", manuscriptId],
    queryFn: () => manuscriptsApi.listVersions(manuscriptId, 100),
    enabled: Boolean(manuscriptId),
  });

  // Active version: defaults to current_version, but the timeline can switch.
  const [activeVersion, setActiveVersion] = useState<number | null>(null);
  useEffect(() => {
    if (meta.data && activeVersion === null) {
      setActiveVersion(meta.data.current_version || null);
    }
  }, [meta.data, activeVersion]);

  const versionDetail = useQuery({
    queryKey: ["manuscript-version", manuscriptId, activeVersion],
    queryFn: () => manuscriptsApi.getVersion(manuscriptId, activeVersion!),
    enabled: Boolean(manuscriptId && activeVersion),
  });

  const [draft, setDraft] = useState<string>("");
  const [note, setNote] = useState<string>("");
  const initialDraft = useRef<string>("");

  // When a different version loads, reset the editor draft + note.
  useEffect(() => {
    if (versionDetail.data) {
      setDraft(versionDetail.data.content);
      initialDraft.current = versionDetail.data.content;
      setNote("");
    }
  }, [versionDetail.data?.manuscript_id, versionDetail.data?.version]); // eslint-disable-line react-hooks/exhaustive-deps

  const dirty = draft !== initialDraft.current;
  const isLatest = meta.data ? activeVersion === meta.data.current_version : false;

  const commit = useMutation({
    mutationFn: (body: CommitVersionInput) =>
      manuscriptsApi.commitVersion(manuscriptId, body),
    onSuccess: (v) => {
      toast.success(`Committed v${v.version}`);
      void qc.invalidateQueries({ queryKey: ["manuscript", manuscriptId] });
      void qc.invalidateQueries({ queryKey: ["manuscript-versions", manuscriptId] });
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
      setActiveVersion(v.version);
      initialDraft.current = v.content;
      setNote("");
    },
    onError: (err: Error) => toast.error(`Commit failed: ${err.message}`),
  });

  const handleEditorMount: OnMount = (editor) => {
    // Keyboard shortcut Ctrl/Cmd-S triggers commit (with confirmation if dirty).
    editor.addAction({
      id: "aaf.commit-version",
      label: "AAF: Commit version",
      keybindings: [
        // monaco's KeyMod is on the global, but we use a simple binding the
        // editor exposes. Ctrl/Cmd + S is 2048 | 49 → use the constant lookup.
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        (window as any).monaco?.KeyMod?.CtrlCmd | (window as any).monaco?.KeyCode?.KeyS,
      ].filter(Boolean) as number[],
      run: () => {
        if (!dirty) return;
        commit.mutate({
          content: editor.getValue(),
          note: note || "manual save",
          origin: "api",
        });
      },
    });
  };

  if (!manuscriptId) {
    return null;
  }

  // P7 — bundle layout takes a completely different shape (file tree + per-file
  // editor). The single-document path below stays unchanged and keeps working
  // for legacy manuscripts.
  if (meta.data?.layout === "bundle") {
    return (
      <div className="flex h-[calc(100vh-7rem)] min-h-0 flex-col gap-4">
        <PaperHeader
          meta={meta.data}
          loading={meta.isLoading}
          onBack={() => navigate("/papers")}
          onRevise={() => navigate(`/revision?manuscript=${encodeURIComponent(manuscriptId)}`)}
          reviseDisabled
        />
        <BundleExplorer manuscript={meta.data} />
      </div>
    );
  }

  return (
    <div className="flex h-[calc(100vh-7rem)] min-h-0 flex-col">
      <PaperHeader
        meta={meta.data}
        loading={meta.isLoading}
        onBack={() => navigate("/papers")}
        onRevise={() =>
          navigate(
            `/revision?manuscript=${encodeURIComponent(manuscriptId)}` +
              (activeVersion ? `&from=${activeVersion}` : ""),
          )
        }
        reviseDisabled={!activeVersion || (meta.data?.current_version ?? 0) === 0}
      />

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[1fr_18rem]">
        {/* Editor */}
        <Card className="flex min-h-0 flex-col">
          <CardHeader className="flex-row items-center justify-between gap-2 p-3">
            <CardTitle className="text-sm">
              {activeVersion ? `Version ${activeVersion}` : "—"}
              {!isLatest && activeVersion ? (
                <span className="ml-2 text-xs font-normal text-[var(--color-warning)]">
                  viewing history (commits create a new version)
                </span>
              ) : null}
            </CardTitle>
            <div className="flex items-center gap-2">
              <Input
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder="commit message…"
                className="h-8 w-56 text-xs"
              />
              <Button
                size="sm"
                disabled={!dirty || commit.isPending}
                onClick={() =>
                  commit.mutate({
                    content: draft,
                    note: note || (isLatest ? "manual save" : `revised from v${activeVersion}`),
                    origin: "api",
                  })
                }
                title={dirty ? "Commit a new version" : "No changes to commit"}
              >
                {commit.isPending ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Save className="h-4 w-4" />
                )}
                Commit
              </Button>
              <a
                href={manuscriptsApi.exportUrl(manuscriptId, activeVersion ?? undefined)}
                className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--color-border)] px-3 text-xs hover:bg-[var(--color-accent)]"
              >
                <Download className="h-3 w-3" />
                Export
              </a>
            </div>
          </CardHeader>
          <CardContent className="min-h-0 flex-1 p-0">
            {versionDetail.isLoading ? (
              <div className="p-4">
                <Skeleton className="h-full w-full" />
              </div>
            ) : (
              <Editor
                height="100%"
                language="markdown"
                value={draft}
                onChange={(v) => setDraft(v ?? "")}
                onMount={handleEditorMount}
                theme={isDark ? "vs-dark" : "vs"}
                options={{
                  fontSize: 13,
                  wordWrap: "on",
                  minimap: { enabled: false },
                  scrollBeyondLastLine: false,
                  lineNumbersMinChars: 3,
                  padding: { top: 12, bottom: 12 },
                  fontFamily:
                    'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
                }}
              />
            )}
          </CardContent>
        </Card>

        {/* Version timeline */}
        <Card className="flex min-h-0 flex-col">
          <CardHeader className="p-3">
            <CardTitle className="text-sm">Version timeline</CardTitle>
          </CardHeader>
          <CardContent className="flex-1 overflow-y-auto p-0">
            {versions.isLoading ? (
              <div className="p-4 text-xs text-[var(--color-muted-foreground)]">Loading…</div>
            ) : !versions.data || versions.data.items.length === 0 ? (
              <div className="p-4 text-xs text-[var(--color-muted-foreground)]">
                No versions yet — write something and commit.
              </div>
            ) : (
              <ol className="divide-y">
                {versions.data.items.map((v) => (
                  <VersionRow
                    key={v.version}
                    version={v}
                    active={v.version === activeVersion}
                    isLatest={meta.data ? v.version === meta.data.current_version : false}
                    onSelect={() => setActiveVersion(v.version)}
                    saving={dirty && v.version === activeVersion}
                  />
                ))}
              </ol>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header
// ---------------------------------------------------------------------------

function PaperHeader({
  meta,
  loading,
  onBack,
  onRevise,
  reviseDisabled,
}: {
  meta: Manuscript | undefined;
  loading: boolean;
  onBack: () => void;
  onRevise: () => void;
  reviseDisabled: boolean;
}) {
  const title = useMemo(() => meta?.title || "Untitled manuscript", [meta]);

  return (
    <div className="mb-3 flex flex-wrap items-center gap-3">
      <Button variant="ghost" size="sm" onClick={onBack}>
        <ArrowLeft className="h-4 w-4" />
      </Button>
      <Link to="/papers" className="text-sm text-[var(--color-muted-foreground)] hover:underline">
        Manuscripts
      </Link>
      <span className="text-[var(--color-muted-foreground)]">/</span>
      <h1 className="truncate text-base font-semibold tracking-tight">
        {loading ? <Skeleton className="h-4 w-48" /> : title}
      </h1>
      {meta && (
        <>
          <Badge variant="neutral">{meta.kind}</Badge>
          <Badge variant="outline">{meta.status}</Badge>
          <span className="ml-auto text-xs text-[var(--color-muted-foreground)]">
            v{meta.current_version} ·{" "}
            {format(new Date(meta.updated_at), "yyyy-MM-dd HH:mm")}
          </span>
          <Button
            variant="outline"
            size="sm"
            onClick={onRevise}
            disabled={reviseDisabled}
            title={
              reviseDisabled
                ? "Commit a version first"
                : "Open Revision Studio for the active version"
            }
          >
            <PencilRuler className="h-4 w-4" /> Revise…
          </Button>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Version row
// ---------------------------------------------------------------------------

function VersionRow({
  version,
  active,
  isLatest,
  onSelect,
  saving,
}: {
  version: ManuscriptVersion;
  active: boolean;
  isLatest: boolean;
  onSelect: () => void;
  saving: boolean;
}) {
  const Icon = ORIGIN_ICON[version.origin];
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={`flex w-full items-start gap-3 px-3 py-3 text-left transition-colors ${
          active
            ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
            : "hover:bg-[var(--color-muted)]"
        }`}
      >
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-muted)] text-[var(--color-muted-foreground)]">
          <Icon className="h-3 w-3" />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-2 text-xs font-medium">
            <GitCommit className="h-3 w-3" />v{version.version}
            <Badge variant={ORIGIN_VARIANT[version.origin]}>{version.origin}</Badge>
            {isLatest && <CheckCircle2 className="h-3 w-3 text-[var(--color-success)]" />}
          </span>
          {version.note && (
            <span className="mt-0.5 block truncate text-xs text-[var(--color-muted-foreground)]">
              {version.note}
            </span>
          )}
          <span className="mt-0.5 block text-[10px] text-[var(--color-muted-foreground)]">
            {format(new Date(version.created_at), "yyyy-MM-dd HH:mm")} · {version.word_count} words
            {saving && " · uncommitted edits"}
          </span>
        </span>
      </button>
    </li>
  );
}
