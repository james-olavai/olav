"""Sim-side TCF construction (Python helper for ops-analyze).

Per ADR-0007 (R91 Step 3), the agent imports this from
``run_python_simulation`` instead of calling an MCP wrapper.

Small-model friendly shape: top-level scalars + parallel arrays for
devices, JSON-string args for nested lists. Same pattern that made
R89 work after the v1 ``list[dict]`` failure mode.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tcf_io import tcf_emit
from .tcf_schema import CabTcf, CliBlock, Device, Intent, PostCheck, TvtRow


def _parse_json_list(label: str, raw: str) -> list:
    try:
        value = json.loads(raw) if raw else []
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, list):
        raise ValueError(
            f"{label} must be a JSON array; got {type(value).__name__}"
        )
    return value


def tcf_emit_from_sim(
    *,
    change_id: str,
    title: str,
    intent_type: str,
    device_names: list[str],
    device_platforms: list[str],
    device_loopbacks: list[str],
    device_asns: list[int],
    implementation_json: str,
    device_intfs: list[str] | None = None,
    rollback_json: str = "[]",
    post_check_json: str = "[]",
    tvt_json: str = "[]",
    required_test_ids: list[str] | None = None,
    optional_test_ids: list[str] | None = None,
    lab_subnet: str = "172.16.99.0/30",
    risk_class: str = "medium",
    output_dir: str | Path = "exports/cab",
    created_by: str = "ops-analyze",
) -> dict[str, Any]:
    """Build + atomically write a TCF for a single CAB change.

    Returns a dict envelope with ``status``, ``spec_path``, and basic
    counts. On validation error returns ``status="error"`` and writes
    no file.
    """
    n = len(device_names)
    if not (len(device_platforms) == len(device_loopbacks) == len(device_asns) == n):
        return {
            "status": "error",
            "error": (
                f"device_* arrays must all have the same length: "
                f"names={n} platforms={len(device_platforms)} "
                f"loopbacks={len(device_loopbacks)} asns={len(device_asns)}"
            ),
        }
    if device_intfs is not None and len(device_intfs) != n:
        return {
            "status": "error",
            "error": (
                f"device_intfs (optional) length {len(device_intfs)} "
                f"must match device_names length {n}"
            ),
        }

    try:
        impl_raw = _parse_json_list("implementation_json", implementation_json)
        rollback_raw = _parse_json_list("rollback_json", rollback_json)
        post_check_raw = _parse_json_list("post_check_json", post_check_json)
        tvt_raw = _parse_json_list("tvt_json", tvt_json)
    except ValueError as exc:
        return {"status": "error", "error": str(exc)}

    try:
        devices: list[Device] = []
        for i, name in enumerate(device_names):
            d_kwargs: dict = {
                "name": name,
                "platform": device_platforms[i],
                "prod_loopback": device_loopbacks[i],
                "prod_asn": int(device_asns[i]),
            }
            if device_intfs is not None:
                d_kwargs["prod_intf"] = device_intfs[i]
            devices.append(Device(**d_kwargs))

        intent = Intent(type=intent_type, lab_subnet=lab_subnet)

        implementation = [CliBlock(**raw) for raw in impl_raw]
        rollback = [CliBlock(**raw) for raw in rollback_raw]
        post_check = [PostCheck(**raw) for raw in post_check_raw]
        tvt = [TvtRow(**raw) for raw in tvt_raw]

        tcf = CabTcf(
            change_id=change_id,
            title=title,
            created_by=created_by,
            created_at=datetime.now(UTC),
            risk_class=risk_class,
            intent=intent,
            devices=devices,
            implementation=implementation,
            rollback=rollback,
            post_check=post_check,
            tvt=tvt,
            required_tests=list(required_test_ids or []),
            optional_tests=list(optional_test_ids or []),
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": f"TCF construction failed: {type(exc).__name__}: {exc}",
        }

    # Patch O'-B: stamp first-emission metadata (revision_count stays 0;
    # subsequent writes by record_lab_run / patch_block increment).
    from datetime import UTC as _UTC, datetime as _dt
    tcf.last_revised_at = _dt.now(_UTC)
    tcf.last_revised_by = "ops-analyze"

    out_path = Path(output_dir) / change_id / "spec.tcf.yaml"
    try:
        written = tcf_emit(tcf, out_path)
    except Exception as exc:
        return {
            "status": "error",
            "error": f"emit failed: {type(exc).__name__}: {exc}",
        }

    return {
        "status": "ok",
        "spec_path": str(written),
        "change_id": change_id,
        "intent_type": intent_type,
        "device_count": len(devices),
        "implementation_blocks": len(implementation),
        "rollback_blocks": len(rollback),
        "post_check_count": len(post_check),
        "tvt_count": len(tvt),
        "next_step": (
            f"Validate in lab: ops-lab run_python_simulation → "
            f"olav.core.cab.tcf_load_for_lab({str(written)!r})"
        ),
    }
