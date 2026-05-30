"""Text-extraction helpers shared across the backend.

Each helper returns ``(body, meta)`` so callers can persist the body and
attach the metadata without re-parsing.
"""

from __future__ import annotations

from .pdf import pdf_to_markdown

__all__ = ["pdf_to_markdown"]
