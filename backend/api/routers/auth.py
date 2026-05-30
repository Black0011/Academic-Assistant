"""Authentication API.

Endpoints:

* ``POST /api/auth/login``    — exchange ``email + password`` for a JWT.
* ``GET  /api/auth/me``       — current user (or 401 if no/invalid token).
* ``POST /api/auth/register`` — only when ``settings.auth_allow_signup``.
* ``POST /api/auth/logout``   — no-op for stateless JWT (frontend drops it).

When ``settings.auth_disabled`` is true the login/register endpoints
return 503; ``/me`` answers with the synthetic anonymous user. The frontend
uses the ``GET /api/auth/config`` endpoint to discover whether auth is on.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from backend.core.app_state import AppState, get_app_state
from backend.core.auth import (
    InMemoryUserStore,
    LoginInput,
    PublicUser,
    RegisterInput,
    TokenResponse,
    User,
    UserRole,
    UserStore,
    YamlUserStore,
    current_user,
    hash_password,
    issue,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class AuthConfig(BaseModel):
    """Public auth configuration. Frontend reads this on boot to decide
    whether to show the login screen or skip it."""

    enabled: bool
    allow_signup: bool


@router.get("/config", response_model=AuthConfig, summary="Public auth feature flags")
async def auth_config(state: Annotated[AppState, Depends(get_app_state)]) -> AuthConfig:
    settings = state.settings
    if settings is None:
        return AuthConfig(enabled=False, allow_signup=False)
    return AuthConfig(
        enabled=not settings.auth_disabled,
        allow_signup=(not settings.auth_disabled) and settings.auth_allow_signup,
    )


@router.post("/login", response_model=TokenResponse, summary="Issue a JWT")
async def login(
    body: LoginInput,
    state: Annotated[AppState, Depends(get_app_state)],
) -> TokenResponse:
    settings = state.settings
    if settings is None or settings.auth_disabled:
        raise HTTPException(status_code=503, detail="auth is disabled on this server")

    users = _require_user_store(state)
    user = await users.by_email(str(body.email))
    if user is None or user.disabled or not verify_password(body.password, user.password_hash):
        # Single error keeps email-existence side-channel closed.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = issue(
        settings.secret_key,
        user_id=user.id,
        email=str(user.email),
        role=user.role,
        ttl_s=settings.jwt_expire_seconds,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_seconds,
        user=user.public(),
    )


@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    summary="Sign up a new user (only when allow_signup is true)",
)
async def register(
    body: RegisterInput,
    state: Annotated[AppState, Depends(get_app_state)],
) -> TokenResponse:
    settings = state.settings
    if settings is None or settings.auth_disabled:
        raise HTTPException(status_code=503, detail="auth is disabled on this server")
    if not settings.auth_allow_signup:
        raise HTTPException(status_code=403, detail="signup is disabled")

    users = _require_user_store(state)
    if await users.by_email(str(body.email)) is not None:
        raise HTTPException(status_code=409, detail="email already registered")

    # First-ever user becomes admin so a fresh deployment has a way in.
    role: UserRole = "admin" if (await users.count() == 0) else "user"
    user = User(
        id="",  # store assigns a fresh id
        email=body.email,
        display_name=body.display_name or str(body.email).split("@", 1)[0],
        role=role,
        password_hash=hash_password(body.password),
    )
    saved = await users.create(user)
    token = issue(
        settings.secret_key,
        user_id=saved.id,
        email=str(saved.email),
        role=saved.role,
        ttl_s=settings.jwt_expire_seconds,
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expire_seconds,
        user=saved.public(),
    )


@router.get("/me", response_model=PublicUser, summary="Current authenticated user")
async def me(user: Annotated[User, Depends(current_user)]) -> PublicUser:
    return user.public()


@router.post("/logout", status_code=204, summary="Stateless logout (client drops the token)")
async def logout() -> Response:
    # Stateless JWT: nothing to revoke server-side without a denylist.
    # The frontend clears its stored token and re-routes to /login.
    return Response(status_code=204)


def _require_user_store(state: AppState) -> UserStore:
    if state.users is None:
        # Tests sometimes don't pre-wire a UserStore. We attach a fresh
        # in-memory store lazily so the route stays observable instead of
        # 500-ing on a None deref.
        store = InMemoryUserStore()
        state.users = store
        return store
    return state.users


# YamlUserStore is re-exported here so `app.py` can import everything
# auth-related from a single module.
__all__ = ["YamlUserStore", "router"]
