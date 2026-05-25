import { format } from "date-fns";
import {
  AlertTriangle,
  Brain,
  Cpu,
  Database,
  Hammer,
  PencilLine,
  ShieldAlert,
  Sparkle,
  Workflow,
} from "lucide-react";
import { useMemo } from "react";

import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/cn";
import type { StreamEvent } from "@/types/api";

interface Stage {
  name: string;
  startedAt?: string;
  endedAt?: string;
  events: StreamEvent[];
  ok?: boolean;
}

interface Props {
  events: ReadonlyArray<StreamEvent>;
}

/**
 * Group raw events into stages, anchored by `task.stage_start` /
 * `task.stage_end`. Pre-stage events live under a synthetic "setup" bucket;
 * post-task events under "summary".
 */
function groupEvents(events: ReadonlyArray<StreamEvent>): Stage[] {
  const stages: Stage[] = [];
  let current: Stage = { name: "setup", events: [] };

  for (const ev of events) {
    if (ev.type === "task.stage_start") {
      if (current.events.length > 0) stages.push(current);
      current = {
        name: typeof ev.data.stage === "string" ? ev.data.stage : "stage",
        startedAt: ev.at,
        events: [],
      };
      continue;
    }
    if (ev.type === "task.stage_end") {
      current.endedAt = ev.at;
      current.ok = ev.data.error == null;
      stages.push(current);
      current = { name: "between", events: [] };
      continue;
    }
    current.events.push(ev);
  }
  if (current.events.length > 0) stages.push(current);
  return stages;
}

const ICON_BY_PREFIX: Array<[string, typeof Sparkle, string]> = [
  ["task.error", AlertTriangle, "text-[var(--color-destructive)]"],
  // P12.1 — soft-fail signal: render with the same icon as rule.block so
  // it reads as a warning, not an error. Recoverable degradations
  // (recall failed, embedder offline) emit task.warning instead of
  // task.error so the workflow keeps running.
  ["task.warning", ShieldAlert, "text-[var(--color-warning)]"],
  ["task.", Workflow, "text-[var(--color-primary)]"],
  ["skill.", Hammer, "text-[var(--color-foreground)]"],
  ["llm.", Cpu, "text-[var(--color-foreground)]"],
  ["memory.", Database, "text-[var(--color-foreground)]"],
  ["rule.", ShieldAlert, "text-[var(--color-warning)]"],
];

function eventIcon(type: string) {
  for (const [prefix, Icon, color] of ICON_BY_PREFIX) {
    if (type.startsWith(prefix)) return { Icon, color };
  }
  return { Icon: Sparkle, color: "text-[var(--color-muted-foreground)]" };
}

function summarise(ev: StreamEvent): string {
  const d = ev.data ?? {};
  switch (ev.type) {
    case "task.start":
      return typeof d.workflow === "string" ? `workflow: ${d.workflow}` : "task started";
    case "task.end":
      return typeof d.verdict === "string" ? `verdict: ${d.verdict}` : "task complete";
    case "task.error":
      return typeof d.error === "string" ? d.error : "task failed";
    case "task.warning": {
      // Soft-fail summary: prefer "<stage> degraded: <reason>" so it reads
      // naturally inline. ``source_type`` is the original exception class
      // (e.g. BrokenPipeError) — useful to power-users, hidden behind the
      // generic "degraded" phrasing for everyone else.
      const stage = typeof d.stage === "string" ? d.stage : "stage";
      const msg = typeof d.message === "string" ? d.message : "degraded";
      return `${stage} degraded: ${msg}`;
    }
    case "skill.matched":
      return typeof d.skill === "string" ? `matched ${d.skill}` : "skill matched";
    case "skill.call":
      return typeof d.skill === "string" ? `→ ${d.skill}` : "skill call";
    case "skill.result":
      return typeof d.skill === "string" ? `← ${d.skill}` : "skill result";
    case "llm.call": {
      const tokens = typeof d.tokens === "number" ? `${d.tokens} tok` : null;
      const cost = typeof d.cost_usd === "number" ? `$${d.cost_usd.toFixed(4)}` : null;
      return [d.model, tokens, cost].filter(Boolean).join(" · ") || "llm call";
    }
    case "llm.token":
      return typeof d.text === "string" ? d.text.slice(0, 80) : "token";
    case "memory.read":
    case "memory.write":
      return typeof d.store === "string" ? `${ev.type.split(".")[1]} → ${d.store}` : ev.type;
    case "rule.block":
      return typeof d.rule === "string" ? `blocked by ${d.rule}` : "rule blocked";
    default:
      return Object.keys(d).length ? JSON.stringify(d).slice(0, 120) : "";
  }
}

export function EventTimeline({ events }: Props) {
  const stages = useMemo(() => groupEvents(events), [events]);

  if (events.length === 0) {
    return (
      <div className="rounded-md border border-dashed p-6 text-center text-sm text-[var(--color-muted-foreground)]">
        Waiting for events…
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {stages.map((stage, idx) => (
        <div key={`${stage.name}-${idx}`} className="rounded-lg border bg-[var(--color-card)]">
          <div className="flex items-center justify-between gap-2 border-b px-4 py-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <PencilLine className="h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />
              <span className="font-mono uppercase tracking-wider">{stage.name}</span>
              {stage.ok === true && <Badge variant="success">ok</Badge>}
              {stage.ok === false && <Badge variant="destructive">error</Badge>}
            </div>
            <div className="text-xs tabular-nums text-[var(--color-muted-foreground)]">
              {stage.startedAt && format(new Date(stage.startedAt), "HH:mm:ss.SSS")}
              {stage.endedAt && (
                <>
                  {" → "}
                  {format(new Date(stage.endedAt), "HH:mm:ss.SSS")}
                </>
              )}
            </div>
          </div>
          <ol className="divide-y">
            {stage.events.map((ev, i) => {
              const { Icon, color } = eventIcon(ev.type);
              return (
                <li
                  key={`${ev.type}-${ev.at}-${i}`}
                  className="flex gap-3 px-4 py-2 text-xs"
                >
                  <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", color)} aria-hidden />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
                        {ev.type}
                      </span>
                      <span className="shrink-0 tabular-nums text-[var(--color-muted-foreground)]">
                        {format(new Date(ev.at), "HH:mm:ss.SSS")}
                      </span>
                    </div>
                    <div className="mt-0.5 truncate font-medium">{summarise(ev)}</div>
                  </div>
                </li>
              );
            })}
            {stage.events.length === 0 && (
              <li className="flex items-center gap-2 px-4 py-2 text-xs text-[var(--color-muted-foreground)]">
                <Brain className="h-3.5 w-3.5" /> empty stage
              </li>
            )}
          </ol>
        </div>
      ))}
    </div>
  );
}
