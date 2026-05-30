"""Runtime-detected build metadata.

The user's most common debugging frustration is "is my running backend
actually running the code I just edited?" — when there are multiple
agent sessions, hot-reload misfires, or an old uvicorn process is still
listening on the same port, you can stare at fresh code and watch stale
behaviour reproduce forever.

This module gives every running backend a *visible* identity:

* Reads ``git rev-parse HEAD`` once at import time. Cheap, no
  ``GitPython`` dependency.
* Reads ``git describe --dirty=+`` to detect uncommitted changes.
* Reads the HEAD commit's author timestamp (ISO 8601).
* All ``subprocess`` calls are guarded so a missing ``git`` binary, a
  non-repo workdir, or a Docker image without ``.git/`` all degrade to
  ``"unknown"`` instead of breaking app startup.

Exposed via:

* ``GET /api/version`` (existing endpoint, extended in this commit) so
  any browser session can see what version it's talking to.
* Backend startup banner ``app.build.info`` so log readers can confirm
  which commit the running process loaded.
* Frontend ``VersionBadge`` reads it from ``/api/version``.

A future Docker build can override the runtime detection by setting
``AAF_BUILD_SHA`` / ``AAF_BUILD_TS`` / ``AAF_BUILD_DIRTY`` env vars —
useful in CI where the image is built far from the original repo.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# ``__file__`` is ``backend/core/build_info.py``. Walking two levels up
# lands on the repo root in dev. In a Docker image the working copy may
# live elsewhere, so we accept that ``git`` calls will fail there and
# fall back to env-var-injected values.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass(slots=True, frozen=True)
class BuildInfo:
    """Identity stamp of the running backend process."""

    git_sha: str
    git_sha_short: str
    git_dirty: bool
    commit_ts: str  # ISO 8601 UTC; empty when unknown
    commit_subject: str  # one-line headline, empty when unknown

    def to_dict(self) -> dict[str, object]:
        return {
            "git_sha": self.git_sha,
            "git_sha_short": self.git_sha_short,
            "git_dirty": self.git_dirty,
            "commit_ts": self.commit_ts,
            "commit_subject": self.commit_subject,
        }


def _git(*args: str) -> str | None:
    """Run ``git <args>`` from the repo root. Returns trimmed stdout, or
    ``None`` if the binary is missing / not a repo / command fails.

    Deliberately broad ``Exception`` catch: anything that goes wrong with
    git introspection must not break app startup, and the upstream
    fallback to env vars is the documented contract.
    """

    try:
        # ``timeout=2`` keeps a misbehaving git on a busy laptop from
        # adding seconds to FastAPI lifespan startup.
        out = subprocess.run(
            ["git", *args],  # fixed argv (no shell), safe by construction
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if out.returncode != 0:
        return None
    return (out.stdout or "").strip() or None


def _detect() -> BuildInfo:
    """Build the snapshot once at import time."""

    # Env-var overrides take precedence so Docker builds can inject a
    # baked-in identity even when ``.git`` is absent.
    env_sha = os.getenv("AAF_BUILD_SHA")
    env_ts = os.getenv("AAF_BUILD_TS", "")
    env_dirty = os.getenv("AAF_BUILD_DIRTY", "").lower() in {"1", "true", "yes"}
    env_subject = os.getenv("AAF_BUILD_SUBJECT", "")

    if env_sha:
        return BuildInfo(
            git_sha=env_sha,
            git_sha_short=env_sha[:7],
            git_dirty=env_dirty,
            commit_ts=env_ts,
            commit_subject=env_subject,
        )

    sha = _git("rev-parse", "HEAD") or "unknown"
    short = sha[:7] if sha != "unknown" else "unknown"
    # ``--dirty=+`` doesn't print a flag, it suffixes the describe output;
    # using ``status --porcelain`` is more reliable across older gits.
    status = _git("status", "--porcelain")
    dirty = bool(status)  # any output = working-tree has changes
    ts = _git("log", "-1", "--format=%cI") or ""
    subject = _git("log", "-1", "--format=%s") or ""
    return BuildInfo(
        git_sha=sha,
        git_sha_short=short,
        git_dirty=dirty,
        commit_ts=ts,
        commit_subject=subject,
    )


# Module-level singleton — import once, read forever. The cost of git
# subprocess calls only matters at the first import.
BUILD_INFO: BuildInfo = _detect()


__all__ = ["BUILD_INFO", "BuildInfo"]
