#!/usr/bin/env python3
"""
write_compose_file — Write files into a service directory under .olav/services/<name>/.

Creates the directory if it does not exist. Call this BEFORE deploy_service.
Sandboxed to .olav/services/ — cannot write outside that tree.
"""

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


PROJECT_ROOT = _find_project_root()
_SERVICES_ROOT = PROJECT_ROOT / ".olav" / "services"


def write_compose_file(
    name: str,
    content: str,
    filename: str = "docker-compose.yml",
) -> dict:
    """Write a file into the service directory .olav/services/<name>/<filename>.

    Use this to create docker-compose.yml and any supporting files (env files,
    config files) BEFORE calling deploy_service.

    Common filenames:
      - "docker-compose.yml"   (required before deploy_service)
      - "env/<name>.env"       (environment variables)
      - "config/config.py"     (service-specific config, e.g. NetBox)
      - "config/nginx.conf"    (service-specific config, e.g. nginx)

    Args:
        name:     Service name (directory under .olav/services/)
        content:  File content as a string
        filename: Relative path within the service dir (default: docker-compose.yml)

    Returns:
        {"success": true, "path": "...", "bytes": N}
        {"success": false, "error": "..."}
    """
    # Validate filename stays within service dir (no ../ escapes)
    service_dir = _SERVICES_ROOT / name
    target = (service_dir / filename).resolve()
    try:
        target.relative_to(_SERVICES_ROOT.resolve())
    except ValueError:
        return {
            "success": False,
            "error": f"filename '{filename}' resolves outside .olav/services/ — forbidden",
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")

    return {
        "success": True,
        "path": str(target.relative_to(PROJECT_ROOT)),
        "bytes": len(content.encode()),
    }


if __name__ == "__main__":
    _args = json.loads(sys.stdin.read() or "{}")
    result = write_compose_file(**_args)
    print(json.dumps(result, default=str))
