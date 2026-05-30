"""Unit tests for :mod:`backend.knowledge.ingest`."""

from __future__ import annotations

import json

import pytest

from backend.core.errors import ValidationError as AAFValidationError
from backend.core.llm.mock import MockLLMProvider
from backend.knowledge.extractor import PaperExtractor
from backend.knowledge.ingest import (
    IngestInput,
    PaperIngestor,
    build_ingest_input_from_upload,
)
from backend.memory import MemoryBundle, PaperCard, PaperMemoryEvolver

SAMPLE_BODY = """# Self-Evolving Agents

Alice, Bob — 2024

## Abstract

We study a class of agents that improve their own behaviour by editing
their long-term memory after each task.

## Introduction

Prior work has focused on…
"""


@pytest.fixture
def bundle() -> MemoryBundle:
    return MemoryBundle.in_memory()


async def test_ingest_writes_card_and_skips_evolve_when_disabled(bundle: MemoryBundle) -> None:
    ingestor = PaperIngestor(bundle, llm=None)
    payload = IngestInput(
        title="Self-Evolving Agents",
        body_text=SAMPLE_BODY,
        trigger_evolution=False,
    )

    result = await ingestor.ingest(payload)

    assert result.card.title == "Self-Evolving Agents"
    assert result.card.year == 2024  # heuristic picked up year
    assert result.evolution.mode == "skip"
    assert result.evolution.reason == "trigger_evolution=false"
    # Card landed in the store and the run_id is the ingest stamp.
    assert (await bundle.knowledge.get(result.card.paper_id)) is not None
    assert result.card.source_run_id == f"ingest:{result.card.paper_id}"


async def test_ingest_runs_evolve_with_neighbour_links(bundle: MemoryBundle) -> None:
    # Pre-seed a neighbour with overlapping tags so the evolver can link.
    neighbour = PaperCard(
        paper_id="neighbour01",
        title="Adaptive Memory for Agents",
        tags=["agent", "memory"],
        summary="A typed-link memory system for agents.",
    )
    await bundle.knowledge.write_card(neighbour)
    await bundle.vector.add(
        neighbour.paper_id, neighbour.search_text(), metadata={"tags": neighbour.tags}
    )

    ingestor = PaperIngestor(
        bundle,
        llm=None,
        evolver=PaperMemoryEvolver(bundle, llm=None, neighbors_k=5),
    )
    payload = IngestInput(
        title="Self-Evolving Agents",
        body_text=SAMPLE_BODY,
        tags=["agent", "memory"],
        trigger_evolution=True,
    )

    result = await ingestor.ingest(payload)

    assert result.evolution.mode == "heuristic"
    # At least one neighbour was considered; tag overlap → applies link.
    assert result.evolution.neighbors_considered >= 1
    assert any(
        link.target_paper_id == "neighbour01" and link.link_type == "applies"
        for link in result.evolution.typed_links_added
    )


async def test_ingest_uses_llm_extracted_metadata(bundle: MemoryBundle) -> None:
    payload_json = {
        "title": "A-Mem: Adaptive Memory for Agents",
        "authors": ["Carol", "Dave"],
        "year": 2024,
        "venue": "NeurIPS",
        "abstract": "Typed-link memory for agents.",
        "summary": "Boosts agent learning with typed-links.",
        "method": "Vector + symbolic.",
        "findings": "+8% across three benches.",
        "tags": ["memory", "agent"],
    }
    mock = MockLLMProvider()
    mock.queue_text(json.dumps(payload_json))

    ingestor = PaperIngestor(
        bundle,
        llm=mock,
        extractor=PaperExtractor(llm=mock),
        evolver=PaperMemoryEvolver(bundle, llm=None, neighbors_k=0),
    )
    payload = IngestInput(body_text="raw paper body text", trigger_evolution=True)

    result = await ingestor.ingest(payload)

    assert result.card.title == "A-Mem: Adaptive Memory for Agents"
    assert result.card.authors == ["Carol", "Dave"]
    assert result.card.year == 2024
    assert "memory" in result.card.tags
    assert result.extracted["method"] == "llm"
    # neighbors_k=0 → evolver explicitly skips.
    assert result.evolution.mode == "skip"


async def test_ingest_rejects_when_no_title_extractable(bundle: MemoryBundle) -> None:
    ingestor = PaperIngestor(bundle, llm=None)
    # Empty body and no fallback title.
    with pytest.raises(AAFValidationError):
        await ingestor.ingest(IngestInput(body_text="", trigger_evolution=False))


async def test_ingest_user_metadata_overrides_extracted(bundle: MemoryBundle) -> None:
    ingestor = PaperIngestor(bundle, llm=None)
    payload = IngestInput(
        title="Manually titled",
        year=2030,
        tags=["override"],
        body_text=SAMPLE_BODY,
        trigger_evolution=False,
    )

    result = await ingestor.ingest(payload)

    assert result.card.title == "Manually titled"
    assert result.card.year == 2030
    assert "override" in result.card.tags


def test_build_ingest_input_decodes_markdown_bytes() -> None:
    payload = build_ingest_input_from_upload(
        raw=b"# hello\n\nworld",
        filename="my-paper.md",
        content_type="text/markdown",
    )
    assert payload.body_text == "# hello\n\nworld"
    assert payload.source_kind == "user_upload"
    # title left empty — extractor will pick "hello" from the H1, only
    # falling back to the stem-derived value if extraction fails.
    assert payload.title == ""
    assert payload.fallback_title == "my paper"
    assert payload.raw_pdf_meta == {}


def test_build_ingest_input_rejects_non_utf8_unknown_extension() -> None:
    # A zip-ish magic byte sequence — not text, not pdf.
    with pytest.raises(AAFValidationError):
        build_ingest_input_from_upload(
            raw=b"\x80\x81\x82\xff",
            filename="weird.dat",
            content_type="application/octet-stream",
        )
