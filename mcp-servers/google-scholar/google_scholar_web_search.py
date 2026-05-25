"""Google Scholar web search — lightweight HTML scraper.

Parses Google Scholar search result pages using requests + BeautifulSoup.
This is deliberately simple: the MCP server wraps this module's functions
as MCP tools.
"""

from __future__ import annotations

import re
import ssl
from typing import Any
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager

SCHOLAR_URL = "https://scholar.google.com/scholar"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT_S = 20.0

_CLEAN_RE = re.compile(r"\s+")


class _NoVerifyAdapter(HTTPAdapter):
    """HTTPS adapter that skips SSL verification (needed for proxy/VPN)."""

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs["ssl_context"] = ctx
        return super().init_poolmanager(*args, **kwargs)


def _get_session() -> requests.Session:
    s = requests.Session()
    s.verify = False
    s.mount("https://", _NoVerifyAdapter())
    # Configure proxy from env (AIP_HTTPS_PROXY for tool-specific, HTTPS_PROXY for global)
    import os as _os
    proxy = _os.environ.get("AIP_HTTPS_PROXY") or _os.environ.get("HTTPS_PROXY")
    if proxy:
        s.proxies = {"http": proxy, "https": proxy}
    return s


def _clean(s: str) -> str:
    return _CLEAN_RE.sub(" ", (s or "").strip())


def _parse_result(div) -> dict[str, Any] | None:
    """Parse a single .gs_ri div into a structured result dict."""
    title_el = div.select_one("h3.gs_rt")
    if not title_el:
        return None
    title_link = title_el.select_one("a")
    title = _clean(title_el.get_text())
    url = title_link.get("href", "") if title_link else ""

    authors_el = div.select_one("div.gs_a")
    authors_text = _clean(authors_el.get_text()) if authors_el else ""

    abstract_el = div.select_one("div.gs_rs")
    abstract = _clean(abstract_el.get_text()) if abstract_el else ""

    return {
        "Title": title,
        "URL": url,
        "Authors": authors_text,
        "Abstract": abstract,
    }


_sessions: dict[int, requests.Session] = {}


def _session() -> requests.Session:
    # One session per thread, since MCP tools may be called from different threads
    import threading
    tid = threading.get_ident()
    if tid not in _sessions:
        _sessions[tid] = _get_session()
    return _sessions[tid]


def google_scholar_search(query: str, num_results: int = 5) -> list[dict[str, Any]]:
    """Search Google Scholar by keyword query.

    Args:
        query: Free-text search query.
        num_results: Max results to return (1-20).

    Returns:
        List of dicts with keys: Title, Authors, Abstract, URL.
    """
    num_results = max(1, min(num_results, 20))
    params = {
        "q": query,
        "hl": "en",
        "lr": "lang_en",
        "num": num_results,
    }
    try:
        resp = _session().get(
            SCHOLAR_URL,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Google Scholar request failed: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, Any]] = []
    for div in soup.select("div.gs_ri"):
        parsed = _parse_result(div)
        if parsed:
            results.append(parsed)
        if len(results) >= num_results:
            break
    return results


