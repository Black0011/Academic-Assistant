---
name: aaf-backend-api
description: >-
  Conventions for writing FastAPI routes, Pydantic schemas, SSE streams, and
  error handling in AAF. Load this skill whenever adding or modifying files
  under backend/api/.
domain: engineering
triggers:
  - add api
  - new endpoint
  - fastapi route
  - sse
  - backend/api
version: "1.0.0"
---

# AAF Backend API — Conventions

## 1. Versioning and prefixes

- All API routes live under `/api/v1/`.
- `/api/v1/health`, `/api/v1/health/ready` are special — no auth, no rate limits.
- SSE endpoints follow `/api/v1/tasks/{id}/stream` — NOT under a `/stream/` subpath.

## 2. Router layout

One router per resource, one file per router:

```
backend/api/routers/
├── research.py   → POST /research
├── write.py
├── revise.py
├── rebuttal.py
├── survey.py
├── memory.py     → /memory/* (knowledge / heuristics / sessions)
├── skills.py     → /skills
├── rules.py      → /rules
├── models.py     → /models/providers, /models/usage
├── tasks.py      → /tasks/*
├── auth.py
└── health.py
```

Every router:
- `router = APIRouter(prefix="/<resource>", tags=["<resource>"])`
- Imports its Pydantic schemas from `backend/api/schemas/<resource>.py`
- Imports dependencies (`get_db`, `get_llm`, `get_current_user`, `get_workflow_runner`) from `backend/api/deps.py`

## 3. Pydantic schemas

- Request model: `{ResourceAction}Request` (e.g. `ResearchRequest`).
- Response model: `{ResourceAction}Response`.
- Always set `model_config = ConfigDict(extra="forbid")` on request models.
- Enum values use lowercase strings.
- Never return raw SQLAlchemy models; always map through a response schema.
- Dates always ISO 8601 UTC with `Z` suffix (let Pydantic handle it via `datetime`).

## 4. Starting a workflow: the universal pattern

Every workflow endpoint (`/research`, `/write`, `/revise`, …) follows the exact same shape:

```python
@router.post("", response_model=TaskEnqueuedResponse, status_code=202)
async def start(
    req: ResearchRequest,
    bg: BackgroundTasks,
    runner: Annotated[WorkflowRunner, Depends(get_workflow_runner)],
    user:   Annotated[User, Depends(get_current_user)],
) -> TaskEnqueuedResponse:
    task_id = await runner.enqueue(
        workflow="research",
        input=req.model_dump(),
        user_id=user.id,
    )
    return TaskEnqueuedResponse(task_id=task_id)
```

**Never** run the workflow synchronously inside the route — always enqueue to ARQ and return 202 + `task_id`.

## 5. SSE contract

Use `sse_starlette.EventSourceResponse`. Event stream follows `PLAN.md` §23.5.

```python
@router.get("/tasks/{task_id}/stream")
async def stream(task_id: str, user: Annotated[User, Depends(get_current_user)]):
    async def gen():
        async for event in subscribe(task_id):
            yield {"event": event.type, "data": event.model_dump_json()}
    return EventSourceResponse(gen(), media_type="text/event-stream")
```

- Set `Cache-Control: no-cache` (EventSourceResponse does this).
- Heartbeat every 15s via `yield {"event": "ping", "data": ""}` so intermediate proxies don't drop the connection.
- Close connection on `task.finished` / `task.error` / `task.cancelled`.

## 6. Error handling

- Raise `AAFError` subclasses; the global exception handler in `backend/api/errors.py` translates to RFC 7807 Problem Details JSON.
- Never return raw `{"error": ...}` dicts.
- 422 only for request-body validation (Pydantic handles automatically).

Example:
```python
if not memory.knowledge.exists(id):
    raise MemoryNotFound(id=id)
```

## 7. Auth

- Use `Depends(get_current_user)`. When `AUTH_DISABLED=true`, `get_current_user` returns a fixed `User(id="anonymous")`.
- Routes that truly need no auth (`health`) declare `dependencies=[]` on the router.
- Admin-only routes declare `Depends(require_admin)`.

## 8. OpenAPI

- Every route has a one-line `summary="..."`.
- Every response model has example(s) via `json_schema_extra`.
- Tags match the resource name exactly so Swagger groups correctly.

## 9. Pagination

For list endpoints:

```
GET /memory/knowledge?q=...&limit=20&cursor=<opaque>
```

Return:
```json
{ "items": [...], "next_cursor": "..." | null }
```

Never use page-number pagination.

## 10. Testing

- `backend/tests/integration/api/test_<router>.py` per router.
- Use FastAPI `TestClient` + `MockLLMProvider` + `tmp_path`-backed stores.
- Assert both 2xx happy path and at least one 4xx edge case per endpoint.

## 11. Adding a new endpoint — checklist

- [ ] Schemas in `backend/api/schemas/<resource>.py`
- [ ] Router file exists and is included in `backend/api/__init__.py`
- [ ] `PLAN.md` §13.2 table updated
- [ ] OpenAPI summary + examples
- [ ] Error cases raise `AAFError` subclasses
- [ ] At least one integration test
