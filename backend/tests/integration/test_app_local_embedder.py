"""End-to-end check that the ``local`` embedding backend wires through.

We don't want to download a real ~130 MB sentence-transformers model in
CI, so we monkey-patch ``sentence_transformers.SentenceTransformer``
with a tiny in-process stand-in. The asserts then prove:

* ``app.state.aaf.memory.vector`` was built with the local embedder
* ``app.state.aaf.skill_host`` shares that embedder
* a real ``vector.add(...) → vector.query(...)`` round-trip uses the
  fake embedder (deterministic vectors, top-1 matches the inserted doc)
"""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator, Iterator
from types import ModuleType
from typing import Any, ClassVar

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.local_embedder import LocalSentenceTransformerEmbedder
from backend.memory.vector_store import InMemoryVectorStore
from backend.settings import Settings, reload_settings


class _FakeSentenceTransformer:
    instances: ClassVar[list[_FakeSentenceTransformer]] = []

    def __init__(self, model_name: str, device: str | None = None, cache_folder: str | None = None) -> None:
        self.model_name = model_name
        self.device = device
        self.cache_folder = cache_folder
        type(self).instances.append(self)

    def encode(
        self,
        texts: list[str],
        *,
        convert_to_numpy: bool = True,
        show_progress_bar: bool = True,
        normalize_embeddings: bool = False,
    ) -> list[list[float]]:
        # Deterministic 4-dim vector keyed off the first character so the
        # cosine query in the test below has an obvious top-1.
        return [[float(ord(t[0])) if t else 0.0, 0.0, 0.0, 1.0] for t in texts]


@pytest.fixture
def fake_sentence_transformers(monkeypatch: pytest.MonkeyPatch) -> Iterator[type[_FakeSentenceTransformer]]:
    _FakeSentenceTransformer.instances.clear()
    fake_mod = ModuleType("sentence_transformers")
    fake_mod.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_mod)
    yield _FakeSentenceTransformer
    _FakeSentenceTransformer.instances.clear()


@pytest.fixture
def offline_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> Iterator[Settings]:
    monkeypatch.setenv("AAF_EMBEDDING_BACKEND", "local")
    monkeypatch.setenv("AAF_LOCAL_EMBEDDING_MODEL", "fake-model")
    monkeypatch.setenv("AAF_WORKDIR", str(tmp_path))
    monkeypatch.setenv("USERS_DIR", str(tmp_path / "users"))
    monkeypatch.setenv("MEMORY_KNOWLEDGE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setenv("MEMORY_SKILLS_DIR", str(tmp_path / "skills"))
    monkeypatch.setenv("MEMORY_DOCUMENTS_DIR", str(tmp_path / "documents"))
    monkeypatch.setenv("AAF_PROPOSALS_DIR", str(tmp_path / "proposals"))
    monkeypatch.setenv("AAF_SKILL_WORKDIR_ROOT", str(tmp_path / "skill_runs"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/aaf.db")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("AAF_TASK_QUEUE_BACKEND", "inmemory")
    monkeypatch.setenv("AAF_TASK_STORE_BACKEND", "sql")
    monkeypatch.setenv("MEMORY_VECTOR_BACKEND", "memory")
    monkeypatch.setenv("MEMORY_SESSION_BACKEND", "memory")
    monkeypatch.setenv("AAF_AUTOCOMPACT_ENABLED", "false")
    monkeypatch.setenv("AAF_MCP_ENABLED", "false")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    yield reload_settings()
    reload_settings()


@pytest.fixture
async def app_with_local_embedder(
    fake_sentence_transformers: type[_FakeSentenceTransformer],
    offline_settings: Settings,
) -> AsyncIterator[FastAPI]:
    app = create_app()
    async with app.router.lifespan_context(app):
        yield app


@pytest.mark.asyncio
async def test_local_embedder_wires_into_memory_and_skill_host(
    app_with_local_embedder: FastAPI,
) -> None:
    state: AppState = app_with_local_embedder.state.aaf
    assert state.memory is not None
    assert state.skill_host is not None
    # MEMORY_VECTOR_BACKEND=memory in the fixture forces this concrete
    # type; assert it so the ``_embedder`` access below is type-safe.
    assert isinstance(state.memory.vector, InMemoryVectorStore)
    vector = state.memory.vector
    embedder = vector._embedder

    assert isinstance(embedder, LocalSentenceTransformerEmbedder)
    assert state.skill_host._matcher._embedder is embedder

    # Round-trip: the deterministic fake encoder makes the doc starting
    # with the same character as the query the unique top-1 hit.
    await vector.add("doc-1", "alpha example", metadata={"src": "test"})
    await vector.add("doc-2", "zeta example", metadata={"src": "test"})

    hits = await vector.query("alpine", k=2)
    assert hits, "embedder should have produced at least one hit"
    assert hits[0].doc_id == "doc-1"
    # Sanity: a SentenceTransformer instance was actually constructed.
    assert _FakeSentenceTransformer.instances, "local embedder never loaded"
    assert _FakeSentenceTransformer.instances[0].model_name == "fake-model"


@pytest.mark.asyncio
async def test_offline_app_health_endpoint_responds(
    app_with_local_embedder: FastAPI,
) -> None:
    """A second sanity check: the app boots end-to-end with the offline embedder."""
    transport = ASGITransport(app=app_with_local_embedder)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
