import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  BookOpen,
  BrainCircuit,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  FileText,
  Lightbulb,
  ListTree,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Snowflake,
  Sun,
  Trash2,
  Upload,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { PaperFormDrawer, type PaperFormSubmit } from "@/components/memory/PaperFormDrawer";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input, Textarea } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { documentsApi } from "@/lib/documents";
import { heuristicsApi, knowledgeApi, memoryApi } from "@/lib/memory";
import type {
  DocumentSourceKind,
  Heuristic,
  HeuristicDomain,
  IngestPaperResponse,
  KnowledgeDocument,
  MemoryStats,
  PaperCard,
  Reflection,
  ReflectionType,
  UpdateDocumentInput,
} from "@/types/api";

type TabId =
  | "stats"
  | "knowledge"
  | "documents"
  | "heuristics"
  | "reflections";

const TABS: ReadonlyArray<{ id: TabId; label: string; icon: typeof BrainCircuit }> = [
  { id: "stats", label: "Overview", icon: BrainCircuit },
  { id: "knowledge", label: "Knowledge", icon: BookOpen },
  { id: "documents", label: "Documents", icon: FileText },
  { id: "heuristics", label: "Heuristics", icon: Lightbulb },
  { id: "reflections", label: "Reflections", icon: ListTree },
];

const DOMAINS: HeuristicDomain[] = ["research", "writing", "revision", "rebuttal", "survey"];
const REFLECTION_TYPES: ReflectionType[] = ["reflection", "observation", "insight"];

