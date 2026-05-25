"""Unit tests for the MCP config loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.errors import ConfigError
from backend.tools.mcp_config import (
    MCPServerConfig,
    expand_env_refs,
    load_mcp_config,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    """Missing config = MCP-off (zero-config tenet)."""
    assert load_mcp_config(tmp_path / "nope.yaml") == []


def test_empty_file_returns_empty_list(tmp_path: Path) -> None:
    p = _write(tmp_path / "empty.yaml", "")
    assert load_mcp_config(p) == []


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    p = _write(tmp_path / "bad.yaml", "::not yaml::\n  - [")
    with pytest.raises(ConfigError, match="invalid YAML"):
        load_mcp_config(p)


def test_top_level_must_be_mapping(tmp_path: Path) -> None:
    p = _write(tmp_path / "list.yaml", "- a\n- b\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_mcp_config(p)


def test_unknown_field_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "extra.yaml",
        "servers:\n"
        "  - name: x\n"
        "    transport: stdio\n"
        "    command: echo\n"
        "    bogus_field: 1\n",
    )
    with pytest.raises(ConfigError, match="failed validation"):
        load_mcp_config(p)


def test_stdio_requires_command(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "no_cmd.yaml",
        "servers:\n  - name: x\n    transport: stdio\n",
    )
    with pytest.raises(ConfigError, match="requires `command`"):
        load_mcp_config(p)


def test_sse_requires_url(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "no_url.yaml",
        "servers:\n  - name: x\n    transport: sse\n",
    )
    with pytest.raises(ConfigError, match="requires `url`"):
        load_mcp_config(p)


def test_duplicate_server_names_rejected(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "dup.yaml",
        "servers:\n"
        "  - name: x\n    transport: stdio\n    command: a\n"
        "  - name: x\n    transport: stdio\n    command: b\n",
    )
    with pytest.raises(ConfigError, match="duplicate"):
        load_mcp_config(p)


def test_name_pattern_enforced(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "bad_name.yaml",
        "servers:\n  - name: 'Has Space'\n    transport: stdio\n    command: a\n",
    )
    with pytest.raises(ConfigError, match="failed validation"):
        load_mcp_config(p)


def test_full_round_trip(tmp_path: Path) -> None:
    p = _write(
        tmp_path / "ok.yaml",
        "servers:\n"
        "  - name: filesystem\n"
        "    transport: stdio\n"
        "    command: npx\n"
        "    args: [-y, '@modelcontextprotocol/server-filesystem', /tmp]\n"
        "    allow: [read_file, list_directory]\n"
        "    requires_network: false\n"
        "  - name: github\n"
        "    transport: sse\n"
        "    url: https://example.com/sse\n"
        "    headers:\n"
        "      Authorization: 'Bearer ${TEST_TOKEN_ABC}'\n"
        "    requires_network: true\n",
    )
    out = load_mcp_config(p)
    assert len(out) == 2

    fs, gh = out
    assert isinstance(fs, MCPServerConfig)
    assert fs.name == "filesystem"
    assert fs.transport == "stdio"
    assert fs.command == "npx"
    assert fs.args[0] == "-y"
    assert fs.allow == ["read_file", "list_directory"]
    assert fs.requires_network is False

    assert gh.name == "github"
    assert gh.transport == "sse"
    assert gh.url == "https://example.com/sse"
    # Env ref unset → empty string after substitution
    assert gh.headers["Authorization"] == "Bearer "
    assert gh.requires_network is True


def test_env_ref_expansion(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MY_TOKEN_X", "secret-123")
    p = _write(
        tmp_path / "env.yaml",
        "servers:\n"
        "  - name: x\n"
        "    transport: sse\n"
        "    url: https://h/${MY_TOKEN_X}/sse\n",
    )
    out = load_mcp_config(p)
    assert out[0].url == "https://h/secret-123/sse"


def test_expand_env_refs_unknown_becomes_empty() -> None:
    assert expand_env_refs("a-${DEFINITELY_NOT_SET_XYZ}-b") == "a--b"
