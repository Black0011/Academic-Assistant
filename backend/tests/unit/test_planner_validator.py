"""Unit tests for ``backend.planner.validator`` (M8.2).

The validator is pure-python, so we exercise every code path with hand-
crafted DAGs. Tool / skill name resolution is verified with a lightweight
fake registry pair.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from backend.planner.models import PlanDAG, PlanNode
from backend.planner.validator import validate_plan


@dataclass
class _FakeTools:
    _names: list[str]

    def names(self) -> list[str]:
        return list(self._names)


@dataclass
class _FakeSkillMeta:
    name: str


@dataclass
class _FakeSkillHost:
    skills: Iterable[_FakeSkillMeta]

    def list_skills(self) -> list[_FakeSkillMeta]:
        return list(self.skills)


def _plan(*nodes: PlanNode, query: str = "demo") -> PlanDAG:
    return PlanDAG(query=query, nodes=list(nodes))


def test_valid_simple_plan_passes() -> None:
    plan = _plan(
        PlanNode(id="a", kind="memory.read", args={"query": "x"}),
        PlanNode(id="b", kind="llm", depends_on=["a"], description="summarise"),
    )
    res = validate_plan(plan)
    assert res.ok is True
    assert res.errors == []


def test_duplicate_id_is_error() -> None:
    plan = _plan(
        PlanNode(id="a", kind="llm", description="x"),
        PlanNode(id="a", kind="llm", description="y"),
    )
    res = validate_plan(plan)
    assert res.ok is False
    assert any("duplicate node id" in e for e in res.errors)


def test_missing_dependency_is_error() -> None:
    plan = _plan(PlanNode(id="a", kind="llm", depends_on=["ghost"], description="x"))
    res = validate_plan(plan)
    assert res.ok is False
    assert any("ghost" in e for e in res.errors)


def test_self_loop_is_error() -> None:
    plan = _plan(PlanNode(id="a", kind="llm", depends_on=["a"], description="x"))
    res = validate_plan(plan)
    assert res.ok is False
    assert any("itself" in e for e in res.errors)


def test_cycle_is_detected() -> None:
    plan = _plan(
        PlanNode(id="a", kind="llm", depends_on=["b"], description="x"),
        PlanNode(id="b", kind="llm", depends_on=["a"], description="y"),
    )
    res = validate_plan(plan)
    assert res.ok is False
    assert any("cycle" in e for e in res.errors)


def test_unknown_tool_name_is_error_when_registry_present() -> None:
    plan = _plan(
        PlanNode(id="a", kind="tool", name="ghost__op", args={"q": "x"}),
        PlanNode(id="b", kind="llm", depends_on=["a"], description="x"),
    )
    tools = _FakeTools(_names=["arxiv__search", "pdf__parse"])
    res = validate_plan(plan, tools=tools)
    assert res.ok is False
    assert any("ghost__op" in e for e in res.errors)


def test_known_tool_name_is_accepted() -> None:
    plan = _plan(
        PlanNode(id="a", kind="tool", name="arxiv__search", args={"q": "x"}),
        PlanNode(id="b", kind="llm", depends_on=["a"], description="x"),
    )
    tools = _FakeTools(_names=["arxiv__search", "pdf__parse"])
    res = validate_plan(plan, tools=tools)
    assert res.ok is True


def test_unknown_skill_name_is_error_when_host_present() -> None:
    plan = _plan(
        PlanNode(id="a", kind="skill", name="aaf-ghost", args={}),
        PlanNode(id="b", kind="llm", depends_on=["a"], description="x"),
    )
    host = _FakeSkillHost(skills=[_FakeSkillMeta(name="aaf-real")])
    res = validate_plan(plan, skill_host=host)
    assert res.ok is False
    assert any("aaf-ghost" in e for e in res.errors)


def test_memory_write_requires_kind() -> None:
    plan = _plan(
        PlanNode(id="a", kind="memory.write", args={"text": "note"}),
    )
    res = validate_plan(plan)
    assert res.ok is False
    assert any("memory.write" in e and "kind" in e for e in res.errors)


def test_empty_plan_warns_only() -> None:
    res = validate_plan(PlanDAG(query="empty", nodes=[]))
    assert res.ok is True
    assert any("no nodes" in w for w in res.warnings)
