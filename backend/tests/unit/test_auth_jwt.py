"""Unit tests for the stdlib JWT issuer/decoder."""

from __future__ import annotations

import time

import pytest

from backend.core.auth import (
    InvalidTokenError,
    decode,
    hash_password,
    issue,
    verify_password,
)

# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def test_issue_then_decode_round_trip():
    token = issue("secret", user_id="u1", email="a@b.co", role="admin", ttl_s=60)
    claims = decode("secret", token)
    assert claims.sub == "u1"
    assert claims.email == "a@b.co"
    assert claims.role == "admin"
    assert claims.exp - claims.iat == 60
    assert not claims.expired


def test_decode_rejects_wrong_secret():
    token = issue("right", user_id="u1", email="a@b.co")
    with pytest.raises(InvalidTokenError):
        decode("wrong", token)


def test_decode_rejects_tampered_payload():
    token = issue("secret", user_id="u1", email="a@b.co")
    head, body, sig = token.split(".")
    # Flip a character in the body — signature should no longer match.
    tampered = f"{head}.{body[:-1]}{'A' if body[-1] != 'A' else 'B'}.{sig}"
    with pytest.raises(InvalidTokenError):
        decode("secret", tampered)


def test_decode_rejects_expired_token():
    token = issue("secret", user_id="u1", email="a@b.co", ttl_s=1, now=int(time.time()) - 100)
    with pytest.raises(InvalidTokenError):
        decode("secret", token)


def test_decode_rejects_malformed_token():
    with pytest.raises(InvalidTokenError):
        decode("secret", "not-a-jwt")
    with pytest.raises(InvalidTokenError):
        decode("secret", "a.b")  # only 2 segments


def test_issue_requires_secret():
    with pytest.raises(ValueError):
        issue("", user_id="u1", email="a@b.co")


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_hash_then_verify_round_trip():
    h = hash_password("hunter2")
    assert h.startswith("pbkdf2$sha256$")
    assert verify_password("hunter2", h) is True
    assert verify_password("wrong", h) is False


def test_hash_is_salted_so_two_hashes_differ_for_same_password():
    a = hash_password("same")
    b = hash_password("same")
    assert a != b
    assert verify_password("same", a) and verify_password("same", b)


def test_verify_handles_garbage_inputs():
    assert verify_password("anything", "") is False
    assert verify_password("", "pbkdf2$sha256$1$AAAA$AAAA") is False
    assert verify_password("anything", "not-a-hash") is False
    assert verify_password("anything", "scram$sha256$1$AAAA$AAAA") is False


def test_empty_password_hash_rejected():
    with pytest.raises(ValueError):
        hash_password("")
