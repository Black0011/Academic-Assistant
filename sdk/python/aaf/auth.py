"""``/api/auth/*`` sub-client."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .models import AuthConfig, PublicUser, TokenResponse

if TYPE_CHECKING:  # pragma: no cover - import-time only
    from .client import AAFClient, AsyncAAFClient


class AsyncAuthAPI:
    """Async version of the auth sub-client."""

    def __init__(self, client: AsyncAAFClient) -> None:
        self._client = client

    async def config(self) -> AuthConfig:
        body = await self._client.request_json("GET", "/api/auth/config")
        return AuthConfig.model_validate(body)

    async def login(self, email: str, password: str) -> TokenResponse:
        body = await self._client.request_json(
            "POST",
            "/api/auth/login",
            json_body={"email": email, "password": password},
        )
        return TokenResponse.model_validate(body)

    async def register(
        self,
        email: str,
        password: str,
        *,
        display_name: str | None = None,
    ) -> TokenResponse:
        payload: dict[str, str] = {"email": email, "password": password}
        if display_name:
            payload["display_name"] = display_name
        body = await self._client.request_json("POST", "/api/auth/register", json_body=payload)
        return TokenResponse.model_validate(body)

    async def me(self) -> PublicUser:
        body = await self._client.request_json("GET", "/api/auth/me")
        return PublicUser.model_validate(body)

    async def logout(self) -> None:
        await self._client.request_json("POST", "/api/auth/logout")
        self._client.set_token(None)


class AuthAPI:
    def __init__(self, client: AAFClient) -> None:
        self._client = client

    def config(self) -> AuthConfig:
        body = self._client.request_json("GET", "/api/auth/config")
        return AuthConfig.model_validate(body)

    def login(self, email: str, password: str) -> TokenResponse:
        body = self._client.request_json(
            "POST",
            "/api/auth/login",
            json_body={"email": email, "password": password},
        )
        return TokenResponse.model_validate(body)

    def register(
        self,
        email: str,
        password: str,
        *,
        display_name: str | None = None,
    ) -> TokenResponse:
        payload: dict[str, str] = {"email": email, "password": password}
        if display_name:
            payload["display_name"] = display_name
        body = self._client.request_json("POST", "/api/auth/register", json_body=payload)
        return TokenResponse.model_validate(body)

    def me(self) -> PublicUser:
        body = self._client.request_json("GET", "/api/auth/me")
        return PublicUser.model_validate(body)

    def logout(self) -> None:
        self._client.request_json("POST", "/api/auth/logout")
        self._client.set_token(None)


__all__ = ["AsyncAuthAPI", "AuthAPI"]
