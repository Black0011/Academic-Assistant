/**
 * Planner DAG page (M8.2).
 *
 * Workflow:
 *   1. Operator describes the task in natural language ("Compile prompt").
 *   2. We hit `/api/planner/skills_for_compile` to show what's available
 *      to the host LLM compiler.
 *   3. POST `/api/planner/compile` -> returns a `PlanDAG`. The page renders
 *      the DAG (topo layers) and the underlying JSON in a Monaco editor
 *      where the operator can hand-edit.
 *   4. POST `/api/planner/validate` whenever the JSON changes — surface
 *      errors / warnings inline.
 *   5. POST `/api/planner/execute` -> backend enqueues a `dag` workflow
 *      task. We subscribe to its SSE stream and project node-level
 *      `task.stage_start` / `task.stage_end` events back onto the DAG.
 *
 * The page is intentionally a single-pane SPA — no routing per plan ID.
 * Plans are ephemeral artefacts of compilation; persistence is the
 * Tasks system's job.
 */
import Editor, { type OnChange } from "@monaco-editor/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  ChevronRight,
  CircleDot,
  ClipboardCheck,
  Layers,
  ListChecks,
  Loader2,
  Play,
  RefreshCcw,
  Wand2,
  Wrench,
  XCircle,
  Zap,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { EmptyState } from "@/components/common/EmptyState";
import { PageHeader } from "@/components/common/PageHeader";
import { TaskError } from "@/components/common/TaskError";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Label } from "@/components/ui/Label";
import { useTaskStream } from "@/hooks/useTaskStream";
import { ApiError } from "@/lib/api";
import { cn } from "@/lib/cn";
import { plannerApi } from "@/lib/planner";
import type {
  CompilePlanInput,
  ExecutePlanInput,
  NodeStatus,
  PlanDAG,
  PlanNode,
  StreamEvent,
  ValidatePlanResponse,
} from "@/types/api";

const STATUS_VARIANT: Record<NodeStatus, "neutral" | "warning" | "success" | "destructive" | "primary"> = {
  pending: "neutral",
  running: "warning",
  succeeded: "success",
  failed: "destructive",
  skipped: "neutral",
};

const KIND_ICON = {
  llm: Brain,
  tool: Wrench,
  skill: Wand2,
  "memory.read": Layers,
  "memory.write": Layers,
} as const;

function isDarkMode(): boolean {
  if (typeof window === "undefined") return false;
  return document.documentElement.classList.contains("dark");
}

/**
 * Group nodes into topological layers. Nodes with all dependencies in
 * earlier layers go into the next layer. The DAG executor uses the same
 * algorithm; we replicate it here for read-only visualisation.
 */
function topoLayers(nodes: PlanNode[]): PlanNode[][] {
  const byId = new Map<string, PlanNode>(nodes.map((n) => [n.id, n]));
  const placed = new Set<string>();
  const layers: PlanNode[][] = [];
  let safety = nodes.length + 5;
  while (placed.size < nodes.length && safety-- > 0) {
    const layer = nodes.filter(
      (n) =>
        !placed.has(n.id) &&
        n.depends_on.every((d) => !byId.has(d) || placed.has(d)),
    );
    if (!layer.length) {
      // Cycle or missing dep — fall back to one big layer with what's left.
      const rest = nodes.filter((n) => !placed.has(n.id));
      layers.push(rest);
      rest.forEach((n) => placed.add(n.id));
      break;
    }
    layers.push(layer);
    layer.forEach((n) => placed.add(n.id));
  }
  return layers;
}

interface NodeRuntime {
  status: NodeStatus;
  attempts: number;
  duration_ms: number | null;
  error: string | null;
}

/**
 * Project SSE events emitted by the `dag` workflow into per-node runtime
 * state. The executor emits `task.stage_start` / `task.stage_end` with
 * `data.stage = "node:<id>"` and `data.{node_id, status, attempts,
 * duration_ms, error}` on the end event.
 */