def get_citation_bibtex(query: str) -> str | None:
    """Fetch BibTeX citation from Google Scholar for the first search result."""
    import re as _re_bib
    params = {"q": query, "hl": "en", "num": 1}
    try:
        resp = _session().get(SCHOLAR_URL, params=params, headers=HEADERS, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    cite_url = None
    for link in soup.select("a.gs_or_cit"):
        href = link.get("href", "")
        if "scholar" in href:
            cite_url = "https://scholar.google.com" + href if href.startswith("/") else href
            break
    if not cite_url:
        return None
    try:
        cite_resp = _session().get(cite_url, headers=HEADERS, timeout=TIMEOUT_S)
        cite_resp.raise_for_status()
    except requests.RequestException:
        return None
    cite_soup = BeautifulSoup(cite_resp.text, "html.parser")
    for link in cite_soup.select("a"):
        href = link.get("href", "")
        if "output=cite" in href or "output=bibtex" in href:
            bib_url = "https://scholar.google.com" + href if href.startswith("/") else href
            try:
                bib_resp = _session().get(bib_url, headers=HEADERS, timeout=TIMEOUT_S)
                bib_resp.raise_for_status()
                return bib_resp.text.strip()
            except requests.RequestException:
                return None
    return None


def get_citation_metadata(query: str) -> dict[str, Any] | None:
    """Get full citation metadata (title, authors, year, venue, bibtex) from Google Scholar."""
    import re as _re_meta
    results = google_scholar_search(query, num_results=1)
    if not results:
        return None
    r = results[0]
    authors_text = r.get("Authors", "")
    year = None
    ym = _re_meta.search(r"\b((?:19|20)\d{2})[a-z]?\b", authors_text)
    if ym:
        year = int(ym.group(1))
    parts = [p.strip() for p in authors_text.split(" - ")]
    authors = _parse_author_string(parts[0]) if parts else []
    venue = parts[1] if len(parts) >= 2 else authors_text
    bibtex = get_citation_bibtex(query)
    return {
        "title": r.get("Title", ""),
        "authors": authors,
        "year": year,
        "venue": venue,
        "url": r.get("URL", ""),
        "abstract": r.get("Abstract", ""),
        "bibtex": bibtex,
    }


def advanced_google_scholar_search(
    query: str = "",
    author: str = "",
    year_range: tuple[int, int] | None = None,
    num_results: int = 5,
) -> list[dict[str, Any]]:
    """Search Google Scholar with advanced filters.

    Args:
        query: General search query.
        author: Filter by author name (as_auth parameter).
        year_range: Optional (start_year, end_year) tuple.
        num_results: Max results to return (1-20).

    Returns:
        List of dicts with keys: Title, Authors, Abstract, URL.
    """
    num_results = max(1, min(num_results, 20))
    params: dict[str, Any] = {
        "q": query or "",
        "hl": "en",
        "lr": "lang_en",
        "num": num_results,
    }
    if author:
        params["as_auth"] = author
    if year_range and len(year_range) == 2:
        params["as_ylo"] = int(year_range[0])
        params["as_yhi"] = int(year_range[1])

    try:
        resp = _session().get(
            SCHOLAR_URL,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT_S,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"Google Scholar advanced search failed: {exc}") from exc

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[dict[str, Any]] = []
    for div in soup.select("div.gs_ri"):
        parsed = _parse_result(div)
        if parsed:
            results.append(parsed)
        if len(results) >= num_results:
            break
    return results


def get_citation_bibtex(query: str) -> str | None:
    """Fetch BibTeX citation from Google Scholar for the first search result."""
    import re as _re_bib
    params = {"q": query, "hl": "en", "num": 1}
    try:
        resp = _session().get(SCHOLAR_URL, params=params, headers=HEADERS, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    cite_url = None
    for link in soup.select("a.gs_or_cit"):
        href = link.get("href", "")
        if "scholar" in href:
            cite_url = "https://scholar.google.com" + href if href.startswith("/") else href
            break
    if not cite_url:
        return None
    try:
        cite_resp = _session().get(cite_url, headers=HEADERS, timeout=TIMEOUT_S)
        cite_resp.raise_for_status()
    except requests.RequestException:
        return None
    cite_soup = BeautifulSoup(cite_resp.text, "html.parser")
    for link in cite_soup.select("a"):
        href = link.get("href", "")
        if "output=cite" in href or "output=bibtex" in href:
            bib_url = "https://scholar.google.com" + href if href.startswith("/") else href
            try:
                bib_resp = _session().get(bib_url, headers=HEADERS, timeout=TIMEOUT_S)
                bib_resp.raise_for_status()
                return bib_resp.text.strip()
            except requests.RequestException:
                return None
    return None


def get_citation_metadata(query: str) -> dict[str, Any] | None:
    """Get full citation metadata (title, authors, year, venue, bibtex) from Google Scholar."""
    import re as _re_meta
    results = google_scholar_search(query, num_results=1)
    if not results:
        return None
    r = results[0]
    authors_text = r.get("Authors", "")
    year = None
    ym = _re_meta.search(r"\b((?:19|20)\d{2})[a-z]?\b", authors_text)
    if ym:
        year = int(ym.group(1))
    parts = [p.strip() for p in authors_text.split(" - ")]
    authors = _parse_author_string(parts[0]) if parts else []
    venue = parts[1] if len(parts) >= 2 else authors_text
    bibtex = get_citation_bibtex(query)
    return {
        "title": r.get("Title", ""),
        "authors": authors,
        "year": year,
        "venue": venue,
        "url": r.get("URL", ""),
        "abstract": r.get("Abstract", ""),
        "bibtex": bibtex,
    }
