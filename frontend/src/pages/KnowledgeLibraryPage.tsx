/**
 * Knowledge Library page (M7.3).
 *
 * Layout: a left list of ingested documents and a right-hand panel with
 * three tabs — **Body** (raw markdown / pdf-extracted text), **Chunks**
 * (the indexed slices the RAG layer sees), and **Search** (live results
 * from `/api/documents/search`). An "Ingest document" drawer accepts a
 * file drop *or* a markdown / clipboard paste.
 *
 * The wire is small and stateless — TanStack Query handles caching,
 * invalidation on mutation, and the steady polling of the list.
 */
import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  ChevronRight,
  FileText,
  Library,
  Plus,
  RefreshCcw,
  Search,
  Trash2,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { documentsApi } from "@/lib/documents";
import { useUiStore } from "@/stores/uiStore";
import type {
  DocChunk,
  DocChunkHit,
  DocumentSourceKind,
  KnowledgeDocument,
} from "@/types/api";

type DetailTab = "body" | "chunks" | "search";

const SOURCE_KINDS: DocumentSourceKind[] = [
  "note",
  "md_upload",
  "txt_upload",
  "pdf_upload",
  "url",
  "clipboard",
];

function isDarkMode(theme: "light" | "dark" | "system"): boolean {
  if (typeof window === "undefined") return false;
  if (theme === "dark") return true;
  if (theme === "system") {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  }
  return false;
}

