/**
 * Planner DAG API client (M8.2).
 *
 * Mirrors `backend/api/routers/planner.py`:
 *
 *   GET    /api/planner/skills_for_compile
 *   POST   /api/planner/compile
 *   POST   /api/planner/validate
 *   POST   /api/planner/execute   -> { task_id, ... } (HTTP 202)
 *
 * Execution goes through the standard Tasks system (workflow="dag"), so
 * existing SSE consumers can subscribe to `/api/tasks/{task_id}/events`
 * to render node-level `task.stage_start` / `task.stage_end` events.
 */
import { api } from "@/lib/api";
import type {
  CompilePlanInput,
  ExecutePlanInput,
  ExecutePlanResponse,
  PlanDAG,
  SkillsForCompileResponse,
  ValidatePlanResponse,
} from "@/types/api";

export const plannerApi = {
  skillsForCompile(): Promise<SkillsForCompileResponse> {
    return api<SkillsForCompileResponse>("/api/planner/skills_for_compile");
  },

  compile(input: CompilePlanInput): Promise<PlanDAG> {
    return api<PlanDAG>("/api/planner/compile", {
      method: "POST",
      json: input,
    });
  },

  validate(plan: PlanDAG): Promise<ValidatePlanResponse> {
    return api<ValidatePlanResponse>("/api/planner/validate", {
      method: "POST",
      json: { plan },
    });
  },

  execute(input: ExecutePlanInput): Promise<ExecutePlanResponse> {
    return api<ExecutePlanResponse>("/api/planner/execute", {
      method: "POST",
      json: input,
    });
  },
};
