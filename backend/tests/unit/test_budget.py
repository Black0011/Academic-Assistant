import time

import pytest

from backend.core.budget import Budget
from backend.core.errors import BudgetExceededError


def test_no_limits_never_raises():
    b = Budget()
    b.accrue_llm(prompt_tokens=1_000_000, completion_tokens=1_000_000, cost_usd=1000.0)
    b.assert_ok()


def test_prompt_token_limit_triggers():
    b = Budget(max_prompt_tokens=100)
    b.accrue_llm(prompt_tokens=99)
    b.assert_ok()
    b.accrue_llm(prompt_tokens=2)
    with pytest.raises(BudgetExceededError) as ei:
        b.assert_ok()
    assert ei.value.context["kind"] == "prompt_tokens"
    assert ei.value.context["limit"] == 100


def test_total_token_limit_includes_both_sides():
    b = Budget(max_total_tokens=50)
    b.accrue_llm(prompt_tokens=40, completion_tokens=15)
    with pytest.raises(BudgetExceededError) as ei:
        b.assert_ok()
    assert ei.value.context["kind"] == "total_tokens"


def test_cost_limit_triggers():
    b = Budget(max_cost_usd=0.01)
    b.accrue_llm(cost_usd=0.02)
    with pytest.raises(BudgetExceededError) as ei:
        b.assert_ok()
    assert ei.value.context["kind"] == "cost_usd"


def test_wallclock_limit_triggers(monkeypatch):
    b = Budget(max_wallclock_s=0.001)
    time.sleep(0.05)
    with pytest.raises(BudgetExceededError) as ei:
        b.assert_ok()
    assert ei.value.context["kind"] == "wallclock_s"


def test_negative_accruals_are_clamped():
    b = Budget()
    b.accrue_llm(prompt_tokens=-10, completion_tokens=-5, cost_usd=-1)
    assert b.prompt_tokens == 0
    assert b.completion_tokens == 0
    assert b.cost_usd == 0.0


def test_snapshot_contains_expected_keys():
    b = Budget()
    b.accrue_llm(prompt_tokens=10, completion_tokens=2, cost_usd=0.005)
    snap = b.snapshot()
    assert snap["prompt_tokens"] == 10
    assert snap["completion_tokens"] == 2
    assert snap["total_tokens"] == 12
    assert snap["cost_usd"] == 0.005
    assert "elapsed_s" in snap
