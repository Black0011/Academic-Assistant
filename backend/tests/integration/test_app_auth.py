"""HTTP integration tests for `/api/auth`.

Two modes are exercised side-by-side:

* **disabled** (`auth_disabled=True`, default) — login/register return
  503 and `/me` answers with the synthetic anonymous user. This is the
  zero-config local-dev path; existing endpoints must not require any
  token.
* **enabled** (`auth_disabled=False`) — login + me happy-path, missing
  token → 401, expired/invalid token → 401, optional signup gate honoured.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from backend.app import create_app
from backend.core.app_state import AppState
from backend.core.auth import InMemoryUserStore, User, hash_password, issue
from backend.settings import Settings


def _build_state(
    *,
    auth_disabled: bool,
    allow_signup: bool = False,
    secret_key: str = "test-secret",
    jwt_expire_seconds: int = 3600,
) -> tuple[AppState, InMemoryUserStore]:
    settings = Settings(
        aaf_secret_key=secret_key,  # type: ignore[call-arg]
        auth_disabled=auth_disabled,
        auth_allow_signup=allow_signup,
        jwt_expire_seconds=jwt_expire_seconds,
    )
    users = InMemoryUserStore()
    state = AppState(settings=settings, users=users)
    return state, users


async def _client(state: AppState) -> AsyncClient:
    app = create_app(state=state)
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://testserver")


# ---------------------------------------------------------------------------
# Auth disabled (default mode)
# ---------------------------------------------------------------------------


async def test_disabled_login_returns_503():
    state, _ = _build_state(auth_disabled=True)
    async with await _client(state) as http:
        r = await http.post(
            "/api/auth/login",
            json={"email": "anyone@example.com", "password": "x"},
        )
    assert r.status_code == 503


async def test_disabled_me_returns_anonymous_user():
    state, _ = _build_state(auth_disabled=True)
    async with await _client(state) as http:
        r = await http.get("/api/auth/me")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "anon"
    assert body["display_name"] == "anonymous"


async def test_disabled_config_reports_off():
    state, _ = _build_state(auth_disabled=True, allow_signup=True)
    async with await _client(state) as http:
        r = await http.get("/api/auth/config")
    assert r.status_code == 200
    assert r.json() == {"enabled": False, "allow_signup": False}


# ---------------------------------------------------------------------------
# Auth enabled — login / me / errors
# ---------------------------------------------------------------------------


async def test_enabled_login_happy_path_then_me():
    state, users = _build_state(auth_disabled=False)
    await users.init()
    await users.create(
        User(
            id="",
            email="alice@example.com",
            display_name="Alice",
            password_hash=hash_password("hunter22"),
        )
    )

    async with await _client(state) as http:
        # /me without a token must 401 in enabled mode
        r0 = await http.get("/api/auth/me")
        assert r0.status_code == 401

        r = await http.post(
            "/api/auth/login",
            json={"email": "alice@example.com", "password": "hunter22"},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["token_type"] == "bearer"
        assert body["expires_in"] == 3600
        assert body["user"]["email"] == "alice@example.com"

        token = body["access_token"]
        me = await http.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["email"] == "alice@example.com"


async def test_enabled_login_wrong_password_is_401():
    state, users = _build_state(auth_disabled=False)
    await users.init()
    await users.create(User(id="", email="bob@x.co", password_hash=hash_password("rightpass1")))
    async with await _client(state) as http:
        r = await http.post(
            "/api/auth/login",
            json={"email": "bob@x.co", "password": "wrong"},
        )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


async def test_enabled_login_unknown_email_is_401_with_same_message():
    """No email-existence side-channel."""
    state, users = _build_state(auth_disabled=False)
    await users.init()
    async with await _client(state) as http:
        r = await http.post(
            "/api/auth/login",
            json={"email": "ghost@x.co", "password": "anything"},
        )
    assert r.status_code == 401
    assert r.json()["detail"] == "invalid credentials"


async def test_enabled_invalid_token_is_401():
    state, users = _build_state(auth_disabled=False)
    await users.init()
    async with await _client(state) as http:
        r = await http.get("/api/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert r.status_code == 401


async def test_enabled_token_signed_with_other_secret_is_401():
    state, users = _build_state(auth_disabled=False)
    await users.init()
    user = await users.create(User(id="", email="c@x.co", password_hash=hash_password("xyzxyzxy")))
    forged = issue("OTHER-SECRET", user_id=user.id, email=str(user.email))
    async with await _client(state) as http:
        r = await http.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401


async def test_enabled_token_for_unknown_user_is_401():
    state, users = _build_state(auth_disabled=False)
    await users.init()
    token = issue("test-secret", user_id="u-does-not-exist", email="ghost@x.co")
    async with await _client(state) as http:
        r = await http.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Sign-up gate
# ---------------------------------------------------------------------------


async def test_enabled_signup_disabled_returns_403():
    state, users = _build_state(auth_disabled=False, allow_signup=False)
    await users.init()
    async with await _client(state) as http:
        r = await http.post(
            "/api/auth/register",
            json={"email": "new@x.co", "password": "longenough1"},
        )
    assert r.status_code == 403


async def test_enabled_signup_allowed_first_user_is_admin():
    state, users = _build_state(auth_disabled=False, allow_signup=True)
    await users.init()
    async with await _client(state) as http:
        r1 = await http.post(
            "/api/auth/register",
            json={"email": "first@x.co", "password": "longenough1"},
        )
        assert r1.status_code == 201
        body = r1.json()
        assert body["user"]["role"] == "admin"

        # Second user is plain `user`
        r2 = await http.post(
            "/api/auth/register",
            json={"email": "second@x.co", "password": "longenough1"},
        )
        assert r2.status_code == 201
        assert r2.json()["user"]["role"] == "user"

        # Duplicate email → 409
        r3 = await http.post(
            "/api/auth/register",
            json={"email": "second@x.co", "password": "longenough1"},
        )
        assert r3.status_code == 409


async def test_logout_is_204():
    state, _ = _build_state(auth_disabled=False)
    async with await _client(state) as http:
        r = await http.post("/api/auth/logout")
    assert r.status_code == 204


# ---------------------------------------------------------------------------
# Existing endpoints stay open in disabled mode
# ---------------------------------------------------------------------------


async def test_disabled_mode_keeps_other_endpoints_open():
    """Smoke-check: /api/health works without a token when auth is off."""
    state, _ = _build_state(auth_disabled=True)
    async with await _client(state) as http:
        r = await http.get("/api/health")
    assert r.status_code == 200
