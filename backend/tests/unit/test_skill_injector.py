from pathlib import Path

import pytest

from backend.core.skill_host.injector import SkillInjector
from backend.core.skill_host.loader import SkillLoader
from backend.core.skill_host.matcher import MatchResult, SkillMatcher
from backend.core.skill_host.types import HeuristicSkill

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


@pytest.mark.asyncio
async def _matches_for(query: str) -> list[MatchResult]:
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    matcher = SkillMatcher(loader.registry, embedder=None)
    return await matcher.match(query, top_k=5)


@pytest.mark.asyncio
async def test_system_additions_contains_skill_sections():
    matches = await _matches_for("echo this")
    bundle = SkillInjector().inject(matches)
    assert "# Skills" in bundle.system_additions
    assert "echo-test" in bundle.system_additions
    assert "echo-test" in bundle.matched_skills


@pytest.mark.asyncio
async def test_tool_specs_use_convention_name():
    matches = await _matches_for("echo this")
    bundle = SkillInjector().inject(matches)
    tool_names = {t.name for t in bundle.tool_specs}
    assert "echo-test__echo" in tool_names
    assert bundle.script_index["echo-test__echo"].name == "echo.py"


@pytest.mark.asyncio
async def test_heuristics_section_is_rendered():
    matches = await _matches_for("echo this")
    heuristics = [
        HeuristicSkill(
            id="h1",
            name="Prefer short abstracts",
            description="Summaries < 200 words tend to be cited more.",
            when_to_use="During paper-reading first-pass.",
            domain="research",
        )
    ]
    bundle = SkillInjector().inject(matches, heuristics=heuristics)
    assert "⚡ Learned strategies" in bundle.system_additions
    assert "Prefer short abstracts" in bundle.system_additions


@pytest.mark.asyncio
async def test_token_budget_truncation():
    matches = await _matches_for("echo this")
    # Tiny budget → definitely forces truncation
    injector = SkillInjector(token_budget=5)
    bundle = injector.inject(matches)
    assert bundle.truncated is True
    # At least no exceptions; matched_skills may be empty
    assert isinstance(bundle.system_additions, str)


@pytest.mark.asyncio
async def test_empty_matches_produces_empty_tools():
    bundle = SkillInjector().inject([])
    assert bundle.tool_specs == []
    assert bundle.script_index == {}
    assert bundle.matched_skills == []


@pytest.mark.asyncio
async def test_parameters_from_args_schema():
    matches = await _matches_for("echo this")
    bundle = SkillInjector().inject(matches)
    echo_spec = next(t for t in bundle.tool_specs if t.name == "echo-test__echo")
    assert echo_spec.parameters == {"message": "string"}
