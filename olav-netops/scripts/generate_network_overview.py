"""generate_network_overview.py — write a per-deployment Network
Overview guide that the LLM sees on every netops query.

R-VERTICAL-SLICE 2026-05-10 (dev_docs/70).  Eliminates the
"discovery loop" failure mode where the LLM has to call
inspect_devices + inspect_topology + inspect_routing 3 times before
it even knows the network shape.

Output: ``.olav/workspace/netops/guides/network_overview.guide.yaml``
which lands in the LanceDB usage_guide store via
``olav kb import-guides`` (run by ``olav agent install``).

Run from a workspace root (must contain
``.olav/databases/main.duckdb``).  Idempotent — overwrites any prior
overview.

Usage:
  python -m olav_netops.scripts.generate_network_overview
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

import duckdb

logger = logging.getLogger("network_overview")
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _resolve_db_path() -> Path:
    cwd_db = Path.cwd() / ".olav" / "databases" / "main.duckdb"
    if cwd_db.exists():
        return cwd_db
    from olav.core.config import MAIN_DB_PATH
    return Path(MAIN_DB_PATH)


def _resolve_guide_path() -> Path:
    """Where the generated guide goes — workspace netops/guides/."""
    cwd_path = Path.cwd() / ".olav" / "workspace" / "netops" / "guides"
    if cwd_path.exists():
        return cwd_path / "network_overview.guide.yaml"
    raise RuntimeError(
        f"netops/guides dir not found at {cwd_path}; run from a workspace root"
    )


def _query_devices(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Return (hostname, platform, ip, role) for every inventoried device."""
    return conn.execute(
        """
        SELECT hostname, platform, ip_address, role
        FROM netops.devices
        WHERE hostname IS NOT NULL
        ORDER BY hostname
        """
    ).fetchall()


def _query_facts() -> dict[str, dict]:
    """Use load_network_model so we get the full reverse-resolved facts
    (loopback, local_as) from the same code path the inspectors use."""
    try:
        from olav_netops.sim import load_network_model
        m = load_network_model()
        return {h: dict(f) for h, f in m.facts.items()}
    except Exception as e:
        logger.warning("load_network_model failed: %s", e)
        return {}


