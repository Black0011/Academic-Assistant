/**
 * ResearchSummary — inline chat bubble that renders a structured
 * research meta-summary. Reads from task.result.summary and displays
 * narrative, key findings, gaps, and next steps.
 *
 * This is a transient display artefact; it does NOT write to PaperCard
 * or any persistent memory store.
 */
import {
  ArrowRight,
  BookOpen,
  Lightbulb,
  SearchX,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/Badge";
import { Card, CardContent } from "@/components/ui/Card";

export interface ResearchSummaryData {
  narrative?: string;
  key_findings?: string[];
  gaps?: string[];
  next_steps?: string[];
}

interface ResearchSummaryProps {
  data: ResearchSummaryData;
}

export function ResearchSummary({ data }: ResearchSummaryProps) {
  if (!data) return null;

  const { narrative, key_findings, gaps, next_steps } = data;
  const isEmpty =
    !narrative &&
    (!key_findings || key_findings.length === 0) &&
    (!gaps || gaps.length === 0) &&
    (!next_steps || next_steps.length === 0);

  if (isEmpty) return null;

  return (
    <Card className="border-l-4 border-l-[var(--color-primary)]">
      <CardContent className="space-y-4 p-4 text-sm">
        {/* Header */}
        <div className="flex items-center gap-2 text-[var(--color-primary)]">
          <Sparkles className="h-4 w-4" />
          <span className="font-semibold">Research Summary</span>
        </div>

        {/* Narrative */}
        {narrative && (
          <div className="space-y-1">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
              <BookOpen className="h-3.5 w-3.5" />
              Synthesis
            </h4>
            <div className="leading-relaxed whitespace-pre-line text-[var(--color-foreground)]/85">
              {narrative}
            </div>
          </div>
        )}

        {/* Key Findings */}
        {key_findings && key_findings.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
              <Lightbulb className="h-3.5 w-3.5" />
              Key Findings
            </h4>
            <ul className="space-y-1">
              {key_findings.map((item, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-[var(--color-foreground)]/85"
                >
                  <Badge variant="neutral" className="mt-0.5 shrink-0 text-[10px] px-1.5">
                    {i + 1}
                  </Badge>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Gaps */}
        {gaps && gaps.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
              <SearchX className="h-3.5 w-3.5" />
              Gaps Identified
            </h4>
            <ul className="space-y-1">
              {gaps.map((item, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-[var(--color-muted-foreground)]"
                >
                  <span className="text-[10px]">-</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Next Steps */}
        {next_steps && next_steps.length > 0 && (
          <div className="space-y-1.5">
            <h4 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--color-muted-foreground)]">
              <ArrowRight className="h-3.5 w-3.5" />
              Next Steps
            </h4>
            <ul className="space-y-1">
              {next_steps.map((item, i) => (
                <li
                  key={i}
                  className="flex items-start gap-2 text-[var(--color-foreground)]/85"
                >
                  <Badge variant="outline" className="mt-0.5 shrink-0 text-[10px] px-1.5">
                    {i + 1}
                  </Badge>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
