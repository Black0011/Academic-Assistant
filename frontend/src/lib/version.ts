/**
 * Thin client for `GET /api/version`. Used by the header VersionBadge
 * so users can see which commit the running backend is on — kills the
 * "did my fix actually deploy?" guessing game.
 *
 * The frontend itself doesn't need its own build identity yet (Vite
 * rebuilds emit a fresh JS bundle the user is forced to load); if that
 * changes we'd just add a second field here.
 */

import { api } from "@/lib/api";
import type { VersionInfo } from "@/types/api";

export async function fetchBackendVersion(): Promise<VersionInfo> {
  return api<VersionInfo>("/api/version");
}
