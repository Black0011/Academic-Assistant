/**
 * Auth helpers — single source of truth for the JWT in the browser.
 *
 * The token lives in localStorage under `aaf.token`. We deliberately keep
 * this module side-effect-free except for the `subscribers` pub/sub the
 * `lib/api.ts` interceptor uses to re-fetch the header on every request.
 */

import { api } from "./api";
import type { AuthConfig, LoginInput, PublicUser, TokenResponse } from "@/types/api";

const STORAGE_KEY = "aaf.token";

let cachedToken: string | null = readToken();
const subs = new Set<(token: string | null) => void>();

function readToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return cachedToken;
}

export function setToken(token: string | null): void {
  cachedToken = token;
  if (typeof window !== "undefined") {
    try {
      if (token) window.localStorage.setItem(STORAGE_KEY, token);
      else window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      // localStorage may be denied in some embeds; in-memory token still works.
    }
  }
  for (const cb of subs) cb(token);
}

export function clearToken(): void {
  setToken(null);
}

export function onTokenChange(cb: (token: string | null) => void): () => void {
  subs.add(cb);
  return () => subs.delete(cb);
}

// Cross-tab sync: if another tab logs in/out, mirror it here.
if (typeof window !== "undefined") {
  window.addEventListener("storage", (e) => {
    if (e.key !== STORAGE_KEY) return;
    cachedToken = e.newValue;
    for (const cb of subs) cb(cachedToken);
  });
}

// ---------------------------------------------------------------------------
// API surface
// ---------------------------------------------------------------------------

export const authApi = {
  config: () => api<AuthConfig>("/api/auth/config", { timeoutMs: 10_000 }),
  me: () => api<PublicUser>("/api/auth/me", { timeoutMs: 10_000 }),
  login: (body: LoginInput) =>
    api<TokenResponse>("/api/auth/login", {
      method: "POST",
      json: body,
      timeoutMs: 15_000,
    }),
  logout: () =>
    api<void>("/api/auth/logout", {
      method: "POST",
      timeoutMs: 10_000,
      throwOnError: false,
    }),
};
