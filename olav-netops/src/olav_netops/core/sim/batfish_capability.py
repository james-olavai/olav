"""``batfish_capability`` — pre-flight check for Batfish vendor support
in a netops snapshot's device scope.

Two-layer answer (per dev_docs/73 §2 follow-up):

  1. **Static map** ``BATFISH_VENDOR_SUPPORT`` — known vendor parser
     coverage in upstream Batfish.  Used to predict whether a query
     will return useful rows for each in-scope device, BEFORE paying
     the snapshot-init cost.  Lets the analyzer skip sim entirely
     when no in-scope device is Batfish-supported.

  2. **Live ``fileParseStatus``** (delegated to ``batfish_q``) —
     ground truth from the running Batfish service.  Used by sim's
     Phase 0 to caveat per-query reports.  Not invoked by this tool
     directly (sim handles that via existing ``batfish_q`` calls).

Returns an envelope ``per_device + summary`` so analyzer / sim
callers can decide what to do with partial coverage.
"""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


#: Static vendor coverage map.  Source: upstream Batfish supported
#: vendors documentation (https://batfish.org/) + community
#: experience.  Update when Batfish announces new parser support.
BATFISH_VENDOR_SUPPORT: dict[str, str] = {
    # FULL — production-grade parsers
    "cisco_ios":         "FULL",
    "cisco_iosxe":       "FULL",
    "cisco_nxos":        "FULL",
    "cisco_asa":         "FULL",
    "juniper_junos":     "FULL",
    "arista_eos":        "FULL",
    "paloalto_panos":    "FULL",
    "f5_bigip":          "FULL",
    "aws_vpc":           "FULL",
    # PARTIAL — some sections parsed, others skipped
    "cisco_iosxr":       "PARTIAL",
    "nokia_sros":        "PARTIAL",
    "huawei_vrp":        "PARTIAL",
    "fortinet_fortios":  "PARTIAL",
    "checkpoint_gaia":   "PARTIAL",
    # NONE — no Batfish parser; sim cannot evaluate config for these
    "nokia_srl":         "NONE",
    "nokia_srlinux":     "NONE",
    "h3c":               "NONE",
    "h3c_comware":       "NONE",
    "mikrotik_routeros": "NONE",
    "ruijie":            "NONE",
    "vyos":              "NONE",
}


def _classify_capability(per_device: dict[str, str]) -> str:
    """Roll per-device capability up to a snapshot-scope summary."""
    if not per_device:
        return "EMPTY"
    statuses = set(per_device.values())
    if statuses == {"FULL"}:
        return "FULL"
    if "NONE" in statuses and "FULL" not in statuses and "PARTIAL" not in statuses:
        return "NONE"
    return "PARTIAL"


@tool
def batfish_capability(
    devices: list[str] | None = None,
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    """Pre-flight check: which in-scope devices can Batfish evaluate?

    Args:
        devices: list of device hostnames to check.  If empty/None,
            checks ALL devices in netops.devices.
        snapshot_id: optional snapshot context (currently informational
            only — static map is snapshot-agnostic).

    Returns:
        ``{"per_device": {hostname: {"platform": str, "capability": "FULL"|"PARTIAL"|"NONE"|"UNKNOWN"}},
            "summary": "FULL"|"PARTIAL"|"NONE"|"EMPTY",
            "unsupported_devices": [names],
            "partially_supported_devices": [names],
            "unknown_platform_devices": [names]}``

    Use BEFORE delegating to sim's batfish_q queries.  If summary is
    NONE, skip sim entirely (Batfish will return empty rows).  If
    PARTIAL, run sim but expect a caveat in the reply.

    For live ground-truth (what Batfish actually parsed at runtime),
    call ``batfish_q(question="fileParseStatus", snapshot_id=...)``
    instead.  This tool is the cheap static pre-check.
    """
    import duckdb
    from olav.core.config import MAIN_DB_PATH

    # Coerce the ``devices`` arg at the boundary (small models pass a regex
    # string like ".*" meaning "all", or a single hostname as a bare string —
    # feeding a str straight to DuckDB params raises "Prepared parameters can
    # only be passed as a list or a dictionary"). Wildcard/empty = discovery
    # (check ALL devices); a bare hostname string becomes a one-item list.
    if isinstance(devices, str):
        devices = None if devices.strip() in ("", "*", ".*", "all", "%") else [devices]
    elif devices is not None and not isinstance(devices, list):
        devices = list(devices)

    try:
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            if devices:
                # Parameterised IN clause
                placeholders = ",".join("?" * len(devices))
                rows = conn.execute(
                    f"SELECT hostname, platform FROM netops.devices "
                    f"WHERE hostname IN ({placeholders})",
                    devices,
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT hostname, platform FROM netops.devices"
                ).fetchall()
    except Exception as exc:
        logger.warning(f"batfish_capability: DB query failed: {exc}")
        return {
            "status": "error",
            "message": f"could not query netops.devices: {exc}",
            "per_device": {},
            "summary": "EMPTY",
            "snapshot_id": snapshot_id,
        }

    per_device: dict[str, dict[str, str]] = {}
    unsupported: list[str] = []
    partial: list[str] = []
    unknown: list[str] = []

    for hostname, platform in rows:
        plat = (platform or "").strip().lower()
        cap = BATFISH_VENDOR_SUPPORT.get(plat, "UNKNOWN")
        per_device[hostname] = {"platform": plat, "capability": cap}
        if cap == "NONE":
            unsupported.append(hostname)
        elif cap == "PARTIAL":
            partial.append(hostname)
        elif cap == "UNKNOWN":
            unknown.append(hostname)

    cap_only = {h: d["capability"] for h, d in per_device.items()}
    summary = _classify_capability(cap_only)

    # Live pre-check: is a Batfish service actually reachable? This is the
    # cheap "call first" tool, so it is the right place to catch a missing
    # Batfish early and hand the user the fix, instead of letting the first
    # batfish_q fail deep. (software-understands-human)
    from olav_netops.core.sim.batfish_q import (
        _batfish_endpoint,
        _batfish_reachable,
        batfish_setup_hint,
    )
    _host, _port, _ = _batfish_endpoint()
    reachable = _batfish_reachable(_host, _port)

    result = {
        "status": "ok",
        "batfish_reachable": reachable,
        "per_device": per_device,
        "summary": summary,
        "unsupported_devices": unsupported,
        "partially_supported_devices": partial,
        "unknown_platform_devices": unknown,
        "device_count": len(per_device),
        "snapshot_id": snapshot_id,
    }
    if not reachable:
        result["setup_hint"] = batfish_setup_hint(_host, _port)
    return result
