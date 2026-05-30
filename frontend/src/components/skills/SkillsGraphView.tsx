/**
 * Skills DAG graph view (P13.D, edge editor added in P14.F).
 *
 * Renders ``GET /api/skills/graph`` as an auto-laid-out, interactive
 * graph. Nodes are coloured by ``domain``; edges are coloured by
 * ``declared_by`` (green = both sides agree; gray = one-sided);
 * cycles are highlighted amber so the user can see + fix asymmetric
 * SKILL.md frontmatter.
 *
 * Why xyflow + dagre instead of a hand-rolled SVG layout?
 * --------------------------------------------------------
 * - xyflow gives pan / zoom / minimap / hit-testing for free; writing
 *   those by hand is hundreds of lines of error-prone pointer code.
 * - dagre is the de-facto Sugiyama implementation for the JS world.
 *
 * P14.F — drag-to-connect + click-to-delete edge edit
 * ---------------------------------------------------
 * The original design notes here said "no drag-to-create-edge" because
 * the SKILL.md body editor was the only mutation path and we didn't
 * want two parallel ways to do the same thing. P14.C lifts that
 * constraint by giving the backend a *dedicated* edge-only endpoint
 * (``POST /api/skills/{name}:edges``) that surgically rewrites
 * frontmatter without touching the body. Now the graph view IS the
 * canonical edge editor: drag from a node's right handle to another
 * node's left handle to add a downstream edge, or click an edge then
 * press Delete / Backspace (or click the trash button in its tooltip)
 * to remove it.
 *
 * Removing a "both"-declared edge requires TWO backend calls (one to
 * each end) — the backend deliberately doesn't auto-cascade so the UI
 * controls which side declares which. This component issues both calls
 * via the ``onRemoveEdge`` callback when ``declared_by === "both"``.
 */

import "@xyflow/react/dist/style.css";

import { useCallback, useMemo, useState, type CSSProperties } from "react";
import { useTranslation } from "react-i18next";
import {
  Background,
  BackgroundVariant,
  Controls,
  type Connection,
  type Edge,
  type EdgeMouseHandler,
  type EdgeChange,
  MarkerType,
  MiniMap,
  type Node,
  Position,
  ReactFlow,
} from "@xyflow/react";
import dagre from "dagre";

import type { SkillGraphEdge, SkillGraphNode, SkillGraphResponse } from "@/types/api";

// ---------------------------------------------------------------------------
// Style helpers — kept module-local because they're entirely visual and
// have no business leaking into the public API.
// ---------------------------------------------------------------------------

const NODE_W = 180;
const NODE_H = 56;

/** Domain → accent colour. ``meta`` is the fallback. */
const DOMAIN_COLOR: Record<string, string> = {
  writing: "#3b82f6", // blue-500
  revision: "#a855f7", // purple-500
  rebuttal: "#f97316", // orange-500
  research: "#10b981", // emerald-500
  survey: "#0ea5e9", // sky-500
  meta: "#6b7280", // gray-500
};

function domainColor(domain: string | null | undefined): string {
  if (!domain) return DOMAIN_COLOR.meta;
  return DOMAIN_COLOR[domain] ?? DOMAIN_COLOR.meta;
}

// ---------------------------------------------------------------------------
// dagre layout — pure transform from graph payload → xyflow nodes/edges.
// ---------------------------------------------------------------------------

interface LayoutResult {
  nodes: Node<{
    label: string;
    domain: string | null;
    version: string;
    enabled: boolean;
    dangling: boolean;
  }>[];
  edges: Edge[];
}

