---
name: aaf-frontend-react
description: >-
  React 19 + TypeScript + Zustand + TanStack Query + shadcn/ui conventions for
  AAF's frontend. Covers component structure, hooks, API wrapping, SSE
  handling, stores, routing, and theming. Load when editing anything under
  frontend/.
domain: engineering
triggers:
  - react
  - react 19
  - frontend
  - component
  - zustand
  - tanstack query
  - shadcn
  - tailwind
  - frontend/src
version: "1.0.0"
---

# AAF Frontend — React 19 Conventions

## 1. Tech stack (fixed)

- **React 19** with functional components + hooks
- **TypeScript** strict mode (`strict`, `noUncheckedIndexedAccess`, `exactOptionalPropertyTypes`)
- **Vite 5** for dev server + build
- **React Router 7** (data-router API)
- **Zustand 5** for UI-only local state
- **TanStack Query v5** for all server state + caching
- **Tailwind CSS v4** + **shadcn/ui** (components copied into `src/components/ui/`)
- **Monaco Editor** (`@monaco-editor/react`) for code / LaTeX, **Tiptap** (`@tiptap/react`) for WYSIWYG
- `markdown-it` + KaTeX for rendering; `echarts-for-react` for graphs
- `@microsoft/fetch-event-source` for SSE
- `react-hook-form` + `zod` for forms; `react-i18next` for i18n

**No Vue, no Vuex/Pinia, no CSS-in-JS, no Redux, no Options API.**

## 2. File layout (see PLAN §5)

```
frontend/src/
├── main.tsx               — React root + providers (Router, QueryClient, Theme)
├── App.tsx                — layout shell
├── routes/                — route tree (createBrowserRouter)
├── pages/                 — page-level components (one per route)
├── components/
│   ├── ui/                — shadcn/ui primitives (source code, editable)
│   ├── common/            — cross-feature wrappers
│   ├── research/
│   ├── writer/
│   ├── revision/
│   └── memory/
├── hooks/                 — custom hooks (useSSE, useTaskMonitor, …)
├── stores/                — Zustand stores
├── api/                   — typed HTTP clients + TanStack Query hooks
├── lib/                   — pure utilities (cn, formatters, guards)
├── types/                 — shared TS types (generated + hand-written)
└── styles/globals.css     — Tailwind entrypoint + CSS variables
```

## 3. Component template

```tsx
// src/components/research/PaperCard.tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

interface Props {
  paper: { id: string; title: string; tags: string[] }
  selected?: boolean
  onSelect?: (id: string) => void
}

export function PaperCard({ paper, selected = false, onSelect }: Props) {
  return (
    <Card
      className={cn('cursor-pointer transition-colors hover:bg-accent',
        selected && 'border-primary')}
      onClick={() => onSelect?.(paper.id)}
    >
      <CardHeader>
        <CardTitle className="text-base">{paper.title}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-wrap gap-1">
        {paper.tags.map(t => <Badge key={t} variant="outline">{t}</Badge>)}
      </CardContent>
    </Card>
  )
}
```

Rules:
- Functional component. Named export (no `default` outside of page-level components).
- Props interface declared adjacent; destructure with defaults in the signature.
- Styling via Tailwind utilities + shadcn primitives only. Compose classes via `cn(...)`.
- Never inline business logic — reach for a hook or query.

## 4. API layer

One file per backend router under `src/api/`:

```ts
// src/api/research.ts
import { client } from './client'
import type { ResearchRequest, TaskEnqueuedResponse } from '@/types/api'

export async function startResearch(req: ResearchRequest): Promise<TaskEnqueuedResponse> {
  const { data } = await client.post('/research', req)
  return data
}
```

`client.ts` holds a single `fetch` wrapper (or `axios`) with baseURL from `import.meta.env.VITE_API_BASE`.

TanStack Query hooks sit next to the raw calls:

```ts
// src/api/queries/research.ts
import { useMutation } from '@tanstack/react-query'
import { startResearch } from '@/api/research'

export function useStartResearch() {
  return useMutation({ mutationFn: startResearch })
}
```

Rules:
- Components never call `fetch` / `axios` directly. Always via api module + query hook.
- Types live in `src/types/api.ts`, generated from OpenAPI with `openapi-typescript` (wired in M3+).
- Query keys centralised in `src/api/queryKeys.ts` to avoid drift.

## 5. Zustand stores (UI state only)

```ts
// src/stores/useUIStore.ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'

interface UIState {
  theme: 'light' | 'dark'
  sidebarOpen: boolean
  toggleTheme: () => void
  setSidebar: (open: boolean) => void
}

export const useUIStore = create<UIState>()(
  persist(
    set => ({
      theme: 'light',
      sidebarOpen: true,
      toggleTheme: () => set(s => ({ theme: s.theme === 'light' ? 'dark' : 'light' })),
      setSidebar: open => set({ sidebarOpen: open }),
    }),
    { name: 'aaf-ui' },
  ),
)
```

