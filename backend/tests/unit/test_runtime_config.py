"""Unit tests for backend.core.runtime_config.

Covers:
* round-trip persistence (save → reload identical content)
* tolerant loader (missing file / corrupt YAML / wrong shape → None)
* atomic write (no .tmp left behind, file mode 0600 on POSIX)
* mask_api_key edge cases (empty / short / typical)
* SUPPORTED_PROVIDERS matches the runtime registry — guards against
  drift between the UI whitelist and the actual factory dict.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.llm.registry import default_registry
from backend.core.runtime_config import (
    SUPPORTED_PROVIDERS,
    RuntimeConfigStore,
    RuntimeProviderConfig,
    available_providers,
    mask_api_key,
)


def _minimal(
    provider: str,
    *,
    api_key: str = "",
    base_url: str = "",
    default_model: str = "",
    timeout_s: int = 120,
) -> RuntimeProviderConfig:
    """Build a config with all fields explicit (mypy strict + pydantic plugin)."""

    return RuntimeProviderConfig(
        provider=provider,  # type: ignore[arg-type]
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
        timeout_s=timeout_s,
    )


def test_supported_providers_match_registry() -> None:
    """SUPPORTED_PROVIDERS must be a subset of the registry's factory keys.

    If somebody adds a new provider to the registry but forgets to
    whitelist it here, the frontend dropdown won't show it (acceptable);
    if somebody whitelists one without a factory, PUT will 500 at runtime
    (not acceptable). This test guards the second direction.
    """

    reg = default_registry()
    for name in SUPPORTED_PROVIDERS:
        assert reg.has(name), f"runtime_config whitelists {name!r} but registry lacks a factory"
    assert available_providers() == list(SUPPORTED_PROVIDERS)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", "—"),
        ("a", "•"),
        ("abc", "•••"),
        ("abcdefgh", "••••••••"),
        ("sk-proj-abcdefghijkl", "sk-p…ijkl"),
        ("  sk-XX-AAAAAAAAA-BBBB  ", "sk-X…BBBB"),
    ],
)
def test_mask_api_key(raw: str, expected: str) -> None:
    assert mask_api_key(raw) == expected


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    cfg = RuntimeProviderConfig(
        provider="openai",
        api_key="sk-test-1234567890",
        base_url="https://api.openai.com/v1",
        default_model="gpt-4o-mini",
        timeout_s=30,
    )
    assert not store.exists()

    store.save(cfg)

    assert store.exists()
    reloaded = store.load()
    assert reloaded is not None
    assert reloaded.model_dump() == cfg.model_dump()


def test_save_writes_file_atomically(tmp_path: Path) -> None:
    """No .tmp companion should survive after save (atomic os.replace)."""

    store = RuntimeConfigStore(tmp_path)
    store.save(_minimal("mock"))
    siblings = list(store.path.parent.iterdir())
    assert all(not p.name.endswith(".tmp") for p in siblings), siblings


@pytest.mark.skipif(sys.platform.startswith("win"), reason="POSIX file mode only")
def test_save_sets_strict_permissions(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    store.save(_minimal("openai", api_key="sk-x"))
    mode = store.path.stat().st_mode & 0o777
    assert mode == 0o600, oct(mode)


def test_load_returns_none_when_file_missing(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    assert store.load() is None


def test_load_returns_none_on_malformed_yaml(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(":\n  - not: [valid", encoding="utf-8")
    assert store.load() is None


def test_load_returns_none_on_wrong_shape(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("just-a-string\n", encoding="utf-8")
    assert store.load() is None


def test_load_returns_none_on_unknown_provider(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("provider: imaginary\napi_key: abc\n", encoding="utf-8")
    assert store.load() is None


def test_clear_removes_existing_file(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    store.save(_minimal("mock"))
    assert store.clear() is True
    assert not store.exists()
    # Idempotent: clearing twice doesn't raise.
    assert store.clear() is False


def test_runtime_provider_config_strips_whitespace() -> None:
    cfg = _minimal(
        "openai",
        api_key="  sk-x  ",
        base_url="  https://api.openai.com/v1  ",
        default_model="  gpt-4o-mini  ",
    )
    assert cfg.api_key == "sk-x"
    assert cfg.base_url == "https://api.openai.com/v1"
    assert cfg.default_model == "gpt-4o-mini"


def test_runtime_provider_config_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        # Bad provider name on purpose; mypy correctly flags it, but the
        # validation error is exactly what we're asserting.
        RuntimeProviderConfig(  # type: ignore[call-arg]
            provider="imaginary",  # type: ignore[arg-type]
        )


def test_runtime_provider_config_rejects_extreme_timeout() -> None:
    with pytest.raises(ValidationError):
        _minimal("mock", timeout_s=0)
    with pytest.raises(ValidationError):
        _minimal("mock", timeout_s=601)


def test_path_is_under_workdir(tmp_path: Path) -> None:
    store = RuntimeConfigStore(tmp_path)
    assert store.path == (tmp_path / "runtime" / "provider.yaml").resolve()
    # We don't accidentally reach outside the workdir even with .. tricks.
    assert os.fspath(store.path).startswith(os.fspath(tmp_path))
