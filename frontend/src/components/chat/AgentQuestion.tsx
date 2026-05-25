import { DiffEditor } from "@monaco-editor/react";
import { Check, RotateCcw, Send, X } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Input";
import { useRespondToTask } from "@/hooks/useRespondToTask";

interface AgentQuestionProps {
  taskId: string;
  prompt: string;
  checkpoint: string;
  promptData: Record<string, unknown>;
  monacoTheme?: string;
  onResponded?: (childTaskId: string) => void;
}

export function AgentQuestion({
  taskId,
  prompt,
  checkpoint,
  promptData,
  monacoTheme = "vs-dark",
  onResponded,
}: AgentQuestionProps) {
  const respondMut = useRespondToTask(taskId);
  const [refinedQuery, setRefinedQuery] = useState("");
  const [rejectedFiles, setRejectedFiles] = useState<Set<string>>(new Set());
  const [action, setAction] = useState<"accept_all" | "accept_some">("accept_all");

  const changes =
    (promptData.changes as Array<{
      path: string;
      before: string;
      after: string;
      summary: string;
    }>) ?? [];
  const plan = (promptData.plan as string) ?? "";
  const exploredFiles = (promptData.explored_files as string[]) ?? [];

  const handleRespond = (response: string, responseData: Record<string, unknown>) => {
    respondMut.mutate(
      { response, response_data: responseData },
      {
        onSuccess: (data) => {
          onResponded?.(data.task_id);
        },
      },
    );
  };

  const toggleReject = (path: string) => {
    setRejectedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
    setAction("accept_some");
  };

  // ---- empty_changes checkpoint -------------------------------------------
  if (checkpoint === "empty_changes") {
    return (
      <div className="space-y-3 rounded border border-[var(--color-warning)] bg-[var(--color-warning)]/5 p-3 text-xs">
        <div className="flex items-start gap-2">
          <RotateCcw className="mt-0.5 h-4 w-4 text-[var(--color-warning)] shrink-0" />
          <div>
            <p className="font-medium">{prompt}</p>
            {plan && <p className="mt-1 text-[var(--color-muted-foreground)]">Plan: {plan}</p>}
            {exploredFiles.length > 0 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {exploredFiles.map((f) => (
                  <Badge key={f} variant="outline" className="font-mono text-[9px]">
                    {f}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>

        <Textarea
          className="h-16 text-xs"
          placeholder="Refine your instruction (e.g. 'also check the methodology section for clarity')..."
          value={refinedQuery}
          onChange={(e) => setRefinedQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (refinedQuery.trim()) {
                handleRespond(refinedQuery.trim(), {
                  action: "refine",
                  refined_query: refinedQuery.trim(),
                });
              }
            }
          }}
          disabled={respondMut.isPending}
        />

        <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-[10px]"
            onClick={() =>
              handleRespond("accept", { action: "accept", refined_query: "" })
            }
            disabled={respondMut.isPending}
          >
            <Check className="mr-1 h-3 w-3" />
            Accept (no changes needed)
          </Button>
          <Button
            size="sm"
            className="h-6 text-[10px]"
            onClick={() => {
              if (refinedQuery.trim()) {
                handleRespond(refinedQuery.trim(), {
                  action: "refine",
                  refined_query: refinedQuery.trim(),
                });
              }
            }}
            disabled={respondMut.isPending || !refinedQuery.trim()}
          >
            <Send className="mr-1 h-3 w-3" />
            {respondMut.isPending ? "Submitting..." : "Refine & retry"}
          </Button>
        </div>
      </div>
    );
  }

  // ---- review_changes checkpoint ------------------------------------------
  if (checkpoint === "review_changes") {
    return (
      <div className="space-y-3 rounded border border-[var(--color-border)] p-3 text-xs">
        <div className="flex items-start gap-2">
          <RotateCcw className="mt-0.5 h-4 w-4 text-[var(--color-primary)] shrink-0" />
          <div>
            <p className="font-medium">{prompt}</p>
            {plan && <p className="mt-1 text-[var(--color-muted-foreground)]">{plan}</p>}
          </div>
        </div>

        <div className="space-y-2 max-h-80 overflow-y-auto">
          {changes.map((ch, i) => {
            const isRejected = rejectedFiles.has(ch.path);
            return (
              <div
                key={i}
                className={`rounded border ${isRejected ? "border-[var(--color-destructive)]/30 opacity-60" : "border-[var(--color-border)]"}`}
              >
                <div className="flex items-center justify-between p-1.5">
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="font-mono text-[9px]">
                      {ch.path}
                    </Badge>
                    {ch.summary && (
                      <span className="text-[10px] text-[var(--color-muted-foreground)]">
                        {ch.summary}
                      </span>
                    )}
                  </div>
                  <button
                    type="button"
                    className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors ${
                      isRejected
                        ? "bg-[var(--color-destructive)]/10 text-[var(--color-destructive)]"
                        : "bg-[var(--color-success)]/10 text-[var(--color-success)]"
                    }`}
                    onClick={() => toggleReject(ch.path)}
                  >
                    {isRejected ? (
                      <>
                        <X className="h-3 w-3" /> Rejected
                      </>
                    ) : (
                      <>
                        <Check className="h-3 w-3" /> Accepted
                      </>
                    )}
                  </button>
                </div>
                {!isRejected && (
                  <div className="border-t border-[var(--color-border)]">
                    <DiffEditor
                      height="160px"
                      original={ch.before || ""}
                      modified={ch.after || ""}
                      language={ch.path.endsWith(".tex") ? "latex" : "markdown"}
                      theme={monacoTheme}
                      options={{
                        readOnly: true,
                        renderSideBySide: false,
                        minimap: { enabled: false },
                        scrollBeyondLastLine: false,
                        fontSize: 11,
                        wordWrap: "on",
                      }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        <div className="flex items-center justify-end gap-2">
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-[10px] text-[var(--color-destructive)]"
            onClick={() =>
              handleRespond("Reject all changes", { action: "reject_all" })
            }
            disabled={respondMut.isPending}
          >
            <X className="mr-1 h-3 w-3" />
            Reject all
          </Button>
          <Button
            size="sm"
            variant="outline"
            className="h-6 text-[10px]"
            onClick={() => {
              const rejected = [...rejectedFiles];
              handleRespond(
                `Apply ${String(changes.length - rejected.length)} of ${String(changes.length)} changes`,
                { action: "accept_some", rejected_files: rejected },
              );
            }}
            disabled={respondMut.isPending}
          >
            <Check className="mr-1 h-3 w-3" />
            Apply accepted ({changes.length - rejectedFiles.size})
          </Button>
          <Button
            size="sm"
            className="h-6 text-[10px]"
            onClick={() =>
              handleRespond("Apply all changes", { action: "accept_all" })
            }
            disabled={respondMut.isPending}
          >
            <Check className="mr-1 h-3 w-3" />
            Accept all
          </Button>
        </div>
      </div>
    );
  }

  // ---- generic / fallback -------------------------------------------------
  return (
    <div className="space-y-2 rounded border border-[var(--color-border)] p-3 text-xs">
      <p>{prompt}</p>
      <div className="flex items-center gap-2">
        <Textarea
          className="h-14 flex-1 text-xs"
          placeholder="Type your response..."
          value={refinedQuery}
          onChange={(e) => setRefinedQuery(e.target.value)}
          disabled={respondMut.isPending}
        />
        <Button
          size="sm"
          className="h-8 text-[10px]"
          onClick={() => handleRespond(refinedQuery, {})}
          disabled={respondMut.isPending || !refinedQuery.trim()}
        >
          <Send className="mr-1 h-3 w-3" />
          Send
        </Button>
      </div>
    </div>
  );
}
