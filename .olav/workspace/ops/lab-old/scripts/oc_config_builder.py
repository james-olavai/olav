"""OC Config Builder — OC JSON → SRL-importable JSON.

Primary config generation path (no LLM for common cases):

    parsed_outputs + schema_catalog
        ↓  apply_oc_mapping_cached  (cab_config_extractor)
    OpenConfig nested dict (per device, per record)
        ↓  merge_oc_records_for_device
    Unified OC tree  (one dict per device)
        ↓  build_srl_json_from_oc_tree
    SRL-native JSON  (interface names substituted, config/ flattened)
        ↓  sr_cli load json <file>
    SRL lab node configured

If `sr_cli load json` fails: LLM receives the JSON + error → repairs it → retry once.
Vendor extensions (_unmapped fields): LLM translates to OC paths → merged → retry.

Architecture note:
    This module does only the minimal OC→SRL structural transformations that are
    1:1 and deterministic (no semantic reasoning):
      - Strip OC module namespace keys
      - Remove OC wrapper containers (interfaces/, network-instances/)
      - Flatten config/ containers into their parent
      - Drop state/ containers (read-only snapshot data)
      - Apply interface name substitution (iface_map)
      - Map value enums: admin-status UP/DOWN → admin-state enable/disable
      - Map OC protocol wrapper: protocols.protocol[]/bgp → protocols/bgp
    The LLM handles anything that doesn't fit these rules on import failure.
"""

from __future__ import annotations

import sys as _sys
from pathlib import Path as _Path
_LAB_SCRIPTS = _Path(__file__).parent.resolve()
if str(_LAB_SCRIPTS) not in _sys.path:
    _sys.path.insert(0, str(_LAB_SCRIPTS))

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Value + leaf name mappings (OC → SRL native)
# ---------------------------------------------------------------------------

_ADMIN_STATUS_MAP: dict[str, str] = {
    "up": "enable",
    "down": "disable",
    "true": "enable",
    "false": "disable",
    "1": "enable",
    "0": "disable",
    "enabled": "enable",
    "disabled": "disable",
}

# OC leaf name → SRL leaf name (where they differ)
_LEAF_RENAME: dict[str, str] = {
    "admin-status": "admin-state",
}


def _map_value(leaf_name: str, value: Any) -> Any:
    """Apply value mapping for known OC→SRL enum differences."""
    if leaf_name in ("admin-status", "enabled"):
        mapped = _ADMIN_STATUS_MAP.get(str(value).lower())
        if mapped is not None:
            return mapped
    return value


# ---------------------------------------------------------------------------
# OC record merging
# ---------------------------------------------------------------------------


def _deep_merge(base: dict, overlay: dict) -> None:
    """Merge overlay into base in-place. Lists are extended."""
    for key, val in overlay.items():
        if key in base and isinstance(base[key], dict) and isinstance(val, dict):
            _deep_merge(base[key], val)
        elif key in base and isinstance(base[key], list) and isinstance(val, list):
            base[key].extend(val)
        else:
            base[key] = val


def merge_oc_records_for_device(
    oc_records: list[dict],
) -> tuple[dict, list[dict]]:
    """Merge per-record OC dicts (from apply_oc_mapping_cached) into one tree.

    Args:
        oc_records: List of {module_key: nested_oc_tree, ...} dicts, one per
                    parsed CLI record. May contain ``_unmapped`` vendor keys.

    Returns:
        (merged_oc_tree, vendor_fields)
        merged_oc_tree: Unified OC tree keyed by openconfig-* module names.
        vendor_fields: List of _unmapped dicts for LLM vendor extension handling.
    """
    merged: dict[str, Any] = {}
    vendor_fields: list[dict] = []

    for record in oc_records:
        for key, val in record.items():
            if key == "_unmapped":
                if isinstance(val, dict) and val:
                    vendor_fields.append(val)
                continue
            if not isinstance(val, dict):
                continue
            if key not in merged:
                merged[key] = copy.deepcopy(val)
            else:
                _deep_merge(merged[key], copy.deepcopy(val))

    return merged, vendor_fields


# ---------------------------------------------------------------------------
# OC tree → SRL JSON structural transformation
# ---------------------------------------------------------------------------


