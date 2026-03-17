"""OLAV core.auth public package.

Convenience re-exports::

    from olav.core.auth import UserIdentity, get_auth_provider
"""

from olav.core.auth.identity import UserIdentity
from olav.core.auth.provider import AuthProvider, get_auth_provider

__all__ = ["AuthProvider", "UserIdentity", "get_auth_provider"]
