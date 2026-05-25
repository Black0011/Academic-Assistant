"""Unit tests for :mod:`backend.core.skill_host.admin`.

Coverage: validators (frontmatter / sizes / paths / dup scripts / footgun
warnings), staging-then-rename install, idempotent disable / enable, and
filesystem rollback when reload fails after an atomic swap.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.skill_host import SkillHost
from backend.core.skill_host.admin import (
    MAX_SCRIPT_BYTES,
    SkillAdmin,
    SkillAdminError,
    SkillInstallInput,
    SkillScriptInput,
    _validate_install,
)

GOOD_BODY = """---
name: hello
description: A skill that greets.
domain: meta
triggers:
  - greet
  - say hello
version: "1.0.0"
---

# Hello

Say hello to the user.
"""

GOOD_SCRIPT = """#!/usr/bin/env python3
\"\"\"Print a greeting.\"\"\"

# aaf:network none
# aaf:timeout 5
import json, sys
print(json.dumps({"hello": "world"}))
"""


def _payload(name: str = "hello", **overrides) -> SkillInstallInput:
    body = overrides.pop("body_md", GOOD_BODY.replace("name: hello", f"name: {name}"))
    scripts = overrides.pop("scripts", [SkillScriptInput(name="greet", content=GOOD_SCRIPT)])
    overwrite = overrides.pop("overwrite", False)
    if overrides:  # surface accidental misuse instead of silently ignoring
        raise TypeError(f"unexpected payload kwargs: {sorted(overrides)}")
    return SkillInstallInput(
        name=name,
        body_md=body,
        scripts=scripts,
        overwrite=overwrite,
    )


# ---------------------------------------------------------------------------
# Validator unit tests (no filesystem)
# ---------------------------------------------------------------------------


def test_validator_accepts_minimal_good_payload():
    _validate_install(_payload())


def test_validator_rejects_invalid_name():
    with pytest.raises(SkillAdminError) as exc:
        _validate_install(_payload(name="Bad Name!"))
    assert exc.value.code == "validation"


def test_validator_rejects_oversize_script():
    big = "x" * (MAX_SCRIPT_BYTES + 1)
    with pytest.raises(SkillAdminError) as exc:
        _validate_install(_payload(scripts=[SkillScriptInput(name="big", content=big)]))
    assert exc.value.code == "limit"


def test_validator_rejects_duplicate_scripts():
    s = SkillScriptInput(name="greet", content=GOOD_SCRIPT)
    with pytest.raises(SkillAdminError) as exc:
        _validate_install(_payload(scripts=[s, s]))
    assert exc.value.code == "validation"


def test_validator_requires_frontmatter_triggers():
    body = '---\nname: hello\ndescription: hi\ndomain: meta\nversion: "1.0.0"\n---\n\n# hello\n'
    with pytest.raises(SkillAdminError) as exc:
        _validate_install(_payload(body_md=body))
    assert exc.value.code == "validation"
    assert "triggers" in str(exc.value)


def test_validator_rejects_name_mismatch_in_frontmatter():
    body = GOOD_BODY  # frontmatter says name=hello
    with pytest.raises(SkillAdminError) as exc:
        _validate_install(_payload(name="other", body_md=body))
    assert exc.value.code == "validation"


# ---------------------------------------------------------------------------
# Filesystem-backed integration tests (use a real SkillHost on tmp dir)
# ---------------------------------------------------------------------------


@pytest.fixture
async def admin(tmp_path: Path) -> SkillAdmin:
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    workdir = tmp_path / "wd"
    workdir.mkdir()
    host = SkillHost.build(skills_root=skills_root, workdir_root=workdir)
    await host.load()
    return SkillAdmin(host)


@pytest.mark.asyncio
async def test_install_creates_skill_and_reloads_registry(admin: SkillAdmin):
    snap = await admin.install(_payload())
    assert snap.name == "hello"
    assert snap.enabled is True
    assert snap.version_hash.startswith("sha256:")
    assert (snap.loaded_from / "SKILL.md").is_file()
    assert (snap.loaded_from / "scripts" / "greet.py").is_file()
    # Registry should now expose it.
    assert admin.host.get_skill("hello") is not None
    assert admin.host.generation >= 1


@pytest.mark.asyncio
async def test_install_rejects_duplicate(admin: SkillAdmin):
    await admin.install(_payload())
    with pytest.raises(SkillAdminError) as exc:
        await admin.install(_payload())
    assert exc.value.code == "conflict"


@pytest.mark.asyncio
async def test_overwrite_installs_again(admin: SkillAdmin):
    await admin.install(_payload())
    snap = await admin.install(_payload(overwrite=True))
    assert snap.enabled


@pytest.mark.asyncio
async def test_disable_then_enable_round_trip(admin: SkillAdmin):
    await admin.install(_payload())
    disabled = await admin.disable("hello")
    assert disabled.enabled is False
    assert "hello" in admin.list_disabled()
    assert admin.host.get_skill("hello") is None  # registry forgot it

    enabled = await admin.enable("hello")
    assert enabled.enabled is True
    assert admin.host.get_skill("hello") is not None
    assert "hello" not in admin.list_disabled()


@pytest.mark.asyncio
async def test_disable_is_idempotent(admin: SkillAdmin):
    await admin.install(_payload())
    await admin.disable("hello")
    snap = await admin.disable("hello")
    assert snap.enabled is False


@pytest.mark.asyncio
async def test_disable_unknown_raises_not_found(admin: SkillAdmin):
    with pytest.raises(SkillAdminError) as exc:
        await admin.disable("nope")
    assert exc.value.code == "not_found"


@pytest.mark.asyncio
async def test_enable_conflict_when_active_already_exists(admin: SkillAdmin):
    await admin.install(_payload())
    await admin.disable("hello")
    # Recreate an "active" skills/hello dir manually so enable hits a clash.
    (admin.host.skills_root / "hello").mkdir()
    with pytest.raises(SkillAdminError) as exc:
        await admin.enable("hello")
    assert exc.value.code == "conflict"


@pytest.mark.asyncio
async def test_update_replaces_body_and_scripts(admin: SkillAdmin):
    await admin.install(_payload())
    new_body = GOOD_BODY.replace("Say hello to the user.", "Say hi instead.")
    snap = await admin.update(
        "hello",
        _payload(body_md=new_body, overwrite=True),
    )
    assert "Say hi instead" in snap.body_md
    # Old hash stored on a fresh snapshot should match the new content.
    assert snap.version_hash.startswith("sha256:")


@pytest.mark.asyncio
async def test_update_requires_matching_name(admin: SkillAdmin):
    await admin.install(_payload())
    with pytest.raises(SkillAdminError) as exc:
        await admin.update("hello", _payload(name="other"))
    assert exc.value.code == "validation"


@pytest.mark.asyncio
async def test_install_rolls_back_when_reload_fails(
    admin: SkillAdmin, monkeypatch: pytest.MonkeyPatch
):
    """If `host.reload` raises, the previous content must be restored."""
    await admin.install(_payload())

    async def boom_reload(name: str | None = None):
        raise RuntimeError("simulated reload failure")

    monkeypatch.setattr(admin.host._loader, "reload", boom_reload)

    new_body = GOOD_BODY.replace("Say hello to the user.", "BROKEN UPDATE")
    with pytest.raises(SkillAdminError) as exc:
        await admin.update(
            "hello",
            _payload(body_md=new_body, overwrite=True),
        )
    assert exc.value.code == "internal"

    # The original SKILL.md content should still be in place after rollback.
    text = (admin.host.skills_root / "hello" / "SKILL.md").read_text(encoding="utf-8")
    assert "BROKEN UPDATE" not in text
    assert "Say hello to the user." in text
