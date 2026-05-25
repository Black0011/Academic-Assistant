"""Pure-Python PDF → markdown extractor.

Used by both the manuscripts upload route (preserves the raw body for
versioning) and the M7.1 paper-ingest pipeline (feeds extracted text into
the :class:`PaperExtractor`). Kept deliberately simple — pages joined by
``## Page N`` headings — so the manuscripts behaviour stays byte-exact
after the extraction.

Network access is **not** part of this module. Callers fetch bytes
themselves; we accept ``bytes`` only.
"""

from __future__ import annotations

import io
from typing import Any

import structlog

log = structlog.get_logger(__name__)


def pdf_to_markdown(raw: bytes, *, max_pages: int = 200) -> tuple[str, dict[str, Any]]:
    """Extract text from a PDF into a markdown-ish string.

    Returns ``(body, meta)``. ``meta`` always carries ``pdf_num_pages``
    (total pages in the document) and ``pdf_pages_extracted`` (how many
    actually yielded text). When ``raw`` is empty or pypdf cannot parse
    a page, that page contributes the empty string.
    """
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    total = len(reader.pages)
    limit = min(max_pages, total)
    chunks: list[str] = []
    for idx in range(limit):
        try:
            text = (reader.pages[idx].extract_text() or "").strip()
        except Exception as exc:
            log.debug("pdf.page_extract_failed", page=idx, error=str(exc))
            text = ""
        if text:
            chunks.append(f"## Page {idx + 1}\n\n{text}")
    body = "\n\n".join(chunks) if chunks else ""
    return body, {"pdf_num_pages": total, "pdf_pages_extracted": len(chunks)}


__all__ = ["pdf_to_markdown"]
