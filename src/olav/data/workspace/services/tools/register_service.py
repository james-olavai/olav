#!/usr/bin/env python3
"""register_service — append a new entry to ``.olav/config/services.yaml``.

ARCH-21 Sprint 3 Step A new tool. Append-only by design: overwriting an
existing service entry requires the operator to remove it manually so
config merges stay auditable.

Typical usage::

    register_service(
        name="netbox-stage",
        endpoint="https://netbox.stage.internal/api",
        auth_type="bearer",
        auth_token_env="NETBOX_STAGE_TOKEN",
    )

Returns ``{"status": "success", "path": "...", "entry": {...}}`` on
insert, ``{"status": "already_registered", ...}`` on duplicate name.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import tool


_VALID_AUTH_TYPES = frozenset({"none", "bearer", "basic"})


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


def _rel_path(p: Path) -> str:
    """Prefer a project-relative string for logs, fall back to absolute."""
    try:
        return str(p.relative_to(_PROJECT_ROOT))
    except ValueError:
        return str(p)


@tool
def register_service(
    name: str,
    endpoint: str,
    auth_type: str = "none",
    auth_token_env: str | None = None,
    kind: str | None = None,
) -> dict[str, Any]:
    """Register a new service in ``.olav/config/services.yaml``.

    Call `tool_help('register_service')` for the full config schema.

    Args:
        name: Unique registry key (e.g. ``"netbox-stage"``).
        endpoint: HTTP base URL.
        auth_type: One of ``"none"`` / ``"bearer"`` / ``"basic"``.
        auth_token_env: Env-var name holding the token (for bearer/basic).
        kind: Optional hint for deploy/stop (e.g. ``"containerlab"``).

    Returns:
        On success: ``{"status": "success", "path": "...", "entry": {...}}``.
        On duplicate name: ``{"status": "already_registered", "existing": ...}``.
        On validation error: ``{"status": "error", "message": "..."}``.
    """
    import yaml

    if not name or not isinstance(name, str):
        return {"status": "error", "message": "name must be a non-empty string"}
    if not endpoint or not isinstance(endpoint, str):
        return {"status": "error", "message": "endpoint must be a non-empty string"}
    if auth_type not in _VALID_AUTH_TYPES:
        return {
            "status": "error",
            "message": f"auth_type must be one of {sorted(_VALID_AUTH_TYPES)}",
        }
    if auth_type in ("bearer", "basic") and not auth_token_env:
        return {
            "status": "error",
            "message": f"auth_type={auth_type!r} requires auth_token_env",
        }

    path = _services_yaml_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing (if any) — tolerate missing file.
    doc: dict[str, Any]
    if path.exists():
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            return {"status": "error", "message": f"{path} is not valid YAML: {exc}"}
    else:
        doc = {}

    services = doc.setdefault("services", {})
    if not isinstance(services, dict):
        return {
            "status": "error",
            "message": f"{path} has a non-mapping 'services' field; fix by hand",
        }

    if name in services:
        return {
            "status": "already_registered",
            "path": _rel_path(path),
            "existing": services[name],
            "hint": (
                f"To replace {name!r}, remove it from {path} manually then "
                "re-run register_service."
            ),
        }

    entry: dict[str, Any] = {"endpoint": endpoint, "auth_type": auth_type}
    if auth_token_env:
        entry["auth_token_env"] = auth_token_env
    if kind:
        entry["kind"] = kind

    services[name] = entry
    path.write_text(yaml.safe_dump(doc, sort_keys=True, allow_unicode=True), encoding="utf-8")

    return {
        "status": "success",
        "path": _rel_path(path),
        "entry": {"name": name, **entry},
    }
