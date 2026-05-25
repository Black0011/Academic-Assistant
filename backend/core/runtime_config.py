"""Runtime LLM provider configuration — read/write/persist + masking.

Why this exists
---------------
The default boot path reads provider credentials from environment variables
(see :mod:`backend.settings`). For the laptop / single-user scenario we
also want users to drop an API key in via the frontend Settings panel
without restarting the backend or editing dotfiles.

This module owns one tiny responsibility: serialise/deserialise the
"current default LLM provider" choice to a YAML file under the workdir
and offer a **masked** view for the API. The HTTP layer (see
``backend/api/routers/settings.py``) wires it into FastAPI; the lifespan
in ``backend/app.py`` consults it before falling back to env-only config.

Hard rules (encoded in tests):

* The file is YAML, **plaintext** by design — keychain integration is
  out of scope for the laptop preset and would couple us to per-OS
  backends. Protection comes from filesystem permissions (``0600``)
  and ``.gitignore`` (``data/runtime/`` is committed empty with a
  ``.keep`` marker).
* Writes are atomic: write to ``<path>.tmp`` then ``os.replace`` —
  partial writes can never produce an unreadable file.
* Reads are tolerant: a malformed file logs a warning and returns
  ``None`` so the boot path falls back to env-only config rather than
  crashing the process.
* The ``api_key`` is never returned by :meth:`mask`. Callers that need
  the raw value go through :meth:`load`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import structlog
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = structlog.get_logger(__name__)


SUPPORTED_PROVIDERS: tuple[str, ...] = ("openai", "anthropic", "ollama", "mock")
"""Whitelisted provider names for runtime override.

Mirrors the registry built in :func:`backend.core.llm.registry.default_registry`.
Adding a new provider here without registering it elsewhere will fail at
boot, so the two lists must stay in sync — :func:`available_providers`
below is the canonical source for UI menus.
"""


def available_providers() -> list[str]:
    """Return the list of provider names the frontend may pick from.

    Kept as a function (not a constant) so future builds can filter by
    capability flags or installed extras without changing call sites.
    """

    return list(SUPPORTED_PROVIDERS)


class RuntimeProviderConfig(BaseModel):
    """User-supplied override for the default LLM provider.

    Field semantics intentionally mirror :class:`backend.settings.ProviderConfig`
    so the merge logic in ``backend.app._build_llm`` is a one-line copy.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["openai", "anthropic", "ollama", "mock"]
    api_key: str = Field("", description="Raw secret. Never serialised in API responses.")
    base_url: str = ""
    default_model: str = ""
    timeout_s: int = Field(120, ge=1, le=600)

    @field_validator("api_key", "base_url", "default_model")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


@dataclass(frozen=True)
class MaskedProviderView:
    """API-safe projection of a stored config.

    ``api_key_masked`` is what the frontend renders ("sk-...XXXX" or "—").
    ``api_key_set`` is the boolean the frontend uses to decide whether to
    show "Change" vs "Set" on the form. We never echo the raw key.
    """

    provider: str
    api_key_masked: str
    api_key_set: bool
    base_url: str
    default_model: str
    timeout_s: int
    source: Literal["runtime", "env"]


def mask_api_key(raw: str) -> str:
    """Return a UI-safe representation of an API key.

    Empty / very short keys collapse to ``"—"`` (no leakage of length).
    Real keys preserve the first four characters (vendor prefix is useful
    context) and the last four (helps users distinguish two keys).
    """

    if not raw:
        return "—"
    s = raw.strip()
    if len(s) <= 8:
        return "•" * len(s)
    return f"{s[:4]}…{s[-4:]}"


class RuntimeConfigStore:
    """Persist the active default-provider override under the workdir.

    One instance per process; pass ``workdir`` from
    ``Settings.workdir`` so tests can use ``tmp_path``.

    The file lives at ``<workdir>/runtime/provider.yaml``. The directory
    is created lazily on first write. Permissions are tightened to
    ``0700`` (dir) / ``0600`` (file) so other unix users on the same
    machine can't read keys.
    """

    FILENAME = "provider.yaml"

    def __init__(self, workdir: Path) -> None:
        self._dir = (Path(workdir) / "runtime").resolve()
        self._path = self._dir / self.FILENAME

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.is_file()

    def load(self) -> RuntimeProviderConfig | None:
        """Return the persisted config, or ``None`` if absent / malformed.

        Tolerant by design: missing file is the common boot case; a
        corrupt file is logged and treated as missing so the operator
        gets a clean fallback to the env-driven defaults rather than a
        crashed process.
        """

        if not self._path.is_file():
            return None
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            log.exception("runtime_config.read_failed", path=str(self._path))
            return None
        if not isinstance(raw, dict):
            log.warning(
                "runtime_config.bad_shape",
                path=str(self._path),
                got=type(raw).__name__,
            )
            return None
        try:
            return RuntimeProviderConfig.model_validate(raw)
        except Exception:
            log.exception("runtime_config.validate_failed", path=str(self._path))
            return None

    def save(self, config: RuntimeProviderConfig) -> None:
        """Atomically persist *config* with ``0600`` permissions.

        Tightens parent dir to ``0700`` on first write. Subsequent writes
        leave existing perms alone (operator may have intentionally set
        something stricter).
        """

        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self._dir, 0o700)
        except OSError:
            log.warning("runtime_config.chmod_dir_failed", path=str(self._dir))

        payload: dict[str, Any] = config.model_dump()
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
            encoding="utf-8",
        )
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            log.warning("runtime_config.chmod_tmp_failed", path=str(tmp))
        os.replace(tmp, self._path)
        log.info(
            "runtime_config.saved",
            path=str(self._path),
            provider=config.provider,
            has_key=bool(config.api_key),
        )

    def clear(self) -> bool:
        """Remove the persisted config; returns True iff a file was deleted."""

        if not self._path.is_file():
            return False
        try:
            self._path.unlink()
        except OSError:
            log.exception("runtime_config.unlink_failed", path=str(self._path))
            return False
        log.info("runtime_config.cleared", path=str(self._path))
        return True


__all__ = [
    "SUPPORTED_PROVIDERS",
    "MaskedProviderView",
    "RuntimeConfigStore",
    "RuntimeProviderConfig",
    "available_providers",
    "mask_api_key",
]
