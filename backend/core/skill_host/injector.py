"""Compose matched skills into a prompt bundle.

Given a list of matched skills (optionally with heuristic skills), produce:
  - `system_additions`: markdown appended to the system prompt
  - `tool_specs`      : OpenAI-shaped tool list
  - `script_index`    : {tool_name: absolute_script_path}

Token budget: the approximate token count is capped (default 8000); when
exceeded, skills are dropped in ascending score order until the bundle
fits. A log line is emitted on truncation.
"""

from __future__ import annotations

from pathlib import Path

import structlog

from backend.core.llm.base import ToolSpec

from .matcher import MatchResult
from .types import HeuristicSkill, InjectionBundle, ScriptMeta, SkillMeta

log = structlog.get_logger(__name__)

DEFAULT_TOKEN_BUDGET = 8000
_AVG_CHARS_PER_TOKEN = 4


class SkillInjector:
    def __init__(self, *, token_budget: int = DEFAULT_TOKEN_BUDGET) -> None:
        self._budget = token_budget

    def inject(
        self,
        matches: list[MatchResult],
        *,
        heuristics: list[HeuristicSkill] | None = None,
    ) -> InjectionBundle:
        # Drop by ascending score until we fit under the token budget.
        matches_sorted = sorted(matches, key=lambda r: r.score, reverse=True)
        kept: list[MatchResult] = []
        truncated = False
        for m in matches_sorted:
            trial = [*kept, m]
            if _approx_tokens_for(trial, heuristics) <= self._budget:
                kept.append(m)
            else:
                truncated = True
                log.info(
                    "skill.injector.truncated",
                    dropped=m.skill.name,
                    kept=[k.skill.name for k in kept],
                )

        system_additions = _render_system(kept, heuristics)
        tool_specs, script_index = _render_tools(kept)

        return InjectionBundle(
            system_additions=system_additions,
            tool_specs=tool_specs,
            script_index=script_index,
            matched_skills=[m.skill.name for m in kept],
            truncated=truncated,
        )


# ---- rendering helpers ---------------------------------------------------


def _render_system(matches: list[MatchResult], heuristics: list[HeuristicSkill] | None) -> str:
    """Build the system-prompt markdown."""
    sections: list[str] = []
    if matches:
        sections.append(
            "# Skills\n\nYou have access to the following skills. Load and follow the rules described in each."
        )
        for m in matches:
            sections.append(_render_skill(m.skill))
    if heuristics:
        sections.append(_render_heuristics(heuristics))
    return "\n\n".join(sections).strip()


def _render_skill(s: SkillMeta) -> str:
    lines = [f"## 🧩 Skill: `{s.name}`"]
    if s.version and s.version != "0.0.0":
        lines.append(f"_Version: {s.version}_")
    if s.description:
        lines.append(f"**Purpose:** {s.description}")
    if s.triggers:
        lines.append(f"**Triggers:** {', '.join(s.triggers)}")
    if s.body:
        lines.append("")
        lines.append(s.body)
    if s.scripts:
        lines.append("")
        lines.append("**Available scripts (exposed as tools):**")
        for sc in s.scripts:
            bullet = f"- `{_tool_name(s.name, sc.name)}`"
            if sc.description:
                bullet += f" — {sc.description}"
            lines.append(bullet)
    return "\n".join(lines)


def _render_heuristics(items: list[HeuristicSkill]) -> str:
    lines = ["## ⚡ Learned strategies"]
    lines.append(
        "Strategies below were learned from past successful runs. Apply them only when they clearly fit the current task."
    )
    for h in items:
        lines.append("")
        lines.append(f"### {h.name}")
        if h.description:
            lines.append(h.description)
        if h.when_to_use:
            lines.append(f"_When to use:_ {h.when_to_use}")
    return "\n".join(lines)


def _render_tools(matches: list[MatchResult]) -> tuple[list[ToolSpec], dict[str, Path]]:
    specs: list[ToolSpec] = []
    index: dict[str, Path] = {}
    for m in matches:
        for sc in m.skill.scripts:
            tool_name = _tool_name(m.skill.name, sc.name)
            specs.append(_tool_spec_for(m.skill.name, sc, tool_name))
            index[tool_name] = sc.path
    return specs, index


def _tool_name(skill_name: str, script_stem: str) -> str:
    return f"{skill_name}__{script_stem}"


def _tool_spec_for(skill_name: str, script: ScriptMeta, tool_name: str) -> ToolSpec:
    parameters = script.args_schema or {"type": "object", "properties": {}}
    desc = script.description or f"Run the `{script.name}` script of the `{skill_name}` skill."
    return ToolSpec(name=tool_name, description=desc, parameters=parameters)


def _approx_tokens_for(matches: list[MatchResult], heuristics: list[HeuristicSkill] | None) -> int:
    text = _render_system(matches, heuristics)
    # account for tool specs too
    for m in matches:
        for sc in m.skill.scripts:
            text += sc.description or ""
            text += str(sc.args_schema or "")
    return max(1, len(text) // _AVG_CHARS_PER_TOKEN)


__all__ = ["DEFAULT_TOKEN_BUDGET", "SkillInjector"]
