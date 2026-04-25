"""Topology ETL — extract neighbour relationships into ``netops.topology_links``.

Protocols and their field mappings are declared in
``.olav/workspace/ops/netops_init/config/discovery_protocols.yaml``. Adding
a new protocol (IS-IS, BFD, FabricPath, …) is a YAML-only change — no
Python edits needed. Only the optional "raw output" regex fallback is
hardcoded for the two ubiquitous protocols (CDP/LLDP); new protocols rely
on TextFSM/ntc-templates/PaC populating ``parsed_outputs`` first.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

from olav.core.utils import utc_now

if TYPE_CHECKING:
    import duckdb as _duckdb

logger = logging.getLogger(__name__)

_PROTOCOLS_CACHE: dict[str, dict[str, Any]] | None = None


def _protocols_path() -> Path:
    """Resolve discovery_protocols.yaml shipped with the ops skill workspace."""
    try:
        from olav.core.config import get_paths_config
        base = Path(get_paths_config().agent_dir) / "workspace" / "ops" / "netops_init" / "config"
        candidate = base / "discovery_protocols.yaml"
        if candidate.exists():
            return candidate
    except Exception:
        pass
    here = Path(__file__).resolve().parent
    for up in [here.parent.parent.parent, here.parent.parent.parent.parent]:
        candidate = up / ".olav" / "workspace" / "ops" / "netops_init" / "config" / "discovery_protocols.yaml"
        if candidate.exists():
            return candidate
    return Path("")


def load_discovery_protocols(force_reload: bool = False) -> dict[str, dict[str, Any]]:
    """Load discovery_protocols.yaml into a cache dict.

    Returns ``{key: protocol_spec}``. Empty dict + WARN log on missing
    file / parse error — callers treat as "no discovery protocols
    configured" and the ETL becomes a no-op (non-fatal).
    """
    global _PROTOCOLS_CACHE
    if _PROTOCOLS_CACHE is not None and not force_reload:
        return _PROTOCOLS_CACHE
    path = _protocols_path()
    if not path or not path.exists():
        logger.warning("discovery_protocols.yaml not found; topology ETL will be empty")
        _PROTOCOLS_CACHE = {}
        return _PROTOCOLS_CACHE
    try:
        import yaml
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("discovery_protocols.yaml parse failed: %s", exc)
        _PROTOCOLS_CACHE = {}
        return _PROTOCOLS_CACHE
    protos = data.get("protocols") or {}
    if not isinstance(protos, dict):
        logger.warning("discovery_protocols.yaml: top-level 'protocols' must be a mapping")
        _PROTOCOLS_CACHE = {}
        return _PROTOCOLS_CACHE
    _PROTOCOLS_CACHE = protos
    return _PROTOCOLS_CACHE


def _make_link_id(src_dev: str, src_intf: str, dst_dev: str, dst_intf: str) -> str:
    """Deterministic bidirectional link ID — A→B and B→A produce the same ID."""
    pair_a = f"{src_dev.lower()}:{src_intf.lower()}"
    pair_b = f"{dst_dev.lower()}:{dst_intf.lower()}"
    canonical = "|".join(sorted([pair_a, pair_b]))
    return hashlib.md5(canonical.encode()).hexdigest()  # noqa: S324


def _normalise(val: Any) -> str:
    if val is None:
        return ""
    return str(val).strip()


def _pick(entry: dict[str, Any], fields: list[str]) -> str:
    for f in fields:
        val = entry.get(f)
        if isinstance(val, list):
            val = val[0] if val else None
        if val:
            return _normalise(val)
    return ""


def _ensure_topology_table(con: "_duckdb.DuckDBPyConnection") -> None:
    try:
        from olav.platform.ingest_base import TableRegistry
        topo_tbl = TableRegistry.get("topology_links")
        if topo_tbl is not None:
            topo_tbl.ensure_schema(con)
            return
    except Exception as exc:
        logger.debug("TableRegistry lookup for topology_links failed: %s", exc)
    # Fallback DDL — kept minimal to match the registered schema.
    con.execute("CREATE SCHEMA IF NOT EXISTS netops")
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS netops.topology_links (
            link_id VARCHAR PRIMARY KEY,
            source_device VARCHAR NOT NULL, source_interface VARCHAR NOT NULL,
            destination_device VARCHAR NOT NULL, destination_interface VARCHAR NOT NULL,
            discovery_protocol VARCHAR, link_type VARCHAR, link_status VARCHAR,
            link_speed VARCHAR, first_seen TIMESTAMP NOT NULL, last_seen TIMESTAMP NOT NULL,
            last_verified TIMESTAMP, status_changes INTEGER,
            snapshot_id VARCHAR NOT NULL, platform VARCHAR
        )
        """
    )


