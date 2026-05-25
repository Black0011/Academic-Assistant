import pytest

from backend.core.errors import MemoryNotFound, ValidationError
from backend.memory import (
    InMemoryKnowledgeStore,
    PaperCard,
    YamlKnowledgeStore,
)


@pytest.fixture
def card_a() -> PaperCard:
    return PaperCard(
        paper_id="p_a",
        title="Alpha on RL",
        abstract="reinforcement learning approach to alignment",
        summary="uses PPO",
        source_run_id="run-1",
    )


@pytest.fixture
def card_b() -> PaperCard:
    return PaperCard(
        paper_id="p_b",
        title="Beta on cooking",
        abstract="how to bake a cake",
        source_run_id="run-2",
    )


# ---------- in-memory ------------------------------------------------------


@pytest.mark.asyncio
async def test_inmem_write_and_get(card_a: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    got = await s.get("p_a")
    assert got is not None
    assert got.title == "Alpha on RL"


@pytest.mark.asyncio
async def test_inmem_find_related_keyword(card_a: PaperCard, card_b: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    await s.write_card(card_b)
    rel = await s.find_related("reinforcement learning alignment", k=2)
    assert rel and rel[0].paper_id == "p_a"


@pytest.mark.asyncio
async def test_inmem_link_bidirectional(card_a: PaperCard, card_b: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    await s.write_card(card_b)
    await s.link("p_a", "p_b", "extends", evidence="X uses Y")
    a = await s.get("p_a")
    b = await s.get("p_b")
    assert a and b
    assert any(
        link.target_paper_id == "p_b" and link.link_type == "extends" for link in a.typed_links
    )
    # Inverse should be "motivated_by"
    assert any(
        link.target_paper_id == "p_a" and link.link_type == "motivated_by" for link in b.typed_links
    )


@pytest.mark.asyncio
async def test_inmem_link_unknown_type_rejected(card_a: PaperCard, card_b: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    await s.write_card(card_b)
    with pytest.raises(ValidationError):
        await s.link("p_a", "p_b", "mysterious")


@pytest.mark.asyncio
async def test_inmem_link_requires_both_papers(card_a: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    with pytest.raises(MemoryNotFound):
        await s.link("p_a", "missing", "extends")


@pytest.mark.asyncio
async def test_inmem_delete_scrubs_inbound(card_a: PaperCard, card_b: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    await s.write_card(card_b)
    await s.link("p_a", "p_b", "extends")
    await s.delete("p_b")
    a = await s.get("p_a")
    assert a is not None
    assert not any(link.target_paper_id == "p_b" for link in a.typed_links)


@pytest.mark.asyncio
async def test_inmem_rollback_run_removes_matching(card_a: PaperCard, card_b: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    await s.write_card(card_b)
    removed = await s.rollback_run("run-1")
    assert removed == 1
    assert await s.get("p_a") is None
    assert await s.get("p_b") is not None


@pytest.mark.asyncio
async def test_inmem_rewrite_merges_links(card_a: PaperCard, card_b: PaperCard):
    s = InMemoryKnowledgeStore()
    await s.write_card(card_a)
    await s.write_card(card_b)
    await s.link("p_a", "p_b", "extends")
    # Re-writing the same card must NOT drop the typed_links we just added.
    await s.write_card(card_a)
    a = await s.get("p_a")
    assert a and a.typed_links


# ---------- YAML ----------------------------------------------------------


@pytest.mark.asyncio
async def test_yaml_persists_to_disk(card_a: PaperCard, tmp_path):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_card(card_a)
    assert (tmp_path / "p_a.yaml").exists()

    s2 = YamlKnowledgeStore(tmp_path)
    got = await s2.get("p_a")
    assert got is not None
    assert got.title == "Alpha on RL"


@pytest.mark.asyncio
async def test_yaml_atomic_write_leaves_no_tmp(tmp_path, card_a: PaperCard):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_card(card_a)
    leftovers = list(tmp_path.glob(".aaf-*.tmp"))
    assert leftovers == []


@pytest.mark.asyncio
async def test_yaml_link_persists(tmp_path, card_a: PaperCard, card_b: PaperCard):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_card(card_a)
    await s.write_card(card_b)
    await s.link("p_a", "p_b", "contradicts", evidence="empirical gap")

    s2 = YamlKnowledgeStore(tmp_path)
    a = await s2.get("p_a")
    b = await s2.get("p_b")
    assert a and b
    assert any(link.link_type == "contradicts" for link in a.typed_links)
    # contradicts is symmetric
    assert any(link.link_type == "contradicts" for link in b.typed_links)


@pytest.mark.asyncio
async def test_yaml_rollback_cleans_cards_and_links(tmp_path, card_a: PaperCard, card_b: PaperCard):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_card(card_a)
    await s.write_card(card_b)
    await s.link("p_a", "p_b", "extends")
    removed = await s.rollback_run("run-1")
    assert removed == 1
    # p_a gone on disk
    assert not (tmp_path / "p_a.yaml").exists()
    b = await s.get("p_b")
    assert b is not None
    assert not any(link.target_paper_id == "p_a" for link in b.typed_links)


@pytest.mark.asyncio
async def test_yaml_list_all_skips_bad_files(tmp_path, card_a: PaperCard):
    s = YamlKnowledgeStore(tmp_path)
    await s.write_card(card_a)
    # Drop a corrupt yaml alongside.
    (tmp_path / "corrupt.yaml").write_text("not: [valid: yaml", encoding="utf-8")
    cards = await s.list_all()
    assert len(cards) == 1
    assert cards[0].paper_id == "p_a"


# ---------- P13 manual-CRUD metadata ---------------------------------------
#
# These four tests pin down the new ``url`` / ``field_major`` / ``field_minor``
# fields. They cover:
#
#   (1) ``search_text`` must include the taxonomy strings so recall by
#       category works even when the abstract doesn't spell out the term.
#   (2) The YAML round-trip preserves the new fields verbatim.
#   (3) Legacy YAML files written before the new fields existed continue to
#       parse — the missing keys default to ``None`` and are not an error.
#       This is the "no migration script" promise from the model docstring.
#   (4) A clear-out PATCH semantics check is integration-level (kept under
#       ``test_app_knowledge.py``); here we just confirm the model accepts
#       the explicit empty string.


def test_paper_card_search_text_includes_taxonomy():
    card = PaperCard(
        paper_id="p_c",
        title="Self-Refine: iterative self-feedback",
        abstract="we propose an iterative method",
        field_major="NLP",
        field_minor="LLM-Agent",
    )
    text = card.search_text()
    assert "NLP" in text and "LLM-Agent" in text


@pytest.mark.asyncio
async def test_yaml_round_trips_new_fields(tmp_path):
    card = PaperCard(
        paper_id="p_url",
        title="Constitutional AI",
        url="https://arxiv.org/abs/2212.08073",
        field_major="Alignment",
        field_minor="RLAIF",
    )
    s1 = YamlKnowledgeStore(tmp_path)
    await s1.write_card(card)
    s2 = YamlKnowledgeStore(tmp_path)
    got = await s2.get("p_url")
    assert got is not None
    assert got.url == "https://arxiv.org/abs/2212.08073"
    assert got.field_major == "Alignment"
    assert got.field_minor == "RLAIF"


@pytest.mark.asyncio
async def test_yaml_reads_legacy_card_without_new_fields(tmp_path):
    """A YAML file written before P13 must still load — the missing
    ``url`` / ``field_major`` / ``field_minor`` keys should resolve to
    ``None`` via the model defaults, not raise."""
    legacy = (
        "paper_id: p_legacy\n"
        "title: Pre-P13 card\n"
        "authors: []\n"
        "tags: []\n"
        "typed_links: []\n"
        "abstract: ''\n"
        "summary: ''\n"
        "method: ''\n"
        "findings: ''\n"
        "created_at: '2026-01-01T00:00:00+00:00'\n"
        "updated_at: '2026-01-01T00:00:00+00:00'\n"
    )
    (tmp_path / "p_legacy.yaml").write_text(legacy, encoding="utf-8")
    s = YamlKnowledgeStore(tmp_path)
    got = await s.get("p_legacy")
    assert got is not None
    assert got.title == "Pre-P13 card"
    assert got.url is None
    assert got.field_major is None
    assert got.field_minor is None


def test_paper_card_accepts_empty_string_clear():
    """The PATCH endpoint clears a field by sending an empty string (since
    ``exclude_none=True`` filters ``null``). The model must accept that."""
    card = PaperCard(
        paper_id="p_clear",
        title="t",
        url="",
        field_major="",
        field_minor="",
    )
    assert card.url == ""
    assert card.field_major == ""
