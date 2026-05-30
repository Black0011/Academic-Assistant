"""Compile a free-form query into a :class:`PlanDAG`.

The compiler has two paths:

* **LLM-driven** — when an LLM provider is wired, we ask the model to
  emit JSON describing the plan. We expose available skills / tools as
  prompt context. The model's JSON is parsed leniently (we strip code
  fences, scan for the first balanced ``{ ... }`` envelope, and then
  validate via :class:`PlanDAG.model_validate`). On any parse / validate
  failure we fall back to the heuristic plan and surface a warning in
  ``rationale``.

* **Heuristic fallback** — a single-node ``llm`` plan that asks the
  default model to summarise the query against memory. This keeps the
  end-to-end contract intact even on cold-start machines without
  credentials (the same property `_build_llm` in ``backend.app`` gives
  the rest of the framework).

The compiler is intentionally tolerant: as long as the JSON contains a
``nodes`` list with at least one valid node, we accept it. Strict
correctness is the validator's job (run at the router boundary).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.llm.base import ChatMessage, collect_text

from .models import (
    PlanDAG,
    PlanNode,
    SkillForCompile,
    SkillsForCompileResponse,
    ToolForCompile,
    new_node_id,
    new_plan_id,
)

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider
    from backend.core.skill_host import SkillHost
    from backend.tools.registry import ToolRegistry

log = structlog.get_logger(__name__)


_SYSTEM_PROMPT = """You are a planning agent for an academic research framework.
Given a user query, output a JSON object describing an executable DAG.

The JSON envelope is:

{
  "rationale": "<one paragraph explaining the plan>",
  "nodes": [
    {
      "id": "<short unique id>",
      "kind": "skill | tool | llm | memory.read | memory.write",
      "name": "<tool or skill name; empty for llm/memory>",
      "args": { ... },
      "depends_on": ["<other-node-id>", ...],
      "description": "<short prose>",
      "expected_output": "<one sentence>",
      "on_failure": "abort | skip | continue",
      "retries": 0
    }
  ]
}

Rules:
* Use only the skills and tools listed in the context. If unsure, omit.
* Always start with a memory.read node so the downstream nodes have context.
* Prefer tools (deterministic) over skills (heuristic) over llm (free-form).
* Keep the plan small (<= 8 nodes unless the user asks for more).
* The final node SHOULD be an llm summarisation node depending on prior nodes.
* Return ONLY the JSON, no prose, no markdown fences.
"""


class PlannerCompiler:
    """Compile a query into a :class:`PlanDAG`.

    Constructed once per request from :class:`AppState`. The compiler is
    intentionally stateless — every call rebuilds the prompt from the
    live skill / tool catalogue.
    """

    def __init__(
        self,
        *,
        llm: LLMProvider | None,
        skill_host: SkillHost | None,
        tools: ToolRegistry | None,
    ) -> None:
        self._llm = llm
        self._skills = skill_host
        self._tools = tools

    # ---- catalogue helpers -----------------------------------------

    def skills_for_compile(self) -> SkillsForCompileResponse:
        skills: list[SkillForCompile] = []
        if self._skills is not None:
            for meta in self._skills.list_skills():
                skills.append(
                    SkillForCompile(
                        name=meta.name,
                        description=meta.description,
                        domain=getattr(meta, "domain", "") or "",
                        triggers=list(getattr(meta, "triggers", []) or []),
                        invocation_modes=list(getattr(meta, "invocation_modes", []) or []),
                    )
                )
        tools: list[ToolForCompile] = []
        if self._tools is not None:
            specs = self._tools.list_for_injection(allow_network=True, allow_paid_api=True)
            for spec in specs:
                tools.append(
                    ToolForCompile(
                        name=spec.name,
                        description=spec.description,
                        parameters=dict(spec.parameters),
                    )
                )
        return SkillsForCompileResponse(skills=skills, tools=tools)

    # ---- entry point -----------------------------------------------

    async def compile(
        self,
        *,
        query: str,
        domain: str = "",
        hints: list[str] | None = None,
        only_skills: list[str] | None = None,
        only_tools: list[str] | None = None,
        max_nodes: int = 30,
    ) -> PlanDAG:
        catalogue = self.skills_for_compile()
        catalogue = _filter_catalogue(catalogue, only_skills, only_tools)

        if self._llm is None:
            return _fallback_plan(
                query=query,
                domain=domain,
                rationale="no LLM provider configured; using fallback plan",
                provider="",
            )

        provider = getattr(self._llm, "name", "?")
        try:
            envelope = await _request_plan_json(
                self._llm,
                query=query,
                domain=domain,
                hints=hints or [],
                catalogue=catalogue,
            )
        except Exception as exc:
            log.warning("planner.compile.llm_failed", err=str(exc))
            return _fallback_plan(
                query=query,
                domain=domain,
                rationale=f"LLM call failed: {exc}; using fallback plan",
                provider=provider,
            )

        plan = _coerce_to_plan(envelope, query=query, domain=domain, provider=provider)
        if plan is None:
            return _fallback_plan(
                query=query,
                domain=domain,
                rationale="LLM output not parseable; using fallback plan",
                provider=provider,
            )

        if max_nodes and len(plan.nodes) > max_nodes:
            plan = plan.model_copy(update={"nodes": plan.nodes[:max_nodes]})
        return plan


# ---------------------------------------------------------------------------
# LLM round-trip
# ---------------------------------------------------------------------------


async def _request_plan_json(
    llm: LLMProvider,
    *,
    query: str,
    domain: str,
    hints: list[str],
    catalogue: SkillsForCompileResponse,
) -> dict[str, Any]:
    skills_block = "\n".join(
        f"- {s.name} :: {s.description or ''} (domain={s.domain or 'none'})"
        for s in catalogue.skills[:30]
    )
    tools_block = "\n".join(f"- {t.name} :: {t.description or ''}" for t in catalogue.tools[:30])
    user_msg_parts = [
        f"User query: {query}",
        f"Domain hint: {domain or 'none'}",
        "Available skills:",
        skills_block or "  (none)",
        "Available tools:",
        tools_block or "  (none)",
    ]
    if hints:
        user_msg_parts += ["Constraints / hints:"] + [f"- {h}" for h in hints]
    user_msg = "\n".join(user_msg_parts)

    messages = [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content=user_msg),
    ]
    stream = await llm.complete(messages, temperature=0.1, stream=False)
    text, _, _, _ = await collect_text(stream)
    payload = _extract_json_object(text)
    if payload is None:
        raise ValueError("no JSON object in LLM output")
    return payload


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Parse the first balanced ``{ ... }`` block in *text*.

    Tolerant of leading/trailing prose and markdown code fences. If the
    parsed value isn't a dict, returns None.
    """
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                blob = cleaned[start : i + 1]
                try:
                    parsed = json.loads(blob)
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


