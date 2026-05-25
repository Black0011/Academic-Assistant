# AAF Frontend

React 19 + Vite + Tailwind v4 + TanStack Query MVP for the Academic Agent
Framework backend (`/api/*`).

## Quick start

```bash
cd frontend
npm install
npm run dev          # http://127.0.0.1:5173
```

`/api/*` is proxied to `http://127.0.0.1:8000` (the FastAPI backend) during
development. In production the bundle is served behind nginx and talks to
`/api/*` on the same origin.

## Scripts

| Script              | Purpose                                |
| ------------------- | -------------------------------------- |
| `npm run dev`       | Vite dev server with HMR + API proxy   |
| `npm run build`     | Type-check + production build to `dist`|
| `npm run typecheck` | `tsc -b --noEmit`                      |
| `npm run preview`   | Serve `dist/` locally                  |

## Routes

| Path                | Page             | Backend surface                    |
| ------------------- | ---------------- | ---------------------------------- |
| `/`                 | Dashboard        | `/api/version`, `/api/memory/stats`, `/api/tasks`, `/api/manuscripts/stats` |
| `/research`         | Research Console | `/api/tasks` + `/api/tasks/:id/stream` (SSE) |
| `/papers`           | Manuscripts      | `/api/manuscripts*` (M4 frontend)  |
| `/revision`         | Revision Studio  | `/api/manuscripts/:id` + revision workflow (M4 frontend) |
| `/memory`           | Memory Explorer  | `/api/memory/*`, `/api/knowledge/*`, `/api/heuristics/*` (M5 frontend) |
| `/settings`         | Settings         | `/api/version`, `/api/tools`, `/api/workflows` |

## Tech

- **React 19** + **TypeScript 5**
- **Vite 5** (with `@vitejs/plugin-react`)
- **Tailwind v4** via `@tailwindcss/vite` (no PostCSS config needed)
- **TanStack Query v5** for server state / SSE-driven cache invalidation
- **Zustand** for ephemeral UI state (theme, sidebar, filters)
- **React Router 7** (data router)
- **`@microsoft/fetch-event-source`** for SSE with proper backoff & reconnect
- **`sonner`** for toasts, **`lucide-react`** for icons
- **CSS variables** for theming, no shadcn registry needed yet — UI primitives
  live in `src/components/ui/` and are hand-authored shadcn-style components.
