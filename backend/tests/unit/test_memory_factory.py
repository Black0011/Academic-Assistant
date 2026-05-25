"""MemoryFactory — integration-ish tests: config → fully wired MemoryBundle.

We exercise every backend that doesn't require an external service:
* vector: memory (chroma path covered in test_memory_vector_chroma)
* knowledge: yaml
* heuristic: yaml
* episodic: sql (sqlite in-memory)
* session: redis (fakeredis)
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import pytest

from backend.core.errors import ConfigError
from backend.memory import (
    InMemoryEpisodicStore,
    InMemoryHeuristicStore,
    InMemoryKnowledgeStore,
    InMemorySessionStore,
    InMemoryVectorStore,
    MemoryFactory,
    PaperCard,
    RedisSessionStore,
    Reflection,
    SessionContext,
    SqlEpisodicStore,
    YamlHeuristicStore,
    YamlKnowledgeStore,
)

fakeredis = pytest.importorskip("fakeredis")


async def test_defaults_build_pure_in_memory_bundle():
    factory = MemoryFactory()
    bundle = await factory.build()
    assert isinstance(bundle.vector, InMemoryVectorStore)
    assert isinstance(bundle.knowledge, InMemoryKnowledgeStore)
    assert isinstance(bundle.heuristic, InMemoryHeuristicStore)
    assert isinstance(bundle.episodic, InMemoryEpisodicStore)
    assert isinstance(bundle.session, InMemorySessionStore)
    await factory.aclose()


async def test_unknown_backend_raises_config_error():
    factory = MemoryFactory({"vector": {"backend": "qdrant"}})
    with pytest.raises(ConfigError):
        await factory.build()


async def test_yaml_backends_persist_to_disk(tmp_path: Path):
    config = {
        "knowledge": {"backend": "yaml", "root": str(tmp_path / "knowledge")},
        "heuristic": {"backend": "yaml", "root": str(tmp_path / "skills")},
    }
    factory = MemoryFactory(config)
    bundle = await factory.build()
    try:
        assert isinstance(bundle.knowledge, YamlKnowledgeStore)
        assert isinstance(bundle.heuristic, YamlHeuristicStore)
        await bundle.knowledge.write_card(
            PaperCard(paper_id="p1", title="x", abstract="y", tags=["a"])
        )
        assert (tmp_path / "knowledge" / "p1.yaml").exists()
    finally:
        await factory.aclose()


async def test_sql_episodic_writes_and_reads(tmp_path: Path):
    factory = MemoryFactory({"episodic": {"backend": "sql"}})
    bundle = await factory.build()
    try:
        assert isinstance(bundle.episodic, SqlEpisodicStore)
        from datetime import datetime, timezone

        await bundle.episodic.append(
            Reflection(
                id="r1",
                type="reflection",
                content="hello",
                created_at=datetime.now(UTC),
            )
        )
        recent = await bundle.episodic.recent(n=5)
        assert len(recent) == 1
        assert recent[0].id == "r1"
    finally:
        await factory.aclose()


async def test_redis_session_backend_uses_injected_client():
    client = fakeredis.aioredis.FakeRedis()
    config = {"session": {"backend": "redis", "client": client, "namespace": "test"}}
    factory = MemoryFactory(config)
    bundle = await factory.build()
    try:
        assert isinstance(bundle.session, RedisSessionStore)
        from datetime import datetime, timezone

        await bundle.session.create(
            SessionContext(
                session_id="s1",
                user_id="u1",
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
        )
        got = await bundle.session.get("s1")
        assert got is not None
    finally:
        await factory.aclose()
        await client.aclose()


async def test_full_bundle_snapshot_cross_backends(tmp_path: Path):
    """End-to-end: yaml + sql + redis + in-memory vector all answer snapshot()."""
    client = fakeredis.aioredis.FakeRedis()
    config = {
        "knowledge": {"backend": "yaml", "root": str(tmp_path / "kn")},
        "heuristic": {"backend": "yaml", "root": str(tmp_path / "sk")},
        "episodic": {"backend": "sql"},
        "session": {"backend": "redis", "client": client, "namespace": "snap"},
    }
    factory = MemoryFactory(config)
    bundle = await factory.build()
    try:
        snap = await bundle.snapshot("retinoid acne", domain="research", k=3)
        assert snap.query == "retinoid acne"
        assert snap.domain == "research"
    finally:
        await factory.aclose()
        await client.aclose()
