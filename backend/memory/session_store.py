"""SessionStore — multi-turn conversation contexts.

Redis hot + Postgres cold arrive in M2 stage 2. The in-memory variant
below is the source of truth for the protocol contract.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

from backend.core.errors import MemoryNotFound

from .models import SessionContext, SessionMessage


class InMemorySessionStore:
    def __init__(self) -> None:
        self._items: dict[str, SessionContext] = {}
        self._lock = asyncio.Lock()

    async def create(self, session: SessionContext) -> None:
        async with self._lock:
            self._items[session.session_id] = session

    async def get(self, session_id: str) -> SessionContext | None:
        return self._items.get(session_id)

    async def update(self, session_id: str, **updates: Any) -> SessionContext:
        async with self._lock:
            s = self._items.get(session_id)
            if s is None:
                raise MemoryNotFound(
                    f"session not found: {session_id}", store="session", id=session_id
                )
            # Shallow-merge for `state`, straight replace for other fields.
            new_state = updates.pop("state", None)
            if new_state is not None:
                merged_state = dict(s.state)
                merged_state.update(new_state)
                updates["state"] = merged_state
            updates.setdefault("updated_at", datetime.now(UTC))
            updated = s.model_copy(update=updates)
            self._items[session_id] = updated
            return updated

    async def append_message(self, session_id: str, message: SessionMessage) -> None:
        async with self._lock:
            s = self._items.get(session_id)
            if s is None:
                raise MemoryNotFound(
                    f"session not found: {session_id}", store="session", id=session_id
                )
            s.messages.append(message)
            s.updated_at = datetime.now(UTC)

    async def delete(self, session_id: str) -> bool:
        async with self._lock:
            return self._items.pop(session_id, None) is not None

    async def list_for_user(self, user_id: str) -> list[SessionContext]:
        items = [s for s in self._items.values() if s.user_id == user_id]
        items.sort(key=lambda s: s.updated_at, reverse=True)
        return items


__all__ = ["InMemorySessionStore"]
