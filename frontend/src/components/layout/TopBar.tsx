import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Languages, LogIn, LogOut, Menu, Monitor, Moon, Sun, User as UserIcon } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";

import { Button } from "@/components/ui/Button";
import { LANGUAGE_LABELS, SUPPORTED_LANGUAGES, type SupportedLanguage } from "@/i18n";
import { authApi, clearToken } from "@/lib/auth";
import { cn } from "@/lib/cn";
import { fetchBackendVersion } from "@/lib/version";
import { useAuthStore } from "@/stores/authStore";
import { useUiStore, type ThemeMode } from "@/stores/uiStore";

import { VersionBadge } from "./VersionBadge";

const THEMES: ReadonlyArray<{ value: ThemeMode; icon: typeof Sun; labelKey: string }> = [
  { value: "light", icon: Sun, labelKey: "theme.light" },
  { value: "dark", icon: Moon, labelKey: "theme.dark" },
  { value: "system", icon: Monitor, labelKey: "theme.system" },
];

export function TopBar() {
  const { t } = useTranslation();
  const { theme, setTheme, language, setLanguage, toggleSidebar } = useUiStore();
  const config = useAuthStore((s) => s.config);
  const user = useAuthStore((s) => s.user);
  const setUser = useAuthStore((s) => s.setUser);
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data } = useQuery({
    queryKey: ["version"],
    queryFn: fetchBackendVersion,
    staleTime: 5 * 60_000,
  });

  async function onLogout(): Promise<void> {
    await authApi.logout();
    clearToken();
    setUser(null);
    qc.clear();
    navigate("/login", { replace: true });
  }

  return (
    <header className="flex h-14 items-center justify-between border-b bg-[var(--color-card)]/30 px-4 backdrop-blur">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={toggleSidebar} aria-label={t("nav.toggleSidebar")}>
          <Menu className="h-4 w-4" />
        </Button>
        <div className="flex items-center gap-2 text-sm text-[var(--color-muted-foreground)]">
          {data ? (
            <>
              <span className="font-medium text-[var(--color-foreground)]">
                {t("app.shortName")} {t("app.version", { version: data.version })}
              </span>
              {/* P12.2 — running-process identity. Hovers reveal full SHA + */}
              {/* commit subject so users can pin down exactly which build  */}
              {/* the running backend is on, without shell access.          */}
              <VersionBadge build={data.build} />
              <span className="text-[var(--color-border)]">·</span>
              <span>
                {t("app.llmLabel")}: {data.llm_provider ?? t("app.unknown")}
              </span>
            </>
          ) : (
            <span>{t("app.connecting")}</span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-3">
        {/* Language switcher */}
        <div
          className="flex items-center gap-1 rounded-md border bg-[var(--color-card)] p-0.5"
          role="group"
          aria-label={t("language.switch")}
        >
          <Languages className="ml-1 h-3.5 w-3.5 text-[var(--color-muted-foreground)]" aria-hidden />
          {SUPPORTED_LANGUAGES.map((lng) => (
            <button
              key={lng}
              type="button"
              onClick={() => setLanguage(lng as SupportedLanguage)}
              aria-pressed={language === lng}
              title={LANGUAGE_LABELS[lng].native}
              className={cn(
                "flex h-7 min-w-[1.75rem] items-center justify-center rounded px-1.5 text-xs font-medium transition-colors",
                language === lng
                  ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                  : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]/60",
              )}
            >
              {LANGUAGE_LABELS[lng].flag}
            </button>
          ))}
        </div>

        {/* Theme switcher */}
        <div
          className="flex items-center gap-1 rounded-md border bg-[var(--color-card)] p-0.5"
          role="group"
          aria-label={t("theme.label")}
        >
          {THEMES.map(({ value, icon: Icon, labelKey }) => (
            <button
              key={value}
              type="button"
              onClick={() => setTheme(value)}
              aria-label={t(labelKey)}
              aria-pressed={theme === value}
              className={cn(
                "flex h-7 w-7 items-center justify-center rounded text-[var(--color-muted-foreground)] transition-colors",
                theme === value
                  ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                  : "hover:bg-[var(--color-accent)]/60",
              )}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden />
            </button>
          ))}
        </div>

        {config?.enabled ? (
          user ? (
            <div className="flex items-center gap-2">
              <span
                className="hidden items-center gap-1.5 rounded-md border border-[var(--color-border)] px-2 py-1 text-xs text-[var(--color-muted-foreground)] sm:inline-flex"
                title={user.email}
              >
                <UserIcon className="h-3.5 w-3.5" />
                {user.display_name}
                {user.role === "admin" ? (
                  <span className="ml-1 rounded bg-[var(--color-accent)] px-1 text-[10px] uppercase text-[var(--color-accent-foreground)]">
                    {t("auth.adminBadge")}
                  </span>
                ) : null}
              </span>
              <Button
                variant="ghost"
                size="sm"
                onClick={onLogout}
                aria-label={t("auth.signOutTooltip")}
                title={t("auth.signOutTooltip")}
              >
                <LogOut className="h-4 w-4" />
              </Button>
            </div>
          ) : (
            <Button variant="outline" size="sm" onClick={() => navigate("/login")}>
              <LogIn className="h-3.5 w-3.5" />
              {t("auth.signIn")}
            </Button>
          )
        ) : null}
      </div>
    </header>
  );
}
