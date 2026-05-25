/**
 * Friendly task-error renderer (P9.1).
 *
 * Backend task records carry an ``error`` field shaped like
 * ``"<ExceptionType>: <message>"`` (see ``backend/workflows/*.py`` and
 * ``backend/tasks/runner.py``). This component:
 *
 *  - Parses the type prefix and looks up a translated short title +
 *    actionable hint via the ``errors.types.<TypeName>.*`` namespace.
 *  - Shows the raw technical message (always — power users want it).
 *  - Falls back to ``errors.fallback.*`` when the type is unknown so
 *    we never render a blank panel.
 *
 * Two density modes:
 *
 *  - ``compact`` for list rows (TasksPage) — single coloured line with
 *    a title + truncated message + hover tooltip for the rest.
 *  - ``full`` for detail pages (RevisionPage / ResearchConsolePage /
 *    PaperWriterPage) — boxed panel with title, hint, and the raw
 *    message in a <details> drawer.
 */

import { AlertTriangle, ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { cn } from "@/lib/cn";

interface ParsedError {
  type: string;
  message: string;
}

function parseError(raw: string): ParsedError {
  // Shape produced by P9.0: ``"<TypeName>: <message>"`` — match the
  // first colon, but only when the LHS looks like a Python class name.
  const m = raw.match(/^([A-Za-z_][A-Za-z0-9_]*Error|[A-Za-z_][A-Za-z0-9_]*Exception|ValueError|TypeError|RuntimeError|BrokenPipeError|ConnectionError|OSError):\s*(.*)$/s);
  if (m) return { type: m[1], message: m[2] };
  return { type: "Unknown", message: raw };
}

interface Props {
  error: string;
  density?: "compact" | "full";
  className?: string;
}

export function TaskError({ error, density = "full", className }: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const parsed = parseError(error);

  // Lookup with sane fallback chain: specific type → fallback.
  const titleKey = `errors.types.${parsed.type}.title`;
  const hintKey = `errors.types.${parsed.type}.hint`;
  const title = t(titleKey, { defaultValue: t("errors.fallback.title") });
  const hint = t(hintKey, { defaultValue: t("errors.fallback.hint") });

  if (density === "compact") {
    return (
      <span
        className={cn(
          "inline-flex max-w-full items-center gap-1 text-[var(--color-destructive)]",
          className,
        )}
        title={`${parsed.type}: ${parsed.message}`}
      >
        <AlertTriangle className="h-3 w-3 shrink-0" />
        <span className="font-medium">{title}</span>
        <span className="truncate opacity-75">· {parsed.message}</span>
      </span>
    );
  }

  return (
    <div
      className={cn(
        "rounded-md border border-[var(--color-destructive)]/40 bg-[var(--color-destructive)]/10 p-3",
        className,
      )}
      role="alert"
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--color-destructive)]" />
        <div className="min-w-0 flex-1 space-y-1">
          <div className="text-sm font-semibold text-[var(--color-destructive)]">{title}</div>
          <div className="text-xs text-[var(--color-destructive)]/90">{hint}</div>
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="mt-1 inline-flex items-center gap-1 text-[11px] text-[var(--color-muted-foreground)] hover:text-[var(--color-foreground)]"
          >
            {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
            {t("errors.toggleRaw")}
          </button>
          {open && (
            <pre className="mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-[var(--color-muted)]/40 p-2 font-mono text-[10px] text-[var(--color-foreground)]/85">
              {parsed.type}: {parsed.message}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}

export function pickFriendlyTitle(error: string, t: (k: string, o?: Record<string, unknown>) => string): string {
  const parsed = parseError(error);
  return t(`errors.types.${parsed.type}.title`, { defaultValue: t("errors.fallback.title") });
}
