"""Filesystem layer for bundled manuscripts (P7).

`BundleStorage` is the **only** module allowed to touch the work directory of
a bundled manuscript. Everything goes through it so we have one place to
enforce:

* **Path containment** — every relative path is resolved + checked
  ``is_relative_to(physical_root)``. ``..`` segments and absolute paths are
  rejected before any I/O happens. We use ``Path.resolve(strict=False)``
  so we can validate not-yet-existing parents during a write.
* **Size caps** — per-file (default 50 MB) + per-bundle (default 500 MB)
  via :class:`backend.settings.Settings`. Both are configurable.
* **Ignore patterns** — common transient junk (``.git`` internals,
  ``__pycache__``, ``.DS_Store``, ``node_modules``) is hidden from listings
  by default to keep the UI clean. Files are still readable if requested
  by exact path; only listings filter.
* **Atomic writes** — write to ``<path>.tmp.<pid>`` then ``os.replace``. No
  half-written file ever shadows a real one.
* **Layout enforcement** — every method takes a ``Manuscript`` so it can
  refuse single-layout calls and pick the right physical root for copy vs
  link mode.

Two physical placements per bundle:

* **copy**  — ``manuscript.bundle_link_path is None``. Root is
  ``settings_root / <id> / work``. AAF owns it; safe to wipe.
* **link**  — ``bundle_link_path`` is an absolute path on the host. AAF
  reads / writes that directory in place. We still validate containment
  against the link root (so ``../`` escapes are still impossible).

Versioning (zip snapshots) lives in Phase B. This module is purely about
the work tree.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import mimetypes
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import structlog

from backend.core.errors import (
    ManuscriptBundleTooLarge,
    ManuscriptFileTooLarge,
    ManuscriptIOError,
    ManuscriptLayoutMismatch,
    ManuscriptPathInvalid,
)

from .models import BundleManifest, Manuscript, ManuscriptFile

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Heuristics — kept module-level so callers can introspect / extend
# ---------------------------------------------------------------------------

#: Ignored from ``list_tree`` output (still readable / writable by exact path).
DEFAULT_IGNORE_DIRS = frozenset(
    {".git", ".svn", ".hg", "__pycache__", "node_modules", ".venv", ".idea", ".vscode"}
)
DEFAULT_IGNORE_FILES = frozenset({".DS_Store", "Thumbs.db"})

#: Extensions / mime prefixes treated as text for the API's "preview vs
#: download" decision. Conservative — anything not matching is binary unless
#: caller explicitly opts in.
TEXT_EXTENSIONS = frozenset(
    {
        ".md",
        ".markdown",
        ".txt",
        ".rst",
        ".tex",
        ".bib",
        ".sty",
        ".cls",
        ".bst",
        ".cfg",
        ".ini",
        ".toml",
        ".yaml",
        ".yml",
        ".json",
        ".xml",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".py",
        ".sh",
        ".bat",
        ".env",
        ".gitignore",
        ".gitattributes",
    }
)

#: Bytes streamed per chunk during binary reads. 64 KiB matches typical
#: filesystem page sizes and starlette's default streaming chunk.
STREAM_CHUNK_BYTES = 64 * 1024


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------


class BundleStorage:
    """Filesystem-backed store for one or more manuscript bundles.

    Construct once at startup with the configured root + caps; pass into
    routers via ``AppState.bundle_storage``. Methods are all async (using
    ``asyncio.to_thread`` for the actual filesystem syscalls — they're
    fast but blocking, and we want the event loop free).
    """

    def __init__(
        self,
        *,
        root: Path,
        max_file_bytes: int,
        max_bundle_bytes: int,
        ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
        ignore_files: frozenset[str] = DEFAULT_IGNORE_FILES,
    ) -> None:
        self._root = root.resolve()
        self._max_file_bytes = max_file_bytes
        self._max_bundle_bytes = max_bundle_bytes
        self._ignore_dirs = ignore_dirs
        self._ignore_files = ignore_files

    # ---- meta / paths ------------------------------------------------

    @property
    def root(self) -> Path:
        """Configured bundle root (copy mode default home for new bundles)."""
        return self._root

    @property
    def max_file_bytes(self) -> int:
        return self._max_file_bytes

    @property
    def max_bundle_bytes(self) -> int:
        return self._max_bundle_bytes

    def physical_root(self, manuscript: Manuscript) -> Path:
        """Resolve the on-disk root directory for a manuscript.

        Raises :class:`ManuscriptLayoutMismatch` for single-layout manuscripts.
        """
        if manuscript.layout != "bundle":
            raise ManuscriptLayoutMismatch(
                "manuscript is not a bundle",
                manuscript_id=manuscript.id,
                layout=manuscript.layout,
            )
        if manuscript.bundle_link_path:
            return Path(manuscript.bundle_link_path).resolve()
        return (self._root / manuscript.id / "work").resolve()

    def is_link_mode(self, manuscript: Manuscript) -> bool:
        return manuscript.layout == "bundle" and manuscript.bundle_link_path is not None

    # ---- lifecycle ---------------------------------------------------

    async def init_for(self, manuscript: Manuscript) -> Path:
        """Ensure the physical root exists; return its absolute path.

        Idempotent — safe to call on every request. For link mode we just
        validate the path exists and is a directory; we never ``mkdir`` on
        a user-provided link path because that would silently materialise
        a wrong path.
        """
        root = self.physical_root(manuscript)
        if self.is_link_mode(manuscript):
            if not root.exists() or not root.is_dir():
                raise ManuscriptPathInvalid(
                    "bundle link path does not exist or is not a directory",
                    manuscript_id=manuscript.id,
                    path=str(root),
                )
            return root

        def _mk() -> None:
            root.mkdir(parents=True, exist_ok=True)

        await asyncio.to_thread(_mk)
        return root

    async def remove_owned(self, manuscript: Manuscript) -> None:
        """Recursively delete the AAF-owned directory for a manuscript.

        No-op for link mode — we never touch the user's directory. Used by
        the manuscript ``DELETE`` endpoint to free disk space.
        """
        if manuscript.layout != "bundle":
            return
        if self.is_link_mode(manuscript):
            return
        owned = (self._root / manuscript.id).resolve()
        if not owned.exists():
            return

        def _rm() -> None:
            shutil.rmtree(owned, ignore_errors=False)

        try:
            await asyncio.to_thread(_rm)
        except OSError as exc:
            log.exception("manuscript.bundle.remove_failed", manuscript_id=manuscript.id)
            raise ManuscriptIOError(
                "failed to remove bundle directory", manuscript_id=manuscript.id
            ) from exc
        log.info("manuscript.bundle.removed", manuscript_id=manuscript.id, path=str(owned))

    # ---- safe path resolution ---------------------------------------

    def _safe_resolve(self, manuscript: Manuscript, rel_path: str) -> Path:
        """Resolve ``rel_path`` under the manuscript's root.

        Rejects empty paths, absolute paths, ``..`` segments after
        normalisation, and anything that escapes the physical root via a
        symlink target. Returns the absolute resolved path (which may not
        yet exist — for write operations).
        """
        if not rel_path or rel_path.strip() == "":
            raise ManuscriptPathInvalid("empty path", manuscript_id=manuscript.id, path=rel_path)
        # Reject absolute / drive-letter inputs BEFORE normalising — otherwise
        # ``/foo`` would be quietly downgraded to ``foo`` by lstrip and look
        # safe to the rest of the function.
        normalised = rel_path.replace("\\", "/")
        if normalised.startswith("/") or Path(normalised).is_absolute():
            raise ManuscriptPathInvalid(
                "absolute paths not allowed",
                manuscript_id=manuscript.id,
                path=rel_path,
            )
        cleaned = normalised.lstrip("/")
        if not cleaned:
            raise ManuscriptPathInvalid(
                "path is empty after normalisation",
                manuscript_id=manuscript.id,
                path=rel_path,
            )
        # ``Path`` collapses ``foo/./bar`` but NOT ``..`` — inspect explicit
        # parts and reject any parent reference before resolving (``resolve``
        # would silently follow symlinks, which is the wrong default here).
        parts = Path(cleaned).parts
        if any(p == ".." for p in parts):
            raise ManuscriptPathInvalid(
                "path contains '..' segment",
                manuscript_id=manuscript.id,
                path=rel_path,
            )
        root = self.physical_root(manuscript)
        candidate = (root / cleaned).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            # Symlink chased outside root.
            raise ManuscriptPathInvalid(
                "resolved path escapes bundle root",
                manuscript_id=manuscript.id,
                path=rel_path,
                resolved=str(candidate),
            ) from exc
        return candidate

    # ---- listing / metadata -----------------------------------------

    async def list_tree(
        self,
        manuscript: Manuscript,
        *,
        include_hash: bool = False,
        include_hidden: bool = False,
    ) -> BundleManifest:
        """Walk the bundle root and return a flat manifest of files.

        ``include_hash=True`` computes SHA-256 per file (slow for big
        bundles — opt-in). ``include_hidden=True`` keeps dotfiles + the
        default ignore set; otherwise we hide ``.git`` etc. for the UI.
        """
        root = await self.init_for(manuscript)

        def _walk() -> tuple[list[ManuscriptFile], int]:
            files: list[ManuscriptFile] = []
            total = 0
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                if not include_hidden:
                    dirnames[:] = [
                        d for d in dirnames if d not in self._ignore_dirs and not d.startswith(".")
                    ]
                for name in filenames:
                    if not include_hidden:
                        if name in self._ignore_files or name.startswith("."):
                            continue
                    abs_path = Path(dirpath) / name
                    try:
                        st = abs_path.stat()
                    except OSError:
                        # raced with deletion or permission glitch — skip
                        continue
                    rel = abs_path.relative_to(root).as_posix()
                    mime = _guess_mime(abs_path)
                    is_text = _looks_textual(abs_path, mime)
                    sha: str | None = None
                    if include_hash:
                        sha = _sha256_file(abs_path)
                    files.append(
                        ManuscriptFile(
                            path=rel,
                            size=int(st.st_size),
                            mime=mime,
                            is_text=is_text,
                            sha256=sha,
                            modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
                        )
                    )
                    total += int(st.st_size)
            files.sort(key=lambda f: f.path)
            return files, total

        files, total = await asyncio.to_thread(_walk)
        return BundleManifest(
            manuscript_id=manuscript.id,
            layout="bundle",
            root=str(root),
            link_mode=self.is_link_mode(manuscript),
            file_count=len(files),
            total_size=total,
            files=files,
        )

    async def stat(self, manuscript: Manuscript, rel_path: str) -> ManuscriptFile:
        """Return metadata for one file. Raises ``ManuscriptPathInvalid`` for
        invalid paths and :class:`FileNotFoundError` if the file is absent."""
        target = self._safe_resolve(manuscript, rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(rel_path)
        st = await asyncio.to_thread(target.stat)
        mime = _guess_mime(target)
        return ManuscriptFile(
            path=Path(rel_path).as_posix().lstrip("/"),
            size=int(st.st_size),
            mime=mime,
            is_text=_looks_textual(target, mime),
            sha256=None,
            modified_at=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        )

    # ---- read --------------------------------------------------------

    async def read_bytes(self, manuscript: Manuscript, rel_path: str) -> bytes:
        target = self._safe_resolve(manuscript, rel_path)
        if not target.exists() or not target.is_file():
            raise FileNotFoundError(rel_path)
        return await asyncio.to_thread(target.read_bytes)

    async def read_text(
        self, manuscript: Manuscript, rel_path: str, encoding: str = "utf-8"
    ) -> str:
        raw = await self.read_bytes(manuscript, rel_path)
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ManuscriptPathInvalid(
                "file is not valid utf-8 (use binary read)",
                manuscript_id=manuscript.id,
                path=rel_path,
            ) from exc

    # ---- write -------------------------------------------------------

    async def write_bytes(
        self, manuscript: Manuscript, rel_path: str, data: bytes
    ) -> ManuscriptFile:
        if len(data) > self._max_file_bytes:
            raise ManuscriptFileTooLarge(
                "file exceeds per-file size cap",
                manuscript_id=manuscript.id,
                path=rel_path,
                size=len(data),
                cap=self._max_file_bytes,
            )
        target = self._safe_resolve(manuscript, rel_path)
        # Estimate post-write bundle size: subtract existing-file size if any.
        existing = target.stat().st_size if target.exists() and target.is_file() else 0
        current_total = await self._bundle_size(manuscript)
        projected = current_total - existing + len(data)
        if projected > self._max_bundle_bytes:
            raise ManuscriptBundleTooLarge(
                "write would exceed per-bundle size cap",
                manuscript_id=manuscript.id,
                path=rel_path,
                projected=projected,
                cap=self._max_bundle_bytes,
            )

        def _atomic_write() -> None:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(f"{target.name}.tmp.{os.getpid()}")
            tmp.write_bytes(data)
            os.replace(tmp, target)

        try:
            await asyncio.to_thread(_atomic_write)
        except OSError as exc:
            log.exception(
                "manuscript.bundle.write_failed",
                manuscript_id=manuscript.id,
                path=rel_path,
            )
            raise ManuscriptIOError(
                "failed to write file", manuscript_id=manuscript.id, path=rel_path
            ) from exc
        log.info(
            "manuscript.bundle.write",
            manuscript_id=manuscript.id,
            path=rel_path,
            bytes=len(data),
        )
        return await self.stat(manuscript, rel_path)

    async def write_text(
        self,
        manuscript: Manuscript,
        rel_path: str,
        text: str,
        encoding: str = "utf-8",
    ) -> ManuscriptFile:
        return await self.write_bytes(manuscript, rel_path, text.encode(encoding))

    async def delete_path(self, manuscript: Manuscript, rel_path: str) -> bool:
        target = self._safe_resolve(manuscript, rel_path)
        if not target.exists():
            return False

        def _rm() -> None:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

        try:
            await asyncio.to_thread(_rm)
        except OSError as exc:
            log.exception(
                "manuscript.bundle.delete_failed",
                manuscript_id=manuscript.id,
                path=rel_path,
            )
            raise ManuscriptIOError(
                "failed to delete path", manuscript_id=manuscript.id, path=rel_path
            ) from exc
        log.info("manuscript.bundle.delete", manuscript_id=manuscript.id, path=rel_path)
        return True

    # ---- import / export --------------------------------------------

    async def import_directory(
        self,
        manuscript: Manuscript,
        source: Path,
        *,
        overwrite: bool = False,
    ) -> int:
        """Recursively copy ``source`` into the bundle work tree.

        Skips the ignore set (``.git``, ``__pycache__``, ``.DS_Store``, …)
        and enforces both per-file + per-bundle caps mid-stream so a hostile
        directory can't fill the disk before the size check runs.

        ``overwrite=False`` (default) refuses to copy a file when one already
        exists at the same relative path; use ``True`` for re-imports.

        Returns the number of files copied. Refuses link-mode bundles —
        they already are the user's directory.
        """
        if self.is_link_mode(manuscript):
            raise ManuscriptPathInvalid(
                "import-folder is meaningless in link mode (manuscript already points here)",
                manuscript_id=manuscript.id,
                path=str(source),
            )

        def _resolve_and_check(p: Path) -> Path:
            resolved = p.expanduser().resolve()
            if not resolved.exists() or not resolved.is_dir():
                raise ManuscriptPathInvalid(
                    "source directory does not exist or is not a directory",
                    manuscript_id=manuscript.id,
                    path=str(resolved),
                )
            return resolved

        source = await asyncio.to_thread(_resolve_and_check, source)
        root = await self.init_for(manuscript)

        def _copy() -> int:
            current_total = 0
            for dp, _dn, fn in os.walk(root, followlinks=False):
                for n in fn:
                    try:
                        current_total += (Path(dp) / n).stat().st_size
                    except OSError:
                        continue
            count = 0
            for dirpath, dirnames, filenames in os.walk(source, followlinks=False):
                # Prune ignored subtrees in-place to skip recursion.
                dirnames[:] = [d for d in dirnames if d not in self._ignore_dirs]
                for name in filenames:
                    if name in self._ignore_files:
                        continue
                    src = Path(dirpath) / name
                    try:
                        size = src.stat().st_size
                    except OSError:
                        continue
                    if size > self._max_file_bytes:
                        raise ManuscriptFileTooLarge(
                            "file exceeds per-file size cap",
                            manuscript_id=manuscript.id,
                            path=str(src),
                            size=size,
                            cap=self._max_file_bytes,
                        )
                    rel = src.relative_to(source)
                    dest = root / rel
                    existing = dest.stat().st_size if dest.exists() and dest.is_file() else 0
                    if dest.exists() and not overwrite:
                        raise ManuscriptPathInvalid(
                            "destination already exists; pass overwrite=true to replace",
                            manuscript_id=manuscript.id,
                            path=str(rel),
                        )
                    projected = current_total - existing + size
                    if projected > self._max_bundle_bytes:
                        raise ManuscriptBundleTooLarge(
                            "import would exceed per-bundle size cap",
                            manuscript_id=manuscript.id,
                            projected=projected,
                            cap=self._max_bundle_bytes,
                        )
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dest)
                    current_total = projected
                    count += 1
            return count

        try:
            count = await asyncio.to_thread(_copy)
        except (
            ManuscriptFileTooLarge,
            ManuscriptBundleTooLarge,
            ManuscriptPathInvalid,
        ):
            raise
        except OSError as exc:
            log.exception(
                "manuscript.bundle.import_failed",
                manuscript_id=manuscript.id,
                source=str(source),
            )
            raise ManuscriptIOError(
                "import failed",
                manuscript_id=manuscript.id,
                source=str(source),
            ) from exc
        log.info(
            "manuscript.bundle.imported",
            manuscript_id=manuscript.id,
            source=str(source),
            files=count,
        )
        return count

    async def import_zip(
        self,
        manuscript: Manuscript,
        zip_bytes: bytes,
        *,
        overwrite: bool = False,
    ) -> int:
        """Extract a zip archive into the work tree.

        Enforces zip-slip defence (every entry is path-validated against the
        bundle root before extraction), the per-file cap, and the per-bundle
        cap (running sum of uncompressed sizes). Symlink entries are skipped
        — we never let a zip place a symlink inside the bundle.
        """
        if self.is_link_mode(manuscript):
            raise ManuscriptPathInvalid(
                "import-zip is meaningless in link mode",
                manuscript_id=manuscript.id,
                path="",
            )
        root = await self.init_for(manuscript)
        try:
            zf = zipfile.ZipFile(io.BytesIO(zip_bytes))
        except zipfile.BadZipFile as exc:
            raise ManuscriptPathInvalid(
                "invalid zip archive", manuscript_id=manuscript.id, path=""
            ) from exc

        def _extract() -> int:
            current_total = 0
            for dp, _dn, fn in os.walk(root, followlinks=False):
                for n in fn:
                    try:
                        current_total += (Path(dp) / n).stat().st_size
                    except OSError:
                        continue

            count = 0
            for info in zf.infolist():
                # Skip directory entries — they materialise via parents below.
                if info.is_dir():
                    continue
                name = info.filename
                # Symlinks have a Unix mode bit set in external_attr; refuse them.
                # zip stores Unix mode in the high 16 bits of external_attr.
                unix_mode = (info.external_attr >> 16) & 0o170000
                if unix_mode == 0o120000:
                    log.warning(
                        "manuscript.bundle.zip_skip_symlink",
                        manuscript_id=manuscript.id,
                        name=name,
                    )
                    continue
                if Path(name).is_absolute() or name.startswith("/") or ".." in Path(name).parts:
                    raise ManuscriptPathInvalid(
                        "zip entry escapes bundle root (zip-slip)",
                        manuscript_id=manuscript.id,
                        path=name,
                    )
                if info.file_size > self._max_file_bytes:
                    raise ManuscriptFileTooLarge(
                        "zip entry exceeds per-file size cap",
                        manuscript_id=manuscript.id,
                        path=name,
                        size=info.file_size,
                        cap=self._max_file_bytes,
                    )
                dest = (root / name).resolve()
                try:
                    dest.relative_to(root)
                except ValueError as exc:
                    raise ManuscriptPathInvalid(
                        "resolved zip entry escapes bundle root",
                        manuscript_id=manuscript.id,
                        path=name,
                    ) from exc
                existing = dest.stat().st_size if dest.exists() and dest.is_file() else 0
                if dest.exists() and not overwrite:
                    raise ManuscriptPathInvalid(
                        "destination already exists; pass overwrite=true to replace",
                        manuscript_id=manuscript.id,
                        path=name,
                    )
                projected = current_total - existing + info.file_size
                if projected > self._max_bundle_bytes:
                    raise ManuscriptBundleTooLarge(
                        "zip would exceed per-bundle size cap",
                        manuscript_id=manuscript.id,
                        projected=projected,
                        cap=self._max_bundle_bytes,
                    )
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info, "r") as src, dest.open("wb") as out:
                    shutil.copyfileobj(src, out, STREAM_CHUNK_BYTES)
                current_total = projected
                count += 1
            return count

        try:
            count = await asyncio.to_thread(_extract)
        except (
            ManuscriptFileTooLarge,
            ManuscriptBundleTooLarge,
            ManuscriptPathInvalid,
        ):
            raise
        except OSError as exc:
            log.exception("manuscript.bundle.unzip_failed", manuscript_id=manuscript.id)
            raise ManuscriptIOError("zip extraction failed", manuscript_id=manuscript.id) from exc
        log.info(
            "manuscript.bundle.zip_imported",
            manuscript_id=manuscript.id,
            files=count,
        )
        return count

    def export_zip(
        self,
        manuscript: Manuscript,
        *,
        subdir: str | None = None,
        include_hidden: bool = False,
    ) -> bytes:
        """Pack the bundle (or one subdirectory) into a zip and return bytes.

        ``subdir`` is interpreted relative to the bundle root and validated
        with the same containment rules as file ops. ``None`` ⇒ pack the
        whole bundle. Useful for the Overleaf workflow:
        ``subdir="overleaf"`` ⇒ a zip you can drag into Overleaf directly.

        Synchronous on purpose — caller wraps in :func:`asyncio.to_thread`.
        Avoids holding everything in memory at once by writing each entry
        through ``zipfile``'s streaming interface, but the final bytes are
        returned as one buffer (acceptable for the laptop-scale bundles
        AAF targets; see ``manuscript_max_bundle_mb``).
        """
        root = self.physical_root(manuscript)
        target_root = root if subdir is None else self._safe_resolve(manuscript, subdir)
        if not target_root.exists() or not target_root.is_dir():
            raise ManuscriptPathInvalid(
                "export subdir does not exist or is not a directory",
                manuscript_id=manuscript.id,
                path=subdir or "",
            )

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, dirnames, filenames in os.walk(target_root, followlinks=False):
                if not include_hidden:
                    dirnames[:] = [
                        d for d in dirnames if d not in self._ignore_dirs and not d.startswith(".")
                    ]
                for name in filenames:
                    if not include_hidden:
                        if name in self._ignore_files or name.startswith("."):
                            continue
                    abs_path = Path(dirpath) / name
                    arcname = abs_path.relative_to(target_root).as_posix()
                    zf.write(abs_path, arcname=arcname)
        return buf.getvalue()

    def detect_overleaf_subdir(self, manuscript: Manuscript) -> str | None:
        """Heuristic: if ``overleaf/`` exists at bundle root, return its name;
        otherwise None (caller falls back to packing the whole bundle).

        Matches the convention in your ``paper-dataagent-eval`` layout.
        """
        try:
            root = self.physical_root(manuscript)
        except ManuscriptLayoutMismatch:
            return None
        candidate = root / "overleaf"
        return "overleaf" if candidate.is_dir() else None

    # ---- internal ----------------------------------------------------

    async def _bundle_size(self, manuscript: Manuscript) -> int:
        root = await self.init_for(manuscript)

        def _sum() -> int:
            total = 0
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    p = Path(dirpath) / name
                    try:
                        total += p.stat().st_size
                    except OSError:
                        continue
            return total

        return await asyncio.to_thread(_sum)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    if mime:
        return mime
    # `.tex` etc. fall through `mimetypes` — give a sensible textual default
    # so the UI knows it can preview them.
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return "text/plain"
    return "application/octet-stream"


def _looks_textual(path: Path, mime: str) -> bool:
    if mime.startswith("text/"):
        return True
    if mime in {
        "application/json",
        "application/xml",
        "application/yaml",
        "application/x-yaml",
        "application/toml",
        "application/javascript",
    }:
        return True
    return path.suffix.lower() in TEXT_EXTENSIONS


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(STREAM_CHUNK_BYTES)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


__all__ = [
    "DEFAULT_IGNORE_DIRS",
    "DEFAULT_IGNORE_FILES",
    "STREAM_CHUNK_BYTES",
    "TEXT_EXTENSIONS",
    "BundleStorage",
]
