"""
client.py — Authenticated HTTP client for registered services

Provides service_call() for making authenticated API requests.
Handles JWT auto-login/refresh, Bearer injection, Basic encoding.
Uses api_registry for schema-aware response trimming.

Reference: dev_docs/16. SERVICE_REGISTRY_DESIGN.md §Phase2
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from olav.platform.safety.permissions import is_bypass_active
from olav.platform.services.registry import ServiceConfig, ServiceRegistry

logger = logging.getLogger(__name__)

# HTTP methods that modify external service state — always require approval
_WRITE_METHODS: frozenset[str] = frozenset({"DELETE", "POST", "PUT", "PATCH"})

# Process-wide HTTP client pool — keyed by verify_ssl so services with
# self-signed certs (e.g. an in-house ContainerLab) get a relaxed-TLS
# client while production services keep strict verification.
_http_clients: dict[bool, httpx.Client] = {}


def _get_http_client(verify_ssl: bool = True) -> httpx.Client:
    c = _http_clients.get(verify_ssl)
    if c is None or c.is_closed:
        c = httpx.Client(verify=verify_ssl)
        _http_clients[verify_ssl] = c
    return c


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
    client = _get_http_client(svc.verify_ssl)
    resp = client.post(url, json={"username": username, "password": password}, timeout=15.0)
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

    if auth_type == "api_key":
        token = svc.get_token()
        if not token:
            raise ValueError(
                f"Service '{svc.name}': auth.type=api_key but {svc.auth.token_env!r} env var is not set"
            )
        header = svc.auth.header_name or "Authorization"
        return {header: token}

    raise ValueError(f"Service '{svc.name}': unknown auth.type={auth_type!r}")


def _trim_response(
    data: Any,
    api_name: str,
    def_name: str | None,
) -> Any:
    """Schema-aware response trimming using api_registry.field_names().

    Removes unknown/noisy fields from response dicts to reduce LLM context.
    Falls back to returning data unchanged if no schema is known.

    Delegates to response_extractor.schema_trim() to avoid duplication.
    """
    from olav.platform.services.response_extractor import schema_trim

    return schema_trim(data, api_name, def_name)


def service_call(
    service_name: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    params: dict | None = None,
    response_def: str | None = None,
    timeout: float = 30.0,
    confirmed: bool = False,
) -> Any:
    """Make an authenticated REST call to a registered service.

    Args:
        service_name:  Key in services.yaml (e.g. "netbox", "containerlab")
        method:        HTTP method (GET, POST, PUT, DELETE, …)
        path:          API path (e.g. "/api/dcim/sites/")
        body:          JSON request body (for POST/PUT/PATCH)
        params:        Query parameters
        response_def:  OpenAPI definition name for response trimming
        timeout:       Request timeout in seconds
        confirmed:     Set True after presenting the operation to the user and
                       receiving explicit approval. Bypasses the write gate for
                       this single call only.

    Returns:
        Parsed JSON response (dict or list), schema-trimmed if response_def given.
        On unconfirmed write: {"status": "requires_approval", ...} — show the
        user the method/path/body, then re-call with confirmed=True.

    Raises:
        httpx.HTTPStatusError: on 4xx/5xx responses
        KeyError: if service_name not found in registry
        ValueError: if auth configuration is incomplete
    """
    # §20 SECURITY_MODEL §6.3: write methods require approval before any HTTP
    # (bypassed when confirmed=True, OLAV_DANGEROUSLY_SKIP_PERMISSIONS=1, or
    #  path is in the service's readonly_post_paths whitelist)
    registry = ServiceRegistry.get_instance()
    svc = registry.get(service_name)
    is_readonly_post = (
        method.upper() == "POST" and path in (svc.readonly_post_paths or [])
    )
    if method.upper() in _WRITE_METHODS and not confirmed and not is_bypass_active() and not is_readonly_post:
        return {
            "status": "requires_approval",
            "service": service_name,
            "method": method.upper(),
            "path": path,
            "body": body,
            "reason": (
                f"Write operation '{method.upper()} {path}' on service "
                f"'{service_name}' requires operator approval"
            ),
            "suggested_action": (
                "Show the user exactly what will be created/modified (method, path, body). "
                "Once the user confirms, re-call with confirmed=True to execute."
            ),
        }

    url = svc.endpoint.rstrip("/") + path
    headers = _get_auth_headers(svc)

    logger.debug("service_call: %s %s → %s", method.upper(), service_name, url)

    client = _get_http_client(svc.verify_ssl)
    resp = client.request(
        method.upper(),
        url,
        json=body,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    if resp.status_code == 401 and svc.auth.type == "jwt":
        # Token expired — clear cache and retry once with fresh token
        _token_cache.pop(service_name, None)
        headers = _get_auth_headers(svc)
        resp = client.request(
            method.upper(), url, json=body, params=params, headers=headers,
            timeout=timeout,
        )
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception:
        return resp.text

    # Prefer explicit response_def; fall back to auto_extract which auto-detects
    # the schema from api_registry and applies list truncation.
    if response_def:
        return _trim_response(data, service_name, response_def)

    try:
        from olav.platform.services.response_extractor import auto_extract
        return auto_extract(data, service_name, method, path)
    except Exception:
        return data
