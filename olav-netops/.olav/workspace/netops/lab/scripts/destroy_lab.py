#!/usr/bin/env python3
"""Skill script: destroy a ContainerLab lab via the remote CLAB REST API.

Args (stdin JSON):
    lab_name:    str
    timeout:     int | float   (default 30)
    config_path: str | null    (optional override for CLAB credentials JSON)

Output (stdout JSON): dict from olav.core.lab.destroy_lab —
``status`` ("ok"|"error"), ``destroyed`` (bool), ``lab_name``,
``detail`` (or ``error``).

Note on credentials: CLAB_USERNAME / CLAB_PASSWORD are read from
env first, then from the config_path JSON file. The subprocess
inherits the parent agent's env, so credentials work the same way
as the historical @tool wrapper.
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

    if "lab_name" not in args:
        print(json.dumps({"status": "error", "error": "lab_name is required"}))
        return 1

    try:
        from olav.core.lab import destroy_lab
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = destroy_lab(**args)
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
