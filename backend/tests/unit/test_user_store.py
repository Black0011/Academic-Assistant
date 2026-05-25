"""Tests for the in-memory and YAML user stores."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.core.auth import InMemoryUserStore, User, YamlUserStore, hash_password


def _make_user(email: str = "alice@example.com") -> User:
    return User(
        id="",
        email=email,
        display_name="Alice",
        password_hash=hash_password("hunter22"),
    )


# ---------------------------------------------------------------------------
# InMemoryUserStore
# ---------------------------------------------------------------------------


async def test_inmemory_store_create_and_lookup():
    store = InMemoryUserStore()
    await store.init()
    user = await store.create(_make_user())
    assert user.id and user.created_at_epoch_s

    by_email = await store.by_email("alice@example.com")
    by_id = await store.by_id(user.id)
    assert by_email and by_id and by_email.id == by_id.id == user.id


async def test_inmemory_store_email_is_normalised():
    store = InMemoryUserStore()
    await store.create(_make_user("Mixed@Case.com"))
    assert (await store.by_email("mixed@case.com")) is not None
    assert (await store.by_email("MIXED@case.COM")) is not None


async def test_inmemory_store_rejects_duplicate_email():
    store = InMemoryUserStore()
    await store.create(_make_user())
    with pytest.raises(ValueError):
        await store.create(_make_user())


# ---------------------------------------------------------------------------
# YamlUserStore
# ---------------------------------------------------------------------------


async def test_yaml_store_persists_across_init(tmp_path: Path):
    store = YamlUserStore(tmp_path)
    await store.init()
    user = await store.create(_make_user())

    # New store instance reads the same directory.
    other = YamlUserStore(tmp_path)
    await other.init()
    found = await other.by_email("alice@example.com")
    assert found and found.id == user.id and found.role == "user"


async def test_yaml_store_count_and_listing(tmp_path: Path):
    store = YamlUserStore(tmp_path)
    await store.init()
    await store.create(_make_user("a@x.co"))
    await store.create(_make_user("b@x.co"))
    assert await store.count() == 2
    emails = sorted(u.email for u in await store.list_all())
    assert emails == ["a@x.co", "b@x.co"]