export function MemoryPage() {
  const { t } = useTranslation();
  const [tab, setTab] = useState<TabId>("stats");

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("memory.title")}
        description={t("memory.description")}
      />

      <Tabs value={tab} onChange={setTab} />

      {tab === "stats" && <StatsTab />}
      {tab === "knowledge" && <KnowledgeTab />}
      {tab === "documents" && <DocumentsTab />}
      {tab === "heuristics" && <HeuristicsTab />}
      {tab === "reflections" && <ReflectionsTab />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------

function Tabs({ value, onChange }: { value: TabId; onChange: (id: TabId) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1 rounded-md border bg-[var(--color-card)]/40 p-1">
      {TABS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          aria-pressed={value === id}
          className={cn(
            "inline-flex items-center gap-2 rounded px-3 py-1.5 text-sm font-medium transition-colors",
            value === id
              ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
              : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]/60 hover:text-[var(--color-foreground)]",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden />
          {label}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

function StatsTab() {
  const memoryQ = useQuery({
    queryKey: ["memory", "stats"],
    queryFn: () => memoryApi.stats(),
    refetchInterval: 5000,
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <BrainCircuit className="h-4 w-4" /> Counts
        </CardTitle>
      </CardHeader>
      <CardContent>
        {memoryQ.isLoading && <Skeleton className="h-32 w-full" />}
        {memoryQ.isError && (
          <p className="text-sm text-[var(--color-destructive)]">
            Failed to load memory stats: {(memoryQ.error as Error).message}
          </p>
        )}
        {memoryQ.data && <StatsGrid data={memoryQ.data} />}
      </CardContent>
    </Card>
  );
}

function StatsGrid({ data }: { data: MemoryStats }) {
  return (
    <dl className="grid gap-4 text-sm sm:grid-cols-3">
      <Stat label="Vectors" value={data.vector_count ?? "—"} />
      <Stat label="Knowledge cards" value={data.knowledge_count} />
      <Stat label="Synthesis notes" value={data.synthesis_count} />
      <Stat label="Heuristics (L3)" value={data.heuristic_count} />
      <Stat label="Reflections" value={data.reflection_count ?? "—"} />
      <Stat label="Session backend" value={data.session_backend} mono />
    </dl>
  );
}

function Stat({ label, value, mono }: { label: string; value: number | string; mono?: boolean }) {
  return (
    <div className="rounded-md border bg-[var(--color-background)] p-4">
      <dt className="text-xs uppercase tracking-wider text-[var(--color-muted-foreground)]">
        {label}
      </dt>
      <dd
        className={`mt-1 text-2xl tabular-nums ${
          mono ? "font-mono text-base" : "font-semibold"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Knowledge
// ---------------------------------------------------------------------------

function KnowledgeTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [query, setQuery] = useState("");
  const [tag, setTag] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [ingestOpen, setIngestOpen] = useState(false);

  // P13.C — manual CRUD state. ``editing === null`` + ``formOpen`` =
  // create mode; ``editing !== null`` = edit mode.
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<PaperCard | null>(null);

  // Hierarchical taxonomy filter. ``null`` means "all"; ``"NLP"`` means
  // major-only; ``"NLP/LLM-Agent"`` means major + minor.
  const [activeMajor, setActiveMajor] = useState<string | null>(null);
  const [activeMinor, setActiveMinor] = useState<string | null>(null);

  // Light debouncing without bringing in a new dep.
  useMemo(() => {
    const handle = setTimeout(() => setDebouncedQuery(query), 250);
    return () => clearTimeout(handle);
  }, [query]);

  const list = useQuery({
    queryKey: ["memory", "knowledge", { q: debouncedQuery, tag }],
    queryFn: () =>
      knowledgeApi.listPapers({
        q: debouncedQuery.trim() || undefined,
        tag: tag.trim() || undefined,
        limit: 200,
      }),
  });

  // Build the major/minor index from the *unfiltered* list so the
  // sidebar buckets don't disappear when the user picks one.
  const items = list.data?.items ?? [];
  const taxonomy = useMemo(() => {
    const map = new Map<string, Map<string | null, number>>();
    for (const c of items) {
      const major = (c.field_major ?? "").trim() || "_uncategorized";
      const minor = (c.field_minor ?? "").trim() || null;
      const inner = map.get(major) ?? new Map<string | null, number>();
      inner.set(minor, (inner.get(minor) ?? 0) + 1);
      map.set(major, inner);
    }
    return map;
  }, [items]);

  const filtered = useMemo(() => {
    if (activeMajor === null) return items;
    return items.filter((c) => {
      const major = (c.field_major ?? "").trim() || "_uncategorized";
      if (major !== activeMajor) return false;
      if (activeMinor === null) return true;
      const minor = (c.field_minor ?? "").trim() || null;
      return minor === activeMinor;
    });
  }, [items, activeMajor, activeMinor]);

  const remove = useMutation({
    mutationFn: (paperId: string) => knowledgeApi.deletePaper(paperId),
    onSuccess: () => {
      toast.success(t("memory.toast.deleted"));
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) => toast.error(`${t("memory.toast.deleteFailed")}: ${err.message}`),
  });

  const save = useMutation({
    mutationFn: async (s: PaperFormSubmit) => {
      if (s.mode === "create") return knowledgeApi.createPaper(s.payload);
      return knowledgeApi.updatePaper(s.paperId, s.payload);
    },
    onSuccess: (card, vars) => {
      const created = vars.mode === "create";
      toast.success(
        created
          ? `${t("memory.toast.created")} · ${card.title}`
          : `${t("memory.toast.updated")} · ${card.title}`,
      );
      setFormOpen(false);
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) =>
      toast.error(`${t("memory.toast.saveFailed")}: ${err.message}`),
  });

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-sm">
            <BookOpen className="h-4 w-4" /> {t("memory.knowledge.title")}
          </CardTitle>
          <div className="flex items-center gap-2">
            {/* New card — manual entry. Different from Ingest (which
                extracts metadata from a PDF / markdown blob).        */}
            <Button
              size="sm"
              variant="primary"
              onClick={() => {
                setEditing(null);
                setFormOpen(true);
              }}
              className="gap-1"
            >
              <Plus className="h-3.5 w-3.5" />
              {t("memory.knowledge.newCard")}
            </Button>
            <Button
              size="sm"
              variant={ingestOpen ? "outline" : "secondary"}
              onClick={() => setIngestOpen((open) => !open)}
              className="gap-1"
            >
              <Upload className="h-3.5 w-3.5" />
              {ingestOpen ? t("memory.knowledge.closeIngest") : t("memory.knowledge.ingest")}
              {ingestOpen ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {ingestOpen ? (
          <IngestPaperPanel
            onIngested={() => {
              void qc.invalidateQueries({ queryKey: ["memory"] });
            }}
          />
        ) : null}
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="flex flex-col gap-1">
            <Label htmlFor="kn-query">{t("memory.knowledge.search")}</Label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-[var(--color-muted-foreground)]" />
              <Input
                id="kn-query"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={t("memory.knowledge.searchPlaceholder")}
                className="pl-8"
              />
            </div>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="kn-tag">{t("memory.knowledge.tag")}</Label>
            <Input
              id="kn-tag"
              value={tag}
              onChange={(e) => setTag(e.target.value)}
              placeholder={t("memory.knowledge.tagPlaceholder")}
            />
          </div>
        </div>

        {/* Major / minor taxonomy filter. The "_uncategorized" bucket
            uses an i18n label rather than a magic key.              */}
        {taxonomy.size > 0 && (
          <TaxonomyFilter
            taxonomy={taxonomy}
            activeMajor={activeMajor}
            activeMinor={activeMinor}
            onPickMajor={(m) => {
              setActiveMajor(m);
              setActiveMinor(null);
            }}
            onPickMinor={(m) => setActiveMinor(m)}
            onClear={() => {
              setActiveMajor(null);
              setActiveMinor(null);
            }}
          />
        )}

        {list.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : list.isError ? (
          <p className="text-sm text-[var(--color-destructive)]">
            {t("memory.knowledge.loadFailed")}: {(list.error as Error).message}
          </p>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon={BookOpen}
            title={t("memory.knowledge.empty.title")}
            description={t("memory.knowledge.empty.description")}
          />
        ) : (
          <ul className="divide-y rounded-md border">
            {filtered.map((card) => (
              <PaperRow
                key={card.paper_id}
                card={card}
                onDelete={() => {
                  if (confirm(t("memory.knowledge.confirmDelete", { title: card.title }))) {
                    remove.mutate(card.paper_id);
                  }
                }}
                onEdit={() => {
                  setEditing(card);
                  setFormOpen(true);
                }}
                deleting={remove.isPending && remove.variables === card.paper_id}
              />
            ))}
          </ul>
        )}
        {list.data && list.data.total > list.data.items.length ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("memory.knowledge.showingMore", {
              shown: list.data.items.length,
              total: list.data.total,
            })}
          </p>
        ) : null}
      </CardContent>

      <PaperFormDrawer
        card={editing}
        open={formOpen}
        onClose={() => {
          setFormOpen(false);
          setEditing(null);
        }}
        onSubmit={(s) => save.mutate(s)}
        submitting={save.isPending}
      />
    </Card>
  );
}

interface TaxonomyFilterProps {
  taxonomy: Map<string, Map<string | null, number>>;
  activeMajor: string | null;
  activeMinor: string | null;
  onPickMajor: (m: string | null) => void;
  onPickMinor: (m: string | null) => void;
  onClear: () => void;
}

function TaxonomyFilter({
  taxonomy,
  activeMajor,
  activeMinor,
  onPickMajor,
  onPickMinor,
  onClear,
}: TaxonomyFilterProps) {
  const { t } = useTranslation();
  const sortedMajors = Array.from(taxonomy.keys()).sort();
  return (
    <div className="space-y-2 rounded-md border bg-[var(--color-muted)]/30 p-2">
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]">
          {t("memory.knowledge.filterByCategory")}
        </span>
        {(activeMajor !== null || activeMinor !== null) && (
          <button
            type="button"
            onClick={onClear}
            className="text-[10px] text-[var(--color-primary)] hover:underline"
          >
            {t("memory.knowledge.clearFilter")}
          </button>
        )}
      </div>
      <div className="flex flex-wrap gap-1">
        {sortedMajors.map((major) => {
          const count = Array.from(taxonomy.get(major)?.values() ?? []).reduce(
            (a, b) => a + b,
            0,
          );
          const isActive = activeMajor === major;
          const label =
            major === "_uncategorized" ? t("memory.knowledge.uncategorized") : major;
          return (
            <button
              key={major}
              type="button"
              onClick={() => onPickMajor(isActive ? null : major)}
              className={cn(
                "rounded border px-2 py-0.5 text-[10px] transition-colors",
                isActive
                  ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                  : "hover:bg-[var(--color-muted)]",
              )}
            >
              {label} ({count})
            </button>
          );
        })}
      </div>
      {activeMajor !== null && (
        <div className="flex flex-wrap gap-1 border-t pt-2">
          {Array.from(taxonomy.get(activeMajor)?.entries() ?? [])
            .sort(([a], [b]) => (a ?? "").localeCompare(b ?? ""))
            .map(([minor, count]) => {
              const isActive = activeMinor === minor;
              const label = minor ?? t("memory.knowledge.noMinor");
              return (
                <button
                  key={String(minor)}
                  type="button"
                  onClick={() => onPickMinor(isActive ? null : minor)}
                  className={cn(
                    "rounded border px-2 py-0.5 text-[10px] transition-colors",
                    isActive
                      ? "border-[var(--color-primary)] bg-[var(--color-primary)] text-[var(--color-primary-foreground)]"
                      : "hover:bg-[var(--color-muted)]",
                  )}
                >
                  {label} ({count})
                </button>
              );
            })}
        </div>
      )}
    </div>
  );
}

type IngestMode = "file" | "metadata";

function IngestPaperPanel({ onIngested }: { onIngested: () => void }) {
  const [mode, setMode] = useState<IngestMode>("file");
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [year, setYear] = useState("");
  const [tags, setTags] = useState("");
  const [summary, setSummary] = useState("");
  const [bodyText, setBodyText] = useState("");
  const [triggerEvolution, setTriggerEvolution] = useState(true);
  const [llmExtract, setLlmExtract] = useState(true);
  const [result, setResult] = useState<IngestPaperResponse | null>(null);

  const ingest = useMutation<IngestPaperResponse, Error>({
    mutationFn: async () => {
      if (mode === "file") {
        if (!file) throw new Error("choose a file first");
        return knowledgeApi.ingestPaperFile({
          file,
          title: title.trim() || undefined,
          authors: parseCSV(authors),
          year: year ? Number(year) : null,
          tags: parseCSV(tags),
          source_kind: "user_upload",
          trigger_evolution: triggerEvolution,
          llm_extract: llmExtract,
        });
      }
      if (!title.trim()) throw new Error("title is required for metadata ingest");
      return knowledgeApi.ingestPaperJSON({
        title: title.trim(),
        authors: parseCSV(authors),
        year: year ? Number(year) : null,
        tags: parseCSV(tags),
        summary: summary.trim() || undefined,
        body_text: bodyText.trim() || undefined,
        source_kind: "manual",
        trigger_evolution: triggerEvolution,
        llm_extract: llmExtract,
      });
    },
    onSuccess: (data) => {
      setResult(data);
      toast.success(`Ingested · ${data.card.title}`);
      onIngested();
    },
    onError: (err) => toast.error(`Ingest failed: ${err.message}`),
  });

  const reset = () => {
    setFile(null);
    setTitle("");
    setAuthors("");
    setYear("");
    setTags("");
    setSummary("");
    setBodyText("");
    setResult(null);
  };

  return (
    <div className="rounded-md border bg-[var(--color-muted)]/30 p-4">
      <div className="mb-3 flex items-center gap-2">
        <Button
          size="sm"
          variant={mode === "file" ? "primary" : "outline"}
          onClick={() => setMode("file")}
        >
          Upload file
        </Button>
        <Button
          size="sm"
          variant={mode === "metadata" ? "primary" : "outline"}
          onClick={() => setMode("metadata")}
        >
          Paste metadata
        </Button>
      </div>

      {mode === "file" ? (
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="ingest-file">PDF / Markdown / Text</Label>
            <Input
              id="ingest-file"
              type="file"
              accept=".pdf,.md,.markdown,.txt,application/pdf,text/markdown,text/plain"
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            {file ? (
              <p className="text-[10px] text-[var(--color-muted-foreground)]">
                {file.name} · {(file.size / 1024).toFixed(1)} KB
              </p>
            ) : null}
          </div>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="ingest-body">Body text (optional)</Label>
            <Textarea
              id="ingest-body"
              rows={4}
              value={bodyText}
              onChange={(e) => setBodyText(e.target.value)}
              placeholder="Paste the abstract or full paper text. Leave empty if you only have metadata."
            />
          </div>
        </div>
      )}

      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1">
          <Label htmlFor="ingest-title">
            Title{mode === "metadata" ? " *" : " (optional override)"}
          </Label>
          <Input
            id="ingest-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Self-Evolving Agents …"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="ingest-year">Year</Label>
          <Input
            id="ingest-year"
            type="number"
            value={year}
            onChange={(e) => setYear(e.target.value)}
            placeholder="2024"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="ingest-authors">Authors (comma-separated)</Label>
          <Input
            id="ingest-authors"
            value={authors}
            onChange={(e) => setAuthors(e.target.value)}
            placeholder="Alice, Bob"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="ingest-tags">Tags (comma-separated)</Label>
          <Input
            id="ingest-tags"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
            placeholder="agent, memory"
          />
        </div>
        {mode === "metadata" ? (
          <div className="flex flex-col gap-1 sm:col-span-2">
            <Label htmlFor="ingest-summary">Summary</Label>
            <Textarea
              id="ingest-summary"
              rows={2}
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
            />
          </div>
        ) : null}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-4 text-xs">
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={triggerEvolution}
            onChange={(e) => setTriggerEvolution(e.target.checked)}
          />
          Trigger memory evolution (typed-link inference + synthesis check)
        </label>
        <label className="inline-flex items-center gap-2">
          <input
            type="checkbox"
            checked={llmExtract}
            onChange={(e) => setLlmExtract(e.target.checked)}
          />
          Use LLM to extract metadata from body
        </label>
      </div>

      <div className="mt-4 flex items-center gap-2">
        <Button
          size="sm"
          onClick={() => ingest.mutate()}
          disabled={ingest.isPending || (mode === "file" && !file)}
        >
          {ingest.isPending ? "Ingesting…" : "Ingest"}
        </Button>
        <Button size="sm" variant="ghost" onClick={reset} disabled={ingest.isPending}>
          Reset
        </Button>
      </div>

      {result ? <IngestResultCard result={result} /> : null}
    </div>
  );
}

function IngestResultCard({ result }: { result: IngestPaperResponse }) {
  const { card, evolution, synthesis, extracted } = result;
  return (
    <div className="mt-4 rounded-md border border-[var(--color-border)] bg-[var(--color-background)] p-3 text-xs space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{extracted.method}</Badge>
        <Badge variant="neutral">extract {extracted.extract_ms} ms</Badge>
        <Badge variant="neutral">evolve {extracted.evolve_ms} ms</Badge>
        <Badge variant={evolution.mode === "skip" ? "neutral" : "outline"}>
          mode: {evolution.mode}
        </Badge>
        {synthesis ? <Badge variant="outline">synthesis v{synthesis.version}</Badge> : null}
      </div>
      <div>
        <span className="font-medium">{card.title}</span>
        {card.year ? <span className="ml-2 opacity-70">({card.year})</span> : null}
        {card.tags.length > 0 ? (
          <span className="ml-2 opacity-70">· {card.tags.join(", ")}</span>
        ) : null}
      </div>
      {evolution.typed_links_added.length > 0 ? (
        <div>
          <p className="font-medium">Typed links added</p>
          <ul className="ml-3 list-disc space-y-0.5">
            {evolution.typed_links_added.map((link) => (
              <li key={`${link.target_paper_id}-${link.link_type}`}>
                <span className="font-mono">{link.link_type}</span> →{" "}
                <span className="font-mono">{link.target_paper_id}</span>
                {link.evidence ? <span className="opacity-70"> · {link.evidence}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p className="opacity-70">No typed links inferred (reason: {evolution.reason || "n/a"}).</p>
      )}
      {extracted.preview ? (
        <details className="cursor-pointer">
          <summary className="opacity-70">Body preview ({extracted.preview.length} chars)</summary>
          <pre className="mt-1 max-h-36 overflow-auto whitespace-pre-wrap rounded bg-[var(--color-muted)] p-2 text-[10px]">
            {extracted.preview}
          </pre>
        </details>
      ) : null}
    </div>
  );
}

function parseCSV(value: string): string[] | undefined {
  const items = value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  return items.length > 0 ? items : undefined;
}

function PaperRow({
  card,
  onDelete,
  onEdit,
  deleting,
}: {
  card: PaperCard;
  onDelete: () => void;
  onEdit: () => void;
  deleting: boolean;
}) {
  const { t } = useTranslation();
  const authors = card.authors.slice(0, 3).join(", ");
  const more = card.authors.length > 3 ? ` +${card.authors.length - 3}` : "";
  // ``url`` may have a non-http scheme (file://, magnet:, etc.) — we
  // still render it as a clickable anchor but rely on the browser to
  // honour or reject the scheme.
  const hasFields = Boolean(card.field_major || card.field_minor);
  return (
    <li className="flex items-start gap-3 p-4 hover:bg-[var(--color-muted)]">
      <BookOpen className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-sm font-medium">{card.title}</span>
          {card.year ? <Badge variant="outline">{card.year}</Badge> : null}
          {card.venue ? <Badge variant="neutral">{card.venue}</Badge> : null}
          {hasFields ? (
            <Badge variant="outline" className="font-mono">
              {card.field_major}
              {card.field_minor ? ` / ${card.field_minor}` : ""}
            </Badge>
          ) : null}
          {card.tags.slice(0, 4).map((tg) => (
            <Badge key={tg} variant="neutral">
              {tg}
            </Badge>
          ))}
          {card.url ? (
            <a
              href={card.url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-0.5 text-[10px] text-[var(--color-primary)] hover:underline"
              title={card.url}
              aria-label={t("memory.knowledge.openUrl")}
            >
              {t("memory.knowledge.link")}
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
          ) : null}
        </div>
        {authors && (
          <p className="truncate text-xs text-[var(--color-muted-foreground)]">
            {authors}
            {more}
          </p>
        )}
        {card.summary && (
          <p className="line-clamp-2 text-xs text-[var(--color-muted-foreground)]">
            {card.summary}
          </p>
        )}
        <p className="text-[10px] text-[var(--color-muted-foreground)]">
          {card.paper_id} ·{" "}
          {formatDistanceToNow(new Date(card.updated_at), { addSuffix: true })}
          {card.source_run_id ? ` · run ${card.source_run_id}` : null}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <Button
          variant="ghost"
          size="icon"
          onClick={onEdit}
          aria-label={t("memory.knowledge.edit")}
          title={t("memory.knowledge.edit")}
        >
          <Pencil className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onDelete}
          disabled={deleting}
          aria-label={t("memory.knowledge.delete")}
          title={t("memory.knowledge.delete")}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </li>
  );
}

// ---------------------------------------------------------------------------
// Heuristics
// ---------------------------------------------------------------------------

function HeuristicsTab() {
  const qc = useQueryClient();
  const [domain, setDomain] = useState<HeuristicDomain | "">("");
  const [includeFrozen, setIncludeFrozen] = useState(true);

  const list = useQuery({
    queryKey: ["memory", "heuristics", { domain, includeFrozen }],
    queryFn: () =>
      heuristicsApi.list({
        domain: domain || undefined,
        include_frozen: includeFrozen,
        limit: 200,
      }),
  });

  const freeze = useMutation({
    mutationFn: ({ id, frozen }: { id: string; frozen: boolean }) =>
      frozen ? heuristicsApi.unfreeze(id) : heuristicsApi.freeze(id),
    onSuccess: (h) => {
      toast.success(h.frozen ? "Heuristic frozen" : "Heuristic activated");
      void qc.invalidateQueries({ queryKey: ["memory", "heuristics"] });
    },
    onError: (err: Error) => toast.error(`Toggle failed: ${err.message}`),
  });

  const bump = useMutation({
    mutationFn: ({ id, verdict }: { id: string; verdict: "pass" | "fail" }) =>
      heuristicsApi.bump(id, verdict),
    onSuccess: (_h, vars) => {
      toast.success(`Recorded ${vars.verdict}`);
      void qc.invalidateQueries({ queryKey: ["memory", "heuristics"] });
    },
    onError: (err: Error) => toast.error(`Bump failed: ${err.message}`),
  });

  const remove = useMutation({
    mutationFn: (id: string) => heuristicsApi.delete(id),
    onSuccess: () => {
      toast.success("Heuristic deleted");
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) => toast.error(`Delete failed: ${err.message}`),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Lightbulb className="h-4 w-4" /> Heuristics
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <Label htmlFor="he-domain">Domain</Label>
            <select
              id="he-domain"
              className="h-9 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
              value={domain}
              onChange={(e) => setDomain((e.target.value || "") as HeuristicDomain | "")}
            >
              <option value="">any</option>
              {DOMAINS.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={includeFrozen}
              onChange={(e) => setIncludeFrozen(e.target.checked)}
            />
            Include frozen
          </label>
        </div>

        {list.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : list.isError ? (
          <p className="text-sm text-[var(--color-destructive)]">
            Failed to load heuristics: {(list.error as Error).message}
          </p>
        ) : !list.data || list.data.items.length === 0 ? (
          <EmptyState
            icon={Lightbulb}
            title="No heuristics yet"
            description="The Evolver writes new heuristics whenever a workflow finishes successfully."
          />
        ) : (
          <ul className="divide-y rounded-md border">
            {list.data.items.map((h) => (
              <HeuristicRow
                key={h.id}
                heuristic={h}
                onToggleFreeze={() => freeze.mutate({ id: h.id, frozen: h.frozen })}
                onBump={(verdict) => bump.mutate({ id: h.id, verdict })}
                onDelete={() => remove.mutate(h.id)}
              />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}

function HeuristicRow({
  heuristic,
  onToggleFreeze,
  onBump,
  onDelete,
}: {
  heuristic: Heuristic;
  onToggleFreeze: () => void;
  onBump: (verdict: "pass" | "fail") => void;
  onDelete: () => void;
}) {
  const failureRate =
    heuristic.success_count + heuristic.failure_count === 0
      ? 0
      : heuristic.failure_count / (heuristic.success_count + heuristic.failure_count);

  return (
    <li className="space-y-2 p-4 hover:bg-[var(--color-muted)]">
      <div className="flex flex-wrap items-center gap-2">
        <Lightbulb className="h-4 w-4 shrink-0 text-[var(--color-muted-foreground)]" />
        <span className="truncate text-sm font-medium">{heuristic.name}</span>
        <Badge variant="outline">{heuristic.domain}</Badge>
        {heuristic.frozen ? (
          <Badge variant="warning">frozen</Badge>
        ) : (
          <Badge variant="success">active</Badge>
        )}
        <span className="ml-auto text-xs tabular-nums text-[var(--color-muted-foreground)]">
          ✓ {heuristic.success_count} · ✗ {heuristic.failure_count}{" "}
          {failureRate ? `(${Math.round(failureRate * 100)}% fail)` : ""}
        </span>
      </div>
      {heuristic.description && (
        <p className="text-xs text-[var(--color-muted-foreground)]">{heuristic.description}</p>
      )}
      {heuristic.trigger_pattern && (
        <p className="text-[11px] text-[var(--color-muted-foreground)]">
          <span className="font-mono">trigger:</span> {heuristic.trigger_pattern}
        </p>
      )}
      {(heuristic.strategy.planning_hints ||
        heuristic.strategy.search_tips ||
        heuristic.strategy.evaluation_criteria) && (
        <details className="text-xs text-[var(--color-muted-foreground)]">
          <summary className="cursor-pointer select-none">Strategy</summary>
          <dl className="mt-2 space-y-1 pl-4">
            {heuristic.strategy.planning_hints && (
              <StrategyLine label="Planning" text={heuristic.strategy.planning_hints} />
            )}
            {heuristic.strategy.search_tips && (
              <StrategyLine label="Search" text={heuristic.strategy.search_tips} />
            )}
            {heuristic.strategy.evaluation_criteria && (
              <StrategyLine label="Evaluation" text={heuristic.strategy.evaluation_criteria} />
            )}
          </dl>
        </details>
      )}
      <div className="flex flex-wrap gap-2 text-xs">
        <Button size="sm" variant="outline" onClick={onToggleFreeze}>
          {heuristic.frozen ? (
            <>
              <Sun className="h-3.5 w-3.5" /> Unfreeze
            </>
          ) : (
            <>
              <Snowflake className="h-3.5 w-3.5" /> Freeze
            </>
          )}
        </Button>
        <Button size="sm" variant="outline" onClick={() => onBump("pass")}>
          Bump pass
        </Button>
        <Button size="sm" variant="outline" onClick={() => onBump("fail")}>
          Bump fail
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => {
            if (confirm(`Delete heuristic "${heuristic.name}"?`)) onDelete();
          }}
        >
          <Trash2 className="h-3.5 w-3.5" />
          Delete
        </Button>
        <span className="ml-auto self-center text-[10px] tabular-nums text-[var(--color-muted-foreground)]">
          {heuristic.id}
        </span>
      </div>
    </li>
  );
}

function StrategyLine({ label, text }: { label: string; text: string }) {
  return (
    <div className="flex gap-2">
      <dt className="w-20 shrink-0 text-[10px] uppercase tracking-wider">{label}</dt>
      <dd className="flex-1 whitespace-pre-wrap">{text}</dd>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Documents (P14.E) — list + edit metadata + delete; ingest stays in /library
// ---------------------------------------------------------------------------
//
// Why: documents and PaperCards are *orthogonal* memory surfaces (the
// MemoryPage stats tab makes that explicit). Users editing memory in
// MemoryPage shouldn't have to bounce to /library just to fix a typo
// in a doc title or rename tags.
//
// Why no inline ingest here: the ingest flow already lives on
// /library and has a dedicated form for file upload, source-kind
// detection, and reindex parameters. Mirroring it here would
// duplicate ~150 lines of UI. Instead this tab links out to /library
// for the create path and keeps the surface scoped to "manage
// existing".

const DOC_SOURCE_KINDS: DocumentSourceKind[] = [
  "pdf_upload",
  "md_upload",
  "txt_upload",
  "note",
  "url",
  "clipboard",
];

function DocumentsTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<KnowledgeDocument | null>(null);
  const [tagFilter, setTagFilter] = useState("");

  const list = useQuery({
    queryKey: ["memory", "documents", { tag: tagFilter }],
    queryFn: () =>
      documentsApi.list({
        tag: tagFilter.trim() || undefined,
        limit: 200,
      }),
  });

  const update = useMutation({
    mutationFn: (args: { docId: string; payload: UpdateDocumentInput }) =>
      documentsApi.patchMetadata(args.docId, args.payload),
    onSuccess: () => {
      toast.success(t("memory.documents.toast.updated"));
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["memory", "documents"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.documents.toast.updateFailed", { error: err.message })),
  });

  const remove = useMutation({
    mutationFn: (docId: string) => documentsApi.delete(docId),
    onSuccess: () => {
      toast.success(t("memory.documents.toast.deleted"));
      void qc.invalidateQueries({ queryKey: ["memory", "documents"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.documents.toast.deleteFailed", { error: err.message })),
  });

  const reindex = useMutation({
    mutationFn: (docId: string) => documentsApi.reindex(docId),
    onSuccess: () => {
      toast.success(t("memory.documents.toast.reindexed"));
      void qc.invalidateQueries({ queryKey: ["memory", "documents"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.documents.toast.reindexFailed", { error: err.message })),
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <FileText className="h-4 w-4" /> {t("memory.documents.title")}
          <Button
            asChild
            size="sm"
            variant="outline"
            className="ml-auto h-7 text-xs"
            title={t("memory.documents.ingestHint") ?? ""}
          >
            <a href="/library">
              <Upload className="mr-1 h-3 w-3" />
              {t("memory.documents.openIngest")}
            </a>
          </Button>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t("memory.documents.subtitle")}
        </p>

        <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
          <div className="flex flex-col gap-1">
            <Label htmlFor="doc-tag">{t("memory.documents.fields.tag")}</Label>
            <Input
              id="doc-tag"
              value={tagFilter}
              onChange={(e) => setTagFilter(e.target.value)}
              placeholder={t("memory.documents.tagPlaceholder") ?? ""}
            />
          </div>
          <Button
            type="button"
            variant="outline"
            onClick={() => setTagFilter("")}
            disabled={!tagFilter}
            className="self-end"
          >
            {t("common.clear") ?? t("memory.knowledge.clearFilter")}
          </Button>
        </div>

        {list.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : list.isError ? (
          <p className="text-sm text-[var(--color-destructive)]">
            {t("memory.documents.loadFailed", { error: (list.error as Error).message })}
          </p>
        ) : !list.data || list.data.items.length === 0 ? (
          <EmptyState
            icon={FileText}
            title={t("memory.documents.empty.title")}
            description={t("memory.documents.empty.description")}
          />
        ) : (
          <ul className="divide-y rounded-md border">
            {list.data.items.map((doc) => (
              <DocumentRow
                key={doc.doc_id}
                doc={doc}
                onEdit={() => setEditing(doc)}
                onDelete={() => {
                  if (
                    confirm(
                      t("memory.documents.confirmDelete", { title: doc.title }),
                    )
                  ) {
                    remove.mutate(doc.doc_id);
                  }
                }}
                onReindex={() => reindex.mutate(doc.doc_id)}
                reindexing={reindex.isPending}
              />
            ))}
          </ul>
        )}
      </CardContent>

      {editing ? (
        <DocumentEditDialog
          doc={editing}
          submitting={update.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(payload) => update.mutate({ docId: editing.doc_id, payload })}
        />
      ) : null}
    </Card>
  );
}

function DocumentRow({
  doc,
  onEdit,
  onDelete,
  onReindex,
  reindexing,
}: {
  doc: KnowledgeDocument;
  onEdit: () => void;
  onDelete: () => void;
  onReindex: () => void;
  reindexing: boolean;
}) {
  const { t } = useTranslation();
  const sizeKB = (doc.bytes / 1024).toFixed(1);
  const updated = doc.updated_at
    ? formatDistanceToNow(new Date(doc.updated_at), { addSuffix: true })
    : "";

  return (
    <li className="space-y-1 p-4 hover:bg-[var(--color-muted)]">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium">{doc.title || doc.doc_id}</span>
        <Badge variant="outline">{doc.source_kind}</Badge>
        {doc.tags.map((tag) => (
          <Badge key={tag} variant="neutral">
            {tag}
          </Badge>
        ))}
        {updated && (
          <span className="ml-auto text-[10px] text-[var(--color-muted-foreground)]">
            {updated}
          </span>
        )}
        <Button
          size="icon"
          variant="ghost"
          onClick={onReindex}
          disabled={reindexing}
          className="h-7 w-7"
          aria-label={t("memory.documents.reindex") ?? "Reindex"}
          title={t("memory.documents.reindexHint") ?? ""}
        >
          <RefreshCw className={cn("h-3.5 w-3.5", reindexing && "animate-spin")} />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          onClick={onEdit}
          className="h-7 w-7"
          aria-label={t("common.edit") ?? "Edit"}
        >
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          onClick={onDelete}
          className="h-7 w-7 text-[var(--color-destructive)]"
          aria-label={t("common.delete") ?? "Delete"}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      {doc.summary ? (
        <p className="line-clamp-2 text-xs text-[var(--color-muted-foreground)]">
          {doc.summary}
        </p>
      ) : null}
      <p className="text-[10px] text-[var(--color-muted-foreground)]">
        {doc.doc_id} · {sizeKB} KB · {doc.chunk_ids.length} chunks
        {doc.source_uri ? (
          <>
            {" · "}
            <a
              href={doc.source_uri}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-0.5 hover:underline"
            >
              <ExternalLink className="h-3 w-3" />
              {t("memory.knowledge.link")}
            </a>
          </>
        ) : null}
      </p>
    </li>
  );
}

function DocumentEditDialog({
  doc,
  submitting,
  onCancel,
  onSubmit,
}: {
  doc: KnowledgeDocument;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (payload: UpdateDocumentInput) => void;
}) {
  const { t } = useTranslation();
  const [title, setTitle] = useState(doc.title);
  const [summary, setSummary] = useState(doc.summary);
  const [tagsInput, setTagsInput] = useState(doc.tags.join(", "));
  const [sourceKind, setSourceKind] = useState<DocumentSourceKind>(doc.source_kind);
  const [sourceUri, setSourceUri] = useState(doc.source_uri ?? "");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const canSubmit = title.trim().length > 0 && !submitting;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          // Pack only changed-relative-to-form fields, not the original
          // doc — the backend's PATCH semantics merge what's sent.
          onSubmit({
            title: title.trim(),
            summary,
            tags: tagsInput
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            source_kind: sourceKind,
            source_uri: sourceUri.trim() || undefined,
          });
        }}
        className="w-full max-w-xl space-y-3 rounded-lg border bg-[var(--color-background)] p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold">{t("memory.documents.editTitle")}</h2>
        <p className="text-[10px] text-[var(--color-muted-foreground)]">
          {t("memory.documents.editHint")}
        </p>

        <div className="space-y-1">
          <Label htmlFor="doc-title">{t("memory.documents.fields.title")} *</Label>
          <Input
            id="doc-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
            aria-invalid={!title.trim() || undefined}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <div className="space-y-1">
            <Label htmlFor="doc-kind">{t("memory.documents.fields.sourceKind")}</Label>
            <select
              id="doc-kind"
              className="h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
              value={sourceKind}
              onChange={(e) => setSourceKind(e.target.value as DocumentSourceKind)}
            >
              {DOC_SOURCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="doc-uri">{t("memory.documents.fields.sourceUri")}</Label>
            <Input
              id="doc-uri"
              value={sourceUri}
              onChange={(e) => setSourceUri(e.target.value)}
              placeholder="https://… or path"
            />
          </div>
        </div>

        <div className="space-y-1">
          <Label htmlFor="doc-tags">{t("memory.documents.fields.tags")}</Label>
          <Input
            id="doc-tags"
            value={tagsInput}
            onChange={(e) => setTagsInput(e.target.value)}
            placeholder="rag, notes"
          />
          <p className="text-[10px] text-[var(--color-muted-foreground)]">
            {t("memory.paperForm.csvHint")}
          </p>
        </div>

        <div className="space-y-1">
          <Label htmlFor="doc-summary">{t("memory.documents.fields.summary")}</Label>
          <Textarea
            id="doc-summary"
            value={summary}
            onChange={(e) => setSummary(e.target.value)}
            rows={4}
          />
        </div>

        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onCancel} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {submitting ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Reflections
// ---------------------------------------------------------------------------

function ReflectionsTab() {
  const { t } = useTranslation();
  const qc = useQueryClient();

  // ---- query state ---------------------------------------------------
  // ``type``           — backend filter
  // ``sessionFilter``  — backend filter (session_id)
  // ``runFilter``      — *client-side* prefix filter (the backend's
  //                      list endpoint takes session_id only, not run_id;
  //                      we filter the response in JS to keep the
  //                      surface small. Bulk delete still uses both.)
  const [type, setType] = useState<ReflectionType | "">("");
  const [sessionFilter, setSessionFilter] = useState("");
  const [runFilter, setRunFilter] = useState("");
  const [content, setContent] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [editing, setEditing] = useState<Reflection | null>(null);

  const list = useQuery({
    queryKey: ["memory", "reflections", { type, sessionFilter }],
    queryFn: () =>
      memoryApi.listReflections({
        type: type || undefined,
        session_id: sessionFilter.trim() || undefined,
        n: 200,
      }),
  });

  // Apply the run-id filter client-side on the already-narrowed list.
  // ``items`` is small in practice (≤200) so a JS filter is fine.
  const filteredItems = useMemo(() => {
    if (!list.data) return [];
    const run = runFilter.trim();
    if (!run) return list.data.items;
    return list.data.items.filter((r) => (r.source_run_id ?? "").includes(run));
  }, [list.data, runFilter]);

  const create = useMutation({
    mutationFn: () =>
      memoryApi.createReflection({
        type: (type || "reflection") as ReflectionType,
        content: content.trim(),
        tags: tagsInput
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
      }),
    onSuccess: () => {
      toast.success(t("memory.reflections.toast.added"));
      setContent("");
      setTagsInput("");
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.reflections.toast.appendFailed", { error: err.message })),
  });

  const update = useMutation({
    mutationFn: (args: {
      id: string;
      payload: { type?: ReflectionType; content?: string; tags?: string[] };
    }) => memoryApi.updateReflection(args.id, args.payload),
    onSuccess: () => {
      toast.success(t("memory.reflections.toast.updated"));
      setEditing(null);
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.reflections.toast.updateFailed", { error: err.message })),
  });

  const remove = useMutation({
    mutationFn: (id: string) => memoryApi.deleteReflection(id),
    onSuccess: () => {
      toast.success(t("memory.reflections.toast.deleted"));
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.reflections.toast.deleteFailed", { error: err.message })),
  });

  const bulkRemove = useMutation({
    mutationFn: (params: { session_id?: string; source_run_id?: string }) =>
      memoryApi.bulkDeleteReflections(params),
    onSuccess: (res) => {
      toast.success(t("memory.reflections.toast.bulkDeleted", { count: res.deleted }));
      void qc.invalidateQueries({ queryKey: ["memory"] });
    },
    onError: (err: Error) =>
      toast.error(t("memory.reflections.toast.bulkFailed", { error: err.message })),
  });

  const triggerBulkDelete = () => {
    const sid = sessionFilter.trim();
    const rid = runFilter.trim();
    if (!sid && !rid) {
      // Defence in depth — match the backend's 400. Friendlier to refuse
      // here than to bounce through the network with a non-actionable
      // toast.
      toast.error(t("memory.reflections.bulkRequiresFilter"));
      return;
    }
    if (
      !confirm(
        t("memory.reflections.confirmBulkDelete", {
          session: sid || "*",
          run: rid || "*",
        }),
      )
    ) {
      return;
    }
    bulkRemove.mutate({
      session_id: sid || undefined,
      source_run_id: rid || undefined,
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <ListTree className="h-4 w-4" /> {t("memory.reflections.title")}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* ---- filter row -------------------------------------------- */}
        <div className="grid gap-3 sm:grid-cols-[8rem_1fr_1fr_auto]">
          <div className="flex flex-col gap-1">
            <Label htmlFor="rf-type">{t("memory.reflections.fields.type")}</Label>
            <select
              id="rf-type"
              className="h-9 rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
              value={type}
              onChange={(e) => setType((e.target.value || "") as ReflectionType | "")}
            >
              <option value="">{t("memory.reflections.any")}</option>
              {REFLECTION_TYPES.map((tp) => (
                <option key={tp} value={tp}>
                  {tp}
                </option>
              ))}
            </select>
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rf-session">{t("memory.reflections.fields.session")}</Label>
            <Input
              id="rf-session"
              value={sessionFilter}
              onChange={(e) => setSessionFilter(e.target.value)}
              placeholder={t("memory.reflections.sessionPlaceholder") ?? ""}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rf-run">{t("memory.reflections.fields.run")}</Label>
            <Input
              id="rf-run"
              value={runFilter}
              onChange={(e) => setRunFilter(e.target.value)}
              placeholder={t("memory.reflections.runPlaceholder") ?? ""}
            />
          </div>
          <Button
            variant="destructive"
            onClick={triggerBulkDelete}
            disabled={bulkRemove.isPending}
            className="self-end"
            title={t("memory.reflections.bulkHint") ?? ""}
          >
            <Trash2 className="mr-1 h-3.5 w-3.5" />
            {t("memory.reflections.bulkDelete")}
          </Button>
        </div>

        {/* ---- create row -------------------------------------------- */}
        <div className="grid gap-3 sm:grid-cols-[1fr_8rem_auto]">
          <div className="flex flex-col gap-1">
            <Label htmlFor="rf-content">{t("memory.reflections.appendTitle")}</Label>
            <Input
              id="rf-content"
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder={t("memory.reflections.appendPlaceholder") ?? ""}
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label htmlFor="rf-tags">{t("memory.reflections.fields.tags")}</Label>
            <Input
              id="rf-tags"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
              placeholder="qa, planning"
            />
          </div>
          <Button
            onClick={() => create.mutate()}
            disabled={!content.trim() || create.isPending}
            className="self-end"
          >
            {create.isPending
              ? t("memory.reflections.saving")
              : t("memory.reflections.append")}
          </Button>
        </div>

        {/* ---- list -------------------------------------------------- */}
        {list.isLoading ? (
          <Skeleton className="h-32 w-full" />
        ) : list.isError ? (
          <p className="text-sm text-[var(--color-destructive)]">
            {t("memory.reflections.loadFailed", { error: (list.error as Error).message })}
          </p>
        ) : filteredItems.length === 0 ? (
          <EmptyState
            icon={ListTree}
            title={t("memory.reflections.emptyTitle")}
            description={t("memory.reflections.emptyDescription")}
          />
        ) : (
          <ul className="divide-y rounded-md border">
            {filteredItems.map((r) => (
              <ReflectionRow
                key={r.id}
                reflection={r}
                onEdit={() => setEditing(r)}
                onDelete={() => {
                  if (
                    confirm(
                      t("memory.reflections.confirmDelete", {
                        snippet: r.content.slice(0, 60),
                      }),
                    )
                  ) {
                    remove.mutate(r.id);
                  }
                }}
              />
            ))}
          </ul>
        )}
      </CardContent>

      {editing ? (
        <ReflectionEditDialog
          reflection={editing}
          submitting={update.isPending}
          onCancel={() => setEditing(null)}
          onSubmit={(payload) => update.mutate({ id: editing.id, payload })}
        />
      ) : null}
    </Card>
  );
}

function ReflectionRow({
  reflection,
  onEdit,
  onDelete,
}: {
  reflection: Reflection;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = useTranslation();
  return (
    <li className="space-y-1 p-4 hover:bg-[var(--color-muted)]">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{reflection.type}</Badge>
        {reflection.tags.map((tag) => (
          <Badge key={tag} variant="neutral">
            {tag}
          </Badge>
        ))}
        {reflection.created_at && (
          <span className="ml-auto text-[10px] text-[var(--color-muted-foreground)]">
            {formatDistanceToNow(new Date(reflection.created_at), { addSuffix: true })}
          </span>
        )}
        <Button size="icon" variant="ghost" onClick={onEdit} className="h-7 w-7" aria-label={t("common.edit") ?? "Edit"}>
          <Pencil className="h-3.5 w-3.5" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          onClick={onDelete}
          className="h-7 w-7 text-[var(--color-destructive)]"
          aria-label={t("common.delete") ?? "Delete"}
        >
          <Trash2 className="h-3.5 w-3.5" />
        </Button>
      </div>
      <p className="whitespace-pre-wrap text-sm">{reflection.content}</p>
      <p className="text-[10px] text-[var(--color-muted-foreground)]">
        {reflection.id}
        {reflection.source_run_id ? ` · run ${reflection.source_run_id}` : null}
        {reflection.session_id ? ` · session ${reflection.session_id}` : null}
      </p>
    </li>
  );
}

function ReflectionEditDialog({
  reflection,
  submitting,
  onCancel,
  onSubmit,
}: {
  reflection: Reflection;
  submitting: boolean;
  onCancel: () => void;
  onSubmit: (payload: { type?: ReflectionType; content?: string; tags?: string[] }) => void;
}) {
  const { t } = useTranslation();
  const [type, setType] = useState<ReflectionType>(reflection.type);
  const [content, setContent] = useState(reflection.content);
  const [tagsInput, setTagsInput] = useState(reflection.tags.join(", "));

  // ESC closes — parity with PaperFormDrawer. ``useEffect`` (NOT
  // useMemo) because we need React to actually run the cleanup on
  // unmount; useMemo would silently leak the listener.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);

  const canSubmit = content.trim().length > 0 && !submitting;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      onClick={(e) => {
        if (e.target === e.currentTarget) onCancel();
      }}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (!canSubmit) return;
          onSubmit({
            type,
            content: content.trim(),
            tags: tagsInput
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
          });
        }}
        className="w-full max-w-xl space-y-3 rounded-lg border bg-[var(--color-background)] p-5 shadow-xl"
      >
        <h2 className="text-sm font-semibold">{t("memory.reflections.editTitle")}</h2>
        <div className="grid gap-3 sm:grid-cols-[10rem_1fr]">
          <div className="space-y-1">
            <Label htmlFor="rf-edit-type">{t("memory.reflections.fields.type")}</Label>
            <select
              id="rf-edit-type"
              className="h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-2 text-sm"
              value={type}
              onChange={(e) => setType(e.target.value as ReflectionType)}
            >
              {REFLECTION_TYPES.map((tp) => (
                <option key={tp} value={tp}>
                  {tp}
                </option>
              ))}
            </select>
          </div>
          <div className="space-y-1">
            <Label htmlFor="rf-edit-tags">{t("memory.reflections.fields.tags")}</Label>
            <Input
              id="rf-edit-tags"
              value={tagsInput}
              onChange={(e) => setTagsInput(e.target.value)}
            />
          </div>
        </div>
        <div className="space-y-1">
          <Label htmlFor="rf-edit-content">{t("memory.reflections.fields.content")}</Label>
          <Textarea
            id="rf-edit-content"
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={6}
          />
          <p className="text-[10px] text-[var(--color-muted-foreground)]">
            {t("memory.reflections.editHint")}
          </p>
        </div>
        <div className="flex items-center justify-end gap-2 pt-1">
          <Button type="button" variant="outline" onClick={onCancel} disabled={submitting}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" disabled={!canSubmit}>
            {submitting ? t("common.saving") : t("common.save")}
          </Button>
        </div>
      </form>
    </div>
  );
}

