"""Shared tool registry (PLAN §12).

Tools are the framework-wide capabilities any skill or workflow can invoke
through :class:`ToolRegistry`. Keep this package import-light — concrete
tool modules may pull in extra deps (``httpx``, ``pypdf``…), so the
``build_default_registry`` factory is what callers use in practice.
"""

from __future__ import annotations

from .arxiv_search import ArxivSearchTool
from .base import BaseTool, Tool, ToolResult
from .pdf_parse import PdfParseTool
from .registry import ToolRegistry, build_default_registry

__all__ = [
    "ArxivSearchTool",
    "BaseTool",
    "PdfParseTool",
    "Tool",
    "ToolRegistry",
    "ToolResult",
    "build_default_registry",
]
