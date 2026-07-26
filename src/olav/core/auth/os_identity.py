"""OSIdentityProvider — Tier 0 auth using OS environment ($USER / $LOGNAME).

No password verification; suitable for a trusted single-user machine or a
trusted multi-user Linux server where each user has their own HOME directory.

Role:
  Defaults to ``"user"`` (least privilege) so it stays SAFE as the failure
  fallback for the token/ldap/server providers — a failed remote credential
  must never escalate to admin. The **personal tier** (``auth.mode="none"``)
  constructs it with ``role="admin"`` via ``get_auth_provider``: the owner of a
  personal machine has full control of their own box, and RBAC restrictions are
  a team feature (olav-ent). See dev_docs/111 tiered model.
"""

from __future__ import annotations

import os

from olav.core.auth.identity import Role, UserIdentity


class OSIdentityProvider:
    """Returns a UserIdentity derived from the current OS user.

    Falls back to "anonymous" if neither $USER nor $LOGNAME is set.
    """

    def __init__(self, role: Role = "user") -> None:
        self._role: Role = role

    def authenticate(self, token: str | None = None) -> UserIdentity:  # noqa: ARG002
        username = os.environ.get("USER") or os.environ.get("LOGNAME") or "anonymous"
        return UserIdentity(username=username, role=self._role, source="os")
