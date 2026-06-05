#!/usr/bin/env python3
"""
bootstrap_registry — Sync all entries from services.yaml to api_registry.services.

Called by olav init and on-demand to ensure DuckDB reflects the current
services.yaml without requiring individual register/deregister calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


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


def bootstrap_registry() -> dict:
    """Full sync from services.yaml → api_registry.services in main.duckdb."""
    from olav.platform.services.registry_sync import bootstrap_from_yaml
    return bootstrap_from_yaml()


if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(bootstrap_registry(**args)))
