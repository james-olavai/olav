#!/usr/bin/env python3
"""Skill script: build a CLAB topology YAML from netops.v_l2_links_auto.

Per ADR-0008, this script is invoked by the ops-lab agent via
``execute_skill_script(skill_name="lab", script_name="generate_clab_topology.py", args={...})``.

Args (read from stdin as JSON):
    nodes: list[str]            — prod device names, e.g. ["R1", "R4"]
    lab_name: str               — CLAB lab name (default "cab_lab")
    image: str | None           — SR Linux image (optional override)
    snapshot_id: str | None     — netops snapshot to read from (optional)

Output (printed to stdout as JSON-wrapping the raw YAML):
    {"status": "ok", "yaml": "<topology yaml string>"}
or
    {"status": "error", "error": "<message>"}

The Python helper at ``olav.core.lab.topology.generate_clab_topology``
is the single source of truth — this script is a thin shim.
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
        from olav.core.lab.topology import generate_clab_topology
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"olav.core.lab unavailable: {type(exc).__name__}: {exc}",
        }))
        return 1

    try:
        yaml_text = generate_clab_topology(**args)
    except TypeError as exc:
        print(json.dumps({"status": "error", "error": f"bad args: {exc}"}))
        return 1
    except Exception as exc:
        print(json.dumps({
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }))
        return 1

    print(json.dumps({"status": "ok", "yaml": yaml_text}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
