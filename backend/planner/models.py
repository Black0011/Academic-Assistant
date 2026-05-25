"""Pydantic models for compile / validate / execute (M8.2).

The wire shape is small on purpose. A plan is a list of nodes plus
optional metadata; nothing more. Anything fancier (CRDT-style merging,
cost estimation, etc.) belongs upstream in the compiler or downstream
in the executor.

Naming:

* ``PlanNode.id`` is unique within the plan (the executor uses it as a
  hash-map key).
* ``PlanDAG.plan_id`` is unique across plans (stamped by the compiler).
* ``NodeOutcome`` is what the executor records and emits per node.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

NodeKind = Literal["llm", "tool", "skill", "memory.read", "memory.write"]
OnFailure = Literal["abort", "skip", "continue"]
NodeStatus = Literal["pending", "running", "succeeded", "failed", "skipped"]


def new_plan_id() -> str:
    """Short, URL-safe identifier for a single compiled plan."""
    return secrets.token_hex(6)


def new_node_id(prefix: str = "n") -> str:
    """Compact node id used inside one plan."""
    return f"{prefix}_{secrets.token_hex(3)}"


class PlanNode(BaseModel):
    """One unit of work inside a :class:`PlanDAG`."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: NodeKind
    name: str = ""
    args: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list)
    description: str = ""
    expected_output: str = ""
    on_failure: OnFailure = "abort"
    retries: Annotated[int, Field(ge=0, le=5)] = 0


class PlanDAG(BaseModel):
    """A serializable DAG produced by :class:`PlannerCompiler`."""

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(default_factory=new_plan_id)
    query: str
    domain: str = ""
    nodes: list[PlanNode] = Field(default_factory=list)
    rationale: str = ""
    estimated_steps: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    llm_provider: str = ""
    extras: dict[str, Any] = Field(default_factory=dict)


class CompilePlanInput(BaseModel):
    """Body for ``POST /api/planner/compile``."""

    model_config = ConfigDict(extra="forbid")

    query: Annotated[str, Field(min_length=1)]
    domain: str = ""
    hints: list[str] = Field(default_factory=list)
    only_skills: list[str] | None = None
    only_tools: list[str] | None = None
    max_nodes: Annotated[int, Field(ge=1, le=100)] = 30


class ValidatePlanInput(BaseModel):
    """Body for ``POST /api/planner/validate``."""

    model_config = ConfigDict(extra="forbid")

    plan: PlanDAG


class ValidatePlanResponse(BaseModel):
    ok: bool
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExecutePlanInput(BaseModel):
    """Body for ``POST /api/planner/execute``."""

    model_config = ConfigDict(extra="forbid")

    plan: PlanDAG
    params: dict[str, Any] = Field(default_factory=dict)
    dry_run: bool = False
    user_id: str | None = None
    session_id: str | None = None


class NodeOutcome(BaseModel):
    """Per-node execution record streamed back via SSE + ``WorkflowOutput``."""

    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: NodeKind
    name: str = ""
    status: NodeStatus = "pending"
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int = 0
    output: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    attempts: int = 0


class SkillForCompile(BaseModel):
    """Curated skill descriptor exposed to host LLMs."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    domain: str = ""
    triggers: list[str] = Field(default_factory=list)
    invocation_modes: list[str] = Field(default_factory=list)


class ToolForCompile(BaseModel):
    """Curated tool descriptor exposed to host LLMs."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class SkillsForCompileResponse(BaseModel):
    skills: list[SkillForCompile] = Field(default_factory=list)
    tools: list[ToolForCompile] = Field(default_factory=list)


__all__ = [
    "CompilePlanInput",
    "ExecutePlanInput",
    "NodeKind",
    "NodeOutcome",
    "NodeStatus",
    "OnFailure",
    "PlanDAG",
    "PlanNode",
    "SkillForCompile",
    "SkillsForCompileResponse",
    "ToolForCompile",
    "ValidatePlanInput",
    "ValidatePlanResponse",
    "new_node_id",
    "new_plan_id",
]
