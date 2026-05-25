"""Smoke tests using ``httpx.MockTransport`` so we never touch the network."""

from __future__ import annotations

import json

import httpx
import pytest

from aaf import (
    APIError,
    AsyncAAFClient,
    AuthenticationError,
    NotFoundError,
    parse_sse_block,
)


def _route(handler):
    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_health() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/health"
        return httpx.Response(200, json={"status": "ok"})

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        assert await cli.health() == {"status": "ok"}


@pytest.mark.asyncio
async def test_login_and_token() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/auth/login":
            return httpx.Response(
                200,
                json={
                    "access_token": "tok-123",
                    "expires_in": 3600,
                    "user": {
                        "id": "u1",
                        "email": "a@b.test",
                        "display_name": "alice",
                        "role": "admin",
                        "disabled": False,
                    },
                },
            )
        if request.url.path == "/api/auth/me":
            assert request.headers.get("Authorization") == "Bearer tok-123"
            return httpx.Response(
                200,
                json={
                    "id": "u1",
                    "email": "a@b.test",
                    "display_name": "alice",
                    "role": "admin",
                    "disabled": False,
                },
            )
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        token = await cli.login("a@b.test", "secret")
        assert token == "tok-123"
        me = await cli.auth.me()
        assert me.role == "admin"


@pytest.mark.asyncio
async def test_create_task_and_stream() -> None:
    sse_body = (
        'event: task.start\ndata: {"task_id":"t1","seq":1,"data":{"workflow":"demo"}}\n\n'
        'event: task.end\ndata: {"task_id":"t1","seq":2,"data":{"verdict":"ok"}}\n\n'
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/tasks":
            payload = json.loads(request.content)
            assert payload["workflow"] == "demo"
            return httpx.Response(
                202,
                json={"task_id": "t1", "status": "queued", "workflow": "demo"},
            )
        if request.method == "GET" and request.url.path == "/api/tasks/t1/stream":
            return httpx.Response(
                200,
                text=sse_body,
                headers={"content-type": "text/event-stream"},
            )
        raise AssertionError(f"unexpected {request.method} {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        created = await cli.tasks.create(workflow="demo", query="hello")
        assert created.task_id == "t1"
        events = [e async for e in cli.tasks.stream(created.task_id)]
        assert [e.type for e in events] == ["task.start", "task.end"]


@pytest.mark.asyncio
async def test_404_raises_not_found() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"detail": "task 'missing' not found"})

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        with pytest.raises(NotFoundError) as excinfo:
            await cli.tasks.get("missing")
        assert excinfo.value.status_code == 404
        assert "missing" in (excinfo.value.detail or "")


@pytest.mark.asyncio
async def test_401_raises_auth_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "invalid credentials"})

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        with pytest.raises(AuthenticationError):
            await cli.auth.me()


@pytest.mark.asyncio
async def test_5xx_propagates_as_api_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="busy")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        with pytest.raises(APIError) as excinfo:
            await cli.tasks.list_all()
        assert excinfo.value.status_code == 503


def test_parse_sse_block_basic() -> None:
    block = 'event: task.stage\ndata: {"task_id":"t1","data":{"name":"plan"}}'
    parsed = parse_sse_block(block)
    assert parsed is not None
    assert parsed.type == "task.stage"
    assert parsed.task_id == "t1"
    assert parsed.data == {"name": "plan"}


def test_parse_sse_block_skips_comments() -> None:
    block = ":heartbeat\n"
    assert parse_sse_block(block) is None


@pytest.mark.asyncio
async def test_knowledge_ingest_paper_via_json() -> None:
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/knowledge/papers/ingest"
        seen["content_type"] = request.headers.get("content-type", "")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            201,
            json={
                "card": {
                    "paper_id": "abc123",
                    "title": "Self-Evolving Agents",
                    "authors": ["Alice"],
                    "year": 2024,
                    "tags": ["agent", "memory"],
                    "typed_links": [],
                },
                "evolution": {
                    "paper_id": "abc123",
                    "mode": "heuristic",
                    "typed_links_added": [],
                    "tags_added": ["new-tag"],
                    "neighbors_considered": 1,
                    "reason": "",
                },
                "synthesis": None,
                "extracted": {
                    "method": "heuristic",
                    "extract_ms": 12,
                    "evolve_ms": 5,
                    "preview": "abstract preview…",
                    "source_kind": "manual",
                    "raw_pdf_meta": {},
                },
            },
        )

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        result = await cli.knowledge.ingest_paper(
            title="Self-Evolving Agents",
            authors=["Alice"],
            year=2024,
            tags=["agent", "memory"],
            source_kind="manual",
            trigger_evolution=True,
        )

    assert "application/json" in seen["content_type"]
    assert seen["body"]["title"] == "Self-Evolving Agents"
    assert seen["body"]["trigger_evolution"] is True
    assert result.card.paper_id == "abc123"
    assert result.evolution.mode == "heuristic"
    assert result.extracted.method == "heuristic"


