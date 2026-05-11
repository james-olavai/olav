#!/usr/bin/env python3
"""Skill script: mine recent failures into operational constraints.

Args (stdin JSON): hours=168, limit=50

Output (stdout JSON): dict from olav.core.curator.trace_learner.
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
        from olav.core.curator import trace_learner
    except Exception as exc:
        print(json.dumps({
            "error": f"olav.core.curator unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = trace_learner(**args)
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
