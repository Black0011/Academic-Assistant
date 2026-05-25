import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import {
  ActivitySquare,
  BookOpenText,
  BrainCircuit,
  FileText,
  Hammer,
  Library,
  Lightbulb,
  Workflow,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusPill } from "@/components/common/StatusPill";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/LinkButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import type {
  ManuscriptStats,
  MemoryStats,
  TaskListResponse,
  ToolInfo,
  VersionInfo,
  WorkflowInfo,
} from "@/types/api";

interface StatCardProps {
  icon: typeof Library;
  label: string;
  value: string | number;
  hint?: string;
}

function StatCard({ icon: Icon, label, value, hint }: StatCardProps) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 p-5 pt-5">
        <div>
          <div className="text-xs uppercase tracking-wider text-[var(--color-muted-foreground)]">
            {label}
          </div>
          <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
          {hint && <div className="mt-1 text-xs text-[var(--color-muted-foreground)]">{hint}</div>}
        </div>
        <div className="rounded-md bg-[var(--color-accent)] p-2 text-[var(--color-accent-foreground)]">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
      </CardContent>
    </Card>
  );
}

export function DashboardPage() {
  const { t } = useTranslation();
  const version = useQuery({
    queryKey: ["version"],
    queryFn: () => api<VersionInfo>("/api/version"),
  });
  const memory = useQuery({
    queryKey: ["memory", "stats"],
    queryFn: () => api<MemoryStats>("/api/memory/stats"),
  });
  const manuscripts = useQuery({
    queryKey: ["manuscripts", "stats"],
    queryFn: () => api<ManuscriptStats>("/api/manuscripts/stats"),
  });
  const workflows = useQuery({
    queryKey: ["workflows"],
    queryFn: () => api<WorkflowInfo[]>("/api/workflows"),
  });
  const tools = useQuery({
    queryKey: ["tools"],
    queryFn: () => api<ToolInfo[]>("/api/tools"),
  });
  const recent = useQuery({
    queryKey: ["tasks", { limit: 5 }],
    queryFn: () => api<TaskListResponse>("/api/tasks?limit=5"),
    refetchInterval: 5000,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("dashboard.title")}
        description={t("dashboard.description")}
        actions={
          <LinkButton to="/research" variant="primary">
            <BookOpenText className="h-4 w-4" /> {t("dashboard.newResearch")}
          </LinkButton>
        }
      />

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard
          icon={Library}
          label={t("dashboard.stats.knowledgeCards")}
          value={memory.data?.knowledge_count ?? "—"}
          hint={
            memory.data
              ? t("dashboard.stats.knowledgeHint", {
                  synth: memory.data.synthesis_count,
                  vec: memory.data.vector_count ?? "?",
                })
              : undefined
          }
        />
        <StatCard
          icon={Lightbulb}
          label={t("dashboard.stats.heuristics")}
          value={memory.data?.heuristic_count ?? "—"}
          hint={
            memory.data?.reflection_count != null
              ? t("dashboard.stats.heuristicsHint", { count: memory.data.reflection_count })
              : undefined
          }
        />
        <StatCard
          icon={FileText}
          label={t("dashboard.stats.manuscripts")}
          value={manuscripts.data?.total ?? "—"}
          hint={
            manuscripts.data
              ? Object.entries(manuscripts.data.by_status)
                  .map(([k, v]) => `${k}:${v}`)
                  .join(" · ")
              : undefined
          }
        />
        <StatCard
          icon={Hammer}
          label={t("dashboard.stats.toolsWorkflows")}
          value={`${tools.data?.length ?? "?"} / ${workflows.data?.length ?? "?"}`}
          hint={
            version.data?.llm_provider
              ? t("dashboard.stats.llmHint", { provider: version.data.llm_provider })
              : undefined
          }
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="flex items-center gap-2">
              <ActivitySquare className="h-4 w-4" /> {t("dashboard.recentTasks")}
            </CardTitle>
            <Link
              to="/tasks"
              className="text-xs font-medium text-[var(--color-primary)] hover:underline"
            >
              {t("common.viewAll")} →
            </Link>
          </CardHeader>
          <CardContent className="space-y-2">
            {recent.isLoading && (
              <>
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </>
            )}
            {recent.data && recent.data.items.length === 0 && (
              <EmptyState
                icon={ActivitySquare}
                title={t("dashboard.noTasksYet")}
                description={t("dashboard.noTasksHint")}
                action={<LinkButton to="/research">{t("dashboard.startResearch")}</LinkButton>}
              />
            )}
            {recent.data?.items.map((task) => (
              <div
                key={task.id}
                className="flex items-center justify-between gap-3 rounded-md border bg-[var(--color-background)] p-3 text-sm"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px]">
                      {task.workflow}
                    </span>
                    <span className="truncate">
                      {task.query || <em>{t("dashboard.noQuery")}</em>}
                    </span>
                  </div>
                  <div className="mt-0.5 text-xs text-[var(--color-muted-foreground)]">
                    {formatDistanceToNow(new Date(task.created_at), { addSuffix: true })} ·
                    <span className="ml-1 font-mono">{task.id.slice(0, 8)}</span>
                  </div>
                </div>
                <StatusPill status={task.status} />
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <BrainCircuit className="h-4 w-4" /> {t("dashboard.memoryBackends")}
            </CardTitle>
          </CardHeader>
          <CardContent>
            {version.data ? (
              <dl className="space-y-2 text-sm">
                {Object.entries(version.data.memory).map(([k, v]) => (
                  <div key={k} className="flex justify-between">
                    <dt className="text-[var(--color-muted-foreground)] capitalize">{k}</dt>
                    <dd className="font-mono text-xs">{v ?? "—"}</dd>
                  </div>
                ))}
              </dl>
            ) : (
              <Skeleton className="h-32 w-full" />
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Workflow className="h-4 w-4" /> {t("dashboard.registeredWorkflows")}
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {workflows.isLoading && <Skeleton className="h-16 w-full" />}
          {workflows.data?.map((w) => (
            <div
              key={w.name}
              className="rounded-md border bg-[var(--color-background)] p-3 text-sm"
            >
              <div className="font-medium">{w.name}</div>
              {w.description && (
                <div className="mt-1 text-xs text-[var(--color-muted-foreground)]">
                  {w.description}
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}
