"""``/api/memory``, ``/api/knowledge`` and ``/api/heuristics`` sub-clients."""

from __future__ import annotations

from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Literal

from .models import (
    Heuristic,
    HeuristicDomain,
    HeuristicVerdict,
    IngestPaperResponse,
    MemoryStats,
    PaperCard,
    Reflection,
    ReflectionType,
    RollbackResponse,
    SourceKind,
    StrategyBlock,
)

if TYPE_CHECKING:  # pragma: no cover
    from .client import AAFClient, AsyncAAFClient


# ---------------------------------------------------------------------------
# Knowledge
# ---------------------------------------------------------------------------


class _KnowledgeMixin:
    @staticmethod
    def _list_params(
        *,
        q: str | None,
        tag: str | None,
        user_id: str | None,
        session_id: str | None,
        source_run_id: str | None,
        k: int | None,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        return {
            "q": q,
            "tag": tag,
            "user_id": user_id,
            "session_id": session_id,
            "source_run_id": source_run_id,
            "k": k,
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _create_payload(
        *,
        title: str,
        paper_id: str | None,
        authors: list[str] | None,
        year: int | None,
        venue: str | None,
        abstract: str,
        summary: str,
        method: str,
        findings: str,
        tags: list[str] | None,
        source_run_id: str | None,
        user_id: str | None,
        session_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": title,
            "authors": authors or [],
            "abstract": abstract,
            "summary": summary,
            "method": method,
            "findings": findings,
            "tags": tags or [],
        }
        if paper_id is not None:
            payload["paper_id"] = paper_id
        if year is not None:
            payload["year"] = year
        if venue is not None:
            payload["venue"] = venue
        if source_run_id is not None:
            payload["source_run_id"] = source_run_id
        if user_id is not None:
            payload["user_id"] = user_id
        if session_id is not None:
            payload["session_id"] = session_id
        return payload

    @staticmethod
    def _ingest_form_data(
        *,
        title: str | None,
        authors: list[str] | None,
        year: int | None,
        venue: str | None,
        tags: list[str] | None,
        source_kind: SourceKind,
        source_uri: str | None,
        trigger_evolution: bool,
        llm_extract: bool,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source_kind": source_kind,
            "trigger_evolution": "true" if trigger_evolution else "false",
            "llm_extract": "true" if llm_extract else "false",
        }
        if title:
            data["title"] = title
        if authors:
            data["authors"] = ", ".join(authors)
        if year is not None:
            data["year"] = str(year)
        if venue:
            data["venue"] = venue
        if tags:
            data["tags"] = ", ".join(tags)
        if source_uri:
            data["source_uri"] = source_uri
        return data

    @staticmethod
    def _ingest_json_payload(
        *,
        title: str,
        authors: list[str] | None,
        year: int | None,
        venue: str | None,
        abstract: str,
        summary: str,
        method: str,
        findings: str,
        tags: list[str] | None,
        source_kind: SourceKind,
        source_uri: str | None,
        body_text: str,
        trigger_evolution: bool,
        llm_extract: bool,
        user_id: str | None,
        session_id: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "title": title,
            "authors": authors or [],
            "abstract": abstract,
            "summary": summary,
            "method": method,
            "findings": findings,
            "tags": tags or [],
            "source_kind": source_kind,
            "source_uri": source_uri or "",
            "body_text": body_text,
            "trigger_evolution": trigger_evolution,
            "llm_extract": llm_extract,
        }
        if year is not None:
            payload["year"] = year
        if venue is not None:
            payload["venue"] = venue
        if user_id is not None:
            payload["user_id"] = user_id
        if session_id is not None:
            payload["session_id"] = session_id
        return payload


def _resolve_ingest_file(
    file: str | Path | IO[bytes] | tuple[str, IO[bytes], str],
) -> tuple[str, IO[bytes] | bytes, str]:
    """Normalise the ``file=`` argument into an httpx ``files=`` triple."""
    if isinstance(file, (str, Path)):
        path = Path(file).expanduser().resolve()
        suffix = path.suffix.lower()
        ct = {
            ".pdf": "application/pdf",
            ".md": "text/markdown",
            ".markdown": "text/markdown",
            ".txt": "text/plain",
        }.get(suffix, "application/octet-stream")
        return path.name, path.read_bytes(), ct
    if isinstance(file, tuple):
        return file
    name = getattr(file, "name", "upload.bin")
    return name, file, "application/octet-stream"


class AsyncKnowledgeAPI(_KnowledgeMixin):
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(
        self,
        *,
        q: str | None = None,
        tag: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_run_id: str | None = None,
        k: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaperCard]:
        body = await self._client.request_json(
            "GET",
            "/api/knowledge/papers",
            params=self._list_params(
                q=q,
                tag=tag,
                user_id=user_id,
                session_id=session_id,
                source_run_id=source_run_id,
                k=k,
                limit=limit,
                offset=offset,
            ),
        )
        return [PaperCard.model_validate(item) for item in (body or {}).get("items", [])]

    async def get(self, paper_id: str) -> PaperCard:
        body = await self._client.request_json("GET", f"/api/knowledge/papers/{paper_id}")
        return PaperCard.model_validate(body)

    async def create(
        self,
        *,
        title: str,
        paper_id: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        venue: str | None = None,
        abstract: str = "",
        summary: str = "",
        method: str = "",
        findings: str = "",
        tags: list[str] | None = None,
        source_run_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> PaperCard:
        body = await self._client.request_json(
            "POST",
            "/api/knowledge/papers",
            json_body=self._create_payload(
                title=title,
                paper_id=paper_id,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                summary=summary,
                method=method,
                findings=findings,
                tags=tags,
                source_run_id=source_run_id,
                user_id=user_id,
                session_id=session_id,
            ),
        )
        return PaperCard.model_validate(body)

    async def delete(self, paper_id: str) -> None:
        await self._client.request_json("DELETE", f"/api/knowledge/papers/{paper_id}")

    async def link(
        self,
        paper_id: str,
        *,
        target_paper_id: str,
        link_type: Literal["cites", "extends", "compares", "contradicts", "applies"],
        evidence: str = "",
        bidirectional: bool = True,
    ) -> PaperCard:
        body = await self._client.request_json(
            "POST",
            f"/api/knowledge/papers/{paper_id}/links",
            json_body={
                "target_paper_id": target_paper_id,
                "link_type": link_type,
                "evidence": evidence,
                "bidirectional": bidirectional,
            },
        )
        return PaperCard.model_validate(body)

    async def ingest_paper(
        self,
        *,
        file: str | Path | IO[bytes] | tuple[str, IO[bytes], str] | None = None,
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
        venue: str | None = None,
        abstract: str = "",
        summary: str = "",
        method: str = "",
        findings: str = "",
        tags: list[str] | None = None,
        source_kind: SourceKind = "user_upload",
        source_uri: str | None = None,
        body_text: str = "",
        trigger_evolution: bool = True,
        llm_extract: bool = True,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> IngestPaperResponse:
        """Ingest a paper.

        ``file`` (a path, open binary handle, or ``(name, fp, content_type)``
        tuple) takes the multipart path; otherwise the call is sent as
        JSON metadata. ``title`` is required when no ``file`` is given.
        """
        if file is not None:
            name, fp, ct = _resolve_ingest_file(file)
            files = {"file": (name, fp, ct)}
            data = self._ingest_form_data(
                title=title or None,
                authors=authors,
                year=year,
                venue=venue,
                tags=tags,
                source_kind=source_kind,
                source_uri=source_uri,
                trigger_evolution=trigger_evolution,
                llm_extract=llm_extract,
            )
            body = await self._client.request_json(
                "POST", "/api/knowledge/papers/ingest", files=files, data=data
            )
            return IngestPaperResponse.model_validate(body)

        if not title:
            raise ValueError("ingest_paper requires either 'file' or a non-empty 'title'")
        body = await self._client.request_json(
            "POST",
            "/api/knowledge/papers/ingest",
            json_body=self._ingest_json_payload(
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                summary=summary,
                method=method,
                findings=findings,
                tags=tags,
                source_kind=source_kind,
                source_uri=source_uri,
                body_text=body_text,
                trigger_evolution=trigger_evolution,
                llm_extract=llm_extract,
                user_id=user_id,
                session_id=session_id,
            ),
        )
        return IngestPaperResponse.model_validate(body)


class KnowledgeAPI(_KnowledgeMixin):
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(
        self,
        *,
        q: str | None = None,
        tag: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_run_id: str | None = None,
        k: int | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[PaperCard]:
        body = self._client.request_json(
            "GET",
            "/api/knowledge/papers",
            params=self._list_params(
                q=q,
                tag=tag,
                user_id=user_id,
                session_id=session_id,
                source_run_id=source_run_id,
                k=k,
                limit=limit,
                offset=offset,
            ),
        )
        return [PaperCard.model_validate(item) for item in (body or {}).get("items", [])]

    def get(self, paper_id: str) -> PaperCard:
        body = self._client.request_json("GET", f"/api/knowledge/papers/{paper_id}")
        return PaperCard.model_validate(body)

    def create(
        self,
        *,
        title: str,
        paper_id: str | None = None,
        authors: list[str] | None = None,
        year: int | None = None,
        venue: str | None = None,
        abstract: str = "",
        summary: str = "",
        method: str = "",
        findings: str = "",
        tags: list[str] | None = None,
        source_run_id: str | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> PaperCard:
        body = self._client.request_json(
            "POST",
            "/api/knowledge/papers",
            json_body=self._create_payload(
                title=title,
                paper_id=paper_id,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                summary=summary,
                method=method,
                findings=findings,
                tags=tags,
                source_run_id=source_run_id,
                user_id=user_id,
                session_id=session_id,
            ),
        )
        return PaperCard.model_validate(body)

    def delete(self, paper_id: str) -> None:
        self._client.request_json("DELETE", f"/api/knowledge/papers/{paper_id}")

    def link(
        self,
        paper_id: str,
        *,
        target_paper_id: str,
        link_type: Literal["cites", "extends", "compares", "contradicts", "applies"],
        evidence: str = "",
        bidirectional: bool = True,
    ) -> PaperCard:
        body = self._client.request_json(
            "POST",
            f"/api/knowledge/papers/{paper_id}/links",
            json_body={
                "target_paper_id": target_paper_id,
                "link_type": link_type,
                "evidence": evidence,
                "bidirectional": bidirectional,
            },
        )
        return PaperCard.model_validate(body)

    def ingest_paper(
        self,
        *,
        file: str | Path | IO[bytes] | tuple[str, IO[bytes], str] | None = None,
        title: str = "",
        authors: list[str] | None = None,
        year: int | None = None,
        venue: str | None = None,
        abstract: str = "",
        summary: str = "",
        method: str = "",
        findings: str = "",
        tags: list[str] | None = None,
        source_kind: SourceKind = "user_upload",
        source_uri: str | None = None,
        body_text: str = "",
        trigger_evolution: bool = True,
        llm_extract: bool = True,
        user_id: str | None = None,
        session_id: str | None = None,
    ) -> IngestPaperResponse:
        """Synchronous mirror of :meth:`AsyncKnowledgeAPI.ingest_paper`."""
        if file is not None:
            name, fp, ct = _resolve_ingest_file(file)
            files = {"file": (name, fp, ct)}
            data = self._ingest_form_data(
                title=title or None,
                authors=authors,
                year=year,
                venue=venue,
                tags=tags,
                source_kind=source_kind,
                source_uri=source_uri,
                trigger_evolution=trigger_evolution,
                llm_extract=llm_extract,
            )
            body = self._client.request_json(
                "POST", "/api/knowledge/papers/ingest", files=files, data=data
            )
            return IngestPaperResponse.model_validate(body)

        if not title:
            raise ValueError("ingest_paper requires either 'file' or a non-empty 'title'")
        body = self._client.request_json(
            "POST",
            "/api/knowledge/papers/ingest",
            json_body=self._ingest_json_payload(
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                summary=summary,
                method=method,
                findings=findings,
                tags=tags,
                source_kind=source_kind,
                source_uri=source_uri,
                body_text=body_text,
                trigger_evolution=trigger_evolution,
                llm_extract=llm_extract,
                user_id=user_id,
                session_id=session_id,
            ),
        )
        return IngestPaperResponse.model_validate(body)


# ---------------------------------------------------------------------------
# Heuristics
# ---------------------------------------------------------------------------


class _HeuristicsMixin:
    @staticmethod
    def _list_params(
        *,
        domain: HeuristicDomain | None,
        include_frozen: bool,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        return {
            "domain": domain,
            "include_frozen": include_frozen,
            "limit": limit,
            "offset": offset,
        }

    @staticmethod
    def _create_payload(
        *,
        name: str,
        domain: HeuristicDomain,
        description: str,
        trigger_pattern: str,
        strategy: StrategyBlock | dict[str, Any] | None,
        source_query: str,
        source_verdict: HeuristicVerdict,
        source_run_id: str,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "name": name,
            "domain": domain,
            "description": description,
            "trigger_pattern": trigger_pattern,
            "source_query": source_query,
            "source_verdict": source_verdict,
            "source_run_id": source_run_id,
        }
        if strategy is not None:
            payload["strategy"] = (
                strategy.model_dump() if isinstance(strategy, StrategyBlock) else dict(strategy)
            )
        return payload


class AsyncHeuristicsAPI(_HeuristicsMixin):
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def list_all(
        self,
        *,
        domain: HeuristicDomain | None = None,
        include_frozen: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Heuristic]:
        body = await self._client.request_json(
            "GET",
            "/api/heuristics",
            params=self._list_params(
                domain=domain,
                include_frozen=include_frozen,
                limit=limit,
                offset=offset,
            ),
        )
        return [Heuristic.model_validate(item) for item in (body or {}).get("items", [])]

    async def match(
        self,
        query: str,
        *,
        domain: HeuristicDomain | None = None,
        top_k: int = 3,
    ) -> list[Heuristic]:
        body = await self._client.request_json(
            "GET",
            "/api/heuristics/match",
            params={"query": query, "domain": domain, "top_k": top_k},
        )
        return [Heuristic.model_validate(item) for item in (body or {}).get("items", [])]

    async def create(
        self,
        *,
        name: str,
        domain: HeuristicDomain,
        description: str = "",
        trigger_pattern: str = "",
        strategy: StrategyBlock | dict[str, Any] | None = None,
        source_query: str = "",
        source_verdict: HeuristicVerdict = "pass",
        source_run_id: str = "",
    ) -> Heuristic:
        body = await self._client.request_json(
            "POST",
            "/api/heuristics",
            json_body=self._create_payload(
                name=name,
                domain=domain,
                description=description,
                trigger_pattern=trigger_pattern,
                strategy=strategy,
                source_query=source_query,
                source_verdict=source_verdict,
                source_run_id=source_run_id,
            ),
        )
        return Heuristic.model_validate(body)

    async def freeze(self, heuristic_id: str) -> Heuristic:
        body = await self._client.request_json("POST", f"/api/heuristics/{heuristic_id}/freeze")
        return Heuristic.model_validate(body)

    async def unfreeze(self, heuristic_id: str) -> Heuristic:
        body = await self._client.request_json("POST", f"/api/heuristics/{heuristic_id}/unfreeze")
        return Heuristic.model_validate(body)

    async def bump(
        self,
        heuristic_id: str,
        *,
        verdict: HeuristicVerdict = "pass",
    ) -> Heuristic:
        body = await self._client.request_json(
            "POST",
            f"/api/heuristics/{heuristic_id}/bump",
            json_body={"verdict": verdict},
        )
        return Heuristic.model_validate(body)

    async def delete(self, heuristic_id: str) -> None:
        await self._client.request_json("DELETE", f"/api/heuristics/{heuristic_id}")


class HeuristicsAPI(_HeuristicsMixin):
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def list_all(
        self,
        *,
        domain: HeuristicDomain | None = None,
        include_frozen: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Heuristic]:
        body = self._client.request_json(
            "GET",
            "/api/heuristics",
            params=self._list_params(
                domain=domain,
                include_frozen=include_frozen,
                limit=limit,
                offset=offset,
            ),
        )
        return [Heuristic.model_validate(item) for item in (body or {}).get("items", [])]

    def match(
        self,
        query: str,
        *,
        domain: HeuristicDomain | None = None,
        top_k: int = 3,
    ) -> list[Heuristic]:
        body = self._client.request_json(
            "GET",
            "/api/heuristics/match",
            params={"query": query, "domain": domain, "top_k": top_k},
        )
        return [Heuristic.model_validate(item) for item in (body or {}).get("items", [])]

    def create(
        self,
        *,
        name: str,
        domain: HeuristicDomain,
        description: str = "",
        trigger_pattern: str = "",
        strategy: StrategyBlock | dict[str, Any] | None = None,
        source_query: str = "",
        source_verdict: HeuristicVerdict = "pass",
        source_run_id: str = "",
    ) -> Heuristic:
        body = self._client.request_json(
            "POST",
            "/api/heuristics",
            json_body=self._create_payload(
                name=name,
                domain=domain,
                description=description,
                trigger_pattern=trigger_pattern,
                strategy=strategy,
                source_query=source_query,
                source_verdict=source_verdict,
                source_run_id=source_run_id,
            ),
        )
        return Heuristic.model_validate(body)

    def freeze(self, heuristic_id: str) -> Heuristic:
        body = self._client.request_json("POST", f"/api/heuristics/{heuristic_id}/freeze")
        return Heuristic.model_validate(body)

    def unfreeze(self, heuristic_id: str) -> Heuristic:
        body = self._client.request_json("POST", f"/api/heuristics/{heuristic_id}/unfreeze")
        return Heuristic.model_validate(body)

    def bump(
        self,
        heuristic_id: str,
        *,
        verdict: HeuristicVerdict = "pass",
    ) -> Heuristic:
        body = self._client.request_json(
            "POST",
            f"/api/heuristics/{heuristic_id}/bump",
            json_body={"verdict": verdict},
        )
        return Heuristic.model_validate(body)

    def delete(self, heuristic_id: str) -> None:
        self._client.request_json("DELETE", f"/api/heuristics/{heuristic_id}")


# ---------------------------------------------------------------------------
# Memory (stats / reflections / rollback)
# ---------------------------------------------------------------------------


class AsyncMemoryAPI:
    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def stats(self) -> MemoryStats:
        body = await self._client.request_json("GET", "/api/memory/stats")
        return MemoryStats.model_validate(body)

    async def reflections(
        self,
        *,
        type: ReflectionType | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        n: int = 20,
    ) -> list[Reflection]:
        body = await self._client.request_json(
            "GET",
            "/api/memory/reflections",
            params={"type": type, "session_id": session_id, "user_id": user_id, "n": n},
        )
        return [Reflection.model_validate(item) for item in (body or {}).get("items", [])]

    async def append_reflection(
        self,
        content: str,
        *,
        type: ReflectionType = "reflection",
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_run_id: str | None = None,
    ) -> Reflection:
        body = await self._client.request_json(
            "POST",
            "/api/memory/reflections",
            json_body={
                "type": type,
                "content": content,
                "tags": tags or [],
                "user_id": user_id,
                "session_id": session_id,
                "source_run_id": source_run_id,
            },
        )
        return Reflection.model_validate(body)

    async def rollback_run(self, run_id: str) -> RollbackResponse:
        body = await self._client.request_json("POST", f"/api/memory/rollback/{run_id}")
        return RollbackResponse.model_validate(body)


class MemoryAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def stats(self) -> MemoryStats:
        body = self._client.request_json("GET", "/api/memory/stats")
        return MemoryStats.model_validate(body)

    def reflections(
        self,
        *,
        type: ReflectionType | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
        n: int = 20,
    ) -> list[Reflection]:
        body = self._client.request_json(
            "GET",
            "/api/memory/reflections",
            params={"type": type, "session_id": session_id, "user_id": user_id, "n": n},
        )
        return [Reflection.model_validate(item) for item in (body or {}).get("items", [])]

    def append_reflection(
        self,
        content: str,
        *,
        type: ReflectionType = "reflection",
        tags: list[str] | None = None,
        user_id: str | None = None,
        session_id: str | None = None,
        source_run_id: str | None = None,
    ) -> Reflection:
        body = self._client.request_json(
            "POST",
            "/api/memory/reflections",
            json_body={
                "type": type,
                "content": content,
                "tags": tags or [],
                "user_id": user_id,
                "session_id": session_id,
                "source_run_id": source_run_id,
            },
        )
        return Reflection.model_validate(body)

    def rollback_run(self, run_id: str) -> RollbackResponse:
        body = self._client.request_json("POST", f"/api/memory/rollback/{run_id}")
        return RollbackResponse.model_validate(body)


__all__ = [
    "AsyncHeuristicsAPI",
    "AsyncKnowledgeAPI",
    "AsyncMemoryAPI",
    "HeuristicsAPI",
    "KnowledgeAPI",
    "MemoryAPI",
]
