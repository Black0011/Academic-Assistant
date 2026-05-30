"""Unit tests for :mod:`backend.knowledge.extractor`."""

from __future__ import annotations

import json

import pytest

from backend.core.llm.mock import MockLLMProvider
from backend.knowledge.extractor import PaperExtractor

HEURISTIC_BODY = """
# Self-Evolving Agents

Alice, Bob — 2024

## Abstract

We study a class of agents that improve their own behaviour by editing
their long-term memory after each task. Our main contribution is a
typed-link evolution scheme that yields measurable performance gains
on three benchmarks.

## Introduction

Prior work on self-improving agents has focused on…
"""


async def test_heuristic_extracts_title_year_abstract() -> None:
    ex = PaperExtractor(llm=None)
    result = await ex.extract(HEURISTIC_BODY)

    assert result.method_used == "heuristic"
    assert result.title == "Self-Evolving Agents"
    assert result.year == 2024
    assert "typed-link evolution" in result.abstract
    # Summary defaults to abstract when no other source is available.
    assert result.summary.startswith("We study")


async def test_heuristic_uses_first_line_when_no_heading() -> None:
    ex = PaperExtractor(llm=None)
    result = await ex.extract("This paper has no heading.\n\nJust prose.", fallback_title="my-doc")
    # First non-empty line wins when no markdown heading is present.
    assert result.title == "This paper has no heading."
    assert result.method_used == "heuristic"


async def test_empty_body_returns_metadata_only() -> None:
    ex = PaperExtractor(llm=None)
    result = await ex.extract("", fallback_title="placeholder")
    assert result.method_used == "metadata_only"
    assert result.title == "placeholder"
    assert result.abstract == ""


async def test_llm_path_used_when_returns_valid_json() -> None:
    payload = {
        "title": "A-Mem: Adaptive Memory for Agents",
        "authors": ["Carol", "Dave"],
        "year": 2024,
        "venue": "NeurIPS",
        "abstract": "We introduce A-Mem, a typed-link memory.",
        "summary": "Typed-link memory framework that boosts agent gains.",
        "method": "Vector index + symbolic links.",
        "findings": "+8% on three benchmarks.",
        "tags": ["memory", "agent", "neurips"],
    }
    mock = MockLLMProvider()
    mock.queue_text(json.dumps(payload))

    ex = PaperExtractor(llm=mock)
    result = await ex.extract("anything", fallback_title="ignored")

    assert result.method_used == "llm"
    assert result.title == "A-Mem: Adaptive Memory for Agents"
    assert result.authors == ["Carol", "Dave"]
    assert result.year == 2024
    assert result.tags == ["memory", "agent", "neurips"]
    assert result.findings.startswith("+8%")
    # The LLM was invoked exactly once.
    assert len(mock.calls) == 1


async def test_llm_path_with_fenced_json_still_parses() -> None:
    payload = {"title": "Fenced", "abstract": "x"}
    mock = MockLLMProvider()
    mock.queue_text(f"some preamble\n```json\n{json.dumps(payload)}\n```\nepilogue")

    ex = PaperExtractor(llm=mock)
    result = await ex.extract("body", fallback_title="ignored")

    assert result.title == "Fenced"
    assert result.method_used == "llm"


async def test_llm_path_falls_back_when_json_is_garbage() -> None:
    mock = MockLLMProvider()
    mock.queue_text("not json at all, just prose")

    ex = PaperExtractor(llm=mock)
    result = await ex.extract(HEURISTIC_BODY, fallback_title="x")

    # LLM produced nothing usable → heuristic path takes over.
    assert result.method_used == "heuristic"
    assert result.title == "Self-Evolving Agents"


async def test_llm_path_falls_back_when_llm_raises() -> None:
    mock = MockLLMProvider()
    mock.queue_error("boom")

    ex = PaperExtractor(llm=mock)
    result = await ex.extract(HEURISTIC_BODY, fallback_title="x")

    assert result.method_used == "heuristic"


def test_merge_metadata_overrides_user_supplied() -> None:
    from backend.knowledge.extractor import ExtractedPaper

    base = ExtractedPaper(
        title="auto", authors=["A"], year=2020, abstract="auto-abs", method_used="llm"
    )
    merged = base.merge_metadata(override={"title": "manual", "year": 2024})

    assert merged.title == "manual"
    assert merged.authors == ["A"]
    assert merged.year == 2024
    assert merged.method_used == "llm"


@pytest.mark.parametrize(
    "year_input,expected",
    [(2024, 2024), ("2024", 2024), ("Nov 2023", 2023), ("nope", None), (None, None)],
)
async def test_year_coercion_handles_strings(year_input: object, expected: int | None) -> None:
    payload: dict = {"title": "T", "abstract": "A", "year": year_input}
    mock = MockLLMProvider()
    mock.queue_text(json.dumps(payload))

    ex = PaperExtractor(llm=mock)
    result = await ex.extract("body")

    assert result.year == expected
