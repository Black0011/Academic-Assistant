"""Unit tests for :mod:`backend.core.skill_host.invocations`.

Covers ring-buffer behaviour, stats over a window, and the
``SkillExecutor`` integration that records every call (success / error /
timeout / dry-run) into the store.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from backend.core.skill_host import SkillExecutor
from backend.core.skill_host.invocations import (
    InMemorySkillInvocationStore,
    SkillInvocation,
    make_invocation,
)

# ---------------------------------------------------------------------------
# Bare store
# ---------------------------------------------------------------------------


def _now_inv(
    skill: str, *, status: str = "success", at: datetime | None = None, ms: float = 50.0
) -> SkillInvocation:
    return SkillInvocation(
        skill=skill,
        script="run",
        tool_name=f"{skill}__run",
        task_id="t1",
        status=status,  # type: ignore[arg-type]
        started_at=at or datetime.now(UTC),
        duration_ms=ms,
    )


@pytest.mark.asyncio
async def test_record_then_list_returns_in_reverse_chronological_order():
    store = InMemorySkillInvocationStore()
    older = _now_inv("hello", at=datetime.now(UTC) - timedelta(minutes=10))
    newer = _now_inv("hello", at=datetime.now(UTC))
    await store.record(older)
    await store.record(newer)
    rows = await store.list_for("hello")
    assert [r.task_id for r in rows] == ["t1", "t1"]
    assert rows[0].started_at >= rows[1].started_at


@pytest.mark.asyncio
async def test_ring_buffer_evicts_oldest_per_skill():
    store = InMemorySkillInvocationStore(max_per_skill=3)
    for i in range(5):
        await store.record(_now_inv("hello", at=datetime.now(UTC) - timedelta(minutes=10 - i)))
    rows = await store.list_for("hello", limit=10)
    assert len(rows) == 3


@pytest.mark.asyncio
async def test_stats_windows_recent_only():
    store = InMemorySkillInvocationStore()
    await store.record(_now_inv("hello", at=datetime.now(UTC) - timedelta(days=45), ms=10))
    await store.record(_now_inv("hello", at=datetime.now(UTC), ms=200))
    stats = await store.stats("hello", window_days=30)
    assert stats.invocation_count_30d == 1
    assert stats.avg_elapsed_ms == 200
    assert stats.last_used_at is not None


@pytest.mark.asyncio
async def test_stats_falls_back_to_latest_when_window_empty():
    store = InMemorySkillInvocationStore()
    older = datetime.now(UTC) - timedelta(days=90)
    await store.record(_now_inv("hello", at=older, ms=10, status="error"))
    stats = await store.stats("hello", window_days=7)
    assert stats.invocation_count_30d == 0
    assert stats.last_used_at == older
    assert stats.last_status == "error"


@pytest.mark.asyncio
async def test_list_filters_by_since():
    store = InMemorySkillInvocationStore()
    older = datetime.now(UTC) - timedelta(days=10)
    newer = datetime.now(UTC) - timedelta(hours=1)
    await store.record(_now_inv("hello", at=older))
    await store.record(_now_inv("hello", at=newer))
    rows = await store.list_for("hello", since=datetime.now(UTC) - timedelta(days=1))
    assert len(rows) == 1
    assert rows[0].started_at == newer


def test_make_invocation_truncates_long_args():
    long = "a" * 10_000
    inv = make_invocation(
        skill="x",
        script="r",
        tool_name="x__r",
        task_id="t",
        status="success",
        started_at=time.time(),
        duration_ms=1.0,
        args={"data": long},
        result_text="",
    )
    assert len(inv.args_summary) <= 280


# ---------------------------------------------------------------------------
# Executor integration: every call records exactly one row
# ---------------------------------------------------------------------------


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


@pytest.mark.asyncio
async def test_executor_records_success(tmp_path: Path):
    store = InMemorySkillInvocationStore()
    executor = SkillExecutor(workdir_root=tmp_path, invocations=store)
    script = FIXTURES / "echo-test" / "scripts" / "echo.py"
    result = await executor.run(
        script_path=script,
        args={"message": "hi"},
        tool_name="echo-test__echo",
        task_id="t-success",
    )
    assert result.ok
    rows = await store.list_for("echo-test")
    assert len(rows) == 1
    assert rows[0].status == "success"
    assert rows[0].tool_name == "echo-test__echo"


@pytest.mark.asyncio
async def test_executor_records_dry_run_status_separately(tmp_path: Path):
    store = InMemorySkillInvocationStore()
    executor = SkillExecutor(workdir_root=tmp_path, invocations=store)
    script = FIXTURES / "echo-test" / "scripts" / "echo.py"
    result = await executor.run(
        script_path=script,
        args={"message": "hi"},
        tool_name="echo-test__echo",
        task_id="t-dry",
        dry_run=True,
    )
    assert result.ok
    rows = await store.list_for("echo-test")
    assert rows[0].status == "dry_run"


@pytest.mark.asyncio
async def test_executor_records_timeout(tmp_path: Path):
    """A script that exceeds the timeout must be killed and recorded."""
    sleeper = tmp_path / "skill" / "scripts"
    sleeper.mkdir(parents=True)
    sleeper_script = sleeper / "sleep.py"
    sleeper_script.write_text(
        "import time, json, sys\nimport sys\ntime.sleep(5)\nsys.stdout.write(json.dumps({}))\n",
        encoding="utf-8",
    )
    store = InMemorySkillInvocationStore()
    executor = SkillExecutor(
        workdir_root=tmp_path / "wd",
        default_timeout_s=1,
        invocations=store,
    )
    from backend.core.errors import SkillTimeout

    with pytest.raises(SkillTimeout):
        await executor.run(
            script_path=sleeper_script,
            args={},
            tool_name="sleep__sleep",
            task_id="t-timeout",
            timeout_s=1,
        )
    # Allow the bookkeeping coroutine to flush before we assert.
    await asyncio.sleep(0)
    rows = await store.list_for("sleep")
    assert len(rows) == 1
    assert rows[0].status == "timeout"
