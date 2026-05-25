"""User store implementations.

Two concrete stores ship out of the box:

* :class:`InMemoryUserStore` — for tests and ephemeral demos.
* :class:`YamlUserStore` — single-file durable store. Each user lives in
  ``<root>/<user-id>.yaml``. Good enough for "private server, ≤ a few
  dozen users". Beyond that, replace with a SQL-backed implementation
  (subclass :class:`UserStore`).

The store interface is intentionally tiny — auth is the only consumer
and we don't want to grow it into a generic ORM.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Protocol, runtime_checkable

import yaml

from .models import User


@runtime_checkable
class UserStore(Protocol):
    async def init(self) -> None: ...
    async def by_email(self, email: str) -> User | None: ...
    async def by_id(self, user_id: str) -> User | None: ...
    async def create(self, user: User) -> User: ...
    async def list_all(self) -> list[User]: ...
    async def count(self) -> int: ...
    async def close(self) -> None: ...


class _Base:
    @staticmethod
    def _normalise_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _new_id() -> str:
        return f"u-{uuid.uuid4().hex[:12]}"


class InMemoryUserStore(_Base):
    """Process-local store. Resets on restart."""

    def __init__(self) -> None:
        self._by_id: dict[str, User] = {}
        self._email_to_id: dict[str, str] = {}

    async def init(self) -> None:  # pragma: no cover - trivial
        return

    async def by_email(self, email: str) -> User | None:
        uid = self._email_to_id.get(self._normalise_email(email))
        return self._by_id.get(uid) if uid else None

    async def by_id(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    async def create(self, user: User) -> User:
        email = self._normalise_email(str(user.email))
        if email in self._email_to_id:
            raise ValueError(f"user already exists: {email}")
        record = user.model_copy(
            update={
                "id": user.id or self._new_id(),
                "created_at_epoch_s": user.created_at_epoch_s or time.time(),
            }
        )
        self._by_id[record.id] = record
        self._email_to_id[email] = record.id
        return record

    async def list_all(self) -> list[User]:
        return list(self._by_id.values())

    async def count(self) -> int:
        return len(self._by_id)

    async def close(self) -> None:  # pragma: no cover - trivial
        return


class YamlUserStore(_Base):
    """One-file-per-user YAML store under ``root``.

    Concurrency notes: tiny optimistic store — last-writer-wins on the
    same email (rare for this deployment shape). If you need multi-node
    auth, swap for a SQL-backed UserStore.
    """

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._cache: dict[str, User] = {}
        self._email_to_id: dict[str, str] = {}

    async def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for path in self.root.glob("*.yaml"):
            try:
                payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            except yaml.YAMLError:
                continue
            try:
                user = User.model_validate(payload)
            except Exception:
                continue
            self._cache[user.id] = user
            self._email_to_id[self._normalise_email(str(user.email))] = user.id

    async def by_email(self, email: str) -> User | None:
        uid = self._email_to_id.get(self._normalise_email(email))
        return self._cache.get(uid) if uid else None

    async def by_id(self, user_id: str) -> User | None:
        return self._cache.get(user_id)

    async def create(self, user: User) -> User:
        email = self._normalise_email(str(user.email))
        if email in self._email_to_id:
            raise ValueError(f"user already exists: {email}")
        record = user.model_copy(
            update={
                "id": user.id or self._new_id(),
                "created_at_epoch_s": user.created_at_epoch_s or time.time(),
            }
        )
        self._cache[record.id] = record
        self._email_to_id[email] = record.id
        path = self.root / f"{record.id}.yaml"
        path.write_text(
            yaml.safe_dump(record.model_dump(mode="json"), sort_keys=True), encoding="utf-8"
        )
        return record

    async def list_all(self) -> list[User]:
        return list(self._cache.values())

    async def count(self) -> int:
        return len(self._cache)

    async def close(self) -> None:  # pragma: no cover - trivial
        return


__all__ = ["InMemoryUserStore", "UserStore", "YamlUserStore"]
