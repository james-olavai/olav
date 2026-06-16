"""
tool_generator.py — Auto-generate @tool Python files from registered service schemas

Flow:
  1. Fetch OpenAPI spec from service endpoint
  2. Store in api_registry DuckDB (load_schema)
  3. Group operations by tag
  4. Render one Python file per tool group using the embedded template
  5. Write to tool_generation.output_dir

Generated tools use service_call() for authentication and schema-aware trimming.

Reference: dev_docs/archive/19. SERVICE_REGISTRY_DESIGN.md §Phase2
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from olav.core.api_registry import load_schema
from olav.platform.services.registry import ServiceConfig, ServiceRegistry

logger = logging.getLogger(__name__)


_SCHEMA_PROBE_PATHS = [
    "/api/schema/?format=json",
    "/api/schema/",
    "/openapi.json",
    "/api/openapi.json",
    "/swagger.json",
    "/api/swagger.json",
    "/v1/openapi.json",
    "/api/v1/openapi.json",
    "/api/schema/swagger/?format=openapi",
    # InfluxDB 2.x style
    "/api/v2/swagger.json",
    "/api/v2/api-docs",
    # SpringDoc / SpringFox
    "/v3/api-docs",
    "/v2/api-docs",
    "/api-docs",
    # Kubernetes API server
    "/openapi/v2",
    # FastAPI / Starlette alternate
    "/api/v3/openapi.json",
]


def _fetch_openapi_schema(url: str, timeout: float = 30.0) -> dict:
    """Fetch and return the raw OpenAPI schema dict from *url*.

    Extracted as a standalone function so tests can mock it independently
    of httpx internals.  Raises on HTTP or connection errors.
    """
    import httpx
    with httpx.Client(timeout=timeout) as client:
        resp = client.get(url)
        resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if "yaml" in ct or "yml" in ct:
            import yaml
            return yaml.safe_load(resp.text)
        return resp.json()


def _discover_schema_url(endpoint: str, configured_url: str | None = None) -> str:
    """Return a working OpenAPI schema URL.

    Tries *configured_url* first, then probes common paths under *endpoint*.
    Raises RuntimeError if no working URL is found.
    """
    import httpx

    candidates: list[str] = []
    if configured_url:
        candidates.append(configured_url)
    for path in _SCHEMA_PROBE_PATHS:
        url = endpoint.rstrip("/") + path
        if url not in candidates:
            candidates.append(url)

    try:
        from olav.core.config import get_services_config
        _probe_timeout = get_services_config().schema_probe_timeout
    except Exception:
        _probe_timeout = 10.0
    with httpx.Client(timeout=_probe_timeout) as client:
        for url in candidates:
            try:
                resp = client.get(url)
                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    # Must look like OpenAPI (JSON or YAML with openapi/swagger key)
                    if "yaml" in ct or "yml" in ct:
                        import yaml
                        doc = yaml.safe_load(resp.text)
                    else:
                        try:
                            doc = resp.json()
                        except Exception:
                            continue
                    if isinstance(doc, dict) and ("openapi" in doc or "swagger" in doc):
                        logger.info("Discovered schema URL: %s", url)
                        return url
            except Exception:
                continue

    raise RuntimeError(
        f"Could not discover OpenAPI schema at {endpoint}. "
        f"Tried: {candidates}"
    )


def _store_schema(service_name: str, svc: ServiceConfig, resolved_url: str, force: bool = False) -> int:
    """Load schema from the service into api_registry. Returns operation count."""
    return load_schema(
        api_name=service_name,
        schema_url=resolved_url,
        base_url=svc.endpoint,
        force=force,
    )

# ---------------------------------------------------------------------------
# Tool file template
# ---------------------------------------------------------------------------

# NOTE: Python tool code generation templates (_TOOL_TEMPLATE, _FUNCTION_TEMPLATE)
# were removed in doc 39 migration. Tool generation is replaced by reference
# markdown generation (_render_markdown_reference). See doc 39 §1.


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------

def _to_func_name(prefix: str, method: str, path: str) -> str:
    """Build a Python function name from a tool prefix + HTTP method + path.

    Example: ("clab", "GET", "/api/v1/labs/{name}") → "clab_get_labs_by_name"
    """
    # Strip leading /api/v1/ prefixes
    slug = re.sub(r"^(/api/v\d+)?/", "", path).strip("/")
    # Replace path params {name} → by_name
    slug = re.sub(r"\{(\w+)\}", lambda m: f"by_{m.group(1)}", slug)
    # Slugify
    slug = re.sub(r"[^a-z0-9]+", "_", slug.lower()).strip("_")
    return f"{prefix}_{method.lower()}_{slug}" if slug else f"{prefix}_{method.lower()}"


# ---------------------------------------------------------------------------
# Registration flow
# ---------------------------------------------------------------------------

def register_service(
    service_name: str,
    force: bool = False,
    max_retries: int | None = None,
    retry_delay: float = 5.0,
) -> dict[str, Any]:
    """Full registration flow for a service.

    1. Fetch OpenAPI schema (with retries — GAP-08)
    2. Load schema into api_registry
    3. Generate tool files for each tag group
    4. Return registration summary

    Args:
        service_name: Key in services.yaml
        force:        Re-fetch schema even if already loaded
        max_retries:  Total fetch attempts before giving up (None → read from config, default 1)
        retry_delay:  Seconds to wait between attempts

    Returns:
        {"service": name, "ops_loaded": int, "reference_files": [str, ...]}
        or {"service": name, "status": "error", "error": str} on failure
    """
    if max_retries is None:
        try:
            from olav.core.config import get_services_config
            max_retries = get_services_config().schema_fetch_max_retries
        except Exception:
            max_retries = 1
    registry = ServiceRegistry.get_instance()
    svc = registry.get(service_name)

    # Step 1: discover working schema URL (auto-probe if configured URL fails or missing)
    try:
        resolved_url = _discover_schema_url(svc.endpoint, svc.schema_url or None)
    except RuntimeError as exc:
        return {"service": service_name, "status": "error", "error": str(exc)}

    # Step 2: fetch schema with retry (GAP-08)
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            logger.info(
                "Fetching schema for '%s' from %s (attempt %d/%d)",
                service_name, resolved_url, attempt + 1, max_retries,
            )
            _fetch_openapi_schema(resolved_url)
            break  # success
        except Exception as exc:
            last_exc = exc
            logger.warning("Schema fetch failed for '%s': %s", service_name, exc)
            if attempt < max_retries - 1:
                logger.info("Retrying in %.1fs…", retry_delay)
                time.sleep(retry_delay)
    else:
        return {
            "service": service_name,
            "status": "error",
            "error": f"Schema fetch failed after {max_retries} attempt(s): {last_exc}",
        }

    # Step 3: load schema into api_registry
    try:
        ops_count = _store_schema(service_name, svc, resolved_url=resolved_url, force=force)
    except Exception as exc:
        return {"service": service_name, "status": "error",
                "error": f"Schema store failed: {exc}"}
    logger.info("Loaded %d operations for '%s'", ops_count, service_name)

    # Step 3: generate reference markdown files
    reference_files: list[str] = []
    groups = svc.reference_generation.groups or []
    out_dir = Path(svc.reference_generation.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if groups:
        for group in groups:
            tag = group.tag
            try:
                rows = _query_tag_operations(svc.name, tag, readonly_only=False)
            except Exception as exc:
                logger.warning("Could not query ops for '%s' tag '%s': %s", svc.name, tag, exc)
                rows = []
            if svc.readonly_only:
                allowed = {p.rstrip("/") for p in (svc.readonly_post_paths or [])}
                rows = [
                    r for r in rows
                    if r[0].upper() in _READONLY_METHODS
                    or (r[0].upper() == "POST" and r[1].rstrip("/") in allowed)
                ]
            ops_by_tag = {tag: rows} if rows else {}
            md = _render_markdown_reference(svc, ops_by_tag)
            out_file = out_dir / f"{svc.name}_{tag}_api.md"
            out_file.write_text(md)
            reference_files.append(str(out_file))
            logger.info("Generated reference → %s", out_file)
    else:
        # No groups configured — generate a combined file from all ops
        md = _render_markdown_reference(svc, {})
        out_file = out_dir / f"{svc.name}_api.md"
        out_file.write_text(md)
        reference_files.append(str(out_file))
        logger.info("Generated skeleton reference → %s", out_file)

    return {
        "service": service_name,
        "status": "ok",
        "ops_loaded": ops_count,
        "reference_files": reference_files,
    }


_READONLY_METHODS = {"GET", "HEAD", "OPTIONS"}


def _query_tag_operations(
    api_name: str, tag: str, readonly_only: bool
) -> list[tuple]:
    """Query api_registry for operations matching tag, filtered by readonly_only."""
    import duckdb
    from olav.core.api_registry import DEFAULT_DB

    method_clause = "AND method IN ('GET', 'HEAD', 'OPTIONS')" if readonly_only else ""
    with duckdb.connect(str(DEFAULT_DB), read_only=True) as con:
        return con.execute(
            f"""
            SELECT method, path, summary, request_body_def, response_200_def, query_params
            FROM api_registry.operations
            WHERE api_name = ? AND list_contains(tags, ?)
            {method_clause}
            ORDER BY path, method
            """,
            [api_name, tag],
        ).fetchall()


def generate_schema_reference(
    service_name: str,
    tag: str | None = None,
) -> dict:
    """Build a schema reference dict for a registered service.

    Returns a compact JSON-serializable dict suitable for writing to
    schema_reference.json and embedding as static_context in a workspace.

    Structure::

        {
          "service": "netbox",
          "endpoint": "http://localhost:8000",
          "readonly_only": true,
          "operations": {
            "GET /api/circuits/circuits/": {
              "summary": "circuits_circuits_list",
              "query_params": [
                {"name": "status", "type": "string", "description": "...", "required": false},
                ...
              ]
            },
            ...
          }
        }
    """

    from olav.core.api_registry import DEFAULT_DB, get_query_params
    from olav.platform.services.registry import ServiceRegistry

    svc = ServiceRegistry().get(service_name)
    qp_map = get_query_params(service_name, tag=tag, db_path=DEFAULT_DB)

    # Fetch summaries too
    import duckdb
    tag_clause = "AND list_contains(tags, ?)" if tag else ""
    db_params = [service_name]
    if tag:
        db_params.append(tag)
    with duckdb.connect(str(DEFAULT_DB), read_only=True) as con:
        rows = con.execute(
            f"""
            SELECT method, path, summary
            FROM api_registry.operations
            WHERE api_name = ? {tag_clause}
            ORDER BY path, method
            """,
            db_params,
        ).fetchall()

    operations: dict = {}
    for method, path, summary in rows:
        key = f"{method} {path}"
        operations[key] = {
            "summary": summary or "",
            "query_params": qp_map.get(key, []),
        }

    return {
        "service": service_name,
        "endpoint": svc.endpoint,
        "readonly_only": svc.readonly_only,
        "tag_filter": tag,
        "operations": operations,
    }


# ---------------------------------------------------------------------------
# Reference markdown rendering (doc 39 §4.1)
# ---------------------------------------------------------------------------

_MAX_PARAMS = 8
_MAX_RETURN_FIELDS = 10


def _render_markdown_reference(
    svc: "ServiceConfig",
    ops_by_tag: dict[str, list[tuple]],
) -> str:
    """Render a service API reference in doc 39 §4.1 markdown format.

    Args:
        svc:        ServiceConfig with display_name, endpoint, etc.
        ops_by_tag: {tag: [(method, path, summary, req_def, resp_def, qp_raw), ...]}

    Returns:
        Markdown string (~4000 token budget; params capped at _MAX_PARAMS each).
    """
    import json
    from datetime import date

    display_name = svc.display_name or svc.name
    lines: list[str] = [
        f"# {display_name} API Reference",
        f"> Generated by olav registry register | {date.today().isoformat()}",
        f"> Base URL: {svc.endpoint}",
        "",
    ]

    if not ops_by_tag:
        lines += [
            "⚠️ No operations found. Schema may be unavailable.",
            "",
            "_This is a skeleton file. Run `olav registry register` once the service is reachable._",
        ]
        return "\n".join(lines)

    for tag, rows in sorted(ops_by_tag.items()):
        lines.append(f"## {tag}")
        lines.append("")
        for method, path, summary, _req, _resp, qp_raw in rows:
            lines.append(f"### {method} {path}")
            if summary:
                lines.append(f"> {summary}")
            # Query params
            try:
                params = json.loads(qp_raw) if isinstance(qp_raw, str) else (qp_raw or [])
            except (ValueError, TypeError):
                params = []
            if params:
                lines.append("")
                lines.append("**Parameters:**")
                for p in params[:_MAX_PARAMS]:
                    req = " *(required)*" if p.get("required") else ""
                    desc = p.get("description", "")
                    lines.append(f"- `{p['name']}` ({p.get('type', 'string')}){req} — {desc}")
                if len(params) > _MAX_PARAMS:
                    lines.append(f"- _(+{len(params) - _MAX_PARAMS} more params)_")
            lines.append("")

    return "\n".join(lines)

