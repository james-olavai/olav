#!/usr/bin/env python3
"""Skill script: save SR Linux config lines for a lab node to dropbox.

Args (stdin JSON):
    lab_name:     str
    node:         str
    config_lines: list[str]

Output (stdout JSON): dict from olav.core.lab.save_lab_config —
``saved`` (bool), ``node``, ``lab_name``, ``lines``, ``path``,
``message`` (or ``error``).
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        raw = sys.stdin.read()
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"saved": False, "error": f"args JSON parse failed: {exc}"}))
        return 1

    try:
        from olav.core.lab import save_lab_config
    except Exception as exc:
        print(json.dumps({
            "saved": False,
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = save_lab_config(**args)
    except TypeError as exc:
        print(json.dumps({"saved": False, "error": f"bad args: {exc}"}))
        return 1
    except Exception as exc:
        print(json.dumps({"saved": False, "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(result, default=str))
    return 0 if result.get("saved") else 1


if __name__ == "__main__":
    sys.exit(main())
