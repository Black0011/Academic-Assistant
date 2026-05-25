import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Outlet } from "react-router-dom";
import { Toaster } from "sonner";

import {
  OnboardingDialog,
  isOnboardingSeen,
} from "@/components/settings/OnboardingDialog";
import { settingsApi } from "@/lib/settings";
import { applyTheme, useUiStore } from "@/stores/uiStore";

import { Sidebar } from "./Sidebar";
import { TopBar } from "./TopBar";

export function AppLayout() {
  const theme = useUiStore((s) => s.theme);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const handler = () => applyTheme("system");
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, [theme]);

  // First-run onboarding: only consult /api/settings/llm if the user
  // hasn't dismissed the modal before. The query is cached + reused by
  // the Settings panel, so this isn't an extra round-trip.
  const skipOnboardingProbe = isOnboardingSeen();
  const llm = useQuery({
    queryKey: ["settings", "llm"],
    queryFn: () => settingsApi.getLLM(),
    staleTime: 30_000,
    enabled: !skipOnboardingProbe,
  });

  const [forceClosed, setForceClosed] = useState(false);
  const onboardingOpen =
    !skipOnboardingProbe &&
    !forceClosed &&
    llm.data !== undefined &&
    llm.data.source === "env" &&
    !llm.data.api_key_set &&
    llm.data.provider === "mock";

  return (
    <div className="grid h-full grid-cols-[auto_1fr] grid-rows-[auto_1fr] bg-[var(--color-background)] text-[var(--color-foreground)]">
      <Sidebar className="row-span-2" />
      <TopBar />
      <main className="overflow-y-auto scrollbar-thin">
        <div className="mx-auto w-full max-w-6xl p-6">
          <Outlet />
        </div>
      </main>
      <Toaster
        position="top-right"
        richColors
        toastOptions={{
          classNames: {
            toast:
              "rounded-md border border-[var(--color-border)] bg-[var(--color-card)] text-[var(--color-card-foreground)]",
          },
        }}
      />
      <OnboardingDialog open={onboardingOpen} onClose={() => setForceClosed(true)} />
    </div>
  );
}
