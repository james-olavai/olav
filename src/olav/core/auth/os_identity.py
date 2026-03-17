"""OSIdentityProvider — Tier 0 auth using OS environment ($USER / $LOGNAME).

No password verification; suitable for trusted multi-user Linux servers
where each user has their own HOME directory.
"""

from __future__ import annotations

import os

from olav.core.auth.identity import UserIdentity


class OSIdentityProvider:
    """Returns a UserIdentity derived from the current OS user.

    Falls back to "anonymous" if neither $USER nor $LOGNAME is set.
    """

    def authenticate(self, token: str | None = None) -> UserIdentity:  # noqa: ARG002
        username = os.environ.get("USER") or os.environ.get("LOGNAME") or "anonymous"
        return UserIdentity(username=username, role="user", source="os")
