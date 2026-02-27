"""Read and parse API schema files (OpenAPI, WSDL)."""

from typing import Optional, Dict, Any

from langchain_core.tools import tool


@tool
def read_api_schema(
    source: str,
    schema_type: str = "openapi",
) -> dict:
    """Read and parse API schema files.

    Args:
        source: Path to schema file (local or URL), or inline schema content
        schema_type: Type of schema (openapi, wsdl, postman, json)

    Returns:
        dict with parsed schema details including endpoints, auth, models
    """
    import yaml
    import json
    from pathlib import Path
    from urllib.parse import urlparse

    result = {
        "source": source,
        "schema_type": schema_type,
        "status": "success",
        "endpoints": [],
        "authentication": {},
        "models": {},
    }

    try:
        # Determine if source is URL, path, or inline
        parsed = urlparse(source)

        if parsed.scheme in ("http", "https"):
            # Fetch from URL
            import requests

            response = requests.get(source, timeout=30)
            content = response.text
        elif Path(source).exists():
            # Read from file
            content = Path(source).read_text()
        else:
            # Assume inline content
            content = source

        # Parse based on type
        if schema_type == "openapi" or "openapi" in content.lower():
            data = (
                yaml.safe_load(content)
                if content.startswith("#") or "---" in content
                else json.loads(content)
            )

            # Extract info
            result["info"] = data.get("info", {})
            result["title"] = result["info"].get("title", "Unknown API")
            result["version"] = result["info"].get("version", "1.0.0")

            # Extract endpoints
            paths = data.get("paths", {})
            for path, methods in paths.items():
                for method, details in methods.items():
                    if method.upper() in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                        result["endpoints"].append(
                            {
                                "path": path,
                                "method": method.upper(),
                                "summary": details.get("summary", ""),
                                "operation_id": details.get("operationId", ""),
                                "parameters": details.get("parameters", []),
                            }
                        )

            # Extract auth
            components = data.get("components", {}).get("securitySchemes", {})
            result["authentication"] = components

            # Extract models
            schemas = components = data.get("components", {}).get("schemas", {})
            result["models"] = schemas

        elif schema_type == "wsdl":
            # Basic WSDL parsing (simplified)
            result["status"] = "unsupported"
            result["error"] = "WSDL parsing not yet implemented"

        else:
            result["status"] = "unsupported"
            result["error"] = f"Schema type {schema_type} not supported"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result
