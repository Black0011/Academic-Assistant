/**
 * Bundle explorer — file tree + Monaco editor for project-shaped manuscripts.
 *
 * Renders inside `PaperWriterPage` when `manuscript.layout === "bundle"`. The
 * single-document path (`layout === "single"`) keeps using the prior version
 * timeline + editor and is unaffected.
 *
 * Architecture:
 *   - Tree pane (left, ~18rem):  flat manifest from `GET /tree`, filterable.
 *   - Editor pane (right):       Monaco for text files; "binary" placeholder
 *                                with a Download link for everything else.
 *   - Toolbar (top):             Save / New file / Upload / Delete /
 *                                Download zip / Download Overleaf zip.
 *
 * All API calls go through `manuscriptsApi` (which goes through `lib/api.ts`),
 * so the consistency check (no inline fetch) stays green.
 */

import { loader } from "@monaco-editor/react";
import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

loader.config({ paths: { vs: "/monaco-vs" } });
import { formatDistanceToNow } from "date-fns";
import {
  ChevronRight,
  Download,
  File,
  FileArchive,
  Folder,
  FolderOpen,
  Link as LinkIcon,
  Loader2,
  Plus,
  Save,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { manuscriptsApi } from "@/lib/manuscripts";
import { useUiStore } from "@/stores/uiStore";
import type { Manuscript, ManuscriptFile } from "@/types/api";

interface BundleExplorerProps {
  manuscript: Manuscript;
}

export function BundleExplorer({ manuscript }: BundleExplorerProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const themeMode = useUiStore((s) => s.theme);
  const isDark = useIsDark(themeMode);

  const [selectedPath, setSelectedPath] = useState<string | null>(null);
  const [filter, setFilter] = useState("");

  const treeQuery = useQuery({
    queryKey: ["bundle-tree", manuscript.id],
    queryFn: () => manuscriptsApi.tree(manuscript.id),
  });

  const filteredFiles = useMemo(() => {
    const all = treeQuery.data?.files ?? [];
    if (!filter.trim()) return all;
    const q = filter.toLowerCase();
    return all.filter((f) => f.path.toLowerCase().includes(q));
  }, [treeQuery.data, filter]);

  return (
    <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[20rem_1fr]">
      <Card className="flex min-h-0 flex-col">
        <CardHeader className="p-3 pb-2">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-sm">{t("bundle.tree")}</CardTitle>
            <BundleToolbar manuscript={manuscript} disabled={treeQuery.isLoading} />
          </div>
          <BundleHeaderMeta manuscript={manuscript} manifestFileCount={treeQuery.data?.file_count ?? 0} />
          <Input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder={t("bundle.filterPathPlaceholder")}
            className="mt-2 h-8 text-xs"
            aria-label={t("bundle.filterPathPlaceholder")}
          />
        </CardHeader>
        <CardContent className="min-h-0 flex-1 overflow-y-auto p-0">
          {treeQuery.isLoading ? (
            <div className="p-4">
              <Skeleton className="h-32 w-full" />
            </div>
          ) : treeQuery.isError ? (
            <p className="p-4 text-xs text-[var(--color-destructive)]">
              {t("bundle.treeError", { error: (treeQuery.error as Error).message })}
            </p>
          ) : filteredFiles.length === 0 ? (
            <p className="p-4 text-xs text-[var(--color-muted-foreground)]">
              {treeQuery.data && treeQuery.data.file_count === 0
                ? t("bundle.noFiles")
                : t("common.none")}
            </p>
          ) : (
            <BundleFileTree
              files={filteredFiles}
              selected={selectedPath}
              onSelect={setSelectedPath}
            />
          )}
        </CardContent>
      </Card>

      <Card className="flex min-h-0 flex-col">
        {selectedPath ? (
          <FileEditor
            manuscriptId={manuscript.id}
            path={selectedPath}
            onDeleted={() => {
              setSelectedPath(null);
              void qc.invalidateQueries({ queryKey: ["bundle-tree", manuscript.id] });
            }}
            isDark={isDark}
          />
        ) : (
          <CardContent className="flex flex-1 items-center justify-center p-6 text-sm text-[var(--color-muted-foreground)]">
            {t("bundle.selectFileHint")}
          </CardContent>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header meta
// ---------------------------------------------------------------------------

function BundleHeaderMeta({
  manuscript,
  manifestFileCount,
}: {
  manuscript: Manuscript;
  manifestFileCount: number;
}) {
  const { t } = useTranslation();
  const linked = manuscript.bundle_link_path !== null;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-[var(--color-muted-foreground)]">
      <Badge variant={linked ? "warning" : "neutral"} className="text-[10px]">
        {linked ? <LinkIcon className="mr-1 inline h-3 w-3" /> : null}
        {linked ? t("manuscripts.linkBadge") : t("manuscripts.layoutBundle")}
      </Badge>
      <span>{t("bundle.fileCount", { count: manifestFileCount })}</span>
      {linked ? (
        <span className="truncate" title={manuscript.bundle_link_path ?? undefined}>
          {t("bundle.linkMode", { path: shortPath(manuscript.bundle_link_path ?? "") })}
        </span>
      ) : (
        <span className="truncate">{t("bundle.copyMode")}</span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Toolbar — new file / upload / download zip
// ---------------------------------------------------------------------------

function BundleToolbar({
  manuscript,
  disabled,
}: {
  manuscript: Manuscript;
  disabled: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const newFileMut = useMutation({
    mutationFn: (path: string) =>
      manuscriptsApi.writeTextFile(manuscript.id, path, { content: "" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["bundle-tree", manuscript.id] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const uploadMut = useMutation({
    mutationFn: ({ path, file }: { path: string; file: File }) =>
      manuscriptsApi.uploadBundleFile(manuscript.id, path, file),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["bundle-tree", manuscript.id] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  return (
    <div className="flex items-center gap-1">
      <Button
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => {
          const path = window.prompt(t("bundle.newFile"), t("bundle.newFilePlaceholder"));
          if (path?.trim()) newFileMut.mutate(path.trim());
        }}
        title={t("bundle.newFile")}
      >
        <Plus className="h-3 w-3" />
      </Button>

      <label
        className={
          "inline-flex h-8 cursor-pointer items-center gap-1 rounded-md border " +
          "border-[var(--color-border)] bg-[var(--color-background)] px-2 text-xs " +
          (disabled || uploadMut.isPending ? "pointer-events-none opacity-60" : "hover:bg-[var(--color-accent)]")
        }
        title={t("bundle.uploadHere")}
      >
        <input
          type="file"
          className="sr-only"
          disabled={disabled || uploadMut.isPending}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (!f) return;
            const path = window.prompt(t("bundle.uploadHere"), f.name);
            if (path?.trim()) uploadMut.mutate({ path: path.trim(), file: f });
            e.target.value = "";
          }}
        />
        {uploadMut.isPending ? (
          <Loader2 className="h-3 w-3 animate-spin" />
        ) : (
          <Upload className="h-3 w-3" />
        )}
      </label>

      <a
        href={manuscriptsApi.exportZipUrl(manuscript.id)}
        className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--color-border)] bg-[var(--color-background)] px-2 text-xs hover:bg-[var(--color-accent)]"
        title={t("bundle.downloadOverleaf")}
      >
        <FileArchive className="h-3 w-3" />
      </a>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Hierarchical file tree — recursive expand/collapse
// ---------------------------------------------------------------------------

/** A node in the virtual tree built from the flat ManuscriptFile list. */
interface TreeNode {
  name: string;
  path: string; // full relative path ("experiments/results" or "experiments/results/data.csv")
  isDir: boolean;
  children: TreeNode[];
  file?: ManuscriptFile; // present only for leaf files
}

/** Build a hierarchical tree from a flat list of files with POSIX-relative paths. */
function buildTree(files: ManuscriptFile[]): TreeNode[] {
  const root: TreeNode = { name: "", path: "", isDir: true, children: [] };

  for (const f of files) {
    const segments = f.path.split("/");
    let current = root;
    for (let i = 0; i < segments.length; i++) {
      const seg = segments[i];
      const partialPath = segments.slice(0, i + 1).join("/");
      const isLast = i === segments.length - 1;
      let child = current.children.find((c) => c.name === seg && c.isDir === !isLast);
      if (!child) {
        // Also check for a dir node that may already exist if a deeper file created it
        if (!isLast) {
          child = current.children.find((c) => c.name === seg && c.isDir);
        }
        if (!child) {
          child = {
            name: seg,
            path: partialPath,
            isDir: !isLast,
            children: [],
            file: isLast ? f : undefined,
          };
          current.children.push(child);
        }
      }
      current = child;
    }
  }

  // Sort recursively: directories first (alphabetical), then files (alphabetical)
  function sortTree(nodes: TreeNode[]): TreeNode[] {
    for (const n of nodes) {
      if (n.children.length > 0) n.children = sortTree(n.children);
    }
    return nodes.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      return a.name.localeCompare(b.name);
    });
  }

  return sortTree(root.children);
}

/** Collect all directory paths from a tree (for expand-all). */
function collectDirPaths(nodes: TreeNode[]): string[] {
  const result: string[] = [];
  for (const n of nodes) {
    if (n.isDir) {
      result.push(n.path);
      result.push(...collectDirPaths(n.children));
    }
  }
  return result;
}

export function BundleFileTree({
  files,
  selected,
  onSelect,
  multiSelect = false,
  checked = new Set(),
  onCheckChange,
  recentlyModified = new Set(),
}: {
  files: ManuscriptFile[];
  selected: string | null;
  onSelect: (path: string) => void;
  multiSelect?: boolean;
  checked?: Set<string>;
  onCheckChange?: (checked: Set<string>) => void;
  recentlyModified?: Set<string>;
}) {
  const { t } = useTranslation();
  const tree = useMemo(() => buildTree(files), [files]);
  const allDirs = useMemo(() => collectDirPaths(tree), [tree]);

  // Default: expand top-level directories
  const [expanded, setExpanded] = useState<Set<string>>(() => {
    return new Set(tree.filter((n) => n.isDir).map((n) => n.path));
  });

  // Re-expand top-level when tree changes (e.g. filter applied)
  useEffect(() => {
    setExpanded(new Set(tree.filter((n) => n.isDir).map((n) => n.path)));
  }, [tree]);

  const toggle = useCallback((path: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  }, []);

  const expandAll = useCallback(() => setExpanded(new Set(allDirs)), [allDirs]);
  const collapseAll = useCallback(() => setExpanded(new Set()), []);

  if (files.length === 0) return null;

  return (
    <div>
      <div className="flex items-center justify-end gap-1 border-b px-2 py-1">
        <button
          type="button"
          onClick={expandAll}
          className="text-[10px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
        >
          {t("bundle.expandAll")}
        </button>
        <span className="text-[10px] text-[var(--color-muted-foreground)]">/</span>
        <button
          type="button"
          onClick={collapseAll}
          className="text-[10px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
        >
          {t("bundle.collapseAll")}
        </button>
      </div>
      <ul className="text-sm">
        {tree.map((node) => (
          <TreeNodeRow
            key={node.path}
            node={node}
            depth={0}
            selected={selected}
            expanded={expanded}
            onSelect={onSelect}
            onToggle={toggle}
            multiSelect={multiSelect}
            checked={checked}
            onCheckChange={onCheckChange}
          />
        ))}
      </ul>
    </div>
  );
}

function TreeNodeRow({
  node,
  depth,
  selected,
  expanded,
  onSelect,
  onToggle,
  multiSelect = false,
  checked = new Set(),
  onCheckChange,
  recentlyModified = new Set(),
}: {
  node: TreeNode;
  depth: number;
  selected: string | null;
  expanded: Set<string>;
  onSelect: (path: string) => void;
  onToggle: (path: string) => void;
  multiSelect?: boolean;
  checked?: Set<string>;
  onCheckChange?: (checked: Set<string>) => void;
  recentlyModified?: Set<string>;
}) {
  const isOpen = expanded.has(node.path);

  if (node.isDir) {
    const childFileCount = countFiles(node);
    // P15: folder-level select — checkbox toggles all files recursively
    const allChildFiles = collectFilePaths(node);
    const checkedCount = allChildFiles.filter((f) => checked.has(f)).length;
    const isAllChecked = checkedCount === allChildFiles.length && allChildFiles.length > 0;
    const isPartialChecked = checkedCount > 0 && !isAllChecked;

    const handleFolderCheck = () => {
      if (!onCheckChange) return;
      const next = new Set(checked);
      if (isAllChecked) {
        // Uncheck all
        for (const f of allChildFiles) next.delete(f);
      } else {
        // Check all
        for (const f of allChildFiles) next.add(f);
      }
      onCheckChange(next);
    };

    return (
      <li>
        <div
          className="flex w-full items-center gap-1.5 py-1 text-left text-xs hover:bg-[var(--color-muted)]"
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
        >
          <button
            type="button"
            onClick={() => onToggle(node.path)}
            className="flex items-center gap-1"
            title={node.path}
          >
            <ChevronRight
              className={
                "h-3 w-3 shrink-0 text-[var(--color-muted-foreground)] transition-transform " +
                (isOpen ? "rotate-90" : "")
              }
            />
          </button>
          {multiSelect ? (
            <button
              type="button"
              onClick={handleFolderCheck}
              className="flex items-center gap-1.5"
              title={`${isAllChecked ? "Deselect" : "Select"} all ${childFileCount} files in ${node.name}`}
            >
              <input
                type="checkbox"
                checked={isAllChecked}
                ref={(el) => {
                  if (el) el.indeterminate = isPartialChecked;
                }}
                onChange={() => {}}  /* handled by parent button */
                className="h-3 w-3 shrink-0 accent-[var(--color-primary)]"
                aria-label={`${isAllChecked ? "Deselect" : "Select"} folder ${node.path}`}
              />
              {isOpen ? (
                <FolderOpen className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
              )}
              <span className="truncate font-medium">{node.name}</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onToggle(node.path)}
              className="flex items-center gap-1.5"
            >
              {isOpen ? (
                <FolderOpen className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
              ) : (
                <Folder className="h-3.5 w-3.5 shrink-0 text-[var(--color-primary)]" />
              )}
              <span className="truncate font-medium">{node.name}</span>
            </button>
          )}
          <span className="ml-auto pr-2 text-[10px] text-[var(--color-muted-foreground)]">
            {multiSelect && allChildFiles.length > 0
              ? `${checkedCount}/${allChildFiles.length}`
              : childFileCount}
          </span>
        </div>
        {isOpen ? (
          <ul>
            {node.children.map((child) => (
              <TreeNodeRow
                key={child.path}
                node={child}
                depth={depth + 1}
                selected={selected}
                expanded={expanded}
                onSelect={onSelect}
                onToggle={onToggle}
                multiSelect={multiSelect}
                checked={checked}
                onCheckChange={onCheckChange}
                recentlyModified={recentlyModified}
              />
            ))}
          </ul>
        ) : null}
      </li>
    );
  }

  // File node — show checkbox in multiSelect mode
  const isChecked = checked.has(node.path);
  const isModified = recentlyModified.has(node.path);
  const handleClick = () => {
    if (multiSelect && onCheckChange) {
      const next = new Set(checked);
      if (isChecked) next.delete(node.path);
      else next.add(node.path);
      onCheckChange(next);
    } else {
      onSelect(node.path);
    }
  };

  const mtime = node.file?.modified_at
    ? new Date(node.file.modified_at)
    : null;
  const mtimeStr = mtime
    ? mtime.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : "";

  return (
    <li>
      <button
        type="button"
        onClick={handleClick}
        className={
          "flex w-full items-center gap-1.5 py-1 text-left text-xs hover:bg-[var(--color-muted)] " +
          (isModified ? "bg-[var(--color-success)]/10 " : "") +
          (selected === node.path && !multiSelect ? "bg-[var(--color-accent)] font-medium" : "")
        }
        style={{ paddingLeft: `${depth * 16 + 8 + 16}px` }}
        title={node.path + (mtime ? ` — modified ${mtime.toLocaleString()}` : "")}
      >
        {multiSelect ? (
          <input
            type="checkbox"
            checked={isChecked}
            onChange={() => {}}
            className="h-3 w-3 shrink-0 accent-[var(--color-primary)]"
            aria-label={`Select ${node.path}`}
          />
        ) : (
          <File className={`h-3 w-3 shrink-0 ${isModified ? "text-[var(--color-success)]" : "text-[var(--color-muted-foreground)]"}`} />
        )}
        <span className="truncate">{node.name}</span>
        {isModified && (
          <span className="shrink-0 text-[9px] text-[var(--color-success)]">modified</span>
        )}
        <span className="ml-auto whitespace-nowrap pr-2 text-[9px] text-[var(--color-muted-foreground)]" title={mtime?.toLocaleString()}>
          {mtimeStr}
        </span>
      </button>
    </li>
  );
}

/** Count all files (leaves) under a directory node recursively. */
function countFiles(node: TreeNode): number {
  let count = 0;
  for (const child of node.children) {
    if (child.isDir) count += countFiles(child);
    else count += 1;
  }
  return count;
}

/** Collect all file paths under a directory node recursively. */
function collectFilePaths(node: TreeNode): string[] {
  const result: string[] = [];
  for (const child of node.children) {
    if (child.isDir) result.push(...collectFilePaths(child));
    else result.push(child.path);
  }
  return result;
}

// ---------------------------------------------------------------------------
// File editor
// ---------------------------------------------------------------------------

function FileEditor({
  manuscriptId,
  path,
  onDeleted,
  isDark,
}: {
  manuscriptId: string;
  path: string;
  onDeleted: () => void;
  isDark: boolean;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const reviseEligible = /\.(tex|md|txt|rst)$/i.test(path);

  const fileQuery = useQuery({
    queryKey: ["bundle-file", manuscriptId, path],
    queryFn: () => manuscriptsApi.readFile(manuscriptId, path, { text: true }),
  });

  const [draft, setDraft] = useState<string>("");
  const initial = useRef<string>("");
  useEffect(() => {
    if (fileQuery.data && fileQuery.data.encoding === "utf-8") {
      setDraft(fileQuery.data.content);
      initial.current = fileQuery.data.content;
    }
  }, [fileQuery.data?.file.path, fileQuery.data?.encoding, fileQuery.data?.content]);

  const dirty = draft !== initial.current;

  const saveMut = useMutation({
    mutationFn: () =>
      manuscriptsApi.writeTextFile(manuscriptId, path, { content: draft }),
    onSuccess: (meta) => {
      initial.current = draft;
      toast.success(t("bundle.saved"));
      // Refresh tree (size/mtime may change).
      void qc.invalidateQueries({ queryKey: ["bundle-tree", manuscriptId] });
      void qc.invalidateQueries({ queryKey: ["bundle-file", manuscriptId, meta.path] });
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const deleteMut = useMutation({
    mutationFn: () => manuscriptsApi.deleteFile(manuscriptId, path),
    onSuccess: () => {
      toast.success(`${path}`);
      onDeleted();
    },
    onError: (err: Error) => toast.error(err.message),
  });

  const isText = fileQuery.data?.encoding === "utf-8";
  const language = languageForPath(path);

  return (
    <>
      <CardHeader className="flex-row items-center justify-between gap-2 p-3">
        <div className="min-w-0">
          <CardTitle className="truncate text-sm" title={path}>
            {path}
          </CardTitle>
          {fileQuery.data ? (
            <p className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
              {humanBytes(fileQuery.data.file.size)} ·{" "}
              {t("bundle.modifiedAt", {
                when: formatDistanceToNow(new Date(fileQuery.data.file.modified_at), {
                  addSuffix: true,
                }),
              })}
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          <a
            href={manuscriptsApi.downloadFileUrl(manuscriptId, path)}
            className="inline-flex h-8 items-center gap-1 rounded-md border border-[var(--color-border)] px-2 text-xs hover:bg-[var(--color-accent)]"
            title={t("bundle.downloadFile")}
          >
            <Download className="h-3 w-3" />
          </a>
          <Button
            size="sm"
            variant="outline"
            disabled={!reviseEligible}
            title={
              reviseEligible
                ? t("bundle.reviseThisFileHint")
                : t("bundle.reviseTextOnly")
            }
            onClick={() =>
              navigate(
                `/revision?manuscript=${encodeURIComponent(
                  manuscriptId,
                )}&bundle_target=${encodeURIComponent(path)}`,
              )
            }
          >
            <Sparkles className="h-3 w-3" />
            {t("bundle.reviseThisFile")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={deleteMut.isPending}
            onClick={() => {
              if (window.confirm(t("bundle.deleteConfirm", { path }))) deleteMut.mutate();
            }}
          >
            <Trash2 className="h-3 w-3" />
          </Button>
          {isText ? (
            <Button
              size="sm"
              disabled={!dirty || saveMut.isPending}
              onClick={() => saveMut.mutate()}
              title={dirty ? t("bundle.save") : t("bundle.saved")}
            >
              {saveMut.isPending ? (
                <Loader2 className="h-3 w-3 animate-spin" />
              ) : (
                <Save className="h-3 w-3" />
              )}
              {saveMut.isPending ? t("bundle.saving") : t("bundle.save")}
            </Button>
          ) : null}
        </div>
      </CardHeader>
      <CardContent className="min-h-0 flex-1 p-0">
        {fileQuery.isLoading ? (
          <div className="p-4">
            <Skeleton className="h-full w-full" />
          </div>
        ) : fileQuery.isError ? (
          <p className="p-4 text-xs text-[var(--color-destructive)]">
            {(fileQuery.error as Error).message}
          </p>
        ) : isText ? (
          <Editor
            height="100%"
            language={language}
            value={draft}
            onChange={(v) => setDraft(v ?? "")}
            theme={isDark ? "vs-dark" : "vs"}
            options={{
              fontSize: 13,
              wordWrap: "on",
              minimap: { enabled: false },
              scrollBeyondLastLine: false,
              padding: { top: 12, bottom: 12 },
              fontFamily:
                'ui-monospace, SFMono-Regular, "SF Mono", Menlo, monospace',
            }}
          />
        ) : (
          <div className="p-6 text-sm text-[var(--color-muted-foreground)]">
            {t("bundle.binaryFile", {
              mime: fileQuery.data?.file.mime ?? "?",
              size: humanBytes(fileQuery.data?.file.size ?? 0),
            })}
          </div>
        )}
      </CardContent>
    </>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function humanBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function shortPath(path: string): string {
  if (path.length <= 36) return path;
  return `…${path.slice(-35)}`;
}

const LANGUAGE_BY_EXT: Record<string, string> = {
  md: "markdown",
  markdown: "markdown",
  txt: "plaintext",
  tex: "latex",
  bib: "bibtex",
  sty: "latex",
  cls: "latex",
  bst: "plaintext",
  yaml: "yaml",
  yml: "yaml",
  json: "json",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  py: "python",
  js: "javascript",
  ts: "typescript",
  tsx: "typescript",
  jsx: "javascript",
  sh: "shell",
  bat: "bat",
  html: "html",
  xml: "xml",
  css: "css",
};

function languageForPath(path: string): string {
  const idx = path.lastIndexOf(".");
  if (idx === -1) return "plaintext";
  const ext = path.slice(idx + 1).toLowerCase();
  return LANGUAGE_BY_EXT[ext] ?? "plaintext";
}

function useIsDark(themeMode: string): boolean {
  return (
    themeMode === "dark" ||
    (themeMode === "system" &&
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-color-scheme: dark)").matches)
  );
}