function applyLayout(
  graph: SkillGraphResponse,
  cycleEdgeKeys: Set<string>,
): LayoutResult {
  const g = new dagre.graphlib.Graph();
  g.setGraph({
    rankdir: "LR",
    nodesep: 24,
    ranksep: 80,
    marginx: 16,
    marginy: 16,
  });
  g.setDefaultEdgeLabel(() => ({}));

  const knownNames = new Set(graph.nodes.map((n) => n.name));
  const allNames = new Set<string>(knownNames);
  for (const d of graph.dangling) allNames.add(d);

  for (const name of allNames) {
    g.setNode(name, { width: NODE_W, height: NODE_H });
  }
  for (const e of graph.edges) {
    if (allNames.has(e.source) && allNames.has(e.target)) {
      g.setEdge(e.source, e.target);
    }
  }
  dagre.layout(g);

  const outNodes: LayoutResult["nodes"] = [];
  for (const n of graph.nodes) {
    const pos = g.node(n.name);
    if (!pos) continue;
    outNodes.push(toFlowNode(n, pos, false));
  }
  for (const danglingName of graph.dangling) {
    if (knownNames.has(danglingName)) continue;
    const pos = g.node(danglingName);
    if (!pos) continue;
    outNodes.push(
      toFlowNode(
        {
          name: danglingName,
          domain: null,
          version: "",
          enabled: false,
          description: "",
        },
        pos,
        true,
      ),
    );
  }

  const outEdges: Edge[] = graph.edges.map((e) => toFlowEdge(e, cycleEdgeKeys));

  return { nodes: outNodes, edges: outEdges };
}

function toFlowNode(
  n: SkillGraphNode,
  pos: { x: number; y: number },
  dangling: boolean,
): LayoutResult["nodes"][number] {
  const color = domainColor(n.domain);
  const style: CSSProperties = {
    width: NODE_W,
    height: NODE_H,
    borderRadius: 8,
    border: dangling
      ? `1.5px dashed ${color}`
      : n.enabled
        ? `1px solid ${color}`
        : `1px dashed ${color}`,
    background: n.enabled && !dangling ? `${color}15` : "transparent",
    color: dangling ? color : "var(--color-foreground)",
    fontSize: 12,
    padding: 6,
    opacity: n.enabled ? 1 : 0.65,
  };
  return {
    id: n.name,
    position: { x: pos.x - NODE_W / 2, y: pos.y - NODE_H / 2 },
    data: {
      label: n.name,
      domain: n.domain,
      version: n.version,
      enabled: n.enabled,
      dangling,
    },
    sourcePosition: Position.Right,
    targetPosition: Position.Left,
    style,
  };
}

function toFlowEdge(e: SkillGraphEdge, cycleEdgeKeys: Set<string>): Edge {
  const key = `${e.source}__${e.target}`;
  const inCycle = cycleEdgeKeys.has(key);
  // Colour priority: cycle → amber; both-sided → emerald; one-sided → slate.
  const stroke = inCycle
    ? "#f59e0b"
    : e.declared_by === "both"
      ? "#10b981"
      : "#94a3b8";
  return {
    id: key,
    source: e.source,
    target: e.target,
    type: "smoothstep",
    animated: inCycle,
    label: e.declared_by === "both" ? "↔" : "→",
    labelStyle: { fontSize: 9, fill: stroke },
    style: { stroke, strokeWidth: 1.5 },
    markerEnd: {
      type: MarkerType.ArrowClosed,
      color: stroke,
      width: 14,
      height: 14,
    },
    // Stash the declared_by side so onRemoveEdge knows whether to issue
    // one HTTP call (source / target) or two (both).
    data: { declared_by: e.declared_by },
  };
}

// ---------------------------------------------------------------------------
// Cycle membership — collapse the API's list-of-SCCs into a set of edge
// keys so the renderer can do an O(1) "is this edge in a cycle?" check.
// ---------------------------------------------------------------------------

