"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from backend.core.llm import MockLLMProvider
from backend.core.llm.telemetry import recorder, reset_prices_cache


@pytest.fixture
def mock_llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture(autouse=True)
def _reset_telemetry() -> None:
    """Every test sees a fresh telemetry recorder."""
    recorder().reset()
    reset_prices_cache()
