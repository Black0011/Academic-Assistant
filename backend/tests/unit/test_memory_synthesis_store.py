"""Synthesis note CRUD on both InMemory and YAML KnowledgeStore."""

import pytest

from backend.memory import (
    InMemoryKnowledgeStore,
    SynthesisNote,
    YamlKnowledgeStore,
)


def _note(tag: str = "rlhf", *, version: int = 1, **kw) -> SynthesisNote:
    return SynthesisNote(
        cluster_tag=tag,
        version=version,
        paper_ids=kw.pop("paper_ids", ["p1", "p2"]),
        content=kw.pop("content", f"synthesis for {tag}"),
        summary=kw.pop("summary", f"n={2}"),
        **kw,
    )


# ---------- in-memory -----------------------------------------------------


@pytest.mark.asyncio
async def test_inmem_synth_roundtrip():
    s = InMemoryKnowledgeStore()
    await s.write_synthesis(_note())
    got = await s.get_synthesis("rlhf")
    assert got is not None and got.content == "synthesis for rlhf"


@pytest.mark.asyncio
async def test_inmem_synth_version_bumps_when_same_or_older():
    s = InMemoryKnowledgeStore()
    await s.write_synthesis(_note(version=1))
    # A second write with version<=current must bump to current+1.
    await s.write_synthesis(_note(version=1, content="v2"))
    got = await s.get_synthesis("rlhf")
    assert got is not None
    assert got.version == 2
    assert got.content == "v2"


@pytest.mark.asyncio
async def test_inmem_synth_respects_explicit_higher_version():
    s = InMemoryKnowledgeStore()
    await s.write_synthesis(_note(version=1))
    await s.write_synthesis(_note(version=5, content="jump"))
    got = await s.get_synthesis("rlhf")
    assert got and got.version == 5


@pytest.mark.asyncio
async def test_inmem_synth_list_and_delete():
    s = InMemoryKnowledgeStore()
    await s.write_synthesis(_note("alpha"))
    await s.write_synthesis(_note("beta"))
    assert {n.cluster_tag for n in await s.list_synthesis()} == {"alpha", "beta"}
    assert await s.delete_synthesis("alpha") is True
    assert await s.delete_synthesis("alpha") is False


# ---------- YAML ----------------------------------------------------------


@pytest.mark.asyncio
async def test_yaml_synth_persists(tmp_path):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_synthesis(_note("rlhf"))
    assert (tmp_path / "_synthesis" / "rlhf.yaml").exists()

    s2 = YamlKnowledgeStore(tmp_path)
    got = await s2.get_synthesis("rlhf")
    assert got is not None
    assert got.paper_ids == ["p1", "p2"]


@pytest.mark.asyncio
async def test_yaml_synth_slugifies_unsafe_tag(tmp_path):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_synthesis(_note("path/with spaces"))
    files = list((tmp_path / "_synthesis").glob("*.yaml"))
    assert files  # written at all
    assert all("/" not in f.name for f in files)


@pytest.mark.asyncio
async def test_yaml_synth_delete_removes_file(tmp_path):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_synthesis(_note("rlhf"))
    assert await s.delete_synthesis("rlhf") is True
    assert not (tmp_path / "_synthesis" / "rlhf.yaml").exists()


@pytest.mark.asyncio
async def test_yaml_synth_does_not_bleed_into_list_all_papers(tmp_path):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_synthesis(_note("rlhf"))
    # list_all() returns paper cards; synthesis lives in a subdir so it must
    # NOT surface as a card.
    assert await s.list_all() == []
