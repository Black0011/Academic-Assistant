import { QueryClient } from "@tanstack/react-query";

/** Global query client.
 *  - Stale 30s by default; lists / dashboards refetch when the tab regains
 *    focus, but not on every mount.
 *  - We share retries with the API layer (1 retry on 5xx-ish failures).
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: (failureCount, error) => {
        const status = (error as { status?: number } | undefined)?.status ?? 0;
        if (status >= 400 && status < 500) return false;
        return failureCount < 1;
      },
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: false,
    },
  },
});
