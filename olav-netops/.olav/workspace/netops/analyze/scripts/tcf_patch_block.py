#!/usr/bin/env python3
"""Skill script: surgical edit of one CliBlock in a TCF spec.

Use this when the operator (or sim agent under operator instruction)
wants to make a TARGETED change to an existing TCF — typically in
response to a lab finding or a manual review note.  Non-destructive:
only the requested lines change; everything else (other devices,
lab section, post_check, tvt, manual edits) is preserved.

Args (stdin JSON):
    spec_path:    str           — path to the TCF spec yaml (required)
    device:       str           — device name (must exist in tcf.devices)
    add_lines:    list[str]     — lines to append (deduped)
    del_lines:    list[str]     — lines to remove (exact match)
    action:       str           — CliBlock.action (default "configure")
    phase:        int           — CliBlock.phase (default 1)
    rollback:    bool           — edit rollback block instead of implementation
    revised_by:   str           — actor name for audit (default "ops-analyze")

Output (stdout JSON): envelope from
``olav.core.cab.tcf_patch.tcf_patch_block`` including:
    status, spec_path, device, phase, action, rollback,
    added, removed, cli_after, revision_count, last_revised_by
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
    device = args.get("device")
    if not spec_path or not device:
        print(json.dumps({
            "status": "error",
            "error": "spec_path and device are required",
        }))
        return 1

    try:
        from olav.core.cab import tcf_patch_block
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.cab.tcf_patch_block unavailable: "
                     f"{type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = tcf_patch_block(
            spec_path,
            device,
            add_lines=args.get("add_lines") or [],
            del_lines=args.get("del_lines") or [],
            action=args.get("action", "configure"),
            phase=int(args.get("phase", 1)),
            rollback=bool(args.get("rollback", False)),
            revised_by=args.get("revised_by", "ops-analyze"),
        )
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
