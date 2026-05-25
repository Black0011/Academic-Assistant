/**
 * i18next bootstrap.
 *
 * Why a hand-rolled detector instead of `i18next-browser-languagedetector`'s
 * defaults: we already persist user choice through `useUiStore` (Zustand
 * + localStorage). Threading detection through a separate cookie/storage
 * key would let the two diverge — the language picked in the topbar
 * could disagree with what i18next loads on the next refresh. So we
 * read the persisted UI store first and only fall back to navigator
 * language for the very first visit.
 *
 * Hard rules:
 *
 *   * Single namespace, single resource bundle per language. Splitting
 *     namespaces would force lazy-loading + suspense boundaries and
 *     buys us nothing for a 14-page SPA.
 *   * No fallback to keys: missing English → blank string, missing
 *     Chinese → English fallback. Catches missing translations early
 *     in dev (you see "" instead of "research.console.title").
 *   * `react: { useSuspense: false }` — every t() call is synchronous,
 *     even on cold start, because resources are bundled at build time.
 */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";

import en from "./locales/en.json";
import zh from "./locales/zh.json";

export const SUPPORTED_LANGUAGES = ["en", "zh"] as const;
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number];

export const LANGUAGE_LABELS: Record<SupportedLanguage, { native: string; flag: string }> = {
  en: { native: "English", flag: "EN" },
  zh: { native: "中文", flag: "中" },
};

const STORAGE_KEY = "aaf.ui";

function readPersistedLanguage(): SupportedLanguage | null {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as { state?: { language?: string } };
    const candidate = parsed.state?.language;
    if (candidate && SUPPORTED_LANGUAGES.includes(candidate as SupportedLanguage)) {
      return candidate as SupportedLanguage;
    }
  } catch {
    // Corrupted storage → silent fallback. Don't block first paint.
  }
  return null;
}

function detectInitialLanguage(): SupportedLanguage {
  const persisted = readPersistedLanguage();
  if (persisted) return persisted;
  const nav =
    typeof navigator !== "undefined"
      ? (navigator.language ?? navigator.languages?.[0] ?? "en").toLowerCase()
      : "en";
  return nav.startsWith("zh") ? "zh" : "en";
}

void i18n.use(initReactI18next).init({
  resources: {
    en: { translation: en },
    zh: { translation: zh },
  },
  lng: detectInitialLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnEmptyString: false,
  react: { useSuspense: false },
});

export { i18n };
