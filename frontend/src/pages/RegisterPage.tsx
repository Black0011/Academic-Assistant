/**
 * Sign-up page. Only mounted when the backend reports
 * `auth.allow_signup === true`. The first user that completes this form
 * on a fresh deployment becomes admin (server-side decision).
 */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ApiError, api } from "@/lib/api";
import { setToken } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";
import type { RegisterInput, TokenResponse } from "@/types/api";

export function RegisterPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const setUser = useAuthStore((s) => s.setUser);

  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");

  const mut = useMutation<TokenResponse, ApiError, RegisterInput>({
    mutationFn: (body) =>
      api<TokenResponse>("/api/auth/register", { method: "POST", json: body, timeoutMs: 15_000 }),
    onSuccess: (data) => {
      setToken(data.access_token);
      setUser(data.user);
      qc.invalidateQueries();
      toast.success(t("auth.welcomeBack", { name: data.user.display_name }));
      navigate("/", { replace: true });
    },
    onError: (err) => toast.error(err.message || t("auth.registrationFailed")),
  });

  function onSubmit(e: FormEvent<HTMLFormElement>): void {
    e.preventDefault();
    if (password.length < 8) {
      toast.warning(t("auth.credentialsRequired"));
      return;
    }
    mut.mutate({ email: email.trim(), password, display_name: displayName.trim() });
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-background)] px-4">
      <div className="w-full max-w-sm rounded-lg border border-[var(--color-border)] bg-[var(--color-card)] p-6 shadow-sm">
        <h1 className="text-xl font-semibold text-[var(--color-foreground)]">
          {t("auth.createAccount")}
        </h1>
        <p className="mt-1 text-sm text-[var(--color-muted-foreground)]">{t("app.name")}</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="block text-sm">
            <span className="text-[var(--color-muted-foreground)]">{t("auth.email")}</span>
            <Input
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1"
              placeholder={t("auth.emailPlaceholder")}
            />
          </label>
          <label className="block text-sm">
            <span className="text-[var(--color-muted-foreground)]">
              {t("auth.displayName")} ({t("common.optional")})
            </span>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="mt-1"
              placeholder={t("auth.displayNamePlaceholder")}
            />
          </label>
          <label className="block text-sm">
            <span className="text-[var(--color-muted-foreground)]">{t("auth.password")}</span>
            <Input
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1"
              placeholder={t("auth.passwordPlaceholder")}
            />
          </label>

          <Button type="submit" className="w-full" disabled={mut.isPending}>
            {mut.isPending ? t("auth.creating") : t("auth.createAccount")}
          </Button>
        </form>
      </div>
    </div>
  );
}
