#!/usr/bin/env python3
"""Skill script: LLM + DB schema discovery → view_recipes.

Args (stdin JSON): force_refresh=False, concepts_filter=None

Output (stdout JSON): dict from olav.core.curator.discover_view_schemas.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        raw = sys.stdin.read()
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"error": f"args JSON parse failed: {exc}"}))
        return 1

    try:
        from olav.core.curator import discover_view_schemas
    except Exception as exc:
        print(json.dumps({
            "error": f"olav.core.curator unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = discover_view_schemas(**args)
    except TypeError as exc:
        print(json.dumps({"error": f"bad args: {exc}"}))
        return 1
    except Exception as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