@pytest.mark.asyncio
async def test_knowledge_ingest_paper_via_multipart() -> None:
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["content_type"] = request.headers.get("content-type", "")
        # Multipart bodies contain the filename + form fields.
        body = request.content
        captured["body_excerpt"] = body[:512]
        return httpx.Response(
            201,
            json={
                "card": {
                    "paper_id": "p1",
                    "title": "Uploaded",
                    "authors": [],
                    "year": None,
                    "tags": [],
                    "typed_links": [],
                },
                "evolution": {
                    "paper_id": "p1",
                    "mode": "skip",
                    "typed_links_added": [],
                    "tags_added": [],
                    "neighbors_considered": 0,
                    "reason": "trigger_evolution=false",
                },
                "synthesis": None,
                "extracted": {
                    "method": "metadata_only",
                    "extract_ms": 0,
                    "evolve_ms": 0,
                    "preview": "",
                    "source_kind": "user_upload",
                    "raw_pdf_meta": {},
                },
            },
        )

    import io as _io

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        result = await cli.knowledge.ingest_paper(
            file=("paper.md", _io.BytesIO(b"# hello"), "text/markdown"),
            tags=["agent"],
            trigger_evolution=False,
        )

    assert "multipart/form-data" in captured["content_type"]
    assert b"paper.md" in captured["body_excerpt"]
    assert result.card.title == "Uploaded"


def test_knowledge_ingest_paper_requires_title_or_file() -> None:
    from aaf import KnowledgeAPI

    class _DummyClient:
        def request_json(self, *args: object, **kwargs: object) -> object:
            raise AssertionError("must not call HTTP")

    api = KnowledgeAPI(_DummyClient())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        api.ingest_paper()


# ---------------------------------------------------------------------------
# Skills sub-client (M7.2)
# ---------------------------------------------------------------------------


_SKILL_DETAIL = {
    "name": "greeter",
    "description": "Sample",
    "domain": "meta",
    "triggers": ["greet"],
    "version": "1.0.0",
    "enabled": True,
    "scripts": ["greet"],
    "uses_llm_any": False,
    "last_used_at": None,
    "invocation_count_30d": 0,
    "avg_elapsed_ms": 0.0,
    "version_hash": "sha256:abc",
    "loaded_from": "/skills/greeter",
    "body_md": "---\nname: greeter\n---\n# greeter",
    "scripts_detail": [
        {
            "name": "greet",
            "description": "",
            "requires_network": False,
            "max_duration_s": None,
            "uses_llm": False,
            "args_schema": None,
            "size_bytes": 200,
        }
    ],
}


@pytest.mark.asyncio
async def test_skills_list_and_get() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/skills":
            assert request.url.params.get("include_disabled") in {"True", "true"}
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "greeter",
                            "description": "Sample",
                            "enabled": True,
                            "version_hash": "sha256:abc",
                        }
                    ],
                    "total": 1,
                    "generation": 4,
                },
            )
        if request.url.path == "/api/skills/greeter":
            return httpx.Response(200, json=_SKILL_DETAIL)
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        items = await cli.skills.list_all()
        assert len(items) == 1
        assert items[0].name == "greeter"
        detail = await cli.skills.get("greeter")
        assert detail.body_md.startswith("---")
        assert detail.scripts_detail[0].name == "greet"


@pytest.mark.asyncio
async def test_skills_install_and_dry_run() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/skills":
            seen["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(201, json=_SKILL_DETAIL)
        if request.url.path == "/api/skills/greeter/scripts/greet:dry_run":
            seen["dry_run_body"] = json.loads(request.content.decode("utf-8") or "{}")
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "returncode": 0,
                    "duration_ms": 12.5,
                    "timed_out": False,
                    "stdout": '{"hello":"ada"}',
                    "stderr": "",
                },
            )
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        detail = await cli.skills.install(
            {
                "name": "greeter",
                "body_md": "---\nname: greeter\n---\n# greeter",
                "scripts": [{"name": "greet", "content": "print('hi')\n"}],
            }
        )
        assert detail.name == "greeter"

        dry = await cli.skills.dry_run("greeter", "greet", {"name": "ada"})
        assert dry.ok is True
        assert dry.returncode == 0

    assert seen["body"]["name"] == "greeter"
    assert seen["dry_run_body"] == {"name": "ada"}


