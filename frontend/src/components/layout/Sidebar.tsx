import {
  BookOpenText,
  BrainCircuit,
  GanttChartSquare,
  GitBranch,
  Home,
  LayoutPanelTop,
  Library,
  Plug,
  Settings as SettingsIcon,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { NavLink } from "react-router-dom";

import { cn } from "@/lib/cn";
import { useUiStore } from "@/stores/uiStore";

// IA simplification (P12.4) — the academic-assistant has exactly two
// daily workflows: 调研分析 and 写作/修改. The sidebar should reflect
// that, not the historical "every workflow gets its own top-level entry".
//
// Primary group:    the two daily-use entries + task history + settings
// Secondary group:  power-user surfaces (skills/mcp/planner) and the
//                   single-purpose viewers (library/memory) — still
//                   reachable, just visually demoted.
//
// Removed from the sidebar (still routable for bookmarks):
//   /papers           — subsumed by Research Console → Writing tab
//   /chat             — renamed to /workbench, kept as alias
//   /revision         — reachable from the workbench toolbar

interface NavLinkItem {
  kind: "link";
  to: string;
  labelKey: string;
  icon: typeof Home;
  end?: boolean;
}
interface NavSection {
  kind: "section";
  labelKey: string;
}
type NavItem = NavLinkItem | NavSection;

const NAV: ReadonlyArray<NavItem> = [
  { kind: "link", to: "/", labelKey: "nav.dashboard", icon: Home, end: true },
  { kind: "link", to: "/research", labelKey: "nav.researchConsole", icon: BookOpenText },
  { kind: "link", to: "/workbench", labelKey: "nav.workbench", icon: LayoutPanelTop },
  { kind: "link", to: "/tasks", labelKey: "nav.tasks", icon: GanttChartSquare },
  { kind: "link", to: "/settings", labelKey: "nav.settings", icon: SettingsIcon },
  { kind: "section", labelKey: "nav.sectionMore" },
  { kind: "link", to: "/library", labelKey: "nav.knowledgeLibrary", icon: Library },
  { kind: "link", to: "/memory", labelKey: "nav.memoryExplorer", icon: BrainCircuit },
  { kind: "link", to: "/proposals", labelKey: "nav.proposals", icon: ShieldCheck },
  { kind: "link", to: "/skills", labelKey: "nav.skills", icon: Wrench },
  { kind: "link", to: "/mcp", labelKey: "nav.mcpServers", icon: Plug },
  { kind: "link", to: "/planner", labelKey: "nav.plannerDag", icon: GitBranch },
];

interface SidebarProps {
  className?: string;
}

export function Sidebar({ className }: SidebarProps) {
  const collapsed = useUiStore((s) => s.sidebarCollapsed);
  const { t } = useTranslation();

  return (
    <aside
      className={cn(
        "flex flex-col border-r bg-[var(--color-card)]/40 backdrop-blur-sm",
        collapsed ? "w-[3.75rem]" : "w-60",
        "transition-[width] duration-150",
        className,
      )}
      aria-label={t("nav.primary")}
    >
      <div className="flex h-14 items-center gap-2 border-b px-4">
        <div className="flex h-8 w-8 items-center justify-center rounded-md bg-[var(--color-primary)] text-[var(--color-primary-foreground)]">
          <Sparkles className="h-4 w-4" aria-hidden />
        </div>
        {!collapsed && (
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">{t("app.shortName")}</div>
            <div className="text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)]">
              {t("app.tagline")}
            </div>
          </div>
        )}
      </div>

      <nav className="flex-1 overflow-y-auto p-2 scrollbar-thin">
        <ul className="space-y-0.5">
          {NAV.map((item, idx) => {
            if (item.kind === "section") {
              if (collapsed) {
                // In collapsed mode, sections degrade to a thin divider —
                // keep the visual rhythm without taking horizontal space.
                return (
                  <li key={`sec-${idx}`} className="my-2 border-t" aria-hidden />
                );
              }
              return (
                <li
                  key={`sec-${idx}`}
                  className="px-3 pb-1 pt-3 text-[10px] font-semibold uppercase tracking-wider text-[var(--color-muted-foreground)]/70"
                >
                  {t(item.labelKey)}
                </li>
              );
            }
            const { to, labelKey, icon: Icon, end } = item;
            const label = t(labelKey);
            return (
              <li key={to}>
                <NavLink
                  to={to}
                  end={end}
                  title={label}
                  className={({ isActive }) =>
                    cn(
                      "group flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                      isActive
                        ? "bg-[var(--color-accent)] text-[var(--color-accent-foreground)]"
                        : "text-[var(--color-muted-foreground)] hover:bg-[var(--color-accent)]/60 hover:text-[var(--color-foreground)]",
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" aria-hidden />
                  {!collapsed && <span className="truncate">{label}</span>}
                </NavLink>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="border-t p-3 text-[10px] text-[var(--color-muted-foreground)]">
        {!collapsed && <span>v0.1.0 · {t("app.selfHosted")}</span>}
      </div>
    </aside>
  );
}