def _flatten_config_container(node: dict) -> dict:
    """Recursively flatten 'config/' containers into their parent dict.

    OC: {config: {name: "foo", admin-status: "UP"}, subinterfaces: {...}}
    SRL:         {name: "foo", admin-state: "enable", subinterface: [...]}

    Also:
    - Drops 'state/' containers (read-only snapshot data).
    - Renames leaves per _LEAF_RENAME.
    - Maps values per _map_value.
    - Unwraps plural wrapper containers: interfaces→interface, neighbors→neighbor, etc.
    """
    if not isinstance(node, dict):
        return node

    result: dict = {}
    for key, val in node.items():
        # Drop state containers entirely
        if key == "state":
            continue

        # Flatten config containers: merge their children up
        if key == "config":
            if isinstance(val, dict):
                for ck, cv in val.items():
                    srl_name = _LEAF_RENAME.get(ck, ck)
                    result[srl_name] = _map_value(ck, cv)
            continue

        # Recurse into dicts
        if isinstance(val, dict):
            result[key] = _flatten_config_container(val)
            continue

        # Recurse into lists
        if isinstance(val, list):
            result[key] = [
                _flatten_config_container(item) if isinstance(item, dict) else item
                for item in val
            ]
            continue

        # Leaf value
        srl_name = _LEAF_RENAME.get(key, key)
        result[srl_name] = _map_value(key, val)

    return result


# OC module key → (oc_wrapper_key, srl_top_key)
# The OC JSON has an extra plural wrapper that SRL doesn't need.
_MODULE_UNWRAP: dict[str, tuple[str, str]] = {
    "openconfig-interfaces": ("interfaces", "interface"),
    "openconfig-network-instance": ("network-instances", "network-instance"),
    "openconfig-bgp": ("bgp", "bgp"),
    "openconfig-lldp": ("lldp", "lldp"),
    "openconfig-platform": ("components", "component"),
}


def _unwrap_protocol_list(network_instance_list: list[dict]) -> list[dict]:
    """SRL doesn't have a protocol[identifier=BGP] wrapper — collapse it.

    OC: protocols.protocol[identifier=BGP, name=BGP].bgp.{...}
    SRL: protocols.bgp.{...}
    """
    result = []
    for ni in network_instance_list:
        if not isinstance(ni, dict):
            result.append(ni)
            continue
        ni_copy = dict(ni)
        protocols = ni_copy.get("protocols")
        if isinstance(protocols, dict):
            proto_list = protocols.get("protocol")
            if isinstance(proto_list, list):
                srl_protocols: dict = {}
                for proto in proto_list:
                    if not isinstance(proto, dict):
                        continue
                    # Each protocol item contains the protocol sub-tree (bgp, ospf, ...)
                    # Copy everything except the 'identifier' and 'name' OC keys
                    for pk, pv in proto.items():
                        if pk in ("identifier", "name", "config"):
                            continue
                        srl_protocols[pk] = pv
                ni_copy["protocols"] = srl_protocols
        result.append(ni_copy)
    return result


def _substitute_iface_names(node: Any, iface_map: dict[str, str]) -> Any:
    """Recursively substitute interface name values using iface_map.

    Only substitutes string values that appear as list-key fields (interface
    'name' leaf) or in known interface-name fields. Filters out loopbacks and
    interfaces not in the map (when iface_map is non-empty).
    """
    if isinstance(node, str):
        return iface_map.get(node, node)
    if isinstance(node, dict):
        return {k: _substitute_iface_names(v, iface_map) for k, v in node.items()}
    if isinstance(node, list):
        processed = []
        for item in node:
            item_out = _substitute_iface_names(item, iface_map)
            # If this is an interface list item with a 'name' key and iface_map is
            # non-empty, filter out entries whose name is still a vendor name
            # (not in iface_map values) or is a loopback.
            if (
                isinstance(item_out, dict)
                and "name" in item_out
                and iface_map
            ):
                name_val = item_out["name"]
                if isinstance(name_val, str):
                    import re as _re
                    if _re.match(r"^(loopback|lo)\d*$", name_val, _re.IGNORECASE):
                        continue  # skip loopbacks
                    # Skip if name was NOT translated (still a vendor name not in iface_map)
                    if name_val not in iface_map.values() and name_val in iface_map:
                        continue
            processed.append(item_out)
        return processed
    return node


