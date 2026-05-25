/**
 * Thin fetch wrapper for the AAF backend. We deliberately stay close to
 * `fetch` so the SSE clients (`@microsoft/fetch-event-source`) and the
 * regular JSON callers share the same auth/error story.
 *
 * Auth: when a JWT is present (see `lib/auth.ts`), it's injected as a
 * `Authorization: Bearer …` header on every request. A 401 fires an
 * `aaf:auth:expired` event so the AuthProvider can clear local state and
 * redirect to /login. Importantly, this module DOES NOT import from
 * `lib/auth.ts` — it would create a cycle. Instead `lib/auth.ts` reads
 * tokens via the simple getter callback below.
 */

export const API_BASE: string = (import.meta.env.VITE_API_BASE ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

let getAuthToken: () => string | null = () => null;
/** Wired at app boot from `lib/auth.ts`. */
export function setAuthTokenGetter(fn: () => string | null): void {
  getAuthToken = fn;
}

/** Fired when any request hits 401 with an Authorization header attached. */
export const AUTH_EXPIRED_EVENT = "aaf:auth:expired";

export interface ApiOptions extends Omit<RequestInit, "body"> {
  /** Plain object — JSON.stringify'd automatically. Skip for `GET`. */
  json?: unknown;
  /** Pre-serialised body (FormData, Blob, string). Wins over `json`. */
  body?: BodyInit | null;
  /** Auto-throw on non-2xx (default `true`). */
  throwOnError?: boolean;
  /** Aborts the request after N ms. */
  timeoutMs?: number;
}

export function apiUrl(path: string): string {
  if (path.startsWith("http://") || path.startsWith("https://")) return path;
  const clean = path.startsWith("/") ? path : `/${path}`;
  return `${API_BASE}${clean}`;
}

export async function api<T>(path: string, opts: ApiOptions = {}): Promise<T> {
  const { json, body, throwOnError = true, timeoutMs, headers, ...rest } = opts;

  const controller = new AbortController();
  const composedSignal = mergeSignals(controller.signal, rest.signal);
  const timer = timeoutMs ? setTimeout(() => controller.abort("timeout"), timeoutMs) : null;

  const finalHeaders = new Headers(headers);
  if (json !== undefined && !finalHeaders.has("content-type")) {
    finalHeaders.set("content-type", "application/json");
  }
  if (!finalHeaders.has("accept")) {
    finalHeaders.set("accept", "application/json");
  }

  const token = getAuthToken();
  if (token && !finalHeaders.has("authorization")) {
    finalHeaders.set("authorization", `Bearer ${token}`);
  }

  let response: Response;
  try {
    response = await fetch(apiUrl(path), {
      ...rest,
      signal: composedSignal,
      headers: finalHeaders,
      body: body ?? (json !== undefined ? JSON.stringify(json) : null),
    });
  } finally {
    if (timer) clearTimeout(timer);
  }

  const contentType = response.headers.get("content-type") ?? "";
  const isJson = contentType.includes("application/json");
  const parsed: unknown = isJson
    ? await response.json().catch(() => null)
    : await response.text().catch(() => "");

  if (response.status === 401 && token && typeof window !== "undefined") {
    // Notify the AuthProvider so it can clear state + redirect. Throwing
    // is still fine — callers usually catch ApiError and surface a toast.
    window.dispatchEvent(new CustomEvent(AUTH_EXPIRED_EVENT));
  }

  if (!response.ok && throwOnError) {
    let message = `${response.status} ${response.statusText}`;
    if (isJson && parsed && typeof parsed === "object" && "detail" in parsed) {
      const detail = (parsed as { detail: unknown }).detail;
      if (typeof detail === "string") {
        message = detail;
      } else if (Array.isArray(detail)) {
        message = detail.map((d: { msg?: string }) => d.msg || JSON.stringify(d)).join("; ");
      } else if (detail) {
        message = JSON.stringify(detail);
      }
    }
    throw new ApiError(response.status, message, parsed);
  }

  return parsed as T;
}

/** Tiny helper used by SSE callers that need the raw URL. */
export function streamUrl(path: string): string {
  return apiUrl(path);
}

function mergeSignals(a: AbortSignal, b?: AbortSignal | null): AbortSignal {
  if (!b) return a;
  if (a.aborted) return a;
  if (b.aborted) return b;
  const ctrl = new AbortController();
  const onAbort = (): void => ctrl.abort();
  a.addEventListener("abort", onAbort, { once: true });
  b.addEventListener("abort", onAbort, { once: true });
  return ctrl.signal;
}