# ---------------------------------------------------------------------------
# Documents (M7.3)
# ---------------------------------------------------------------------------


_DOC_PAYLOAD = {
    "doc_id": "d-001",
    "title": "RAG primer",
    "source_kind": "note",
    "summary": "intro",
    "raw_text": "# RAG primer\nIntro body.",
    "tags": ["rag"],
    "chunk_ids": ["d-001#0000"],
    "bytes": 32,
}


@pytest.mark.asyncio
async def test_documents_ingest_and_search() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/documents/ingest":
            seen["body"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                201,
                json={
                    "document": _DOC_PAYLOAD,
                    "chunks_indexed": 1,
                    "indexer_ms": 7,
                },
            )
        if request.url.path == "/api/documents/search":
            seen["search"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "chunk_id": "d-001#0000",
                            "doc_id": "d-001",
                            "doc_title": "RAG primer",
                            "text": "Intro body.",
                            "score": 0.93,
                            "section_path": ["RAG primer"],
                            "tags": ["rag"],
                        }
                    ],
                    "total": 1,
                },
            )
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        result = await cli.documents.ingest_text(
            title="RAG primer",
            raw_text="# RAG primer\nIntro body.",
            tags=["rag"],
        )
        assert result.document.doc_id == "d-001"
        assert result.chunks_indexed == 1

        hits = await cli.documents.search("rag retrieval", top_k=3)
        assert hits and hits[0].score > 0.5

    assert seen["body"]["title"] == "RAG primer"
    assert seen["search"]["q"] == "rag retrieval"


@pytest.mark.asyncio
async def test_documents_list_get_and_delete() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/documents":
            return httpx.Response(200, json={"items": [_DOC_PAYLOAD], "total": 1})
        if request.method == "GET" and request.url.path == "/api/documents/d-001":
            return httpx.Response(200, json=_DOC_PAYLOAD)
        if request.method == "DELETE" and request.url.path == "/api/documents/d-001":
            return httpx.Response(204)
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        items = await cli.documents.list_all()
        assert len(items) == 1 and items[0].title == "RAG primer"
        doc = await cli.documents.get("d-001")
        assert doc.doc_id == "d-001"
        await cli.documents.delete("d-001")


# ---------------------------------------------------------------------------
# Proposals (M8.1)
# ---------------------------------------------------------------------------


_PROPOSAL_PAYLOAD = {
    "proposal_id": "abc123",
    "title": "Add memory exporter",
    "summary": "expose recall stage",
    "motivation": "let CLI dump bundle.snapshot()",
    "risk_level": "low",
    "target_paths": ["skills/aaf-memory-exporter/SKILL.md"],
    "diff": "diff --git a/x b/x",
    "status": "draft",
    "proposer_id": "u1",
    "proposer_kind": "human",
    "tags": ["memory"],
    "audit_log": [
        {"timestamp": "2026-01-01T00:00:00Z", "actor": "u1", "action": "create"}
    ],
}


