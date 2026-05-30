"""Workflow-facing facade over :class:`BundleStorage`.

`BundleStorage` (in `backend/manuscripts/bundle_storage.py`) is the
"raw" filesystem layer that takes a `Manuscript` plus a relative path
on every call. Inside a workflow we already know which manuscript is in
play (the runner resolved it from `record.input["manuscript_id"]`) and
we want a one-method-call API that doesn't require reaching back into
the store.

`BundleAdapter` does exactly that: it pre-binds a `Manuscript` and
forwards a curated subset of the storage methods. Anything that mutates
the manuscript record itself (rename, layout change, delete) stays on
the HTTP / store path; the adapter is for *content* operations.

Construction always goes through :func:`BundleAdapter.maybe_build`,
which returns `None` for a single-layout manuscript (no bundle to wrap)
or when the runner has no `BundleStorage` wired. Workflows therefore
just guard with::

    if ctx.bundle is None:
        ...  # single-layout / pre-P7 path
    else:
        text = await ctx.bundle.read_text(...)

— matching the rest of AAF's optional-dependency pattern (`ctx.llm`,
`ctx.memory`, `ctx.tools` are all `Any | None`).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.manuscripts.bundle_storage import BundleStorage
    from backend.manuscripts.models import BundleManifest, Manuscript, ManuscriptFile
    from backend.manuscripts.store import ManuscriptStore


@dataclass(frozen=True)
class BundleAdapter:
    """Manuscript-bound, workflow-facing wrapper over `BundleStorage`.

    Frozen on purpose: the bound manuscript is per-task and must not
    drift mid-run (otherwise auto-rollback / event correlation breaks).
    """

    manuscript: Manuscript
    storage: BundleStorage

    # ---- read helpers ------------------------------------------------

    async def read_text(self, rel_path: str, *, encoding: str = "utf-8") -> str:
        """Read a UTF-8 text file under the bundle root.

        Raises :class:`backend.core.errors.ManuscriptPathInvalid` for
        unsafe paths and :class:`FileNotFoundError` for missing files —
        both passed through from the underlying storage so the workflow
        can decide whether to translate them into a soft `WorkflowOutput`
        error or surface as a task crash.
        """
        return await self.storage.read_text(self.manuscript, rel_path, encoding=encoding)

    async def read_bytes(self, rel_path: str) -> bytes:
        return await self.storage.read_bytes(self.manuscript, rel_path)

    async def list_tree(
        self,
        *,
        include_hash: bool = False,
        include_hidden: bool = False,
    ) -> BundleManifest:
        """Flat listing of every file under the bundle root."""
        return await self.storage.list_tree(
            self.manuscript,
            include_hash=include_hash,
            include_hidden=include_hidden,
        )

    async def stat(self, rel_path: str) -> ManuscriptFile:
        return await self.storage.stat(self.manuscript, rel_path)

    # ---- write helpers ----------------------------------------------

    async def write_text(
        self,
        rel_path: str,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> ManuscriptFile:
        """Write a UTF-8 text file. Atomic + size-cap-checked by the storage layer."""
        return await self.storage.write_text(self.manuscript, rel_path, text, encoding=encoding)

    async def write_bytes(self, rel_path: str, data: bytes) -> ManuscriptFile:
        return await self.storage.write_bytes(self.manuscript, rel_path, data)

    # ---- introspection ----------------------------------------------

    def detect_overleaf_subdir(self) -> str | None:
        """Heuristic: returns ``"overleaf"`` if the bundle root contains an
        ``overleaf/`` directory (matches the user's existing
        `paper-dataagent-eval` convention), else ``None``.
        """
        return self.storage.detect_overleaf_subdir(self.manuscript)

    def physical_root(self) -> Path:
        """Absolute on-disk path of the bundle root.

        Workflows should *not* read or write through this path directly —
        always go through `read_text` / `write_text` so the path-safety
        and size-cap checks run. This accessor is here for telemetry +
        log lines only.
        """
        return self.storage.physical_root(self.manuscript)

    # ---- factory -----------------------------------------------------

    @classmethod
    async def maybe_build(
        cls,
        *,
        manuscript_id: str | None,
        manuscripts: ManuscriptStore | None,
        storage: BundleStorage | None,
    ) -> BundleAdapter | None:
        """Best-effort constructor used by the task runner.

        Returns ``None`` (and never raises) when:

        * ``manuscript_id`` is missing / empty
        * either dependency (``manuscripts`` or ``storage``) is missing
        * the manuscript record can't be loaded
        * the manuscript is single-layout (no bundle to wrap)

        In every "no bundle" case the workflow's `ctx.bundle` ends up
        ``None``, which is exactly what the existing single-doc workflow
        code already expects. This keeps the adapter strictly additive.
        """
        if not manuscript_id or manuscripts is None or storage is None:
            return None
        try:
            manuscript = await manuscripts.get(manuscript_id)
        except Exception:
            return None
        if manuscript is None or manuscript.layout != "bundle":
            return None
        return cls(manuscript=manuscript, storage=storage)


__all__ = ["BundleAdapter"]
