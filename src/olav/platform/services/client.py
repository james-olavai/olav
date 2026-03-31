"""
client.py — Authenticated HTTP client for registered services

Provides service_call() for making authenticated API requests.
Handles JWT auto-login/refresh, Bearer injection, Basic encoding.
Uses api_registry for schema-aware response trimming.

Reference: dev_docs/16. SERVICE_REGISTRY_DESIGN.md §Phase2
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from olav.platform.services.registry import ServiceConfig, ServiceRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token cache (in-process; reuses token across calls in the same session)
# ---------------------------------------------------------------------------

_token_cache: dict[str, str] = {}


def _jwt_login(svc: ServiceConfig) -> str:
    """POST to login_path, return JWT token. Caches per service name."""
    cached = _token_cache.get(svc.name)
    if cached:
        return cached

    username, password = svc.get_credentials()
    url = svc.endpoint.rstrip("/") + svc.auth.login_path
    with httpx.Client(timeout=15.0) as client:
        resp = client.post(url, json={"username": username, "password": password})
        resp.raise_for_status()
        body = resp.json()

    # ContainerLab returns {"token": "..."}, try common keys
    token = body.get("token") or body.get("access_token") or body.get("jwt", "")
    if not token:
        raise ValueError(f"JWT login to {url} returned no token: {list(body.keys())}")

    _token_cache[svc.name] = token
    return token


def _get_auth_headers(svc: ServiceConfig) -> dict[str, str]:
    """Build Authorization headers for the service's auth type."""
    auth_type = svc.auth.type

    if auth_type == "none":
        return {}

    if auth_type == "bearer":
        token = svc.get_token()
        if not token:
            raise ValueError(
                f"Service '{svc.name}': auth.type=bearer but {svc.auth.token_env!r} env var is not set"
            )
        return {"Authorization": f"Bearer {token}"}

    if auth_type == "jwt":
        # Use cached token or login
        token = svc.get_token() or _jwt_login(svc)
        return {"Authorization": f"Bearer {token}"}

    if auth_type == "basic":
        import base64
        username, password = svc.get_credentials()
        creds = base64.b64encode(f"{username}:{password}".encode()).decode()
        return {"Authorization": f"Basic {creds}"}

    raise ValueError(f"Service '{svc.name}': unknown auth.type={auth_type!r}")


def _trim_response(
    data: Any,
    api_name: str,
    def_name: str | None,
) -> Any:
    """Schema-aware response trimming using api_registry.field_names().

    Removes unknown/noisy fields from response dicts to reduce LLM context.
    Falls back to returning data unchanged if no schema is known.
    """
    if not def_name or not isinstance(data, (dict, list)):
        return data

    try:
        from olav.core.api_registry import field_names
        known_fields = field_names(api_name, def_name)
        if not known_fields:
            return data
    except Exception:
        return data

    if isinstance(data, dict):
        return {k: v for k, v in data.items() if k in known_fields}
    if isinstance(data, list):
        return [
            {k: v for k, v in item.items() if k in known_fields}
            if isinstance(item, dict) else item
            for item in data
        ]
    return data


def service_call(
    service_name: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    params: dict | None = None,
    response_def: str | None = None,
    timeout: float = 30.0,
) -> Any:
    """Make an authenticated REST call to a registered service.

    Args:
        service_name:  Key in services.yaml (e.g. "containerlab")
        method:        HTTP method (GET, POST, PUT, DELETE, …)
        path:          API path (e.g. "/api/v1/labs")
        body:          JSON request body (for POST/PUT/PATCH)
        params:        Query parameters
        response_def:  OpenAPI definition name for response trimming
                       (e.g. "Lab"); uses api_registry.field_names()
        timeout:       Request timeout in seconds

    Returns:
        Parsed JSON response (dict or list), schema-trimmed if response_def given.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx responses
        KeyError: if service_name not found in registry
        ValueError: if auth configuration is incomplete
    """
    registry = ServiceRegistry.get_instance()
    svc = registry.get(service_name)

    url = svc.endpoint.rstrip("/") + path
    headers = _get_auth_headers(svc)

    logger.debug("service_call: %s %s → %s", method.upper(), service_name, url)

    with httpx.Client(timeout=timeout) as client:
        resp = client.request(
            method.upper(),
            url,
            json=body,
            params=params,
            headers=headers,
        )
        if resp.status_code == 401 and svc.auth.type == "jwt":
            # Token expired — clear cache and retry once with fresh token
            _token_cache.pop(service_name, None)
            headers = _get_auth_headers(svc)
            resp = client.request(
                method.upper(), url, json=body, params=params, headers=headers
            )
        resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        return resp.text

    return _trim_response(data, service_name, response_def)
