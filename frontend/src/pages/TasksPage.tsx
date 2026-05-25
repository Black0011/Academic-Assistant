import { useQuery } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ActivitySquare } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { StatusPill } from "@/components/common/StatusPill";
import { TaskError } from "@/components/common/TaskError";
import { Card, CardContent } from "@/components/ui/Card";
import { LinkButton } from "@/components/ui/LinkButton";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import type { TaskListResponse } from "@/types/api";

export function TasksPage() {
  const { t } = useTranslation();
  const tasksQ = useQuery({
    queryKey: ["tasks", { limit: 100 }],
    queryFn: () => api<TaskListResponse>("/api/tasks?limit=100"),
    refetchInterval: 3000,
  });

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("tasks.title")}
        description={t("tasks.description")}
        actions={<LinkButton to="/research">{t("research.newRun")}</LinkButton>}
      />

      <Card>
        <CardContent className="p-0">
          {tasksQ.isLoading && (
            <div className="space-y-2 p-4">
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
              <Skeleton className="h-12 w-full" />
            </div>
          )}
          {tasksQ.data && tasksQ.data.items.length === 0 && (
            <div className="p-6">
              <EmptyState
                icon={ActivitySquare}
                title={t("dashboard.noTasksYet")}
                description={t("dashboard.noTasksHint")}
                action={<LinkButton to="/research">{t("dashboard.startResearch")}</LinkButton>}
              />
            </div>
          )}
          {tasksQ.data && tasksQ.data.items.length > 0 && (
            <ul className="divide-y">
              {tasksQ.data.items.map((task) => (
                <li key={task.id}>
                  <Link
                    to={`/tasks/${task.id}`}
                    className="flex items-center gap-4 px-4 py-3 hover:bg-[var(--color-accent)]/40"
                  >
                    <span className="rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px]">
                      {task.workflow}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">
                        {task.query || (
                          <em className="text-[var(--color-muted-foreground)]">
                            {t("dashboard.noQuery")}
                          </em>
                        )}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-[var(--color-muted-foreground)]">
                        <span className="font-mono">{task.id.slice(0, 12)}</span>
                        <span>·</span>
                        <span>{formatDistanceToNow(new Date(task.created_at), { addSuffix: true })}</span>
                      </div>
                      {task.error && (
                        <div className="mt-1 max-w-full overflow-hidden">
                          <TaskError error={task.error} density="compact" />
                        </div>
                      )}
                    </div>
                    <StatusPill status={task.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
