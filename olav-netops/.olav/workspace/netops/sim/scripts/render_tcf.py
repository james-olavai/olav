#!/usr/bin/env python3
"""Skill script: render TCF from a prose change plan.

Phase C of R-AGENT-HIERARCHY.  Sim sub-agent outputs a Markdown
plan with `## Change Summary` block; this script extracts it,
queries the DB for facts (ASN, loopback, platform), renders CLI
from per-intent + per-platform templates, and writes the TCF YAML.

Args (stdin JSON):
    plan_text:         str — full Markdown plan from sim (required)
    output_dir:        str — default "exports/cab"
    lab_subnet:        str — default "172.16.99.0/30"
    risk_class:        str — default "medium"

Output (stdout JSON): envelope from
``olav.core.cab.tcf_writer.render_tcf_from_change_plan`` —
    On success: {"status": "ok", "spec_path": "...", "facts": {...},
                 "warnings": [...]}
    On error:   {"status": "error", "error": "...", "blockers": [...],
                 "facts": {...}}
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    try:
        raw = sys.stdin.read()
        args = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({
            "status": "error",
            "error": f"args JSON parse failed: {exc}",
        }))
        return 1

    plan_text = args.get("plan_text")
    if not plan_text or not isinstance(plan_text, str):
        print(json.dumps({
            "status": "error",
            "error": (
                "plan_text is required — pass the full Markdown change "
                "plan including the `## Change Summary` YAML block."
            ),
        }))
        return 1

    try:
        from olav.core.cab import render_tcf_from_change_plan
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": (
                f"olav.core.cab.render_tcf_from_change_plan unavailable: "
                f"{type(exc).__name__}: {exc}"
            ),
        }))
        return 1

    try:
        result = render_tcf_from_change_plan(
            plan_text,
            output_dir=args.get("output_dir", "exports/cab"),
            lab_subnet=args.get("lab_subnet", "172.16.99.0/30"),
            risk_class=args.get("risk_class", "medium"),
            created_by="sim",
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
