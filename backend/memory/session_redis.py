"""Redis-backed SessionStore.

Keys laid out as (PLAN §11.5 "hot" tier):

* ``aaf:session:<session_id>`` — JSON blob of :class:`SessionContext`
* ``aaf:user:<user_id>:sessions`` — set of session ids for fast listing

Cold storage (Postgres) ships in a later milestone when we wire FastAPI
lifespan & migrations. Redis alone is enough for real-time agent state.

Construction accepts any ``redis.asyncio.Redis``-compatible client so
tests can pass :class:`fakeredis.aioredis.FakeRedis` without patching.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from backend.core.errors import MemoryNotFound

from .models import SessionContext, SessionMessage


class RedisSessionStore:
    def __init__(self, client: Any, *, namespace: str = "aaf") -> None:
        self._r = client
        self._ns = namespace

    # ---- key helpers ------------------------------------------------

    def _session_key(self, session_id: str) -> str:
        return f"{self._ns}:session:{session_id}"

    def _user_key(self, user_id: str) -> str:
        return f"{self._ns}:user:{user_id}:sessions"

    # ---- protocol ---------------------------------------------------

    async def create(self, session: SessionContext) -> None:
        payload = _dumps(session)
        await self._r.set(self._session_key(session.session_id), payload)
        if session.user_id:
            await self._r.sadd(self._user_key(session.user_id), session.session_id)

    async def get(self, session_id: str) -> SessionContext | None:
        raw = await self._r.get(self._session_key(session_id))
        if raw is None:
            return None
        return _loads(raw)

    async def update(self, session_id: str, **updates: Any) -> SessionContext:
        current = await self.get(session_id)
        if current is None:
            raise MemoryNotFound(f"session not found: {session_id}", store="session", id=session_id)
        # Shallow-merge for `state`, replace for other fields.
        new_state = updates.pop("state", None)
        if new_state is not None:
            merged_state = dict(current.state)
            merged_state.update(new_state)
            updates["state"] = merged_state
        updates.setdefault("updated_at", datetime.now(UTC))
        updated = current.model_copy(update=updates)
        await self._r.set(self._session_key(session_id), _dumps(updated))
        return updated

    async def append_message(self, session_id: str, message: SessionMessage) -> None:
        current = await self.get(session_id)
        if current is None:
            raise MemoryNotFound(f"session not found: {session_id}", store="session", id=session_id)
        current.messages.append(message)
        current.updated_at = datetime.now(UTC)
        await self._r.set(self._session_key(session_id), _dumps(current))

    async def delete(self, session_id: str) -> bool:
        current = await self.get(session_id)
        if current is None:
            return False
        pipe = self._r.pipeline()
        pipe.delete(self._session_key(session_id))
        if current.user_id:
            pipe.srem(self._user_key(current.user_id), session_id)
        await pipe.execute()
        return True

    async def list_for_user(self, user_id: str) -> list[SessionContext]:
        ids = await self._r.smembers(self._user_key(user_id))
        sessions: list[SessionContext] = []
        for raw_id in ids:
            sid = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            s = await self.get(sid)
            if s is not None:
                sessions.append(s)
        sessions.sort(key=lambda s: s.updated_at, reverse=True)
        return sessions


# ---------------------------------------------------------------------------
# (De)serialisation — pydantic handles timestamps in ISO 8601.
# ---------------------------------------------------------------------------


def _dumps(session: SessionContext) -> str:
    return json.dumps(session.model_dump(mode="json"), ensure_ascii=False)


def _loads(raw: Any) -> SessionContext:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return SessionContext.model_validate(json.loads(raw))


__all__ = ["RedisSessionStore"]