function projectEvents(events: StreamEvent[], plan: PlanDAG | null): Record<string, NodeRuntime> {
  const out: Record<string, NodeRuntime> = {};
  if (!plan) return out;
  for (const node of plan.nodes) {
    out[node.id] = {
      status: "pending",
      attempts: 0,
      duration_ms: null,
      error: null,
    };
  }
  for (const ev of events) {
    const data = ev.data ?? {};
    const stage =
      typeof data.stage === "string" ? data.stage : undefined;
    const nodeId =
      (typeof data.node_id === "string" && data.node_id) ||
      (stage && stage.startsWith("node:") ? stage.slice(5) : null);
    if (!nodeId) continue;
    const cur = out[nodeId];
    if (!cur) continue;
    if (ev.type === "task.stage_start") {
      cur.status = "running";
    } else if (ev.type === "task.stage_end") {
      const status = (data.status as NodeStatus | undefined) ?? "succeeded";
      cur.status = status;
      cur.attempts = Number(data.attempts ?? cur.attempts);
      cur.duration_ms = Number(data.duration_ms ?? 0);
      const err = data.error;
      cur.error = typeof err === "string" && err ? err : null;
    } else if (ev.type === "task.retry") {
      cur.attempts = Number(data.attempt ?? cur.attempts);
    }
  }
  return out;
}

const SAMPLE_QUERIES = [
  "Survey recent advances in retrieval-augmented generation and summarise them",
  "Write a related-work section for a paper on chain-of-thought prompting",
  "Critique my draft and suggest 3 concrete revisions",
];

