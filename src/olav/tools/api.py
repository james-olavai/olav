"""olav.tools.api — HTTP API client for registered services (platform-agnostic).

Core API request logic used by the `api_request` workspace tool.
Can be used standalone::

    from olav.tools.api import service_request

    devices = service_request("netbox", "GET", "/api/dcim/devices/")
    health = service_request("influxdb_netops", "GET", "/health")
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def service_request(
    service: str,
    method: str = "GET",
    path: str = "/",
    params: dict | None = None,
    body: dict | None = None,
    confirmed: bool = False,
    page_size: int | None = None,
    enable_write: bool | None = None,
) -> dict | list:
    """Execute an authenticated API request to a registered service.

    Args:
        service: Registered service name (key in services.yaml).
        method: HTTP method (GET, POST, PUT, PATCH, DELETE).
        path: API path, e.g. "/api/dcim/devices/".
        params: Query string parameters.
        body: Request body for POST/PUT/PATCH.
        confirmed: True only after user has approved a write operation.
        page_size: None=first page, -1=all pages.
        enable_write: Override write gate. None reads from OLAV_ENABLE_API_WRITE env.

    Returns:
        dict or list of dicts with API response data.

    Raises:
        KeyError: If service is not registered.

    Example::

        from olav.tools.api import service_request

        # Read (always works)
        devices = service_request("netbox", "GET", "/api/dcim/devices/", params={"site": "DC1"})

        # Write (requires enable_write=True + confirmed=True)
        result = service_request("netbox", "POST", "/api/dcim/devices/",
                                 body={"name": "sw3"}, enable_write=True, confirmed=True)
    """
    from olav.platform.services.client import service_call

    # Write gate
    if method.upper() in _WRITE_METHODS:
        write_enabled = enable_write if enable_write is not None else bool(os.environ.get("OLAV_ENABLE_API_WRITE"))
        if not write_enabled:
            return {
                "status": "blocked",
                "reason": "API write mode not enabled.",
                "method": method.upper(),
                "path": path,
            }

    result = service_call(
        service,
        method=method,
        path=path,
        params=params or {},
        body=body or {},
        confirmed=confirmed,
    )

    # Auto-expand paginated responses (DRF/NetBox style)
    if isinstance(result, dict) and "results" in result and "count" in result:
        if page_size == -1:
            items: list[Any] = list(result["results"])
            next_path = result.get("next")
            while next_path:
                if next_path.startswith("http"):
                    from olav.platform.services.registry import ServiceRegistry
                    svc = ServiceRegistry.get_instance().get(service)
                    next_path = next_path.replace(svc.endpoint.rstrip("/"), "")
                page = service_call(service, method="GET", path=next_path, params={}, body={}, confirmed=False)
                if isinstance(page, dict) and "results" in page:
                    items.extend(page["results"])
                    next_path = page.get("next")
                else:
                    break
            return items
        return result["results"]

    return result
