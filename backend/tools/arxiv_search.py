"""`arxiv__search` — query arXiv's public Atom API.

Minimal, dependency-light port of the Academic-Agent arXiv searcher. We
drive the API directly over Python's stdlib ``urllib.request`` (same
OpenSSL path as the system ``curl``) and parse the Atom payload with
``feedparser`` (already a declared dependency).

We deliberately avoid ``httpx`` for this specific tool. arXiv's edge
fronts requests through a CDN that fingerprints client TLS hellos +
HTTP framing, and the Python httpx fingerprint is well-known to bot
detection systems — empirically it gets soft-throttled (TCP accept,
no application response, eventual ``ReadTimeout``) on networks where
``curl`` succeeds in <1s. ``urllib.request`` uses the same TLS code
path the OS curl uses, which sails through.

Important properties:

* **Zero paid API / auth** — ``requires_paid_api = False``.
* **Network required** — ``requires_network = True``; disabled runs
  skip the tool through ``ToolRegistry``.
* **Injectable fetcher** — the ``fetcher`` argument lets unit tests
  return canned Atom payloads without touching the network.
* **Stable output shape** — each result is a dict with the exact keys
  the Research workflow expects (``paper_id``, ``title``, ``authors``,
  ``year``, ``pdf_url``, ``summary``, ``entry_id``, ``categories``).
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

import feedparser
import structlog

from backend.memory.base import stable_id

from .base import BaseTool, ToolResult

log = structlog.get_logger(__name__)

ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"


@dataclass(frozen=True)
class FetchResult:
    """A flattened HTTP response that hides the underlying client choice."""

    status: int
    body: str
    headers: dict[str, str]


Fetcher = Callable[[str, dict[str, Any], dict[str, str], float], Awaitable[FetchResult]]


# arXiv asks API consumers to space requests at least ~3 seconds apart
# (https://info.arxiv.org/help/api/tou.html). We retry transient 429/503
# with bounded exponential backoff and honour any Retry-After header so
# users behind a shared NAT (multiple devs on one office IP) recover
# automatically instead of needing manual cool-down.
_RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 4
_BASE_BACKOFF_S = 3.0  # arxiv guidance — we round up rather than down
_MAX_BACKOFF_S = 30.0
_DEFAULT_TIMEOUT_S = 45.0

_DEFAULT_HEADERS: dict[str, str] = {
    # arXiv's TOU asks for a self-identifying User-Agent. We keep it short,
    # avoid `.local` (mDNS-reserved → flagged by WAFs), and include a
    # contact hint per arxiv's published guidance.
    "User-Agent": "aaf/0.1 (academic-agent-framework; +mailto:dev@aaf.example)",
    "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.5",
    "Accept-Encoding": "identity",
}


# Build an opener that respects AAF_HTTPS_PROXY / HTTPS_PROXY when set,
# otherwise uses a direct connection (avoiding stale/inaccessible proxies).
def _build_opener():
    import os as _os
    proxy_url = _os.environ.get("AAF_HTTPS_PROXY") or _os.environ.get("HTTPS_PROXY") or ""
    if proxy_url:
        return build_opener(ProxyHandler({"https": proxy_url}), HTTPSHandler())
    return build_opener(ProxyHandler({}), HTTPSHandler())

_DIRECT_OPENER = _build_opener()


async def _urllib_fetch(
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: float,  # noqa: ASYNC109 - protocol mirrors a per-call deadline
) -> FetchResult:
    """Run ``urllib.request.urlopen`` in a worker thread.

    Why urllib, not httpx? See module docstring — arXiv's CDN soft-throttles
    httpx's TLS/HTTP fingerprint to a 20s timeout on some networks.

    Why a direct opener? Default ``urlopen`` reads ``HTTPS_PROXY`` from the
    process environment. We bypass that to keep our outbound HTTPS path
    deterministic regardless of how the operator launched uvicorn. If a
    user genuinely *wants* a proxy (e.g. corporate egress), they should
    point it via a future ``AAF_HTTP_PROXY`` setting we'll plumb through.
    """
    full = f"{url}?{urlencode(params)}" if params else url

    def _sync() -> FetchResult:
        req = Request(full, method="GET", headers=headers)
        try:
            with _DIRECT_OPENER.open(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
                return FetchResult(
                    status=resp.status,
                    body=body,
                    headers={k.lower(): v for k, v in resp.headers.items()},
                )
        except HTTPError as exc:
            # urllib treats 4xx/5xx as exceptions; we want to surface them
            # so the retry loop above can decide whether to wait + retry.
            body = ""
            try:
                body = exc.read().decode("utf-8", errors="replace")
            except Exception:  # pragma: no cover - body read can fail
                pass
            return FetchResult(
                status=exc.code,
                body=body,
                headers={k.lower(): v for k, v in (exc.headers or {}).items()},
            )

    return await asyncio.to_thread(_sync)


def _retry_after_seconds(headers: dict[str, str], fallback: float) -> float:
    """Honour ``Retry-After`` (seconds form) when arxiv supplies it."""
    raw = headers.get("retry-after")
    if not raw:
        return fallback
    try:
        return max(fallback, float(raw))
    except ValueError:
        return fallback


class ArxivSearchTool(BaseTool):
    name = "arxiv__search"
    description = (
        "Search arXiv for academic papers by keyword query. "
        "Returns up to `max_results` entries ranked by relevance."
    )
    parameters = {  # noqa: RUF012 — intentional shared spec across instances
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Free-text query, e.g. 'retrieval augmented generation'.",
            },
            "max_results": {
                "type": "integer",
                "minimum": 1,
                "maximum": 50,
                "default": 5,
            },
            "sort_by": {
                "type": "string",
                "enum": ["relevance", "lastUpdatedDate", "submittedDate"],
                "default": "relevance",
            },
            "sort_order": {
                "type": "string",
                "enum": ["ascending", "descending"],
                "default": "descending",
            },
        },
        "required": ["query"],
    }
    requires_network = True
    requires_paid_api = False

    def __init__(
        self,
        *,
        endpoint: str = ARXIV_ENDPOINT,
        fetcher: Fetcher | None = None,
        timeout: float = _DEFAULT_TIMEOUT_S,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._endpoint = endpoint
        self._fetcher: Fetcher = fetcher or _urllib_fetch
        self._timeout = timeout
        self._headers = dict(_DEFAULT_HEADERS, **(headers or {}))

    async def call(self, arguments: dict[str, Any]) -> ToolResult:
        query = (arguments.get("query") or "").strip()
        if not query:
            return ToolResult(ok=False, error="arxiv__search: 'query' is required")
        max_results = int(arguments.get("max_results") or 5)
        max_results = max(1, min(max_results, 50))
        sort_by = arguments.get("sort_by") or "relevance"
        sort_order = arguments.get("sort_order") or "descending"

        params: dict[str, Any] = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        attempt = 0
        try:
            while True:
                attempt += 1
                result = await self._fetcher(self._endpoint, params, self._headers, self._timeout)
                if result.status in _RETRYABLE_STATUS and attempt < _MAX_ATTEMPTS:
                    backoff = min(
                        _BASE_BACKOFF_S * (2 ** (attempt - 1)) + random.uniform(0, 0.5),
                        _MAX_BACKOFF_S,
                    )
                    wait_s = _retry_after_seconds(result.headers, backoff)
                    log.info(
                        "arxiv.retry",
                        attempt=attempt,
                        status=result.status,
                        wait_s=round(wait_s, 2),
                    )
                    await asyncio.sleep(wait_s)
                    continue
                if 200 <= result.status < 300:
                    body = result.body
                    break
                return ToolResult(
                    ok=False,
                    error=(
                        f"arxiv http error: {result.status} (body preview: {result.body[:200]!r})"
                    ),
                    meta={"code": "aaf.tool_http_error", "status": result.status},
                )
        except (URLError, OSError, TimeoutError) as exc:
            kind = type(exc).__name__
            detail = str(exc) or "(no message)"
            hint = ""
            if "timeout" in detail.lower() or "Timeout" in kind:
                hint = (
                    " — TCP connected but no response within timeout; "
                    "likely a corporate firewall / SWG silently dropping "
                    "export.arxiv.org. Verify with: "
                    "`curl -v --max-time 15 https://export.arxiv.org/api/query?search_query=all:test`."
                )
            elif "SSL" in detail or "CERTIFICATE" in detail.upper():
                hint = (
                    " — TLS verification failed; install `truststore` and "
                    "ensure your corporate root CA is in the OS trust store, "
                    "or set $SSL_CERT_FILE to a CA bundle that includes it."
                )
            elif "resolution" in detail.lower() or "name or service" in detail.lower():
                hint = " — hostname unreachable (DNS or routing block)."
            log.warning("arxiv.http_error", kind=kind, error=detail)
            return ToolResult(
                ok=False,
                error=f"arxiv http error ({kind}): {detail}{hint}",
                meta={"code": "aaf.tool_http_error", "kind": kind},
            )

        parsed = feedparser.parse(body)
        results = [_entry_to_dict(entry) for entry in parsed.entries]
        return ToolResult(
            ok=True,
            data={"query": query, "count": len(results), "results": results},
            meta={"source": "arxiv", "endpoint": self._endpoint},
        )


def _entry_to_dict(entry: Any) -> dict[str, Any]:
    """Normalise a feedparser Atom entry into the shape we promise."""
    entry_id = getattr(entry, "id", "") or ""
    arxiv_id = entry_id.rsplit("/", 1)[-1] if entry_id else ""
    title = (getattr(entry, "title", "") or "").strip().replace("\n", " ")
    summary = (getattr(entry, "summary", "") or "").strip()
    authors = [a.get("name", "").strip() for a in getattr(entry, "authors", []) if a.get("name")]
    year: int | None = None
    published = getattr(entry, "published", "") or ""
    if len(published) >= 4 and published[:4].isdigit():
        year = int(published[:4])
    categories = [t.get("term", "") for t in getattr(entry, "tags", []) if t.get("term")]

    pdf_url = ""
    for link in getattr(entry, "links", []):
        if link.get("type") == "application/pdf" or link.get("title") == "pdf":
            pdf_url = link.get("href", "")
            break
    if not pdf_url and arxiv_id:
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    paper_id = stable_id("arxiv", arxiv_id or entry_id or title)
    citation_url = f"https://arxiv.org/bibtex/{arxiv_id}" if arxiv_id else ""

    return {
        "paper_id": paper_id,
        "arxiv_id": arxiv_id,
        "entry_id": entry_id,
        "title": title,
        "authors": authors,
        "year": year,
        "summary": summary,
        "pdf_url": pdf_url,
        "citation_url": citation_url,
        "categories": categories,
    }


__all__ = ["ARXIV_ENDPOINT", "ArxivSearchTool", "FetchResult", "Fetcher"]
