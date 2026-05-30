"""Unit tests for :mod:`backend.core.build_info`.

Covers the three degradation paths in :func:`backend.core.build_info._detect`:

* Env-var override path (Docker baked-in identity).
* Git-detected path (dev workspace).
* Total absence (no git, no env vars) → ``"unknown"`` placeholders.

These checks matter because the build-info module is loaded at FastAPI
startup; a crash here would block app boot.
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from backend.core.build_info import BUILD_INFO, BuildInfo, _detect


def test_module_singleton_loaded():
    """Sanity: the module-level singleton must be a :class:`BuildInfo`
    with the full set of fields. If a future refactor drops a field
    every consumer (API, log, frontend) will need to compensate; this
    test guards the schema."""

    assert isinstance(BUILD_INFO, BuildInfo)
    assert hasattr(BUILD_INFO, "git_sha")
    assert hasattr(BUILD_INFO, "git_sha_short")
    assert hasattr(BUILD_INFO, "git_dirty")
    assert hasattr(BUILD_INFO, "commit_ts")
    assert hasattr(BUILD_INFO, "commit_subject")


def test_to_dict_round_trip_keys():
    """``to_dict`` is what /api/version returns. Pin the key set so a
    frontend type drift gets caught at the seam rather than at runtime."""

    info = BuildInfo(
        git_sha="abc1234abcdef",
        git_sha_short="abc1234",
        git_dirty=False,
        commit_ts="2026-05-12T10:00:00+00:00",
        commit_subject="test commit",
    )
    out = info.to_dict()
    assert set(out.keys()) == {
        "git_sha",
        "git_sha_short",
        "git_dirty",
        "commit_ts",
        "commit_subject",
    }


def test_env_override_takes_precedence():
    """When ``AAF_BUILD_SHA`` is set (Docker / CI), git introspection is
    skipped and the env values flow through unchanged. ``_short`` is
    derived from the first 7 chars."""

    with patch.dict(
        os.environ,
        {
            "AAF_BUILD_SHA": "deadbeefcafebabe1234567890",
            "AAF_BUILD_TS": "2026-05-12T08:00:00Z",
            "AAF_BUILD_DIRTY": "true",
            "AAF_BUILD_SUBJECT": "container build",
        },
        clear=False,
    ):
        info = _detect()
    assert info.git_sha == "deadbeefcafebabe1234567890"
    assert info.git_sha_short == "deadbee"
    assert info.git_dirty is True
    assert info.commit_ts == "2026-05-12T08:00:00Z"
    assert info.commit_subject == "container build"


def test_env_override_dirty_parses_truthy_strings():
    """``AAF_BUILD_DIRTY`` accepts the common truthy spellings (CI
    pipelines vary). Anything else is False — including empty string,
    which is the most likely real-world value."""

    for truthy in ("1", "true", "TRUE", "yes", "Yes"):
        with patch.dict(
            os.environ, {"AAF_BUILD_SHA": "x" * 8, "AAF_BUILD_DIRTY": truthy}, clear=False
        ):
            assert _detect().git_dirty is True
    for falsy in ("0", "false", "", "no", "off"):
        with patch.dict(
            os.environ, {"AAF_BUILD_SHA": "x" * 8, "AAF_BUILD_DIRTY": falsy}, clear=False
        ):
            assert _detect().git_dirty is False


def test_detect_falls_back_to_unknown_when_no_git_and_no_env(monkeypatch):
    """The unhappy path: no env var override, ``git`` subprocess fails
    (binary missing or .git absent). The function must still return a
    valid BuildInfo with ``"unknown"`` placeholders so app startup
    proceeds rather than crashing."""

    # Clear env first so the override branch doesn't short-circuit.
    for var in ("AAF_BUILD_SHA", "AAF_BUILD_TS", "AAF_BUILD_DIRTY", "AAF_BUILD_SUBJECT"):
        monkeypatch.delenv(var, raising=False)

    # Force the internal helper to behave as if every git call failed.
    monkeypatch.setattr("backend.core.build_info._git", lambda *_a, **_kw: None)

    info = _detect()
    assert info.git_sha == "unknown"
    assert info.git_sha_short == "unknown"
    assert info.git_dirty is False
    assert info.commit_ts == ""
    assert info.commit_subject == ""


@pytest.mark.parametrize("returncode,stdout", [(0, ""), (0, "   \n  "), (1, "anything")])
def test_git_helper_returns_none_on_empty_or_failed_output(returncode, stdout, monkeypatch):
    """``_git`` must distinguish "empty stdout" from "successful empty
    answer" — both should yield ``None`` so the caller falls back."""

    class _FakeProc:
        def __init__(self, rc, out):
            self.returncode = rc
            self.stdout = out

    monkeypatch.setattr(
        "backend.core.build_info.subprocess.run",
        lambda *_a, **_kw: _FakeProc(returncode, stdout),
    )
    from backend.core.build_info import _git

    assert _git("rev-parse", "HEAD") is None
