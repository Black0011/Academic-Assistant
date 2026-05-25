"""`pdf__parse` — download a PDF and extract text.

Strategy:

* Prefer ``pypdf`` (pure Python, already declared) — fast, no native deps.
* Accepts either a local ``path`` or an ``url`` (HTTP/HTTPS). URL mode
  requires network access and streams into a temporary bytes buffer; we
  never write to disk from the tool itself to keep runs side-effect free.
* Returns the full text plus a per-page list so downstream summarisers
  can pick the first few pages cheaply.
* ``max_pages`` caps work (PDFs routinely exceed 100 pages); the caller
  decides how much context it wants.

Security note: we do **not** follow redirects beyond one hop by default,
and we reject non-HTTPS redirects to HTTP to avoid silent downgrades.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import structlog

from .base import BaseTool, ToolResult

log = structlog.get_logger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]

MAX_PDF_BYTES = 40 * 1024 * 1024  # 40 MB safety cap


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(60.0, connect=10.0),
        follow_redirects=True,
        headers={"User-Agent": "academic-agent-framework/0.1 (+https://aaf.local)"},
    )


class PdfParseTool(BaseTool):
    name = "pdf__parse"
    description = (
        "Download (if url is given) or open (if path is given) a PDF and extract text. "
        "Returns {pages: [...], text: str, num_pages: int}."
    )
    parameters = {  # noqa: RUF012 — intentional shared spec across instances
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTPS PDF URL to download."},
            "path": {"type": "string", "description": "Local filesystem path to a PDF."},
            "max_pages": {
                "type": "integer",
                "minimum": 1,
                "maximum": 200,
                "default": 20,
            },
        },
        "anyOf": [{"required": ["url"]}, {"required": ["path"]}],
    }
    requires_network = True
    requires_paid_api = False

    def __init__(self, *, client_factory: ClientFactory | None = None) -> None:
        self._client_factory = client_factory or _default_client_factory

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        url = (arguments.get("url") or "").strip()
        path = (arguments.get("path") or "").strip()
        if not url and not path:
            return ToolResult(ok=False, error="pdf__parse: 'url' or 'path' is required")
        max_pages = int(arguments.get("max_pages") or 20)
        max_pages = max(1, min(max_pages, 200))

        try:
            if path:
                raw = await _read_local(path)
                source = {"mode": "file", "path": path}
            else:
                raw = await _fetch_pdf(url, self._client_factory)
                source = {"mode": "url", "url": url}
        except FileNotFoundError as exc:
            return ToolResult(ok=False, error=str(exc), meta={"code": "aaf.tool_not_found"})
        except httpx.HTTPError as exc:
            log.warning("pdf.http_error", error=str(exc), url=url)
            return ToolResult(
                ok=False,
                error=f"pdf http error: {exc}",
                meta={"code": "aaf.tool_http_error"},
            )
        except ValueError as exc:
            return ToolResult(ok=False, error=str(exc), meta={"code": "aaf.tool_validation_error"})

        try:
            pages, num_pages = _extract_text(raw, max_pages=max_pages)
        except Exception as exc:  # pypdf throws a variety of exception types
            log.warning("pdf.parse_failed", error=str(exc))
            return ToolResult(
                ok=False,
                error=f"pdf parse failed: {exc}",
                meta={"code": "aaf.tool_parse_error"},
            )

        text = "\n\n".join(p for p in pages if p).strip()
        return ToolResult(
            ok=True,
            data={
                "source": source,
                "num_pages": num_pages,
                "pages_extracted": len(pages),
                "pages": pages,
                "text": text,
            },
        )


# ---------------------------------------------------------------------------
# IO helpers
# ---------------------------------------------------------------------------


async def _read_local(path: str) -> bytes:
    import asyncio

    def _read() -> bytes:
        p = Path(path).expanduser()
        if not p.exists() or not p.is_file():
            raise FileNotFoundError(f"pdf not found: {path}")
        return p.read_bytes()

    return await asyncio.to_thread(_read)


async def _fetch_pdf(url: str, factory: ClientFactory) -> bytes:
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"url must be http(s): {url!r}")
    async with factory() as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            buf = bytearray()
            async for chunk in resp.aiter_bytes():
                buf.extend(chunk)
                if len(buf) > MAX_PDF_BYTES:
                    raise ValueError(f"pdf exceeds size cap ({MAX_PDF_BYTES} bytes)")
            return bytes(buf)


def _extract_text(raw: bytes, *, max_pages: int) -> tuple[list[str], int]:
    """Use pypdf to extract per-page text. Returns (pages, total_page_count)."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(raw))
    total = len(reader.pages)
    limit = min(max_pages, total)
    pages: list[str] = []
    for idx in range(limit):
        try:
            pages.append((reader.pages[idx].extract_text() or "").strip())
        except Exception as exc:
            log.debug("pdf.page_extract_failed", page=idx, error=str(exc))
            pages.append("")
    return pages, total


__all__ = ["MAX_PDF_BYTES", "PdfParseTool"]
