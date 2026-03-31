"""Build a ContainerLab topology YAML from the snapshot database.

Reads netops.devices and netops.topology_links to generate a CLAB topology
where all nodes are SR Linux (nokia_srlinux) regardless of production platform.

Topology rules:
  - All devices in netops.devices become SRL nodes
  - Links from topology_links (both OSPF and BGP)
  - IP-only destination names (e.g. "10.1.12.2") are resolved to hostnames
    via the devices table and ARP/BGP adjacency data
  - Duplicate links (A→B and B→A) are deduplicated
  - Interface names are mapped to SRL ethernet-1/N format
  - Management IPs: 192.168.100.110+ (avoids collision with physical 101-106)

Tool: build_topology_yaml

Args (JSON):
    lab_name:   str | None   — lab name (default: "digital-twin")
    db_path:    str | None   — path to main.duckdb (default: .olav/databases/main.duckdb)
    srl_image:  str | None   — SRL image (default: ghcr.io/nokia/srlinux:latest)
    protocols:  list[str] | None — filter link protocols ["OSPF","BGP"] (default: all)

Returns: JSON string
    {"yaml": "<clab topology YAML string>", "nodes": [...], "links": [...]}
    {"error": "..."}
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import duckdb
import yaml

_OLAV_SRC = Path(__file__).parents[5] / "src"
if str(_OLAV_SRC) not in sys.path:
    sys.path.insert(0, str(_OLAV_SRC))

# Reuse interface name mapper from lab-old
_LAB_OLD_SCRIPTS = Path(__file__).parents[3] / "lab-old" / "scripts"
if str(_LAB_OLD_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_LAB_OLD_SCRIPTS))

try:
    from clab_topology_render import map_iface_to_srl
except ImportError:
    # Fallback inline if lab-old not available
    def map_iface_to_srl(iface: str, fallback_index: int = 1) -> str:  # type: ignore[misc]
        _GI = re.compile(r"^(?:gi|gigabitethernet)\d+/(\d+)$", re.I)
        _ETH = re.compile(r"^(?:eth|e|ethernet)(\d+)$", re.I)
        _ET = re.compile(r"^et(\d+)$", re.I)
        _ETDASH = re.compile(r"^et-\d+/\d+/(\d+)$", re.I)
        _SRL = re.compile(r"^ethernet-\d+/(\d+)$", re.I)
        if not iface:
            return f"ethernet-1/{fallback_index}"
        m = _SRL.match(iface)
        if m:
            return iface.lower()
        m = _ETH.match(iface)
        if m:
            return f"ethernet-1/{m.group(1)}"
        m = _ET.match(iface)
        if m:
            return f"ethernet-1/{max(int(m.group(1)), 1)}"
        m = _GI.match(iface)
        if m:
            return f"ethernet-1/{m.group(1)}"
        m = _ETDASH.match(iface)
        if m:
            return f"ethernet-1/{int(m.group(1)) + 1}"
        return f"ethernet-1/{fallback_index}"

_DEFAULT_DB = Path(".olav") / "databases" / "main.duckdb"
_DEFAULT_IMAGE = "ghcr.io/nokia/srlinux:latest"
_DEFAULT_LAB = "digital-twin"
_IPV4_RE = re.compile(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$")

# BGP:10.0.0.1 style interface names — extract IP for resolution
_BGP_IFACE_RE = re.compile(r"^BGP:(.+)$", re.I)


def _is_ip(s: str) -> bool:
    return bool(_IPV4_RE.match(s or ""))


def _build_ip_to_hostname(con) -> dict[str, str]:
    """Build IP → hostname map from devices table and BGP adjacency data."""
    ip_map: dict[str, str] = {}

    # Management IPs from devices table
    try:
        rows = con.execute(
            "SELECT hostname, ip_address FROM netops.devices WHERE ip_address IS NOT NULL"
        ).fetchall()
        for hostname, ip in rows:
            if ip:
                ip_map[ip.strip()] = hostname
    except Exception:
        pass

    # BGP router-IDs from oc_outputs (router-id → device)
    try:
        rows = con.execute(
            """
            SELECT device_name, json_extract_string(oc_data, '$.bgp.global.config.router-id') AS rid
            FROM netops.oc_outputs
            WHERE oc_module = 'openconfig-bgp'
              AND json_extract_string(oc_data, '$.bgp.global.config.router-id') IS NOT NULL
            """
        ).fetchall()
        for device_name, rid in rows:
            if rid and rid not in ip_map:
                ip_map[rid.strip()] = device_name
    except Exception:
        pass

    # BGP peer IPs from parsed_outputs: if peer X is a neighbor of device Y,
    # and X is not in ip_map, we can't resolve. But we can cross-reference:
    # if device A says peer is 10.1.12.2, and 10.1.12.2 is A's neighbor IP,
    # we look for who has that IP on their interface.
    # This requires interface IP data which we may not have. Skip for now.

    return ip_map


def _resolve(name: str, ip_map: dict[str, str]) -> str | None:
    """Resolve a hostname or IP to a known hostname. Returns None if unresolvable."""
    if not _is_ip(name):
        return name  # already a hostname
    return ip_map.get(name)  # None if unknown IP


def _is_bogus_iface(iface: str | None) -> bool:
    """Return True if this is not a real interface name (BGP peer markers, etc.)."""
    if not iface:
        return True
    if iface.startswith("BGP:") or iface.startswith("ospf-peer") or iface.startswith("bgp-peer"):
        return True
    return False


def build_topology_yaml(args: dict) -> str:
    """Build CLAB topology YAML from snapshot DB."""
    lab_name: str = args.get("lab_name") or _DEFAULT_LAB
    db_path_str: str | None = args.get("db_path")
    srl_image: str = args.get("srl_image") or _DEFAULT_IMAGE
    protocols: list[str] | None = args.get("protocols")

    db_path = Path(db_path_str) if db_path_str else _DEFAULT_DB

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return json.dumps({"error": f"cannot open DB: {exc}"})

    try:
        # 1. Load all devices
        device_rows = con.execute(
            "SELECT hostname, platform, ip_address FROM netops.devices ORDER BY hostname"
        ).fetchall()
        if not device_rows:
            return json.dumps({"error": "no devices in netops.devices"})

        known_hostnames = {r[0] for r in device_rows}

        # 2. Build IP→hostname resolution map
        ip_map = _build_ip_to_hostname(con)

        # 3. Load topology links
        link_rows = con.execute(
            """
            SELECT source_device, destination_device,
                   source_interface, destination_interface,
                   discovery_protocol, link_type
            FROM netops.topology_links
            ORDER BY source_device, destination_device
            """
        ).fetchall()

        con.close()

        # 4. Filter and resolve links
        seen_pairs: set[frozenset] = set()
        resolved_links: list[dict[str, Any]] = []
        node_iface_counter: dict[str, int] = defaultdict(int)

        for src, dst, src_iface, dst_iface, proto, link_type in link_rows:
            # Protocol filter
            if protocols and proto not in protocols:
                continue

            # Resolve destination if IP
            resolved_dst = _resolve(dst, ip_map)
            if resolved_dst is None:
                # Unresolvable IP — skip link but don't crash
                continue

            # Both endpoints must be known devices
            if src not in known_hostnames or resolved_dst not in known_hostnames:
                continue

            # Deduplicate (A→B == B→A)
            pair = frozenset({src, resolved_dst})
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            # Map interface names to SRL format
            if _is_bogus_iface(src_iface):
                node_iface_counter[src] += 1
                srl_src = f"ethernet-1/{node_iface_counter[src]}"
            else:
                srl_src = map_iface_to_srl(src_iface, fallback_index=node_iface_counter[src] + 1)
                node_iface_counter[src] += 1

            if _is_bogus_iface(dst_iface):
                node_iface_counter[resolved_dst] += 1
                srl_dst = f"ethernet-1/{node_iface_counter[resolved_dst]}"
            else:
                srl_dst = map_iface_to_srl(dst_iface, fallback_index=node_iface_counter[resolved_dst] + 1)
                node_iface_counter[resolved_dst] += 1

            resolved_links.append({
                "src": src, "dst": resolved_dst,
                "src_iface": srl_src, "dst_iface": srl_dst,
                "protocol": proto,
            })

        # 5. Build CLAB topology dict
        # Management IPs: start at .110 to avoid collision with physical devices (.101-.106)
        mgmt_base = 110
        nodes: dict[str, Any] = {}
        node_list = sorted(known_hostnames)
        for i, hostname in enumerate(node_list):
            nodes[hostname] = {
                "mgmt-ipv4": f"192.168.100.{mgmt_base + i}",
            }

        clab_links = [
            {"endpoints": [f"{lk['src']}:{lk['src_iface']}", f"{lk['dst']}:{lk['dst_iface']}"]}
            for lk in resolved_links
        ]

        topo_dict = {
            "name": lab_name,
            "prefix": "",  # container names = node names (no clab- prefix)
            "mgmt": {
                "network": f"mgmt-{lab_name}",
                "ipv4-subnet": "192.168.100.0/24",
            },
            "topology": {
                "defaults": {
                    "kind": "nokia_srlinux",
                    "image": srl_image,
                    "type": "ixrd3",  # SRL hardware type — needed for datapath init
                },
                "nodes": nodes,
                "links": clab_links,
            },
        }

        topo_yaml = yaml.dump(topo_dict, default_flow_style=False, sort_keys=False)

        return json.dumps({
            "yaml": topo_yaml,
            "nodes": node_list,
            "links": [{"src": lk["src"], "dst": lk["dst"], "protocol": lk["protocol"]}
                      for lk in resolved_links],
        })

    except Exception as exc:
        try:
            con.close()
        except Exception:
            pass
        return json.dumps({"error": str(exc)})


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Build CLAB topology YAML from snapshot DB")
    parser.add_argument("args_json", nargs="?", default="{}")
    parsed = parser.parse_args()
    result = json.loads(build_topology_yaml(json.loads(parsed.args_json)))
    if "yaml" in result:
        print(result["yaml"])
        print(f"# nodes: {result['nodes']}")
        print(f"# links: {result['links']}")
    else:
        print(json.dumps(result, indent=2))
