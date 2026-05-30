"""Manuscript subsystem — first-class versioned storage for user papers.

The Write and Revision workflows produce markdown; the user uploads
drafts. Both sides land here. A :class:`Manuscript` is a metadata row
(title, kind, status, tags, current version), a :class:`ManuscriptVersion`
is one immutable snapshot of the text. Together they form an append-only
document history per paper.

See PLAN §14.
"""

from __future__ import annotations

from .bundle_storage import BundleStorage
from .models import (
    BundleConvertInput,
    BundleManifest,
    CommitVersionInput,
    CreateManuscriptInput,
    ImportFolderInput,
    Manuscript,
    ManuscriptFile,
    ManuscriptKind,
    ManuscriptLayout,
    ManuscriptStatus,
    ManuscriptVersion,
    UpdateManuscriptInput,
    WriteFileInput,
)
from .store import InMemoryManuscriptStore, ManuscriptStore

__all__ = [
    "BundleConvertInput",
    "BundleManifest",
    "BundleStorage",
    "CommitVersionInput",
    "CreateManuscriptInput",
    "ImportFolderInput",
    "InMemoryManuscriptStore",
    "Manuscript",
    "ManuscriptFile",
    "ManuscriptKind",
    "ManuscriptLayout",
    "ManuscriptStatus",
    "ManuscriptStore",
    "ManuscriptVersion",
    "UpdateManuscriptInput",
    "WriteFileInput",
]
