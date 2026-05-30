"""Unit tests for `ArxivSearchTool` — uses an injected stub fetcher."""

from __future__ import annotations

from typing import Any

from backend.tools.arxiv_search import ArxivSearchTool, FetchResult

ATOM_SAMPLE = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Retrieval Augmented Generation</title>
    <summary>A paper about RAG.</summary>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Alice</name></author>
    <author><name>Bob</name></author>
    <category term="cs.CL"/>
    <link title="pdf" href="https://arxiv.org/pdf/2401.00001v1.pdf" type="application/pdf"/>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2402.00002v2</id>
    <title>Another Paper</title>
    <summary>About something else.</summary>
    <published>2024-02-10T00:00:00Z</published>
    <author><name>Carol</name></author>
    <link title="pdf" href="https://arxiv.org/pdf/2402.00002v2.pdf" type="application/pdf"/>
  </entry>
</feed>
"""


def _make_fetcher(
    payload: str = ATOM_SAMPLE, status: int = 200, headers: dict[str, str] | None = None
):
    async def fetch(
        url: str,
        params: dict[str, Any],
        req_headers: dict[str, str],
        timeout: float,  # noqa: ASYNC109 - mirrors Fetcher protocol signature
    ) -> FetchResult:
        assert "example.test" in url
        return FetchResult(status=status, body=payload, headers=headers or {})

    return fetch


def _tool(
    payload: str = ATOM_SAMPLE, status: int = 200, headers: dict[str, str] | None = None
) -> ArxivSearchTool:
    return ArxivSearchTool(
        endpoint="https://example.test/api/query",
        fetcher=_make_fetcher(payload, status, headers),
    )


async def test_search_parses_entries():
    tool = _tool()
    result = await tool.call({"query": "RAG", "max_results": 5})
    assert result.ok, result.error
    data = result.data
    assert data["count"] == 2
    first = data["results"][0]
    assert first["title"] == "Retrieval Augmented Generation"
    assert first["authors"] == ["Alice", "Bob"]
    assert first["year"] == 2024
    assert first["pdf_url"].endswith(".pdf")
    assert "arxiv" in first["entry_id"]
    assert first["paper_id"]
    assert "cs.CL" in first["categories"]


async def test_search_requires_query():
    tool = _tool()
    res = await tool.call({"query": "   "})
    assert not res.ok
    assert "query" in res.error.lower()


async def test_search_handles_http_error():
    # 4xx is non-retryable and should surface immediately.
    tool = _tool(payload="not found", status=404)
    res = await tool.call({"query": "hi"})
    assert not res.ok
    assert "http" in (res.error or "").lower()
    assert res.meta.get("code") == "aaf.tool_http_error"


async def test_search_clamps_max_results():
    tool = _tool()
    res = await tool.call({"query": "q", "max_results": 500})
    # Even with 500 requested, the fake payload only has 2 entries — we
    # mainly assert the tool didn't error on clamping.
    assert res.ok
    assert res.data["count"] == 2


async def test_search_deterministic_paper_id():
    tool = _tool()
    a = await tool.call({"query": "q"})
    b = await tool.call({"query": "q"})
    ids_a = [r["paper_id"] for r in a.data["results"]]
    ids_b = [r["paper_id"] for r in b.data["results"]]
    assert ids_a == ids_b


async def test_search_retries_on_429_then_succeeds(monkeypatch):
    """Retry path: first call returns 429, second succeeds. We monkey-patch
    ``asyncio.sleep`` to keep the test fast; the real backoff is exercised
    in the integration tests."""
    calls = {"n": 0}

    async def flaky_fetch(
        url: str,
        params: dict[str, Any],
        headers: dict[str, str],
        timeout: float,  # noqa: ASYNC109 - mirrors Fetcher protocol signature
    ) -> FetchResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return FetchResult(status=429, body="rate-limited", headers={"retry-after": "0"})
        return FetchResult(status=200, body=ATOM_SAMPLE, headers={})

    async def fast_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr("backend.tools.arxiv_search.asyncio.sleep", fast_sleep)

    tool = ArxivSearchTool(endpoint="https://example.test/api/query", fetcher=flaky_fetch)
    res = await tool.call({"query": "q"})
    assert res.ok, res.error
    assert calls["n"] == 2
