from backend.core.llm.telemetry import (
    Record,
    estimate_cost_usd,
    record,
    recorder,
)


def test_known_pricing_openai_gpt4o_mini():
    # 1M input tokens → $0.15, 1M output → $0.60
    cost = estimate_cost_usd(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )
    assert cost is not None
    assert abs(cost - 0.75) < 1e-9


def test_unknown_model_returns_none():
    cost = estimate_cost_usd(
        provider="openai",
        model="fictional-gpt",
        prompt_tokens=100,
        completion_tokens=100,
    )
    assert cost is None


def test_ollama_default_zero():
    cost = estimate_cost_usd(
        provider="ollama",
        model="whatever",
        prompt_tokens=1_000_000,
        completion_tokens=1_000_000,
    )
    assert cost == 0.0


def test_recorder_totals_accumulate():
    r = recorder()
    r.reset()
    record(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50,
        cost_usd=0.001,
        duration_ms=123.0,
    )
    record(
        provider="openai",
        model="gpt-4o-mini",
        prompt_tokens=200,
        completion_tokens=100,
        cost_usd=0.002,
        duration_ms=456.0,
    )
    totals = r.totals()
    assert totals["calls"] == 2
    assert totals["prompt_tokens"] == 300
    assert totals["completion_tokens"] == 150
    assert abs(totals["cost_usd"] - 0.003) < 1e-9


def test_recorder_ring_buffer_bounded():
    from backend.core.llm.telemetry import TelemetryRecorder

    r = TelemetryRecorder(max_records=3)
    for i in range(5):
        r.record(
            Record(
                provider="p",
                model="m",
                task_id=None,
                prompt_tokens=i,
                completion_tokens=0,
                duration_ms=0.0,
                cost_usd=0.0,
            )
        )
    assert len(r.records()) == 3
    # oldest dropped → prompt_tokens starts at 2
    assert [rec.prompt_tokens for rec in r.records()] == [2, 3, 4]
