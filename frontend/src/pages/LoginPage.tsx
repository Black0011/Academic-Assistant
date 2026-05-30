/**
 * Sign-in page. Renders only when the backend reports `auth.enabled === true`.
 *
 * Flow:
 *   1. Submit (email, password) → POST /api/auth/login → token + user
 *   2. setToken / setUser → invalidate React Query caches → navigate to
 *      the "from" location (or `/`) so the user lands where they tried
 *      to go before being bounced to /login.
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { LogIn, UserPlus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, useLocation, useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError } from "@/lib/api";
import { authApi, setToken } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";
import type { TokenResponse } from "@/types/api";

interface LocationState {
  from?: string;
}

export function LoginPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const location = useLocation();
  const qc = useQueryClient();
  const config = useAuthStore((s) => s.config);
  const setUser = useAuthStore((s) => s.setUser);

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  const fromState = (location.state as LocationState | null) ?? null;
  const redirectTo = fromState?.from ?? "/";

  const loginMut = useMutation<TokenResponse, ApiError, void>({
    mutationFn: () => authApi.login({ email: email.trim(), password }),
    onSuccess: (data) => {
      setToken(data.access_token);
      setUser(data.user);
      qc.invalidateQueries();
      toast.success(t("auth.welcomeBack", { name: data.user.display_name }));
      navigate(redirectTo, { replace: true });
    },
    onError: (err) => {
      toast.error(err.message || t("auth.loginFailed"));
    },
  });

  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (!email.trim() || !password) {
      toast.warning(t("auth.credentialsRequired"));
      return;
    }
    loginMut.mutate();
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-background)] px-4">
      <div className="w-full max-w-sm rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-sm">
        <div className="mb-6">
          <h1 className="text-xl font-semibold text-[var(--color-foreground)]">
            {t("app.name")}
          </h1>
          <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">
            {t("auth.signInToContinue")}
          </p>
        </div>

        <form onSubmit={onSubmit} className="space-y-4">
          <label className="block text-sm">
            <span className="text-[var(--color-muted-foreground)]">{t("auth.email")}</span>
            <Input
              autoComplete="email"
              autoFocus
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1"
              placeholder={t("auth.emailPlaceholder")}
            />
          </label>
          <label className="block text-sm">
            <span className="text-[var(--color-muted-foreground)]">{t("auth.password")}</span>
            <Input
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1"
              placeholder={t("auth.passwordPlaceholder")}
            />
          </label>

          <Button type="submit" className="w-full" disabled={loginMut.isPending}>
            <LogIn className="h-4 w-4" />
            {loginMut.isPending ? t("auth.signingIn") : t("auth.signIn")}
          </Button>
        </form>

        {config?.allow_signup ? (
          <div className="mt-4 flex items-center justify-between border-t border-[var(--color-border)] pt-4 text-sm text-[var(--color-muted-foreground)]">
            <span>{t("auth.noAccount")}</span>
            <Link
              to="/register"
              className="inline-flex items-center gap-1 text-[var(--color-primary)] hover:underline"
            >
              <UserPlus className="h-3.5 w-3.5" />
              {t("auth.createOne")}
            </Link>
          </div>
        ) : null}
      </div>
    </div>
  );
}