def _coerce_to_plan(
    envelope: dict[str, Any],
    *,
    query: str,
    domain: str,
    provider: str,
) -> PlanDAG | None:
    """Build a :class:`PlanDAG` from an LLM-emitted envelope.

    Auto-fills ``id`` for any node missing one and skips entries that
    can't be coerced into a :class:`PlanNode`.
    """
    raw_nodes = envelope.get("nodes")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        return None

    nodes: list[PlanNode] = []
    used_ids: set[str] = set()
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            continue
        candidate = dict(raw)
        nid = candidate.get("id") or new_node_id()
        while nid in used_ids:
            nid = new_node_id()
        candidate["id"] = nid
        used_ids.add(nid)
        try:
            nodes.append(PlanNode.model_validate(candidate))
        except Exception:
            continue

    if not nodes:
        return None

    rationale = str(envelope.get("rationale") or "").strip()
    return PlanDAG(
        plan_id=new_plan_id(),
        query=query,
        domain=domain,
        nodes=nodes,
        rationale=rationale,
        estimated_steps=len(nodes),
        created_at=datetime.now(UTC),
        llm_provider=provider,
    )


def _fallback_plan(
    *,
    query: str,
    domain: str,
    rationale: str,
    provider: str,
) -> PlanDAG:
    """Single-node ``llm`` plan used when the model isn't available."""
    recall = PlanNode(
        id="recall",
        kind="memory.read",
        args={"query": query},
        description="recall MemorySnapshot for the query",
        expected_output="MemorySnapshot summary string",
    )
    summary = PlanNode(
        id="summarise",
        kind="llm",
        depends_on=["recall"],
        args={"prompt": f"Answer the query using the recall context: {query}"},
        description="summarise the recall context for the user query",
        expected_output="markdown answer",
    )
    return PlanDAG(
        plan_id=new_plan_id(),
        query=query,
        domain=domain,
        nodes=[recall, summary],
        rationale=rationale,
        estimated_steps=2,
        created_at=datetime.now(UTC),
        llm_provider=provider,
        extras={"fallback": True},
    )


def _filter_catalogue(
    catalogue: SkillsForCompileResponse,
    only_skills: list[str] | None,
    only_tools: list[str] | None,
) -> SkillsForCompileResponse:
    skills = catalogue.skills
    tools = catalogue.tools
    if only_skills is not None:
        keep = set(only_skills)
        skills = [s for s in skills if s.name in keep]
    if only_tools is not None:
        keep = set(only_tools)
        tools = [t for t in tools if t.name in keep]
    return SkillsForCompileResponse(skills=skills, tools=tools)


__all__ = ["PlannerCompiler"]
