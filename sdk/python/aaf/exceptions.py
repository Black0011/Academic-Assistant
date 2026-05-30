"""Exception hierarchy for the AAF SDK.

We mirror just enough of the backend's :class:`AAFError` taxonomy to give
SDK users actionable handles. The HTTP status code and response body are
always preserved for caller logging.
"""

from __future__ import annotations

from typing import Any


class AAFClientError(Exception):
    """Base for every error raised by the SDK."""


class APIError(AAFClientError):
    """Raised when the AAF server returned a non-2xx response.

    Attributes
    ----------
    status_code : the HTTP status code (e.g. 401, 404, 500).
    code        : machine-readable code from the server when available.
    detail      : human-readable detail string.
    response    : raw JSON body the server returned, when parseable.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        code: str | None = None,
        detail: str | None = None,
        response: Any | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.detail = detail
        self.response = response


class AuthenticationError(APIError):
    """401 — missing / invalid / expired JWT."""


class PermissionDeniedError(APIError):
    """403 — caller is authenticated but not allowed."""


class NotFoundError(APIError):
    """404 — the resource (task, manuscript, paper card, …) does not exist."""


class ValidationError(APIError):
    """422 — request body / query failed schema validation server-side."""


class ServerError(APIError):
    """5xx — server-side failure. Caller should retry with backoff."""


def raise_for_status(status_code: int, body: Any | None = None) -> None:
    """Map a status code → SDK exception. Returns silently on 2xx."""
    if 200 <= status_code < 300:
        return
    detail: str | None = None
    code: str | None = None
    if isinstance(body, dict):
        detail = body.get("detail") if isinstance(body.get("detail"), str) else None
        code = body.get("code") if isinstance(body.get("code"), str) else None
    msg = detail or f"HTTP {status_code}"
    cls: type[APIError]
    if status_code == 401:
        cls = AuthenticationError
    elif status_code == 403:
        cls = PermissionDeniedError
    elif status_code == 404:
        cls = NotFoundError
    elif status_code == 422:
        cls = ValidationError
    elif status_code >= 500:
        cls = ServerError
    else:
        cls = APIError
    raise cls(msg, status_code=status_code, code=code, detail=detail, response=body)


__all__ = [
    "AAFClientError",
    "APIError",
    "AuthenticationError",
    "NotFoundError",
    "PermissionDeniedError",
    "ServerError",
    "ValidationError",
    "raise_for_status",
]
