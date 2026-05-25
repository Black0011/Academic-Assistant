"""End-to-end Skill Host integration."""

import json
from pathlib import Path

import pytest

from backend.core.errors import SkillNotFound
from backend.core.llm import MockLLMProvider
from backend.core.skill_host import SkillHost

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


@pytest.mark.asyncio
async def test_select_inject_and_call(tmp_path):
    host = SkillHost.build(
        skills_root=FIXTURES,
        workdir_root=tmp_path,
        embedder=MockLLMProvider(),
    )
    await host.load()

    bundle = await host.select_and_inject("please echo this message")
    assert "echo-test" in bundle.matched_skills
    assert "echo-test__echo" in bundle.script_index

    result = await host.call_tool(
        "echo-test__echo",
        {"message": "hi"},
        task_id="task-abc",
        bundle=bundle,
    )
    assert result.ok
    assert json.loads(result.stdout)["echoed"] == "hi"


@pytest.mark.asyncio
async def test_call_tool_without_bundle_resolves_by_convention(tmp_path):
    host = SkillHost.build(skills_root=FIXTURES, workdir_root=tmp_path)
    await host.load()
    result = await host.call_tool(
        "echo-test__echo",
        {"message": "via-convention"},
        task_id="task-conv",
    )
    assert result.ok


@pytest.mark.asyncio
async def test_unknown_tool_raises(tmp_path):
    host = SkillHost.build(skills_root=FIXTURES, workdir_root=tmp_path)
    await host.load()
    with pytest.raises(SkillNotFound):
        await host.call_tool("no_such__thing", {}, task_id="task-fail")


@pytest.mark.asyncio
async def test_list_skills_excludes_malformed(tmp_path):
    host = SkillHost.build(skills_root=FIXTURES, workdir_root=tmp_path)
    await host.load()
    names = {s.name for s in host.list_skills()}
    assert "echo-test" in names
    assert "bad-frontmatter" not in names


@pytest.mark.asyncio
async def test_reload_name_individual(tmp_path):
    import shutil

    # Create a writable skills dir with just echo-test
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    shutil.copytree(FIXTURES / "echo-test", skills_dir / "echo-test")

    host = SkillHost.build(skills_root=skills_dir, workdir_root=tmp_path / "wd")
    await host.load()
    assert host.get_skill("echo-test") is not None

    # Remove the skill on disk and reload it — should drop.
    shutil.rmtree(skills_dir / "echo-test")
    await host.reload("echo-test")
    assert host.get_skill("echo-test") is None


@pytest.mark.asyncio
async def test_embedder_can_be_swapped(tmp_path):
    host = SkillHost.build(skills_root=FIXTURES, workdir_root=tmp_path)
    await host.load()
    # No embedder initially
    b1 = await host.select_and_inject("echo")
    assert b1.matched_skills  # keyword still works

    host.set_embedder(MockLLMProvider())
    b2 = await host.select_and_inject("echo")
    assert b2.matched_skills
