"""Plan validator — pure-python, no I/O.

We re-run this on every execute attempt so a freshly compiled plan and a
plan supplied by an external host LLM go through the same gate. The
checks are deliberately conservative:

1. Each ``id`` is non-empty and unique.
2. Every ``depends_on`` references a sibling id.
3. The dependency graph is acyclic.
4. Tool / skill nodes name a concrete registered capability.
5. Memory nodes carry the minimum keys their kind needs.
6. Self-loops are rejected.

Anything ambiguous (e.g. an LLM node without a description) downgrades
to a warning so the executor still has a chance to run.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .models import PlanDAG, PlanNode, ValidatePlanResponse


def validate_plan(
    plan: PlanDAG,
    *,
    skill_host: Any | None = None,
    tools: Any | None = None,
) -> ValidatePlanResponse:
    """Validate a :class:`PlanDAG` against the local skill / tool registries.

    Either registry may be ``None`` — that lets unit tests run without
    booting the full app state. Names are not checked when the
    corresponding registry is missing (a warning is emitted instead).
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not plan.nodes:
        warnings.append("plan has no nodes; nothing to execute")
        return ValidatePlanResponse(ok=True, errors=errors, warnings=warnings)

    seen_ids: set[str] = set()
    for node in plan.nodes:
        if not node.id:
            errors.append("node has empty id")
            continue
        if node.id in seen_ids:
            errors.append(f"duplicate node id: {node.id!r}")
        seen_ids.add(node.id)

    known_tools = set(tools.names()) if tools is not None else None
    known_skills = (
        {meta.name for meta in skill_host.list_skills()} if skill_host is not None else None
    )

    by_id = {n.id: n for n in plan.nodes if n.id}
    for node in plan.nodes:
        if not node.id:
            continue
        for dep in node.depends_on:
            if dep == node.id:
                errors.append(f"node {node.id!r} depends on itself")
                continue
            if dep not in by_id:
                errors.append(f"node {node.id!r} depends on unknown id {dep!r}")
        _check_kind_args(node, errors, warnings)
        if node.kind == "tool" and known_tools is not None:
            if not node.name:
                errors.append(f"tool node {node.id!r} has empty name")
            elif node.name not in known_tools:
                errors.append(f"tool node {node.id!r} references unknown tool {node.name!r}")
        if node.kind == "skill" and known_skills is not None:
            if not node.name:
                errors.append(f"skill node {node.id!r} has empty name")
            elif node.name not in known_skills:
                errors.append(f"skill node {node.id!r} references unknown skill {node.name!r}")

    if _has_cycle(plan.nodes):
        errors.append("plan contains a cycle")

    return ValidatePlanResponse(ok=not errors, errors=errors, warnings=warnings)


def _check_kind_args(
    node: PlanNode,
    errors: list[str],
    warnings: list[str],
) -> None:
    """Per-kind shallow checks. Keep these minimal — the executor enforces
    the rest at runtime when it dispatches to the actual skill / tool."""
    if node.kind == "llm":
        if not node.description and not node.args.get("prompt"):
            warnings.append(
                f"llm node {node.id!r} has no description nor args.prompt; "
                "the executor will fall back to the plan query"
            )
    elif node.kind == "memory.read":
        if "query" not in node.args and "doc_id" not in node.args:
            warnings.append(
                f"memory.read node {node.id!r} has neither args.query nor args.doc_id; "
                "the recall will use the plan query as default"
            )
    elif node.kind == "memory.write":
        if "kind" not in node.args:
            errors.append(
                f"memory.write node {node.id!r} missing required args.kind "
                "(one of: heuristic, episodic, knowledge, document, session)"
            )


def _has_cycle(nodes: Iterable[PlanNode]) -> bool:
    """Standard 3-state DFS. Returns True iff any back-edge is found."""
    indices: dict[str, int] = {}
    successors: dict[str, list[str]] = {}
    for n in nodes:
        if not n.id:
            continue
        indices[n.id] = len(indices)
        successors.setdefault(n.id, [])
    for n in nodes:
        if not n.id:
            continue
        for dep in n.depends_on:
            if dep in indices and dep != n.id:
                successors[dep].append(n.id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(indices, WHITE)

    def visit(u: str) -> bool:
        color[u] = GRAY
        for v in successors.get(u, []):
            c = color.get(v, WHITE)
            if c == GRAY:
                return True
            if c == WHITE and visit(v):
                return True
        color[u] = BLACK
        return False

    return any(color[u] == WHITE and visit(u) for u in list(color))


__all__ = ["validate_plan"]
