/**
 * Route guard. Behaviour matrix:
 *
 *   auth.config.enabled = false  →  always render children (open mode)
 *   auth.config = null           →  show a thin "loading" skeleton while
 *                                   AuthProvider boots
 *   user = null                  →  redirect to /login, remembering the
 *                                   attempted path so post-login can return
 *   user != null                 →  render children
 */

import { Navigate, Outlet, useLocation } from "react-router-dom";

import { useAuthStore } from "@/stores/authStore";

export function RequireAuth() {
  const { config, user, status } = useAuthStore();
  const location = useLocation();

  if (status === "idle" || status === "loading" || config === null) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--color-muted-foreground)]">
        Loading…
      </div>
    );
  }

  if (!config.enabled) return <Outlet />;
  if (!user) {
    return (
      <Navigate
        to="/login"
        replace
        state={{ from: location.pathname + location.search }}
      />
    );
  }
  return <Outlet />;
}
