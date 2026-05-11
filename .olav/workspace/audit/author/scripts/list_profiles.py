#!/usr/bin/env python3
"""list_profiles — enumerate available audit profiles.

Skill script (R92.3 fold pattern) invoked via:
    execute_skill_script(skill_name='auditor', script_name='list_profiles.py')

Reads ``<workspace>/audit/profiles/*.md`` and returns each profile's
filename + first non-empty markdown header line as a quick description.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _resolve_profiles_dir() -> Path:
    """Find the audit profiles dir relative to runtime workspace."""
    if env := os.environ.get("OLAV_WORKSPACE_ROOT"):
        return Path(env) / "audit" / "profiles"
    cwd_workspace = Path.cwd() / ".olav" / "workspace" / "audit" / "profiles"
    if cwd_workspace.exists():
        return cwd_workspace
    # Fallback — install-time path
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "audit" / "profiles"
        if candidate.is_dir():
            return candidate
    return Path(".olav/workspace/audit/profiles")


def _first_header(path: Path) -> str:
    """Pull the first H1 (`# ...`) from a markdown file."""
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:20]:
            line = line.strip()
            if line.startswith("# ") and not line.startswith("# !"):
                return line[2:].strip()
    except Exception:
        pass
    return ""


def main() -> int:
    profiles_dir = _resolve_profiles_dir()
    if not profiles_dir.is_dir():
        print(json.dumps({
            "status": "error",
            "message": f"profiles dir not found: {profiles_dir}",
        }, ensure_ascii=False))
        return 1

    profiles: list[dict] = []
    for p in sorted(profiles_dir.glob("*.md")):
        profiles.append({
            "name": p.stem,
            "filename": p.name,
            "title": _first_header(p),
            "size_bytes": p.stat().st_size,
        })

    print(json.dumps({
        "status": "success",
        "profiles_dir": str(profiles_dir),
        "count": len(profiles),
        "profiles": profiles,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
