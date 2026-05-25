"""Lifespan smoke test — boots the app with the real factory wiring.

httpx's ASGITransport does not fire ASGI lifespan events, so we drive the
context manager directly. This keeps the test hermetic (no real Redis /
disk) by forcing every store to its in-memory backend via env vars.
"""

from __future__ import annotations

from httpx import ASGITransport, AsyncClient

from backend.app import create_app, lifespan


async def test_lifespan_boots_with_defaults(tmp_path, monkeypatch):
    # Steer all stores into ephemeral / in-memory backends.
    monkeypatch.setenv("memory_vector_backend", "memory")
    monkeypatch.setenv("memory_knowledge_backend", "memory")
    monkeypatch.setenv("memory_heuristic_backend", "memory")
    monkeypatch.setenv("memory_episodic_backend", "memory")
    monkeypatch.setenv("memory_session_backend", "memory")
    monkeypatch.setenv("aaf_workdir", str(tmp_path))
    from backend.settings import reload_settings

    reload_settings()

    app = create_app()
    async with lifespan(app):
        assert hasattr(app.state, "aaf")
        state = app.state.aaf
        assert state.memory is not None
        assert state.llm is not None
        # LLM falls back to mock when no credentials configured.
        assert getattr(state.llm, "name", None) == "mock"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as c:
            r = await c.get("/api/version")
            assert r.status_code == 200
            assert r.json()["llm_provider"] == "mock"

    reload_settings()


async def test_lifespan_closes_memory_factory(tmp_path, monkeypatch):
    """After shutdown the factory must have released its resources."""
    monkeypatch.setenv("memory_episodic_backend", "sql")
    monkeypatch.setenv("memory_session_backend", "memory")
    monkeypatch.setenv("memory_vector_backend", "memory")
    monkeypatch.setenv("memory_knowledge_backend", "memory")
    monkeypatch.setenv("memory_heuristic_backend", "memory")
    monkeypatch.setenv("database_url", "sqlite+aiosqlite:///:memory:")
    monkeypatch.setenv("aaf_workdir", str(tmp_path))
    from backend.settings import reload_settings

    reload_settings()

    app = create_app()
    async with lifespan(app):
        factory = app.state.aaf.memory_factory
        assert factory is not None
        # One close hook should have been registered by SqlEpisodicStore.
        assert len(factory._close_hooks) >= 1

    # After the ctxmgr exits the factory should have cleared its hooks.
    assert factory._close_hooks == []

    reload_settings()
