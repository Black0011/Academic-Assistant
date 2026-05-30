"""Auth subsystem — JWT issuance, password hashing, user store, dependencies.

Public surface used outside this package::

    from backend.core.auth import current_user, optional_current_user, require_role
    from backend.core.auth import hash_password, verify_password
    from backend.core.auth import issue, decode, InvalidTokenError
    from backend.core.auth import User, PublicUser, UserStore
    from backend.core.auth import InMemoryUserStore, YamlUserStore

See :mod:`.dependencies`, :mod:`.models`, :mod:`.password`, :mod:`.tokens`,
:mod:`.users`.
"""

from __future__ import annotations

from .dependencies import current_user, optional_current_user, require_role
from .models import LoginInput, PublicUser, RegisterInput, TokenResponse, User, UserRole
from .password import hash_password, verify_password
from .tokens import InvalidTokenError, TokenClaims, decode, issue
from .users import InMemoryUserStore, UserStore, YamlUserStore

__all__ = [
    "InMemoryUserStore",
    "InvalidTokenError",
    "LoginInput",
    "PublicUser",
    "RegisterInput",
    "TokenClaims",
    "TokenResponse",
    "User",
    "UserRole",
    "UserStore",
    "YamlUserStore",
    "current_user",
    "decode",
    "hash_password",
    "issue",
    "optional_current_user",
    "require_role",
    "verify_password",
]
