import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { formatDistanceToNow } from "date-fns";
import { ActivitySquare, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { toast } from "sonner";

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
  const qc = useQueryClient();
  const tasksQ = useQuery({
    queryKey: ["tasks", { limit: 100 }],
    queryFn: () => api<TaskListResponse>("/api/tasks?limit=100"),
    refetchInterval: 3000,
  });

  const deleteMut = useMutation({
    mutationFn: (taskId: string) =>
      api(`/api/tasks/${taskId}`, { method: "DELETE" }),
    onSuccess: () => {
      toast.success("Task deleted");
      void qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (err: unknown) =>
      toast.error(`Delete failed: ${err instanceof Error ? err.message : String(err)}`),
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
                <li key={task.id} className="flex items-center gap-2 px-4 py-3 hover:bg-[var(--color-accent)]/40 group">
                  <Link
                    to={`/tasks/${task.id}`}
                    className="flex items-center gap-4 flex-1 min-w-0"
                  >
                    <span className="rounded bg-[var(--color-muted)] px-1.5 py-0.5 font-mono text-[10px] shrink-0">
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
                  {(task.status === "ok" || task.status === "error" || task.status === "cancelled" || task.status === "waiting") && (
                    <button
                      type="button"
                      className="shrink-0 p-1 rounded opacity-0 group-hover:opacity-100 hover:bg-red-100 dark:hover:bg-red-900/20 text-[var(--color-muted-foreground)] hover:text-red-500 transition-all"
                      title="Delete task"
                      onClick={(e) => {
                        e.preventDefault();
                        if (confirm(`Delete task ${task.id.slice(0, 12)}? This cannot be undone.`)) {
                          deleteMut.mutate(task.id);
                        }
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
