from pathlib import Path

import pytest

from backend.core.skill_host.loader import SkillLoader

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "skills"


@pytest.mark.asyncio
async def test_loads_fixture_skills():
    loader = SkillLoader(FIXTURES)
    reg = await loader.load_all()
    names = {s.name for s in reg.snapshot()}
    # echo-test, sleep-test, exclusive-alt are valid; bad-frontmatter is skipped
    assert "echo-test" in names
    assert "sleep-test" in names
    assert "exclusive-alt" in names
    assert "bad-frontmatter" not in names


@pytest.mark.asyncio
async def test_frontmatter_fields_extracted():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    echo = loader.registry.get("echo-test")
    assert echo is not None
    assert echo.description.startswith("Test-only skill:")
    assert echo.domain == "test"
    assert "echo" in echo.triggers
    assert echo.version == "1.0.0"
    assert echo.exclusive is False


@pytest.mark.asyncio
async def test_scripts_parsed_from_scripts_dir():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    echo = loader.registry.get("echo-test")
    assert echo is not None
    assert len(echo.scripts) == 1
    sc = echo.scripts[0]
    assert sc.name == "echo"
    assert "Echo the input message" in sc.description
    # magic comments
    assert sc.max_duration_s == 10
    assert sc.requires_network is False
    assert sc.args_schema == {"message": "string"}


@pytest.mark.asyncio
async def test_exclusive_flag_parsed():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    sleep = loader.registry.get("sleep-test")
    assert sleep is not None
    assert sleep.exclusive is True
    alt = loader.registry.get("exclusive-alt")
    assert alt is not None
    assert alt.exclusive is True


@pytest.mark.asyncio
async def test_missing_skills_root_is_warned_not_raised(tmp_path):
    loader = SkillLoader(tmp_path / "does_not_exist")
    reg = await loader.load_all()
    assert reg.snapshot() == []


@pytest.mark.asyncio
async def test_reload_single_skill(tmp_path):
    # Copy a subset into a writable dir so we can mutate.
    import shutil

    dst = tmp_path / "skills"
    dst.mkdir()
    shutil.copytree(FIXTURES / "echo-test", dst / "echo-test")

    loader = SkillLoader(dst)
    await loader.load_all()
    assert loader.registry.get("echo-test") is not None
    gen0 = loader.registry.generation

    # Delete the skill directory and reload by name → should drop it.
    shutil.rmtree(dst / "echo-test")
    await loader.reload("echo-test")
    assert loader.registry.get("echo-test") is None
    assert loader.registry.generation > gen0


@pytest.mark.asyncio
async def test_generation_counter_advances():
    loader = SkillLoader(FIXTURES)
    await loader.load_all()
    g1 = loader.registry.generation
    await loader.load_all()
    g2 = loader.registry.generation
    assert g2 > g1
