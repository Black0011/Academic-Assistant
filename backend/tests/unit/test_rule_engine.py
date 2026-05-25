from pathlib import Path

import pytest

from backend.core.rule_engine import Action, Block, Rule, RuleEngine

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "rules"


def _loaded() -> RuleEngine:
    engine = RuleEngine()
    engine.load(FIXTURES)
    return engine


def test_load_skips_broken_rule():
    engine = _loaded()
    names = {r.name for r in engine.rules()}
    assert "broken" not in names
    assert {
        "always-prompt",
        "planner-only",
        "block-dangerous",
        "annotate-writes",
        "cursor-compat",
    } <= names


def test_priority_sort_descending():
    engine = _loaded()
    priorities = [r.priority for r in engine.rules()]
    assert priorities == sorted(priorities, reverse=True)
    # block-dangerous has priority 100 → first
    assert engine.rules()[0].name == "block-dangerous"


def test_cursor_compat_defaults():
    engine = _loaded()
    rule = next(r for r in engine.rules() if r.name == "cursor-compat")
    assert rule.scope == ["all"]
    assert rule.enforcement == "prompt"


def test_system_prompt_includes_only_prompt_rules():
    engine = _loaded()
    prompt = engine.system_prompt(agent="all")
    assert "always-prompt" in prompt
    assert "cursor-compat" in prompt
    # planner-only should NOT appear when agent='all' isn't in its scope
    assert "planner-only" not in prompt
    # hook rules never appear in the prompt
    assert "block-dangerous" not in prompt
    assert "annotate-writes" not in prompt


def test_system_prompt_scope_filters_by_agent():
    engine = _loaded()
    planner_prompt = engine.system_prompt(agent="planner")
    assert "planner-only" in planner_prompt
    assert "always-prompt" in planner_prompt  # scope=all → every agent


def test_system_prompt_empty_when_nothing_applies():
    engine = RuleEngine()
    assert engine.system_prompt(agent="planner") == ""


@pytest.mark.asyncio
async def test_pre_action_mutates_via_annotate_hook():
    engine = _loaded()
    action = Action(type="write_file", payload={"path": "x.txt"})
    result = await engine.pre_action("executor", action)
    assert isinstance(result, Action)
    assert result.payload.get("annotated") is True


@pytest.mark.asyncio
async def test_pre_action_block_stops_hook_chain():
    engine = _loaded()
    # block-dangerous has priority 100, annotate-writes has 50.
    # Block should fire first for a dangerous write.
    action = Action(type="write_file", payload={"dangerous": True})
    result = await engine.pre_action("executor", action)
    assert isinstance(result, Block)
    assert result.rule == "block-dangerous"
    assert "dangerous" in result.reason


@pytest.mark.asyncio
async def test_pre_action_ignores_nonmatching_scope():
    engine = _loaded()
    # Register a planner-scoped hook; it should NOT fire for executor agent.
    called = False

    async def spy(action, ctx):
        nonlocal called
        called = True
        return action

    engine._rules.append(
        Rule(name="planner-spy", scope=["planner"], enforcement="hook", hook="x.y")
    )
    engine.register_hook("planner-spy", spy)
    await engine.pre_action("executor", Action(type="anything"))
    assert called is False


@pytest.mark.asyncio
async def test_import_based_hook_resolution():
    """A rule with a real dotted import path is resolved automatically."""
    engine = _loaded()
    # annotate-writes is declared in the fixture file with an import path.
    names = {r.name for r in engine.rules() if r.enforcement == "hook"}
    assert "annotate-writes" in names
    # The hook must be callable after load.
    action = Action(type="write_file", payload={})
    res = await engine.pre_action("all", action)
    assert isinstance(res, Action)
    assert res.payload["annotated"] is True


@pytest.mark.asyncio
async def test_missing_hook_import_drops_rule(tmp_path):
    bad_rule = tmp_path / "bad-hook.md"
    bad_rule.write_text(
        "---\nname: bad-hook\nenforcement: hook\nhook: this.module.does.not.exist\n---\nBody\n",
        encoding="utf-8",
    )
    engine = RuleEngine()
    engine.load(tmp_path)
    assert all(r.name != "bad-hook" for r in engine.rules())


def test_missing_root_returns_empty():
    engine = RuleEngine()
    engine.load(Path("/tmp/aaf_does_not_exist_xyzzy"))
    assert engine.rules() == []
