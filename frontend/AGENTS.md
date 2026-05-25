# frontend/AGENTS.md

React 19 + Vite + Tailwind v4 + TanStack Query. Single-page app served
behind nginx in production; talks to `/api/*` on the same origin.

## House rules

1. **Server state lives in React Query**, not Zustand. Zustand holds UI
   state (theme, sidebar) and ephemeral form drafts only.
2. **One component, one file.** UI primitives in `components/ui/`; pages
   in `pages/`; cross-cutting in `components/common/`.
3. **No inline `fetch`.** Use `lib/api.ts` (`api<T>()`). It centralises
   error mapping and timeouts and is the single place auth headers will
   land in M5.
4. **Type the wire.** All response/request shapes live in
   `src/types/api.ts`, hand-mirrored from backend Pydantic. We'll switch
   to OpenAPI codegen once the surface stabilises.
5. **No SSR, no Next.** Vite is the entire build. Don't import
   server-only APIs.

## Layout

```
frontend/src/
├── main.tsx · routes/index.tsx
├── lib/{api,cn,queryClient}.ts
├── hooks/                 ← useTaskStream, useSSE-style hooks
├── stores/uiStore.ts      ← zustand persist (theme, sidebar)
├── types/api.ts           ← backend DTO mirrors
├── components/
│   ├── layout/{AppLayout,Sidebar,TopBar}.tsx
│   ├── ui/                ← Button / Card / Input / … (shadcn-style, hand-rolled)
│   ├── common/            ← PageHeader, EmptyState, StatusPill
│   └── <feature>/         ← feature-scoped components (e.g. research/)
└── pages/                 ← one file per route, named <Page>Page.tsx
```

## Adding a page

1. New file: `src/pages/MyThingPage.tsx` exporting a named component.
2. Wire it in `src/routes/index.tsx` and add a `NavLink` to
   `components/layout/Sidebar.tsx`.
3. If the page reads server data, add the query in the page itself with a
   stable `queryKey` (`["mything", { …filters }]`). Hooks live in
   `src/hooks/` only when they're shared.
4. Use the `Card`, `PageHeader`, `EmptyState`, `StatusPill` primitives
   for visual consistency. Don't restyle them inline.

## M7 surface (delivered)

| Page / surface       | Path                  | Backend                              | Notes                                                            |
| -------------------- | --------------------- | ------------------------------------ | ---------------------------------------------------------------- |
| Knowledge Library    | `/library`, `/library/:docId` | `/api/documents/*`           | Doc upload / chunks / per-doc search; pairs with M7.3 RAG.       |
| Skills               | `/skills`, `/skills/:name`    | `/api/skills/*`              | List + detail + Install/Edit/Dry-run; admin-only writes.         |
| Memory · Knowledge   | (existing)            | `/api/knowledge/papers/ingest`       | "Ingest paper" drawer in `MemoryPage` Knowledge tab.             |

## M8 surface (delivered)

| Page / surface | Path                                                  | Backend             | Notes                                                                                                  |
| -------------- | ----------------------------------------------------- | ------------------- | ------------------------------------------------------------------------------------------------------ |
| Planner DAG    | `/planner`                                            | `/api/planner/*`    | Compile NL goal → DAG, validate, execute. Live SSE projection on top of `task.stage_*` events. M8.2.   |
| Proposals      | `/proposals`, `/proposals/:proposalId`                | `/api/proposals/*`  | Gated framework changes: draft → pending → approved → applied. `apply` records status only. M8.1.      |

Sidebar order after M8: Dashboard → Research → Manuscripts → Revision → Library → Memory → Skills → **Planner DAG** → **Proposals** → Tasks → Settings.

## P12.3 / P12.4 surface (delivered)

| Page / surface | Path                                              | Backend                       | Notes                                                                                                                       |
| -------------- | ------------------------------------------------- | ----------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| Workbench      | `/workbench[/:manuscriptId]`, alias `/chat[/:id]` | `/api/manuscripts/*` + tasks  | Cursor-style 3-pane shell: file tree · Monaco preview · chat. Replaces the standalone Paper Chat entry in the sidebar.      |
| Console tabs   | `/research?tab=research\|writing`                 | `/api/manuscripts`, workflows | "Research" tab is the original task form. "Writing" tab lists manuscripts and click-throughs into the Workbench.            |

Sidebar order after P12.4: **Dashboard → Research Console → Workbench → Tasks → Settings** (primary group) ─── *More* ─── **Library → Memory → Proposals → Skills → MCP Servers → Planner DAG** (secondary group).

Dropped from the sidebar (routes still resolve so bookmarks survive):
* `/papers`   — reachable via Research Console → Writing → "Manage all".
* `/chat`     — alias of `/workbench`.
* `/revision` — reachable via the Workbench toolbar (top-right link).

