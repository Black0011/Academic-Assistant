from datetime import UTC, datetime, timezone

import pytest
from pydantic import ValidationError

from backend.memory.models import (
    Heuristic,
    PaperCard,
    Reflection,
    SessionContext,
    StrategyBlock,
    TypedLink,
    VectorHit,
)


def test_paper_card_minimal_valid():
    card = PaperCard(paper_id="p1", title="A study")
    assert card.paper_id == "p1"
    assert card.authors == []
    assert card.created_at.tzinfo is UTC


def test_paper_card_search_text_skips_empty():
    card = PaperCard(paper_id="p1", title="T")
    assert card.search_text() == "T"


def test_paper_card_extra_fields_forbidden():
    with pytest.raises(ValidationError):
        PaperCard.model_validate({"paper_id": "p1", "title": "T", "unknown": "x"})


def test_typed_link_link_type_is_constrained():
    with pytest.raises(ValidationError):
        TypedLink.model_validate({"target_paper_id": "p2", "link_type": "dubious"})


def test_heuristic_requires_domain():
    h = Heuristic(
        id="a1b2c3d4e5f6",
        name="h",
        domain="research",
        strategy=StrategyBlock(planning_hints="do it"),
    )
    assert h.failure_rate == 0.0
    assert h.total_count == 1


def test_heuristic_failure_rate():
    h = Heuristic(
        id="a" * 12,
        name="h",
        domain="writing",
        success_count=2,
        failure_count=3,
    )
    assert h.total_count == 5
    assert h.failure_rate == pytest.approx(0.6)


def test_heuristic_domain_is_constrained():
    with pytest.raises(ValidationError):
        Heuristic.model_validate({"id": "a" * 12, "name": "h", "domain": "cooking"})


def test_reflection_roundtrip_via_json():
    r = Reflection(id="r1", type="reflection", content="hi", tags=["x"])
    serialised = r.model_dump(mode="json")
    assert serialised["created_at"]
    datetime.fromisoformat(serialised["created_at"])


def test_session_context_default_empty_state():
    s = SessionContext(session_id="s1")
    assert s.messages == []
    assert s.state == {}


def test_vector_hit_score_and_metadata():
    h = VectorHit(doc_id="d", score=0.9, metadata={"k": "v"})
    assert h.metadata["k"] == "v"
