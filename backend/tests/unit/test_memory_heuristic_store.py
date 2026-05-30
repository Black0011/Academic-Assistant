import pytest

from backend.core.errors import MemoryNotFound
from backend.memory import (
    Heuristic,
    InMemoryHeuristicStore,
    StrategyBlock,
    YamlHeuristicStore,
)


def _mk(id_: str, *, domain: str = "research", trigger: str = "", **extra) -> Heuristic:
    return Heuristic(
        id=id_,
        name=extra.pop("name", f"skill-{id_}"),
        domain=domain,  # type: ignore[arg-type]
        trigger_pattern=trigger,
        strategy=StrategyBlock(planning_hints="do this"),
        source_run_id=extra.pop("source_run_id", ""),
        **extra,
    )


# ---------- in-memory -----------------------------------------------------


@pytest.mark.asyncio
async def test_inmem_add_get_domain():
    s = InMemoryHeuristicStore()
    h = _mk("a" * 12, domain="research", trigger="rlhf, reward model")
    await s.add(h)
    assert (await s.get(h.id)) is not None
    assert len(await s.list_by_domain("research")) == 1


@pytest.mark.asyncio
async def test_inmem_match_keyword():
    s = InMemoryHeuristicStore()
    await s.add(_mk("a" * 12, trigger="rlhf, reward model"))
    await s.add(_mk("b" * 12, trigger="writing, survey"))
    hits = await s.match("how to train a reward model for rlhf", domain="research")
    assert hits and hits[0].id.startswith("a")


@pytest.mark.asyncio
async def test_inmem_match_respects_domain():
    s = InMemoryHeuristicStore()
    await s.add(_mk("a" * 12, domain="research", trigger="alpha"))
    await s.add(_mk("b" * 12, domain="writing", trigger="alpha"))
    hits = await s.match("alpha", domain="writing")
    assert [h.id for h in hits] == ["b" * 12]


@pytest.mark.asyncio
async def test_inmem_freeze_excluded_from_match():
    s = InMemoryHeuristicStore()
    await s.add(_mk("a" * 12, trigger="alpha"))
    await s.freeze("a" * 12)
    assert await s.match("alpha", domain="research") == []


@pytest.mark.asyncio
async def test_inmem_bump_counters_update_and_timestamp():
    s = InMemoryHeuristicStore()
    h = _mk("a" * 12, trigger="alpha")
    await s.add(h)
    await s.bump_success("a" * 12)
    await s.bump_failure("a" * 12)
    updated = await s.get("a" * 12)
    assert updated is not None
    assert updated.success_count == 2  # starts at 1
    assert updated.failure_count == 1


@pytest.mark.asyncio
async def test_inmem_freeze_missing_raises():
    s = InMemoryHeuristicStore()
    with pytest.raises(MemoryNotFound):
        await s.freeze("z" * 12)


@pytest.mark.asyncio
async def test_inmem_rollback_run():
    s = InMemoryHeuristicStore()
    await s.add(_mk("a" * 12, source_run_id="run-1"))
    await s.add(_mk("b" * 12, source_run_id="run-2"))
    assert (await s.rollback_run("run-1")) == 1
    assert (await s.get("a" * 12)) is None
    assert (await s.get("b" * 12)) is not None


# ---------- YAML ----------------------------------------------------------


@pytest.mark.asyncio
async def test_yaml_persists_and_reloads(tmp_path):
    s = YamlHeuristicStore(tmp_path)
    await s.add(_mk("a" * 12, domain="research", trigger="rlhf, reward"))
    assert (tmp_path / "research" / f"skill_{'a' * 12}.yaml").exists()
    assert (tmp_path / "research" / "_index.yaml").exists()

    s2 = YamlHeuristicStore(tmp_path)
    assert (await s2.get("a" * 12)) is not None


@pytest.mark.asyncio
async def test_yaml_index_reflects_updates(tmp_path):
    import yaml as _yaml

    s = YamlHeuristicStore(tmp_path)
    await s.add(_mk("a" * 12, trigger="alpha"))
    await s.bump_success("a" * 12)
    idx = _yaml.safe_load((tmp_path / "research" / "_index.yaml").read_text())
    assert idx["skills"]["a" * 12]["success_count"] == 2


@pytest.mark.asyncio
async def test_yaml_delete_removes_file(tmp_path):
    s = YamlHeuristicStore(tmp_path)
    await s.add(_mk("a" * 12, trigger="alpha"))
    assert await s.delete("a" * 12)
    assert not (tmp_path / "research" / f"skill_{'a' * 12}.yaml").exists()


@pytest.mark.asyncio
async def test_yaml_rollback_across_domains(tmp_path):
    s = YamlHeuristicStore(tmp_path)
    await s.add(_mk("a" * 12, domain="research", source_run_id="r1"))
    await s.add(_mk("b" * 12, domain="writing", source_run_id="r1"))
    await s.add(_mk("c" * 12, domain="research", source_run_id="r2"))
    removed = await s.rollback_run("r1")
    assert removed == 2
    assert (await s.get("a" * 12)) is None
    assert (await s.get("b" * 12)) is None
    assert (await s.get("c" * 12)) is not None
