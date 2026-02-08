"""OLAV API v1 - Stable, production-ready programmatic API.

Provides type-safe access to OLAV functionality:
- list_tables, get_table_schema, get_sample_data (schema module)
- Query devices and network data
- Manage cache and system operations
- Future: Additional modules in Phase 1.2-1.6

Usage:
    from olav.api.v1 import schema
    result = schema.list_tables()
    
    from olav.api.v1.schema import get_table_schema
    devices = get_table_schema("devices")
"""

from . import schema

__all__ = ["schema"]
