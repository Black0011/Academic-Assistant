/**
 * Runtime settings client.
 *
 * Mirrors `backend/api/routers/settings.py` (Phase A). The single resource
 * we currently expose is the default LLM provider. Hot-reload semantics
 * live on the backend — every PUT here triggers a swap of `state.llm`
 * and `runner_deps.llm`.
 */
import { api } from "@/lib/api";
import type {
  LLMProviderInput,
  LLMProviderResponse,
  LLMTestResponse,
  ProvidersResponse,
} from "@/types/api";

export const settingsApi = {
  getLLM(): Promise<LLMProviderResponse> {
    return api<LLMProviderResponse>("/api/settings/llm");
  },
  putLLM(input: LLMProviderInput): Promise<LLMProviderResponse> {
    return api<LLMProviderResponse>("/api/settings/llm", { method: "PUT", json: input });
  },
  deleteLLM(): Promise<void> {
    return api<void>("/api/settings/llm", { method: "DELETE" });
  },
  testLLM(input: LLMProviderInput): Promise<LLMTestResponse> {
    return api<LLMTestResponse>("/api/settings/llm:test", {
      method: "POST",
      json: input,
      timeoutMs: 30_000,
    });
  },
  providers(): Promise<ProvidersResponse> {
    return api<ProvidersResponse>("/api/settings/llm/providers");
  },
};
