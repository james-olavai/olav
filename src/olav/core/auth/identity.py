"""UserIdentity — immutable value object for an authenticated user."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

Role = Literal["admin", "user", "readonly"]


@dataclass(frozen=True)
class UserIdentity:
    """Represents a verified identity returned by an AuthProvider.

    Attributes:
        username:   Unique user identifier (e.g. OS username, LDAP uid).
        role:       One of "admin", "user", "readonly".
        source:     Origin of this identity: "os", "token", "ldap", "ad", "oidc".
        expires_at: Optional expiry timestamp; None = never expires.
    """

    username: str
    role: Role = "user"
    source: str = "os"
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(self.expires_at.tzinfo) > self.expires_at