def _insert_link(
    con: "_duckdb.DuckDBPyConnection",
    *,
    src_dev: str, src_intf: str,
    dst_dev: str, dst_intf: str,
    protocol: str, link_type: str,
    snapshot_id: str, now: str,
) -> bool:
    if not (src_dev and dst_dev):
        return False

    # gitea #16: canonicalise destination against netops.devices BEFORE
    # writing so CDP/LLDP ``.local`` / ``.corp`` / ``.example.com`` variants
    # collapse to the inventory hostname and bidirectional dedup works in
    # plain SQL.  ``canonicalize`` is a no-op when dst_dev already matches
    # a device exactly, and a pass-through when no device matches (external
    # devices such as upstream ``WAN`` / ``Switch`` stay unchanged).
    from olav_netops.core.hostname_registry import canonicalize
    dst_dev = canonicalize(dst_dev, con)
    # Source side should already be canonical (it comes from nornir
    # inventory via the parsed_outputs.device_name column), but run it
    # through the same resolver to catch future drift.
    src_dev = canonicalize(src_dev, con)

    if src_dev == dst_dev:
        # self-loop after canonicalisation — e.g. an LLDP receive loop
        # on a management interface; drop rather than write a useless
        # A→A row that will always sort-alphabetical-dedupe to nothing.
        return False

    link_id = _make_link_id(src_dev, src_intf, dst_dev, dst_intf)
    try:
        con.execute(
            """
            INSERT OR IGNORE INTO netops.topology_links
                (link_id, source_device, source_interface,
                 destination_device, destination_interface,
                 discovery_protocol, link_type, link_status,
                 first_seen, last_seen, snapshot_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'up', ?, ?, ?)
            """,
            [link_id, src_dev, src_intf, dst_dev, dst_intf,
             protocol, link_type, now, now, snapshot_id or "unknown"],
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.debug("topology_engine: insert failed for %s: %s", link_id, exc)
        return False


def extract_lldp_topology(con: "_duckdb.DuckDBPyConnection") -> int:
    """Extract neighbour records from ``parsed_outputs`` into ``topology_links``.

    Protocols and their field hints come from ``discovery_protocols.yaml``.
    Name kept for back-compat; actually handles every configured protocol.
    """
    protos = load_discovery_protocols()
    if not protos:
        return 0

    _ensure_topology_table(con)

    now = utc_now().isoformat(timespec="seconds")
    inserted = 0

    # Build a single SQL IN-list from every configured command.
    all_commands: list[str] = []
    cmd_to_spec: dict[str, tuple[str, dict[str, Any]]] = {}
    for key, spec in protos.items():
        if not isinstance(spec, dict):
            continue
        for cmd in spec.get("commands") or []:
            if isinstance(cmd, str):
                all_commands.append(cmd)
                cmd_to_spec[cmd] = (key, spec)
    if not all_commands:
        return 0

    placeholders = ",".join("?" * len(all_commands))
    query = (
        "SELECT device_name, command, parsed_data, snapshot_id "
        "FROM netops.parsed_outputs "
        f"WHERE command IN ({placeholders}) AND parsed_data IS NOT NULL"
    )
    try:
        rows = con.execute(query, all_commands).fetchall()
    except Exception as exc:  # noqa: BLE001
        logger.warning("topology_engine: could not query parsed_outputs: %s", exc)
        return 0

    for device_name, command, parsed_data, snapshot_id in rows:
        proto_key, spec = cmd_to_spec.get(command, (None, None))
        if spec is None:
            continue
        protocol = spec.get("name") or proto_key.upper() if proto_key else "UNKNOWN"
        link_type = spec.get("link_type") or "L2"
        local_fields = spec.get("local_interface_fields") or []
        neigh_dev_fields = spec.get("neighbor_device_fields") or []
        neigh_intf_fields = spec.get("neighbor_interface_fields") or []

        if isinstance(parsed_data, str):
            try:
                entries = json.loads(parsed_data)
            except json.JSONDecodeError:
                continue
        elif isinstance(parsed_data, list):
            entries = parsed_data
        else:
            continue

        if not isinstance(entries, list):
            continue

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            src_dev = _normalise(device_name)
            src_intf = _pick(entry, local_fields)
            dst_dev = _pick(entry, neigh_dev_fields)
            dst_intf = _pick(entry, neigh_intf_fields)
            if _insert_link(
                con,
                src_dev=src_dev, src_intf=src_intf,
                dst_dev=dst_dev, dst_intf=dst_intf,
                protocol=protocol, link_type=link_type,
                snapshot_id=snapshot_id, now=now,
            ):
                inserted += 1

    # Raw-output fallback (CDP/LLDP only — these are ubiquitous and their
    # raw format is well-known; custom protocols should train a PaC parser
    # rather than rely on regex).
    try:
        devices_with_links = {
            r[0] for r in con.execute(
                "SELECT DISTINCT source_device FROM netops.topology_links"
            ).fetchall()
        }
        all_devices: set[str] = set()
        try:
            all_devices = {
                r[0] for r in con.execute("SELECT hostname FROM netops.devices").fetchall()
            }
        except Exception as exc:
            logger.debug("netops.devices probe failed: %s", exc)
        missing = all_devices - devices_with_links
        if missing:
            logger.info("topology_engine: %d devices missing links, trying raw fallback", len(missing))
            inserted += _raw_fallback(con, protos, missing, now)
    except Exception as exc:
        logger.debug("topology_engine: raw fallback wrapper failed (non-fatal): %s", exc)

    logger.info("topology_engine: inserted %d topology_links rows", inserted)
    return inserted


def _raw_fallback(
    con: "_duckdb.DuckDBPyConnection",
    protos: dict[str, dict[str, Any]],
    devices: set[str],
    now: str,
) -> int:
    """Regex-based neighbour extraction from raw CLI text, driven by
    ``raw_fallback`` in the protocol spec. Only CDP/LLDP have built-in
    regexes; unknown ``raw_fallback`` values are ignored."""
    inserted = 0
    for key, spec in protos.items():
        fallback_kind = (spec.get("raw_fallback") or "").lower()
        if fallback_kind not in {"cdp", "lldp"}:
            continue
        protocol = spec.get("name") or key.upper()
        link_type = spec.get("link_type") or "L2"
        commands = spec.get("commands") or []
        for device in devices:
            for cmd in commands:
                try:
                    rows = con.execute(
                        "SELECT raw_output, snapshot_id FROM netops.raw_output_store "
                        "WHERE device_name = ? AND command = ?",
                        [device, cmd],
                    ).fetchall()
                except Exception:
                    continue
                for raw_output, snapshot_id in rows:
                    if not raw_output or len(raw_output) < 50:
                        continue
                    links = _parse_neighbors_from_raw(raw_output, device, fallback_kind)
                    for src_intf, dst_dev, dst_intf in links:
                        if _insert_link(
                            con,
                            src_dev=device, src_intf=src_intf,
                            dst_dev=dst_dev, dst_intf=dst_intf,
                            protocol=protocol, link_type=link_type,
                            snapshot_id=snapshot_id, now=now,
                        ):
                            inserted += 1
    if inserted:
        logger.info("topology_engine: raw fallback extracted %d additional links", inserted)
    return inserted


def _parse_neighbors_from_raw(
    raw_text: str, source_device: str, protocol: str
) -> list[tuple[str, str, str]]:
    """Regex neighbour extraction for the built-in raw fallbacks (CDP/LLDP).

    Returns list of (source_interface, dest_device, dest_interface).
    """
    import re
    results: list[tuple[str, str, str]] = []
    lines = raw_text.strip().split("\n")

    if protocol == "lldp":
        for line in lines:
            parts = line.split()
            if len(parts) >= 5 and "/" in parts[0]:
                local_intf = parts[0]
                remote_port = parts[-2]
                remote_name = parts[-1]
                if remote_name and remote_name != "-":
                    results.append((local_intf, remote_name, remote_port))
            elif len(parts) >= 4:
                m = re.match(r"^(\S+)\s+(\S+)\s+(\S+)\s+\d+", line)
                if m and ("/" in m.group(1) or m.group(1).startswith(("Gi", "Et"))):
                    results.append((m.group(1), m.group(2), m.group(3)))
    elif protocol == "cdp":
        device_id = None
        for line in lines:
            m_dev = re.search(r"Device ID:\s*(\S+)", line)
            if m_dev:
                device_id = m_dev.group(1)
                continue
            m_intf = re.search(r"Interface:\s*(\S+),\s*Port ID.*?:\s*(\S+)", line)
            if m_intf and device_id:
                results.append((m_intf.group(1).rstrip(","), device_id, m_intf.group(2)))
                device_id = None

    return results