def _query_bgp_sessions(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    """All BGP sessions across vendors via v_bgp_neighbors_auto."""
    try:
        return conn.execute(
            """
            SELECT device_name, neighbor_ip, neighbor_as, state,
                   prefixes_received, vendor_family
            FROM netops.v_bgp_neighbors_auto
            ORDER BY device_name, neighbor_ip
            """
        ).fetchall()
    except Exception:
        return []


def _query_topology_links(conn: duckdb.DuckDBPyConnection) -> list[tuple]:
    """Cross-vendor L2 links."""
    try:
        return conn.execute(
            """
            SELECT source_device, source_interface,
                   destination_device, destination_interface,
                   discovery_protocol, link_status
            FROM netops.v_l2_links_auto
            ORDER BY source_device, destination_device
            LIMIT 80
            """
        ).fetchall()
    except Exception:
        return []


def _resolve_ip_to_hostname(ip: str | None, facts: dict[str, dict]) -> str | None:
    if not ip:
        return None
    for h, f in facts.items():
        if str(f.get("loopback")) == str(ip):
            return h
    return None


def render_overview(
    devices: list[tuple],
    facts: dict[str, dict],
    bgp: list[tuple],
    links: list[tuple],
) -> str:
    """Compose the Markdown body of the guide."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    # Devices section grouped by role
    routers = [d for d in devices if (d[3] or "").lower() in
               {"border", "core", "router", "edge", "spine", "leaf"}]
    access = [d for d in devices if (d[3] or "").lower() == "access"]
    other = [d for d in devices if d not in routers and d not in access]

    parts: list[str] = []
    parts.append(f"# Network Overview")
    parts.append(f"_Auto-generated {now} from netops.devices + "
                 f"netops.v_bgp_neighbors_auto + netops.v_l2_links_auto._")
    parts.append("")
    parts.append(f"**Inventory**: {len(routers)} routed, {len(access)} access, "
                 f"{len(other)} other.")
    parts.append("")

    parts.append("## Devices")
    parts.append("")
    for hostname, platform, ip, role in devices:
        f = facts.get(hostname, {})
        loopback = f.get("loopback") or "-"
        as_ = f.get("local_as") or "-"
        bits = [f"`{hostname}`"]
        if platform: bits.append(f"({platform})")
        if role: bits.append(f"role={role}")
        bits.append(f"mgmt={ip}" if ip else "mgmt=-")
        bits.append(f"loopback={loopback}")
        bits.append(f"AS={as_}")
        parts.append(f"- {' '.join(bits)}")
    parts.append("")

    # BGP topology
    parts.append("## BGP topology")
    parts.append("")
    if not bgp:
        parts.append("_No BGP sessions found in v_bgp_neighbors_auto._")
    else:
        # Aggregate
        established = [b for b in bgp if b[3] == "Established"]
        zero_pfx = [b for b in established if b[4] == 0]
        parts.append(f"**{len(bgp)} sessions** ({len(established)} Established, "
                     f"{len(zero_pfx)} of those receiving 0 prefixes).")
        parts.append("")
        parts.append("| Device | Peer | AS | State | Prefixes |")
        parts.append("|---|---|---|---|---|")
        for dev, peer_ip, peer_as, state, pfx, vendor in bgp:
            peer_name = _resolve_ip_to_hostname(peer_ip, facts)
            peer_repr = f"{peer_name} ({peer_ip})" if peer_name else str(peer_ip)
            parts.append(f"| {dev} | {peer_repr} | {peer_as} | {state} | "
                         f"{pfx if pfx is not None else '-'} |")
        parts.append("")
        if zero_pfx and len(zero_pfx) == len(established):
            parts.append("⚠ **Network-wide observation**: every Established "
                         "BGP session is receiving 0 prefixes.  This is a "
                         "systemic issue (likely no `network` statements / "
                         "redistribution configured).")
            parts.append("")

    # L2 topology
    parts.append("## L2 topology (LLDP/CDP)")
    parts.append("")
    if not links:
        parts.append("_No L2 links found in v_l2_links_auto._")
    else:
        parts.append(f"**{len(links)} adjacencies** (showing first 80):")
        parts.append("")
        for src, src_int, dst, dst_int, proto, status in links[:80]:
            parts.append(f"- `{src}:{src_int}` ↔ `{dst}:{dst_int}` "
                         f"({proto}, {status or 'unknown'})")
    parts.append("")

    # Hint to LLM
    parts.append("## Notes for the agent")
    parts.append("")
    parts.append("- Use this overview BEFORE calling inspect_* — it answers "
                 "\"who exists\", \"what AS\", \"who peers with whom\" without "
                 "any tool calls.")
    parts.append("- Cross-reference device hostnames + AS + loopback IP when "
                 "the user mentions an IP — the BGP table above maps both ways.")
    parts.append("- Numbers reflect the most recent ingested snapshot at the "
                 "time of generation.  For real-time state changes, still "
                 "call inspect_routing or take a fresh snapshot.")
    parts.append("")

    return "\n".join(parts)


def write_guide(body: str, guide_path: Path) -> None:
    """Wrap body in usage_guide YAML envelope so AutoRecall sees it."""
    yaml_content = f"""schema_version: 1
intent: network_overview
agent: netops
keywords:
  - network overview
  - what devices
  - what is the topology
  - inventory
  - which routers
  - what AS
  - 网络拓扑
  - 设备清单
  - 哪些路由器
  - environment
  - what does the network look like
  - lay of the land
body: |
{chr(10).join('  ' + line for line in body.splitlines())}
"""
    guide_path.parent.mkdir(parents=True, exist_ok=True)
    guide_path.write_text(yaml_content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Print to stdout; don't write the guide file")
    args = parser.parse_args()

    db_path = _resolve_db_path()
    logger.info("DB: %s", db_path)

    with duckdb.connect(str(db_path), read_only=True) as conn:
        devices = _query_devices(conn)
        bgp = _query_bgp_sessions(conn)
        links = _query_topology_links(conn)

    facts = _query_facts()
    body = render_overview(devices, facts, bgp, links)

    if args.dry_run:
        print(body)
        return 0

    guide_path = _resolve_guide_path()
    write_guide(body, guide_path)
    logger.info("Wrote %s (%d devices, %d BGP, %d L2 links)",
                guide_path, len(devices), len(bgp), len(links))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
