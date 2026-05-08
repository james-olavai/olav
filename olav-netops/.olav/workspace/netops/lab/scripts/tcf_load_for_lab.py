#!/usr/bin/env python3
"""Skill script: load + validate a TCF spec, derive R88/R89 args.

Args (stdin JSON):
    spec_path: str   — absolute or repo-relative path to a .tcf.yaml

Output (stdout JSON): the dict envelope returned by
``olav.core.cab.tcf_lab.tcf_load_for_lab``, including:
  * change_id, title, risk_class, intent
  * device_names, devices
  * r88_args, r89_args (with r89_error if intent unsupported)
  * post_check, tvt, required_tests, optional_tests
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

    spec_path = args.get("spec_path")
    if not spec_path:
        print(json.dumps({"status": "error", "error": "spec_path is required"}))
        return 1

    try:
        from olav.core.cab import tcf_load_for_lab
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.cab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = tcf_load_for_lab(spec_path)
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }))
        return 1

    print(json.dumps(result, default=str))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
