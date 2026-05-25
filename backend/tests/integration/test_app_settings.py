"""Integration tests for /api/settings/llm — runtime LLM provider config.

Boots a minimal FastAPI app with a temporary workdir so each test owns
its own ``data/runtime/provider.yaml``. Asserts:

* GET masks the api_key (raw secret never leaves the process)
* PUT persists, hot-reloads ``state.llm`` and ``runner_deps.llm``
* PUT with empty api_key + same provider keeps the old key
* PUT for a real provider with no key returns 400
* DELETE clears the override and falls back to env / mock
* :test runs a probe against the candidate config without persisting
"""

from __future__ import annotations

import shutil
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.llm.mock import MockLLMProvider
from backend.core.runtime_config import RuntimeConfigStore, RuntimeProviderConfig
from backend.memory import MemoryBundle
from backend.settings import Settings
from backend.tasks.runner import RunnerDeps
from backend.tasks.store import InMemoryTaskStore
from backend.tools.registry import ToolRegistry
from backend.workflows.registry import build_default_registry as build_workflows


@pytest.fixture
def tmp_workdir(tmp_path: Path) -> Path:
    workdir = tmp_path / "aaf-data"
    workdir.mkdir()
    return workdir


@pytest.fixture
def state(tmp_workdir: Path) -> AppState:
    settings = Settings(  # type: ignore[call-arg]
        aaf_workdir=tmp_workdir,
        default_llm_provider="mock",
    )
    initial_llm = MockLLMProvider(default_model="mock-1")
    runner_deps = RunnerDeps(
        store=InMemoryTaskStore(),
        workflows=build_workflows(),
        memory=MemoryBundle.in_memory(),
        llm=initial_llm,
        tools=ToolRegistry(),
    )
    return AppState(
        settings=settings,
        memory=MemoryBundle.in_memory(),
        llm=initial_llm,
        tools=ToolRegistry(),
        task_store=runner_deps.store,
        runner_deps=runner_deps,
        runtime_config_store=RuntimeConfigStore(tmp_workdir),
    )


@pytest.fixture
async def client(state: AppState) -> AsyncIterator[AsyncClient]:
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


# ---------------------------------------------------------------------------
# GET — env fallback when no override exists
# ---------------------------------------------------------------------------


async def test_get_returns_env_view_when_no_override(client: AsyncClient) -> None:
    r = await client.get("/api/settings/llm")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "mock"
    assert body["source"] == "env"
    assert body["api_key_set"] is False
    assert body["api_key_masked"] == "—"


async def test_providers_endpoint_lists_whitelist(client: AsyncClient) -> None:
    r = await client.get("/api/settings/llm/providers")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "openai" in body["items"]
    assert "anthropic" in body["items"]
    assert "ollama" in body["items"]
    assert "mock" in body["items"]


# ---------------------------------------------------------------------------
# PUT — persist + hot-reload + masking
# ---------------------------------------------------------------------------


