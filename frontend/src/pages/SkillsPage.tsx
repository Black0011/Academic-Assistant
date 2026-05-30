/**
 * Skills page (M7.2).
 *
 * Layout: a left list of installed skills (active + disabled, with stats)
 * and a right-hand panel with three tabs — **Body** (SKILL.md) / **Scripts**
 * (Monaco-based viewer/editor with dry-run) / **Invocations** (the last 30
 * days of executions). An "Install skill" drawer lets admins compose a
 * minimal SKILL.md + scripts pair from a starter template.
 *
 * Progressive disclosure on the wire is mirrored on the screen:
 *
 *   - The list query only fetches frontmatter + invocation stats.
 *   - Selecting a skill triggers the body fetch (SKILL.md only).
 *   - Selecting a script triggers an on-demand source fetch.
 *
 * All write paths run through TanStack Query mutations + sonner toasts so
 * the UI stays optimistic and reversible.
 */
import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  Activity,
  AlertTriangle,
  CircleSlash,
  CodeXml,
  FileCode2,
  LayoutGrid,
  List as ListIcon,
  PlayCircle,
  Plus,
  Power,
  RefreshCcw,
  ScrollText,
  Trash2,
  Wrench,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { SkillsGraphView } from "@/components/skills/SkillsGraphView";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { Skeleton } from "@/components/ui/Skeleton";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { skillsApi } from "@/lib/skills";
import { useUiStore } from "@/stores/uiStore";
import type {
  SkillDetail,
  SkillDryRunResponse,
  SkillInstallInput,
  SkillInvocation,
  SkillInvocationStatus,
  SkillSummary,
} from "@/types/api";

const TEMPLATE_BODY = `---
name: my-skill
description: >-
  Replace this with a one-paragraph capability summary.
  End with "Use when ...".
domain: meta
triggers:
  - replace me
  - example trigger
version: "1.0.0"
---

# My Skill

Walk an agent through *how* to do the thing. Mention any required inputs,
quirks, and the expected output shape. Keep it under ~200 lines.
`;

const TEMPLATE_SCRIPT = `#!/usr/bin/env python3
"""Short docstring summarising what the script does."""

# aaf:network none
# aaf:timeout 30
# aaf:args {"name": "string"}
import json
import sys


def main() -> int:
    args = json.loads(sys.stdin.read() or "{}")
    name = args.get("name", "world")
    sys.stdout.write(json.dumps({"hello": name}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
`;

