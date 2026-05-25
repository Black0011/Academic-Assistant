"""Planner DAG subsystem (M8.2).

Composes three pieces:

* :class:`PlannerCompiler` turns a free-form user query into a
  serializable :class:`PlanDAG` of skill / tool / LLM / memory nodes.
  When an LLM provider is configured it asks the model to emit JSON;
  otherwise (or on parse failure) it falls back to a single-node plan
  so callers can always trust the return shape.
* :func:`validate_plan` ensures the DAG is internally consistent
  (unique ids, dependencies present, acyclic, references known
  skills / tools, retries / on_failure within bounds). Routers re-run
  this before every execute call as the safety gate.
* :class:`DAGExecutor` runs the plan layer by layer with bounded
  parallelism, emitting standard workflow events so the existing SSE
  infrastructure in ``backend.tasks`` can stream them to clients.

See PLAN.md §20.9 (M8.2) for the full design + DoD.
"""

from .compiler import PlannerCompiler
from .executor import DAGExecutor
from .models import (
    CompilePlanInput,
    ExecutePlanInput,
    NodeKind,
    NodeOutcome,
    OnFailure,
    PlanDAG,
    PlanNode,
    ValidatePlanInput,
    ValidatePlanResponse,
    new_node_id,
    new_plan_id,
)
from .validator import validate_plan

__all__ = [
    "CompilePlanInput",
    "DAGExecutor",
    "ExecutePlanInput",
    "NodeKind",
    "NodeOutcome",
    "OnFailure",
    "PlanDAG",
    "PlanNode",
    "PlannerCompiler",
    "ValidatePlanInput",
    "ValidatePlanResponse",
    "new_node_id",
    "new_plan_id",
    "validate_plan",
]
