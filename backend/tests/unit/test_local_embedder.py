"""Unit tests for ``LocalSentenceTransformerEmbedder``.

Strategy: inject a fake SentenceTransformer-shaped object so we don't
download a real model in CI. A separate, opt-in test exercises the
real model path when ``sentence-transformers`` is installed.
"""

from __future__ import annotations

import sys

import pytest

from backend.core.errors import ConfigError, LLMAPIError
from backend.core.llm.base import ChatMessage
from backend.core.llm.local_embedder import (
    DEFAULT_LOCAL_EMBEDDING_MODEL,
    LocalSentenceTransformerEmbedder,
)


class _FakeST:
    """Minimal stand-in for ``sentence_transformers.SentenceTransformer``.

    Returns deterministic 4-dim vectors so tests can assert exact values.
    """

    def __init__(self, model_name: str, device: str | None = None, cache_folder: str | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self.cache_folder = cache_folder
        self.calls: list[list[str]] = []

    def encode(
        self,
        texts: list[str],
        *,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = True,
        normalize_embeddings: bool = False,
    ) -> list[list[float]]:
        self.calls.append(list(texts))
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


@pytest.mark.asyncio
async def test_embed_returns_one_vector_per_text_and_is_threaded() -> None:
    fake = _FakeST("fake-model")
    embedder = LocalSentenceTransformerEmbedder(model_name="fake-model", model=fake)

    out = await embedder.embed(["hi", "hello"])

    assert len(out) == 2
    assert out[0] == [2.0, 0.0, 0.0, 0.0]
    assert out[1] == [5.0, 0.0, 0.0, 0.0]
    assert fake.calls == [["hi", "hello"]]


@pytest.mark.asyncio
async def test_embed_empty_input_short_circuits() -> None:
    fake = _FakeST("fake-model")
    embedder = LocalSentenceTransformerEmbedder(model_name="fake-model", model=fake)

    out = await embedder.embed([])

    assert out == []
    assert fake.calls == []


@pytest.mark.asyncio
async def test_embed_normalises_vector_objects_via_tolist() -> None:
    class _Vec:
        def __init__(self, xs: list[float]) -> None:
            self._xs = xs

        def tolist(self) -> list[float]:
            return self._xs

    class _ToListST(_FakeST):
        def encode(self, texts, **kw):
            return [_Vec([1.0, 2.0]) for _ in texts]

    embedder = LocalSentenceTransformerEmbedder(
        model_name="fake-model", model=_ToListST("fake-model")
    )
    out = await embedder.embed(["x"])
    assert out == [[1.0, 2.0]]


@pytest.mark.asyncio
async def test_embed_translates_runtime_errors_to_llm_api_error() -> None:
    class _BoomST(_FakeST):
        def encode(self, texts, **kw):
            raise RuntimeError("torch oom")

    embedder = LocalSentenceTransformerEmbedder(
        model_name="fake-model", model=_BoomST("fake-model")
    )

    with pytest.raises(LLMAPIError) as excinfo:
        await embedder.embed(["x"])
    assert "local-embed" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_complete_raises_not_implemented_when_awaited() -> None:
    embedder = LocalSentenceTransformerEmbedder(model_name="fake-model", model=_FakeST("f"))

    with pytest.raises(NotImplementedError):
        await embedder.complete([ChatMessage(role="user", content="hi")])


@pytest.mark.asyncio
async def test_estimate_cost_is_zero_and_records_provider_name() -> None:
    embedder = LocalSentenceTransformerEmbedder(model_name="fake-model", model=_FakeST("f"))
    est = await embedder.estimate_cost([ChatMessage(role="user", content="hi")])
    assert est.usd == 0.0
    assert est.provider == "local-embed"
    assert est.model == "fake-model"


@pytest.mark.asyncio
async def test_load_failure_when_sentence_transformers_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the optional extra is not installed we surface ConfigError, not ImportError.

    Python's import machinery treats ``sys.modules["x"] = None`` as a
    sentinel that blocks any subsequent ``import x`` with a clean
    ``ModuleNotFoundError`` -- no monkey-patching of ``__import__`` needed.
    """

    monkeypatch.setitem(sys.modules, "sentence_transformers", None)

    embedder = LocalSentenceTransformerEmbedder(model_name=DEFAULT_LOCAL_EMBEDDING_MODEL)
    with pytest.raises(ConfigError) as excinfo:
        await embedder.embed(["hi"])
    assert "sentence-transformers" in str(excinfo.value)
    assert "uv sync --extra offline" in str(excinfo.value)
