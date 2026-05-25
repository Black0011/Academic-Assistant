"""Auth DTOs.

Plain ``str`` is used for emails (with a light shape check) instead of
``pydantic[email]`` so the auth subsystem stays stdlib-only — the framework
is meant to run anywhere with zero credentials and minimal deps.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

UserRole = Literal["admin", "user"]

# Conservative single-line email shape. We deliberately skip RFC 5322 since
# we only need "looks like an email" — the deployment threat model is small.
_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def _validate_email(value: str) -> str:
    v = value.strip().lower()
    if not _EMAIL_RE.match(v):
        raise ValueError("email is not a valid address")
    if len(v) > 254:
        raise ValueError("email exceeds 254 characters")
    return v


Email = Annotated[str, AfterValidator(_validate_email)]


class User(BaseModel):
    """Persistent user record.

    Note: ``password_hash`` is *only* serialised by trusted backends
    (UserStore implementations). HTTP responses must use :class:`PublicUser`.
    """

    id: str
    email: Email
    display_name: str = ""
    role: UserRole = "user"
    password_hash: str = Field(default="", repr=False)
    disabled: bool = False
    created_at_epoch_s: float | None = None

    def public(self) -> PublicUser:
        return PublicUser(
            id=self.id,
            email=self.email,
            display_name=self.display_name or self.email.split("@", 1)[0],
            role=self.role,
            disabled=self.disabled,
        )


class PublicUser(BaseModel):
    id: str
    email: Email
    display_name: str
    role: UserRole = "user"
    disabled: bool = False


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    password: str = Field(..., min_length=1, max_length=256)


class RegisterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: Email
    password: str = Field(..., min_length=8, max_length=256)
    display_name: str = ""


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: PublicUser


__all__ = [
    "Email",
    "LoginInput",
    "PublicUser",
    "RegisterInput",
    "TokenResponse",
    "User",
    "UserRole",
]
