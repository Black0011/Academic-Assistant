"""Unit tests for :mod:`backend.manuscripts.bundle_storage`.

Covers the security surface (path containment, size caps), the layout
guard (single layout rejected), and the basic CRUD on a tmp-path-backed
bundle.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.errors import (
    ManuscriptBundleTooLarge,
    ManuscriptFileTooLarge,
    ManuscriptLayoutMismatch,
    ManuscriptPathInvalid,
)
from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.models import Manuscript


def _make_bundle_record(
    *,
    manuscript_id: str = "m1",
    link_path: str | None = None,
    layout: str = "bundle",
) -> Manuscript:
    return Manuscript.model_validate(
        {
            "id": manuscript_id,
            "layout": layout,
            "bundle_link_path": link_path,
        }
    )


def _make_storage(tmp_path: Path, *, max_file_mb: int = 1, max_bundle_mb: int = 4) -> BundleStorage:
    return BundleStorage(
        root=tmp_path / "manuscripts",
        max_file_bytes=max_file_mb * 1024 * 1024,
        max_bundle_bytes=max_bundle_mb * 1024 * 1024,
    )


# ---------------------------------------------------------------------------
# layout guard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_single_layout_rejected(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    record = _make_bundle_record(layout="single")
    with pytest.raises(ManuscriptLayoutMismatch):
        await storage.list_tree(record)


# ---------------------------------------------------------------------------
# init_for / physical_root
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copy_mode_provisions_work_dir(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    record = _make_bundle_record(manuscript_id="copy1")
    root = await storage.init_for(record)
    assert root.exists() and root.is_dir()
    assert root == (tmp_path / "manuscripts" / "copy1" / "work").resolve()


@pytest.mark.asyncio
async def test_link_mode_requires_existing_dir(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    bogus = tmp_path / "does_not_exist"
    record = _make_bundle_record(link_path=str(bogus))
    with pytest.raises(ManuscriptPathInvalid):
        await storage.init_for(record)


@pytest.mark.asyncio
async def test_link_mode_uses_user_dir(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    user_dir = tmp_path / "user_paper"
    user_dir.mkdir()
    (user_dir / "main.tex").write_text("\\documentclass{article}\n")

    record = _make_bundle_record(link_path=str(user_dir))
    root = await storage.init_for(record)
    assert root == user_dir.resolve()
    manifest = await storage.list_tree(record)
    assert manifest.link_mode is True
    assert {f.path for f in manifest.files} == {"main.tex"}


# ---------------------------------------------------------------------------
# Path safety — the security-critical surface.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad",
    [
        "../../etc/passwd",
        "subdir/../../escape",
        "/absolute/path",
        "",
        "   ",
    ],
)
async def test_unsafe_paths_are_rejected(tmp_path: Path, bad: str) -> None:
    storage = _make_storage(tmp_path)
    record = _make_bundle_record()
    await storage.init_for(record)
    with pytest.raises(ManuscriptPathInvalid):
        await storage.write_text(record, bad, "x")


@pytest.mark.asyncio
async def test_symlink_escape_is_rejected(tmp_path: Path) -> None:
    """A symlink pointing outside the bundle root must not allow reads."""
    storage = _make_storage(tmp_path)
    record = _make_bundle_record(manuscript_id="sym")
    root = await storage.init_for(record)

    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    bad_link = root / "leak"
    try:
        bad_link.symlink_to(secret)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not supported on this platform")
    with pytest.raises(ManuscriptPathInvalid):
        await storage.read_bytes(record, "leak")


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_then_read_then_delete_roundtrip(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    record = _make_bundle_record(manuscript_id="crud")
    await storage.init_for(record)

    meta = await storage.write_text(record, "sections/intro.tex", "Hello \\LaTeX")
    assert meta.path == "sections/intro.tex"
    assert meta.is_text is True
    assert meta.size > 0

    text = await storage.read_text(record, "sections/intro.tex")
    assert text == "Hello \\LaTeX"

    manifest = await storage.list_tree(record)
    assert manifest.file_count == 1
    assert manifest.files[0].path == "sections/intro.tex"
    assert manifest.total_size == meta.size

    deleted = await storage.delete_path(record, "sections/intro.tex")
    assert deleted is True
    assert (await storage.list_tree(record)).file_count == 0


@pytest.mark.asyncio
async def test_list_tree_skips_default_ignored_dirs(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    record = _make_bundle_record(manuscript_id="ignore")
    root = await storage.init_for(record)

    (root / "main.tex").write_text("body")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "junk.pyc").write_bytes(b"\x00\x01")
    (root / ".git").mkdir()
    (root / ".git" / "HEAD").write_text("ref: refs/heads/main")
    (root / ".DS_Store").write_bytes(b"\x00")

    manifest = await storage.list_tree(record)
    assert {f.path for f in manifest.files} == {"main.tex"}

    # include_hidden=True restores them.
    full = await storage.list_tree(record, include_hidden=True)
    assert {f.path for f in full.files} == {
        "main.tex",
        "__pycache__/junk.pyc",
        ".git/HEAD",
        ".DS_Store",
    }


# ---------------------------------------------------------------------------
# Size caps
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_file_cap(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path, max_file_mb=1)
    record = _make_bundle_record(manuscript_id="cap1")
    await storage.init_for(record)
    payload = b"x" * (1024 * 1024 + 1)
    with pytest.raises(ManuscriptFileTooLarge):
        await storage.write_bytes(record, "huge.bin", payload)


@pytest.mark.asyncio
async def test_per_bundle_cap(tmp_path: Path) -> None:
    """Sum of files cannot exceed the bundle cap."""
    storage = _make_storage(tmp_path, max_file_mb=1, max_bundle_mb=2)
    record = _make_bundle_record(manuscript_id="cap2")
    await storage.init_for(record)
    one_mb = b"x" * 1024 * 1024
    await storage.write_bytes(record, "a.bin", one_mb)
    await storage.write_bytes(record, "b.bin", one_mb)
    with pytest.raises(ManuscriptBundleTooLarge):
        await storage.write_bytes(record, "c.bin", b"y" * 1024)


@pytest.mark.asyncio
async def test_bundle_cap_accounts_for_overwrite(tmp_path: Path) -> None:
    """Replacing a file should not double-count its size."""
    storage = _make_storage(tmp_path, max_file_mb=1, max_bundle_mb=2)
    record = _make_bundle_record(manuscript_id="cap3")
    await storage.init_for(record)
    one_mb = b"x" * 1024 * 1024
    await storage.write_bytes(record, "a.bin", one_mb)
    await storage.write_bytes(record, "b.bin", one_mb)
    await storage.write_bytes(record, "a.bin", b"y" * 1024)
    final_total = sum(f.size for f in (await storage.list_tree(record)).files)
    assert final_total == len(one_mb) + 1024


# ---------------------------------------------------------------------------
# remove_owned
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_remove_owned_drops_copy_dir(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    record = _make_bundle_record(manuscript_id="rm")
    await storage.init_for(record)
    await storage.write_text(record, "x.md", "body")
    assert (tmp_path / "manuscripts" / "rm").exists()

    await storage.remove_owned(record)
    assert not (tmp_path / "manuscripts" / "rm").exists()


@pytest.mark.asyncio
async def test_remove_owned_noop_for_link_mode(tmp_path: Path) -> None:
    storage = _make_storage(tmp_path)
    user_dir = tmp_path / "linked"
    user_dir.mkdir()
    (user_dir / "main.tex").write_text("body")
    record = _make_bundle_record(manuscript_id="link", link_path=str(user_dir))

    await storage.remove_owned(record)
    assert (user_dir / "main.tex").exists(), "link mode must never touch user dirs"
