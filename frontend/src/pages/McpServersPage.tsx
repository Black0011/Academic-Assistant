/**
 * MCP servers page (M-MCP, P2.5).
 *
 * Read-only operator view onto the MCP layer:
 *
 *   - Top: feature flag + config path so it's obvious whether MCP is on.
 *   - Left: list of servers from `AAF_MCP_CONFIG`, with connection state
 *     and tool count per row.  A red badge surfaces the connect error
 *     when one is recorded.
 *   - Right: per-server tool catalogue (description + JSON schema) so
 *     the operator can sanity-check what the LLM will see.
 *
 * There is no mutate UI in v1 — the YAML file is the source of truth
 * and a backend restart is the supported way to apply changes (see
 * PLAN.md §10.8.4).  Hot-reload is intentionally postponed.
 */
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Plug, Server } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Skeleton } from "@/components/ui/Skeleton";
import { cn } from "@/lib/cn";
import { mcpApi } from "@/lib/mcp";
import type { McpServerStatus, McpToolInfo } from "@/types/api";

export function McpServersPage() {
  const { t } = useTranslation();
  const serversQ = useQuery({
    queryKey: ["mcp", "servers"],
    queryFn: () => mcpApi.servers(),
    refetchInterval: 30_000,
  });

  const servers: McpServerStatus[] = serversQ.data?.servers ?? [];
  const [selected, setSelected] = useState<string | null>(null);

  // Auto-select the first server when the list arrives.
  useEffect(() => {
    if (selected !== null) return;
    if (servers.length === 0) return;
    setSelected(servers[0].name);
  }, [servers, selected]);

  return (
    <div className="space-y-4">
      <PageHeader
        title={t("mcp.title")}
        description={t("mcp.description")}
        actions={
          <FlagPill
            enabled={serversQ.data?.enabled ?? false}
            configPath={serversQ.data?.config_path ?? ""}
          />
        }
      />

      {serversQ.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-[18rem_1fr]">
          <Skeleton className="h-72 w-full" />
          <Skeleton className="h-72 w-full" />
        </div>
      ) : serversQ.isError ? (
        <Card>
          <CardContent className="flex items-center gap-2 p-6 text-sm text-[var(--color-destructive)]">
            <AlertTriangle className="h-4 w-4" />
            Failed to load MCP status: {(serversQ.error as Error).message}
          </CardContent>
        </Card>
      ) : servers.length === 0 ? (
        <EmptyState
          icon={Plug}
          title={
            serversQ.data?.enabled === false
              ? "MCP is currently disabled"
              : "No MCP servers configured"
          }
          description={
            serversQ.data?.enabled === false
              ? "Set AAF_MCP_ENABLED=true in your .env, then point AAF_MCP_CONFIG at a YAML file. Template at config/mcp_servers.example.yaml."
              : "Add server entries to the YAML at the path above and restart the backend."
          }
        />
      ) : (
        <div className="grid gap-4 lg:grid-cols-[20rem_1fr]">
          <ServerList
            items={servers}
            selected={selected}
            onSelect={setSelected}
          />
          {selected ? (
            <ServerDetailPanel name={selected} />
          ) : (
            <EmptyState
              icon={Server}
              title="Pick a server"
              description="Select a server on the left to see the tools it contributes."
            />
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Header pill
// ---------------------------------------------------------------------------

function FlagPill({ enabled, configPath }: { enabled: boolean; configPath: string }) {
  return (
    <div className="flex items-center gap-2 text-[11px]">
      <Badge variant={enabled ? "success" : "outline"}>
        {enabled ? "MCP enabled" : "MCP disabled"}
      </Badge>
      {configPath && (
        <span className="font-mono text-[10px] text-[var(--color-muted-foreground)]">
          {configPath}
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// List
// ---------------------------------------------------------------------------

function ServerList({
  items,
  selected,
  onSelect,
}: {
  items: McpServerStatus[];
  selected: string | null;
  onSelect: (name: string) => void;
}) {
  return (
    <Card className="h-fit">
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-sm">
          <Server className="h-4 w-4" /> Configured
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-1.5">
        <ul className="space-y-1">
          {items.map((server) => (
            <li key={server.name}>
              <button
                type="button"
                onClick={() => onSelect(server.name)}
                className={cn(
                  "w-full rounded-md border px-3 py-2 text-left text-xs transition-colors",
                  selected === server.name
                    ? "border-[var(--color-primary)] bg-[var(--color-accent)]"
                    : "border-transparent hover:bg-[var(--color-accent)]/60",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="truncate font-semibold">{server.name}</span>
                  <ConnectionBadge connected={server.connected} />
                </div>
                <div className="mt-1 flex items-center gap-2 text-[10px] text-[var(--color-muted-foreground)]">
                  <span className="font-mono uppercase">{server.transport}</span>
                  <span>·</span>
                  <span>
                    {server.tools.length} tool{server.tools.length === 1 ? "" : "s"}
                  </span>
                </div>
                {server.error && (
                  <p className="mt-1 line-clamp-2 text-[10px] text-[var(--color-destructive)]">
                    {server.error}
                  </p>
                )}
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  );
}

function ConnectionBadge({ connected }: { connected: boolean }) {
  if (connected) {
    return (
      <Badge variant="success" className="gap-1">
        <CheckCircle2 className="h-3 w-3" /> connected
      </Badge>
    );
  }
  return (
    <Badge variant="destructive" className="gap-1">
      <AlertTriangle className="h-3 w-3" /> down
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Detail
// ---------------------------------------------------------------------------

function ServerDetailPanel({ name }: { name: string }) {
  const toolsQ = useQuery({
    queryKey: ["mcp", "tools", name],
    queryFn: () => mcpApi.tools(name),
  });

  return (
    <Card className="flex min-h-[24rem] flex-col">
      <CardHeader className="border-b">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle className="text-base">{name}</CardTitle>
          <span className="text-[11px] text-[var(--color-muted-foreground)]">
            {toolsQ.data ? `${toolsQ.data.tools.length} tools` : "—"}
          </span>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        {toolsQ.isLoading ? (
          <div className="space-y-2 p-4">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        ) : toolsQ.isError ? (
          <div className="flex items-center gap-2 p-4 text-sm text-[var(--color-destructive)]">
            <AlertTriangle className="h-4 w-4" />
            {(toolsQ.error as Error).message}
          </div>
        ) : toolsQ.data && toolsQ.data.tools.length > 0 ? (
          <ToolList tools={toolsQ.data.tools} />
        ) : (
          <EmptyState
            icon={Plug}
            title="No tools registered"
            description="The server connected but exposed nothing. Either the server is empty or your `allow` filter excluded everything."
          />
        )}
      </CardContent>
    </Card>
  );
}

function ToolList({ tools }: { tools: McpToolInfo[] }) {
  return (
    <ul className="divide-y">
      {tools.map((tool) => (
        <li key={tool.name} className="space-y-1.5 p-4">
          <div className="flex flex-wrap items-center gap-2">
            <code className="font-mono text-xs font-semibold">{tool.name}</code>
            {tool.requires_network && <Badge variant="outline">network</Badge>}
            {tool.requires_paid_api && <Badge variant="warning">paid</Badge>}
          </div>
          {tool.description && (
            <p className="text-xs text-[var(--color-muted-foreground)]">
              {tool.description}
            </p>
          )}
          {Object.keys(tool.parameters ?? {}).length > 0 && (
            <details className="group">
              <summary className="cursor-pointer text-[10px] uppercase tracking-wider text-[var(--color-muted-foreground)] group-open:mb-1">
                JSON schema
              </summary>
              <pre className="max-h-48 overflow-auto rounded bg-[var(--color-muted)]/40 p-2 font-mono text-[11px]">
                {JSON.stringify(tool.parameters, null, 2)}
              </pre>
            </details>
          )}
        </li>
      ))}
    </ul>
  );
}
