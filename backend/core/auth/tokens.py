"""Stateless JWT (HS256) — stdlib only.

We re-implement the bare minimum of RFC 7519 instead of pulling
``PyJWT`` / ``python-jose`` because:

* Auth is the **least** place we want a transitive dependency that's
  rarely audited but always parsing untrusted input.
* HS256 with a per-deployment ``settings.secret_key`` matches the
  framework's "private server" threat model.
* Payload is intentionally minimal: ``sub`` (user id), ``email``,
  ``role``, ``iat``, ``exp``. No JWE, no nested tokens, no kid rotation
  — when those are needed, swap to a real library.

Usage::

    issue(secret, user_id="u1", email="a@b", role="user", ttl_s=3600)
    decode(secret, token)  # raises InvalidTokenError on any failure
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any


class InvalidTokenError(Exception):
    """Raised on any signature / shape / expiry failure."""


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    email: str
    role: str
    iat: int
    exp: int

    @property
    def expired(self) -> bool:
        return int(time.time()) >= self.exp


def issue(
    secret: str,
    *,
    user_id: str,
    email: str,
    role: str = "user",
    ttl_s: int = 86_400,
    now: int | None = None,
) -> str:
    """Mint a signed JWT. ``now`` is injectable for tests."""
    if not secret:
        raise ValueError("secret_key must not be empty when auth is enabled")
    issued = int(now if now is not None else time.time())
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "iat": issued,
        "exp": issued + int(ttl_s),
    }
    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode("ascii")
    sig = _b64(hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest())
    return f"{header}.{body}.{sig}"


def decode(secret: str, token: str, *, leeway_s: int = 0) -> TokenClaims:
    """Verify signature and expiry, returning typed claims.

    Raises :class:`InvalidTokenError` for *any* validation failure.
    """
    if not token or token.count(".") != 2:
        raise InvalidTokenError("malformed token")
    header_b64, body_b64, sig_b64 = token.split(".", 2)

    try:
        header = json.loads(_b64d(header_b64))
        body: dict[str, Any] = json.loads(_b64d(body_b64))
    except (ValueError, json.JSONDecodeError) as exc:
        raise InvalidTokenError("malformed token") from exc

    if header.get("alg") != "HS256" or header.get("typ") != "JWT":
        raise InvalidTokenError("unsupported alg/typ")

    expected = _b64(
        hmac.new(
            secret.encode("utf-8"),
            f"{header_b64}.{body_b64}".encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    if not hmac.compare_digest(expected, sig_b64):
        raise InvalidTokenError("bad signature")

    try:
        sub = str(body["sub"])
        email = str(body["email"])
        role = str(body.get("role", "user"))
        iat = int(body["iat"])
        exp = int(body["exp"])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidTokenError("missing/invalid claims") from exc

    if int(time.time()) >= exp + max(0, leeway_s):
        raise InvalidTokenError("token expired")

    return TokenClaims(sub=sub, email=email, role=role, iat=iat, exp=exp)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


__all__ = ["InvalidTokenError", "TokenClaims", "decode", "issue"]
