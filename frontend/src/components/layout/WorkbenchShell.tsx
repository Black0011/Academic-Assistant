/**
 * Three-pane workbench layout primitive (cursor / vscode-style).
 *
 * Owns:
 *  - drag-handle resize between left↔center and center↔right
 *  - per-pane collapse toggles via header buttons
 *  - panel-state persistence (delegated to `workbenchStore`)
 *
 * Does NOT own:
 *  - the contents of any pane (caller passes `left` / `center` / `right`)
 *  - any data fetching (pure layout primitive)
 *
 * Hand-rolled instead of pulling in `react-resizable-panels` because
 * project conventions (see `aaf-project-conventions/SKILL.md`) prefer
 * < 100 lines of std code over a new dependency; the only feature we
 * need is "drag-to-resize + collapse", which is straightforward with
 * pointer events.
 */

import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";
import { useWorkbenchStore } from "@/stores/workbenchStore";

import { PanelLeftClose, PanelLeftOpen, PanelRightClose, PanelRightOpen } from "lucide-react";

interface WorkbenchShellProps {
  /** Optional toolbar rendered above the three panes (full-width). */
  toolbar?: ReactNode;
  left: ReactNode;
  center: ReactNode;
  right: ReactNode;
  /** i18n key prefix for pane titles — used as accessible labels on toggles. */
  leftTitle?: string;
  centerTitle?: string;
  rightTitle?: string;
}

