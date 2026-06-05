#!/usr/bin/env python3
"""
write_automation — Save a generated script to .olav/automations/<category>/.

User-created automations live here, separate from platform skill scripts
in .olav/workspace/*/scripts/. Scripts persist across sessions and can be
reused, modified, or scheduled by the admin agent.
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

VALID_CATEGORIES = {"backup", "sync", "bulk", "monitoring", "netbox", "misc"}
VALID_FORMATS = {"py", "sh", "yaml", "yml"}


def write_automation(name: str, content: str, category: str = "misc", fmt: str = "py") -> dict:
    if category not in VALID_CATEGORIES:
        return {"status": "error", "error": f"Invalid category '{category}'. Valid: {sorted(VALID_CATEGORIES)}"}
    if fmt not in VALID_FORMATS:
        return {"status": "error", "error": f"Invalid format '{fmt}'. Valid: {sorted(VALID_FORMATS)}"}

    dest_dir = PROJECT_ROOT / ".olav" / "automations" / category
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest = dest_dir / f"{name}.{fmt}"
    dest.write_text(content, encoding="utf-8")
    if fmt == "sh":
        dest.chmod(0o755)

    return {
        "status": "ok",
        "path": str(dest.relative_to(PROJECT_ROOT)),
        "abs_path": str(dest),
        "category": category,
        "size_bytes": len(content.encode()),
    }


if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(json.dumps(write_automation(**args)))
