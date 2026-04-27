"""tcf_emit_from_sim — R90 Phase 4 sim-side TCF emitter.

ops-analyze calls this AT THE END of a CAB-spec workflow instead of
``format_and_export`` for markdown. Pydantic validates everything
before write; structural errors (missing devices, dangling FK,
length-mismatched parallel arrays) surface at the tool boundary
rather than mid-deploy.

Schema is small-model friendly: top-level scalars + parallel arrays
for devices, JSON-string args for nested lists. Same pattern that
made R89 work after the v1 ``list[dict]`` failure mode.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
while _PROJECT_ROOT.parent != _PROJECT_ROOT and not (_PROJECT_ROOT / "pyproject.toml").exists():
    _PROJECT_ROOT = _PROJECT_ROOT.parent
sys.path.insert(0, str(_PROJECT_ROOT / "src"))


from langchain_core.tools import tool


@tool
def tcf_emit_from_sim(
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
) -> str:
    """Emit a TCF (Test Case File) for one CAB change.

    Use this AS THE FINAL STEP of a CAB simulation workflow instead
    of ``format_and_export`` for markdown. The TCF is the structured
    contract ops-lab consumes; markdown narrative is rendered
    on-demand later by the writer agent (LLM).

    Args:
        change_id: Unique change identifier (e.g.
            ``"cab_r1_r4_ebgp_001"``). Becomes the output filename
            stem and directory name.
        title: Human-readable change title.
        intent_type: Free-form intent identifier (e.g.
            ``"ebgp_direct"``, ``"acl_update"``, ``"vlan_add"``,
            ``"mtu_change"``). ops-lab dispatches on this.
        device_names: Prod device names, e.g. ``["R1", "R4"]``.
            Length must match the other 3 device arrays.
        device_platforms: Per-device platform strings (e.g.
            ``["juniper_junos", "cisco_ios"]``). Same length as
            device_names.
        device_loopbacks: Per-device loopback IPs as bare hosts
            (e.g. ``["1.1.1.1", "4.4.4.4"]``). Same length.
        device_asns: Per-device local AS numbers (ints). Same length.
        device_intfs: Optional per-device prod interface names (e.g.
            ``["ge-0/0/2", "Ethernet0/0"]``). If provided, must
            match length of device_names.
        implementation_json: JSON-encoded list of CLI blocks. Each
            entry: ``{"device":"R1","phase":1,"cli":["set ...", ...]}``.
            Use parallel JSON arrays so small models can construct
            them in text without nested tool-arg gymnastics. Required
            (don't pass ``"[]"`` — sim must produce implementation).
        rollback_json: JSON-encoded list of rollback CLI blocks
            (same shape as implementation_json). Empty default
            ``"[]"`` is acceptable for non-blocking changes.
        post_check_json: JSON-encoded list of post-check assertions.
            Each entry: ``{"device":"R1","check_id":"bgp_up",
            "description":"...","command":"show ...","expected_pattern":"..."}``.
        tvt_json: JSON-encoded list of TVT rows (test verification
            tracker). Each entry: ``{"test_id":"T1","description":"...",
            "expected":"...","severity":"blocker"}``. ``actual_lab``
            and ``status`` are filled by lab later.
        required_test_ids: Test IDs that MUST pass for the change
            to be approved (e.g. ``["T1","T2"]``).
        optional_test_ids: Test IDs that are advisory.
        lab_subnet: /30 to allocate for lab link IPs (default
            ``"172.16.99.0/30"``). Lab uses this for the digital
            twin; not the prod IPs.
        risk_class: ``"low"`` / ``"medium"`` / ``"high"`` /
            ``"blocker"``. Free-form string; default ``"medium"``.
        output_dir: Where to write. The TCF lands at
            ``<output_dir>/<change_id>/spec.tcf.yaml``.

    Returns:
        JSON envelope with status, path, and basic counts. On
        validation error (mismatched array lengths, dangling FKs,
        bad JSON), returns ``status="error"`` with a clear message —
        no file is written.

    Example:
        >>> tcf_emit_from_sim(
        ...     change_id="cab_r1_r4_ebgp_001",
        ...     title="Add direct eBGP between R1 and R4",
        ...     intent_type="ebgp_direct",
        ...     device_names=["R1", "R4"],
        ...     device_platforms=["juniper_junos", "cisco_ios"],
        ...     device_loopbacks=["1.1.1.1", "4.4.4.4"],
        ...     device_asns=[65000, 65001],
        ...     device_intfs=["ge-0/0/2", "Ethernet0/0"],
        ...     implementation_json='[{"device":"R1","phase":1,'
        ...                         '"cli":["set protocols bgp ...", "..."]}]',
        ...     post_check_json='[{"device":"R1","check_id":"bgp_up",'
        ...                     '"description":"BGP up","command":"show bgp summary",'
        ...                     '"expected_pattern":"Established"}]',
        ...     tvt_json='[{"test_id":"T1","description":"BGP up",'
        ...              '"expected":"Established","severity":"blocker"}]',
        ...     required_test_ids=["T1"],
        ... )
    """
    try:
        from olav.core.cab import (
            CabTcf,
            CliBlock,
            Device,
            Intent,
            PostCheck,
            TvtRow,
            tcf_emit,
        )
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"olav.core.cab unavailable: {type(exc).__name__}: {exc}",
        })

    # --- 1. Validate device array lengths ---------------------------
    n = len(device_names)
    if not (len(device_platforms) == len(device_loopbacks) == len(device_asns) == n):
        return json.dumps({
            "status": "error",
            "error": (
                f"device_* arrays must all have the same length: "
                f"names={n} platforms={len(device_platforms)} "
                f"loopbacks={len(device_loopbacks)} asns={len(device_asns)}"
            ),
        })
    if device_intfs is not None and len(device_intfs) != n:
        return json.dumps({
            "status": "error",
            "error": (
                f"device_intfs (optional) length {len(device_intfs)} "
                f"must match device_names length {n}"
            ),
        })

    # --- 2. Parse JSON-string sections ------------------------------
    def _parse_json_list(label: str, raw: str) -> list:
        try:
            value = json.loads(raw) if raw else []
        except json.JSONDecodeError as e:
            raise ValueError(f"{label} is not valid JSON: {e}") from e
        if not isinstance(value, list):
            raise ValueError(
                f"{label} must be a JSON array; got "
                f"{type(value).__name__}"
            )
        return value

    try:
        impl_raw = _parse_json_list("implementation_json", implementation_json)
        rollback_raw = _parse_json_list("rollback_json", rollback_json)
        post_check_raw = _parse_json_list("post_check_json", post_check_json)
        tvt_raw = _parse_json_list("tvt_json", tvt_json)
    except ValueError as e:
        return json.dumps({"status": "error", "error": str(e)})

    # --- 3. Build Pydantic models ----------------------------------
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
            created_by="ops-analyze",
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
        return json.dumps({
            "status": "error",
            "error": f"TCF construction failed: {type(exc).__name__}: {exc}",
        })

    # --- 4. Write atomically to <output_dir>/<change_id>/spec.tcf.yaml
    out_path = Path(output_dir) / change_id / "spec.tcf.yaml"
    try:
        written = tcf_emit(tcf, out_path)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "error": f"emit failed: {type(exc).__name__}: {exc}",
        })

    return json.dumps({
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
            f"Validate in lab: ops-lab tcf_load_for_lab(spec_path="
            f"{written!r})"
        ),
    })


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    args = json.loads(parsed.args_json)
    print(tcf_emit_from_sim.invoke(args))
