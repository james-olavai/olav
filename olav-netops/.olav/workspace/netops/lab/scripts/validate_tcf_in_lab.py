#!/usr/bin/env python3
"""Skill script: ATOMIC CAB lab validation — runs the full pipeline.

This is **Patch L** — the one-call replacement for the 5+ separate
skill_script invocations the lab agent used to make. It folds:

    tcf_load_for_lab → generate_clab_topology → generate_srl_lab_config
    → save_lab_config (per node) → deploy_and_push_lab
    → exec_on_node (per post_check) → tcf_record_lab_run → destroy_lab

into a single Python call.  Solves
ISSUE-CAB-AGENT-DRIVEN-LAB-VALIDATION-LOOPS — small models stuck in
the multi-step decision loop spent 12+ minutes on tcf_load_for_lab
alone before the runner timed out.

Args (stdin JSON):
    spec_path:               str   — path to the TCF spec yaml (required)
    destroy_on_finish:       bool  — default true; tear down lab when done
    skip_record:             bool  — default false; if true, don't write
                                     verdict back to the spec
    exec_timeout:            float — per-post_check exec timeout (default 30)
    deploy_wait_seconds:     int   — first-deploy wait (default 40)
    post_commit_wait_seconds:int   — post-config-commit settle (default 30)
    convergence_wait_seconds:int   — extra grace before post_checks (default 5)

Output (stdout JSON): envelope from
``olav.core.cab.tcf_validate.validate_tcf_in_lab`` including:
    status, phase, verdict (PASS/FAIL), spec_path, lab_name,
    post_check_results[], tvt_results[], journal[], tcf_recorded,
    lab_destroyed, errors[]
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
        from olav.core.cab import validate_tcf_in_lab
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.cab.validate_tcf_in_lab unavailable: "
                     f"{type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        result = validate_tcf_in_lab(
            spec_path,
            destroy_on_finish=bool(args.get("destroy_on_finish", True)),
            skip_record=bool(args.get("skip_record", False)),
            exec_timeout=float(args.get("exec_timeout", 30.0)),
            deploy_wait_seconds=int(args.get("deploy_wait_seconds", 40)),
            post_commit_wait_seconds=int(args.get("post_commit_wait_seconds", 30)),
            convergence_wait_seconds=int(args.get("convergence_wait_seconds", 5)),
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
