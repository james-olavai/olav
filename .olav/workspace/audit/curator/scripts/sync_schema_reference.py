#!/usr/bin/env python3
"""Skill script: regenerate SCHEMA_REFERENCE.md from live DuckDB.

Args (stdin JSON): db_path='', schema_ref_path=''

Output (stdout JSON): dict from olav.core.curator.sync_schema_reference.
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
        from olav.core.curator import sync_schema_reference
    except Exception as exc:
        print(json.dumps({
            "error": f"olav.core.curator unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = sync_schema_reference(**args)
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
