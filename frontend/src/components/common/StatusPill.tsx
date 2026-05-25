import { Badge } from "@/components/ui/Badge";
import type { TaskStatus } from "@/types/api";

const VARIANT: Record<TaskStatus, Parameters<typeof Badge>[0]["variant"]> = {
  queued: "neutral",
  running: "primary",
  ok: "success",
  error: "destructive",
  cancelled: "warning",
};

const LABEL: Record<TaskStatus, string> = {
  queued: "Queued",
  running: "Running",
  ok: "Done",
  error: "Error",
  cancelled: "Cancelled",
};

interface Props {
  status: TaskStatus | "connecting" | "closed";
}

export function StatusPill({ status }: Props) {
  if (status === "connecting") {
    return <Badge variant="outline">Connecting…</Badge>;
  }
  if (status === "closed") {
    return <Badge variant="neutral">Closed</Badge>;
  }
  return <Badge variant={VARIANT[status]}>{LABEL[status]}</Badge>;
}