function fmtBytes(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function relTime(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function KnowledgeLibraryPage() {
  const { t } = useTranslation();
  const params = useParams();
  const navigate = useNavigate();
  const selected = params.docId ?? null;
  const [ingestOpen, setIngestOpen] = useState(false);
  const [tagFilter, setTagFilter] = useState("");

  const list = useQuery({
    queryKey: ["library", "list", { tagFilter }],
    queryFn: () => documentsApi.list({ tag: tagFilter || undefined, limit: 200 }),
    refetchInterval: 30_000,
  });

  const docs = list.data?.items ?? [];

  const handleSelect = (docId: string): void => {
    void navigate(`/library/${encodeURIComponent(docId)}`);
  };
  const handleClose = (): void => {
    void navigate("/library");
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("library.title")}
        description={t("library.description")}
        actions={
          <div className="flex items-center gap-2">
            <Input
              placeholder="Filter by tag"
              className="h-8 w-40 text-xs"
              value={tagFilter}
              onChange={(event) => setTagFilter(event.target.value)}
            />
            <Button size="sm" onClick={() => setIngestOpen(true)} className="gap-1">
              <Plus className="h-3.5 w-3.5" /> Ingest document
            </Button>
          </div>
        }
      />

      <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
        <DocumentList
          docs={docs}
          loading={list.isLoading}
          error={list.isError ? (list.error as Error) : null}
          selected={selected}
          onSelect={handleSelect}
        />

        {selected ? (
          <DocumentDetailPanel docId={selected} onClose={handleClose} />
        ) : (
          <EmptyState
            icon={Library}
            title={docs.length === 0 ? "No documents yet" : "Pick a document"}
            description={
              docs.length === 0
                ? "Drop a markdown file or paste any chunk of text to seed the RAG corpus."
                : "Select a document on the left to see its body, chunks, and run RAG searches against it."
            }
            action={
              docs.length === 0 ? (
                <Button size="sm" onClick={() => setIngestOpen(true)}>
                  Ingest document
                </Button>
              ) : null
            }
          />
        )}
      </div>

      {ingestOpen && (
        <IngestDrawer
          onClose={() => setIngestOpen(false)}
          onIngested={(docId) => {
            setIngestOpen(false);
            handleSelect(docId);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

function DocumentList({
  docs,
  loading,
  error,
  selected,
  onSelect,
}: {
  docs: KnowledgeDocument[];
  loading: boolean;
  error: Error | null;
  selected: string | null;
  onSelect: (docId: string) => void;
}) {
  return (
    <Card className="h-fit">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Library className="h-4 w-4" /> Documents
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {error && (
          <p className="text-xs text-[var(--color-destructive)]">
            Failed to load: {error.message}
          </p>
        )}
        {!loading && !error && docs.length === 0 && (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            No documents match the current filter.
          </p>
        )}
        <ul className="space-y-1">
          {docs.map((doc) => (
            <li key={doc.doc_id}>
              <button
                type="button"
                onClick={() => onSelect(doc.doc_id)}
                className={cn(
                  "w-full rounded-md border px-3 py-2 text-left text-xs transition-colors",
                  selected === doc.doc_id
                    ? "border-[var(--color-primary)] bg-[var(--color-accent)]"
                    : "border-transparent hover:bg-[var(--color-accent)]/60",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-semibold">{doc.title}</span>
                  <Badge variant="outline">{doc.source_kind}</Badge>
                </div>
                {doc.summary && (
                  <p className="mt-1 line-clamp-2 text-[11px] text-[var(--color-muted-foreground)]">
                    {doc.summary}
                  </p>
                )}
                <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-[var(--color-muted-foreground)]">
                  <span>
                    {doc.chunk_ids.length} chunks · {fmtBytes(doc.bytes)}
                  </span>
                  <span>{relTime(doc.updated_at)}</span>
                </div>
                {doc.tags.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {doc.tags.slice(0, 4).map((tag) => (
                      <span
                        key={tag}
                        className="rounded bg-[var(--color-muted)]/60 px-1.5 py-0.5 text-[10px] text-[var(--color-muted-foreground)]"
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                )}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function DocumentDetailPanel({
  docId,
  onClose,
}: {
  docId: string;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const [tab, setTab] = useState<DetailTab>("body");

  const docQ = useQuery({
    queryKey: ["library", "doc", docId],
    queryFn: () => documentsApi.get(docId),
  });

  const reindex = useMutation({
    mutationFn: () => documentsApi.reindex(docId),
    onSuccess: (resp) => {
      toast.success(`Re-indexed: ${resp.chunks_indexed} chunks in ${resp.indexer_ms} ms`);
      void qc.invalidateQueries({ queryKey: ["library"] });
    },
    onError: (err: Error) => toast.error(`Re-index failed: ${err.message}`),
  });

  const remove = useMutation({
    mutationFn: () => documentsApi.delete(docId),
    onSuccess: () => {
      toast.success("Document deleted");
      void qc.invalidateQueries({ queryKey: ["library"] });
      onClose();
    },
    onError: (err: Error) => toast.error(`Delete failed: ${err.message}`),
  });

  if (docQ.isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 p-6">
          <Skeleton className="h-6 w-1/2" />
          <Skeleton className="h-4 w-full" />
          <Skeleton className="h-72 w-full" />
        </CardContent>
      </Card>
    );
  }
  if (docQ.isError || !docQ.data) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 p-6">
          <div className="flex items-center gap-2 text-sm text-[var(--color-destructive)]">
            <AlertTriangle className="h-4 w-4" />
            Failed to load: {(docQ.error as Error)?.message ?? "not found"}
          </div>
          <Button size="sm" variant="outline" onClick={onClose}>
            Back
          </Button>
        </CardContent>
      </Card>
    );
  }

  const doc = docQ.data;

  return (
    <Card className="flex min-h-[40rem] flex-col">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <CardTitle className="truncate text-base">{doc.title}</CardTitle>
              <Badge variant="outline">{doc.source_kind}</Badge>
              <Badge variant="neutral">{doc.chunk_ids.length} chunks</Badge>
              <Badge variant="neutral">{fmtBytes(doc.bytes)}</Badge>
            </div>
            {doc.summary && (
              <p className="line-clamp-2 text-sm text-[var(--color-muted-foreground)]">
                {doc.summary}
              </p>
            )}
            {doc.source_uri && (
              <p className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
                {doc.source_uri}
              </p>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() => reindex.mutate()}
              disabled={reindex.isPending}
              className="gap-1"
            >
              <RefreshCcw className={cn("h-3.5 w-3.5", reindex.isPending && "animate-spin")} />
              Re-index
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                if (window.confirm(`Delete "${doc.title}"? Chunks will be removed from the vector store.`)) {
                  remove.mutate();
                }
              }}
              disabled={remove.isPending}
              className="gap-1"
            >
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
            <Button size="sm" variant="ghost" onClick={onClose} className="gap-1">
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        <DetailTabs tab={tab} onChange={setTab} />
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {tab === "body" && <BodyTab doc={doc} />}
        {tab === "chunks" && <ChunksTab docId={doc.doc_id} />}
        {tab === "search" && <SearchTab docId={doc.doc_id} />}
      </CardContent>
    </Card>
  );
}

function DetailTabs({
  tab,
  onChange,
}: {
  tab: DetailTab;
  onChange: (next: DetailTab) => void;
}) {
  const TABS: ReadonlyArray<{ id: DetailTab; label: string; icon: typeof FileText }> = [
    { id: "body", label: "Body", icon: FileText },
    { id: "chunks", label: "Chunks", icon: ChevronRight },
    { id: "search", label: "Search", icon: Search },
  ];
  return (
    <div className="mt-3 flex flex-wrap items-center gap-1 rounded-md border bg-[var(--color-card)]/40 p-1">
      {TABS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={cn(
            "inline-flex items-center gap-1.5 rounded px-2.5 py-1.5 text-xs font-medium transition-colors",
            tab === id
              ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
              : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)] hover:text-[var(--color-accent-foreground)]",
          )}
        >
          <Icon className="h-3.5 w-3.5" />
          {label}
        </button>
      ))}
    </div>
  );
}

function BodyTab({ doc }: { doc: KnowledgeDocument }) {
  const themeMode = useUiStore((s) => s.theme);
  const isDark = isDarkMode(themeMode);
  return (
    <div className="h-[34rem]">
      <Editor
        height="100%"
        defaultLanguage="markdown"
        value={doc.raw_text}
        theme={isDark ? "vs-dark" : "vs"}
        options={{
          readOnly: true,
          fontSize: 13,
          wordWrap: "on",
          minimap: { enabled: false },
          scrollBeyondLastLine: false,
          padding: { top: 12, bottom: 12 },
        }}
      />
    </div>
  );
}

function ChunksTab({ docId }: { docId: string }) {
  const q = useQuery({
    queryKey: ["library", "chunks", docId],
    queryFn: () => documentsApi.listChunks(docId, { limit: 500 }),
  });
  const [active, setActive] = useState<DocChunk | null>(null);

  useEffect(() => {
    if (q.data?.items.length && !active) {
      setActive(q.data.items[0]);
    }
  }, [q.data, active]);

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="p-4 text-sm text-[var(--color-destructive)]">
        Failed to load chunks: {(q.error as Error).message}
      </div>
    );
  }
  const items = q.data?.items ?? [];
  if (!items.length) {
    return (
      <div className="p-4">
        <EmptyState icon={ChevronRight} title="No chunks" description="The document had no extractable text." />
      </div>
    );
  }

  return (
    <div className="grid h-[34rem] grid-cols-[14rem_1fr]">
      <div className="overflow-y-auto border-r">
        <ul>
          {items.map((chunk) => (
            <li key={chunk.chunk_id}>
              <button
                type="button"
                onClick={() => setActive(chunk)}
                className={cn(
                  "w-full px-3 py-2 text-left text-xs",
                  active?.chunk_id === chunk.chunk_id
                    ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                    : "hover:bg-[var(--color-accent)]/60",
                )}
              >
                <div className="font-mono">#{String(chunk.idx).padStart(4, "0")}</div>
                {chunk.section_path.length > 0 && (
                  <div className="mt-0.5 line-clamp-1 text-[10px] text-[var(--color-muted-foreground)]">
                    {chunk.section_path.join(" › ")}
                  </div>
                )}
                <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
                  [{chunk.char_offset_start}-{chunk.char_offset_end}]
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="overflow-auto p-4 text-sm">
        {active ? (
          <>
            <div className="mb-2 text-[10px] font-mono text-[var(--color-muted-foreground)]">
              {active.chunk_id} · {active.text.length} chars
            </div>
            <pre className="whitespace-pre-wrap break-words font-mono text-[12px] leading-relaxed">
              {active.text}
            </pre>
          </>
        ) : (
          <p className="text-xs text-[var(--color-muted-foreground)]">Pick a chunk on the left.</p>
        )}
      </div>
    </div>
  );
}

function SearchTab({ docId }: { docId: string }) {
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<DocChunkHit[]>([]);
  const search = useMutation({
    mutationFn: (q: string) => documentsApi.search(q, { top_k: 8, filters: { doc_id: docId } }),
    onSuccess: (data) => setHits(data.items),
    onError: (err: Error) => toast.error(`Search failed: ${err.message}`),
  });

  const submit = (event: React.FormEvent): void => {
    event.preventDefault();
    if (!query.trim()) return;
    search.mutate(query.trim());
  };

  return (
    <div className="space-y-3 p-4">
      <form className="flex gap-2" onSubmit={submit}>
        <Input
          placeholder="Search inside this document..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Button size="sm" type="submit" disabled={search.isPending} className="gap-1">
          <Search className="h-3.5 w-3.5" /> {search.isPending ? "Searching" : "Search"}
        </Button>
      </form>
      {hits.length === 0 && !search.isPending && (
        <p className="text-xs text-[var(--color-muted-foreground)]">
          Hits will appear here. The query is filtered to this document.
        </p>
      )}
      <ul className="space-y-2">
        {hits.map((hit) => (
          <li key={hit.chunk_id} className="rounded-md border p-3 text-xs">
            <div className="flex items-center justify-between text-[10px] text-[var(--color-muted-foreground)]">
              <span className="font-mono">{hit.chunk_id}</span>
              <span>score {hit.score.toFixed(3)}</span>
            </div>
            {hit.section_path.length > 0 && (
              <p className="mt-1 text-[11px] font-medium text-[var(--color-muted-foreground)]">
                {hit.section_path.join(" › ")}
              </p>
            )}
            <p className="mt-1 line-clamp-4 leading-relaxed">{hit.text}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Ingest drawer
// ---------------------------------------------------------------------------

function IngestDrawer({
  onClose,
  onIngested,
}: {
  onClose: () => void;
  onIngested: (docId: string) => void;
}) {
  const qc = useQueryClient();
  const [mode, setMode] = useState<"file" | "paste">("paste");

  const [title, setTitle] = useState("");
  const [tags, setTags] = useState("");
  const [sourceKind, setSourceKind] = useState<DocumentSourceKind>("note");
  const [rawText, setRawText] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const ingest = useMutation({
    mutationFn: async () => {
      if (mode === "file") {
        if (!file) throw new Error("Please pick a file first");
        return documentsApi.ingestFile({
          file,
          title: title || undefined,
          tags: tags
            .split(",")
            .map((t) => t.trim())
            .filter(Boolean),
        });
      }
      if (!rawText.trim()) throw new Error("raw_text is empty");
      return documentsApi.ingestJSON({
        title,
        raw_text: rawText,
        source_kind: sourceKind,
        tags: tags
          .split(",")
          .map((t) => t.trim())
          .filter(Boolean),
      });
    },
    onSuccess: (resp) => {
      toast.success(`Ingested ${resp.document.title} · ${resp.chunks_indexed} chunks`);
      void qc.invalidateQueries({ queryKey: ["library"] });
      onIngested(resp.document.doc_id);
    },
    onError: (err: Error | ApiError) => {
      const detail = err instanceof ApiError ? String(err.message) : err.message;
      toast.error(`Ingest failed: ${detail}`);
    },
  });

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm">
      <div className="flex w-full max-w-xl flex-col bg-[var(--color-card)] shadow-xl">
        <div className="flex items-center justify-between border-b px-5 py-3">
          <div>
            <div className="text-sm font-semibold">Ingest document</div>
            <div className="text-xs text-[var(--color-muted-foreground)]">
              The framework chunks the document, embeds each slice, and indexes the vectors.
            </div>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} className="gap-1">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid min-h-0 flex-1 grid-rows-[auto_1fr_auto]">
          <div className="space-y-3 border-b p-4">
            <div className="flex items-center gap-1 rounded-md border bg-[var(--color-card)]/40 p-1 text-xs">
              <button
                type="button"
                onClick={() => setMode("paste")}
                className={cn(
                  "flex-1 rounded px-2.5 py-1.5 transition-colors",
                  mode === "paste"
                    ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                    : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]",
                )}
              >
                Paste text
              </button>
              <button
                type="button"
                onClick={() => setMode("file")}
                className={cn(
                  "flex-1 rounded px-2.5 py-1.5 transition-colors",
                  mode === "file"
                    ? "bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                    : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]",
                )}
              >
                Upload file
              </button>
            </div>
            <div className="grid gap-2">
              <Label htmlFor="doc-title">Title</Label>
              <Input
                id="doc-title"
                placeholder="Auto-derived from heading when blank"
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </div>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <Label htmlFor="doc-tags">Tags</Label>
                <Input
                  id="doc-tags"
                  placeholder="rag, foundation"
                  value={tags}
                  onChange={(event) => setTags(event.target.value)}
                />
              </div>
              {mode === "paste" && (
                <div>
                  <Label htmlFor="doc-kind">Source kind</Label>
                  <select
                    id="doc-kind"
                    value={sourceKind}
                    onChange={(event) =>
                      setSourceKind(event.target.value as DocumentSourceKind)
                    }
                    className="flex h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-3 text-sm"
                  >
                    {SOURCE_KINDS.map((k) => (
                      <option key={k} value={k}>
                        {k}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </div>

          <div className="overflow-hidden p-4">
            {mode === "paste" ? (
              <div className="flex h-full flex-col gap-1.5">
                <Label className="text-[11px] font-semibold uppercase">Markdown / text</Label>
                <Textarea
                  value={rawText}
                  onChange={(event) => setRawText(event.target.value)}
                  placeholder="# Heading\nParagraph body..."
                  className="min-h-0 flex-1 font-mono text-[12px]"
                />
                <p className="text-[10px] text-[var(--color-muted-foreground)]">
                  Tip: keep headings (`#`, `##`, `###`) — they become the section breadcrumb in
                  retrieval.
                </p>
              </div>
            ) : (
              <div className="flex h-full flex-col gap-2 rounded-md border border-dashed p-4 text-sm">
                <input
                  id="doc-file"
                  type="file"
                  accept=".pdf,.md,.markdown,.txt,application/pdf,text/markdown,text/plain"
                  onChange={(event) => setFile(event.target.files?.[0] ?? null)}
                  className="text-xs"
                />
                {file ? (
                  <p className="text-xs">
                    <span className="font-semibold">{file.name}</span> —{" "}
                    {fmtBytes(file.size)}
                  </p>
                ) : (
                  <p className="text-xs text-[var(--color-muted-foreground)]">
                    Pick a `.md`, `.txt`, or `.pdf` file. Files are decoded server-side and
                    chunked into ~800-token slices.
                  </p>
                )}
              </div>
            )}
          </div>

          <div className="flex items-center justify-between gap-3 border-t px-4 py-3">
            <p className="hidden text-[10px] text-[var(--color-muted-foreground)] md:block">
              Body ≤ 25 MB. Each chunk ≤ ~3.2 KB. Embeddings auto-rebuild on re-index.
            </p>
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={() => ingest.mutate()}
                disabled={ingest.isPending}
                className="gap-1"
              >
                {ingest.isPending ? (
                  <>
                    <RefreshCcw className="h-3.5 w-3.5 animate-spin" /> Ingesting…
                  </>
                ) : (
                  <>
                    <Upload className="h-3.5 w-3.5" /> Ingest
                  </>
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
