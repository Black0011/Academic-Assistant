"""Password hashing — stdlib-only PBKDF2-HMAC-SHA256.

Format: ``pbkdf2$<algo>$<iters>$<salt_b64>$<hash_b64>``.

PBKDF2 is good enough for an internal multi-user research framework: not
GPU-hard like bcrypt/argon2, but the deployment threat model is "private
server, small user list" — and shipping zero non-stdlib deps for auth is
worth more than 100x slower hashing on commodity attackers.

If you ever need bcrypt/argon2, swap this module out — every call site
goes through ``hash_password`` / ``verify_password``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Final

_ALGO: Final[str] = "sha256"
_ITERS: Final[int] = 200_000
_SALT_BYTES: Final[int] = 16
_HASH_BYTES: Final[int] = 32


def hash_password(password: str) -> str:
    """Return a self-describing hash string suitable for storage."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(_ALGO, password.encode("utf-8"), salt, _ITERS, _HASH_BYTES)
    return f"pbkdf2${_ALGO}${_ITERS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time compare the password against a stored hash."""
    if not encoded or not password:
        return False
    try:
        scheme, algo, iters_str, salt_b64, hash_b64 = encoded.split("$", 4)
    except ValueError:
        return False
    if scheme != "pbkdf2":
        return False
    try:
        iters = int(iters_str)
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(algo, password.encode("utf-8"), salt, iters, len(expected))
    return hmac.compare_digest(digest, expected)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64d(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


__all__ = ["hash_password", "verify_password"]
