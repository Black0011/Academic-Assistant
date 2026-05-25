"""Unit tests for ``backend.planner.compiler`` (M8.2)."""

from __future__ import annotations

import pytest

from backend.core.llm.mock import MockLLMProvider
from backend.planner.compiler import (
    PlannerCompiler,
    _coerce_to_plan,
    _extract_json_object,
)

_VALID_JSON = """
{
  "rationale": "search arxiv, parse results, summarise",
  "nodes": [
    {"id": "a", "kind": "memory.read", "args": {"query": "transformers"}},
    {"id": "b", "kind": "tool", "name": "arxiv__search",
     "args": {"query": "transformers"}, "depends_on": ["a"]},
    {"id": "c", "kind": "llm", "depends_on": ["b"], "description": "summarise"}
  ]
}
"""


def test_extract_json_object_handles_markdown_fences() -> None:
    text = "```json\n" + _VALID_JSON.strip() + "\n```"
    parsed = _extract_json_object(text)
    assert parsed is not None
    assert "nodes" in parsed
    assert len(parsed["nodes"]) == 3


def test_extract_json_object_handles_prose_prefix() -> None:
    text = "Here is the plan:\n" + _VALID_JSON
    parsed = _extract_json_object(text)
    assert parsed is not None


def test_extract_json_object_returns_none_on_garbage() -> None:
    assert _extract_json_object("just words, no braces here") is None
    assert _extract_json_object("") is None


def test_coerce_to_plan_drops_invalid_nodes() -> None:
    envelope = {
        "rationale": "x",
        "nodes": [
            {"id": "ok", "kind": "memory.read"},
            {"id": "broken", "kind": "what_is_this"},
            42,  # invalid type
        ],
    }
    plan = _coerce_to_plan(envelope, query="q", domain="", provider="mock")
    assert plan is not None
    assert {n.id for n in plan.nodes} == {"ok"}


@pytest.mark.asyncio
async def test_compile_returns_fallback_when_no_llm() -> None:
    compiler = PlannerCompiler(llm=None, skill_host=None, tools=None)
    plan = await compiler.compile(query="how do diffusion models work?")
    assert len(plan.nodes) >= 1
    assert plan.extras.get("fallback") is True


@pytest.mark.asyncio
async def test_compile_uses_llm_response_when_valid() -> None:
    mock = MockLLMProvider().queue_text(_VALID_JSON.strip())
    compiler = PlannerCompiler(llm=mock, skill_host=None, tools=None)
    plan = await compiler.compile(query="transformers")
    assert len(plan.nodes) == 3
    assert {n.id for n in plan.nodes} == {"a", "b", "c"}
    assert plan.llm_provider == "mock"
    assert plan.extras.get("fallback") is None


@pytest.mark.asyncio
async def test_compile_falls_back_when_llm_emits_garbage() -> None:
    mock = MockLLMProvider().queue_text("I cannot decide.")
    compiler = PlannerCompiler(llm=mock, skill_host=None, tools=None)
    plan = await compiler.compile(query="x")
    assert plan.extras.get("fallback") is True
    assert plan.llm_provider == "mock"


@pytest.mark.asyncio
async def test_compile_truncates_to_max_nodes() -> None:
    huge = {
        "rationale": "many nodes",
        "nodes": [{"id": f"n{i}", "kind": "llm", "description": "x"} for i in range(20)],
    }
    import json as _json

    mock = MockLLMProvider().queue_text(_json.dumps(huge))
    compiler = PlannerCompiler(llm=mock, skill_host=None, tools=None)
    plan = await compiler.compile(query="x", max_nodes=5)
    assert len(plan.nodes) == 5
