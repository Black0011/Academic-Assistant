"""Google Scholar MCP Server.

Exposes 3 MCP tools over stdio transport:
  1. search_google_scholar_key_words  — keyword search
  2. search_google_scholar_advanced   — advanced search (author, year range)
  3. get_author_info                  — author profile lookup via scholarly

Run directly:
    python google_scholar_server.py
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from google_scholar_web_search import advanced_google_scholar_search, google_scholar_search

mcp = FastMCP("scholar_pubmed")


@mcp.tool()
def search_google_scholar_key_words(
    query: str,
    num_results: int = 5,
) -> list[dict[str, Any]]:
    """Search Google Scholar by keyword query.

    Args:
        query: Free-text search query (e.g. "attention is all you need").
        num_results: Number of results to return (1-20, default 5).

    Returns:
        List of results, each with Title, Authors, Abstract, URL.
    """
    return google_scholar_search(query=query, num_results=num_results)


@mcp.tool()
def search_google_scholar_advanced(
    query: str = "",
    author: str = "",
    year_start: int | None = None,
    year_end: int | None = None,
    num_results: int = 5,
) -> list[dict[str, Any]]:
    """Search Google Scholar with advanced filters.

    Args:
        query: General search query.
        author: Filter by author name.
        year_start: Start year for date range filter.
        year_end: End year for date range filter.
        num_results: Number of results to return (1-20, default 5).

    Returns:
        List of results, each with Title, Authors, Abstract, URL.
    """
    year_range: tuple[int, int] | None = None
    if year_start is not None and year_end is not None:
        year_range = (year_start, year_end)
    return advanced_google_scholar_search(
        query=query,
        author=author,
        year_range=year_range,
        num_results=num_results,
    )


@mcp.tool()
def get_author_info(
    author_name: str,
) -> dict[str, Any] | None:
    """Look up an author by name on Google Scholar.

    Args:
        author_name: Full name of the author.

    Returns:
        Dict with name, affiliation, interests, citedby, publications,
        or None if not found.
    """
    try:
        import scholarly as _scholarly
    except ImportError:
        return {"error": "scholarly library not installed"}

    try:
        author = next(_scholarly.search_author(author_name), None)
        if author is None:
            return None
        filled = _scholarly.fill(author)
        publications: list[dict[str, Any]] = []
        for pub in filled.get("publications", [])[:5]:
            pub_filled = pub
            try:
                pub_filled = _scholarly.fill(pub)
            except Exception:
                pass
            publications.append({
                "title": pub_filled.get("bib", {}).get("title", ""),
                "year": pub_filled.get("bib", {}).get("pub_year", ""),
                "citations": pub_filled.get("num_citations", 0),
            })
        return {
            "name": filled.get("name", ""),
            "affiliation": filled.get("affiliation", ""),
            "interests": filled.get("interests", []),
            "citedby": filled.get("citedby", 0),
            "publications": publications,
        }
    except Exception as exc:
        return {"error": f"Author lookup failed: {exc}"}


@mcp.tool()
def get_citation_bibtex(
    query: str,
) -> str | None:
    """Get BibTeX citation for a paper from Google Scholar.

    Searches Google Scholar for the paper and fetches its BibTeX entry.

    Args:
        query: Title + authors to search for, e.g. \"Spider 2.0 Evaluating Language Models\".

    Returns:
        Raw BibTeX string, or None if not found.
    """
    from google_scholar_web_search import get_citation_bibtex as _bib
    return _bib(query)


@mcp.tool()
def get_citation_metadata(
    query: str,
) -> dict[str, Any] | None:
    """Get full citation metadata for a paper from Google Scholar.

    Searches Google Scholar, extracts title, authors, year, venue,
    abstract, URL, and BibTeX (if available).

    Args:
        query: Title + authors to search for.

    Returns:
        Dict with: title, authors, year, venue, url, abstract, bibtex.
        None if paper not found.
    """
    from google_scholar_web_search import get_citation_metadata as _meta
    return _meta(query)


if __name__ == "__main__":
    mcp.run()
