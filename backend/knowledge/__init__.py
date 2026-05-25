"""Knowledge subsystem — paper ingest pipeline (PLAN §20.8 M7.1).

The HTTP surface for knowledge cards lives in
:mod:`backend.api.routers.knowledge`; this package owns the *logic* of
turning raw uploads (PDF / markdown / metadata) into structured
:class:`PaperCard`s and triggering memory evolution.
"""

from __future__ import annotations

from .extractor import ExtractedPaper, PaperExtractor
from .ingest import IngestInput, IngestResult, PaperIngestor

__all__ = [
    "ExtractedPaper",
    "IngestInput",
    "IngestResult",
    "PaperExtractor",
    "PaperIngestor",
]
