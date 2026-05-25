"""Pydantic DTOs for the manuscript subsystem.

Two layouts coexist:

* ``layout="single"`` — legacy mode. ``ManuscriptVersion.content`` carries the
  full document as a single markdown / text string. Backwards-compatible with
  every API that existed before P7.
* ``layout="bundle"`` — project mode. The manuscript is backed by a directory
  tree on disk (``BundleStorage``); files are first-class objects discovered
  via ``GET /tree`` and read / written via ``/files/{path:path}``. Useful for
  Overleaf-style projects with ``main.tex`` + ``sections/`` + ``figures/`` +
  ``references.bib`` etc.

Bundles support two physical placements:

* **copy** — ``bundle_link_path is None``. AAF owns the directory under
  ``settings.manuscript_root / <id> / work``. Self-contained, portable.
* **link** — ``bundle_link_path`` set to an absolute path on disk. AAF reads
  / writes that directory in place. Useful when the user already manages
  the project (git, IDE, Overleaf sync).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ManuscriptKind = Literal["paper", "section", "outline", "note"]
ManuscriptStatus = Literal["draft", "in_revision", "final", "archived"]
ManuscriptOrigin = Literal["user_upload", "write_workflow", "revision_workflow", "ingest", "api"]
ManuscriptLayout = Literal["single", "bundle"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Manuscript(BaseModel):
    """Metadata row for one tracked paper / section.

    ``current_version`` is the highest committed :class:`ManuscriptVersion.version`
    for this manuscript (0 for a just-created stub).
    """

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: str
    title: str = ""
    kind: ManuscriptKind = "section"
    status: ManuscriptStatus = "draft"
    section: str | None = None
    topic: str | None = None
    tags: list[str] = Field(default_factory=list)
    current_version: int = 0
    origin: ManuscriptOrigin = "api"
    user_id: str | None = None
    session_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    # P7 Bundle layout. Defaults preserve the pre-P7 single-file behaviour.
    layout: ManuscriptLayout = "single"
    # ``None`` for copy mode (AAF owns the dir) or single layout. Absolute
    # path string when the manuscript points at an existing directory the
    # user manages elsewhere (link mode). NEVER trust this value for path
    # operations — always go through :class:`BundleStorage`, which re-resolves
    # and validates containment.
    bundle_link_path: str | None = None
    # When True (default for bundle layout), every committed version snapshots
    # the work tree to a versioned zip on disk. Disable for link mode where the
    # user already has their own version control (git).
    bundle_versioning: bool = True


class ManuscriptVersion(BaseModel):
    """Immutable version snapshot. New edits always append a new row."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    manuscript_id: str
    version: int  # 1-based, monotonically increasing per manuscript
    content: str = ""
    note: str = ""  # commit message / change summary
    produced_by: str | None = None  # task_id for workflow-produced versions
    origin: ManuscriptOrigin = "api"
    citations: list[str] = Field(default_factory=list)
    reviewer_comments: list[dict[str, Any]] = Field(default_factory=list)
    word_count: int = 0
    created_at: datetime = Field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------


class CreateManuscriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field("", max_length=500)
    kind: ManuscriptKind = "section"
    status: ManuscriptStatus = "draft"
    section: str | None = None
    topic: str | None = None
    tags: list[str] = Field(default_factory=list)
    user_id: str | None = None
    session_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    # Optional initial content — commits version 1 in the same request
    # (single layout only — bundles use the file-tree API instead).
    content: str = ""
    note: str = ""
    citations: list[str] = Field(default_factory=list)

    # P7 — pick the layout up front. Bundles will get an empty ``work/``
    # directory provisioned in the same request (copy mode) or the link
    # path will be validated then attached (link mode).
    layout: ManuscriptLayout = "single"
    bundle_link_path: str | None = None
    bundle_versioning: bool = True


class UpdateManuscriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    status: ManuscriptStatus | None = None
    section: str | None = None
    topic: str | None = None
    tags: list[str] | None = None
    meta: dict[str, Any] | None = None
    layout: ManuscriptLayout | None = None
    bundle_link_path: str | None = None
    bundle_versioning: bool | None = None


class CommitVersionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(..., min_length=1)
    note: str = ""
    origin: ManuscriptOrigin = "api"
    produced_by: str | None = None
    citations: list[str] = Field(default_factory=list)
    reviewer_comments: list[dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Bundle layout — file-tree DTOs (P7)
# ---------------------------------------------------------------------------


class ManuscriptFile(BaseModel):
    """One file entry inside a bundled manuscript.

    Discovered by :meth:`BundleStorage.list_tree`. ``path`` is always a
    POSIX-style path **relative** to the bundle root — never absolute,
    never contains ``..`` segments. ``sha256`` is populated only when the
    caller asked for it (computing it is O(file size) per entry).
    """

    model_config = ConfigDict(extra="forbid")

    path: str  # POSIX, relative, no ".." — enforced by storage layer
    size: int  # bytes
    mime: str  # best-effort guess from extension
    is_text: bool  # decoder-friendly text vs binary
    sha256: str | None = None  # filled only when requested
    modified_at: datetime  # last mtime, UTC
    content: str | None = None  # embedded content when with_content=true


class BundleManifest(BaseModel):
    """Result envelope of ``GET /manuscripts/{id}/tree``."""

    model_config = ConfigDict(extra="forbid")

    manuscript_id: str
    layout: ManuscriptLayout
    root: str  # absolute path on the host (informational; clients shouldn't trust)
    link_mode: bool
    file_count: int
    total_size: int
    files: list[ManuscriptFile]


class WriteFileInput(BaseModel):
    """Body for ``PUT /manuscripts/{id}/files/{path:path}`` (text writes).

    Binary uploads use the multipart form variant exposed in the router.
    """

    model_config = ConfigDict(extra="forbid")

    content: str
    encoding: Literal["utf-8"] = "utf-8"


class BundleConvertInput(BaseModel):
    """Body for ``POST /manuscripts/{id}/bundle`` — promote single → bundle.

    ``link_path`` selects link mode; absent ⇒ copy mode (AAF owns the dir).
    """

    model_config = ConfigDict(extra="forbid")

    link_path: str | None = None
    versioning: bool = True


class ImportFolderInput(BaseModel):
    """Body for ``POST /manuscripts/import-folder`` — ingest an existing
    on-disk project (``/Users/.../paper-dataagent-eval`` shape) into AAF.

    ``mode="copy"`` (default) creates a self-contained bundle under the
    AAF data root. ``mode="link"`` registers the path itself — useful when
    the project is already managed elsewhere (git, Overleaf sync) and you
    want AAF to read / write it in place.
    """

    model_config = ConfigDict(extra="forbid")

    local_path: str
    mode: Literal["copy", "link"] = "copy"
    title: str = ""
    kind: ManuscriptKind = "paper"
    overwrite: bool = False
    user_id: str | None = None
    session_id: str | None = None


__all__ = [
    "BundleConvertInput",
    "BundleManifest",
    "CommitVersionInput",
    "CreateManuscriptInput",
    "ImportFolderInput",
    "Manuscript",
    "ManuscriptFile",
    "ManuscriptKind",
    "ManuscriptLayout",
    "ManuscriptOrigin",
    "ManuscriptStatus",
    "ManuscriptVersion",
    "UpdateManuscriptInput",
    "WriteFileInput",
]
