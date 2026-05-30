"""Configuration models + YAML loader for MCP servers.

YAML schema (see ``config/mcp_servers.example.yaml``)::

    servers:
      - name: filesystem
        transport: stdio
        command: npx
        args: ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        env: {}
        allow:               # optional allowlist of tool names; null = all
          - read_file
          - list_directory
        requires_network: false
        requires_paid_api: false

      - name: github
        transport: sse
        url: https://mcp.example.com/sse
        headers:
          Authorization: Bearer ${GITHUB_TOKEN}

Design notes:

* Empty/missing config file is **not** an error — the loader returns an
  empty list so the app boots in MCP-off mode by default. This matches
  the "AAF starts with zero config" tenet from PLAN.md §1.
* ``${VAR}`` references inside string fields are expanded against
  ``os.environ`` at load time, so secrets stay out of the YAML.
* Validation errors are wrapped in :class:`backend.core.errors.ConfigError`
  (per ``aaf-python-style.mdc`` § Errors).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.core.errors import ConfigError

MCPTransport = Literal["stdio", "sse"]

# ${VAR} or ${VAR:-default} — same syntax as docker-compose. We support
# the simple form here; defaults are an unnecessary nicety for v1.
_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class MCPServerConfig(BaseModel):
    """One MCP server entry."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    transport: MCPTransport = "stdio"

    # stdio fields
    command: str = ""
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str = ""

    # sse fields
    url: str = ""
    headers: dict[str, str] = Field(default_factory=dict)

    # cross-cutting
    allow: list[str] | None = None
    requires_network: bool = False
    requires_paid_api: bool = False

    # connect_timeout_s applies to both transports; tools have their own
    # per-call timeout that the runtime injects from settings.
    connect_timeout_s: float = 10.0

    def validate_for_transport(self) -> None:
        """Cross-field check Pydantic can't express directly."""
        if self.transport == "stdio":
            if not self.command:
                raise ConfigError(
                    f"mcp server '{self.name}': stdio transport requires `command`"
                )
        elif self.transport == "sse":
            if not self.url:
                raise ConfigError(
                    f"mcp server '{self.name}': sse transport requires `url`"
                )


class MCPConfigFile(BaseModel):
    """Top-level YAML schema."""

    model_config = ConfigDict(extra="forbid")

    servers: list[MCPServerConfig] = Field(default_factory=list)


def expand_env_refs(value: str) -> str:
    """Substitute ``${VAR}`` placeholders against ``os.environ``.

    Unknown variables are replaced with the empty string — same as a
    POSIX shell. We log nothing here; the caller decides how loud to be
    about a missing variable (for now: silently empty, which surfaces
    via "auth failed" at first call instead of refusing to boot).
    """

    def _sub(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_REF.sub(_sub, value)


def _expand_in_obj(obj: object) -> object:
    """Walk a YAML-decoded structure and expand env refs in str leaves.

    The annotation is `object` rather than ``Any`` because the YAML
    boundary is exactly the validated-external-boundary case allowed by
    `aaf-python-style.mdc` § Types — but we already did the validation
    via ``MCPConfigFile`` further down, so here we only see plain Python
    primitives.
    """
    if isinstance(obj, str):
        return expand_env_refs(obj)
    if isinstance(obj, list):
        return [_expand_in_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand_in_obj(v) for k, v in obj.items()}
    return obj


def load_mcp_config(path: str | Path) -> list[MCPServerConfig]:
    """Load and validate the MCP server config file.

    Returns an empty list when the file is missing — that's the
    "MCP-off" state. Any other failure (unreadable file, invalid YAML,
    schema mismatch) is surfaced as :class:`ConfigError`.
    """

    p = Path(path)
    if not p.exists():
        return []
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigError(f"unable to read MCP config at {p}: {exc}") from exc

    try:
        data: object = yaml.safe_load(raw) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid YAML at {p}: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(
            f"MCP config at {p} must be a mapping, got {type(data).__name__}"
        )

    expanded = _expand_in_obj(data)
    # _expand_in_obj preserves shape; we already checked the top is a dict.
    assert isinstance(expanded, dict)

    try:
        cfg = MCPConfigFile.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigError(f"MCP config at {p} failed validation: {exc}") from exc

    seen: set[str] = set()
    for s in cfg.servers:
        if s.name in seen:
            raise ConfigError(f"duplicate MCP server name '{s.name}'")
        seen.add(s.name)
        s.validate_for_transport()
    return list(cfg.servers)


def load_mcp_json(path: str | Path) -> list[MCPServerConfig]:
    """Load MCP config from a .mcp.json file (Claude Code format).

    Format: ``{"mcpServers": {"server-name": {"command": ..., "args": [...]}}}``
    Transforms into the AAF YAML shape for validation.
    """
    import json as _json

    p = Path(path)
    if not p.exists():
        return []
    try:
        data = _json.loads(p.read_text(encoding="utf-8"))
    except (_json.JSONDecodeError, OSError) as exc:
        raise ConfigError(f"invalid .mcp.json at {p}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f".mcp.json at {p} must be a mapping")
    mcp_servers = data.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        raise ConfigError(f"mcpServers at {p} must be a mapping")

    servers: list[dict] = []
    for name, cfg in mcp_servers.items():
        if not isinstance(cfg, dict):
            continue
        entry: dict = {"name": name}
        if "command" in cfg:
            entry["transport"] = "stdio"
            entry["command"] = cfg["command"]
            entry["args"] = cfg.get("args", [])
            if "env" in cfg:
                entry["env"] = cfg["env"]
        elif "url" in cfg:
            entry["transport"] = "sse"
            entry["url"] = cfg["url"]
        else:
            entry["transport"] = cfg.get("transport", "stdio")
            if "command" in cfg:
                entry["command"] = cfg["command"]
        servers.append(entry)

    expanded = _expand_in_obj({"servers": servers})
    assert isinstance(expanded, dict)
    try:
        cfg = MCPConfigFile.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigError(f"mcp.json at {p} failed validation: {exc}") from exc

    seen: set[str] = set()
    for s in cfg.servers:
        if s.name in seen:
            raise ConfigError(f"duplicate MCP server name '{s.name}'")
        seen.add(s.name)
        s.validate_for_transport()
    return list(cfg.servers)


__all__ = [
    "MCPConfigFile",
    "MCPServerConfig",
    "MCPTransport",
    "expand_env_refs",
    "load_mcp_config",
    "load_mcp_json",
]
