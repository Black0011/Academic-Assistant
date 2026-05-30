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

# Multi-endpoint fallback. All preserve original GS HTML (.gs_ri etc).
# Ordered by likelihood of access from mainland China.
SCHOLAR_ENDPOINTS: list[str] = [
    "https://scholar.google.com/scholar",        # 官网 (需代理)
    "https://scholar.google.com.hk/scholar",      # 备选1: 香港
    "https://scholar.google.com.sg/scholar",      # 备选2: 新加坡
    "https://scholar.google.co.jp/scholar",       # 备选3: 日本
    "https://ac.scmor.com/scholar",               # 备选4: 老牌反向代理镜像
]
CITATION_ENDPOINTS: list[str] = [
    "https://scholar.google.com",                 # 官网
    "https://scholar.google.com.hk",              # 备选1
    "https://scholar.google.com.sg",              # 备选2
    "https://scholar.google.co.jp",               # 备选3
    "https://ac.scmor.com",                       # 备选4
]
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


def _parse_author_string(author_text: str) -> list[str]:
    """Parse a Google Scholar author string into a list of names."""
    cleaned = _clean(author_text)
    if not cleaned:
        return []
    # Normalize common separators and truncate marker.
    cleaned = cleaned.replace("...", "")
    cleaned = cleaned.replace("\u2026", "")
    cleaned = cleaned.replace(" and ", ", ")
    parts = [p.strip() for p in cleaned.split(",")]
    return [p for p in parts if p]


def _fallback_bibtex_from_result(result: dict[str, Any]) -> str | None:
    title = _clean(result.get("Title", ""))
    authors_text = _clean(result.get("Authors", ""))
    url = _clean(result.get("URL", ""))
    if not title:
        return None

    parts = [p.strip() for p in authors_text.split(" - ") if p.strip()]
    authors = _parse_author_string(parts[0]) if parts else []
    venue = parts[1] if len(parts) >= 2 else ""
    ym = re.search(r"\b((?:19|20)\d{2})[a-z]?\b", authors_text)
    year = ym.group(1) if ym else ""

    key_author = (authors[0].split()[-1] if authors else "unknown")
    key_word = re.sub(r"[^A-Za-z0-9]+", "", title.split()[0]) if title else "paper"
    key_year = year if year else "nd"
    key = f"{key_author}{key_year}{key_word}".lower()

    lines = [f"@article{{{key},", f"  title={{{title}}},"]
    if authors:
        lines.append(f"  author={{{' and '.join(authors)}}},")
    if year:
        lines.append(f"  year={{{year}}},")
    if venue:
        lines.append(f"  journal={{{venue}}},")
    if url:
        lines.append(f"  url={{{url}}},")
    lines.append("}")
    return "\n".join(lines)


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


def _try_endpoints(
    endpoints: list[str],
    params: dict[str, Any],
    *,
    path: str = "/scholar",
    timeout: float = TIMEOUT_S,
) -> requests.Response:
    """Try each Google Scholar endpoint. Retries without proxy if proxy fails."""
    last_error: Exception | None = None
    sess = _session()
    for use_proxy in (True, False):
        if not use_proxy:
            sess.proxies = {}
        for base_url in endpoints:
            url = base_url if base_url.endswith(path) else base_url.rstrip("/") + path
            try:
                resp = sess.get(url, params=params, headers=HEADERS, timeout=timeout)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                last_error = exc
                continue
    raise RuntimeError(
        f"All {len(endpoints)} endpoints failed (tried with and without proxy). "
        f"Last error: {last_error}"
    )


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
        resp = _try_endpoints(SCHOLAR_ENDPOINTS, params)
    except RuntimeError as exc:
        raise RuntimeError(f"Google Scholar search failed: {exc}") from exc

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
        resp = _try_endpoints(SCHOLAR_ENDPOINTS, params)
    except RuntimeError:
        return None
    soup = BeautifulSoup(resp.text, "html.parser")
    cite_url = None
    base_url = resp.url.rsplit("/scholar", 1)[0] if "/scholar" in resp.url else resp.url
    for link in soup.select("a.gs_or_cit"):
        href = link.get("href", "")
        if "scholar" in href:
            cite_url = base_url + href if href.startswith("/") else href
            break
    if not cite_url:
        first = soup.select_one("div.gs_ri")
        if first:
            parsed = _parse_result(first)
            if parsed:
                return _fallback_bibtex_from_result(parsed)
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
            bib_url = base_url + href if href.startswith("/") else href
            try:
                bib_resp = _session().get(bib_url, headers=HEADERS, timeout=TIMEOUT_S)
                bib_resp.raise_for_status()
                return bib_resp.text.strip()
            except requests.RequestException:
                return None
    first = soup.select_one("div.gs_ri")
    if first:
        parsed = _parse_result(first)
        if parsed:
            return _fallback_bibtex_from_result(parsed)
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
        resp = _try_endpoints(SCHOLAR_ENDPOINTS, params)
    except RuntimeError as exc:
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
