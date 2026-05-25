"""A-Mem evolver: heuristic + LLM paths, synthesis, reflection."""

import json

import pytest

from backend.core.llm import MockLLMProvider
from backend.memory import (
    MemoryBundle,
    PaperCard,
    PaperMemoryEvolver,
)
from backend.memory.paper_memory import (
    _heuristic_evolution,
    _template_reflection,
    extract_json,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _card(pid: str, *, title: str = "", tags=None, summary: str = "") -> PaperCard:
    return PaperCard(
        paper_id=pid,
        title=title or f"paper {pid}",
        tags=list(tags or []),
        summary=summary,
    )


async def _seed_cards(bundle: MemoryBundle, cards: list[PaperCard]) -> None:
    for c in cards:
        await bundle.knowledge.write_card(c)
        await bundle.vector.add(c.paper_id, c.search_text(), metadata={"tags": c.tags})


# ---------------------------------------------------------------------------
# JSON extractor
# ---------------------------------------------------------------------------


def test_extract_json_plain_object():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": [1,2]}\n```') == {"a": [1, 2]}


def test_extract_json_prose_prefix():
    raw = 'Sure, here: {"typed_connections": []}. done.'
    assert extract_json(raw) == {"typed_connections": []}


def test_extract_json_returns_none_on_garbage():
    assert extract_json("not json") is None


# ---------------------------------------------------------------------------
# Heuristic fallback (pure)
# ---------------------------------------------------------------------------


def test_heuristic_evolution_no_overlap_no_link():
    card = _card("p1", title="Cat grooming", tags=["pets"])
    nb = _card("p2", title="Quantum chromodynamics", tags=["physics"])
    out = _heuristic_evolution(card, [nb])
    assert out["typed_connections"] == []


def test_heuristic_evolution_tag_overlap_produces_applies_link():
    card = _card("p1", title="RLHF scaling", tags=["rlhf", "reward"])
    nb = _card("p2", title="Reward model study", tags=["rlhf"])
    out = _heuristic_evolution(card, [nb])
    conns = out["typed_connections"]
    assert conns and conns[0]["paper_id"] == "p2"
    assert conns[0]["relation_type"] == "applies"
    assert 0 < conns[0]["confidence"] <= 0.6


def test_heuristic_evolution_caps_at_three_neighbours():
    card = _card("p0", title="multi task rlhf", tags=["rlhf"])
    nbs = [_card(f"p{i}", title="rlhf reward", tags=["rlhf"]) for i in range(1, 6)]
    out = _heuristic_evolution(card, nbs)
    assert len(out["typed_connections"]) == 3


# ---------------------------------------------------------------------------
# Evolver — evolve_new_paper
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_evolve_new_paper_skips_when_no_neighbours():
    bundle = MemoryBundle.in_memory()
    card = _card("p1", title="lonely")
    await bundle.knowledge.write_card(card)
    await bundle.vector.add(card.paper_id, card.search_text())
    evo = PaperMemoryEvolver(bundle)
    result = await evo.evolve_new_paper(card)
    assert result.mode == "skip"
    assert result.typed_links_added == []


@pytest.mark.asyncio
async def test_evolve_heuristic_writes_typed_links_both_ways():
    bundle = MemoryBundle.in_memory()
    seed = [
        _card("p1", title="rlhf reward scaling", tags=["rlhf", "reward"]),
        _card("p2", title="reward model for rlhf", tags=["rlhf"]),
    ]
    await _seed_cards(bundle, seed)
    evo = PaperMemoryEvolver(bundle)

    result = await evo.evolve_new_paper(seed[0])
    assert result.mode == "heuristic"
    assert any(link.target_paper_id == "p2" for link in result.typed_links_added)

    p1 = await bundle.knowledge.get("p1")
    p2 = await bundle.knowledge.get("p2")
    assert p1 and p2
    assert any(link.link_type == "applies" for link in p1.typed_links)
    # Inverse side written (baseline_of is the inverse of applies).
    assert any(link.link_type == "baseline_of" for link in p2.typed_links)


@pytest.mark.asyncio
async def test_evolve_llm_path_translates_old_vocab():
    bundle = MemoryBundle.in_memory()
    seed = [
        _card("p1", title="alpha method", tags=["method"]),
        _card("p2", title="baseline work", tags=["method"]),
    ]
    await _seed_cards(bundle, seed)

    llm = MockLLMProvider()
    # "motivates" and "benchmarks" from legacy vocabulary must be translated.
    llm.queue_text(
        json.dumps(
            {
                "typed_connections": [
                    {"paper_id": "p2", "relation_type": "motivates", "confidence": 0.8},
                ],
                "tags_to_update": ["alignment"],
            }
        )
    )
    evo = PaperMemoryEvolver(bundle, llm=llm)
    result = await evo.evolve_new_paper(seed[0])
    assert result.mode == "llm"
    assert result.typed_links_added
    assert result.typed_links_added[0].link_type == "motivated_by"
    assert "alignment" in result.tags_added

    p1 = await bundle.knowledge.get("p1")
    assert p1 and "alignment" in p1.tags


@pytest.mark.asyncio
async def test_evolve_refuses_links_outside_neighbour_set():
    bundle = MemoryBundle.in_memory()
    seed = [
        _card("p1", title="alpha", tags=["x"]),
        _card("p2", title="alpha twin", tags=["x"]),
    ]
    await _seed_cards(bundle, seed)

    llm = MockLLMProvider()
    llm.queue_text(
        json.dumps(
            {
                "typed_connections": [
                    {"paper_id": "hacker", "relation_type": "extends", "confidence": 1.0},
                ]
            }
        )
    )
    evo = PaperMemoryEvolver(bundle, llm=llm)
    result = await evo.evolve_new_paper(seed[0])
    assert result.typed_links_added == []


@pytest.mark.asyncio
async def test_evolve_falls_back_to_heuristic_on_llm_error():
    bundle = MemoryBundle.in_memory()
    seed = [
        _card("p1", title="rlhf reward scaling", tags=["rlhf"]),
        _card("p2", title="reward model for rlhf", tags=["rlhf"]),
    ]
    await _seed_cards(bundle, seed)
    llm = MockLLMProvider()
    llm.queue_error("upstream down")
    evo = PaperMemoryEvolver(bundle, llm=llm)
    result = await evo.evolve_new_paper(seed[0])
    assert result.mode == "heuristic"
    assert result.typed_links_added


# ---------------------------------------------------------------------------
# Evolver — synthesis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_synthesis_trigger_ignored_below_threshold():
    bundle = MemoryBundle.in_memory()
    for i in range(3):
        await bundle.knowledge.write_card(_card(f"p{i}", tags=["rlhf"]))
    evo = PaperMemoryEvolver(bundle, synthesis_threshold=5)
    assert await evo.check_synthesis_trigger("rlhf") is None


@pytest.mark.asyncio
async def test_synthesis_trigger_template_when_no_llm():
    bundle = MemoryBundle.in_memory()
    cards = [_card(f"p{i}", title=f"title-{i}", tags=["rlhf"]) for i in range(5)]
    for c in cards:
        await bundle.knowledge.write_card(c)
    evo = PaperMemoryEvolver(bundle, synthesis_threshold=5)
    note = await evo.check_synthesis_trigger("rlhf", run_id="run-1")
    assert note is not None
    assert note.cluster_tag == "rlhf"
    assert set(note.paper_ids) == {c.paper_id for c in cards}
    assert note.source_run_id == "run-1"
    # Template content is deterministic markdown.
    assert "# Synthesis: rlhf" in note.content


@pytest.mark.asyncio
async def test_synthesis_trigger_reuses_existing_when_cluster_unchanged():
    bundle = MemoryBundle.in_memory()
    cards = [_card(f"p{i}", tags=["rlhf"]) for i in range(5)]
    for c in cards:
        await bundle.knowledge.write_card(c)
    evo = PaperMemoryEvolver(bundle, synthesis_threshold=5)
    first = await evo.check_synthesis_trigger("rlhf")
    second = await evo.check_synthesis_trigger("rlhf")
    assert first is not None and second is not None
    # No regeneration → version stays at 1 (regeneration would bump to 2).
    assert first.version == second.version == 1
    assert first.paper_ids == second.paper_ids


@pytest.mark.asyncio
async def test_synthesis_trigger_uses_llm_when_available():
    bundle = MemoryBundle.in_memory()
    for i in range(5):
        await bundle.knowledge.write_card(_card(f"p{i}", tags=["rlhf"]))
    llm = MockLLMProvider()
    llm.queue_text("## scripted synthesis\n\nkey insight")
    evo = PaperMemoryEvolver(bundle, llm=llm, synthesis_threshold=5)
    note = await evo.check_synthesis_trigger("rlhf")
    assert note is not None and "scripted synthesis" in note.content


# ---------------------------------------------------------------------------
# Evolver — session reflection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reflection_template_without_llm():
    bundle = MemoryBundle.in_memory()
    evo = PaperMemoryEvolver(bundle)
    refl = await evo.write_session_reflection(
        task_id="t1",
        query="rlhf survey",
        outcomes={"papers": 3, "verdict": "pass"},
        session_id="s1",
        user_id="u1",
    )
    assert refl.session_id == "s1"
    assert refl.user_id == "u1"
    assert refl.source_run_id == "t1"
    recent = await bundle.episodic.recent(n=1)
    assert recent and recent[0].id == refl.id


@pytest.mark.asyncio
async def test_reflection_uses_llm_when_available():
    bundle = MemoryBundle.in_memory()
    llm = MockLLMProvider()
    llm.queue_text("Learnt that X beats Y.")
    evo = PaperMemoryEvolver(bundle, llm=llm)
    refl = await evo.write_session_reflection(
        task_id="t1",
        query="test",
        outcomes={"score": 0.9},
    )
    assert refl.content == "Learnt that X beats Y."


def test_template_reflection_handles_nested_values():
    out = _template_reflection(query="q", outcomes={"n": 3, "xs": [1, 2, 3], "ok": True})
    assert "n=3" in out and "xs[3]" in out and "ok=True" in out