def build_srl_json_from_oc_tree(
    oc_tree: dict,
    iface_map: dict[str, str],
) -> dict:
    """Convert a merged OC tree to SRL-importable JSON.

    Transformations (deterministic, no LLM):
    1. Strip OC module namespace keys (openconfig-interfaces → interface[])
    2. Remove OC plural wrapper containers (interfaces/ → implicit in SRL)
    3. Flatten config/ containers into their parent
    4. Drop state/ containers (read-only)
    5. Unwrap protocol[] list (OC: protocol[identifier=BGP].bgp → SRL: bgp)
    6. Substitute interface names via iface_map
    7. Map value enums (admin-status UP/DOWN → admin-state enable/disable)

    Args:
        oc_tree: Merged OC tree from merge_oc_records_for_device.
        iface_map: {vendor_iface: srl_ethernet} from topology (LLDP).

    Returns:
        SRL-native JSON dict ready for ``sr_cli load json <file>``.
    """
    srl: dict = {}

    for module_key, module_val in oc_tree.items():
        if not isinstance(module_val, dict):
            continue
        if module_key.startswith("_olav:") or module_key == "_unmapped":
            continue

        unwrap = _MODULE_UNWRAP.get(module_key)
        if unwrap is None:
            # Unknown module — include as-is under its key (LLM can repair if needed)
            srl_key = module_key.split(":")[-1]
            srl[srl_key] = _flatten_config_container(module_val)
            continue

        oc_wrapper, srl_top_key = unwrap
        # Unwrap the OC plural wrapper: {interfaces: {interface: [...]}} → interface: [...]
        inner = module_val.get(oc_wrapper, module_val)
        # inner may be {interface: [...]} or directly [{...}, ...]
        if isinstance(inner, dict):
            list_items = inner.get(srl_top_key, inner.get(oc_wrapper))
        elif isinstance(inner, list):
            list_items = inner
        else:
            list_items = None

        if list_items is None:
            continue

        # Flatten config/ containers
        flat_items = [
            _flatten_config_container(item) if isinstance(item, dict) else item
            for item in list_items
        ]

        # Protocol list unwrapping (network-instance only)
        if srl_top_key == "network-instance":
            flat_items = _unwrap_protocol_list(flat_items)

        # Interface name substitution
        if iface_map:
            flat_items = _substitute_iface_names(flat_items, iface_map)

        # Merge into srl dict (multiple modules may contribute to same top-level key)
        if srl_top_key in srl and isinstance(srl[srl_top_key], list):
            srl[srl_top_key].extend(flat_items)
        else:
            srl[srl_top_key] = flat_items

    return srl


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def build_srl_config_json(
    device: str,
    oc_records: list[dict],
    iface_map: dict[str, str],
) -> tuple[dict, list[dict]]:
    """Primary config generation path: OC records → SRL JSON.

    No LLM involved. The only transformations are deterministic structural
    conversions (see build_srl_json_from_oc_tree) + interface name substitution.

    Args:
        device:     Device name (for logging).
        oc_records: Output of apply_oc_mapping_cached for this device.
                    [{module_key: nested_oc_tree, ...}, ...]
        iface_map:  {vendor_iface: srl_ethernet} from topology (LLDP).

    Returns:
        (srl_json, vendor_fields)
        srl_json:       SRL-native JSON dict. Pass to json.dumps() → load json file.
                        May need LLM repair if SRL rejects it.
        vendor_fields:  List of _unmapped vendor field dicts. Pass to LLM to translate
                        to standard OC paths and merge into srl_json before retry.
    """
    if not oc_records:
        logger.debug("build_srl_config_json [%s]: no OC records", device)
        return {}, []

    oc_tree, vendor_fields = merge_oc_records_for_device(oc_records)

    if not oc_tree:
        logger.debug("build_srl_config_json [%s]: OC tree empty after merge", device)
        return {}, vendor_fields

    srl_json = build_srl_json_from_oc_tree(oc_tree, iface_map)

    logger.debug(
        "build_srl_config_json [%s]: %d top-level SRL keys, %d vendor extension fields",
        device, len(srl_json), len(vendor_fields),
    )
    return srl_json, vendor_fields
