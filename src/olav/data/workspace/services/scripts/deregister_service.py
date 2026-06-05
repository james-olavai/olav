#!/usr/bin/env python3
"""
deregister_service — Remove a service from services.yaml and api_registry.services.

Requires confirmed=True (HITL gate) — deregistration removes the service
endpoint and stops api_request from routing to it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


_PROJECT_ROOT = _find_project_root()
if str(_PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "src"))


def _services_yaml_path() -> Path:
    return _PROJECT_ROOT / ".olav" / "config" / "services.yaml"


def deregister_service(name: str, confirmed: bool = False) -> dict[str, Any]:
    """Remove a service from services.yaml + api_registry.services DuckDB table.

    Args:
        name: Service name to remove (must match key in services.yaml).
        confirmed: Must be True to execute. Returns preview when False.
    """
    import yaml

    if not name:
        return {"status": "error", "error": "name is required"}

    path = _services_yaml_path()
    if not path.exists():
        return {"status": "error", "error": "services.yaml not found"}

    try:
        doc: dict = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        return {"status": "error", "error": f"services.yaml parse error: {exc}"}

    services = doc.get("services", {})
    if name not in services:
        return {
            "status": "not_found",
            "error": f"Service '{name}' is not registered.",
            "registered": sorted(services.keys()),
        }

    existing = services[name]

    if not confirmed:
        return {
            "status": "preview",
            "action": f"Remove service '{name}' from services.yaml and api_registry.services",
            "endpoint": existing.get("endpoint", ""),
            "hint": "Call again with confirmed=True to execute.",
        }

    # Remove from services.yaml
    del services[name]
    doc["services"] = services
    path.write_text(yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")

    # Remove from DuckDB api_registry.services
    try:
        from olav.platform.services.registry_sync import delete_service
        delete_service(name)
        db_status = "removed"
    except Exception as exc:
        db_status = f"yaml removed; db sync failed: {exc}"

    return {
        "status": "ok",
        "removed": name,
        "endpoint": existing.get("endpoint", ""),
        "db_sync": db_status,
    }


if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(deregister_service(**args)))
