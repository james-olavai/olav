"""Read and parse API schema files (OpenAPI, WSDL)."""

from typing import Any, Dict, Optional

from langchain_core.tools import tool


@tool
def read_api_schema(
    source: str,
    schema_type: str = "openapi",
    tag_filter: str = "",
) -> dict:
    """Read and parse API schema files.

    Returns a COMPACT summary suitable for LLM planning:
    - tags_summary: per-tag endpoint counts + sample paths (use this to choose tag_groups)
    - authentication: security schemes (use this to choose auth_type)
    - endpoints: lightweight list (path, method, operation_id, tags) — no parameter noise
    - When tag_filter is set, only endpoints for that tag are returned (detailed view)

    Args:
        source: Path to schema file (local or URL), or inline schema content
        schema_type: Type of schema (openapi, wsdl, postman, json)
        tag_filter: If set, return detailed endpoints for this specific tag only

    Returns:
        dict with parsed schema details including tags_summary, auth, endpoints
    """
    import json
    from collections import defaultdict
    from pathlib import Path
    from urllib.parse import urlparse

    import yaml

    result: Dict[str, Any] = {
        "source": source,
        "schema_type": schema_type,
        "status": "success",
        "endpoints": [],
        "tags_summary": {},
        "authentication": {},
        "total_endpoints": 0,
    }

    try:
        parsed = urlparse(source)

        if parsed.scheme in ("http", "https"):
            import requests
            response = requests.get(source, timeout=30)
            content = response.text
        elif Path(source).exists():
            content = Path(source).read_text()
        else:
            content = source

        if schema_type == "openapi" or "openapi" in content.lower()[:500]:
            data = (
                yaml.safe_load(content)
                if content.lstrip().startswith(("---", "#"))
                else json.loads(content)
            )

            info = data.get("info", {})
            result["title"] = info.get("title", "Unknown API")
            result["version"] = info.get("version", "1.0.0")

            # Extract auth schemes (compact — just type info)
            sec_schemes = data.get("components", {}).get("securitySchemes", {})
            result["authentication"] = {
                k: {
                    "type": v.get("type"),
                    "scheme": v.get("scheme"),
                    "in": v.get("in"),
                    "name": v.get("name"),
                }
                for k, v in sec_schemes.items()
            }

            # Build compact endpoint list + tags_summary
            paths = data.get("paths", {})
            tag_counts: Dict[str, Any] = defaultdict(lambda: {"count": 0, "methods": defaultdict(int), "sample_paths": []})
            all_endpoints = []

            for path, methods in paths.items():
                for method, details in methods.items():
                    if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        continue
                    tags = details.get("tags", [])
                    operation_id = details.get("operationId", "")
                    ep = {
                        "path": path,
                        "method": method.upper(),
                        "operation_id": operation_id,
                        "tags": tags,
                        "summary": details.get("summary", ""),
                    }
                    all_endpoints.append(ep)

                    for tag in tags:
                        tag_counts[tag]["count"] += 1
                        tag_counts[tag]["methods"][method.upper()] += 1
                        if len(tag_counts[tag]["sample_paths"]) < 3:
                            tag_counts[tag]["sample_paths"].append(path)

            result["total_endpoints"] = len(all_endpoints)

            # Compact tags_summary (no parameter noise)
            result["tags_summary"] = {
                tag: {
                    "endpoint_count": info["count"],
                    "methods": dict(info["methods"]),
                    "sample_paths": info["sample_paths"],
                }
                for tag, info in sorted(tag_counts.items())
            }

            # Return endpoints: filtered (detailed) or compact overview
            if tag_filter:
                result["endpoints"] = [e for e in all_endpoints if tag_filter in e["tags"]]
                result["tag_filter_applied"] = tag_filter
            else:
                # Compact: no parameters, grouped by first tag prefix, max 200 entries
                result["endpoints"] = [
                    {"path": e["path"], "method": e["method"], "operation_id": e["operation_id"], "tags": e["tags"]}
                    for e in all_endpoints[:200]
                ]
                if len(all_endpoints) > 200:
                    result["endpoints_truncated"] = True
                    result["note"] = (
                        f"Showing 200 of {len(all_endpoints)} endpoints. "
                        "Use tag_filter='<tag>' to see all endpoints for a specific tag."
                    )

        elif schema_type == "wsdl":
            result["status"] = "unsupported"
            result["error"] = "WSDL parsing not yet implemented"
        else:
            result["status"] = "unsupported"
            result["error"] = f"Schema type {schema_type} not supported"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result
