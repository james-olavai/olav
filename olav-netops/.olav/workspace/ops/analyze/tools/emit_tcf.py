"""emit_tcf — produce a Test Case File (TCF) for ops-lab consumption.

Patch D / R102.UNIFIED_SANDBOX (2026-05-06): brought back to a real @tool.
Patch F (2026-05-06): forgiving signature — auto-coerce common LLM args mistakes.

Architectural rationale (ADR-0008 condition #2):
``tcf_emit_from_sim`` writes ``exports/cab/<change_id>/spec.tcf.yaml`` to
disk — a sandbox-external write target.

Patch F input coercion (validated by T1g failure modes 2026-05-06):
1. ``implementation_json`` accepted as **list[dict] OR str** — list is
   json.dumps'd automatically (LLMs commonly forget the str-encode step).
2. CLI block ``cli`` field accepted as ``str`` — wrapped in ``[str]``
   (Pydantic schema requires list[str] but LLMs sometimes pass plain str).
3. CLI block ``phase`` defaults to 1 if missing (LLMs sometimes omit it
   when there's only one phase).
4. Same coercion applies to rollback_json / post_check_json / tvt_json.

These reduce common-failure-mode count from 3 to 0 in offline tests.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


_CLIBLOCK_REQUIRED = {"device", "phase", "cli"}
_POSTCHECK_REQUIRED = {"device", "check_id", "description", "command", "expected_pattern"}
_TVTROW_REQUIRED = {"test_id", "description", "expected"}


def _coerce_blocks_json(label: str, value: Any) -> tuple[str, str | None]:
    """Accept either a JSON-encoded string or a Python list/dict.

    Returns ``(json_str, warning_or_None)``.  Fixes common LLM mistakes:

    * ``implementation_json`` / ``rollback_json`` (CliBlock shape):
        - ``cli`` field that's a plain string → wrapped in ``[str]``
        - Missing ``phase`` field → defaulted to 1
    * ``post_check_json`` / ``tvt_json``: silent-degrade to ``"[]"`` if
        agent supplied wrong-shape blocks (e.g. CliBlock shape on
        post_check) — return a warning string in the second tuple slot
        so the agent learns what to fix on the next emit.
    """
    if value is None or value == "":
        return "[]", None

    # If LLM passed a Python list instead of JSON string, accept it
    if isinstance(value, list):
        normalised = value
    elif isinstance(value, str):
        try:
            normalised = json.loads(value)
        except json.JSONDecodeError:
            # Leave it; downstream will surface the error
            return value, None
    else:
        return json.dumps(value), None

    if not isinstance(normalised, list):
        return json.dumps(normalised), None

    # Decide the expected required-key set per label
    required: set[str] | None
    if label in {"implementation_json", "rollback_json"}:
        required = _CLIBLOCK_REQUIRED
    elif label == "post_check_json":
        required = _POSTCHECK_REQUIRED
    elif label == "tvt_json":
        required = _TVTROW_REQUIRED
    else:
        required = None

    fixed: list[dict] = []
    malformed: list[str] = []
    for entry in normalised:
        if not isinstance(entry, dict):
            fixed.append(entry)
            continue
        block = dict(entry)

        if label in {"implementation_json", "rollback_json"}:
            cli = block.get("cli")
            if isinstance(cli, str):
                block["cli"] = [cli]
            if "phase" not in block:
                block["phase"] = 1

        # Shape check — if optional fields (post_check/tvt) are wrong shape,
        # silently degrade rather than fail the whole emit.
        if required is not None:
            missing = required - set(block.keys())
            if missing and label in {"post_check_json", "tvt_json"}:
                malformed.append(
                    f"block missing {sorted(missing)} (got keys {sorted(block.keys())})"
                )
                continue  # drop this block; the rest may still be valid

        fixed.append(block)

    warning = None
    if malformed and label in {"post_check_json", "tvt_json"}:
        warning = (
            f"{label}: dropped {len(malformed)} malformed block(s); "
            f"fix by supplying the required fields and re-emit. "
            f"Examples: {malformed[:2]}"
        )
        # If after pruning we have NOTHING left, default to []
        if not fixed:
            return "[]", warning

    return json.dumps(fixed), warning


@tool
def emit_tcf(
    change_id: str,
    title: str,
    intent_type: str,
    device_names: list[str],
    device_platforms: list[str],
    device_loopbacks: list[str],
    device_asns: list[int],
    implementation_json: str | list[dict[str, Any]],
    device_intfs: list[str] | None = None,
    rollback_json: str | list[dict[str, Any]] = "[]",
    post_check_json: str | list[dict[str, Any]] = "[]",
    tvt_json: str | list[dict[str, Any]] = "[]",
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

    # Patch F+G: coerce common LLM mistakes before strict Pydantic.
    # post_check_json / tvt_json silently degrade to "[]" if blocks are
    # malformed — agent gets a warning in the result envelope so it can
    # refine on a follow-up emit_tcf call rather than failing the whole
    # spec write.
    warnings: list[str] = []
    impl_clean, w = _coerce_blocks_json("implementation_json", implementation_json)
    if w: warnings.append(w)
    rollback_clean, w = _coerce_blocks_json("rollback_json", rollback_json)
    if w: warnings.append(w)
    post_check_clean, w = _coerce_blocks_json("post_check_json", post_check_json)
    if w: warnings.append(w)
    tvt_clean, w = _coerce_blocks_json("tvt_json", tvt_json)
    if w: warnings.append(w)

    # Coerce ASNs to int if they came as strings (LLMs often quote integers)
    coerced_asns: list[int] = []
    for asn in device_asns:
        try:
            coerced_asns.append(int(asn))
        except (TypeError, ValueError):
            return {
                "status": "error",
                "error": f"device_asns must be integers; got non-numeric value {asn!r}",
            }

    # Strip trailing change_id from output_dir if agent included it
    # (T1j observed: agent passes output_dir="exports/cab/r1-r3-ebgp/" and
    # then emit_tcf appends another change_id, producing double-nested path).
    import os as _os
    od = output_dir.rstrip("/")
    od_parts = od.split("/")
    if od_parts and od_parts[-1] == change_id:
        output_dir = "/".join(od_parts[:-1]) or "."

    result = tcf_emit_from_sim(
        change_id=change_id,
        title=title,
        intent_type=intent_type,
        device_names=device_names,
        device_platforms=device_platforms,
        device_loopbacks=device_loopbacks,
        device_asns=coerced_asns,
        implementation_json=impl_clean,
        device_intfs=device_intfs,
        rollback_json=rollback_clean,
        post_check_json=post_check_clean,
        tvt_json=tvt_clean,
        required_test_ids=required_test_ids,
        optional_test_ids=optional_test_ids,
        lab_subnet=lab_subnet,
        risk_class=risk_class,
        output_dir=output_dir,
        created_by="ops-analyze",
    )

    if warnings:
        # Fold coercion warnings into the result so the agent learns what
        # to fix without failing the spec write.
        existing = result.get("warnings", []) if isinstance(result, dict) else []
        if isinstance(result, dict):
            result["warnings"] = list(existing) + warnings
    return result
