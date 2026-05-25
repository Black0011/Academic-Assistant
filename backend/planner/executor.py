"""DAG executor — runs a validated :class:`PlanDAG` end to end.

Design:

* Topologically sort once; group nodes by their layer so we can
  ``asyncio.gather`` siblings within bounded concurrency.
* Per-node retry uses an exponential backoff capped at
  ``node.retries + 1`` total attempts.
* Failure semantics follow ``node.on_failure``:

    - ``abort``    — failed node aborts the whole DAG; descendants get
                     ``status=skipped`` and the executor returns
                     ``verdict="error"``.
    - ``skip``     — failed node marks its descendants as skipped but
                     unrelated nodes keep running.
    - ``continue`` — failed node carries ``output={}`` to descendants
                     (which can decide to ignore it).

* Each node emits ``task.stage_start`` / ``task.stage_end`` with
  ``node_id`` / ``kind`` / ``name`` / ``attempts``. The shape is the
  same the existing SSE consumers know how to render.

* Argument resolution: any ``args`` value of the form
  ``{"$ref": "node_id"}`` is replaced with the upstream node's
  ``output`` dict; ``{"$ref": "node_id.field"}`` does dotted access.
  This is the minimal viable data-flow primitive for now.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.events import Event, EventType
from backend.core.llm.base import ChatMessage, collect_text

from .models import NodeOutcome, PlanDAG, PlanNode

if TYPE_CHECKING:
    from backend.workflows.base import WorkflowContext

log = structlog.get_logger(__name__)


class DAGExecutor:
    """Runs a :class:`PlanDAG` against the framework's runtime collaborators.

    Construct one per execution. The executor reuses the
    :class:`WorkflowContext` injected by the task runner, so the same
    SSE channel that observes built-in workflows transparently sees
    DAG node events.
    """

    def __init__(
        self,
        *,
        memory: Any | None = None,
        llm: Any | None = None,
        tools: Any | None = None,
        skill_host: Any | None = None,
        max_parallel: int = 4,
        node_timeout_s: int | None = None,
    ) -> None:
        self._memory = memory
        self._llm = llm
        self._tools = tools
        self._skill_host = skill_host
        self._max_parallel = max(1, max_parallel)
        self._node_timeout_s = node_timeout_s

    # ---- public ----------------------------------------------------

    async def run(
        self,
        plan: PlanDAG,
        *,
        ctx: WorkflowContext,
        params: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, NodeOutcome]]:
        """Execute *plan*. Returns ``(verdict, outcomes_by_id)``.

        Verdict is ``"ok"`` when no aborting node failed. Even with
        ``"ok"``, individual nodes can be ``failed`` / ``skipped``.
        """
        params = params or {}
        outcomes: dict[str, NodeOutcome] = {
            n.id: NodeOutcome(node_id=n.id, kind=n.kind, name=n.name) for n in plan.nodes
        }
        layers = topo_layers(plan.nodes)
        if layers is None:
            await ctx.emit(Event(EventType.TASK_ERROR, data={"error": "plan contains a cycle"}))
            return "error", outcomes

        cancel_descendants_of: set[str] = set()
        succ = _successors(plan.nodes)
        verdict = "ok"

        for layer in layers:
            ready = [n for n in layer if n.id not in cancel_descendants_of]
            skipped = [n for n in layer if n.id in cancel_descendants_of]
            for n in skipped:
                outcomes[n.id].status = "skipped"
                cancel_descendants_of.update(_descendants(n.id, succ))

            if not ready:
                continue

            sem = asyncio.Semaphore(self._max_parallel)

            async def _run_one(node: PlanNode, _sem: asyncio.Semaphore = sem) -> None:
                async with _sem:
                    await self._run_node(node, plan, params, outcomes, ctx)

            await asyncio.gather(*[_run_one(n) for n in ready])

            for n in ready:
                outcome = outcomes[n.id]
                if outcome.status == "failed":
                    if n.on_failure == "abort":
                        verdict = "error"
                        for other_id in succ.get(n.id, []):
                            cancel_descendants_of.add(other_id)
                            cancel_descendants_of.update(_descendants(other_id, succ))
                        # Also cancel everything downstream — same effect.
                    elif n.on_failure == "skip":
                        for other_id in _descendants(n.id, succ):
                            cancel_descendants_of.add(other_id)
                    # "continue": descendants run normally; they observe empty output.

            if verdict == "error":
                # Mark remaining (yet-untouched) nodes as skipped early so the
                # outcome map is complete when we exit.
                for layer_after in layers[layers.index(layer) + 1 :]:
                    for n in layer_after:
                        if outcomes[n.id].status == "pending":
                            outcomes[n.id].status = "skipped"
                break

        return verdict, outcomes

    # ---- node dispatch ---------------------------------------------

    async def _run_node(
        self,
        node: PlanNode,
        plan: PlanDAG,
        params: dict[str, Any],
        outcomes: dict[str, NodeOutcome],
        ctx: WorkflowContext,
    ) -> None:
        outcome = outcomes[node.id]
        outcome.status = "running"
        outcome.started_at = datetime.now(UTC)
        await ctx.emit(
            Event(
                EventType.TASK_STAGE_START,
                data={
                    "stage": f"node:{node.id}",
                    "node_id": node.id,
                    "kind": node.kind,
                    "name": node.name,
                    "description": node.description,
                },
            )
        )
        started = time.monotonic()
        attempts = 0
        last_err: str = ""
        max_attempts = max(1, node.retries + 1)

        # Resolve $ref placeholders against already-completed outcomes.
        resolved_args = _resolve_args(node.args, outcomes)

        while attempts < max_attempts:
            attempts += 1
            try:
                if self._node_timeout_s:
                    output = await asyncio.wait_for(
                        self._dispatch(node, resolved_args, plan, params, outcomes, ctx),
                        timeout=self._node_timeout_s,
                    )
                else:
                    output = await self._dispatch(node, resolved_args, plan, params, outcomes, ctx)
                outcome.output = output if isinstance(output, dict) else {"value": output}
                outcome.status = "succeeded"
                last_err = ""
                break
            except TimeoutError:
                last_err = f"timeout after {self._node_timeout_s}s"
                outcome.status = "failed"
            except Exception as exc:
                last_err = f"{type(exc).__name__}: {exc}"
                outcome.status = "failed"
                if attempts < max_attempts:
                    await ctx.emit(
                        Event(
                            EventType.TASK_RETRY,
                            data={
                                "node_id": node.id,
                                "attempt": attempts,
                                "next_attempt_in_ms": 200 * 2 ** (attempts - 1),
                                "error": last_err,
                            },
                        )
                    )
                    await asyncio.sleep(0.2 * 2 ** (attempts - 1))

        outcome.attempts = attempts
        outcome.finished_at = datetime.now(UTC)
        outcome.duration_ms = int((time.monotonic() - started) * 1000)
        outcome.error = last_err
        await ctx.emit(
            Event(
                EventType.TASK_STAGE_END,
                data={
                    "stage": f"node:{node.id}",
                    "node_id": node.id,
                    "status": outcome.status,
                    "attempts": attempts,
                    "duration_ms": outcome.duration_ms,
                    "error": last_err,
                },
            )
        )

    async def _dispatch(
        self,
        node: PlanNode,
        args: dict[str, Any],
        plan: PlanDAG,
        params: dict[str, Any],
        outcomes: dict[str, NodeOutcome],
        ctx: WorkflowContext,
    ) -> dict[str, Any]:
        """Per-kind dispatch. Returns a dict (possibly empty)."""
        if node.kind == "tool":
            return await self._dispatch_tool(node, args, ctx)
        if node.kind == "skill":
            return await self._dispatch_skill(node, args, ctx)
        if node.kind == "memory.read":
            return await self._dispatch_memory_read(node, args, plan)
        if node.kind == "memory.write":
            return await self._dispatch_memory_write(node, args, plan)
        if node.kind == "llm":
            return await self._dispatch_llm(node, args, plan, outcomes, ctx)
        raise ValueError(f"unknown node kind: {node.kind!r}")

    async def _dispatch_tool(
        self,
        node: PlanNode,
        args: dict[str, Any],
        ctx: WorkflowContext,
    ) -> dict[str, Any]:
        if self._tools is None:
            raise RuntimeError("tool registry not configured")
        result = await self._tools.call(node.name, args)
        return {
            "ok": result.ok,
            "output": result.output,
            "error": result.error,
            "meta": dict(getattr(result, "meta", {}) or {}),
        }

    async def _dispatch_skill(
        self,
        node: PlanNode,
        args: dict[str, Any],
        ctx: WorkflowContext,
    ) -> dict[str, Any]:
        host = self._skill_host
        if host is None:
            raise RuntimeError("skill host not configured")
        # Convention: 'name' is either '<skill>__<script>' (canonical) or
        # bare '<skill>' (we pick the first script via heuristics later).
        tool_name = node.name if "__" in node.name else f"{node.name}__main"
        result = await host.call_tool(
            tool_name,
            args,
            task_id=ctx.task_id,
        )
        return {
            "ok": getattr(result, "ok", True),
            "stdout": getattr(result, "stdout", ""),
            "stderr": getattr(result, "stderr", ""),
            "exit_code": getattr(result, "exit_code", 0),
            "duration_ms": getattr(result, "duration_ms", 0),
        }

    async def _dispatch_memory_read(
        self,
        node: PlanNode,
        args: dict[str, Any],
        plan: PlanDAG,
    ) -> dict[str, Any]:
        if self._memory is None:
            raise RuntimeError("memory bundle not configured")
        query = str(args.get("query") or plan.query or "")
        domain = str(args.get("domain") or plan.domain or "")
        snap = await self._memory.snapshot(query, domain=domain)
        return {
            "summary": getattr(snap, "vector_summary", ""),
            "papers": [p.model_dump() for p in getattr(snap, "related_papers", [])],
            "doc_chunks": [c.model_dump() for c in getattr(snap, "doc_chunks", [])],
            "heuristics": [h.model_dump() for h in getattr(snap, "heuristics", [])],
        }

    async def _dispatch_memory_write(
        self,
        node: PlanNode,
        args: dict[str, Any],
        plan: PlanDAG,
    ) -> dict[str, Any]:
        if self._memory is None:
            raise RuntimeError("memory bundle not configured")
        kind = str(args.get("kind") or "").lower()
        text = str(args.get("text") or args.get("content") or "")
        if not text:
            return {"written": False, "reason": "empty text"}
        if kind == "episodic":
            from backend.memory.base import gen_id
            from backend.memory.models import Reflection

            await self._memory.episodic.append(
                Reflection(
                    id=gen_id(),
                    type="reflection",
                    content=text,
                    source_run_id=plan.plan_id,
                )
            )
            return {"written": True, "kind": kind}
        # Other kinds intentionally unsupported in this round; emit hint.
        return {"written": False, "reason": f"memory.write kind={kind!r} not supported"}

    async def _dispatch_llm(
        self,
        node: PlanNode,
        args: dict[str, Any],
        plan: PlanDAG,
        outcomes: dict[str, NodeOutcome],
        ctx: WorkflowContext,
    ) -> dict[str, Any]:
        if self._llm is None:
            raise RuntimeError("LLM provider not configured")
        prompt = str(args.get("prompt") or node.description or plan.query)
        upstream = _upstream_outputs(node, outcomes)
        if upstream:
            preview = "\n".join(f"- {nid}: {_short(out)}" for nid, out in upstream.items())
            prompt = f"{prompt}\n\nUpstream context:\n{preview}"
        messages = [
            ChatMessage(role="system", content="You are a research assistant. Be concise."),
            ChatMessage(role="user", content=prompt),
        ]
        stream = await self._llm.complete(messages, temperature=0.2, stream=False)
        text, _, usage, _ = await collect_text(stream)
        return {
            "text": text,
            "usage": usage.model_dump() if usage is not None else {},
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def topo_layers(nodes: Iterable[PlanNode]) -> list[list[PlanNode]] | None:
    """Kahn's algorithm. Returns ``None`` if the graph has a cycle."""
    nodes = list(nodes)
    by_id = {n.id: n for n in nodes}
    indeg: dict[str, int] = {n.id: 0 for n in nodes}
    succ: dict[str, list[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        for dep in n.depends_on:
            if dep not in by_id:
                continue
            indeg[n.id] += 1
            succ[dep].append(n.id)
    layers: list[list[PlanNode]] = []
    frontier = [n.id for n in nodes if indeg[n.id] == 0]
    seen: set[str] = set()
    while frontier:
        layer_nodes = [by_id[i] for i in frontier]
        layers.append(layer_nodes)
        seen.update(frontier)
        nxt: list[str] = []
        for u in frontier:
            for v in succ.get(u, []):
                indeg[v] -= 1
                if indeg[v] == 0:
                    nxt.append(v)
        frontier = nxt
    if len(seen) != len(nodes):
        return None
    return layers


def _successors(nodes: Iterable[PlanNode]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {n.id: [] for n in nodes}
    for n in nodes:
        for dep in n.depends_on:
            out.setdefault(dep, []).append(n.id)
    return out


def _descendants(node_id: str, succ: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    queue = list(succ.get(node_id, []))
    while queue:
        cur = queue.pop()
        if cur in seen:
            continue
        seen.add(cur)
        queue.extend(succ.get(cur, []))
    return seen


def _resolve_args(args: dict[str, Any], outcomes: dict[str, NodeOutcome]) -> dict[str, Any]:
    """Walk *args* replacing ``{"$ref": "node[.field]"}`` placeholders."""

    def _walk(value: Any) -> Any:
        if isinstance(value, dict):
            if set(value.keys()) == {"$ref"} and isinstance(value["$ref"], str):
                return _resolve_ref(value["$ref"], outcomes)
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        return value

    return _walk(args)


def _resolve_ref(ref: str, outcomes: dict[str, NodeOutcome]) -> Any:
    parts = ref.split(".")
    head = parts[0]
    outcome = outcomes.get(head)
    if outcome is None or outcome.status not in {"succeeded", "failed"}:
        return None
    cur: Any = outcome.output
    for part in parts[1:]:
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _upstream_outputs(node: PlanNode, outcomes: dict[str, NodeOutcome]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for dep in node.depends_on:
        outcome = outcomes.get(dep)
        if outcome is None:
            continue
        out[dep] = outcome.output
    return out


def _short(value: Any, *, limit: int = 480) -> str:
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


__all__ = [
    "DAGExecutor",
    "topo_layers",
]
