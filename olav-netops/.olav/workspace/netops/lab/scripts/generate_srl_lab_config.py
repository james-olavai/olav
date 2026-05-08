#!/usr/bin/env python3
"""Skill script: deterministic prod→SRL CLI translator (R89).

Args (stdin JSON):
    nodes:        list[str]    e.g. ["R1", "R4"]
    loopbacks:    list[str]    e.g. ["1.1.1.1", "4.4.4.4"]
    asns:         list[int]    e.g. [65000, 65001]
    intent_type:  str          (optional, default "ebgp_direct")
    lab_subnet:   str          (optional, default "172.16.99.0/30")

Output (stdout JSON):
    The same envelope generate_srl_lab_config produces — a JSON
    string with status, configs (per-lab-node SRL CLI), and warnings.

Per ADR-0008 — thin shim over olav.core.lab.srl_render.
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
        from olav.core.lab.srl_render import generate_srl_lab_config
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        # generate_srl_lab_config already returns a JSON string;
        # forward it verbatim so the caller sees the same envelope
        # as the historical MCP tool.
        result_json = generate_srl_lab_config(**args)
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
