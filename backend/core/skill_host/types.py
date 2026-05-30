"""Shared types for the Skill Host.

Four user-visible models and a couple of helper types.
See PLAN §6 and the aaf-skill-host SKILL for semantics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Script metadata (one per `.py` file under <skill>/scripts/)
# ---------------------------------------------------------------------------


class ScriptMeta(BaseModel):
    """Metadata extracted from one script file inside a skill.

    Scripts declare runtime hints via magic comments at the top:
        # aaf:network none|optional|required
        # aaf:timeout <seconds>
        # aaf:uses-llm
        # aaf:args {"key": "string"}

    Anything not declared falls back to the owning skill's defaults.
    """

    model_config = ConfigDict(extra="forbid")

    name: str  # filename stem
    path: Path
    description: str = ""
    requires_network: bool = False
    max_duration_s: int | None = None
    uses_llm: bool = False
    args_schema: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Skill metadata (one per <skill>/SKILL.md)
# ---------------------------------------------------------------------------


class SkillMeta(BaseModel):
    """Parsed representation of a capability skill."""

    model_config = ConfigDict(extra="ignore")

    name: str
    path: Path
    description: str = ""
    domain: str | None = None
    triggers: list[str] = Field(default_factory=list)
    version: str = "0.0.0"
    requires: list[str] = Field(default_factory=list)
    network: Literal["none", "optional", "required"] = "none"
    exclusive: bool = False
    scripts: list[ScriptMeta] = Field(default_factory=list)
    references: list[Path] = Field(default_factory=list)
    body: str = ""
    description_embedding: list[float] | None = None
    # Skill-DAG fields (based on paper-orchestration pattern)
    downstream_skills: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    failure_modes: list[dict] = Field(default_factory=list)
    raw_meta: dict[str, Any] = Field(default_factory=dict)

    @property
    def has_body(self) -> bool:
        return bool(self.body.strip())


# ---------------------------------------------------------------------------
# Heuristic skills (L3) — shared type used by both Skill Host (for injection)
# and the future HeuristicStore (for persistence).
# ---------------------------------------------------------------------------


class HeuristicSkill(BaseModel):
    """An Evolver-generated strategy. Kept minimal here; the persistent
    schema with success/failure counts lives in memory.heuristic_store."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    when_to_use: str = ""
    domain: str = ""
    score: float = 0.0  # match score, filled by caller


# ---------------------------------------------------------------------------
# Injection output (what Workflows feed to the LLM)
# ---------------------------------------------------------------------------


class InjectionBundle(BaseModel):
    """Output of the Injector.

    `system_additions` is appended to the system prompt.
    `tool_specs`       is passed to the LLM's tool-calling interface.
    `script_index`     maps tool_name → absolute script path, so the
                       Executor can locate the file to run.
    """

    model_config = ConfigDict(extra="forbid")

    system_additions: str
    tool_specs: list[Any] = Field(
        default_factory=list
    )  # list[ToolSpec] (avoid cross-module import)
    script_index: dict[str, Path] = Field(default_factory=dict)
    matched_skills: list[str] = Field(default_factory=list)
    truncated: bool = False


# ---------------------------------------------------------------------------
# Execution result
# ---------------------------------------------------------------------------


class ExecResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_name: str
    returncode: int
    stdout: str
    stderr: str
    stdout_path: Path | None = None
    artifacts: list[Path] = Field(default_factory=list)
    duration_ms: float
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out


__all__ = [
    "ExecResult",
    "HeuristicSkill",
    "InjectionBundle",
    "ScriptMeta",
    "SkillMeta",
]
