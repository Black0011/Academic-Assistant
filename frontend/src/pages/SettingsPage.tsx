import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Cpu,
  FileCode2,
  Hammer,
  Loader2,
  Save,
  Sparkles,
  Workflow as WorkflowIcon,
} from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { PageHeader } from "@/components/common/PageHeader";
import { LLMProviderForm } from "@/components/settings/LLMProviderForm";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Textarea } from "@/components/ui/Input";
import { Skeleton } from "@/components/ui/Skeleton";
import { api } from "@/lib/api";
import type { ToolInfo, VersionInfo, WorkflowInfo } from "@/types/api";

export function SettingsPage() {
  const { t } = useTranslation();
  const versionQ = useQuery({
    queryKey: ["version"],
    queryFn: () => api<VersionInfo>("/api/version"),
  });
  const toolsQ = useQuery({ queryKey: ["tools"], queryFn: () => api<ToolInfo[]>("/api/tools") });
  const workflowsQ = useQuery({
    queryKey: ["workflows"],
    queryFn: () => api<WorkflowInfo[]>("/api/workflows"),
  });

  return (
    <div className="space-y-6">
      <PageHeader title={t("settings.title")} description={t("settings.description")} />

      {/* The whole point of Phase C: editable provider config first. */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Sparkles className="h-4 w-4" /> {t("settings.llm.title")}
          </CardTitle>
          <p className="text-xs text-[var(--color-muted-foreground)]">
            {t("settings.llm.description")}
          </p>
        </CardHeader>
        <CardContent>
          <LLMProviderForm />
        </CardContent>
      </Card>

      {/* Agent Rules — editable AGENT.md (like Claude Code's CLAUDE.md) */}
      <AgentRulesCard />

      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Cpu className="h-4 w-4" /> {t("settings.runtime")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            {versionQ.isLoading && <Skeleton className="h-32 w-full" />}
            {versionQ.data && (
              <>
                <Row k={t("settings.fields.version")} v={versionQ.data.version} mono />
                <Row k={t("settings.fields.llmProvider")} v={versionQ.data.llm_provider ?? "—"} />
                <Row
                  k={t("settings.fields.memoryVector")}
                  v={versionQ.data.memory.vector ?? "—"}
                  mono
                />
                <Row
                  k={t("settings.fields.memoryKnowledge")}
                  v={versionQ.data.memory.knowledge ?? "—"}
                  mono
                />
                <Row
                  k={t("settings.fields.memoryHeuristic")}
                  v={versionQ.data.memory.heuristic ?? "—"}
                  mono
                />
                <Row
                  k={t("settings.fields.memoryEpisodic")}
                  v={versionQ.data.memory.episodic ?? "—"}
                  mono
                />
                <Row
                  k={t("settings.fields.memorySession")}
                  v={versionQ.data.memory.session ?? "—"}
                  mono
                />
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCode2 className="h-4 w-4" /> {t("settings.frontendBuild")}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2 text-sm">
            <Row k={t("settings.fields.viteMode")} v={import.meta.env.MODE} mono />
            <Row
              k={t("settings.fields.apiBase")}
              v={import.meta.env.VITE_API_BASE || "(same-origin)"}
              mono
            />
            <Row k={t("settings.fields.react")} v="19" mono />
            <Row k={t("settings.fields.tailwind")} v="v4" mono />
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Hammer className="h-4 w-4" /> {t("settings.registeredTools")}
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {toolsQ.isLoading && <Skeleton className="h-20 w-full" />}
          {toolsQ.data?.map((tool) => (
            <div
              key={tool.name}
              className="rounded-md border bg-[var(--color-background)] p-3 text-xs"
            >
              <div className="font-mono text-sm">{tool.name}</div>
              {tool.description && (
                <div className="mt-1 text-[var(--color-muted-foreground)]">{tool.description}</div>
              )}
              {tool.capabilities && tool.capabilities.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {tool.capabilities.map((c) => (
                    <Badge key={c} variant="outline">
                      {c}
                    </Badge>
                  ))}
                </div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <WorkflowIcon className="h-4 w-4" /> {t("settings.workflows")}
          </CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {workflowsQ.data?.map((w) => (
            <div
              key={w.name}
              className="rounded-md border bg-[var(--color-background)] p-3 text-xs"
            >
              <div className="font-mono text-sm">{w.name}</div>
              {w.description && (
                <div className="mt-1 text-[var(--color-muted-foreground)]">{w.description}</div>
              )}
            </div>
          ))}
        </CardContent>
      </Card>
    </div>
  );
}

// ── Agent Rules Editor ──────────────────────────────────────────

interface AgentRules {
  content: string;
  path: string;
}

function AgentRulesCard() {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState("");

  const rulesQ = useQuery({
    queryKey: ["agent-rules"],
    queryFn: () => api<AgentRules>("/api/settings/agent"),
  });

  // Init draft from server on first load
  const [initialized, setInitialized] = useState(false);
  if (rulesQ.data && !initialized) {
    setDraft(rulesQ.data.content);
    setInitialized(true);
  }

  const saveMut = useMutation({
    mutationFn: (content: string) =>
      api<AgentRules>("/api/settings/agent", {
        method: "PUT",
        json: { content },
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(["agent-rules"], data);
      toast.success("Agent rules saved. Effective on next conversation turn.");
    },
    onError: (err: unknown) => {
      toast.error(`Save failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });

  const dirty = draft !== (rulesQ.data?.content ?? "");

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bot className="h-4 w-4" /> Agent System Prompt (presets/chat.md)
        </CardTitle>
        <p className="text-xs text-[var(--color-muted-foreground)]">
          This is the system prompt loaded at the start of every chat conversation.
          Edit it to customize the agent's behavior, tool priorities, and output
          style. Changes take effect on the next conversation turn.
          {rulesQ.data?.path && (
            <span className="ml-2 font-mono text-[10px] opacity-60">
              {rulesQ.data.path}
            </span>
          )}
        </p>
      </CardHeader>
      <CardContent className="space-y-3">
        {rulesQ.isLoading ? (
          <Skeleton className="h-48 w-full" />
        ) : (
          <>
            <Textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={18}
              className="font-mono text-xs leading-relaxed"
              placeholder="# Agent Rules&#10;&#10;You are an academic assistant..."
            />
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-[var(--color-muted-foreground)]">
                Markdown format. Use headings, lists, and bold for structure.
              </span>
              <Button
                type="button"
                size="sm"
                disabled={!dirty || saveMut.isPending}
                onClick={() => saveMut.mutate(draft)}
              >
                {saveMut.isPending ? (
                  <Loader2 className="mr-1 h-3 w-3 animate-spin" />
                ) : (
                  <Save className="mr-1 h-3 w-3" />
                )}
                {saveMut.isPending ? "Saving…" : "Save Rules"}
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

// ── Helpers ─────────────────────────────────────────────────────

function Row({ k, v, mono }: { k: string; v: string; mono?: boolean }) {
  return (
    <div className="flex items-baseline justify-between gap-2 border-b last:border-b-0 last:pb-0 pb-1.5">
      <span className="text-[var(--color-muted-foreground)]">{k}</span>
      <span className={mono ? "font-mono text-xs" : "text-sm"}>{v}</span>
    </div>
  );
}
