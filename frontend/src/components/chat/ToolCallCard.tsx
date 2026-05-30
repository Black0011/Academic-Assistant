/**
 * ToolCallCard — collapsible card showing Agent execution steps.
 *
 * Renders skill invocations, MCP calls, file reads/writes, and
 * script executions as expandable cards in the chat thread.
 * Similar to Claude Code / Cursor's execution transparency.
 */
import {
  ChevronDown,
  ChevronRight,
  Code,
  FileText,
  Globe,
  Loader2,
  Sparkles,
  Terminal,
  Wrench,
} from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";

export type ToolKind = "skill" | "mcp" | "file_read" | "file_write" | "script" | "thinking";

export interface ToolCallStep {
  id: string;
  kind: ToolKind;
  name: string;
  status: "running" | "done" | "error";
  summary?: string;
  detail?: string;
  tokens?: number;
  args?: Record<string, unknown>;
}

interface ToolCallCardProps {
  steps: ToolCallStep[];
}

export function ToolCallCard({ steps }: ToolCallCardProps) {
  if (!steps || steps.length === 0) return null;

  return (
    <div className="space-y-1 my-2">
      {steps.map((step) => (
        <StepRow key={step.id} step={step} />
      ))}
    </div>
  );
}

function StepRow({ step }: { step: ToolCallStep }) {
  const [expanded, setExpanded] = useState(false);

  const icon = (() => {
    if (step.status === "running") return <Loader2 className="h-3.5 w-3.5 animate-spin" />;
    switch (step.kind) {
      case "skill": return <Sparkles className="h-3.5 w-3.5 text-purple-400" />;
      case "mcp": return <Globe className="h-3.5 w-3.5 text-blue-400" />;
      case "file_read": return <FileText className="h-3.5 w-3.5 text-green-400" />;
      case "file_write": return <FileText className="h-3.5 w-3.5 text-orange-400" />;
      case "script": return <Terminal className="h-3.5 w-3.5 text-amber-400" />;
      case "thinking": return <Code className="h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />;
      default: return <Wrench className="h-3.5 w-3.5" />;
    }
  })();

  const kindLabel = (() => {
    switch (step.kind) {
      case "skill": return "skill";
      case "mcp": return "MCP";
      case "file_read": return "read";
      case "file_write": return "write";
      case "script": return "script";
      case "thinking": return "think";
      default: return "tool";
    }
  })();

  const statusColor = step.status === "error" ? "text-red-400" : step.status === "running" ? "text-blue-400" : "text-[var(--color-muted-foreground)]";

  return (
    <div className="rounded-md border border-[var(--color-border)]/50 text-xs">
      <button
        type="button"
        onClick={() => step.detail && setExpanded(!expanded)}
        className="flex w-full items-center gap-2 px-2.5 py-1.5 hover:bg-[var(--color-muted)]/30 text-left"
      >
        {step.detail ? (
          expanded ? <ChevronDown className="h-3 w-3 shrink-0" /> : <ChevronRight className="h-3 w-3 shrink-0" />
        ) : (
          <span className="w-3 shrink-0" />
        )}
        {icon}
        <span className="font-mono font-medium truncate">{step.name}</span>
        <Badge variant="neutral" className="text-[9px] px-1 shrink-0">{kindLabel}</Badge>
        {step.tokens !== undefined && (
          <span className="text-[10px] text-[var(--color-muted-foreground)] shrink-0">{step.tokens}tok</span>
        )}
        {step.status === "done" && step.summary && (
          <span className={`truncate ${statusColor}`}>{step.summary}</span>
        )}
        {step.status === "error" && (
          <span className="text-red-400 truncate">Failed</span>
        )}
      </button>
      {expanded && step.detail && (
        <div className="border-t px-3 py-2 font-mono text-[11px] whitespace-pre-wrap max-h-32 overflow-y-auto bg-[var(--color-muted)]/20">
          {step.detail}
        </div>
      )}
    </div>
  );
}
