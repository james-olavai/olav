"""Phase 2 topology extraction.

Derives ``topology_links`` from parsed outputs using this priority:

1. OC-structured LLDP/CDP data when available
2. Flat neighbor rows interpreted via ``schema_catalog`` field semantics

``mapping_rules`` is no longer part of the topology extraction contract.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import duckdb

from olav.core.inventory import get_inventory_provider

logger = logging.getLogger(__name__)


_NEIGHBOR_NAME_ALIASES = {
    "neighbor",
    "neighbor_name",
    "neighborname",
    "neighborhost",
    "system_name",
    "systemname",
    "remote_id",
    "remote_system_name",
    "device_id",
}

_NEIGHBOR_INTERFACE_ALIASES = {
    "neighbor_interface",
    "neighborinterface",
    "neighbor_port",
    "neighbor_port_id",
    "neighborportid",
    "remote_port",
    "remote_port_id",
    "remoteinterface",
    "port_id",
    "portid",
}

_LOCAL_INTERFACE_ALIASES = {
    "local_interface",
    "localinterface",
    "local_port",
    "localport",
    "interface",
    "interface_name",
    "local_port_id",
}


def _link_id(src: str, src_iface: str, dst: str, dst_iface: str) -> str:
    key = f"{src}|{src_iface}|{dst}|{dst_iface}"
    return hashlib.md5(key.encode()).hexdigest()[:16]  # noqa: S324 – non-security hash


def _protocol_for_command(command: str) -> str:
    cmd = command.lower()
    if "lldp" in cmd:
        return "LLDP"
    if "cdp" in cmd:
        return "CDP"
    return "UNKNOWN"


def _normalize_field_name(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum() or ch == "_").replace("-", "_")


def _load_schema_catalog_fields(
    con: duckdb.DuckDBPyConnection,
    command: str,
    platform: str | None,
) -> list[str]:
    params: list[Any]
    sql: str
    if platform:
        sql = (
            "SELECT fields FROM schema_catalog "
            "WHERE source_name = ? AND platform = ? "
            "ORDER BY updated_at DESC NULLS LAST LIMIT 1"
        )
        params = [command, platform]
    else:
        sql = (
            "SELECT fields FROM schema_catalog "
            "WHERE source_name = ? "
            "ORDER BY updated_at DESC NULLS LAST LIMIT 1"
        )
        params = [command]

    row = con.execute(sql, params).fetchone()
    if not row or not row[0]:
        return []

    try:
        payload = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    except Exception:
        logger.warning(
            "Invalid schema_catalog.fields JSON for command=%s platform=%s", command, platform
        )
        return []

    if not isinstance(payload, list):
        return []

    names: list[str] = []
    payload_items = cast(list[Any], payload)
    for item in payload_items:
        if isinstance(item, dict):
            item_dict = cast(dict[str, Any], item)
            if item_dict.get("name"):
                names.append(str(item_dict["name"]))
    return names


def _classify_fields(field_names: list[str]) -> dict[str, str | None]:
    roles: dict[str, str | None] = {
        "neighbor_name_field": None,
        "neighbor_iface_field": None,
        "local_iface_field": None,
    }
    for field in field_names:
        normalized = _normalize_field_name(field)
        if normalized in _NEIGHBOR_NAME_ALIASES:
            roles["neighbor_name_field"] = field
        elif normalized in _NEIGHBOR_INTERFACE_ALIASES:
            roles["neighbor_iface_field"] = field
        elif normalized in _LOCAL_INTERFACE_ALIASES:
            roles["local_iface_field"] = field

    for field in field_names:
        normalized = _normalize_field_name(field)
        if roles["neighbor_name_field"] is None and (
            "neighbor" in normalized or "system" in normalized or "remoteid" in normalized
        ):
            roles["neighbor_name_field"] = field
        if roles["neighbor_iface_field"] is None and (
            "port" in normalized or ("neighbor" in normalized and "interface" in normalized)
        ):
            roles["neighbor_iface_field"] = field
        if roles["local_iface_field"] is None and (
            "local" in normalized or normalized == "interface"
        ):
            roles["local_iface_field"] = field
    return roles


def _extract_from_oc_lldp(oc_data: dict[str, Any]) -> list[dict[str, str]]:
    """Extract flat neighbor records from OC-structured ``openconfig-lldp`` data.

    Navigates: openconfig-lldp → lldp → interfaces → interface[] →
               neighbors → neighbor[] → state → {system-name, port-id}
               + interface[] → config → name (local interface)

    Returns a list of flat dicts with keys: neighbor_name, neighbor_interface,
    local_interface for downstream topology insertion.
    """
    lldp_container_raw: Any = oc_data.get("openconfig-lldp", {})
    if not isinstance(lldp_container_raw, dict):
        return []
    lldp_container = cast(dict[str, Any], lldp_container_raw)
    lldp: Any = lldp_container.get("lldp", lldp_container)
    if not isinstance(lldp, dict):
        return []
    lldp_dict = cast(dict[str, Any], lldp)
    interfaces_container: Any = lldp_dict.get("interfaces", {})
    if not isinstance(interfaces_container, dict):
        return []
    interfaces_dict = cast(dict[str, Any], interfaces_container)

    iface_list: Any = interfaces_dict.get("interface", [])
    if isinstance(iface_list, dict):
        iface_list = [iface_list]
    if not isinstance(iface_list, list):
        return []
    iface_items = cast(list[Any], iface_list)

    results: list[dict[str, str]] = []
    for iface in iface_items:
        if not isinstance(iface, dict):
            continue
        iface_dict = cast(dict[str, Any], iface)

        local_name = ""
        config: Any = iface_dict.get("config", {})
        if isinstance(config, dict):
            local_name = str(cast(dict[str, Any], config).get("name", ""))
        if not local_name:
            continue

        neighbors_container: Any = iface_dict.get("neighbors", {})
        if not isinstance(neighbors_container, dict):
            continue
        neighbors_dict = cast(dict[str, Any], neighbors_container)
        neighbor_list: Any = neighbors_dict.get("neighbor", [])
        if isinstance(neighbor_list, dict):
            neighbor_list = [neighbor_list]
        if not isinstance(neighbor_list, list):
            continue
        neighbor_items = cast(list[Any], neighbor_list)

        for neighbor in neighbor_items:
            if not isinstance(neighbor, dict):
                continue
            neighbor_dict = cast(dict[str, Any], neighbor)
            state: Any = neighbor_dict.get("state", {})
            if not isinstance(state, dict):
                continue
            state_dict = cast(dict[str, Any], state)

            port_id = str(state_dict.get("port-id", ""))
            if not port_id:
                continue

            neighbor_name = str(state_dict.get("system-name", ""))
            if not neighbor_name:
                continue

            results.append(
                {
                    "neighbor_name": neighbor_name,
                    "neighbor_interface": port_id,
                    "local_interface": local_name,
                }
            )

    return results


def _topology_table(con: duckdb.DuckDBPyConnection) -> str:
    try:
        row = con.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema='netops' AND table_name='topology_links' AND table_type='BASE TABLE'"
        ).fetchone()
        if row and int(row[0]) > 0:
            return "netops.topology_links"
    except Exception:
        pass
    return "topology_links"


# DEPRECATED: Use InventoryProvider.resolve() instead
def _normalize_device_name(raw_name: str, known_devices: set[str]) -> str:
    """Normalize LLDP/CDP neighbor name to match the canonical device name.

    Strips common domain suffixes (.local, FQDN parts) and matches against
    known device names from the devices table.
    """
    name = raw_name.strip()
    if not name:
        return name
    if name in known_devices:
        return name
    short = name.split(".")[0]
    if short in known_devices:
        return short
    return name


def extract_lldp_topology(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Extract LLDP/CDP neighbour links from parsed_outputs into topology_links.

    Handles OC-structured parsed_data and strict mapped flat records.
    """
    rows = con.execute(
        """
        SELECT device_name, command, parsed_data, snapshot_id
        FROM   parsed_outputs
        WHERE  (lower(command) LIKE '%lldp%'
           OR   lower(command) LIKE '%cdp%')
          AND  (raw_output IS NOT NULL OR command LIKE 'netconf_%')
        """
    ).fetchall()

    known_devices: set[str] = set()
    device_platforms: dict[str, str] = {}
    provider = get_inventory_provider(con)
    for identity in provider.list_devices():
        known_devices.add(identity.canonical_name)
        if identity.platform:
            device_platforms[identity.canonical_name] = identity.platform

    now = datetime.utcnow()
    links_inserted = 0
    tbl = _topology_table(con)

    for device_name, command, parsed_data_raw, snapshot_id in rows:
        protocol = _protocol_for_command(command)

        if isinstance(parsed_data_raw, str):
            try:
                parsed = json.loads(parsed_data_raw)
            except json.JSONDecodeError:
                logger.warning("Unparseable JSON for %s / %s", device_name, command)
                continue
        else:
            parsed = parsed_data_raw

        entries: list[dict[str, str]]

        if isinstance(parsed, dict):
            parsed_dict = cast(dict[str, Any], parsed)
            if any(k.startswith("openconfig-") for k in parsed_dict.keys()):
                entries = _extract_from_oc_lldp(parsed_dict)
            else:
                continue
        elif isinstance(parsed, list):
            parsed_list = cast(list[Any], parsed)
            oc_items: list[dict[str, Any]] = []
            for item in parsed_list:
                if not isinstance(item, dict):
                    continue
                item_dict = cast(dict[str, Any], item)
                if any(k.startswith("openconfig-") for k in item_dict.keys()):
                    oc_items.append(item_dict)
            if oc_items:
                entries = []
                for item in oc_items:
                    entries.extend(_extract_from_oc_lldp(cast(dict[str, Any], item)))
            else:
                field_names = _load_schema_catalog_fields(
                    con,
                    command,
                    device_platforms.get(str(device_name)),
                )
                if not field_names and parsed_list:
                    first_entry = parsed_list[0]
                    if isinstance(first_entry, dict):
                        field_names = [str(key) for key in cast(dict[str, Any], first_entry).keys()]

                roles = _classify_fields(field_names)
                nn_field = roles["neighbor_name_field"]
                ni_field = roles["neighbor_iface_field"]
                li_field = roles["local_iface_field"]
                if not (nn_field and ni_field and li_field):
                    continue

                entries = []
                for entry in parsed_list:
                    if not isinstance(entry, dict):
                        continue
                    entry_dict = cast(dict[str, Any], entry)
                    entries.append(
                        {
                            "neighbor_name": str(entry_dict.get(nn_field, "")).strip(),
                            "neighbor_interface": str(entry_dict.get(ni_field, "")).strip(),
                            "local_interface": str(entry_dict.get(li_field, "")).strip(),
                        }
                    )
        else:
            continue

        for rec in entries:
            raw_neighbor = rec.get("neighbor_name", "")
            resolved = provider.resolve(raw_neighbor)
            neighbor_name = resolved.canonical_name if resolved is not None else raw_neighbor
            neighbor_iface = rec.get("neighbor_interface", "").strip()
            local_iface = rec.get("local_interface", "").strip()

            if not neighbor_name:
                continue
            if device_name == neighbor_name:
                continue

            lid = _link_id(device_name, local_iface, neighbor_name, neighbor_iface)

            con.execute(
                f"""
                INSERT OR REPLACE INTO {tbl} (
                    link_id, source_device, source_interface,
                    destination_device, destination_interface,
                    discovery_protocol, link_type, link_status, link_speed,
                    first_seen, last_seen, last_verified,
                    status_changes, snapshot_id, platform
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                [
                    lid,
                    device_name,
                    local_iface,
                    neighbor_name,
                    neighbor_iface,
                    protocol,
                    "L2",
                    "up",
                    None,
                    now,
                    now,
                    now,
                    0,
                    snapshot_id,
                    None,
                ],
            )
            links_inserted += 1

    return {"links_inserted": links_inserted}
