import { useMutation } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { CreateTaskResponse, RespondToTaskInput } from "@/types/api";

export function useRespondToTask(taskId: string) {
  return useMutation({
    mutationFn: (body: RespondToTaskInput) =>
      api<CreateTaskResponse>(`/api/tasks/${taskId}/respond`, {
        method: "POST",
        json: body,
      }),
  });
}