@pytest.mark.asyncio
async def test_proposals_create_and_lifecycle() -> None:
    seen: dict[str, object] = {}
    state: dict[str, object] = {"status": "draft", "audit": list(_PROPOSAL_PAYLOAD["audit_log"])}

    def _snapshot() -> dict[str, object]:
        snap = dict(_PROPOSAL_PAYLOAD)
        snap["status"] = state["status"]
        snap["audit_log"] = list(state["audit"])  # type: ignore[arg-type]
        return snap

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/proposals":
            seen["create"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(201, json=_snapshot())
        if request.method == "POST" and path == "/api/proposals/abc123:submit":
            state["status"] = "pending"
            audit = list(state["audit"])  # type: ignore[arg-type]
            audit.append(
                {"timestamp": "2026-01-01T01:00:00Z", "actor": "u1", "action": "submit"}
            )
            state["audit"] = audit
            return httpx.Response(200, json=_snapshot())
        if request.method == "POST" and path == "/api/proposals/abc123:approve":
            state["status"] = "approved"
            audit = list(state["audit"])  # type: ignore[arg-type]
            audit.append(
                {
                    "timestamp": "2026-01-01T02:00:00Z",
                    "actor": "admin",
                    "action": "approve",
                }
            )
            state["audit"] = audit
            return httpx.Response(200, json=_snapshot())
        if request.method == "POST" and path == "/api/proposals/abc123:apply":
            state["status"] = "applied"
            audit = list(state["audit"])  # type: ignore[arg-type]
            audit.append(
                {
                    "timestamp": "2026-01-01T03:00:00Z",
                    "actor": "admin",
                    "action": "apply",
                }
            )
            state["audit"] = audit
            return httpx.Response(200, json=_snapshot())
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        proposal = await cli.proposals.create(
            title="Add memory exporter",
            summary="expose recall stage",
            motivation="let CLI dump bundle.snapshot()",
            target_paths=["skills/aaf-memory-exporter/SKILL.md"],
            tags=["memory"],
            proposer_id="u1",
        )
        assert proposal.status == "draft"
        submitted = await cli.proposals.submit("abc123", notes="ready")
        assert submitted.status == "pending"
        approved = await cli.proposals.approve("abc123", notes="LGTM")
        assert approved.status == "approved"
        applied = await cli.proposals.apply("abc123")
        assert applied.status == "applied"
    assert seen["create"]["title"] == "Add memory exporter"


@pytest.mark.asyncio
async def test_proposals_list_filters() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/proposals":
            assert request.url.params.get("status") == "pending"
            return httpx.Response(
                200, json={"items": [_PROPOSAL_PAYLOAD], "total": 1}
            )
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        page = await cli.proposals.list_all(status="pending")
        assert page.total == 1


# ---------------------------------------------------------------------------
# Planner (M8.2)
# ---------------------------------------------------------------------------


_PLAN_PAYLOAD = {
    "plan_id": "p-001",
    "query": "transformers",
    "domain": "",
    "rationale": "search arxiv, summarise",
    "estimated_steps": 3,
    "llm_provider": "mock",
    "nodes": [
        {"id": "a", "kind": "memory.read", "args": {"query": "transformers"}},
        {
            "id": "b",
            "kind": "tool",
            "name": "arxiv__search",
            "args": {"q": "transformers"},
            "depends_on": ["a"],
        },
        {"id": "c", "kind": "llm", "depends_on": ["b"], "description": "summarise"},
    ],
}


@pytest.mark.asyncio
async def test_planner_compile_validate_execute() -> None:
    seen: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "POST" and path == "/api/planner/compile":
            seen["compile"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json=_PLAN_PAYLOAD)
        if request.method == "POST" and path == "/api/planner/validate":
            seen["validate"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(200, json={"ok": True, "errors": [], "warnings": []})
        if request.method == "POST" and path == "/api/planner/execute":
            seen["execute"] = json.loads(request.content.decode("utf-8"))
            return httpx.Response(
                202,
                json={
                    "task_id": "t1",
                    "status": "queued",
                    "workflow": "dag",
                    "plan_id": "p-001",
                    "node_count": 3,
                },
            )
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        plan = await cli.planner.compile(query="transformers")
        assert plan.plan_id == "p-001"
        assert len(plan.nodes) == 3
        validation = await cli.planner.validate(plan)
        assert validation.ok is True
        executed = await cli.planner.execute(plan, params={"k": "v"})
        assert executed.task_id == "t1"
        assert executed.workflow == "dag"

    assert seen["compile"]["query"] == "transformers"
    assert seen["validate"]["plan"]["plan_id"] == "p-001"
    assert seen["execute"]["params"] == {"k": "v"}


@pytest.mark.asyncio
async def test_planner_skills_for_compile() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/planner/skills_for_compile":
            return httpx.Response(
                200,
                json={
                    "skills": [
                        {
                            "name": "aaf-memory-exporter",
                            "description": "x",
                            "domain": "memory",
                            "triggers": ["dump"],
                            "invocation_modes": ["script"],
                        }
                    ],
                    "tools": [
                        {
                            "name": "arxiv__search",
                            "description": "search arxiv",
                            "parameters": {"type": "object"},
                        }
                    ],
                },
            )
        raise AssertionError(f"unexpected {request.url}")

    async with AsyncAAFClient("http://t.local", transport=_route(handler)) as cli:
        catalogue = await cli.planner.skills_for_compile()
        assert {s.name for s in catalogue.skills} == {"aaf-memory-exporter"}
        assert {t.name for t in catalogue.tools} == {"arxiv__search"}
