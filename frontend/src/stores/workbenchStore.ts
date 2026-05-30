/**
 * Workbench pane layout state.
 *
 * Lives in its own store (instead of ``uiStore``) because pane widths
 * change on every drag-handle move — keeping that high-churn state out
 * of ``uiStore`` avoids spurious re-renders for unrelated subscribers
 * (theme, language, sidebar collapse).
 *
 * Persistence is via Zustand's ``persist`` middleware so a reload keeps
 * the user's preferred layout — cursor / vscode do the same and users
 * expect it.
 *
 * Why three panes (left / center / right) rather than an open-ended
 * tab system? Because the workbench's job is small and well-defined:
 *   - left:   file navigator
 *   - center: editor / diff
 *   - right:  chat thread
 * Anything fancier would be a different app.
 */

import { create } from "zustand";
import { persist } from "zustand/middleware";

const DEFAULT_LEFT_PX = 260;
const DEFAULT_RIGHT_PX = 380;

// Hard floors keep a "collapsed" pane from being mistaken for "still
// visible" — anything below this is forced to zero so the toggle
// button has a stable contract.
const MIN_VISIBLE_PX = 160;
const MAX_PX = 800;

export interface WorkbenchLayoutState {
  leftWidthPx: number;
  rightWidthPx: number;
  leftVisible: boolean;
  centerVisible: boolean;
  rightVisible: boolean;
  setLeftWidth: (px: number) => void;
  setRightWidth: (px: number) => void;
  toggleLeft: () => void;
  toggleCenter: () => void;
  toggleRight: () => void;
  reset: () => void;
}

function clamp(px: number): number {
  if (px < MIN_VISIBLE_PX) return MIN_VISIBLE_PX;
  if (px > MAX_PX) return MAX_PX;
  return Math.round(px);
}

export const useWorkbenchStore = create<WorkbenchLayoutState>()(
  persist(
    (set) => ({
      leftWidthPx: DEFAULT_LEFT_PX,
      rightWidthPx: DEFAULT_RIGHT_PX,
      leftVisible: true,
      centerVisible: true,
      rightVisible: true,
      setLeftWidth: (px) => set({ leftWidthPx: clamp(px) }),
      setRightWidth: (px) => set({ rightWidthPx: clamp(px) }),
      toggleLeft: () => set((s) => ({ leftVisible: !s.leftVisible })),
      toggleCenter: () => set((s) => ({ centerVisible: !s.centerVisible })),
      toggleRight: () => set((s) => ({ rightVisible: !s.rightVisible })),
      reset: () =>
        set({
          leftWidthPx: DEFAULT_LEFT_PX,
          rightWidthPx: DEFAULT_RIGHT_PX,
          leftVisible: true,
          centerVisible: true,
          rightVisible: true,
        }),
    }),
    { name: "aaf.workbench.layout" },
  ),
);

export const WORKBENCH_LAYOUT_DEFAULTS = {
  LEFT_PX: DEFAULT_LEFT_PX,
  RIGHT_PX: DEFAULT_RIGHT_PX,
  MIN_VISIBLE_PX,
  MAX_PX,
} as const;
