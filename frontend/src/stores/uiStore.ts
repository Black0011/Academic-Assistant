import { create } from "zustand";
import { persist } from "zustand/middleware";

import { SUPPORTED_LANGUAGES, type SupportedLanguage } from "@/i18n";

export type ThemeMode = "light" | "dark" | "system";

interface UiState {
  theme: ThemeMode;
  language: SupportedLanguage;
  sidebarCollapsed: boolean;
  setTheme: (theme: ThemeMode) => void;
  setLanguage: (lang: SupportedLanguage) => void;
  toggleSidebar: () => void;
}

function detectInitialLanguage(): SupportedLanguage {
  if (typeof navigator === "undefined") return "en";
  const nav = (navigator.language ?? "en").toLowerCase();
  return nav.startsWith("zh") ? "zh" : "en";
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      language: detectInitialLanguage(),
      sidebarCollapsed: false,
      setTheme: (theme) => set({ theme }),
      setLanguage: (language) => {
        if (!SUPPORTED_LANGUAGES.includes(language)) return;
        set({ language });
      },
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
    }),
    { name: "aaf.ui" },
  ),
);

/** Apply theme to <html> based on store + system preference. Idempotent. */
export function applyTheme(mode: ThemeMode): void {
  const root = document.documentElement;
  const prefersDark =
    typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches;
  const isDark = mode === "dark" || (mode === "system" && prefersDark);
  root.classList.toggle("dark", isDark);
  root.style.colorScheme = isDark ? "dark" : "light";
}
