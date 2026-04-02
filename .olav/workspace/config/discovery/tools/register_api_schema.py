"""register_api_schema — Phase 4 tool (api_discovery.md §1.2).

Parses an OpenAPI 3.x specification (URL or local file path) and classifies
each field via ``classify_field`` → staging mutation requests for human review.

Zero new pip dependencies: uses only stdlib ``urllib.request``, ``json``,
``pathlib``, ``typing``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# OpenAPI field extraction helpers
# ---------------------------------------------------------------------------


def _load_spec(url_or_path: str) -> dict[str, Any]:
    """Load an OpenAPI 3.x spec from a URL or local file path.

    Parameters
    ----------
    url_or_path:
        Either an HTTP/HTTPS URL or an absolute/relative filesystem path.

    Returns
    -------
    Parsed JSON dict representing the OpenAPI document.

    Raises
    ------
    ValueError
        If the spec cannot be loaded or parsed.
    """
    if url_or_path.startswith(("http://", "https://")):
        try:
            with urllib.request.urlopen(url_or_path, timeout=15) as resp:  # noqa: S310
                raw = resp.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ValueError(f"Failed to fetch spec from {url_or_path!r}: {exc}") from exc
    else:
        path = Path(url_or_path)
        if not path.exists():
            raise ValueError(f"Spec file not found: {url_or_path!r}")
        raw = path.read_text(encoding="utf-8")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Failed to parse spec as JSON: {exc}") from exc


def _extract_fields_from_schema(
    schema: dict[str, Any],
    prefix: str = "",
    parent_description: str = "",
) -> list[dict[str, Any]]:
    """Recursively extract field metadata from a JSON Schema object.

    Handles ``properties``, ``allOf``, ``anyOf``, ``oneOf`` — flat extraction
    only (no deep recursion beyond 1 nesting level) to keep latency bounded.
    """
    fields: list[dict[str, Any]] = []

    # Merge allOf/anyOf/oneOf schemas shallowly
    for combiner in ("allOf", "anyOf", "oneOf"):
        for sub in schema.get(combiner, []):
            fields.extend(_extract_fields_from_schema(sub, prefix=prefix))

    props = schema.get("properties", {})
    required_set = set(schema.get("required", []))

    for field_name, field_schema in props.items():
        if not isinstance(field_schema, dict):
            continue

        full_name = f"{prefix}.{field_name}" if prefix else field_name
        description = field_schema.get("description", parent_description)
        data_type = field_schema.get("type", "")
        example = field_schema.get("example", "")
        fmt = field_schema.get("format", "")

        fields.append(
            {
                "name": full_name,
                "description": description,
                "type": f"{data_type}({fmt})" if fmt else data_type,
                "example": str(example) if example != "" else "",
                "required": field_name in required_set,
            }
        )

        # One level of nesting for object properties
        if field_schema.get("type") == "object" or "properties" in field_schema:
            fields.extend(
                _extract_fields_from_schema(
                    field_schema,
                    prefix=full_name,
                    parent_description=description,
                )
            )

    return fields


def _fields_from_component_schemas(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract all fields from ``components/schemas``."""
    schemas = spec.get("components", {}).get("schemas", {})
    fields: list[dict[str, Any]] = []
    for schema_name, schema_obj in schemas.items():
        if not isinstance(schema_obj, dict):
            continue
        for field in _extract_fields_from_schema(schema_obj, prefix=schema_name):
            field["source"] = f"components/schemas/{schema_name}"
            fields.append(field)
    return fields


