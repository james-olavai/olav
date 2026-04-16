"""api_request — Universal API query tool for registered services.

Authenticated API request to any service registered in services.yaml.
Auth is handled automatically. Write operations require:
  1. --enable-api-write CLI flag (sets OLAV_ENABLE_API_WRITE=1)
  2. HITL approval (confirmed=True after user confirmation)

Reference: dev_docs/39. SCHEMA_AWARE_API_ARCHITECTURE.md §8
"""
from __future__ import annotations

import os
from typing import Any

from langchain_core.tools import tool

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_READ_METHODS = {"GET", "HEAD", "OPTIONS"}


@tool
def api_request(
    service: str,
    method: str = "GET",
    path: str = "/",
    params: dict | None = None,
    body: dict | None = None,
    page_size: int | None = None,
    confirmed: bool = False,
) -> dict | list:
    """Authenticated API request to a registered service.

    Auth is handled automatically via services.yaml configuration.

    Read operations (GET) always work.

    Write operations (POST/PUT/PATCH/DELETE) require:
      1. CLI flag --enable-api-write (blocked without it, even with --dangerously-skip-permissions)
      2. First call with confirmed=False → returns {"status": "requires_approval", ...}
      3. Present the diff to the user and get explicit confirmation
      4. Second call with confirmed=True → executes the write

    Args:
        service:   Registered service name (key in services.yaml)
        method:    HTTP method (GET, POST, PUT, PATCH, DELETE)
        path:      API path, e.g. "/api/dcim/devices/"
        params:    Query string parameters, e.g. {"site": "DC1", "limit": 50}
        body:      Request body for POST/PUT/PATCH operations
        page_size: Pagination control (GET only):
                   - None (default): return first-page results only
                   - -1: auto-follow all pages until next=null
        confirmed: Set True ONLY after user has explicitly approved the write.
                   Never set True on first call — always show the diff first.

    Returns:
        - dict: single-object response, write-approval dict, or blocked dict
        - list[dict]: paginated list response (results array auto-extracted)
    """
    from olav.tools.api import service_request

    try:
        return service_request(
            service,
            method=method,
            path=path,
            params=params,
            body=body,
            confirmed=confirmed,
            page_size=page_size,
        )
    except KeyError:
        from olav.platform.services.registry import ServiceRegistry
        registry = ServiceRegistry.get_instance()
        available = sorted(s.name for s in registry.list())
        return {
            "status": "error",
            "reason": f"Service '{service}' is not registered.",
            "hint": f"Run `olav registry register <url>` to add it. Available: {available}",
        }
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "reason": str(exc), "service": service, "path": path}
