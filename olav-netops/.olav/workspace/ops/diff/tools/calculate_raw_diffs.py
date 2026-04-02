#!/usr/bin/env python3
"""
calculate_raw_diffs — LangChain @tool wrapper for config diff computation.

Triggers (or back-fills) raw_diffs for a pair of snapshots.
The core logic lives in olav.core.calculate_diffs (lean, no staging).

Usage (agent call):
    calculate_raw_diffs(
        snapshot_id_1="2026-03-01_2200",
        snapshot_id_2="2026-03-02_0900",
    )
    calculate_raw_diffs(
        snapshot_id_1="2026-03-01_2200",
        snapshot_id_2="2026-03-02_0900",
        devices=["R1", "SW-CORE-01"],
        platform="cisco_ios",
    )
"""

from __future__ import annotations

from typing import Optional

from langchain_core.tools import tool


@tool
def calculate_raw_diffs(
    snapshot_id_1: str,
    snapshot_id_2: str,
    devices: list[str] | None = None,
    commands: list[str] | None = None,
    platform: str | None = None,
) -> str:
    """Compute and persist config diffs between two snapshots into raw_diffs.

    Reads raw .txt files from disk, computes unified diff, writes to raw_diffs.
    Safe to re-run (idempotent INSERT OR REPLACE).

    Useful for back-filling raw_diffs for snapshots that predate automatic
    Stage 3 execution, or for targeted re-computation after template changes.

    Args:
        snapshot_id_1: Baseline snapshot ID (earlier).
        snapshot_id_2: Target snapshot ID (later).
        devices:       Restrict to these device names. None = all devices.
        commands:      Restrict to these commands. None = config-type from YAML.
        platform:      Platform for noise filtering (e.g. 'cisco_ios',
                       'nxos', 'huawei_vrp', 'juniper', 'paloalto').
                       None = no noise filtering.

    Returns:
        Human-readable summary of the operation.
    """
    from olav.core.calculate_diffs import calculate_diffs

    result = calculate_diffs(
        snapshot_id_1=snapshot_id_1,
        snapshot_id_2=snapshot_id_2,
        devices=devices,
        commands=commands,
        platform=platform,
    )

    if result["status"] == "success":
        return (
            f"✅ Diff complete: {result['records_written']} records "
            f"({snapshot_id_1} → {snapshot_id_2})."
        )
    elif result["status"] == "no_data":
        return (
            f"⚠️  No config files found for snapshots "
            f"'{snapshot_id_1}' / '{snapshot_id_2}'. "
            f"{result.get('message', '')}"
        )
    else:
        return f"❌ Unexpected status: {result}"
