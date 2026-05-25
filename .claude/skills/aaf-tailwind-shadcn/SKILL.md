---
name: aaf-tailwind-shadcn
description: >-
  Tailwind CSS v4 and shadcn/ui conventions for the AAF frontend. Covers
  design tokens, component customisation, dark mode, responsive breakpoints,
  and the `cn` composition helper. Load when touching any styling code.
domain: engineering
triggers:
  - tailwind
  - shadcn
  - styling
  - theme
  - dark mode
  - css
  - frontend/src/styles
  - frontend/src/components/ui
version: "1.0.0"
---

# AAF Styling — Tailwind v4 + shadcn/ui

## 1. Why this stack

shadcn/ui is **not an npm package**. Components are copied into `src/components/ui/` so they are fully editable — we own the source. Tailwind v4 provides the utility engine and the CSS variable system that shadcn colour tokens hook into. Together they give us:

- No runtime style generation (every class is known at build time)
- No opaque component library to work around
- First-class dark mode via CSS variables
- Type-safe component APIs under our control

## 2. Install / initialise (M3-0)

```bash
pnpm add -D tailwindcss@next @tailwindcss/vite
pnpm add clsx tailwind-merge class-variance-authority lucide-react
npx shadcn@latest init
```

`components.json` lives at `frontend/components.json` and is version controlled.

## 3. Adding a shadcn component

```bash
npx shadcn@latest add button card dialog sheet tabs sidebar
```

This writes editable `.tsx` files under `src/components/ui/`. Edit them freely — they are our code now.

## 4. Composing classes

Use the `cn` helper (already exported by shadcn bootstrap):

```ts
// src/lib/utils.ts
import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs))
}
```

```tsx
<Button className={cn('w-full', disabled && 'opacity-50', variant === 'ghost' && 'bg-transparent')}>
```

Never concatenate class names with `+` or template literals — `cn` deduplicates and resolves Tailwind conflicts.

## 5. Design tokens

All tokens live in `src/styles/globals.css`:

```css
@import "tailwindcss";

@theme inline {
  --font-sans: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
  --font-mono: ui-monospace, "JetBrains Mono", "Menlo", monospace;
  --radius-sm: 0.25rem;
  --radius: 0.5rem;
  --radius-lg: 0.75rem;
}

:root {
  --background: 0 0% 100%;
  --foreground: 240 10% 3.9%;
  --card: 0 0% 100%;
  --card-foreground: 240 10% 3.9%;
  --primary: 221 83% 53%;
  --primary-foreground: 0 0% 100%;
  --muted: 240 4.8% 95.9%;
  --muted-foreground: 240 3.8% 46.1%;
  --accent: 240 4.8% 95.9%;
  --accent-foreground: 240 5.9% 10%;
  --border: 240 5.9% 90%;
  --destructive: 0 84.2% 60.2%;
}

.dark {
  --background: 240 10% 3.9%;
  --foreground: 0 0% 98%;
  /* … remaining overrides … */
}
```

- **Never hardcode hex colours in components** — always reference tokens (e.g. `bg-primary`, `text-muted-foreground`).
- Adding a new token requires updating both `:root` and `.dark`.

## 6. Dark mode

Toggle by adding / removing `class="dark"` on `<html>`. The `useUIStore` (Zustand) owns the preference and an effect in `App.tsx` syncs it to the DOM.

```tsx
useEffect(() => {
  document.documentElement.classList.toggle('dark', theme === 'dark')
}, [theme])
```

**Never** test theme via `window.matchMedia` inside components — go through the store so state is single-sourced.

## 7. Responsive breakpoints

Stick to Tailwind defaults:

| Prefix | Min width | Use case |
|---|---|---|
| `sm:` | 640px  | small tablets |
| `md:` | 768px  | tablets, split views |
| `lg:` | 1024px | laptop baseline |
| `xl:` | 1280px | standard desktop |
| `2xl:` | 1536px | large displays |

Design **desktop-first** for the app shell (research console, writer, revision studio) but ensure every page collapses gracefully at `md`. Mobile is best-effort — the target surface is a 13"+ laptop.

## 8. Layout primitives

- App shell: shadcn `<Sidebar>` + `<SidebarInset>` + `<SidebarProvider>`
- Modal interactions: `<Dialog>` for blocking, `<Sheet>` for side panels, `<Drawer>` only on mobile
- Grouped controls: `<Tabs>`, `<ToggleGroup>`
- Data display: `<Card>`, `<Table>`, custom virtual list with `@tanstack/react-virtual`
- Feedback: `<Alert>`, `sonner` toast (imported once at app root)

Never nest dialogs inside dialogs. For multi-step flows use `<Tabs>` or a dedicated wizard component.

## 9. Icons

- **`lucide-react`** only. Import named: `import { Search, Plus } from 'lucide-react'`.
- Never render raw SVG outside `components/ui/icons/` (which should remain small and curated).
- Always set `aria-hidden="true"` on decorative icons; provide an `aria-label` on interactive icon-only buttons.

## 10. Animation

- shadcn ships with `tailwindcss-animate`; prefer its utilities (`animate-in`, `fade-in`, `slide-in-from-right-*`).
- Long-running / choreographed motion → `framer-motion` (allowed, but must stay inside `components/motion/`).
- Avoid CSS keyframes in component files; put them as `@keyframes` in `globals.css` if truly necessary.

## 11. Common pitfalls

- **Class ordering drift** — install the `prettier-plugin-tailwindcss` plugin; CI enforces.
- **Mixing `hsl()` and `rgb()` in tokens** — stick to the `hsl space-separated` form that shadcn expects.
- **Forgetting dark-mode tokens** — every new token must appear in both `:root` and `.dark`.
- **Global css files per component** — banned. All styling is Tailwind classes.
- **Inline `style={{...}}` for anything other than dynamic dimensions (`width: ${w}px`)** — banned.

## 12. Don't

- Don't install `styled-components`, `emotion`, `stitches`, `twin.macro` — any CSS-in-JS library.
- Don't `@apply` utilities in component css — compose in JSX via `cn()`.
- Don't override shadcn primitive internals via monkey-patching — edit the copy in `src/components/ui/`.
- Don't introduce a second icon library alongside `lucide-react`.
- Don't use Tailwind's JIT arbitrary values for colours (`bg-[#123456]`) — define a token.
