/**
 * Editable form for the active default LLM provider.
 *
 * The form stays self-contained: it owns the *draft* state (so editing
 * doesn't reach React Query / `state.llm` until the user clicks Save or
 * Test) and reports back through `onSaved` / `onTested` so callers can
 * close drawers / show toasts.
 *
 * Hard rules (mirrored on the server):
 *   * `api_key === ""` means "keep stored key" iff the provider isn't
 *     changing. Switching providers requires a fresh key (or pick a
 *     keyless provider — `mock` / `ollama`).
 *   * `mock` and `ollama` allow Save without a key.
 *   * Test runs `POST /api/settings/llm:test` with the *draft* — never
 *     persists, never hot-reloads. Useful before committing a real key.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eraser, KeyRound, Loader2, PlugZap, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { ApiError } from "@/lib/api";
import { settingsApi } from "@/lib/settings";
import type {
  LLMProviderInput,
  LLMProviderName,
  LLMProviderResponse,
} from "@/types/api";

const KEYLESS_PROVIDERS: ReadonlyArray<LLMProviderName> = ["mock", "ollama"];

interface DraftState {
  provider: LLMProviderName;
  apiKey: string;
  baseUrl: string;
  defaultModel: string;
  timeoutS: number;
}

function draftFromResponse(r: LLMProviderResponse): DraftState {
  return {
    provider: r.provider,
    apiKey: "", // never round-trip the masked value as a real value
    baseUrl: r.base_url,
    defaultModel: r.default_model,
    timeoutS: r.timeout_s,
  };
}

function inputFromDraft(draft: DraftState): LLMProviderInput {
  const payload: LLMProviderInput = {
    provider: draft.provider,
    api_key: draft.apiKey,
    base_url: draft.baseUrl,
    default_model: draft.defaultModel,
    timeout_s: draft.timeoutS,
  };
  return payload;
}

export interface LLMProviderFormProps {
  /** Renders an extra "Reset to environment" button when true. */
  showClear?: boolean;
  /** Called after a successful PUT (after onSettled in the mutation). */
  onSaved?: (saved: LLMProviderResponse) => void;
}

