"""MemoryBundle factory — pick backends from plain configuration dicts.

Callers hand in a dict (usually sourced from ``Settings.memory`` at
FastAPI startup) and get back a fully wired :class:`MemoryBundle`.
Unknown backends raise a clear :class:`ConfigError`. All backends fall
back to their in-process variant when the config selects ``"memory"`` so
the framework still boots without Chroma / Postgres / Redis.

Schema::

    {
      "vector":    {"backend": "memory" | "chroma",
                     "persist_dir": "...",  # chroma only
                     "collection": "aaf_memory"},
      "knowledge": {"backend": "memory" | "yaml",
                     "root": "data/knowledge"},
      "heuristic": {"backend": "memory" | "yaml",
                     "root": "data/skills"},
      "episodic":  {"backend": "memory" | "sql",
                     "url": "sqlite+aiosqlite:///data/episodic.db"},
      "session":   {"backend": "memory" | "redis",
                     "url": "redis://localhost:6379/0",
                     "namespace": "aaf"}
    }
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import structlog

from backend.core.errors import ConfigError

from .base import MemoryBundle
from .document_store import InMemoryDocumentStore, YamlDocumentStore
from .episodic_store import InMemoryEpisodicStore
from .heuristic_store import InMemoryHeuristicStore, YamlHeuristicStore
from .knowledge_store import InMemoryKnowledgeStore, YamlKnowledgeStore
from .session_store import InMemorySessionStore
from .vector_store import InMemoryVectorStore

if TYPE_CHECKING:
    from backend.core.llm.base import LLMProvider

log = structlog.get_logger(__name__)


class MemoryFactory:
    """Helper that constructs + (optionally) initialises each store.

    Usage::

        factory = MemoryFactory(config, embedder=llm)
        bundle = await factory.build()
        # later:
        await factory.aclose()
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        embedder: LLMProvider | None = None,
    ) -> None:
        self._config = dict(config or {})
        self._embedder = embedder
        self._close_hooks: list[Any] = []

    async def build(self) -> MemoryBundle:
        vector = await self._build_vector(self._config.get("vector") or {})
        knowledge = self._build_knowledge(self._config.get("knowledge") or {})
        heuristic = self._build_heuristic(self._config.get("heuristic") or {})
        episodic = await self._build_episodic(self._config.get("episodic") or {})
        session = await self._build_session(self._config.get("session") or {})
        documents = self._build_documents(self._config.get("documents") or {}, vector=vector)
        return MemoryBundle(
            vector=vector,
            knowledge=knowledge,
            heuristic=heuristic,
            episodic=episodic,
            session=session,
            documents=documents,
        )

    async def aclose(self) -> None:
        for hook in self._close_hooks:
            try:
                await hook()
            except Exception as exc:
                log.warning("memory.factory.close_failed", err=str(exc))
        self._close_hooks.clear()

    # ---- vector -----------------------------------------------------

    async def _build_vector(self, cfg: dict[str, Any]) -> Any:
        backend = cfg.get("backend", "memory")
        if backend == "memory":
            return InMemoryVectorStore(embedder=self._embedder)
        if backend == "chroma":
            from .vector_chroma import ChromaVectorStore

            return ChromaVectorStore(
                collection_name=cfg.get("collection", "aaf_memory"),
                persist_dir=cfg.get("persist_dir"),
                embedder=self._embedder,
                embedding_model=cfg.get("embedding_model"),
            )
        raise ConfigError(f"unknown vector backend: {backend!r}", backend=backend)

    # ---- knowledge --------------------------------------------------

    def _build_knowledge(self, cfg: dict[str, Any]) -> Any:
        backend = cfg.get("backend", "memory")
        if backend == "memory":
            return InMemoryKnowledgeStore()
        if backend == "yaml":
            return YamlKnowledgeStore(Path(cfg.get("root", "data/knowledge")))
        raise ConfigError(f"unknown knowledge backend: {backend!r}", backend=backend)

    # ---- heuristic --------------------------------------------------

    def _build_heuristic(self, cfg: dict[str, Any]) -> Any:
        backend = cfg.get("backend", "memory")
        if backend == "memory":
            return InMemoryHeuristicStore()
        if backend == "yaml":
            return YamlHeuristicStore(Path(cfg.get("root", "data/skills")))
        raise ConfigError(f"unknown heuristic backend: {backend!r}", backend=backend)

    # ---- episodic ---------------------------------------------------

    async def _build_episodic(self, cfg: dict[str, Any]) -> Any:
        backend = cfg.get("backend", "memory")
        if backend == "memory":
            return InMemoryEpisodicStore()
        if backend == "sql":
            from .episodic_sql import SqlEpisodicStore

            url = cfg.get("url") or "sqlite+aiosqlite:///:memory:"
            store = SqlEpisodicStore.from_url(url, echo=bool(cfg.get("echo")))
            await store.init()
            self._close_hooks.append(store.close)
            return store
        raise ConfigError(f"unknown episodic backend: {backend!r}", backend=backend)

    # ---- documents (M7.3) ------------------------------------------

    def _build_documents(self, cfg: dict[str, Any], *, vector: Any) -> Any:
        backend = cfg.get("backend", "memory")
        if backend == "memory":
            return InMemoryDocumentStore(vector=vector)
        if backend == "yaml":
            return YamlDocumentStore(
                Path(cfg.get("root", "data/documents")),
                vector=vector,
            )
        raise ConfigError(f"unknown documents backend: {backend!r}", backend=backend)

    # ---- session ----------------------------------------------------

    async def _build_session(self, cfg: dict[str, Any]) -> Any:
        backend = cfg.get("backend", "memory")
        if backend == "memory":
            return InMemorySessionStore()
        if backend == "redis":
            from redis.asyncio import Redis  # imported only when needed

            from .session_redis import RedisSessionStore

            url = cfg.get("url") or "redis://localhost:6379/0"
            client: Any = cfg.get("client")
            if client is None:
                client = Redis.from_url(url)
                self._close_hooks.append(client.aclose)
            return RedisSessionStore(client, namespace=cfg.get("namespace", "aaf"))
        raise ConfigError(f"unknown session backend: {backend!r}", backend=backend)


async def build_memory_bundle(
    config: dict[str, Any] | None = None,
    *,
    embedder: LLMProvider | None = None,
) -> tuple[MemoryBundle, MemoryFactory]:
    """Convenience one-shot constructor. Caller owns the factory for close()."""
    factory = MemoryFactory(config, embedder=embedder)
    return await factory.build(), factory


__all__ = ["MemoryFactory", "build_memory_bundle"]
