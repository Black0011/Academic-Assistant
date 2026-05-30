"""Pull-mode skill registration — each skill becomes a callable ToolSpec.

Replaces the old "push" injector which dumped full skill bodies into
the system prompt. Instead, skills are advertised as tools the LLM can
invoke on demand. When the LLM calls ``use_skill__<name>``, the skill's
body is returned as a tool result.

Also retains the legacy push-mode ``inject()`` for backward compat.
"""

from __future__ import annotations

import structlog

from backend.core.llm.base import ToolSpec

from .types import SkillMeta

log = structlog.get_logger(__name__)

SKILL_TOOL_PREFIX = "use_skill__"


def build_skill_tools(skills: list[SkillMeta], max_tools: int = 24) -> list[ToolSpec]:
    """Generate one ToolSpec per skill for pull-mode invocation.

    Each tool is named ``use_skill__<name>`` and accepts an optional
    ``query`` parameter. The LLM decides WHICH skill to load based on
    the tool description and triggers.
    """
    tools: list[ToolSpec] = []
    for s in skills[:max_tools]:
        desc_parts = [s.description] if s.description else []
        if s.triggers:
            desc_parts.append(f"Triggers: {', '.join(s.triggers[:8])}")
        tools.append(
            ToolSpec(
                name=f"{SKILL_TOOL_PREFIX}{s.name}",
                description=". ".join(desc_parts) if desc_parts else f"Load the {s.name} skill.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Optional: what you want to accomplish with this skill.",
                        }
                    },
                },
            )
        )
    return tools


def render_skill_body(skill: SkillMeta, *, include_scripts: bool = True) -> str:
    """Render a single skill's body suitable for a tool result.

    Returns the full SKILL.md content (after frontmatter) plus an
    optional scripts listing. This is what the LLM receives when it
    calls ``use_skill__<name>``.
    """
    lines = [f"## Skill: {skill.name}"]
    if skill.version and skill.version != "0.0.0":
        lines.append(f"_Version: {skill.version}_")
    if skill.description:
        lines.append(f"**Purpose:** {skill.description}")
    if skill.triggers:
        lines.append(f"**Triggers:** {', '.join(skill.triggers)}")
    if skill.body:
        lines.append("")
        lines.append(skill.body)
    if include_scripts and skill.scripts:
        lines.append("")
        lines.append("**Available sub-tools (callable as functions):**")
        for sc in skill.scripts:
            tool_name = f"{skill.name}__{sc.name}"
            bullet = f"- `{tool_name}`"
            if sc.description:
                bullet += f" — {sc.description}"
            lines.append(bullet)

    # Skill-DAG: expose orchestration chain to the Agent
    dag_sections = []
    if skill.downstream_skills:
        dag_sections.append(
            "**Downstream skills (call next if needed):** "
            + ", ".join(f"`use_skill__{s}`" for s in skill.downstream_skills)
        )
    if skill.consumes:
        dag_sections.append("**Inputs (consumes):** " + ", ".join(skill.consumes))
    if skill.produces:
        dag_sections.append("**Outputs (produces):** " + ", ".join(skill.produces))
    if skill.preconditions:
        dag_sections.append("**Preconditions:** " + "; ".join(skill.preconditions))
    if dag_sections:
        lines.append("")
        lines.append("### Orchestration Chain")
        lines.extend(dag_sections)

    return "\n".join(lines)


def render_script_tools(skill: SkillMeta) -> list[ToolSpec]:
    """Generate ToolSpecs for a skill's bundled scripts.

    These are returned ALONGSIDE the skill body so the LLM can call
    them after reading the skill instructions.
    """
    specs: list[ToolSpec] = []
    for sc in skill.scripts:
        tool_name = f"{skill.name}__{sc.name}"
        parameters = sc.args_schema or {"type": "object", "properties": {}}
        desc = sc.description or f"Run {sc.name} from {skill.name}"
        specs.append(ToolSpec(name=tool_name, description=desc, parameters=parameters))
    return specs


def build_pull_system_additions(skill_count: int, prefix_count: int = 8) -> str:
    """Minimal system-prompt addition listing available skill tools.

    Does NOT include skill bodies — just tells the LLM how to use them:
    call ``use_skill__<name>`` to load a skill's instructions.
    """
    if skill_count == 0:
        return ""
    return (
        "## Skills (on-demand)\n\n"
        f"You have access to {skill_count} skill tools (named `{SKILL_TOOL_PREFIX}<name>`). "
        "Call a skill tool to load its detailed instructions before executing "
        "domain-specific tasks. "
        "Only call skills that are relevant to the user's request.\n"
    )


__all__ = [
    "SKILL_TOOL_PREFIX",
    "build_pull_system_additions",
    "build_skill_tools",
    "render_skill_body",
    "render_script_tools",
]
