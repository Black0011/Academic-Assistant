"""FastAPI dependencies for auth.

Three dependencies, each composing the next:

* :func:`optional_current_user` — best-effort: returns ``User | None``.
  Always returns ``None`` when ``settings.auth_disabled`` is true. Never
  raises 401. Use when an endpoint *can* be public but wants to attach
  ``user_id`` if the caller is authenticated.

* :func:`current_user` — same as above but *requires* a user when auth
  is enabled. Raises 401 on missing/invalid/expired token. Used by
  protected resources.

* :func:`require_role` — factory that returns a dependency requiring a
  given role (``"admin"``). Composes with :func:`current_user`.

When ``auth_disabled`` is true (the default for local dev) every endpoint
behaves as today and tests see no behavioural change.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from backend.core.app_state import AppState, get_app_state

from .models import User
from .tokens import InvalidTokenError, decode

_BEARER_PREFIX = "bearer "
_ANON = User(id="anon", email="anon@local.dev", display_name="anonymous", role="user")


async def optional_current_user(
    request: Request,
    state: Annotated[AppState, Depends(get_app_state)],
) -> User | None:
    """Best-effort: returns the user if a valid token is present, else None.

    When ``auth_disabled`` is true, always returns ``None`` — call sites
    treat this as "open mode" and use ``user_id`` from the body if any.
    """
    settings = state.settings
    if settings is None or settings.auth_disabled:
        return None

    token = _extract_bearer(request)
    if not token:
        return None

    try:
        claims = decode(settings.secret_key, token)
    except InvalidTokenError:
        return None

    if state.users is None:
        return None
    user = await state.users.by_id(claims.sub)
    if user is None or user.disabled:
        return None
    return user


async def current_user(
    request: Request,
    state: Annotated[AppState, Depends(get_app_state)],
) -> User:
    """Required: 401 unless a valid bearer token is presented.

    In ``auth_disabled`` mode returns a synthetic anonymous user so route
    handlers don't have to special-case ``None``.
    """
    settings = state.settings
    if settings is None or settings.auth_disabled:
        return _ANON

    token = _extract_bearer(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        claims = decode(settings.secret_key, token)
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc) or "invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if state.users is None:
        raise HTTPException(status_code=503, detail="auth subsystem not ready")
    user = await state.users.by_id(claims.sub)
    if user is None or user.disabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return user


def require_role(*roles: str):
    """Dependency factory: 403 unless the current user has one of *roles*."""
    allowed = set(roles)

    async def _checker(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=403, detail="insufficient role")
        return user

    return _checker


def _extract_bearer(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if not header:
        return None
    if header.lower().startswith(_BEARER_PREFIX):
        return header[len(_BEARER_PREFIX) :].strip() or None
    return None


__all__ = ["current_user", "optional_current_user", "require_role"]
