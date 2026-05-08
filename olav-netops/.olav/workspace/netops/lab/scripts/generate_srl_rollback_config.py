#!/usr/bin/env python3
"""Skill script: SRL rollback CLI generator (R90 Phase 6).

Args (stdin JSON): same shape as generate_srl_lab_config —
nodes / loopbacks / asns + optional intent_type / lab_subnet.

Output (stdout JSON): the JSON envelope produced by
``olav.core.lab.srl_rollback.generate_srl_rollback_config``,
containing per-lab-node ``delete /`` CLI sequences.
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
        from olav.core.lab.srl_rollback import generate_srl_rollback_config
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result_json = generate_srl_rollback_config(**args)
    except TypeError as exc:
        print(json.dumps({"status": "error", "error": f"bad args: {exc}"}))
        return 1
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }))
        return 1

    print(result_json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