export function LLMProviderForm({ showClear = true, onSaved }: LLMProviderFormProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();

  const currentQ = useQuery({
    queryKey: ["settings", "llm"],
    queryFn: () => settingsApi.getLLM(),
    staleTime: 30_000,
  });
  const providersQ = useQuery({
    queryKey: ["settings", "llm", "providers"],
    queryFn: () => settingsApi.providers(),
    staleTime: 5 * 60_000,
  });

  const [draft, setDraft] = useState<DraftState>({
    provider: "mock",
    apiKey: "",
    baseUrl: "",
    defaultModel: "",
    timeoutS: 120,
  });

  // Re-sync draft when the server view first loads or after a hot-reload.
  useEffect(() => {
    if (currentQ.data) {
      setDraft(draftFromResponse(currentQ.data));
    }
  }, [currentQ.data]);

  const isProviderUnchanged =
    currentQ.data?.provider === draft.provider;
  const keylessProvider = KEYLESS_PROVIDERS.includes(draft.provider);
  const willKeepStoredKey =
    isProviderUnchanged && !draft.apiKey && (currentQ.data?.api_key_set ?? false);

  const saveMut = useMutation({
    mutationFn: () => settingsApi.putLLM(inputFromDraft(draft)),
    onSuccess: (saved) => {
      toast.success(t("settings.llm.saved"));
      void qc.invalidateQueries({ queryKey: ["settings", "llm"] });
      // Other consumers (TopBar version label) need to refresh too.
      void qc.invalidateQueries({ queryKey: ["version"] });
      setDraft(draftFromResponse(saved));
      onSaved?.(saved);
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      toast.error(t("errors.saveFailed"), { description: msg });
    },
  });

  const testMut = useMutation({
    mutationFn: () => settingsApi.testLLM(inputFromDraft(draft)),
    onSuccess: (res) => {
      if (res.ok) {
        toast.success(t("settings.llm.testOk", { ms: res.latency_ms }));
      } else {
        toast.error(t("settings.llm.testFailed", { error: res.error ?? "unknown" }));
      }
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      toast.error(t("settings.llm.testFailed", { error: msg }));
    },
  });

  const clearMut = useMutation({
    mutationFn: () => settingsApi.deleteLLM(),
    onSuccess: () => {
      toast.success(t("settings.llm.cleared"));
      void qc.invalidateQueries({ queryKey: ["settings", "llm"] });
      void qc.invalidateQueries({ queryKey: ["version"] });
    },
    onError: (err) => {
      const msg = err instanceof ApiError ? err.message : (err as Error).message;
      toast.error(t("errors.saveFailed"), { description: msg });
    },
  });

  const providerOptions = useMemo<LLMProviderName[]>(
    () => providersQ.data?.items ?? ["openai", "anthropic", "ollama", "mock"],
    [providersQ.data],
  );

  const canSave =
    !saveMut.isPending && (keylessProvider || draft.apiKey.length > 0 || willKeepStoredKey);

  return (
    <div className="space-y-5">
      {currentQ.data?.warns_arq_worker && (
        <div className="rounded-md border border-yellow-500/40 bg-yellow-500/10 p-3 text-xs text-yellow-700 dark:text-yellow-300">
          {t("settings.llm.arqWarning")}
        </div>
      )}

      <div className="rounded-md border bg-[var(--color-background)] p-3 text-xs text-[var(--color-muted-foreground)]">
        <span className="font-medium text-[var(--color-foreground)]">
          {t("settings.llm.currentSource")}:{" "}
        </span>
        {currentQ.data?.source === "runtime"
          ? t("settings.llm.sourceRuntime")
          : t("settings.llm.sourceEnv")}
      </div>

      {/* Provider */}
      <div className="space-y-1.5">
        <Label htmlFor="llm-provider">{t("settings.llm.provider")}</Label>
        <select
          id="llm-provider"
          className="flex h-9 w-full rounded-md border border-[var(--color-input)] bg-[var(--color-background)] px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--color-ring)]"
          value={draft.provider}
          onChange={(e) =>
            setDraft((s) => ({
              ...s,
              provider: e.target.value as LLMProviderName,
              apiKey: "", // switching provider always requires fresh credentials
            }))
          }
        >
          {providerOptions.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          {t(`settings.llm.providerHint.${draft.provider}`)}
        </p>
      </div>

      {/* API key */}
      <div className="space-y-1.5">
        <Label htmlFor="llm-api-key" className="flex items-center gap-1.5">
          <KeyRound className="h-3.5 w-3.5" /> {t("settings.llm.apiKey")}
          {keylessProvider ? (
            <span className="rounded bg-[var(--color-muted)] px-1 text-[10px] text-[var(--color-muted-foreground)]">
              {t("common.optional")}
            </span>
          ) : null}
        </Label>
        <Input
          id="llm-api-key"
          type="password"
          autoComplete="off"
          value={draft.apiKey}
          onChange={(e) => setDraft((s) => ({ ...s, apiKey: e.target.value }))}
          placeholder={
            willKeepStoredKey
              ? `${currentQ.data?.api_key_masked} — ${t("settings.llm.apiKeyKept")}`
              : t("settings.llm.apiKeyPlaceholder")
          }
        />
      </div>

      {/* Base URL + default model */}
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="llm-base-url">{t("settings.llm.baseUrl")}</Label>
          <Input
            id="llm-base-url"
            value={draft.baseUrl}
            onChange={(e) => setDraft((s) => ({ ...s, baseUrl: e.target.value }))}
            placeholder={t("settings.llm.baseUrlPlaceholder")}
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="llm-default-model">{t("settings.llm.defaultModel")}</Label>
          <Input
            id="llm-default-model"
            value={draft.defaultModel}
            onChange={(e) => setDraft((s) => ({ ...s, defaultModel: e.target.value }))}
            placeholder={t("settings.llm.defaultModelPlaceholder")}
          />
        </div>
      </div>

      {/* Timeout */}
      <div className="space-y-1.5">
        <Label htmlFor="llm-timeout">{t("settings.llm.timeout")}</Label>
        <Input
          id="llm-timeout"
          type="number"
          min={1}
          max={600}
          value={draft.timeoutS}
          onChange={(e) =>
            setDraft((s) => ({ ...s, timeoutS: Math.max(1, Number(e.target.value) || 120) }))
          }
        />
      </div>

      <div className="flex flex-wrap items-center gap-2 pt-2">
        <Button onClick={() => saveMut.mutate()} disabled={!canSave}>
          {saveMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Save className="h-4 w-4" />
          )}
          {t("settings.llm.save")}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => testMut.mutate()}
          disabled={testMut.isPending || (!keylessProvider && !draft.apiKey && !willKeepStoredKey)}
        >
          {testMut.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <PlugZap className="h-4 w-4" />
          )}
          {t("settings.llm.test")}
        </Button>
        {showClear && currentQ.data?.source === "runtime" && (
          <Button
            type="button"
            variant="ghost"
            onClick={() => {
              if (window.confirm(t("settings.llm.clearConfirm"))) clearMut.mutate();
            }}
            disabled={clearMut.isPending}
            className="ml-auto text-[var(--color-muted-foreground)]"
          >
            <Eraser className="h-4 w-4" />
            {t("settings.llm.clear")}
          </Button>
        )}
      </div>
    </div>
  );
}
