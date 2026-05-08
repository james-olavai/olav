#!/usr/bin/env python3
"""Skill script: deploy a ContainerLab topology + post-deploy workarounds.

Args (stdin JSON):
    yaml_content: str    (topology YAML)
    ssh_host:     str    (optional)
    wait_seconds: int    (default 40)

Output (stdout JSON): dict from olav.core.lab.deploy_lab.
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
        from olav.core.lab import deploy_lab
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = deploy_lab(**args)
    except TypeError as exc:
        print(json.dumps({"status": "error", "error": f"bad args: {exc}"}))
        return 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}))
        return 1

    print(json.dumps(result, default=str))
    return 0 if result.get("status") in ("ok", "deployed") else 1


if __name__ == "__main__":
    sys.exit(main())