def _fields_from_paths(spec: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract fields from ``paths`` requestBody / response schemas (best-effort)."""
    fields: list[dict[str, Any]] = []
    paths = spec.get("paths", {})

    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue

            # requestBody
            req_body = op.get("requestBody", {})
            for _media, media_obj in req_body.get("content", {}).items():
                schema = media_obj.get("schema", {})
                # Only inline schemas (not $ref) — resolving $ref needs full parsing
                if "$ref" not in schema:
                    for field in _extract_fields_from_schema(schema):
                        field["source"] = f"paths{path_str}/{method}/requestBody"
                        field["command"] = f"{method.upper()} {path_str}"
                        fields.append(field)

            # responses (200 / 201 only)
            for status in ("200", "201"):
                resp = op.get("responses", {}).get(status, {})
                for _media, media_obj in resp.get("content", {}).items():
                    schema = media_obj.get("schema", {})
                    if "$ref" not in schema:
                        for field in _extract_fields_from_schema(schema):
                            field["source"] = f"paths{path_str}/{method}/response/{status}"
                            field["command"] = f"{method.upper()} {path_str}"
                            fields.append(field)

    return fields


def extract_operation_policies(
    spec: dict[str, Any],
    domain: str = "platform",
) -> list:
    """Extract ApiOperationPolicy for each path+method in the spec."""
    from olav.core.api_operation_policy import derive_operation_policy

    policies = []
    paths = spec.get("paths", {})

    for path_str, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        for method in ("get", "post", "put", "patch", "delete", "head", "options"):
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue

            operation_id = op.get("operationId", "")
            vendor_extensions = {}
            if "x-olav-intent" in op:
                vendor_extensions["x-olav-intent"] = op["x-olav-intent"]
            if "x-olav-approval" in op:
                vendor_extensions["x-olav-approval"] = op["x-olav-approval"]

            policy = derive_operation_policy(
                domain=domain,
                path=path_str,
                method=method,
                operation_id=operation_id,
                vendor_extensions=vendor_extensions or None,
            )
            policies.append(policy)

    return policies


# ---------------------------------------------------------------------------
# Main tool function
# ---------------------------------------------------------------------------


def register_api_schema(
    url_or_path: str,
    domain: str = "platform",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Parse an OpenAPI 3.x spec and classify each field via ``classify_field``.

    Fields with high confidence are automatically mapped to standard names.
    Fields with medium confidence are LLM-confirmed.
    Fields below the confidence threshold are staged as unclassified for future
    evolution via ``trigger_schema_evolve``.

    Parameters
    ----------
    url_or_path:
        HTTP/HTTPS URL **or** local filesystem path to the OpenAPI spec (JSON).
    domain:
        Domain namespace to scope all generated schema mappings
        (default: ``"platform"``).
    dry_run:
        If ``True``, extract and return field metadata without calling
        ``classify_field`` or writing any mutations.

    Returns
    -------
    dict with keys:
        ``fields_found``     — total fields extracted from the spec
        ``matched``          — Tier 0 auto-matched via vector similarity
        ``llm_confirmed``    — Tier 1 LLM-confirmed
        ``unclassified``     — Tier 2 added to evolution pool
        ``errors``           — number of classification errors
        ``staged``           — ``True`` if mutations were staged (``dry_run=False``)
        ``dry_run``          — echoes the ``dry_run`` parameter
    """
    spec = _load_spec(url_or_path)

    # Collect all fields from both components and paths
    component_fields = _fields_from_component_schemas(spec)
    path_fields = _fields_from_paths(spec)
    all_fields = component_fields + path_fields

    # Deduplicate by (name, source) to avoid double-counting $ref expansions
    seen: set[tuple[str, str]] = set()
    unique_fields: list[dict[str, Any]] = []
    for f in all_fields:
        key = (f.get("name", ""), f.get("source", ""))
        if key not in seen:
            seen.add(key)
            unique_fields.append(f)

    if dry_run:
        from dataclasses import asdict

        policies = extract_operation_policies(spec, domain=domain)
        return {
            "fields_found": len(unique_fields),
            "matched": 0,
            "llm_confirmed": 0,
            "unclassified": 0,
            "errors": 0,
            "staged": False,
            "dry_run": True,
            "operation_policies": [asdict(p) for p in policies],
        }

    # Lazy import — classify_field lives in the same tools directory
    try:
        from olav.core.schema_engine import SchemaEngine
        from olav.core.schema_mutation_service import SchemaMutationService
        from olav.core.config import PathsConfig

        paths = PathsConfig()
        staging_dir = Path(paths.DATABASES_DIR) / "staging"
        staging_dir.mkdir(parents=True, exist_ok=True)

        svc = SchemaMutationService(staging_dir=staging_dir)
        engine = SchemaEngine(mutation_service=svc)
    except ImportError as exc:
        from dataclasses import asdict

        policies = extract_operation_policies(spec, domain=domain)
        return {
            "fields_found": len(unique_fields),
            "matched": 0,
            "llm_confirmed": 0,
            "unclassified": 0,
            "errors": 1,
            "staged": False,
            "dry_run": False,
            "error_detail": f"Import error: {exc}",
            "operation_policies": [asdict(p) for p in policies],
        }

    counters = {"matched": 0, "llm_confirmed": 0, "unclassified": 0, "errors": 0}

    for field in unique_fields:
        field_metadata = {
            "name": field.get("name", ""),
            "description": field.get("description", ""),
            "type": field.get("type", ""),
            "example": field.get("example", ""),
            "command": field.get("command", ""),
            "source": field.get("source", ""),
            "domain": domain,
        }
        try:
            result = engine.classify_field(field_metadata)
            status = result.get("status", "unclassified")
            if status == "matched":
                counters["matched"] += 1
            elif status == "llm_confirmed":
                counters["llm_confirmed"] += 1
            else:
                counters["unclassified"] += 1
        except Exception:  # noqa: BLE001
            counters["errors"] += 1

    from dataclasses import asdict

    policies = extract_operation_policies(spec, domain=domain)
    return {
        "fields_found": len(unique_fields),
        "matched": counters["matched"],
        "llm_confirmed": counters["llm_confirmed"],
        "unclassified": counters["unclassified"],
        "errors": counters["errors"],
        "staged": True,
        "dry_run": False,
        "operation_policies": [asdict(p) for p in policies],
    }
