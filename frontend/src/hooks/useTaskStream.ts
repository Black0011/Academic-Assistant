import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useEffect, useRef, useState } from "react";

import { streamUrl } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { StreamEvent, TaskStatus } from "@/types/api";

/**
 * Subscribe to `/api/tasks/:id/stream` (SSE).
 *
 * We use `fetchEventSource` instead of native `EventSource` so we can:
 *   - send Authorization headers (when JWT lands in M5)
 *   - skip retries cleanly on terminal events
 *   - share the same fetch transport as the rest of the app
 *
 * The hook is intentionally minimal: it returns the raw event stream and
 * a derived "stage" view; consumers can group / filter however they like.
 */
export interface TaskStreamState {
  events: StreamEvent[];
  status: TaskStatus | "connecting" | "closed";
  error: string | null;
}

export function useTaskStream(taskId: string | null): TaskStreamState {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<TaskStreamState["status"]>("connecting");
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!taskId) return;
    setEvents([]);
    setStatus("connecting");
    setError(null);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const token = getToken();
    void fetchEventSource(streamUrl(`/api/tasks/${taskId}/stream`), {
      signal: ctrl.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      // The backend never closes for clients on a healthy stream until the
      // task hits a terminal state, so we explicitly disable the lib's
      // auto-reconnect: it would otherwise spam the server post-completion.
      openWhenHidden: true,
      onopen: async (response) => {
        if (response.ok && response.headers.get("content-type")?.includes("text/event-stream")) {
          setStatus("running");
          return;
        }
        setStatus("closed");
        setError(`stream open failed: ${response.status} ${response.statusText}`);
        throw new Error("non-2xx");
      },
      onmessage: (msg) => {
        if (!msg.data) return;
        try {
          const payload = JSON.parse(msg.data) as Omit<StreamEvent, "type">;
          const event: StreamEvent = {
            type: msg.event || "message",
            task_id: payload.task_id ?? taskId,
            at: payload.at ?? new Date().toISOString(),
            data: payload.data ?? {},
          };
          setEvents((prev) => [...prev, event]);
          if (event.type === "task.end") {
            const verdict = (event.data.verdict ?? event.data.status) as TaskStatus | undefined;
            setStatus(verdict ?? "ok");
            ctrl.abort();
          } else if (event.type === "task.error") {
            setStatus("error");
            setError(typeof event.data.error === "string" ? event.data.error : "task failed");
            ctrl.abort();
          }
        } catch (err) {
          // SSE payloads from the backend are JSON-encoded; a parse failure
          // here is a contract bug, not user input. Log + keep streaming.
          console.warn("[useTaskStream] failed to parse event", err, msg);
        }
      },
      onerror: (err) => {
        setError(err instanceof Error ? err.message : String(err));
        setStatus("closed");
        // Throw to stop fetchEventSource's internal reconnect loop.
        throw err;
      },
      onclose: () => {
        setStatus((prev) => (prev === "running" ? "closed" : prev));
      },
    });

    return () => ctrl.abort();
  }, [taskId]);

  return { events, status, error };
}
