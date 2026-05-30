/**
 * First-run onboarding modal.
 *
 * Shown automatically the first time AppLayout mounts when the backend
 * reports `source === "env" && !api_key_set` (i.e. no real provider
 * configured anywhere). Reuses `LLMProviderForm` so there's exactly one
 * place that knows how to talk to /api/settings/llm.
 *
 * The modal can also be opened from the LLM Provider settings panel as
 * a "Re-run onboarding" affordance — see `Settings.tsx`.
 *
 * "Skip" sets a localStorage marker so we don't pester the user every
 * refresh; they can change it any time in Settings → LLM Provider.
 */
import { Sparkles, X } from "lucide-react";
import { type ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { LLMProviderForm } from "@/components/settings/LLMProviderForm";
import { Button } from "@/components/ui/Button";

const SKIP_MARKER = "aaf.onboarding.dismissed";

export function markOnboardingSeen(): void {
  try {
    window.localStorage.setItem(SKIP_MARKER, "1");
  } catch {
    /* private mode — silently ignore */
  }
}

export function isOnboardingSeen(): boolean {
  try {
    return window.localStorage.getItem(SKIP_MARKER) === "1";
  } catch {
    return false;
  }
}

interface OnboardingDialogProps {
  open: boolean;
  onClose: () => void;
  /** Optional banner above the form (e.g. info about ARQ). */
  topNote?: ReactNode;
}

export function OnboardingDialog({ open, onClose, topNote }: OnboardingDialogProps) {
  const { t } = useTranslation();
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="onboarding-title"
    >
      <div className="w-full max-w-lg rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-5 shadow-lg">
        <div className="mb-4 flex items-start justify-between gap-2">
          <div>
            <h2
              id="onboarding-title"
              className="flex items-center gap-2 text-lg font-semibold text-[var(--color-foreground)]"
            >
              <Sparkles className="h-4 w-4 text-[var(--color-primary)]" />
              {t("onboarding.title")}
            </h2>
            <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
              {t("onboarding.subtitle")}
            </p>
          </div>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => {
              markOnboardingSeen();
              onClose();
            }}
            aria-label={t("common.close")}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {topNote}

        <LLMProviderForm
          showClear={false}
          onSaved={() => {
            markOnboardingSeen();
            onClose();
          }}
        />

        <div className="mt-5 flex items-center justify-between border-t border-[var(--color-border)] pt-3 text-xs text-[var(--color-muted-foreground)]">
          <span>{t("onboarding.useMock")}</span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              markOnboardingSeen();
              onClose();
            }}
          >
            {t("common.skip")}
          </Button>
        </div>
      </div>
    </div>
  );
}
