/**
 * Bootstraps auth on app start:
 *
 * 1. Wires `lib/api.ts`'s token getter to `lib/auth.ts` (synchronous —
 *    every API call now sees the latest token).
 * 2. Probes `/api/auth/config`; if auth is disabled, marks the store
 *    as ready and returns. If enabled and a token is present, calls
 *    `/api/auth/me` and clears the token on 401.
 * 3. Listens for `aaf:auth:expired` events fired by `lib/api.ts` and
 *    drops the token + redirects to /login.
 *
 * The provider just renders its children — there is no UI here. Route
 * guards (`<RequireAuth>` in `routes/index.tsx`) decide what to show.
 */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";

import { AUTH_EXPIRED_EVENT, ApiError, setAuthTokenGetter } from "@/lib/api";
import { authApi, clearToken, getToken } from "@/lib/auth";
import { useAuthStore } from "@/stores/authStore";

setAuthTokenGetter(getToken);

export function AuthProvider({ children }: { children: ReactNode }) {
  const setConfig = useAuthStore((s) => s.setConfig);
  const setUser = useAuthStore((s) => s.setUser);
  const setStatus = useAuthStore((s) => s.setStatus);
  const navigate = useNavigate();
  const qc = useQueryClient();

  useEffect(() => {
    // No `bootstrapped` ref guard: in React 18+ StrictMode, the dev-only
    // double-mount fires the cleanup of the first effect immediately, which
    // would flip `cancelled` to true before the async resolves and leave the
    // store stuck at status="loading". Rely purely on the `cancelled` flag
    // for idempotency; the second effect run starts its own probe whose
    // setters do land. Two GETs to `/api/auth/config` in dev is harmless.
    let cancelled = false;

    (async () => {
      // eslint-disable-next-line no-console
      console.info("[AuthProvider] bootstrap.start");
      setStatus("loading");
      try {
        const config = await authApi.config();
        // eslint-disable-next-line no-console
        console.info("[AuthProvider] bootstrap.config", { cancelled, config });
        if (cancelled) return;
        setConfig(config);

        if (!config.enabled) {
          setUser(null);
          setStatus("ready");
          // eslint-disable-next-line no-console
          console.info("[AuthProvider] bootstrap.ready (auth-disabled)");
          return;
        }

        const token = getToken();
        if (!token) {
          setUser(null);
          setStatus("ready");
          return;
        }

        try {
          const me = await authApi.me();
          if (cancelled) return;
          setUser(me);
        } catch (err) {
          if (err instanceof ApiError && err.status === 401) {
            clearToken();
            setUser(null);
          } else {
            throw err;
          }
        }
        if (cancelled) return;
        setStatus("ready");
        // eslint-disable-next-line no-console
        console.info("[AuthProvider] bootstrap.ready (auth-enabled)");
      } catch (err) {
        if (cancelled) return;
        // eslint-disable-next-line no-console
        console.error("[AuthProvider] bootstrap failed", err);
        setStatus("error");
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [setConfig, setStatus, setUser]);

  useEffect(() => {
    function onExpired(): void {
      if (!getToken()) return;
      clearToken();
      setUser(null);
      qc.clear();
      toast.error("Session expired — please sign in again");
      navigate("/login", { replace: true });
    }
    window.addEventListener(AUTH_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(AUTH_EXPIRED_EVENT, onExpired);
  }, [navigate, qc, setUser]);

  return <>{children}</>;
}
