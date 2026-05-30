"""Local embedding-only provider backed by sentence-transformers.

Why this exists
---------------
The full ``LLMProvider`` Protocol couples chat completion and embeddings,
which is fine for hosted providers (OpenAI, Anthropic) but wasteful when
all you want on a laptop is a free, offline embedding model. This adapter
implements the **embed half** of the Protocol — exactly what
:class:`backend.memory.vector_store.InMemoryVectorStore` and
:class:`backend.core.skill_host.matcher.SkillMatcher` call — and
deliberately raises :class:`NotImplementedError` from the chat surface so
nothing accidentally tries to use it for completion.

Wiring
------
``backend/app.py:_build_embedder`` chooses this provider when
``settings.embedding_backend == "local"``. The chat LLM is built
separately (typically Ollama for the offline preset) so the framework
still has *some* completion path. Memory + Skill matcher get this object
as their embedder; everything else keeps using the chat LLM.

Cost
----
The first ``embed`` call lazily loads the SentenceTransformer model
(~80-500 MB depending on choice). Default: ``BAAI/bge-small-en-v1.5``
(133 MB, 384-dim) - small enough to be tolerable on a laptop. Override
via ``settings.local_embedding_model``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.errors import ConfigError, LLMAPIError

from .base import (
    ChatMessage,
    CompletionChunk,
    CostEstimate,
    ToolSpec,
    Usage,
)
from .telemetry import record

if TYPE_CHECKING:  # pragma: no cover - typing-only
    from sentence_transformers import SentenceTransformer

log = structlog.get_logger(__name__)

# Sensible laptop-friendly default. Other good picks documented in
# docs/laptop-mode.md so users can swap without changing code:
#   - BAAI/bge-small-en-v1.5      (133 MB, 384d) — default, English-only
#   - BAAI/bge-m3                 (568 MB, 1024d) — multilingual, heavier
#   - sentence-transformers/all-MiniLM-L6-v2 (90 MB, 384d) — tiny English
DEFAULT_LOCAL_EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"


class LocalSentenceTransformerEmbedder:
    """Embedding-only adapter that satisfies the ``LLMProvider`` Protocol.

    All chat-surface methods raise :class:`NotImplementedError` — this
    object should only be wired into slots that exclusively call
    ``embed(...)`` (memory vector store, skill matcher).
    """

    name: str = "local-embed"

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_LOCAL_EMBEDDING_MODEL,
        device: str | None = None,
        cache_folder: str | None = None,
        # Test seam: callers may inject an already-loaded model so unit
        # tests don't have to download weights from HuggingFace.
        model: SentenceTransformer | None = None,
    ) -> None:
        self._model_name = model_name
        self._device = device
        self._cache_folder = cache_folder
        self._model: SentenceTransformer | None = model
        self._lock = asyncio.Lock()

    # ---- chat surface (intentionally not implemented) ---------------

    def supports_tools(self) -> bool:
        return False

    def supports_streaming(self) -> bool:
        return False

    def context_window(self, model: str) -> int:
        return 0

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        tools: list[ToolSpec] | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        stream: bool = True,
    ) -> AsyncIterator[CompletionChunk]:
        # Match the other providers' shape (`async def` returning an
        # `AsyncIterator`, NOT an async-generator function — the Protocol
        # expects a coroutine that returns the iterator). Raising before
        # returning fires on the very first ``await provider.complete(...)``
        # call, which is the earliest the misuse can possibly be caught.
        raise NotImplementedError(
            "LocalSentenceTransformerEmbedder is embed-only; route chat "
            "completion via a different provider (e.g. set "
            "DEFAULT_LLM_PROVIDER=ollama for fully-local boot)."
        )

    async def estimate_cost(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
    ) -> CostEstimate:
        # Local model — zero marginal API cost. Token count is irrelevant
        # for an embedder, so report a degenerate but truthful estimate.
        return CostEstimate(usd=0.0, input_tokens=0, model=self._model_name, provider=self.name)

    # ---- embed ------------------------------------------------------

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Return one dense vector per input text.

        Lazily loads the SentenceTransformer model on first call. The
        encode call runs in a worker thread so it doesn't block the
        event loop while torch crunches.
        """
        if not texts:
            return []
        target_model = model or self._model_name
        st_model = await self._ensure_model(target_model)
        start = time.monotonic()
        try:
            # ``encode`` is sync + CPU/GPU-bound; offload to a thread so
            # the FastAPI event loop can keep serving other requests.
            vectors = await asyncio.to_thread(
                st_model.encode,
                texts,
                convert_to_numpy=False,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
        except (RuntimeError, ValueError) as exc:
            # Surface the same error class higher layers expect from
            # remote providers, so callers (vector_store) can apply
            # uniform fallback (keyword scoring) on failure.
            raise LLMAPIError(
                f"local-embed encode failed: {exc}", provider=self.name
            ) from exc
        # Sentence-transformers returns either a numpy array or a list of
        # tensors depending on `convert_to_numpy`; normalise to plain
        # Python lists of floats so downstream code (cosine, JSON
        # serialisation) doesn't have to special-case torch.
        out: list[list[float]] = [_to_float_list(v) for v in vectors]
        record(
            provider=self.name,
            model=target_model,
            duration_ms=int((time.monotonic() - start) * 1000),
            usage=Usage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            cost_usd=0.0,
        )
        return out

    # ---- internals --------------------------------------------------

    async def _ensure_model(self, model_name: str) -> SentenceTransformer:
        if self._model is not None and model_name == self._model_name:
            return self._model
        async with self._lock:
            if self._model is not None and model_name == self._model_name:
                return self._model
            try:
                # Imported lazily so users who don't enable the local
                # embedder don't pay the (heavy) torch import cost.
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise ConfigError(
                    "local embedding backend requires sentence-transformers; "
                    "install with `uv sync --extra offline`",
                    backend="local",
                ) from exc
            log.info(
                "llm.local_embedder.load",
                model=model_name,
                device=self._device,
            )
            self._model = await asyncio.to_thread(
                SentenceTransformer,
                model_name,
                device=self._device,
                cache_folder=self._cache_folder,
            )
            self._model_name = model_name
            return self._model


def _to_float_list(vec: Any) -> list[float]:
    # Avoid `import numpy` at module scope — it's a transitive dep of
    # sentence-transformers, only present when the local embedder is.
    tolist = getattr(vec, "tolist", None)
    if callable(tolist):
        result = tolist()
        if isinstance(result, list):
            return [float(x) for x in result]
    if isinstance(vec, list):
        return [float(x) for x in vec]
    raise TypeError(f"unsupported embedding vector type: {type(vec).__name__}")


__all__ = ["DEFAULT_LOCAL_EMBEDDING_MODEL", "LocalSentenceTransformerEmbedder"]
