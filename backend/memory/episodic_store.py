"""EpisodicStore — in-process reflections / observations / insights.

The production Postgres-backed variant arrives in M2 stage 2 (§11.3).
For now the in-memory implementation satisfies the protocol end-to-end
and keeps tests hermetic.
"""

from __future__ import annotations

import asyncio

from .models import Reflection


class InMemoryEpisodicStore:
    def __init__(self) -> None:
        self._items: list[Reflection] = []
        self._lock = asyncio.Lock()

    async def append(self, reflection: Reflection) -> None:
        async with self._lock:
            self._items.append(reflection)

    async def recent(
        self,
        *,
        n: int = 3,
        type: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> list[Reflection]:
        items = list(self._items)
        if type is not None:
            items = [r for r in items if r.type == type]
        if session_id is not None:
            items = [r for r in items if r.session_id == session_id]
        if user_id is not None:
            items = [r for r in items if r.user_id == user_id]
        items.sort(key=lambda r: r.created_at, reverse=True)
        return items[: max(0, n)]

    async def rollback_run(self, run_id: str) -> int:
        async with self._lock:
            before = len(self._items)
            self._items[:] = [r for r in self._items if r.source_run_id != run_id]
            return before - len(self._items)

    async def clear(self) -> None:
        async with self._lock:
            self._items.clear()

    async def count(self) -> int:
        return len(self._items)

    # ---- P14.A manual CRUD ---------------------------------------------

    async def get(self, id_: str) -> Reflection | None:
        for r in self._items:
            if r.id == id_:
                return r
        return None

    async def update(
        self,
        id_: str,
        *,
        type: str | None = None,
        content: str | None = None,
        tags: list[str] | None = None,
    ) -> Reflection | None:
        async with self._lock:
            for i, r in enumerate(self._items):
                if r.id != id_:
                    continue
                # ``model_copy(update=...)`` would silently allow any field;
                # restrict to the three the public surface allows so we
                # never leak system-managed fields (id / created_at / *_id)
                # through this path.
                updates: dict = {}
                if type is not None:
                    updates["type"] = type
                if content is not None:
                    updates["content"] = content
                if tags is not None:
                    updates["tags"] = list(tags)
                self._items[i] = r.model_copy(update=updates)
                return self._items[i]
        return None

    async def delete(self, id_: str) -> bool:
        async with self._lock:
            before = len(self._items)
            self._items[:] = [r for r in self._items if r.id != id_]
            return len(self._items) < before

    async def delete_by(
        self,
        *,
        session_id: str | None = None,
        source_run_id: str | None = None,
    ) -> int:
        if session_id is None and source_run_id is None:
            # Refuse the unbounded delete — the only way to wipe the
            # whole store is the explicit ``clear()`` test helper.
            return 0
        async with self._lock:
            before = len(self._items)
            self._items[:] = [
                r
                for r in self._items
                if not _matches_bulk_filter(r, session_id, source_run_id)
            ]
            return before - len(self._items)


def _matches_bulk_filter(
    r: Reflection, session_id: str | None, source_run_id: str | None
) -> bool:
    """Bulk delete is AND-semantics across the two facets: only rows
    matching every supplied facet are removed. Either facet alone is
    fine (caller can wipe by session_id only)."""
    if session_id is not None and r.session_id != session_id:
        return False
    if source_run_id is not None and r.source_run_id != source_run_id:
        return False
    return True


__all__ = ["InMemoryEpisodicStore"]
