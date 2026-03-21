"""Netutils normalization layer (OC-4).

Cleans TextFSM raw output before LLM mapping:
- Interface name canonicalization (Gi0/0 → GigabitEthernet0/0)
- MAC address normalization to colon-separated lowercase
- IP prefix / netmask-to-CIDR conversion

All functions are pure and return a new value (no mutation).
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

try:
    from netutils.interface import canonical_interface_name as _canonical_intf
except ImportError:  # pragma: no cover
    _canonical_intf = None  # type: ignore[assignment]

try:
    from netutils.ip import netmask_to_cidr as _netmask_to_cidr
except ImportError:  # pragma: no cover
    _netmask_to_cidr = None  # type: ignore[assignment]

_MAC_RE = re.compile(
    r"^[0-9a-fA-F]{2}([:\-])[0-9a-fA-F]{2}\1[0-9a-fA-F]{2}\1[0-9a-fA-F]{2}\1[0-9a-fA-F]{2}\1[0-9a-fA-F]{2}$"
)
_CISCO_MAC_RE = re.compile(r"^[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}$")

INTERFACE_FIELDS = frozenset(
    {
        "interface",
        "intf",
        "port",
        "local_interface",
        "local_intf",
        "neighbor_interface",
        "neighbor_port",
    }
)

MAC_FIELDS = frozenset(
    {
        "mac_address",
        "mac",
        "chassis_id",
        "source_mac",
        "dest_mac",
        "hardware_address",
        "hw_addr",
    }
)


def normalize_interface_name(name: str) -> str:
    if not name:
        return name
    if _canonical_intf is None:
        return name
    try:
        return _canonical_intf(name)
    except Exception:
        return name


def normalize_mac(mac: str) -> str:
    if not mac:
        return mac
    raw = mac.replace(":", "").replace("-", "").replace(".", "").lower()
    if len(raw) != 12 or not all(c in "0123456789abcdef" for c in raw):
        return mac
    return ":".join(raw[i : i + 2] for i in range(0, 12, 2))


def normalize_ip_prefix(ip: str, mask: str | None = None) -> str:
    if not ip:
        return ip
    if "/" in ip:
        return ip
    if mask and _netmask_to_cidr is not None:
        try:
            cidr = _netmask_to_cidr(mask)
            return f"{ip}/{cidr}"
        except Exception:
            return ip
    return ip


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in record.items():
        if not isinstance(value, str):
            out[key] = value
            continue
        if key.lower() in INTERFACE_FIELDS:
            out[key] = normalize_interface_name(value)
        elif key.lower() in MAC_FIELDS:
            out[key] = normalize_mac(value)
        else:
            out[key] = value
    return out


OC_MODULE_MAP: dict[str, str] = {
    "interfaces": "openconfig-interfaces",
    "bgp": "openconfig-bgp",
    "lldp": "openconfig-lldp",
    "network-instances": "openconfig-network-instance",
    "components": "openconfig-platform",
}

YANG_LIST_NODES = frozenset(
    {
        "interface",
        "neighbor",
        "subinterface",
        "component",
        "area",
        "protocol",
    }
)


def _oc_module_for_path(oc_path: str) -> str | None:
    """Return the ``openconfig-*`` or ``_olav:*`` module name for *oc_path*, or ``None``."""
    first_seg = oc_path.split("/", 1)[0]
    # _olav: private namespace — the first segment IS the module name
    if first_seg.startswith("_olav:"):
        return first_seg
    return OC_MODULE_MAP.get(first_seg)


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into *base* (mutates *base*)."""
    for key, val in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        elif key in base and isinstance(base[key], list) and isinstance(val, list):
            if base[key] and val and isinstance(base[key][0], dict) and isinstance(val[0], dict):
                _deep_merge(base[key][0], val[0])
            else:
                base[key] = val
        else:
            base[key] = val
    return base


def _build_nested(segments: list[str], value: Any) -> dict[str, Any]:
    """Build a nested dict from OC path segments, wrapping YANG list nodes in arrays."""
    if len(segments) == 1:
        return {segments[0]: value}

    child = _build_nested(segments[1:], value)
    if segments[0] in YANG_LIST_NODES:
        return {segments[0]: [child]}
    return {segments[0]: child}


def apply_oc_mapping(
    records: list[dict[str, Any]],
    platform: str,
    command: str,
    con: Any,
) -> list[dict[str, Any]]:
    """Build nested OpenConfig JSON from TextFSM records using schema_catalog (with mapping_rules compatibility fallback).

    For each record, mapped fields are grouped by OC module prefix and placed
    into a nested dict under ``openconfig-*`` top-level keys.  Unmapped fields
    are preserved under the ``_unmapped`` key.  Original records are NOT mutated.
    """
    if not records:
        return []

    # Primary: read field map from schema_catalog
    catalog_rows = con.execute(
        "SELECT fields FROM schema_catalog WHERE platform = ? AND source_name = ?",
        [platform, command],
    ).fetchall()

    field_map: dict[str, str]

    if catalog_rows:
        fields_json = catalog_rows[0][0]
        try:
            fields = (
                json.loads(fields_json) if isinstance(fields_json, str) else (fields_json or [])
            )
        except Exception as exc:
            raise ValueError(
                f"Invalid schema_catalog.fields JSON for platform={platform!r}, command={command!r}"
            ) from exc
        field_map = {
            field["name"]: field["openconfig_path"]
            for field in fields
            if field.get("name") and field.get("openconfig_path")
        }
    else:
        # Fallback: compatibility with legacy mapping_rules table
        logger.warning(
            "schema_catalog miss for platform=%r command=%r, falling back to mapping_rules",
            platform,
            command,
        )
        rows = con.execute(
            "SELECT src_field, oc_path FROM mapping_rules WHERE vendor = ? AND command = ?",
            [platform, command],
        ).fetchall()

        if not rows:
            raise ValueError(
                f"No schema_catalog entry found for platform={platform!r}, command={command!r}"
            )

        field_map = {src: oc for src, oc in rows}

    result: list[dict[str, Any]] = []
    for record in records:
        oc_dict: dict[str, Any] = {}
        unmapped: dict[str, Any] = {}

        for key, value in record.items():
            oc_path = field_map.get(key)
            if oc_path is None:
                unmapped[key] = value
                continue

            module = _oc_module_for_path(oc_path)
            if module is None:
                unmapped[key] = value
                continue

            segments = oc_path.split("/")
            nested = _build_nested(segments, value)
            top_key = module
            if top_key not in oc_dict:
                oc_dict[top_key] = nested
            else:
                _deep_merge(oc_dict[top_key], nested)

        if unmapped:
            oc_dict["_unmapped"] = unmapped

        result.append(oc_dict)
    return result