The Writing IA mantra (do not regress): one front-door per workflow.
If you find yourself adding a "Manuscript Foo" sidebar entry, instead
add a tab on `/research`, an action button inside `/workbench`, or a
deep-link from `/tasks`.

### Workbench layout primitive

`components/layout/WorkbenchShell.tsx` owns the 3-pane geometry (left
fixed-px, center flex, right fixed-px) with drag-handles between
adjacent visible panes. State lives in `stores/workbenchStore.ts`
under the persist key `aaf.workbench.layout` — widths are clamped to
`[160, 800]` px and visibility flags are per-pane booleans. Hand-rolled
instead of `react-resizable-panels` per project convention (see
`.cursor/skills/aaf-project-conventions/SKILL.md` §4).

Page contracts:

* `PlannerPage` reuses `useTaskStream` to project per-node runtime back
  onto the topo-layered graph; never re-implements SSE. Validation is
  debounced (~400ms) so JSON edits don't spam `/api/planner/validate`.
* `ProposalsPage` uses `@monaco-editor/react` in `language="diff"` for
  the read-only viewer and an editable Monaco for the create-drawer.
  No file-system writes happen client-side — that's M8.1's whole point.

## P13 surface (delivered)

| Page / surface     | Path                            | Backend                                | Notes                                                                                                                                                |
| ------------------ | ------------------------------- | -------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Knowledge CRUD     | `/memory` → "Knowledge" tab     | `POST/PATCH/DELETE /api/knowledge/papers` | Manual create / edit / delete drawer, two-level taxonomy filter (`field_major / field_minor`), URL external-link icon.                            |
| Skills graph       | `/skills?view=graph`            | `GET /api/skills/graph`                | xyflow + dagre LR layout. Edges read-only — edit via the existing SKILL.md body editor; the graph re-renders on refetch.                             |

### PaperFormDrawer

`components/memory/PaperFormDrawer.tsx` is the modal panel for manual
PaperCard CRUD. Reuses OnboardingDialog's `fixed inset-0 / bg-black/40`
pattern — we have NOT extracted a Dialog primitive because there are
only two consumers; a third one is the threshold. The drawer
constructs its payload with empty-string → `null` mapping for the
optional `str | None` fields so the backend's `exclude_none=True`
semantics work correctly:

* Empty input  → `null`  → "no change" on PATCH, "no value" on POST.
* Non-empty    → string  → write that value.
* Explicit clear is NOT supported by this drawer; user can change the
  value but not blank it out, matching how the existing fields behave.

### SkillsGraphView

`components/skills/SkillsGraphView.tsx` is a **read-mostly**
visualisation:

* Nodes coloured by domain (`writing` / `revision` / `rebuttal` /
  `research` / `survey` / `meta` fallback). Same palette on the
  minimap pip.
* Edge palette: `declared_by="both"` emerald `↔`, one-sided slate `→`,
  cycle members animated amber. Dangling references render as hollow
  dashed nodes so the broken link is visible without faking a target.
* Node click navigates to `/skills/:name?view=graph` (preserves the
  view URL param). The existing SkillDetailPanel opens on the right.
* `nodesDraggable: false` / `nodesConnectable: false` — drag-to-create-
  edge is intentionally NOT supported. The single source of truth for
  edges is each SKILL.md's `compatibility` frontmatter; users edit
  that via the existing body editor, and the graph re-fetches on the
  15s polling interval.

If you need to add interactive editing in a future round, build it
as a **mode toggle** on the graph (`editable` prop) that calls
`PATCH /api/skills/:name` with a new body_md — do NOT add a parallel
`/api/skills/:name/edges` route. One source of truth, one edit path.

### Dependencies added in P13

* `@xyflow/react@12`   — React node-editor (P13.D only).
* `dagre@0.8`          — layered DAG auto-layout.
* `@types/dagre`       — types.

The reasoning for breaking the "<100 lines of std code" rule is
pinned in the P13.D commit body. If you find yourself reaching for a
similar dep, write the equivalent justification first; if you can't
get past "it would be easier with X", write the std-lib version.

## SSE

Use `useTaskStream(taskId)` for `/api/tasks/:id/stream`. It auto-aborts on
terminal events and surfaces `status` + `events`. Don't call
`new EventSource()` directly — it can't carry auth headers.

## Theming

CSS variables in `src/index.css` under `@theme`. Don't introduce new
colour literals in components — extend tokens instead. Dark mode is
class-based (`html.dark`), driven by `applyTheme()` in
`stores/uiStore.ts`.

## Build / quality gate

```bash
npm install
npm run typecheck          # tsc -b --noEmit
npm run build              # tsc + vite build  (this is what CI runs)
npm run dev                # http://127.0.0.1:5173
```

A failing `typecheck` blocks `make check`.
