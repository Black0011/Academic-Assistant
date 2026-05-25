/**
 * Auth Zustand store.
 *
 * Holds the current user + the public auth feature flags. The token itself
 * lives in `lib/auth.ts` (localStorage); we don't put it here because
 * Zustand's `persist` would shadow that storage and complicate cross-tab
 * sync.
 */

import { create } from "zustand";

import type { AuthConfig, PublicUser } from "@/types/api";

interface AuthState {
  /** `null` until /api/auth/config has been queried at least once. */
  config: AuthConfig | null;
  /** Current authenticated user, or `null` for anonymous / logged-out. */
  user: PublicUser | null;
  /** Tracks the bootstrap probe so route guards can wait. */
  status: "idle" | "loading" | "ready" | "error";
  setConfig: (cfg: AuthConfig | null) => void;
  setUser: (user: PublicUser | null) => void;
  setStatus: (status: AuthState["status"]) => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  config: null,
  user: null,
  status: "idle",
  setConfig: (config) => set({ config }),
  setUser: (user) => set({ user }),
  setStatus: (status) => set({ status }),
}));
