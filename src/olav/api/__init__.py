"""OLAV API - Programmatic and HTTP interfaces.

Includes:
- v1: Stable programmatic API (Python functions)
- server: FastAPI HTTP server (future phases)

Usage:
    from olav.api.v1.schema import list_tables
    result = list_tables()
"""

from olav.api.server import app

from . import v1

__all__ = ["app", "v1"]
