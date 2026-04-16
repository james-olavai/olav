"""olav.tools — Platform-agnostic tool implementations.

This package contains the core business logic for all OLAV tools.
Workspace `@tool` wrappers in `.olav/workspace/core/tools/` delegate to
functions defined here.

Usage without OLAV workspace::

    from olav.tools.sql import query_duckdb
    result = query_duckdb("SELECT * FROM netops.devices")

    from olav.tools.api import service_request
    data = service_request("netbox", "GET", "/api/dcim/devices/")

    from olav.tools.memory import search_memory
    memories = search_memory("BGP failover procedure")
"""