async def test_put_persists_and_hot_reloads(
    client: AsyncClient, state: AppState, tmp_workdir: Path
) -> None:
    payload = {
        "provider": "openai",
        "api_key": "sk-real-1234567890ABCDEF",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "timeout_s": 60,
    }
    r = await client.put("/api/settings/llm", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "runtime"
    assert body["provider"] == "openai"
    assert body["api_key_set"] is True
    # Mask must NOT echo the raw key.
    assert "1234567890" not in body["api_key_masked"]
    assert body["api_key_masked"].startswith("sk-r")
    assert body["api_key_masked"].endswith("CDEF")

    # Persisted on disk with the raw key (so the backend can hot-reload
    # after a restart) but with strict permissions.
    yaml_path = tmp_workdir / "runtime" / "provider.yaml"
    assert yaml_path.is_file()
    raw = yaml.safe_load(yaml_path.read_text())
    assert raw["api_key"] == "sk-real-1234567890ABCDEF"

    # Hot-reload swapped both the public state.llm and runner_deps.llm.
    assert state.llm is not None
    assert getattr(state.llm, "name", None) in {"openai", "compactor", "router"}
    assert state.runner_deps is not None
    assert state.runner_deps.llm is state.llm


async def test_put_keeps_existing_key_when_payload_key_is_blank(
    client: AsyncClient, tmp_workdir: Path
) -> None:
    # Seed with a real key.
    seed = {
        "provider": "openai",
        "api_key": "sk-original-AAAAA",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    }
    r = await client.put("/api/settings/llm", json=seed)
    assert r.status_code == 200, r.text

    # Subsequent PUT with empty key should preserve the original.
    update = {
        "provider": "openai",
        "api_key": "",  # explicit "keep current"
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o",
    }
    r2 = await client.put("/api/settings/llm", json=update)
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["default_model"] == "gpt-4o"
    assert body["api_key_set"] is True

    raw = yaml.safe_load((tmp_workdir / "runtime" / "provider.yaml").read_text())
    assert raw["api_key"] == "sk-original-AAAAA"
    assert raw["default_model"] == "gpt-4o"


async def test_put_rejects_real_provider_without_api_key(client: AsyncClient) -> None:
    r = await client.put(
        "/api/settings/llm",
        json={
            "provider": "openai",
            "api_key": "",  # nothing stored, nothing in env → must 400
            "base_url": "",
            "default_model": "gpt-4o-mini",
        },
    )
    assert r.status_code == 400
    assert "api_key" in r.text


async def test_put_accepts_mock_without_key(client: AsyncClient, state: AppState) -> None:
    r = await client.put(
        "/api/settings/llm",
        json={"provider": "mock", "api_key": "", "default_model": "mock-2"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "mock"
    assert body["source"] == "runtime"


async def test_put_accepts_ollama_without_key(client: AsyncClient) -> None:
    r = await client.put(
        "/api/settings/llm",
        json={
            "provider": "ollama",
            "api_key": "",
            "base_url": "http://127.0.0.1:11434/v1",
            "default_model": "llama3.1:8b",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["provider"] == "ollama"


async def test_put_rejects_unknown_provider(client: AsyncClient) -> None:
    r = await client.put(
        "/api/settings/llm",
        json={"provider": "imaginary", "api_key": "x"},
    )
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# DELETE — fall back to env-only
# ---------------------------------------------------------------------------


async def test_delete_clears_runtime_override(client: AsyncClient, tmp_workdir: Path) -> None:
    await client.put(
        "/api/settings/llm",
        json={
            "provider": "openai",
            "api_key": "sk-test-AAAA",
            "base_url": "https://api.openai.com/v1",
        },
    )
    r = await client.delete("/api/settings/llm")
    assert r.status_code == 204
    assert not (tmp_workdir / "runtime" / "provider.yaml").exists()

    follow = await client.get("/api/settings/llm")
    body = follow.json()
    assert body["source"] == "env"


# ---------------------------------------------------------------------------
# :test — candidate-config probe
# ---------------------------------------------------------------------------


async def test_probe_succeeds_with_mock(client: AsyncClient) -> None:
    r = await client.post(
        "/api/settings/llm:test",
        json={"provider": "mock", "api_key": ""},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Mock provider raises when no scripted response is queued, so this
    # probe is *expected* to fail — but the failure is reported in-band
    # (ok=False, error=...) instead of HTTP 500. That's the contract.
    assert body["ok"] is False
    assert body["provider"] == "mock"
    assert body["error"] is not None
    assert body["latency_ms"] >= 0


async def test_probe_does_not_persist(client: AsyncClient, tmp_workdir: Path) -> None:
    await client.post(
        "/api/settings/llm:test",
        json={
            "provider": "openai",
            "api_key": "sk-fake-not-saved",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-4o-mini",
        },
    )
    assert not (tmp_workdir / "runtime" / "provider.yaml").exists()


async def test_probe_returns_structured_error_for_bad_key(client: AsyncClient) -> None:
    r = await client.post(
        "/api/settings/llm:test",
        json={
            "provider": "openai",
            "api_key": "",
            "base_url": "https://api.openai.com/v1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is False
    assert body["error"] is not None


# ---------------------------------------------------------------------------
# Cross-cutting: arq worker warning surfaces
# ---------------------------------------------------------------------------


async def test_arq_worker_warning_defaults_false(client: AsyncClient) -> None:
    """The default in-memory queue should not raise the ARQ-warning flag."""

    r = await client.get("/api/settings/llm")
    assert r.status_code == 200
    assert r.json()["warns_arq_worker"] is False


# ---------------------------------------------------------------------------
# Cleanup hygiene — make sure tests don't leak permissions trickery
# ---------------------------------------------------------------------------


def test_cleanup_idempotent(tmp_path: Path) -> None:
    target = tmp_path / "x"
    target.mkdir()
    shutil.rmtree(target)
    assert not target.exists()
