"""emit_tcf — produce a Test Case File (TCF) for ops-lab consumption.

Patch D / R102.UNIFIED_SANDBOX (2026-05-06): brought back to a real @tool.

Architectural rationale (ADR-0008 condition #2):
``tcf_emit_from_sim`` writes ``exports/cab/<change_id>/spec.tcf.yaml`` to
disk — a sandbox-external write target.  Validation on 2026-05-05
(T1 × 4 attempts) showed agents reliably disk-hunt for "TCF emitter" via
glob/ls/recall_memory when this primitive lives only in the sandbox
prologue, never invoking ``tcf_emit_from_sim`` itself.  Promoting back
to @tool gives the agent a typed Pydantic schema + named callable that
matches its mental model of "dispatch a structured operation".

Thin wrapper around ``olav.core.cab.tcf_emit_from_sim``.  No new logic;
just a schema-validated dispatch surface.
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import tool


@tool
def emit_tcf(
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
    output_dir: str = "exports/cab",
) -> dict[str, Any]:
    """
    Atomically emit a Test Case File (TCF) for a single CAB change.

    Writes the YAML spec to ``{output_dir}/{change_id}/spec.tcf.yaml``.
    The TCF is the contract ops-lab consumes for change validation —
    Pydantic-validated, includes apply + rollback + post-checks + TVT.

    DO NOT free-form Markdown your change plans — emit a TCF.  Markdown
    rendering happens later via the writer agent reading the TCF.

    Args:
        change_id: Short ID for the change (e.g. ``"r1-r3-ebgp"``);
            becomes the output subdirectory name.
        title: Human-readable change title.
        intent_type: Free-form change category (e.g. ``"ebgp_direct"``,
            ``"acl_update"``, ``"vlan_add"``); ops-lab dispatches on it.
        device_names: Devices participating (parallel arrays below
            MUST be same length).
        device_platforms: Per-device platform (e.g. ``"juniper_junos"``,
            ``"cisco_ios"``) — used to dispatch CLI syntax.
        device_loopbacks: Per-device loopback IPs (prod-aligned).
        device_asns: Per-device BGP ASNs.
        implementation_json: JSON-encoded list of CLI blocks per phase.
            Each block: ``{"device": "R1", "phase": 1, "cli": ["..."]}``.
            Use prod CLI syntax matching the device's platform.
        device_intfs: Optional per-device interface (parallel array).
        rollback_json: Same shape as implementation_json — undo CLI.
        post_check_json: Verification steps after apply.
        tvt_json: Test Verification Tracker rows for ops-lab.
        required_test_ids: TVT IDs that MUST pass for prod approval.
        optional_test_ids: TVT IDs allowed to fail (info only).
        lab_subnet: Lab subnet for ContainerLab assignment
            (default ``172.16.99.0/30``).
        risk_class: ``"low" | "medium" | "high"``; default ``"medium"``.
        output_dir: Where to write the spec
            (default ``"exports/cab"``); the function appends
            ``<change_id>/spec.tcf.yaml``.

    Returns:
        ``{"status": "success", "spec_path": "<path>", ...}`` on success;
        ``{"status": "error", "error": "<reason>"}`` on validation failure
        (no file written).

    Example:
        >>> emit_tcf(
        ...     change_id="r1-r3-ebgp",
        ...     title="Add eBGP direct between R1 and R3",
        ...     intent_type="ebgp_direct",
        ...     device_names=["R1", "R3"],
        ...     device_platforms=["juniper_junos", "cisco_ios"],
        ...     device_loopbacks=["10.0.0.1", "10.0.0.3"],
        ...     device_asns=[65001, 65003],
        ...     implementation_json='[{"device":"R1","phase":1,"cli":["set protocols bgp group EBGP-R3 type external"]},{"device":"R3","phase":1,"cli":["router bgp 65003"," neighbor 10.1.13.1 remote-as 65001"]}]',
        ...     rollback_json='[{"device":"R1","phase":1,"cli":["delete protocols bgp group EBGP-R3"]}]',
        ... )
        {'status': 'success', 'spec_path': 'exports/cab/r1-r3-ebgp/spec.tcf.yaml', ...}
    """
    from olav.core.cab import tcf_emit_from_sim

    return tcf_emit_from_sim(
        change_id=change_id,
        title=title,
        intent_type=intent_type,
        device_names=device_names,
        device_platforms=device_platforms,
        device_loopbacks=device_loopbacks,
        device_asns=device_asns,
        implementation_json=implementation_json,
        device_intfs=device_intfs,
        rollback_json=rollback_json,
        post_check_json=post_check_json,
        tvt_json=tvt_json,
        required_test_ids=required_test_ids,
        optional_test_ids=optional_test_ids,
        lab_subnet=lab_subnet,
        risk_class=risk_class,
        output_dir=output_dir,
        created_by="ops-analyze",
    )
