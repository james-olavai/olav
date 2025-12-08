"""OLAV Admin Tools - Server-side management utilities.

This module provides administrator-only tools for:
- Token management (create, list, revoke)
- Device initialization
- Index management

Usage:
    uv run olav-admin token create --role operator --name "alice-laptop"
    uv run olav-admin token list
    uv run olav-admin token revoke <client_id>
"""

from .commands import app

__all__ = ["app"]
