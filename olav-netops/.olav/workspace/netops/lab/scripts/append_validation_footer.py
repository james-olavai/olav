#!/usr/bin/env python3
"""Skill script: append a Lab Validation Footer to a markdown spec.

Legacy F3 helper; prefer ``tcf_record_lab_run.py`` for TCF-shaped
specs. This exists for plain markdown CAB specs.

Args (stdin JSON):
    spec_path:        str
    decision:         str   ("PASS" / "FAIL" / "BLOCKED")
    lab_name:         str
    snapshot_id:      str   (optional)
    evidence:         list[str]   (optional)
    recommendation:   list[str]   (optional)
    full_report_path: str   (optional)

Output (stdout JSON): dict from
``olav.core.lab.spec_footer.append_validation_footer``.
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

    spec_path = args.pop("spec_path", None)
    if not spec_path:
        print(json.dumps({"status": "error", "error": "spec_path is required"}))
        return 1

    try:
        from olav.core.lab import append_validation_footer
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = append_validation_footer(spec_path, **args)
    except TypeError as exc:
        print(json.dumps({"status": "error", "error": f"bad args: {exc}"}))
        return 1
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
