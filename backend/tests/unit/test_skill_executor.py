import json
from pathlib import Path

import pytest

from backend.core.errors import SkillNotFound, SkillTimeout
from backend.core.skill_host.executor import SkillExecutor

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"
ECHO_SCRIPT = FIXTURES / "echo-test" / "scripts" / "echo.py"
SLEEP_SCRIPT = FIXTURES / "sleep-test" / "scripts" / "sleep.py"


@pytest.mark.asyncio
async def test_runs_script_and_returns_stdout(tmp_path):
    ex = SkillExecutor(workdir_root=tmp_path)
    result = await ex.run(
        script_path=ECHO_SCRIPT,
        args={"message": "hello world"},
        tool_name="echo-test__echo",
        task_id="t1",
    )
    assert result.ok
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["echoed"] == "hello world"


@pytest.mark.asyncio
async def test_collects_artifacts(tmp_path):
    ex = SkillExecutor(workdir_root=tmp_path)
    result = await ex.run(
        script_path=ECHO_SCRIPT,
        args={"message": "artifact please"},
        tool_name="echo-test__echo",
        task_id="t2",
    )
    assert len(result.artifacts) == 1
    assert result.artifacts[0].name == "echo.txt"
    assert result.artifacts[0].read_text() == "artifact please"


@pytest.mark.asyncio
async def test_missing_script_raises(tmp_path):
    ex = SkillExecutor(workdir_root=tmp_path)
    with pytest.raises(SkillNotFound):
        await ex.run(
            script_path=tmp_path / "does_not_exist.py",
            args={},
            tool_name="x__nope",
            task_id="t3",
        )


@pytest.mark.asyncio
async def test_timeout_kills_process(tmp_path):
    ex = SkillExecutor(workdir_root=tmp_path, default_timeout_s=1)
    with pytest.raises(SkillTimeout) as ei:
        await ex.run(
            script_path=SLEEP_SCRIPT,
            args={"seconds": 10},
            tool_name="sleep-test__sleep",
            task_id="t4",
            timeout_s=1,
        )
    # Error carries the partial result for debuggability
    partial = ei.value.context.get("partial_result")
    assert partial is not None
    assert partial["timed_out"] is True


@pytest.mark.asyncio
async def test_env_whitelist_hides_secrets(tmp_path, monkeypatch):
    # Add a fake secret env; the script should NOT see it.
    monkeypatch.setenv("AAF_SECRET_SHOULD_NOT_LEAK", "dont-leak-me")
    ex = SkillExecutor(workdir_root=tmp_path)
    # Write a tiny script that dumps os.environ
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import json, os, sys; sys.stdout.write(json.dumps(dict(os.environ)))",
        encoding="utf-8",
    )
    result = await ex.run(
        script_path=probe,
        args={},
        tool_name="x__probe",
        task_id="t5",
    )
    env = json.loads(result.stdout)
    assert "AAF_SECRET_SHOULD_NOT_LEAK" not in env
    assert env["AAF_TASK_ID"] == "t5"
    assert "AAF_WORKDIR" in env


@pytest.mark.asyncio
async def test_llm_endpoint_gated(tmp_path):
    ex = SkillExecutor(
        workdir_root=tmp_path,
        extra_env={"AAF_LLM_ENDPOINT": "http://example"},
    )
    probe = tmp_path / "probe2.py"
    probe.write_text(
        "import json, os, sys; sys.stdout.write(json.dumps(dict(os.environ)))",
        encoding="utf-8",
    )
    # uses_llm=False → AAF_LLM_ENDPOINT should not be injected
    r1 = await ex.run(script_path=probe, args={}, tool_name="x__p", task_id="t6", uses_llm=False)
    assert "AAF_LLM_ENDPOINT" not in json.loads(r1.stdout)

    # uses_llm=True → injected
    r2 = await ex.run(script_path=probe, args={}, tool_name="x__p", task_id="t7", uses_llm=True)
    assert json.loads(r2.stdout)["AAF_LLM_ENDPOINT"] == "http://example"


@pytest.mark.asyncio
async def test_nonzero_exit_captured(tmp_path):
    ex = SkillExecutor(workdir_root=tmp_path)
    failing = tmp_path / "fail.py"
    failing.write_text(
        "import sys; sys.stderr.write('boom'); sys.exit(7)",
        encoding="utf-8",
    )
    result = await ex.run(script_path=failing, args={}, tool_name="x__fail", task_id="t8")
    assert result.returncode == 7
    assert "boom" in result.stderr
    assert not result.ok
