#!/usr/bin/env python3
"""Skill script: atomic write-back of lab results into a TCF.

Args (stdin JSON):
    spec_path:        str
    verdict:          str   ("PASS" / "FAIL" / "BLOCKED")
    lab_name:         str
    snapshot_id:      str   (optional)
    diagnosis:        str   (optional)
    recommendation:   list[str]   (optional)
    tvt_test_ids:     list[str]   (optional, parallel with the next 2)
    tvt_actual_lab:   list[str]   (optional)
    tvt_status:       list[str]   (optional)
    journal:          list[dict] | str   (optional; JSON string accepted)

Output (stdout JSON): dict from
``olav.core.cab.tcf_lab.tcf_record_lab_run`` —
``status``, ``spec_path``, ``verdict``, ``updated_tvt``,
``journal_entries``, ``lab_name`` (or ``error`` on failure).
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
        from olav.core.cab import tcf_record_lab_run
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.cab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = tcf_record_lab_run(spec_path, **args)
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