function cycleEdgeSet(graph: SkillGraphResponse): Set<string> {
  const out = new Set<string>();
  for (const comp of graph.cycles) {
    const members = new Set(comp);
    for (const e of graph.edges) {
      if (members.has(e.source) && members.has(e.target)) {
        out.add(`${e.source}__${e.target}`);
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Public component
// ---------------------------------------------------------------------------

export interface SkillEdgeIdentity {
  source: string;
  target: string;
  declared_by: "source" | "target" | "both";
}

interface SkillsGraphViewProps {
  graph: SkillGraphResponse;
  selected: string | null;
  onSelect: (name: string | null) => void;
  /** P14.F: drag from one node to another. Caller calls
   * ``skillsApi.updateEdges`` and refetches the graph. ``undefined``
   * disables drag-to-connect (read-only mode). */
  onAddEdge?: (source: string, target: string) => void | Promise<void>;
  /** P14.F: delete via Delete/Backspace key OR the trash button. The
   * caller decides whether to coordinate two calls when
   * ``edge.declared_by === "both"``. */
  onRemoveEdge?: (edge: SkillEdgeIdentity) => void | Promise<void>;
  /** Tells the view that a mutation is in flight so the canvas can
   * dim slightly + ignore further drags until the refetch lands. */
  busy?: boolean;
}

export function SkillsGraphView({
  graph,
  selected,
  onSelect,
  onAddEdge,
  onRemoveEdge,
  busy = false,
}: SkillsGraphViewProps) {
  const { t } = useTranslation();
  const editable = onAddEdge !== undefined || onRemoveEdge !== undefined;

  const cycleEdges = useMemo(() => cycleEdgeSet(graph), [graph]);
  const { nodes, edges } = useMemo(
    () => applyLayout(graph, cycleEdges),
    [graph, cycleEdges],
  );

  // Highlight the currently-selected node by overriding its border.
  const decoratedNodes = useMemo<typeof nodes>(() => {
    if (!selected) return nodes;
    return nodes.map((n) =>
      n.id === selected
        ? {
            ...n,
            style: {
              ...(n.style ?? {}),
              boxShadow: "0 0 0 2px var(--color-primary)",
              borderColor: "var(--color-primary)",
            },
          }
        : n,
    );
  }, [nodes, selected]);

  // Currently-clicked edge — used to draw a "delete" affordance and
  // to honour the keyboard Delete shortcut. Cleared when the pane is
  // clicked or when the graph refetches (different ID set).
  const [activeEdgeId, setActiveEdgeId] = useState<string | null>(null);

  const edgeIndex = useMemo(() => {
    const m = new Map<string, SkillGraphEdge>();
    for (const e of graph.edges) {
      m.set(`${e.source}__${e.target}`, e);
    }
    return m;
  }, [graph.edges]);

  // Don't issue self-loops or duplicates — the backend would just
  // skipped_dup them, but a UX-side guard avoids the round trip.
  const onConnect = useCallback(
    (c: Connection) => {
      if (!onAddEdge) return;
      if (!c.source || !c.target) return;
      if (c.source === c.target) return;
      if (edgeIndex.has(`${c.source}__${c.target}`)) return;
      void onAddEdge(c.source, c.target);
    },
    [onAddEdge, edgeIndex],
  );

  const onEdgeClick = useCallback<EdgeMouseHandler>(
    (event, edge) => {
      event.stopPropagation();
      setActiveEdgeId(edge.id);
    },
    [],
  );

  const removeActiveEdge = useCallback(() => {
    if (!activeEdgeId || !onRemoveEdge) return;
    const e = edgeIndex.get(activeEdgeId);
    if (!e) return;
    void onRemoveEdge({
      source: e.source,
      target: e.target,
      declared_by: e.declared_by,
    });
    setActiveEdgeId(null);
  }, [activeEdgeId, edgeIndex, onRemoveEdge]);

  // xyflow's built-in delete handler fires for both the keyboard
  // shortcut and the `deleteKeyCode` on EdgeChange. We funnel both
  // into removeActiveEdge so the request shape is consistent.
  const onEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      for (const c of changes) {
        if (c.type === "remove") {
          if (!onRemoveEdge) continue;
          const e = edgeIndex.get(c.id);
          if (!e) continue;
          void onRemoveEdge({
            source: e.source,
            target: e.target,
            declared_by: e.declared_by,
          });
        }
      }
    },
    [edgeIndex, onRemoveEdge],
  );

  return (
    <div className="flex h-[calc(100vh-18rem)] min-h-[420px] flex-col gap-2">
      <Legend
        cycles={graph.cycles.length}
        dangling={graph.dangling.length}
        totalNodes={graph.nodes.length}
        totalEdges={graph.edges.length}
        editable={editable}
      />

      <div
        className="relative min-h-0 flex-1 overflow-hidden rounded-md border bg-[var(--color-background)]"
        style={{ opacity: busy ? 0.7 : 1, transition: "opacity 120ms" }}
      >
        <ReactFlow
          nodes={decoratedNodes}
          edges={edges}
          fitView
          minZoom={0.3}
          maxZoom={1.6}
          onNodeClick={(_, n) => onSelect(n.id)}
          onPaneClick={() => {
            onSelect(null);
            setActiveEdgeId(null);
          }}
          onConnect={onConnect}
          onEdgeClick={onEdgeClick}
          onEdgesChange={onEdgesChange}
          // ``Delete`` for macOS / ``Backspace`` for desktop laptops.
          deleteKeyCode={onRemoveEdge ? ["Delete", "Backspace"] : null}
          nodesDraggable={false}
          nodesConnectable={editable && !busy}
          edgesFocusable={editable}
          panOnScroll={false}
          zoomOnScroll={true}
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={18} size={1} />
          <Controls position="bottom-right" showInteractive={false} />
          <MiniMap
            position="bottom-left"
            pannable
            zoomable
            nodeColor={(n) => domainColor((n.data as { domain?: string | null }).domain ?? null)}
            maskColor="rgba(0,0,0,0.15)"
            style={{ height: 80, width: 140 }}
          />
        </ReactFlow>

        {/* Floating "delete edge" affordance when an edge is active.
            We overlay this rather than relying solely on the Delete
            key so users on tablets / track-pads have a visible target. */}
        {activeEdgeId && onRemoveEdge ? (
          <button
            type="button"
            onClick={removeActiveEdge}
            disabled={busy}
            className="absolute right-3 top-3 z-10 rounded-md border border-[var(--color-destructive)] bg-[var(--color-background)] px-3 py-1 text-xs text-[var(--color-destructive)] shadow-sm hover:bg-[var(--color-destructive)] hover:text-white disabled:opacity-50"
          >
            {t("skills.graph.deleteEdge", { id: prettifyEdgeId(activeEdgeId) })}
          </button>
        ) : null}
      </div>

      <p className="text-[10px] text-[var(--color-muted-foreground)]">
        {editable
          ? t("skills.graph.editableHint")
          : t("skills.graph.editHint")}
      </p>
    </div>
  );
}

function prettifyEdgeId(id: string): string {
  // ``a__b`` → ``a → b`` for the toast button label.
  return id.replace("__", " → ");
}

interface LegendProps {
  cycles: number;
  dangling: number;
  totalNodes: number;
  totalEdges: number;
  editable: boolean;
}

function Legend({ cycles, dangling, totalNodes, totalEdges, editable }: LegendProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border bg-[var(--color-muted)]/30 px-3 py-1.5 text-[10px] text-[var(--color-muted-foreground)]">
      <span>
        {totalNodes} {t("skills.graph.nodes")} · {totalEdges} {t("skills.graph.edges")}
      </span>
      <Swatch color="#10b981" label={t("skills.graph.legendBoth")} />
      <Swatch color="#94a3b8" label={t("skills.graph.legendOneSided")} />
      {cycles > 0 ? (
        <Swatch
          color="#f59e0b"
          label={t("skills.graph.legendCycles", { count: cycles })}
        />
      ) : null}
      {dangling > 0 ? (
        <span className="font-mono">
          {t("skills.graph.legendDangling", { count: dangling })}
        </span>
      ) : null}
      {editable ? (
        <span className="ml-auto rounded bg-[var(--color-primary)]/15 px-2 py-0.5 text-[var(--color-primary)]">
          {t("skills.graph.editableBadge")}
        </span>
      ) : null}
    </div>
  );
}

function Swatch({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1">
      <span
        aria-hidden
        className="inline-block h-2 w-3 rounded-sm"
        style={{ background: color }}
      />
      {label}
    </span>
  );
}