export function WorkbenchShell({
  toolbar,
  left,
  center,
  right,
  leftTitle,
  centerTitle,
  rightTitle,
}: WorkbenchShellProps) {
  const { t } = useTranslation();
  const {
    leftWidthPx,
    rightWidthPx,
    leftVisible,
    centerVisible,
    rightVisible,
    setLeftWidth,
    setRightWidth,
    toggleLeft,
    toggleCenter,
    toggleRight,
  } = useWorkbenchStore();

  // Ensure center pane is never stuck hidden from persisted state
  useEffect(() => {
    if (!centerVisible) toggleCenter();
  }, []);  // run once on mount

  return (
    // calc subtracts the layout shell's chrome (header + the optional
    // toolbar slot) so the panes fill the rest of the viewport exactly.
    <div className="flex h-[calc(100vh-3.5rem)] flex-col">
      {toolbar ? (
        <div className="flex h-10 shrink-0 items-center gap-2 border-b bg-[var(--color-card)]/30 px-3">
          {/* Quick toggles for each pane — sit in the global toolbar so
              they're always reachable, even when a pane is hidden.    */}
          <PaneToggle
            visible={leftVisible}
            onClick={toggleLeft}
            label={leftTitle ? t(leftTitle) : t("workbench.leftPane")}
            side="left"
          />
          <PaneToggle
            visible={centerVisible}
            onClick={toggleCenter}
            label={centerTitle ? t(centerTitle) : t("workbench.centerPane")}
            side="center"
          />
          <PaneToggle
            visible={rightVisible}
            onClick={toggleRight}
            label={rightTitle ? t(rightTitle) : t("workbench.rightPane")}
            side="right"
          />
          <div className="ml-2 h-4 w-px bg-[var(--color-border)]" />
          {toolbar}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        {leftVisible ? (
          <>
            <Pane width={leftWidthPx} className="border-r">
              <PaneHeader
                title={leftTitle ? t(leftTitle) : t("workbench.leftPane")}
                onCollapse={toggleLeft}
                side="left"
              />
              <div className="min-h-0 flex-1 overflow-y-auto">{left}</div>
            </Pane>
            <DragHandle onResize={(dx) => setLeftWidth(leftWidthPx + dx)} />
          </>
        ) : null}

        {centerVisible ? (
          <Pane flex>
            <PaneHeader
              title={centerTitle ? t(centerTitle) : t("workbench.centerPane")}
              onCollapse={toggleCenter}
            />
            <div className="min-h-0 flex-1">{center}</div>
          </Pane>
        ) : null}

        {rightVisible ? (
          <>
            <DragHandle onResize={(dx) => setRightWidth(rightWidthPx - dx)} />
            <Pane width={rightWidthPx} className="border-l">
              <PaneHeader
                title={rightTitle ? t(rightTitle) : t("workbench.rightPane")}
                onCollapse={toggleRight}
                side="right"
              />
              <div className="min-h-0 flex-1 overflow-y-auto">{right}</div>
            </Pane>
          </>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Building blocks
// ---------------------------------------------------------------------------

interface PaneProps {
  /** Fixed pixel width — omit for a flex-1 pane (the center). */
  width?: number;
  /** When true, the pane stretches to fill remaining space. */
  flex?: boolean;
  className?: string;
  children: ReactNode;
}

function Pane({ width, flex, className, children }: PaneProps) {
  const style = width !== undefined ? { width: `${width}px`, flexShrink: 0 } : undefined;
  return (
    <section
      style={style}
      className={cn(
        "flex min-h-0 flex-col bg-[var(--color-background)]",
        flex && "min-w-0 flex-1",
        className,
      )}
    >
      {children}
    </section>
  );
}

interface PaneHeaderProps {
  title: string;
  onCollapse: () => void;
  side?: "left" | "right";
}

function PaneHeader({ title, onCollapse, side }: PaneHeaderProps) {
  const Icon = side === "right" ? PanelRightClose : PanelLeftClose;
  return (
    <div className="flex h-8 shrink-0 items-center justify-between border-b px-2 text-xs font-medium text-[var(--color-muted-foreground)]">
      <span className="truncate uppercase tracking-wide">{title}</span>
      <Button
        type="button"
        variant="ghost"
        size="icon"
        className="h-6 w-6"
        onClick={onCollapse}
        aria-label={`Hide ${title}`}
        title={`Hide ${title}`}
      >
        <Icon className="h-3.5 w-3.5" />
      </Button>
    </div>
  );
}

interface PaneToggleProps {
  visible: boolean;
  onClick: () => void;
  label: string;
  side: "left" | "center" | "right";
}

function PaneToggle({ visible, onClick, label, side }: PaneToggleProps) {
  const Icon = visible
    ? side === "left"
      ? PanelLeftClose
      : side === "right"
        ? PanelRightClose
        : PanelLeftClose  // center uses same close icon
    : side === "left"
      ? PanelLeftOpen
      : side === "right"
        ? PanelRightOpen
        : PanelLeftOpen;  // center uses same open icon
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="h-7 w-7"
      onClick={onClick}
      aria-pressed={visible}
      title={`${visible ? "Hide" : "Show"} ${label}`}
      aria-label={`${visible ? "Hide" : "Show"} ${label}`}
    >
      <Icon className="h-3.5 w-3.5" />
    </Button>
  );
}

interface DragHandleProps {
  /** Called continuously while the user drags. `dx` is the cumulative
   *  delta since pointerdown — caller adds it to whichever pane's width
   *  should grow / shrink. */
  onResize: (dx: number) => void;
}

function DragHandle({ onResize }: DragHandleProps) {
  const [dragging, setDragging] = useState(false);
  const startX = useRef<number>(0);

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragging(true);
    startX.current = e.clientX;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (!dragging) return;
      const dx = e.clientX - startX.current;
      if (Math.abs(dx) < 1) return;
      startX.current = e.clientX;
      onResize(dx);
    },
    [dragging, onResize],
  );

  const onPointerUp = useCallback((e: React.PointerEvent<HTMLDivElement>) => {
    setDragging(false);
    (e.target as HTMLElement).releasePointerCapture?.(e.pointerId);
  }, []);

  // Keep the cursor styled while dragging even when the pointer is over
  // child elements — feels much smoother than the default flicker.
  useEffect(() => {
    if (!dragging) return;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [dragging]);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerCancel={onPointerUp}
      className={cn(
        "group relative w-1 shrink-0 cursor-col-resize",
        dragging
          ? "bg-[var(--color-primary)]"
          : "bg-transparent hover:bg-[var(--color-primary)]/40",
      )}
    >
      {/* Wider invisible hit-box so the 1px visible line still grabs the
          pointer reliably — common pattern for thin resize handles.   */}
      <div className="absolute inset-y-0 -left-1.5 -right-1.5" />
    </div>
  );
}
