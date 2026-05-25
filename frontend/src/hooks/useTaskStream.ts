import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useEffect, useRef, useState } from "react";

import { streamUrl } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type { AwaitingInputState, StreamEvent, TaskStatus } from "@/types/api";

export type TaskStreamStatus = TaskStatus | "connecting" | "closed";

export interface TaskStreamState {
  events: StreamEvent[];
  status: TaskStreamStatus;
  error: string | null;
  awaitingInput: AwaitingInputState | null;
}

export function useTaskStream(taskId: string | null): TaskStreamState {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const [status, setStatus] = useState<TaskStreamStatus>("connecting");
  const [error, setError] = useState<string | null>(null);
  const [awaitingInput, setAwaitingInput] = useState<AwaitingInputState | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!taskId) return;
    setEvents([]);
    setStatus("connecting");
    setError(null);
    setAwaitingInput(null);

    const ctrl = new AbortController();
    abortRef.current = ctrl;

    const token = getToken();
    void fetchEventSource(streamUrl(`/api/tasks/${taskId}/stream`), {
      signal: ctrl.signal,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
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

          if (event.type === "task.awaiting_input") {
            setStatus("waiting");
            setAwaitingInput({
              prompt: String(event.data.prompt ?? ""),
              checkpoint: String(event.data.checkpoint ?? ""),
              prompt_data: (event.data.prompt_data as Record<string, unknown>) ?? {},
              stage: String(event.data.stage ?? ""),
            });
          } else if (event.type === "task.resume") {
            setStatus("running");
            setAwaitingInput(null);
          } else if (event.type === "task.end") {
            const verdict = (event.data.verdict ?? event.data.status) as TaskStatus | undefined;
            setStatus(verdict ?? "ok");
            setAwaitingInput(null);
            ctrl.abort();
          } else if (event.type === "task.error") {
            setStatus("error");
            setError(typeof event.data.error === "string" ? event.data.error : "task failed");
            setAwaitingInput(null);
            ctrl.abort();
          }
        } catch (err) {
          console.warn("[useTaskStream] failed to parse event", err, msg);
        }
      },
      onerror: (err) => {
        setError(err instanceof Error ? err.message : String(err));
        setStatus("closed");
        throw err;
      },
      onclose: () => {
        setStatus((prev) => (prev === "running" || prev === "waiting" ? "closed" : prev));
      },
    });

    return () => ctrl.abort();
  }, [taskId]);

  return { events, status, error, awaitingInput };
}
