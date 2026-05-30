"""Unit tests for :class:`backend.workflows.bundle_adapter.BundleAdapter`.

The adapter is intentionally thin — its real value is the *contract*:

* `maybe_build` returns ``None`` for every shape that should fall back
  to the legacy single-doc path (missing manuscript_id, missing deps,
  missing manuscript record, single layout).
* When it does build, the bound methods round-trip through the
  underlying :class:`BundleStorage` and respect its security + size
  guarantees (the storage's own tests cover those in depth — here we
  just verify the adapter doesn't bypass them).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.manuscripts.bundle_storage import BundleStorage
from backend.manuscripts.models import CreateManuscriptInput, Manuscript
from backend.manuscripts.store import InMemoryManuscriptStore
from backend.workflows.bundle_adapter import BundleAdapter


def _storage(tmp_path: Path) -> BundleStorage:
    return BundleStorage(
        root=tmp_path / "manuscripts",
        max_file_bytes=1 * 1024 * 1024,
        max_bundle_bytes=4 * 1024 * 1024,
    )


async def _bundle_record(
    store: InMemoryManuscriptStore,
    *,
    title: str = "P",
    link_path: str | None = None,
) -> Manuscript:
    record, _ = await store.create(
        CreateManuscriptInput(
            title=title,
            layout="bundle",
            bundle_link_path=link_path,
        )
    )
    return record


# ---------------------------------------------------------------------------
# maybe_build — every "fall back to single" path returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_build_returns_none_when_manuscript_id_missing(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)

    assert (
        await BundleAdapter.maybe_build(
            manuscript_id=None,
            manuscripts=store,
            storage=storage,
        )
        is None
    )
    assert (
        await BundleAdapter.maybe_build(
            manuscript_id="",
            manuscripts=store,
            storage=storage,
        )
        is None
    )


@pytest.mark.asyncio
async def test_maybe_build_returns_none_when_dependencies_missing(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    assert (
        await BundleAdapter.maybe_build(
            manuscript_id="ms-1",
            manuscripts=None,
            storage=storage,
        )
        is None
    )

    store = InMemoryManuscriptStore()
    record = await _bundle_record(store)
    assert (
        await BundleAdapter.maybe_build(
            manuscript_id=record.id,
            manuscripts=store,
            storage=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_maybe_build_returns_none_for_unknown_manuscript(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    assert (
        await BundleAdapter.maybe_build(
            manuscript_id="ms-does-not-exist",
            manuscripts=store,
            storage=storage,
        )
        is None
    )


@pytest.mark.asyncio
async def test_maybe_build_returns_none_for_single_layout_manuscript(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    record, _ = await store.create(
        CreateManuscriptInput(title="single doc", layout="single", content="# body")
    )
    adapter = await BundleAdapter.maybe_build(
        manuscript_id=record.id,
        manuscripts=store,
        storage=storage,
    )
    assert adapter is None


# ---------------------------------------------------------------------------
# maybe_build — happy path binds storage + manuscript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_maybe_build_returns_adapter_for_bundle(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    record = await _bundle_record(store, title="paper-eval")

    adapter = await BundleAdapter.maybe_build(
        manuscript_id=record.id,
        manuscripts=store,
        storage=storage,
    )
    assert adapter is not None
    assert adapter.manuscript.id == record.id
    assert adapter.storage is storage
    # frozen dataclass — defensive against accidental mutation mid-task.
    with pytest.raises(AttributeError):
        adapter.manuscript = record  # type: ignore[misc]


# ---------------------------------------------------------------------------
# read / write round-trip via the adapter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_then_read_round_trip(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    record = await _bundle_record(store)
    adapter = await BundleAdapter.maybe_build(
        manuscript_id=record.id,
        manuscripts=store,
        storage=storage,
    )
    assert adapter is not None

    meta = await adapter.write_text("overleaf/sections/intro.tex", "Hello body.")
    assert meta.path == "overleaf/sections/intro.tex"
    assert meta.size == len(b"Hello body.")

    text = await adapter.read_text("overleaf/sections/intro.tex")
    assert text == "Hello body."

    manifest = await adapter.list_tree()
    paths = {f.path for f in manifest.files}
    assert "overleaf/sections/intro.tex" in paths


@pytest.mark.asyncio
async def test_overleaf_subdir_detection(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    record = await _bundle_record(store)
    adapter = await BundleAdapter.maybe_build(
        manuscript_id=record.id,
        manuscripts=store,
        storage=storage,
    )
    assert adapter is not None
    assert adapter.detect_overleaf_subdir() is None

    await adapter.write_text("overleaf/main.tex", "\\documentclass{article}")
    assert adapter.detect_overleaf_subdir() == "overleaf"


@pytest.mark.asyncio
async def test_adapter_does_not_bypass_storage_path_safety(tmp_path: Path) -> None:
    """Writing through the adapter still triggers `_safe_resolve`."""
    from backend.core.errors import ManuscriptPathInvalid

    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    record = await _bundle_record(store)
    adapter = await BundleAdapter.maybe_build(
        manuscript_id=record.id,
        manuscripts=store,
        storage=storage,
    )
    assert adapter is not None

    with pytest.raises(ManuscriptPathInvalid):
        await adapter.write_text("../../escape.txt", "pwn")


# ---------------------------------------------------------------------------
# physical_root surfaces the real on-disk path (used for log lines / events)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_physical_root_returns_resolved_dir(tmp_path: Path) -> None:
    store = InMemoryManuscriptStore()
    storage = _storage(tmp_path)
    record = await _bundle_record(store)
    adapter = await BundleAdapter.maybe_build(
        manuscript_id=record.id,
        manuscripts=store,
        storage=storage,
    )
    assert adapter is not None

    await adapter.write_text("placeholder.txt", "")
    root = adapter.physical_root()
    assert root.is_dir()
    assert root.resolve() == (tmp_path / "manuscripts" / record.id / "work").resolve()
