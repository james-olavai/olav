#!/usr/bin/env python3
"""list_profiles — list all available audit profiles.

Single-call terminal operation: no arguments needed.
Call once, present the table to the user, and stop immediately.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def _default_profiles_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_profiles_dir
    except Exception:
        pass
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "audit" / "profiles"
        if candidate.is_dir():
            return str(candidate)
    return ".olav/workspace/audit/profiles"


def list_profiles() -> dict:
    directory = Path(_default_profiles_dir())
    if not directory.exists():
        return {
            "profiles_dir": str(directory),
            "profiles": [],
            "count": 0,
            "message": f"Directory '{directory}' does not exist yet.",
        }
    profiles = []
    for p in sorted(directory.glob("*.md")):
        title = ""
        try:
            for line in p.read_text(encoding="utf-8").splitlines()[:20]:
                line = line.strip()
                if line.startswith("# ") and not line.startswith("# !"):
                    title = line[2:].strip()
                    break
        except Exception:
            pass
        profiles.append({
            "name": p.stem,
            "filename": p.name,
            "title": title,
            "size_bytes": p.stat().st_size,
        })
    return {
        "profiles_dir": str(directory),
        "count": len(profiles),
        "profiles": profiles,
    }


if __name__ == "__main__":
    sys.stdin.read()  # consume any stdin (no args needed)
    print(json.dumps(list_profiles(), default=str, ensure_ascii=False))
