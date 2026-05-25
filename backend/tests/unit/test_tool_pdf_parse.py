"""Unit tests for `PdfParseTool` — builds a minimal PDF in-memory."""

from __future__ import annotations

import io

import httpx
from pypdf import PdfWriter

from backend.tools.pdf_parse import PdfParseTool


def _tiny_pdf(pages: int = 2) -> bytes:
    """Produce a tiny valid PDF with `pages` blank pages.

    pypdf can extract an empty string from blank pages — enough to verify
    the shape of the tool's output; text-extraction fidelity is pypdf's
    responsibility, not ours.
    """
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _tool_from(transport: httpx.MockTransport) -> PdfParseTool:
    def factory() -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=transport, follow_redirects=True)

    return PdfParseTool(client_factory=factory)


async def test_requires_url_or_path():
    tool = PdfParseTool()
    res = await tool.call({})
    assert not res.ok
    assert "url" in (res.error or "").lower() or "path" in (res.error or "").lower()


async def test_parse_local_file(tmp_path):
    pdf = _tiny_pdf(pages=3)
    p = tmp_path / "demo.pdf"
    p.write_bytes(pdf)
    tool = PdfParseTool()
    res = await tool.call({"path": str(p), "max_pages": 5})
    assert res.ok, res.error
    data = res.data
    assert data["source"] == {"mode": "file", "path": str(p)}
    assert data["num_pages"] == 3
    assert data["pages_extracted"] == 3
    assert isinstance(data["pages"], list)
    assert isinstance(data["text"], str)


async def test_parse_url_mode():
    pdf_bytes = _tiny_pdf(pages=2)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=pdf_bytes, headers={"content-type": "application/pdf"})

    tool = _tool_from(httpx.MockTransport(handler))
    res = await tool.call({"url": "https://example.test/a.pdf", "max_pages": 5})
    assert res.ok, res.error
    assert res.data["source"]["mode"] == "url"
    assert res.data["num_pages"] == 2


async def test_http_errors_surface_as_result():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    tool = _tool_from(httpx.MockTransport(handler))
    res = await tool.call({"url": "https://example.test/a.pdf"})
    assert not res.ok
    assert res.meta.get("code") == "aaf.tool_http_error"


async def test_rejects_non_http_url():
    tool = PdfParseTool()
    res = await tool.call({"url": "ftp://example.test/a.pdf"})
    assert not res.ok
    assert "http" in (res.error or "").lower()


async def test_missing_local_file():
    tool = PdfParseTool()
    res = await tool.call({"path": "/tmp/this-does-not-exist-aaf.pdf"})
    assert not res.ok
    assert res.meta.get("code") == "aaf.tool_not_found"


async def test_max_pages_truncates(tmp_path):
    pdf = _tiny_pdf(pages=10)
    p = tmp_path / "big.pdf"
    p.write_bytes(pdf)
    tool = PdfParseTool()
    res = await tool.call({"path": str(p), "max_pages": 3})
    assert res.ok
    assert res.data["num_pages"] == 10
    assert res.data["pages_extracted"] == 3
