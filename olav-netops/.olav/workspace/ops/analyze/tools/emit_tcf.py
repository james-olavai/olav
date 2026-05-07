"""emit_tcf — produce a Test Case File (TCF) for ops-lab consumption.

Patch D / R102.UNIFIED_SANDBOX (2026-05-06): brought back to a real @tool.
Patch F (2026-05-06): forgiving signature — auto-coerce common LLM args mistakes.
Patch G (2026-05-06): silent-degrade malformed post_check/tvt blocks.
Patch K (2026-05-07): content-correctness — DB-side ASN cross-check + sim_passed gate.

Architectural rationale (ADR-0008 condition #2):
``tcf_emit_from_sim`` writes ``exports/cab/<change_id>/spec.tcf.yaml`` to
disk — a sandbox-external write target.

Patch K guarantees:
1. ``device_asns`` cross-checked against
   ``netops.v_show_ip_bgp_summary_auto.local_as`` for the named devices.
   Mismatch → ``result["warnings"]`` shows actual prod ASN; spec still
   writes (don't block on data gaps).
2. ``sim_passed: bool | None`` optional kwarg signals whether the agent
   ran a feasibility-check simulation before emitting.  ``False`` →
   prominent warning so the agent (and the user reviewing the spec)
   know this skipped the validation step.
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import tool


_CLIBLOCK_REQUIRED = {"device", "phase", "cli"}
_POSTCHECK_REQUIRED = {"device", "check_id", "description", "command", "expected_pattern"}
_TVTROW_REQUIRED = {"test_id", "description", "expected"}


def _check_asns_against_db(
    device_names: list[str], device_asns: list[int],
) -> str | None:
    """Cross-check supplied ASNs against actual prod data in
    netops.v_show_ip_bgp_summary_auto.

    Returns a warning string when ASNs disagree (or DB unreachable);
    None when every supplied ASN matches.  Best-effort: if the view
    is missing, the table is empty, or DB is unavailable, return a
    soft note rather than block emission.
    """
    if not device_names or not device_asns:
        return None
    try:
        import duckdb
        from olav.core.config import MAIN_DB_PATH
        con = duckdb.connect(str(MAIN_DB_PATH), read_only=True)
        try:
            placeholders = ",".join("?" for _ in device_names)
            rows = con.execute(
                f"SELECT device_name, local_as FROM "
                f"netops.v_show_ip_bgp_summary_auto "
                f"WHERE device_name IN ({placeholders}) "
                f"  AND local_as IS NOT NULL",
                device_names,
            ).fetchall()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001
        return (
            "ASN cross-check skipped: could not query "
            f"netops.v_show_ip_bgp_summary_auto ({type(exc).__name__}: "
            f"{str(exc)[:80]}). Spec proceeds with the supplied ASNs."
        )

    if not rows:
        return (
            "ASN cross-check inconclusive: no rows in "
            "netops.v_show_ip_bgp_summary_auto for the supplied "
            f"devices {device_names}. If these devices haven't been "
            "snapshotted yet, ASNs in the spec are author-supplied "
            "(treat as placeholders until lab validation)."
        )

    # Coerce DB values to int (some platforms emit local_as as string)
    db_asns: dict[str, int] = {}
    for d, a in rows:
        try:
            db_asns[d] = int(a)
        except (TypeError, ValueError):
            continue

    mismatches = []
    for name, supplied in zip(device_names, device_asns):
        actual = db_asns.get(name)
        if actual is not None and actual != supplied:
            mismatches.append(f"{name}: spec={supplied} prod={actual}")

    if mismatches:
        return (
            "ASN mismatch vs prod data — review before lab/prod apply: "
            + "; ".join(mismatches)
            + ". Either (a) update device_asns to match prod or "
            "(b) confirm the spec is intentionally introducing a new ASN."
        )
    return None


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
    sim_passed: bool | None = None,
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
        sim_passed: Optional flag from a feasibility-check simulation.
            ``True``  = run_python_simulation produced
                ``feasibility_issues=[]`` (the canonical pre-check).
            ``False`` = sim ran and found blockers — emit anyway, but
                produces a prominent warning in the result.
            ``None``  = sim was not run (default).  Result includes
                a soft warning recommending the agent run a sim
                before lab validation.

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

    # Patch K: cross-check device_asns against actual prod data.
    # Soft check — never blocks emission, just appends a warning so the
    # agent (and the human reviewing the spec) know the spec was built
    # with placeholder ASNs.
    asn_warning = _check_asns_against_db(device_names, coerced_asns)
    if asn_warning:
        warnings.append(asn_warning)

    # Patch K: sim_passed gate.  If the agent didn't run a feasibility
    # simulation (or ran one and it found blockers), surface that
    # prominently in the result envelope.
    if sim_passed is None:
        warnings.append(
            "sim_passed=None — no feasibility simulation was run before "
            "this emit. Recommend: run_python_simulation with the "
            "DESIGN_FEASIBILITY_CHECK pattern to validate phase ordering "
            "and blockers, then re-emit with sim_passed=True."
        )
    elif sim_passed is False:
        warnings.append(
            "⚠ sim_passed=False — the feasibility simulation found "
            "blockers but you emitted anyway. ops-lab may FAIL fast on "
            "missing prerequisites (Phase 0 IGP / loopback reachability). "
            "Review feasibility_issues from the sim and re-emit after fixes."
        )

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
