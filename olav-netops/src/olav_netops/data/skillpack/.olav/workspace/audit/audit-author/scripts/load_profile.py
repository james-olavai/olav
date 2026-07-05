#!/usr/bin/env python3
"""load_profile — list or read audit profiles.

Merges the former ``list_profiles`` and ``read_profile`` scripts into a
single entry point selected by the ``action`` parameter.

  action="list"  → enumerate all profiles in the profiles directory
  action="read"  → parse a named profile and return its jobs as structured data

Usage (execute_skill_script):
    load_profile(action="list")
    load_profile(action="read", name="bgp_health")
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Literal


def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        pass
    # Fallback: walk up from this file to find the profiles dir
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "audit" / "profiles"
        if candidate.is_dir():
            return str(candidate)
    return ".olav/workspace/audit/profiles"


def _first_header(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8").splitlines()[:20]:
            line = line.strip()
            if line.startswith("# ") and not line.startswith("# !"):
                return line[2:].strip()
    except Exception:
        pass
    return ""


def _list(profiles_dir: str | None) -> dict:
    directory = Path(profiles_dir or _default_profiles_dir())
    if not directory.exists():
        return {
            "profiles_dir": str(directory),
            "profiles": [],
            "count": 0,
            "message": f"Directory '{directory}' does not exist yet.",
        }
    profiles = []
    for p in sorted(directory.glob("*.md")):
        profiles.append({
            "name": p.stem,
            "filename": p.name,
            "title": _first_header(p),
            "size_bytes": p.stat().st_size,
        })
    return {
        "profiles_dir": str(directory),
        "count": len(profiles),
        "profiles": profiles,
    }


def _read(name: str, profiles_dir: str | None) -> dict:
    directory = Path(profiles_dir or _default_profiles_dir())
    profile_path = directory / f"{name}.md"

    if not profile_path.exists():
        available = [p.stem for p in directory.glob("*.md")] if directory.exists() else []
        return {
            "error": f"Profile '{name}.md' not found in '{directory}'.",
            "available_profiles": available,
            "hint": "Call load_profile(action='list') to see all available profiles.",
        }

    raw = profile_path.read_text(encoding="utf-8")

    frontmatter_text = ""
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            frontmatter_text = parts[1].strip()
            body = parts[2].strip()

    metadata: dict = {}
    jobs: list[dict] = []
    try:
        import yaml  # type: ignore
        metadata = yaml.safe_load(frontmatter_text) or {}
        jobs = metadata.get("jobs", [])
    except Exception as exc:
        return {
            "name": name,
            "file_path": str(profile_path),
            "error": f"YAML parse error: {exc}",
            "raw_frontmatter": frontmatter_text[:500],
        }

    return {
        "name": metadata.get("name", name),
        "version": metadata.get("version", "unknown"),
        "file_path": str(profile_path),
        "job_count": len(jobs),
        "job_names": [j.get("name", f"job_{i}") for i, j in enumerate(jobs)],
        "jobs": jobs,
        "body": body,
        "body_preview": body[:300] if body else "",
        "persist_findings_to_db": metadata.get("persist_findings_to_db", False),
        "max_findings_per_job": metadata.get("max_findings_per_job", 50),
        "raw_yaml": frontmatter_text,
    }


def load_profile(
    action: Literal["list", "read"] = "list",
    name: str | None = None,
    profiles_dir: str | None = None,
) -> dict:
    """List or read audit profiles.

    Args:
        action:       "list" to enumerate all profiles; "read" to parse one.
        name:         Profile stem (no .md) — required when action="read".
        profiles_dir: Override directory. Defaults to config value.

    Returns:
        For "list": {"profiles_dir", "count", "profiles": [{name, filename, title, size_bytes}]}
        For "read": {"name", "version", "job_count", "jobs", "body", ...}
                    or {"error": "..."} when not found.
    """
    if action == "list":
        return _list(profiles_dir)
    elif action == "read":
        if not name:
            return {"error": "name is required for action='read'"}
        return _read(name, profiles_dir)
    else:
        return {"error": f"unknown action {action!r}; use 'list' or 'read'"}


if __name__ == "__main__":
    _args = json.loads(sys.stdin.read() or "{}")
    print(json.dumps(load_profile(**_args), default=str, ensure_ascii=False))
