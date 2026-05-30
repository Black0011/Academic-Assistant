import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  ChevronRight,
  Download,
  FileArchive,
  FileText,
  FolderInput,
  Link as LinkIcon,
  Loader2,
  MessageSquare,
  PencilRuler,
  Plus,
  Trash2,
  Upload,
} from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { manuscriptsApi } from "@/lib/manuscripts";
import type {
  ListManuscriptsParams,
  Manuscript,
  ManuscriptKind,
  ManuscriptStatus,
} from "@/types/api";

const KIND_OPTIONS: ManuscriptKind[] = ["paper", "section", "outline", "note"];
const STATUS_OPTIONS: ManuscriptStatus[] = ["draft", "in_revision", "final", "archived"];

const STATUS_VARIANT: Record<ManuscriptStatus, "neutral" | "primary" | "success" | "warning"> = {
  draft: "neutral",
  in_revision: "warning",
  final: "success",
  archived: "neutral",
};

export function ManuscriptsPage() {
  const { t } = useTranslation();
  const [filters, setFilters] = useState<ListManuscriptsParams>({ limit: 100 });
  const [showCreate, setShowCreate] = useState(false);
  const [showImport, setShowImport] = useState(false);

  const queryKey = useMemo(() => ["manuscripts", filters] as const, [filters]);
  const list = useQuery({
    queryKey,
    queryFn: () => manuscriptsApi.list(filters),
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("manuscripts.title")}
        description={t("manuscripts.description")}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <UploadButton />
            <UploadZipButton />
            <Button variant="outline" onClick={() => setShowImport((s) => !s)}>
              <FolderInput className="h-4 w-4" /> {t("manuscripts.importFolder")}
            </Button>
            <Button onClick={() => setShowCreate((s) => !s)}>
              <Plus className="h-4 w-4" /> {t("manuscripts.newManuscript")}
            </Button>
          </div>
        }
      />

      {showImport && <ImportFolderCard onDone={() => setShowImport(false)} />}
      {showCreate && <CreateManuscriptCard onDone={() => setShowCreate(false)} />}

      <FilterBar filters={filters} onChange={setFilters} />

      {list.isLoading ? (
        <Card>
          <CardContent className="p-6 text-sm text-[var(--color-muted-foreground)]">
            Loading…
          </CardContent>
        </Card>
      ) : list.isError ? (
        <Card>
          <CardContent className="p-6 text-sm text-[var(--color-destructive)]">
            Failed to load manuscripts: {(list.error as Error).message}
          </CardContent>
        </Card>
      ) : !list.data || list.data.items.length === 0 ? (
        <Card>
          <CardContent className="p-6">
            <EmptyState
              icon={FileText}
              title="No manuscripts yet"
              description="Upload a Markdown / PDF, or run a Write workflow from the Research Console — the runner auto-commits drafts here."
            />
          </CardContent>
        </Card>
      ) : (
        <ManuscriptList items={list.data.items} />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

function ManuscriptList({ items }: { items: Manuscript[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const deleteMut = useMutation({
    mutationFn: (manuscript: Manuscript) => manuscriptsApi.delete(manuscript.id),
    onSuccess: (_, manuscript) => {
      toast.success(t("manuscripts.deleted", { title: manuscript.title || "Untitled" }));
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
    },
    onError: (err: Error) => toast.error(t("manuscripts.deleteFailed", { error: err.message })),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t("manuscripts.count", { count: items.length })}</CardTitle>
      </CardHeader>
      <CardContent className="p-0">
        <ul className="divide-y">
          {items.map((m) => {
            const isBundle = m.layout === "bundle";
            const isLinked = isBundle && m.bundle_link_path;
            return (
              <li key={m.id} className="flex items-center gap-3 p-4 hover:bg-[var(--color-muted)]">
                <FileText
                  className="h-5 w-5 shrink-0 text-[var(--color-muted-foreground)]"
                  aria-hidden
                />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Link
                      to={`/papers/${m.id}`}
                      className="truncate text-sm font-medium hover:underline"
                    >
                      {m.title || "Untitled"}
                    </Link>
                    <Badge variant={STATUS_VARIANT[m.status]}>{m.status}</Badge>
                    <Badge variant="outline">{m.kind}</Badge>
                    {isBundle ? (
                      <Badge variant={isLinked ? "warning" : "primary"} title={m.bundle_link_path ?? undefined}>
                        {isLinked ? <LinkIcon className="mr-1 inline h-3 w-3" /> : null}
                        {isLinked ? t("manuscripts.linkBadge") : t("manuscripts.layoutBundle")}
                      </Badge>
                    ) : null}
                    {m.tags.slice(0, 3).map((tag) => (
                      <Badge key={tag} variant="neutral">
                        {tag}
                      </Badge>
                    ))}
                  </div>
                  <div className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                    v{m.current_version} · origin {m.origin} ·{" "}
                    {formatDistanceToNow(new Date(m.updated_at), { addSuffix: true })}
                  </div>
                </div>
                {isBundle ? (
                  <Link
                    to={`/workbench/${encodeURIComponent(m.id)}`}
                    className="hidden items-center gap-1 text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] sm:inline-flex"
                    title={t("manuscripts.actions.chatTitle")}
                  >
                    <MessageSquare className="h-4 w-4" />
                    <span className="hidden md:inline">{t("manuscripts.actions.chat")}</span>
                  </Link>
                ) : null}
                <Link
                  to={`/revision?manuscript=${encodeURIComponent(m.id)}`}
                  className="hidden items-center gap-1 text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)] sm:inline-flex"
                  title={t("manuscripts.actions.reviseTitle")}
                  aria-disabled={!isBundle && m.current_version === 0}
                  onClick={(e) => {
                    if (!isBundle && m.current_version === 0) {
                      e.preventDefault();
                      toast.info(t("manuscripts.actions.reviseNeedsVersion"));
                    }
                  }}
                >
                  <PencilRuler className="h-4 w-4" />
                  <span className="hidden md:inline">{t("manuscripts.actions.revise")}</span>
                </Link>
                {isBundle ? (
                  <a
                    href={manuscriptsApi.exportZipUrl(m.id)}
                    className="text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
                    title={t("bundle.downloadOverleaf")}
                  >
                    <FileArchive className="h-4 w-4" />
                  </a>
                ) : (
                  <a
                    href={manuscriptsApi.exportUrl(m.id)}
                    className="text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
                    title="Export latest version as Markdown"
                  >
                    <Download className="h-4 w-4" />
                  </a>
                )}
                <button
                  type="button"
                  className="text-xs text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
                  title={t("manuscripts.deleteManuscript")}
                  onClick={() => {
                    if (deleteMut.isPending) return;
                    const name = m.title || "Untitled";
                    const isLinked = m.layout === "bundle" && Boolean(m.bundle_link_path);
                    const confirmKey = isLinked
                      ? "manuscripts.deleteConfirmLink"
                      : m.layout === "bundle"
                        ? "manuscripts.deleteConfirmCopy"
                        : "manuscripts.deleteConfirmSingle";
                    if (!window.confirm(t(confirmKey, { title: name }))) return;
                    deleteMut.mutate(m);
                  }}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
                <Link
                  to={`/papers/${m.id}`}
                  className="text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
                  aria-label="Open"
                >
                  <ChevronRight className="h-4 w-4" />
                </Link>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

function FilterBar({
  filters,
  onChange,
}: {
  filters: ListManuscriptsParams;
  onChange: (next: ListManuscriptsParams) => void;
}) {
  return (
    <Card>
      <CardContent className="flex flex-wrap items-end gap-3 p-4">
        <div className="flex flex-col gap-1">
          <Label htmlFor="filter-status">Status</Label>
          <select
            id="filter-status"
            className="h-9 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
            value={filters.status ?? ""}
            onChange={(e) =>
              onChange({
                ...filters,
                status: (e.target.value || undefined) as ManuscriptStatus | undefined,
              })
            }
          >
            <option value="">any</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="filter-kind">Kind</Label>
          <select
            id="filter-kind"
            className="h-9 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
            value={filters.kind ?? ""}
            onChange={(e) =>
              onChange({
                ...filters,
                kind: (e.target.value || undefined) as ManuscriptKind | undefined,
              })
            }
          >
            <option value="">any</option>
            {KIND_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-1 flex-col gap-1">
          <Label htmlFor="filter-tag">Tag</Label>
          <Input
            id="filter-tag"
            placeholder="e.g. survey-2026"
            value={filters.tag ?? ""}
            onChange={(e) => onChange({ ...filters, tag: e.target.value || undefined })}
          />
        </div>
        <Button
          variant="outline"
          onClick={() => onChange({ limit: filters.limit ?? 100 })}
          className="h-9"
        >
          Reset
        </Button>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Create
// ---------------------------------------------------------------------------

function CreateManuscriptCard({ onDone }: { onDone: () => void }) {
  const qc = useQueryClient();
  const [title, setTitle] = useState("");
  const [kind, setKind] = useState<ManuscriptKind>("paper");
  const [topic, setTopic] = useState("");
  const [tags, setTags] = useState("");
  const [content, setContent] = useState("");

  const create = useMutation({
    mutationFn: () =>
      manuscriptsApi.create({
        title: title.trim(),
        kind,
        topic: topic.trim() || null,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
        content: content.trim(),
      }),
    onSuccess: (env) => {
      toast.success(`Created "${env.manuscript.title || env.manuscript.id}"`);
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
      onDone();
    },
    onError: (err: Error) => toast.error(`Create failed: ${err.message}`),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">New manuscript</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-0 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="m-title">Title</Label>
          <Input
            id="m-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="A Survey on …"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="m-kind">Kind</Label>
          <select
            id="m-kind"
            className="h-9 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
            value={kind}
            onChange={(e) => setKind(e.target.value as ManuscriptKind)}
          >
            {KIND_OPTIONS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="m-topic">Topic</Label>
          <Input
            id="m-topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="multi-task RL"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="m-tags">Tags (comma separated)</Label>
          <Input id="m-tags" value={tags} onChange={(e) => setTags(e.target.value)} />
        </div>
        <div className="sm:col-span-2 flex flex-col gap-1">
          <Label htmlFor="m-content">Initial markdown (optional, commits as v1)</Label>
          <Textarea
            id="m-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="# My paper&#10;&#10;Outline / abstract…"
            className="min-h-32 font-mono text-xs"
          />
        </div>
        <div className="sm:col-span-2 flex justify-end gap-2">
          <Button variant="outline" onClick={onDone} disabled={create.isPending}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Upload
// ---------------------------------------------------------------------------

function UploadButton() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const upload = useMutation({
    mutationFn: (file: File) => manuscriptsApi.upload({ file, title: file.name }),
    onSuccess: (env) => {
      toast.success(
        `Uploaded "${env.manuscript.title}" (v${env.manuscript.current_version})`,
      );
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
    },
    onError: (err: Error) => toast.error(`Upload failed: ${err.message}`),
  });

  return (
    <label className="inline-flex">
      <input
        type="file"
        accept=".md,.markdown,.txt,.pdf,application/pdf,text/markdown,text/plain"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload.mutate(f);
          e.target.value = "";
        }}
      />
      <span
        role="button"
        tabIndex={0}
        className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-4 text-sm font-medium hover:bg-[var(--color-accent)]"
      >
        <Upload className="h-4 w-4" />
        {upload.isPending ? t("manuscripts.uploading") : t("manuscripts.upload")}
      </span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Upload zip — turns a project archive into a bundle manuscript
// ---------------------------------------------------------------------------

function UploadZipButton() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const upload = useMutation({
    mutationFn: (file: File) =>
      manuscriptsApi.importZip({ file, title: file.name.replace(/\.zip$/i, "") }),
    onSuccess: (m) => {
      toast.success(t("manuscripts.importSuccess", { title: m.title }));
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
    },
    onError: (err: Error) =>
      toast.error(t("manuscripts.importFailed", { error: err.message })),
  });
  return (
    <label className="inline-flex">
      <input
        type="file"
        accept=".zip,application/zip"
        className="sr-only"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) upload.mutate(f);
          e.target.value = "";
        }}
      />
      <span
        role="button"
        tabIndex={0}
        className="inline-flex h-9 cursor-pointer items-center gap-2 rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-4 text-sm font-medium hover:bg-[var(--color-accent)]"
      >
        {upload.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <FileArchive className="h-4 w-4" />}
        {upload.isPending ? t("manuscripts.importingZip") : t("manuscripts.importZip")}
      </span>
    </label>
  );
}

// ---------------------------------------------------------------------------
// Import folder card — copy / link a local project directory
// ---------------------------------------------------------------------------

function ImportFolderCard({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [path, setPath] = useState("");
  const [mode, setMode] = useState<"copy" | "link">("copy");
  const [title, setTitle] = useState("");

  const importMut = useMutation({
    mutationFn: () =>
      manuscriptsApi.importFolder({
        local_path: path.trim(),
        mode,
        title: title.trim() || undefined,
      }),
    onSuccess: (m) => {
      toast.success(t("manuscripts.importSuccess", { title: m.title }));
      void qc.invalidateQueries({ queryKey: ["manuscripts"] });
      onDone();
    },
    onError: (err: Error) =>
      toast.error(t("manuscripts.importFailed", { error: err.message })),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-sm">{t("manuscripts.importFolderTitle")}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3 p-4 pt-0">
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t("manuscripts.importFolderDescription")}
        </p>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1 sm:col-span-2">
            <Label htmlFor="if-path">{t("manuscripts.importFolderPathLabel")}</Label>
            <Input
              id="if-path"
              value={path}
              onChange={(e) => setPath(e.target.value)}
              placeholder={t("manuscripts.importFolderPathPlaceholder")}
              className="font-mono text-xs"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="if-mode">{t("manuscripts.importFolderModeLabel")}</Label>
            <select
              id="if-mode"
              className="h-9 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
              value={mode}
              onChange={(e) => setMode(e.target.value as "copy" | "link")}
            >
              <option value="copy">{t("manuscripts.importFolderModeCopy")}</option>
              <option value="link">{t("manuscripts.importFolderModeLink")}</option>
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="if-title">{t("manuscripts.importFolderTitleLabel")}</Label>
            <Input
              id="if-title"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="paper-dataagent-eval"
            />
          </div>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onDone} disabled={importMut.isPending}>
            {t("common.cancel")}
          </Button>
          <Button onClick={() => importMut.mutate()} disabled={importMut.isPending || !path.trim()}>
            {importMut.isPending ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <FolderInput className="h-4 w-4" />
            )}
            {importMut.isPending
              ? t("manuscripts.importFolderImporting")
              : t("manuscripts.importFolderSubmit")}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
