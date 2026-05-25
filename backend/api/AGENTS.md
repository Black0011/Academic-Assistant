# backend/api/AGENTS.md

HTTP surface. Each router file under `routers/` is one **resource**.

## Conventions

- Every router file exposes `router: APIRouter` with `prefix="/api/<resource>"`
  and `tags=["<resource>"]`.
- Routers are imported and `app.include_router(...)`-ed in `backend/app.py`.
  The consistency check fails the build if a `routers/<name>.py` file is
  not wired into `app.py`.
- Long-running work returns **202 Accepted** with a `task_id` and pushes to
  the queue. Do not block.
- SSE endpoints use `sse-starlette`'s `EventSourceResponse` and serialise
  events with `Event.to_dict()`.
- All bodies and responses are Pydantic models. No raw dicts on the wire.

## Required wiring (per resource)

```
backend/api/routers/<resource>.py
backend/tests/integration/test_app_<resource>.py    # required (consistency)
```

## File template

```python
"""<resource> API — short purpose statement (≤2 lines)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from backend.core.app_state import AppState, get_app_state

router = APIRouter(prefix="/api/<resource>", tags=["<resource>"])


@router.get("", summary="List …")
async def list_items(state: AppState = Depends(get_app_state)) -> list[…]:
    ...
```

## Don'ts

- Don't reach into `state.memory.knowledge` etc. directly when there's a
  service. Use the service.
- Don't return SQLAlchemy rows. Convert to Pydantic at the boundary.
- Don't add auth checks per-route — middleware in M5.

## M7 routers (delivered)

| Router file                       | Resource          | Notes                                                                                    |
| --------------------------------- | ----------------- | ---------------------------------------------------------------------------------------- |
| `routers/knowledge.py` (extended) | Paper Ingest      | `POST /api/knowledge/papers/ingest` (multipart + JSON). Calls `PaperIngestor`.           |
| `routers/skills.py`               | Skill management  | List/CRUD/`:enable`/`:disable`/`:reload`/`:dry_run`. Writes are admin-only and staged.   |
| `routers/documents.py`            | Knowledge Docs    | Upload, list, chunks, `:reindex`, search (POST `/api/documents/search`). Pairs with `MemoryBundle.documents` (M7.3).   |

## M8 routers (delivered)

| Router file              | Resource     | Notes                                                                                                                                                            |
| ------------------------ | ------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `routers/proposals.py`   | Proposals    | List/CRUD + state machine (`:submit` / `:approve` / `:reject` / `:apply` / `:withdraw`). `:apply` records status only — no file writes. Admin-gated when not in open mode. |
| `routers/planner.py`     | Planner DAG  | `GET /skills_for_compile`, `POST /compile`, `POST /validate`, `POST /execute` (returns `task_id`, workflow `dag`). LLM-driven with heuristic fallback.            |

## P13 surface (delivered)

| Endpoint                                              | Notes                                                                                                                                                                                                                                                                                                                |
| ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `GET /api/skills/graph`                               | New aggregation view. Returns `{nodes, edges, dangling, cycles, generation}`. Edges merge both `compatibility.upstream` and `compatibility.downstream` declarations; `declared_by` ∈ `{source, target, both}`. **MUST be registered before `/{name}`** in the router or it falls into the parametric route and 404s. |
| `POST /api/knowledge/papers` (extended)               | Body now accepts `url`, `field_major`, `field_minor` (all `str \| None`).                                                                                                                                                                                                                                            |
| `PATCH /api/knowledge/papers/{paper_id}` (extended)   | Same three new fields. Clear-out semantics: send empty string (the endpoint uses `exclude_none=True`, so `null` means "no change").                                                                                                                                                                                  |

The `PaperCard` model itself ([`backend/memory/models.py`](../memory/models.py)) gained the same three fields. No data migration required — Pydantic Optional fields default to `None`, so YAML files written before P13 still load. Pinned by `test_yaml_reads_legacy_card_without_new_fields`.

When you add any of the above, follow the existing checklist (section above) — including the matching `backend/tests/integration/test_app_<resource>.py`.

## Adding a router — checklist

1. Create `routers/<resource>.py` with the template above.
2. Add `from .<resource> import router as <resource>_router` in
   `app.py:include_router` calls.
3. Add `from . import <resource>` to `routers/__init__.py`.
4. Create `backend/tests/integration/test_app_<resource>.py` with at least
   one happy-path test.
5. `make consistency`.