export function PlannerPage() {
  const { t } = useTranslation();
  const dark = isDarkMode();

  const [query, setQuery] = useState("");
  const [domain, setDomain] = useState("research");
  const [hints, setHints] = useState("");
  const [maxNodes, setMaxNodes] = useState<number>(15);
  const [onlySkills, setOnlySkills] = useState<string[]>([]);
  const [onlyTools, setOnlyTools] = useState<string[]>([]);
  const [planJson, setPlanJson] = useState<string>("");
  const [plan, setPlan] = useState<PlanDAG | null>(null);
  const [validation, setValidation] = useState<ValidatePlanResponse | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [tab, setTab] = useState<"graph" | "json">("graph");

  const skills = useQuery({
    queryKey: ["planner", "skills_for_compile"],
    queryFn: () => plannerApi.skillsForCompile(),
  });

  const compileMut = useMutation({
    mutationFn: async () => {
      const payload: CompilePlanInput = {
        query: query.trim(),
        domain: domain.trim() || undefined,
        hints: hints
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        max_nodes: Math.max(1, Math.min(100, Number(maxNodes) || 15)),
        only_skills: onlySkills.length ? onlySkills : null,
        only_tools: onlyTools.length ? onlyTools : null,
      };
      if (!payload.query) throw new Error("query is required");
      return plannerApi.compile(payload);
    },
    onSuccess: (p) => {
      setPlan(p);
      setPlanJson(JSON.stringify(p, null, 2));
      setValidation(null);
      setTaskId(null);
      toast.success(`Compiled ${p.nodes.length} nodes`);
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  const validateMut = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error("no plan");
      return plannerApi.validate(plan);
    },
    onSuccess: (resp) => {
      setValidation(resp);
      if (resp.ok) toast.success("Plan looks valid");
      else toast.warning(`Plan has ${resp.errors.length} error(s)`);
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  const executeMut = useMutation({
    mutationFn: () => {
      if (!plan) throw new Error("no plan");
      const payload: ExecutePlanInput = { plan };
      return plannerApi.execute(payload);
    },
    onSuccess: (resp) => {
      setTaskId(resp.task_id);
      toast.success(`Task ${resp.task_id} enqueued`);
    },
    onError: (err) => {
      const detail = err instanceof ApiError ? String(err.body ?? err.message) : String(err);
      toast.error(detail);
    },
  });

  // Live-edit JSON -> plan.
  const onJsonChange: OnChange = (v) => {
    setPlanJson(v ?? "");
    if (!v) {
      setPlan(null);
      return;
    }
    try {
      const parsed = JSON.parse(v) as PlanDAG;
      if (Array.isArray(parsed.nodes)) {
        setPlan(parsed);
      }
    } catch {
      // Invalid JSON — keep last good plan but null-out validation.
      setValidation(null);
    }
  };

  // Re-validate on plan change (debounced via an effect).
  useEffect(() => {
    if (!plan) return;
    const handle = setTimeout(() => {
      void validateMut.mutateAsync().catch(() => undefined);
    }, 400);
    return () => clearTimeout(handle);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan?.plan_id, planJson]);

  const stream = useTaskStream(taskId);
  const runtime = useMemo(
    () => projectEvents(stream.events, plan),
    [stream.events, plan],
  );

  const layers = useMemo(() => (plan ? topoLayers(plan.nodes) : []), [plan]);

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title={t("planner.title")}
        description={t("planner.description")}
        actions={
          <Button
            variant="outline"
            size="sm"
            onClick={() => skills.refetch()}
            disabled={skills.isFetching}
          >
            <RefreshCcw className={cn("h-4 w-4", skills.isFetching && "animate-spin")} />
            Refresh capabilities
          </Button>
        }
      />

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden lg:grid-cols-[20rem_1fr]">
        <CompileForm
          query={query}
          setQuery={setQuery}
          domain={domain}
          setDomain={setDomain}
          hints={hints}
          setHints={setHints}
          maxNodes={maxNodes}
          setMaxNodes={setMaxNodes}
          onlySkills={onlySkills}
          setOnlySkills={setOnlySkills}
          onlyTools={onlyTools}
          setOnlyTools={setOnlyTools}
          availableSkills={skills.data?.skills ?? []}
          availableTools={skills.data?.tools ?? []}
          compiling={compileMut.isPending}
          onCompile={() => compileMut.mutate()}
        />

        <div className="flex flex-col overflow-hidden rounded-lg border bg-[var(--color-card)]">
          {!plan ? (
            <EmptyState
              icon={Brain}
              title="No plan yet"
              description="Describe a goal on the left and hit Compile. The host LLM will turn it into a DAG you can review and execute."
              action={
                <div className="flex flex-wrap justify-center gap-1">
                  {SAMPLE_QUERIES.map((q) => (
                    <button
                      key={q}
                      type="button"
                      onClick={() => setQuery(q)}
                      className="rounded-md border px-2 py-1 text-[11px] hover:bg-[var(--color-accent)]/40"
                    >
                      {q}
                    </button>
                  ))}
                </div>
              }
            />
          ) : (
            <PlanWorkspace
              plan={plan}
              planJson={planJson}
              onJsonChange={onJsonChange}
              tab={tab}
              setTab={setTab}
              dark={dark}
              layers={layers}
              runtime={runtime}
              validation={validation}
              validating={validateMut.isPending}
              onValidate={() => validateMut.mutate()}
              executing={executeMut.isPending}
              onExecute={() => executeMut.mutate()}
              taskId={taskId}
              streamStatus={stream.status}
              streamError={stream.error}
            />
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Left rail: compile form
// ---------------------------------------------------------------------------

interface CompileFormProps {
  query: string;
  setQuery: (v: string) => void;
  domain: string;
  setDomain: (v: string) => void;
  hints: string;
  setHints: (v: string) => void;
  maxNodes: number;
  setMaxNodes: (v: number) => void;
  onlySkills: string[];
  setOnlySkills: (v: string[]) => void;
  onlyTools: string[];
  setOnlyTools: (v: string[]) => void;
  availableSkills: { name: string; description: string }[];
  availableTools: { name: string; description: string }[];
  compiling: boolean;
  onCompile: () => void;
}

function CompileForm(props: CompileFormProps) {
  function toggle(arr: string[], v: string, setter: (next: string[]) => void) {
    if (arr.includes(v)) setter(arr.filter((x) => x !== v));
    else setter([...arr, v]);
  }

  return (
    <div className="flex flex-col gap-3 overflow-y-auto rounded-lg border bg-[var(--color-card)] p-3">
      <div>
        <Label htmlFor="planner-query">Goal</Label>
        <textarea
          id="planner-query"
          value={props.query}
          onChange={(e) => props.setQuery(e.target.value)}
          rows={3}
          className="block w-full rounded-md border bg-[var(--color-background)] px-3 py-2 text-sm"
          placeholder="What do you want the agent to do?"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <Label htmlFor="planner-domain">Domain</Label>
          <Input
            id="planner-domain"
            value={props.domain}
            onChange={(e) => props.setDomain(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="planner-max">Max nodes</Label>
          <Input
            id="planner-max"
            type="number"
            min={1}
            max={100}
            value={props.maxNodes}
            onChange={(e) => props.setMaxNodes(Number(e.target.value))}
          />
        </div>
      </div>
      <div>
        <Label htmlFor="planner-hints">Hints (one per line)</Label>
        <textarea
          id="planner-hints"
          value={props.hints}
          onChange={(e) => props.setHints(e.target.value)}
          rows={2}
          className="block w-full rounded-md border bg-[var(--color-background)] px-3 py-2 text-sm"
          placeholder="Stick to recent literature; cite at most 5 papers"
        />
      </div>

      <div>
        <Label className="mb-1 flex items-center gap-2">
          <Wand2 className="h-3.5 w-3.5" /> Skills
        </Label>
        <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto rounded-md border p-2">
          {props.availableSkills.length === 0 ? (
            <span className="text-[11px] text-[var(--color-muted-foreground)]">
              (no skills installed)
            </span>
          ) : (
            props.availableSkills.map((s) => (
              <button
                key={s.name}
                type="button"
                title={s.description}
                onClick={() =>
                  toggle(props.onlySkills, s.name, props.setOnlySkills)
                }
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                  props.onlySkills.includes(s.name)
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)]/10"
                    : "border-[var(--color-border)] hover:bg-[var(--color-accent)]/40",
                )}
              >
                {s.name}
              </button>
            ))
          )}
        </div>
      </div>

      <div>
        <Label className="mb-1 flex items-center gap-2">
          <Wrench className="h-3.5 w-3.5" /> Tools
        </Label>
        <div className="flex max-h-32 flex-wrap gap-1 overflow-y-auto rounded-md border p-2">
          {props.availableTools.length === 0 ? (
            <span className="text-[11px] text-[var(--color-muted-foreground)]">
              (no tools registered)
            </span>
          ) : (
            props.availableTools.map((t) => (
              <button
                key={t.name}
                type="button"
                title={t.description}
                onClick={() =>
                  toggle(props.onlyTools, t.name, props.setOnlyTools)
                }
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px] transition-colors",
                  props.onlyTools.includes(t.name)
                    ? "border-[var(--color-primary)] bg-[var(--color-primary)]/10"
                    : "border-[var(--color-border)] hover:bg-[var(--color-accent)]/40",
                )}
              >
                {t.name}
              </button>
            ))
          )}
        </div>
        <p className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
          Empty = let the LLM choose anything.
        </p>
      </div>

      <Button
        onClick={props.onCompile}
        disabled={!props.query.trim() || props.compiling}
      >
        {props.compiling ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Wand2 className="h-4 w-4" />
        )}
        Compile DAG
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Right pane: graph + JSON tabs + validation + execute
// ---------------------------------------------------------------------------

interface PlanWorkspaceProps {
  plan: PlanDAG;
  planJson: string;
  onJsonChange: OnChange;
  tab: "graph" | "json";
  setTab: (t: "graph" | "json") => void;
  dark: boolean;
  layers: PlanNode[][];
  runtime: Record<string, NodeRuntime>;
  validation: ValidatePlanResponse | null;
  validating: boolean;
  onValidate: () => void;
  executing: boolean;
  onExecute: () => void;
  taskId: string | null;
  streamStatus: string;
  streamError: string | null;
}

function PlanWorkspace(props: PlanWorkspaceProps) {
  const validIcon =
    props.validation == null ? null : props.validation.ok ? (
      <CheckCircle2 className="h-4 w-4 text-[var(--color-success)]" />
    ) : (
      <XCircle className="h-4 w-4 text-[var(--color-destructive)]" />
    );

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b p-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm">
            <Badge variant="primary">{props.plan.plan_id}</Badge>
            <span className="text-[var(--color-muted-foreground)]">
              · {props.plan.nodes.length} nodes · domain {props.plan.domain}
              · provider {props.plan.llm_provider || "(none)"}
            </span>
          </div>
          {props.plan.rationale && (
            <p className="mt-1 max-w-2xl text-xs text-[var(--color-muted-foreground)]">
              {props.plan.rationale}
            </p>
          )}
        </div>
        <div className="flex items-center gap-2">
          <div className="rounded-md border p-0.5 text-xs">
            <button
              type="button"
              onClick={() => props.setTab("graph")}
              className={cn(
                "rounded-md px-2 py-1",
                props.tab === "graph" && "bg-[var(--color-accent)]",
              )}
            >
              Graph
            </button>
            <button
              type="button"
              onClick={() => props.setTab("json")}
              className={cn(
                "rounded-md px-2 py-1",
                props.tab === "json" && "bg-[var(--color-accent)]",
              )}
            >
              JSON
            </button>
          </div>
          <Button
            size="sm"
            variant="outline"
            onClick={props.onValidate}
            disabled={props.validating}
          >
            {props.validating ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <ClipboardCheck className="h-4 w-4" />
            )}
            Validate
            {validIcon}
          </Button>
          <Button
            size="sm"
            onClick={props.onExecute}
            disabled={
              props.executing ||
              (props.validation != null && !props.validation.ok)
            }
          >
            {props.executing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Play className="h-4 w-4" />
            )}
            Execute
          </Button>
        </div>
      </div>

      <ValidationBanner v={props.validation} />

      <div className="grid flex-1 grid-cols-1 gap-4 overflow-hidden p-4 lg:grid-cols-[2fr_1fr]">
        <div className="flex min-h-0 flex-col overflow-hidden rounded-md border bg-[var(--color-background)]">
          {props.tab === "graph" ? (
            <DagGraph layers={props.layers} runtime={props.runtime} />
          ) : (
            <Editor
              height="100%"
              language="json"
              value={props.planJson}
              theme={props.dark ? "vs-dark" : "vs"}
              onChange={props.onJsonChange}
              options={{
                minimap: { enabled: false },
                fontSize: 12,
                scrollBeyondLastLine: false,
                wordWrap: "on",
              }}
            />
          )}
        </div>
        <ExecutionPanel
          taskId={props.taskId}
          streamStatus={props.streamStatus}
          streamError={props.streamError}
          runtime={props.runtime}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// DAG graph (topo-layered, runtime-aware)
// ---------------------------------------------------------------------------

interface DagGraphProps {
  layers: PlanNode[][];
  runtime: Record<string, NodeRuntime>;
}

function DagGraph({ layers, runtime }: DagGraphProps) {
  if (!layers.length) {
    return (
      <div className="flex flex-1 items-center justify-center text-sm text-[var(--color-muted-foreground)]">
        Plan is empty.
      </div>
    );
  }
  return (
    <div className="flex flex-1 flex-row gap-4 overflow-x-auto p-4">
      {layers.map((layer, layerIdx) => (
        <div key={layerIdx} className="flex min-w-56 flex-col gap-3">
          <div className="text-[11px] font-medium uppercase text-[var(--color-muted-foreground)]">
            Layer {layerIdx + 1}
          </div>
          {layer.map((node) => (
            <NodeCard key={node.id} node={node} rt={runtime[node.id]} />
          ))}
          {layerIdx < layers.length - 1 && (
            <div className="hidden lg:flex flex-1 items-center justify-end pr-1 text-[var(--color-muted-foreground)]">
              <ChevronRight className="h-4 w-4" />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

interface NodeCardProps {
  node: PlanNode;
  rt: NodeRuntime | undefined;
}

function NodeCard({ node, rt }: NodeCardProps) {
  const Icon = KIND_ICON[node.kind] ?? CircleDot;
  const status = rt?.status ?? "pending";
  return (
    <div
      className={cn(
        "rounded-md border p-3 shadow-sm transition-colors",
        status === "running" && "border-[var(--color-warning)]/60",
        status === "succeeded" && "border-[var(--color-success)]/60",
        status === "failed" && "border-[var(--color-destructive)]/60",
        status === "skipped" && "opacity-60",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Icon className="h-4 w-4 shrink-0" />
          <span className="truncate text-sm font-medium" title={node.id}>
            {node.name || node.id}
          </span>
        </div>
        <Badge variant={STATUS_VARIANT[status]}>{status}</Badge>
      </div>
      <div className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
        <span className="rounded bg-[var(--color-muted)] px-1 py-0.5 font-mono text-[10px]">
          {node.kind}
        </span>
        {" · id "}<span className="font-mono">{node.id}</span>
      </div>
      {node.description && (
        <p className="mt-1 line-clamp-2 text-xs">{node.description}</p>
      )}
      {node.depends_on.length > 0 && (
        <p className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
          deps: {node.depends_on.join(", ")}
        </p>
      )}
      {rt && rt.duration_ms != null && rt.status !== "pending" && (
        <p className="mt-1 text-[11px] text-[var(--color-muted-foreground)]">
          {rt.duration_ms} ms · attempts {rt.attempts}
        </p>
      )}
      {rt?.error && (
        <p className="mt-1 line-clamp-3 text-[11px] text-[var(--color-destructive)]">
          {rt.error}
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Validation banner + execution panel
// ---------------------------------------------------------------------------

function ValidationBanner({ v }: { v: ValidatePlanResponse | null }) {
  if (!v) return null;
  if (v.ok && !v.warnings.length) return null;
  return (
    <div
      className={cn(
        "border-b px-4 py-2 text-xs",
        v.ok
          ? "bg-[var(--color-warning)]/10 text-[var(--color-warning)]"
          : "bg-[var(--color-destructive)]/10 text-[var(--color-destructive)]",
      )}
    >
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
        <div className="space-y-0.5">
          {v.errors.map((e, i) => (
            <div key={`e${i}`}>error: {e}</div>
          ))}
          {v.warnings.map((w, i) => (
            <div key={`w${i}`}>warn: {w}</div>
          ))}
        </div>
      </div>
    </div>
  );
}

interface ExecutionPanelProps {
  taskId: string | null;
  streamStatus: string;
  streamError: string | null;
  runtime: Record<string, NodeRuntime>;
}

function ExecutionPanel({
  taskId,
  streamStatus,
  streamError,
  runtime,
}: ExecutionPanelProps) {
  const counts = useMemo(() => {
    const c = { pending: 0, running: 0, succeeded: 0, failed: 0, skipped: 0 };
    for (const rt of Object.values(runtime)) c[rt.status]++;
    return c;
  }, [runtime]);

  return (
    <Card className="flex min-h-0 flex-col overflow-hidden">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <ListChecks className="h-4 w-4" />
          Execution
        </CardTitle>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">
        {!taskId ? (
          <p className="text-xs text-[var(--color-muted-foreground)]">
            Hit <span className="font-medium">Execute</span> to enqueue this DAG
            on the task system. SSE events will show node status here in
            real-time.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant="primary">{taskId}</Badge>
              <Badge
                variant={
                  streamStatus === "ok" || streamStatus === "succeeded"
                    ? "success"
                    : streamStatus === "error"
                      ? "destructive"
                      : "warning"
                }
              >
                {streamStatus}
              </Badge>
            </div>
            {streamError && <TaskError error={streamError} />}
            <div className="grid grid-cols-2 gap-2 text-[11px]">
              <Stat label="pending" value={counts.pending} icon={CircleDot} />
              <Stat label="running" value={counts.running} icon={Zap} />
              <Stat label="ok" value={counts.succeeded} icon={CheckCircle2} />
              <Stat label="failed" value={counts.failed} icon={XCircle} />
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: number;
  icon: typeof CircleDot;
}) {
  return (
    <div className="flex items-center gap-2 rounded-md border px-2 py-1">
      <Icon className="h-3.5 w-3.5 text-[var(--color-muted-foreground)]" />
      <span className="font-medium">{value}</span>
      <span className="text-[var(--color-muted-foreground)]">{label}</span>
    </div>
  );
}