Rules:
- **UI-only state** — never duplicate server data here.
- One store per feature area. Hook name = file name.
- Don't expose the raw `set` function; wrap actions.
- Persist sparingly (theme, sidebar, auth token). Never persist tasks / messages.

## 6. SSE: the canonical hook

```ts
// src/hooks/useSSE.ts
import { fetchEventSource } from '@microsoft/fetch-event-source'
import { useCallback, useEffect, useRef, useState } from 'react'

export interface TaskEvent { type: string; task_id: string; at: string; data: unknown }

export function useSSE(path: string, body?: unknown) {
  const [events, setEvents] = useState<TaskEvent[]>([])
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const start = useCallback(async () => {
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setEvents([]); setRunning(true); setError(null)
    try {
      await fetchEventSource(`${import.meta.env.VITE_API_BASE}${path}`, {
        method: body ? 'POST' : 'GET',
        headers: body ? { 'Content-Type': 'application/json' } : undefined,
        body: body ? JSON.stringify(body) : undefined,
        signal: ctrl.signal,
        onmessage: e => setEvents(prev => [...prev, JSON.parse(e.data)]),
        onerror: e => { setError(String(e)); throw e },
      })
    } finally {
      setRunning(false)
    }
  }, [path, body])

  const stop = useCallback(() => {
    abortRef.current?.abort()
    setRunning(false)
  }, [])

  useEffect(() => () => stop(), [stop])
  return { events, running, error, start, stop }
}
```

All SSE usage in the app must go through this hook. Never call `EventSource` or `fetchEventSource` from a component.

## 7. Routing (React Router 7)

```ts
// src/routes/index.ts
import { createBrowserRouter } from 'react-router-dom'

export const router = createBrowserRouter([
  {
    path: '/',
    Component: () => import('@/App').then(m => m.default),
    children: [
      { index: true,             lazy: () => import('@/pages/Dashboard') },
      { path: 'research',        lazy: () => import('@/pages/Research') },
      { path: 'writer/:id?',     lazy: () => import('@/pages/Writer') },
      { path: 'revision/:docId', lazy: () => import('@/pages/Revision') },
      { path: 'memory',          lazy: () => import('@/pages/Memory') },
      { path: 'settings',        lazy: () => import('@/pages/Settings') },
    ],
  },
])
```

Rules:
- Lazy-load every non-shell route.
- Loaders may prefetch via `queryClient.ensureQueryData` but must not hold business logic.
- Auth guards live in wrapper components; `react-router` v7 pattern.

## 8. Theming

- Tailwind v4 + shadcn tokens; dark mode toggled via `<html class="dark">`.
- Custom tokens in `src/styles/globals.css`:

```css
@import "tailwindcss";

@theme {
  --font-sans: ui-sans-serif, system-ui, ...;
  --radius: 0.5rem;
}

:root {
  --background: 0 0% 100%;
  --foreground: 240 10% 3.9%;
  --primary: 240 5.9% 10%;
  /* … shadcn tokens … */
}
.dark { /* overrides */ }
```

Never inline large `style` attributes; never introduce CSS files per component.

## 9. Naming

- **Components**: `PascalCase.tsx` (e.g. `PaperCard.tsx`).
- **Hooks**: `useCamelCase.ts` (e.g. `useTaskMonitor.ts`).
- **Stores**: `useCamelCaseStore.ts` (e.g. `useAuthStore.ts`).
- **Types**: `src/types/<domain>.ts` (`api.ts`, `paper.ts`, `task.ts`).
- **Query keys**: `['research', 'list']`, `['memory', 'snapshot', { query }]`.

## 10. Testing

- Unit: Vitest + `@testing-library/react` + `@testing-library/user-event`.
- One test file per component under `src/__tests__/`; wrap renders with a fresh `QueryClient`.
- Always mock `@/api/*`; never hit real backend in unit tests.
- E2E: Playwright (deferred to M6).

## 11. Checklist for a new component

- [ ] Functional component, named export (except page defaults)
- [ ] Props interface declared adjacent, no `any`
- [ ] Styling via Tailwind + shadcn; no custom CSS files
- [ ] Server state via TanStack Query, UI state via Zustand
- [ ] No `fetch` / `EventSource` calls; uses `@/api/*` + `useSSE`
- [ ] Keyboard accessible, semantic HTML, `alt` on every `<img>`

## 12. Don't

- Don't reach for `window.fetch`; use the API wrappers.
- Don't mix server state into Zustand; let TanStack Query cache.
- Don't use default exports outside page components.
- Don't import from `@/pages/*` inside `@/components/*` (circular by design).
- Don't write component-owned CSS files — use Tailwind.
- Don't introduce a new state library (Redux / Jotai / Recoil) without written justification.
