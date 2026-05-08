#!/usr/bin/env python3
"""Skill script: push SR Linux CLI to a single ContainerLab node.

Args (stdin JSON):
    lab_name:     str
    node:         str
    config_lines: list[str]
    timeout:      int    (default 60)

Output (stdout JSON): dict from olav.core.lab.push_node_config —
``status`` ("ok" | "error" | "dry_run_failed"), ``stdout``,
``committed``, ``node`` (or ``error``).
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        raw = sys.stdin.read()
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"status": "error", "error": f"args JSON parse failed: {exc}"}))
        return 1

    try:
        from olav.core.lab import push_node_config
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = push_node_config(**args)
    except TypeError as exc:
        print(json.dumps({"status": "error", "error": f"bad args: {exc}"}))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(result, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