function isDarkMode(theme: "light" | "dark" | "system"): boolean {
  if (typeof window === "undefined") return false;
  if (theme === "dark") return true;
  if (theme === "system") {
    return window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type SkillsView = "list" | "graph";

export function SkillsPage() {
  const { t } = useTranslation();
  const params = useParams();
  const navigate = useNavigate();
  // P13.D — view (list vs graph) lives in the URL so a refresh keeps it.
  // We deliberately do NOT bind it to ``useParams`` because the page
  // is already keyed by the optional skill ``name`` segment and adding
  // a second segment would force `/skills/list/foo` vs `/skills/graph/foo`
  // — uglier and not backwards-compat with bookmarks. Search param wins.
  const [searchParams, setSearchParams] = useSearchParams();
  const view: SkillsView = searchParams.get("view") === "graph" ? "graph" : "list";
  const setView = (v: SkillsView) => {
    const next = new URLSearchParams(searchParams);
    if (v === "list") next.delete("view");
    else next.set("view", v);
    setSearchParams(next, { replace: true });
  };

  const selected = params.name ?? null;
  const [installOpen, setInstallOpen] = useState(false);
  const [editingExisting, setEditingExisting] = useState<SkillSummary | null>(null);
  const [domainFilter, setDomainFilter] = useState<string>("");

  const list = useQuery({
    queryKey: ["skills", "list", { domainFilter }],
    queryFn: () => skillsApi.list({ domain: domainFilter || undefined }),
    refetchInterval: 15000,
  });

  // Graph data fetched only when the view actually wants it. Cache shared
  // via the same ``generation`` so a skill install/disable invalidates both
  // list and graph in one go.
  const graph = useQuery({
    queryKey: ["skills", "graph"],
    queryFn: () => skillsApi.getGraph(),
    enabled: view === "graph",
    refetchInterval: view === "graph" ? 15000 : false,
  });

  const items: SkillSummary[] = list.data?.items ?? [];

  // ---- P14.F: edge editor wiring ------------------------------------
  // We refetch list + graph after every successful mutation so the
  // generation counter (and the in-graph rendering of the edge) stays
  // honest. Mutations are intentionally NOT optimistic — a SKILL.md
  // frontmatter rewrite is on the order of 10ms server-side; the round
  // trip is already imperceptible. Skipping optimism removes the need
  // to maintain a parallel client-side mirror of the YAML.
  const qc = useQueryClient();

  const addEdge = useMutation({
    mutationFn: (args: { source: string; target: string }) =>
      skillsApi.updateEdges(args.source, {
        add: [{ kind: "downstream", target: args.target }],
      }),
    onSuccess: (res) => {
      if (res.warnings.length > 0) {
        // Show comments-loss warnings exactly once per edit.
        for (const w of res.warnings) toast.warning(w);
      }
      toast.success(t("skills.graph.toast.edgeAdded"));
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
    onError: (err: Error) =>
      toast.error(t("skills.graph.toast.edgeAddFailed", { error: err.message })),
  });

  const removeEdge = useMutation({
    mutationFn: async (e: {
      source: string;
      target: string;
      declared_by: "source" | "target" | "both";
    }) => {
      // The backend's :edges endpoint operates on ONE side of an edge
      // per call. Removing a "both"-declared edge needs two calls —
      // one to each endpoint — and we only succeed if both succeed.
      // Promise.all here is fine: both writes are independent files.
      const calls: Promise<unknown>[] = [];
      if (e.declared_by === "source" || e.declared_by === "both") {
        calls.push(
          skillsApi.updateEdges(e.source, {
            remove: [{ kind: "downstream", target: e.target }],
          }),
        );
      }
      if (e.declared_by === "target" || e.declared_by === "both") {
        calls.push(
          skillsApi.updateEdges(e.target, {
            remove: [{ kind: "upstream", target: e.source }],
          }),
        );
      }
      await Promise.all(calls);
    },
    onSuccess: () => {
      toast.success(t("skills.graph.toast.edgeRemoved"));
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
    onError: (err: Error) =>
      toast.error(t("skills.graph.toast.edgeRemoveFailed", { error: err.message })),
  });

  const handleSelect = (name: string): void => {
    // Preserve view= search param so picking a node from the graph view
    // doesn't snap you back to list.
    void navigate({
      pathname: `/skills/${encodeURIComponent(name)}`,
      search: searchParams.toString() ? `?${searchParams.toString()}` : "",
    });
  };

  const handleClose = (): void => {
    void navigate({
      pathname: "/skills",
      search: searchParams.toString() ? `?${searchParams.toString()}` : "",
    });
  };

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("skills.title")}
        description={t("skills.description")}
        actions={
          <div className="flex items-center gap-2">
            <ViewToggle value={view} onChange={setView} />
            <Input
              placeholder="Filter by domain"
              className="h-8 w-40 text-xs"
              value={domainFilter}
              onChange={(event) => setDomainFilter(event.target.value)}
            />
            <Button
              size="sm"
              onClick={() => {
                setEditingExisting(null);
                setInstallOpen(true);
              }}
              className="gap-1"
            >
              <Plus className="h-3.5 w-3.5" /> Install skill
            </Button>
          </div>
        }
      />

      {view === "graph" ? (
        <div className="grid gap-4 lg:grid-cols-[1fr_18rem]">
          {graph.isLoading ? (
            <Skeleton className="h-[420px] w-full" />
          ) : graph.isError ? (
            <Card>
              <CardContent className="p-6 text-sm text-[var(--color-destructive)]">
                {(graph.error as Error).message}
              </CardContent>
            </Card>
          ) : graph.data ? (
            <SkillsGraphView
              graph={graph.data}
              selected={selected}
              onSelect={(name) => (name ? handleSelect(name) : handleClose())}
              onAddEdge={(source, target) =>
                addEdge.mutate({ source, target })
              }
              onRemoveEdge={(edge) => removeEdge.mutate(edge)}
              busy={addEdge.isPending || removeEdge.isPending}
            />
          ) : null}
          {selected ? (
            <SkillDetailPanel
              name={selected}
              onClose={handleClose}
              onEdit={(summary) => {
                setEditingExisting(summary);
                setInstallOpen(true);
              }}
            />
          ) : (
            <Card className="h-fit">
              <CardContent className="p-4 text-xs text-[var(--color-muted-foreground)]">
                {t("skills.graph.selectHint")}
              </CardContent>
            </Card>
          )}
        </div>
      ) : (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <SkillList
            items={items}
            loading={list.isLoading}
            error={list.isError ? (list.error as Error) : null}
            generation={list.data?.generation ?? 0}
            selected={selected}
            onSelect={handleSelect}
          />

          {selected ? (
            <SkillDetailPanel
              name={selected}
              onClose={handleClose}
              onEdit={(summary) => {
                setEditingExisting(summary);
                setInstallOpen(true);
              }}
            />
          ) : (
            <EmptyState
              icon={Wrench}
              title={items.length === 0 ? "No skills installed yet" : "Select a skill"}
              description={
                items.length === 0
                  ? "Install one with the button above, or drop a SKILL.md into the configured skills_root and reload."
                  : "Pick a skill on the left to see its body, scripts, and recent invocations."
              }
              action={
                items.length === 0 ? (
                  <Button
                    size="sm"
                    onClick={() => {
                      setEditingExisting(null);
                      setInstallOpen(true);
                    }}
                  >
                    Install skill
                  </Button>
                ) : null
              }
            />
          )}
        </div>
      )}

      {installOpen && (
        <InstallDrawer
          editing={editingExisting}
          onClose={() => setInstallOpen(false)}
          onInstalled={(name) => {
            setInstallOpen(false);
            handleSelect(name);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// View toggle — segmented control in the page header. Two-option Radix-style
// pattern, hand-rolled to avoid a Tabs primitive when only one consumer
// exists.
// ---------------------------------------------------------------------------

function ViewToggle({
  value,
  onChange,
}: {
  value: SkillsView;
  onChange: (v: SkillsView) => void;
}) {
  const { t } = useTranslation();
  const items: Array<{ id: SkillsView; icon: typeof ListIcon; labelKey: string }> = [
    { id: "list", icon: ListIcon, labelKey: "skills.view.list" },
    { id: "graph", icon: LayoutGrid, labelKey: "skills.view.graph" },
  ];
  return (
    <div className="flex items-center rounded-md border bg-[var(--color-muted)]/30 p-0.5">
      {items.map(({ id, icon: Icon, labelKey }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={cn(
            "flex h-7 items-center gap-1 rounded px-2 text-xs transition-colors",
            value === id
              ? "bg-[var(--color-background)] shadow-sm"
              : "text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]",
          )}
          aria-pressed={value === id}
        >
          <Icon className="h-3.5 w-3.5" />
          {t(labelKey)}
        </button>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

function SkillList({
  items,
  loading,
  error,
  generation,
  selected,
  onSelect,
}: {
  items: SkillSummary[];
  loading: boolean;
  error: Error | null;
  generation: number;
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <Card className="h-fit">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center justify-between gap-2 text-sm">
          <span className="flex items-center gap-2">
            <Wrench className="h-4 w-4" /> Installed
          </span>
          <span className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            gen {generation}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        {loading && (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}
        {error && (
          <p className="text-xs text-[var(--color-destructive)]">
            Failed to load: {error.message}
          </p>
        )}
        {!loading && !error && items.length === 0 && (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            No skills match the current filter.
          </p>
        )}
        <ul className="space-y-1">
          {items.map((item) => (
            <li key={item.name}>
              <button
                type="button"
                onClick={() => onSelect(item.name)}
                className={cn(
                  "w-full rounded-md border px-3 py-2 text-left text-xs transition-colors",
                  selected === item.name
                    ? "border-[var(--color-primary)] bg-[var(--color-accent)]"
                    : "border-transparent hover:bg-[var(--color-accent)]/60",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-semibold">{item.name}</span>
                  {!item.enabled && <Badge variant="outline">disabled</Badge>}
                  {item.uses_llm_any && item.enabled && (
                    <Badge variant="primary">llm</Badge>
                  )}
                </div>
                {item.description && (
                  <p className="mt-1 line-clamp-2 text-[11px] text-[var(--color-muted-foreground)]">
                    {item.description}
                  </p>
                )}
                <div className="mt-1.5 flex items-center justify-between gap-2 text-[10px] text-[var(--color-muted-foreground)]">
                  <span>
                    {item.invocation_count_30d > 0
                      ? `${item.invocation_count_30d} runs · ${formatMs(item.avg_elapsed_ms)} avg`
                      : "no recent runs"}
                  </span>
                  <span>{item.last_used_at ? relTime(item.last_used_at) : "—"}</span>
                </div>
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

type DetailTab = "body" | "scripts" | "invocations";

function SkillDetailPanel({
  name,
  onClose,
  onEdit,
}: {
  name: string;
  onClose: () => void;
  onEdit: (summary: SkillSummary) => void;
}) {
  const qc = useQueryClient();
  const detailQ = useQuery({
    queryKey: ["skills", "detail", name],
    queryFn: () => skillsApi.get(name),
  });

  const [tab, setTab] = useState<DetailTab>("body");

  const detail = detailQ.data;

  const reload = useMutation({
    mutationFn: () => skillsApi.reload(name),
    onSuccess: (resp) => {
      toast.success(`Reloaded — generation now ${resp.generation}`);
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
    onError: (err: Error) => toast.error(`Reload failed: ${err.message}`),
  });

  const disable = useMutation({
    mutationFn: () => skillsApi.disable(name),
    onSuccess: () => {
      toast.success(`Disabled ${name}`, {
        action: {
          label: "Undo",
          onClick: () => {
            skillsApi
              .enable(name)
              .then(() => {
                toast.success("Restored");
                void qc.invalidateQueries({ queryKey: ["skills"] });
              })
              .catch((err: Error) => toast.error(`Restore failed: ${err.message}`));
          },
        },
        duration: 5000,
      });
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
    onError: (err: Error) => toast.error(`Disable failed: ${err.message}`),
  });

  const enable = useMutation({
    mutationFn: () => skillsApi.enable(name),
    onSuccess: () => {
      toast.success(`Enabled ${name}`);
      void qc.invalidateQueries({ queryKey: ["skills"] });
    },
    onError: (err: Error) => toast.error(`Enable failed: ${err.message}`),
  });

  if (detailQ.isLoading) {
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

  if (detailQ.isError || !detail) {
    return (
      <Card>
        <CardContent className="flex flex-col gap-3 p-6">
          <div className="flex items-center gap-2 text-sm text-[var(--color-destructive)]">
            <AlertTriangle className="h-4 w-4" />
            Failed to load: {(detailQ.error as Error)?.message ?? "not found"}
          </div>
          <Button size="sm" variant="outline" onClick={onClose}>
            Back
          </Button>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="flex min-h-[40rem] flex-col">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <CardTitle className="text-base">{detail.name}</CardTitle>
              <Badge variant={detail.enabled ? "success" : "outline"}>
                {detail.enabled ? "enabled" : "disabled"}
              </Badge>
              <Badge variant="neutral" className="font-mono">
                v{detail.version}
              </Badge>
              {detail.domain && <Badge variant="outline">{detail.domain}</Badge>}
            </div>
            {detail.description && (
              <p className="text-sm text-[var(--color-muted-foreground)]">
                {detail.description}
              </p>
            )}
            <p className="text-[10px] font-mono text-[var(--color-muted-foreground)]">
              {detail.version_hash || "—"} · {detail.loaded_from || "—"}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <Button
              size="sm"
              variant="outline"
              onClick={() => onEdit(detail)}
              className="gap-1"
            >
              <FileCode2 className="h-3.5 w-3.5" /> Edit
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => reload.mutate()}
              disabled={reload.isPending}
              className="gap-1"
            >
              <RefreshCcw className={cn("h-3.5 w-3.5", reload.isPending && "animate-spin")} />
              Reload
            </Button>
            {detail.enabled ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  if (
                    window.confirm(
                      `Disable ${detail.name}? It will be moved to _disabled/ and excluded from the registry.`,
                    )
                  ) {
                    disable.mutate();
                  }
                }}
                disabled={disable.isPending}
                className="gap-1"
              >
                <CircleSlash className="h-3.5 w-3.5" /> Disable
              </Button>
            ) : (
              <Button
                size="sm"
                variant="primary"
                onClick={() => enable.mutate()}
                disabled={enable.isPending}
                className="gap-1"
              >
                <Power className="h-3.5 w-3.5" /> Enable
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onClose} className="gap-1">
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
        <DetailTabs tab={tab} onChange={setTab} />
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {tab === "body" && <BodyTab detail={detail} />}
        {tab === "scripts" && <ScriptsTab detail={detail} />}
        {tab === "invocations" && <InvocationsTab name={detail.name} />}
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
  const TABS: ReadonlyArray<{ id: DetailTab; label: string; icon: typeof CodeXml }> = [
    { id: "body", label: "Body", icon: ScrollText },
    { id: "scripts", label: "Scripts", icon: CodeXml },
    { id: "invocations", label: "Invocations", icon: Activity },
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

// ---------------------------------------------------------------------------
// Body / Scripts / Invocations tabs
// ---------------------------------------------------------------------------

function BodyTab({ detail }: { detail: SkillDetail }) {
  const themeMode = useUiStore((s) => s.theme);
  const isDark = isDarkMode(themeMode);
  return (
    <div className="flex h-[34rem] flex-col">
      <Editor
        height="100%"
        defaultLanguage="markdown"
        value={detail.body_md}
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

function ScriptsTab({ detail }: { detail: SkillDetail }) {
  const [active, setActive] = useState<string>(detail.scripts_detail[0]?.name ?? "");
  const [args, setArgs] = useState("{}");
  const [dryRun, setDryRun] = useState<SkillDryRunResponse | null>(null);
  const themeMode = useUiStore((s) => s.theme);
  const isDark = isDarkMode(themeMode);
  const qc = useQueryClient();

  useEffect(() => {
    setActive(detail.scripts_detail[0]?.name ?? "");
    setDryRun(null);
  }, [detail.name, detail.scripts_detail]);

  const sourceQ = useQuery({
    queryKey: ["skills", "script", detail.name, active],
    queryFn: () =>
      active ? skillsApi.getScript(detail.name, active) : Promise.resolve(null),
    enabled: Boolean(active) && detail.enabled,
  });

  const dry = useMutation({
    mutationFn: (parsed: Record<string, unknown>) =>
      skillsApi.dryRun(detail.name, active, parsed),
    onSuccess: (resp) => {
      setDryRun(resp);
      if (resp.ok) toast.success(`dry-run ok in ${formatMs(resp.duration_ms)}`);
      else if (resp.timed_out) toast.error("dry-run timed out");
      else toast.error(`dry-run exit ${resp.returncode}`);
      void qc.invalidateQueries({ queryKey: ["skills", "invocations", detail.name] });
    },
    onError: (err: Error) => toast.error(`dry-run failed: ${err.message}`),
  });

  if (detail.scripts_detail.length === 0) {
    return (
      <div className="p-6">
        <EmptyState
          icon={CodeXml}
          title="No scripts in this skill"
          description="Skills can be pure prompt extensions (no executable scripts). Add one by editing the skill if you need a tool the agent can call."
        />
      </div>
    );
  }

  return (
    <div className="grid h-[34rem] grid-cols-[10rem_1fr]">
      <div className="overflow-y-auto border-r p-2">
        <ul className="space-y-0.5">
          {detail.scripts_detail.map((script) => (
            <li key={script.name}>
              <button
                type="button"
                onClick={() => {
                  setActive(script.name);
                  setDryRun(null);
                }}
                className={cn(
                  "w-full rounded px-2 py-1.5 text-left text-xs",
                  active === script.name
                    ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                    : "hover:bg-[var(--color-accent)]/60",
                )}
              >
                <div className="font-medium">{script.name}</div>
                <div className="mt-0.5 text-[10px] text-[var(--color-muted-foreground)]">
                  {script.size_bytes}b
                  {script.uses_llm ? " · llm" : ""}
                  {script.requires_network ? " · net" : ""}
                </div>
              </button>
            </li>
          ))}
        </ul>
      </div>
      <div className="flex min-h-0 flex-col">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-3 py-2 text-[11px] text-[var(--color-muted-foreground)]">
          {sourceQ.data ? (
            <span className="font-mono">
              {sourceQ.data.size_bytes}b · {active}.py
            </span>
          ) : (
            <span>—</span>
          )}
          {detail.enabled ? (
            <div className="flex items-center gap-2">
              <Input
                value={args}
                onChange={(event) => setArgs(event.target.value)}
                className="h-7 w-72 font-mono text-[11px]"
                placeholder={'{"key": "value"}'}
              />
              <Button
                size="sm"
                variant="primary"
                disabled={dry.isPending}
                onClick={() => {
                  try {
                    const parsed = JSON.parse(args || "{}");
                    if (typeof parsed !== "object" || parsed === null) {
                      throw new TypeError("args must be a JSON object");
                    }
                    dry.mutate(parsed as Record<string, unknown>);
                  } catch (err) {
                    toast.error(`Invalid JSON: ${(err as Error).message}`);
                  }
                }}
                className="gap-1"
              >
                <PlayCircle className="h-3.5 w-3.5" /> Dry-run
              </Button>
            </div>
          ) : (
            <span>Skill is disabled — enable it to dry-run scripts.</span>
          )}
        </div>
        <div className="min-h-0 flex-1">
          {sourceQ.isLoading ? (
            <div className="p-3">
              <Skeleton className="h-full w-full" />
            </div>
          ) : sourceQ.isError ? (
            <div className="p-3 text-xs text-[var(--color-destructive)]">
              Failed to load script: {(sourceQ.error as Error).message}
            </div>
          ) : (
            <Editor
              height="100%"
              defaultLanguage="python"
              value={sourceQ.data?.source ?? ""}
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
          )}
        </div>
        {dryRun && <DryRunResult result={dryRun} />}
      </div>
    </div>
  );
}

function DryRunResult({ result }: { result: SkillDryRunResponse }) {
  return (
    <div className="space-y-2 border-t bg-[var(--color-background)] p-3 text-xs">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={result.ok ? "success" : result.timed_out ? "warning" : "destructive"}>
          {result.ok ? "ok" : result.timed_out ? "timed out" : `exit ${result.returncode}`}
        </Badge>
        <span className="text-[var(--color-muted-foreground)]">
          {formatMs(result.duration_ms)}
        </span>
      </div>
      {result.stdout && (
        <details open>
          <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
            stdout
          </summary>
          <pre className="mt-1 max-h-36 overflow-auto rounded bg-[var(--color-muted)]/40 p-2 font-mono text-[11px]">
            {result.stdout}
          </pre>
        </details>
      )}
      {result.stderr && (
        <details>
          <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-[var(--color-destructive)]">
            stderr
          </summary>
          <pre className="mt-1 max-h-36 overflow-auto rounded bg-[var(--color-muted)]/40 p-2 font-mono text-[11px]">
            {result.stderr}
          </pre>
        </details>
      )}
    </div>
  );
}

function InvocationsTab({ name }: { name: string }) {
  const q = useQuery({
    queryKey: ["skills", "invocations", name],
    queryFn: () => skillsApi.invocations(name, { limit: 50, window_days: 30 }),
    refetchInterval: 10_000,
  });

  if (q.isLoading) {
    return (
      <div className="space-y-2 p-4">
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
        <Skeleton className="h-8 w-full" />
      </div>
    );
  }
  if (q.isError) {
    return (
      <div className="p-4 text-sm text-[var(--color-destructive)]">
        Failed to load invocations: {(q.error as Error).message}
      </div>
    );
  }
  const items = q.data?.items ?? [];
  if (items.length === 0) {
    return (
      <div className="p-4">
        <EmptyState
          icon={Activity}
          title="No invocations yet"
          description="Calls from research workflows or dry-runs from the Scripts tab will show up here."
        />
      </div>
    );
  }
  return (
    <div className="overflow-x-auto p-2">
      <table className="w-full table-auto text-left text-xs">
        <thead className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
          <tr>
            <th className="px-2 py-1.5">When</th>
            <th className="px-2 py-1.5">Script</th>
            <th className="px-2 py-1.5">Status</th>
            <th className="px-2 py-1.5">Elapsed</th>
            <th className="px-2 py-1.5">Args</th>
            <th className="px-2 py-1.5">Result</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row, index) => (
            <InvocationRow key={`${row.tool_name}-${row.started_at}-${index}`} row={row} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function InvocationRow({ row }: { row: SkillInvocation }) {
  return (
    <tr className="border-t">
      <td className="px-2 py-1.5 text-[var(--color-muted-foreground)]">
        {relTime(row.started_at)}
      </td>
      <td className="px-2 py-1.5 font-mono">{row.script}</td>
      <td className="px-2 py-1.5">
        <Badge variant={statusVariant(row.status)}>{row.status}</Badge>
      </td>
      <td className="px-2 py-1.5 tabular-nums">{formatMs(row.duration_ms)}</td>
      <td className="px-2 py-1.5 max-w-[16rem] truncate font-mono text-[11px]">
        {row.args_summary || "—"}
      </td>
      <td className="px-2 py-1.5 max-w-[16rem] truncate font-mono text-[11px]">
        {row.error || row.result_preview || "—"}
      </td>
    </tr>
  );
}

function statusVariant(
  status: SkillInvocationStatus,
): "success" | "destructive" | "warning" | "neutral" {
  if (status === "success") return "success";
  if (status === "error") return "destructive";
  if (status === "timeout") return "warning";
  return "neutral";
}

// ---------------------------------------------------------------------------
// Install / Edit drawer
// ---------------------------------------------------------------------------

interface DraftScript {
  id: string;
  name: string;
  content: string;
}

function makeDraftId(): string {
  return `draft-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

function InstallDrawer({
  editing,
  onClose,
  onInstalled,
}: {
  editing: SkillSummary | null;
  onClose: () => void;
  onInstalled: (name: string) => void;
}) {
  const qc = useQueryClient();
  const themeMode = useUiStore((s) => s.theme);
  const isDark = isDarkMode(themeMode);

  // When editing, fetch the latest detail so we initialise the editor with
  // the up-to-date body + scripts (no "stale list summary" surprises).
  const detailQ = useQuery({
    queryKey: ["skills", "detail", editing?.name ?? "<new>"],
    queryFn: () => (editing ? skillsApi.get(editing.name) : Promise.resolve(null)),
    enabled: Boolean(editing),
  });

  const [name, setName] = useState(editing?.name ?? "my-skill");
  const [body, setBody] = useState(TEMPLATE_BODY);
  const [scripts, setScripts] = useState<DraftScript[]>([
    { id: makeDraftId(), name: "main", content: TEMPLATE_SCRIPT },
  ]);
  const [activeScriptId, setActiveScriptId] = useState(scripts[0]?.id ?? "");

  // Hydrate the form once the edit detail arrives.
  useEffect(() => {
    if (!editing) return;
    if (!detailQ.data) return;
    const fetched = detailQ.data;
    setName(fetched.name);
    setBody(fetched.body_md);
    void Promise.all(
      fetched.scripts_detail.map(async (script) => {
        try {
          const src = await skillsApi.getScript(fetched.name, script.name);
          return { id: makeDraftId(), name: script.name, content: src.source };
        } catch {
          return { id: makeDraftId(), name: script.name, content: "" };
        }
      }),
    ).then((drafts) => {
      if (drafts.length > 0) {
        setScripts(drafts);
        setActiveScriptId(drafts[0].id);
      } else {
        setScripts([]);
        setActiveScriptId("");
      }
    });
  }, [editing, detailQ.data]);

  const installMut = useMutation({
    mutationFn: (payload: SkillInstallInput) =>
      editing ? skillsApi.update(editing.name, payload) : skillsApi.install(payload),
    onSuccess: (resp) => {
      toast.success(editing ? `Updated ${resp.name}` : `Installed ${resp.name}`);
      void qc.invalidateQueries({ queryKey: ["skills"] });
      onInstalled(resp.name);
    },
    onError: (err: Error | ApiError) => {
      const detail = err instanceof ApiError ? String(err.message) : err.message;
      toast.error(`Failed: ${detail}`);
    },
  });

  const submit = (): void => {
    const cleaned: SkillInstallInput = {
      name: name.trim(),
      body_md: body,
      scripts: scripts
        .filter((script) => script.name.trim())
        .map((script) => ({ name: script.name.trim(), content: script.content })),
      overwrite: Boolean(editing),
    };
    if (!cleaned.name) {
      toast.error("Name is required");
      return;
    }
    installMut.mutate(cleaned);
  };

  const activeScript = scripts.find((script) => script.id === activeScriptId);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40 backdrop-blur-sm">
      <div className="flex w-full max-w-3xl flex-col bg-[var(--color-card)] shadow-xl">
        <div className="flex items-center justify-between border-b px-5 py-3">
          <div>
            <div className="text-sm font-semibold">
              {editing ? `Edit ${editing.name}` : "Install skill"}
            </div>
            <div className="text-xs text-[var(--color-muted-foreground)]">
              {editing
                ? "Changes write to a staging dir, atomically swap in, and hot-reload."
                : "Define a SKILL.md + 0..N scripts. The framework will validate, stage, and reload."}
            </div>
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} className="gap-1">
            <X className="h-4 w-4" />
          </Button>
        </div>
        <div className="grid min-h-0 flex-1 grid-rows-[auto_1fr_auto]">
          <div className="space-y-3 border-b p-4">
            <div className="grid gap-2">
              <Label htmlFor="skill-name">Name</Label>
              <Input
                id="skill-name"
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="my-skill"
                disabled={Boolean(editing)}
                className="font-mono"
              />
              <p className="text-[10px] text-[var(--color-muted-foreground)]">
                lowercase letters, digits, dash, or underscore. Must match the
                folder name on disk and the frontmatter <code>name</code>.
              </p>
            </div>
          </div>
          <div className="grid min-h-0 grid-rows-2 gap-3 p-4">
            <div className="flex min-h-0 flex-col gap-1.5">
              <Label className="text-[11px] font-semibold uppercase">SKILL.md</Label>
              <div className="min-h-0 flex-1 overflow-hidden rounded-md border">
                <Editor
                  height="100%"
                  defaultLanguage="markdown"
                  value={body}
                  onChange={(value) => setBody(value ?? "")}
                  theme={isDark ? "vs-dark" : "vs"}
                  options={{
                    fontSize: 13,
                    wordWrap: "on",
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    padding: { top: 12, bottom: 12 },
                  }}
                />
              </div>
            </div>
            <div className="flex min-h-0 flex-col gap-1.5">
              <div className="flex items-center justify-between">
                <Label className="text-[11px] font-semibold uppercase">Scripts</Label>
                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-1"
                    onClick={() => {
                      const draft = {
                        id: makeDraftId(),
                        name: `script_${scripts.length + 1}`,
                        content: TEMPLATE_SCRIPT,
                      };
                      setScripts((prev) => [...prev, draft]);
                      setActiveScriptId(draft.id);
                    }}
                  >
                    <Plus className="h-3.5 w-3.5" /> Add
                  </Button>
                </div>
              </div>
              <div className="grid min-h-0 flex-1 grid-cols-[10rem_1fr] gap-2">
                <ul className="space-y-0.5 overflow-y-auto rounded-md border p-1.5">
                  {scripts.length === 0 && (
                    <li className="px-2 py-1 text-[11px] text-[var(--color-muted-foreground)]">
                      No scripts. Add one or leave empty for a prompt-only skill.
                    </li>
                  )}
                  {scripts.map((script) => (
                    <li key={script.id} className="flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => setActiveScriptId(script.id)}
                        className={cn(
                          "flex-1 truncate rounded px-2 py-1 text-left text-xs",
                          activeScriptId === script.id
                            ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                            : "hover:bg-[var(--color-accent)]/60",
                        )}
                      >
                        {script.name || "(untitled)"}.py
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setScripts((prev) => prev.filter((s) => s.id !== script.id));
                          if (activeScriptId === script.id) {
                            setActiveScriptId(scripts[0]?.id ?? "");
                          }
                        }}
                        className="rounded p-1 text-[var(--color-muted-foreground)] hover:bg-[var(--color-destructive)]/20 hover:text-[var(--color-destructive)]"
                        aria-label="Remove script"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </li>
                  ))}
                </ul>
                {activeScript ? (
                  <div className="flex min-h-0 flex-col overflow-hidden rounded-md border">
                    <div className="flex items-center gap-2 border-b px-2 py-1.5">
                      <Input
                        value={activeScript.name}
                        onChange={(event) =>
                          setScripts((prev) =>
                            prev.map((s) =>
                              s.id === activeScript.id
                                ? { ...s, name: event.target.value }
                                : s,
                            ),
                          )
                        }
                        className="h-7 max-w-[12rem] font-mono text-[11px]"
                      />
                      <span className="text-[10px] text-[var(--color-muted-foreground)]">
                        {new TextEncoder().encode(activeScript.content).length}b
                      </span>
                    </div>
                    <div className="min-h-0 flex-1">
                      <Editor
                        height="100%"
                        defaultLanguage="python"
                        value={activeScript.content}
                        onChange={(value) =>
                          setScripts((prev) =>
                            prev.map((s) =>
                              s.id === activeScript.id ? { ...s, content: value ?? "" } : s,
                            ),
                          )
                        }
                        theme={isDark ? "vs-dark" : "vs"}
                        options={{
                          fontSize: 13,
                          minimap: { enabled: false },
                          scrollBeyondLastLine: false,
                          padding: { top: 8, bottom: 8 },
                        }}
                      />
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-center rounded-md border border-dashed text-xs text-[var(--color-muted-foreground)]">
                    Pick a script on the left.
                  </div>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center justify-between gap-3 border-t px-4 py-3">
            <Hints />
            <div className="flex items-center gap-2">
              <Button size="sm" variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button
                size="sm"
                onClick={submit}
                disabled={installMut.isPending}
                className="gap-1"
              >
                {installMut.isPending ? (
                  <>
                    <RefreshCcw className="h-3.5 w-3.5 animate-spin" /> Saving…
                  </>
                ) : editing ? (
                  <>Save changes</>
                ) : (
                  <>Install</>
                )}
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function Hints() {
  return (
    <ul className="hidden gap-x-4 text-[10px] text-[var(--color-muted-foreground)] md:flex">
      <li>SKILL.md ≤ 256 KB</li>
      <li>Each script ≤ 64 KB</li>
      <li>Total ≤ 1 MB</li>
    </ul>
  );
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatMs(ms: number): string {
  if (!Number.isFinite(ms) || ms <= 0) return "0 ms";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function relTime(iso: string): string {
  try {
    return formatDistanceToNow(new Date(iso), { addSuffix: true });
  } catch {
    return iso;
  }
}
