#!/usr/bin/env python3
"""Bootstrap initial standard-field vector library for a domain.

Populates the ``{domain}_field_mappings`` LanceDB collection with a seed set
of standard field definitions so that ``classify_field()`` has a reference
library to compare incoming fields against.

Design reference: dev_docs/api_discovery.md §6

Usage
-----
::

    # Seed the default 'netops' domain standard fields
    uv run python scripts/bootstrap_field_classifications.py

    # Seed a custom domain with verbose output
    uv run python scripts/bootstrap_field_classifications.py --domain itsm --verbose

    # Dry-run: show what would be written without touching LanceDB
    uv run python scripts/bootstrap_field_classifications.py --dry-run

Notes
-----
- Idempotent: existing entries with the same ``openconfig_path`` are skipped.
- The embedder (``get_embedder()``) must be available; run
  ``olav init`` first to ensure the model is downloaded.
- This script is intentionally kept dependency-free beyond the main
  ``olav-platform`` package so it can run in any environment.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Standard field definitions (netops domain seed)
# These mirror the fields declared in api_discovery.md §3.3 / §6.
# ---------------------------------------------------------------------------

NETOPS_STANDARD_FIELDS: list[dict[str, str]] = [
    # ── Interface ──────────────────────────────────────────────────────────
    {
        "openconfig_path": "management_ip",
        "description": "IPv4 management address of the device or interface",
        "data_type": "VARCHAR",
        "category": "interface",
    },
    {
        "openconfig_path": "interface_name",
        "description": "Interface name or identifier, e.g. GigabitEthernet0/0",
        "data_type": "VARCHAR",
        "category": "interface",
    },
    {
        "openconfig_path": "interface_status",
        "description": "Operational status of the interface: up, down, admindown",
        "data_type": "VARCHAR",
        "category": "interface",
    },
    {
        "openconfig_path": "interface_speed",
        "description": "Interface speed in Mbps or Gbps",
        "data_type": "VARCHAR",
        "category": "interface",
    },
    {
        "openconfig_path": "interface_mtu",
        "description": "Maximum Transmission Unit in bytes",
        "data_type": "INTEGER",
        "category": "interface",
    },
    {
        "openconfig_path": "interface_mac",
        "description": "MAC address of the interface",
        "data_type": "VARCHAR",
        "category": "interface",
    },
    # ── BGP ────────────────────────────────────────────────────────────────
    {
        "openconfig_path": "bgp_peer_ip",
        "description": "BGP neighbor or peer IP address",
        "data_type": "VARCHAR",
        "category": "bgp",
    },
    {
        "openconfig_path": "bgp_as_number",
        "description": "BGP autonomous system number (local or remote)",
        "data_type": "BIGINT",
        "category": "bgp",
    },
    {
        "openconfig_path": "bgp_peer_state",
        "description": "BGP session state: Established, Active, Idle, Connect, OpenSent",
        "data_type": "VARCHAR",
        "category": "bgp",
    },
    {
        "openconfig_path": "bgp_prefixes_received",
        "description": "Number of prefixes received from BGP peer",
        "data_type": "BIGINT",
        "category": "bgp",
    },
    {
        "openconfig_path": "bgp_prefixes_sent",
        "description": "Number of prefixes advertised to BGP peer",
        "data_type": "BIGINT",
        "category": "bgp",
    },
    # ── OSPF ───────────────────────────────────────────────────────────────
    {
        "openconfig_path": "ospf_router_id",
        "description": "OSPF router ID in dotted-quad notation",
        "data_type": "VARCHAR",
        "category": "ospf",
    },
    {
        "openconfig_path": "ospf_area",
        "description": "OSPF area ID, e.g. 0.0.0.0 or area 0",
        "data_type": "VARCHAR",
        "category": "ospf",
    },
    {
        "openconfig_path": "ospf_neighbor_ip",
        "description": "OSPF neighbor router IP address",
        "data_type": "VARCHAR",
        "category": "ospf",
    },
    {
        "openconfig_path": "ospf_neighbor_state",
        "description": "OSPF adjacency state: Full, 2-Way, Init, Down, Exstart, Exchange, Loading",
        "data_type": "VARCHAR",
        "category": "ospf",
    },
    # ── Routing ────────────────────────────────────────────────────────────
    {
        "openconfig_path": "route_prefix",
        "description": "IP route prefix in CIDR notation",
        "data_type": "VARCHAR",
        "category": "routing",
    },
    {
        "openconfig_path": "route_next_hop",
        "description": "Next-hop IP address for a route",
        "data_type": "VARCHAR",
        "category": "routing",
    },
    {
        "openconfig_path": "route_protocol",
        "description": "Routing protocol that installed the route: bgp, ospf, static, connected",
        "data_type": "VARCHAR",
        "category": "routing",
    },
    {
        "openconfig_path": "route_metric",
        "description": "Route metric or administrative distance",
        "data_type": "INTEGER",
        "category": "routing",
    },
    # ── Device ─────────────────────────────────────────────────────────────
    {
        "openconfig_path": "hostname",
        "description": "Device hostname or FQDN",
        "data_type": "VARCHAR",
        "category": "device",
    },
    {
        "openconfig_path": "platform",
        "description": "Device platform or hardware model",
        "data_type": "VARCHAR",
        "category": "device",
    },
    {
        "openconfig_path": "os_version",
        "description": "Operating system version string",
        "data_type": "VARCHAR",
        "category": "device",
    },
    {
        "openconfig_path": "serial_number",
        "description": "Device or module serial number",
        "data_type": "VARCHAR",
        "category": "device",
    },
    {
        "openconfig_path": "uptime",
        "description": "Device uptime as a human-readable string",
        "data_type": "VARCHAR",
        "category": "device",
    },
    # ── CDP / LLDP ─────────────────────────────────────────────────────────
    {
        "openconfig_path": "neighbor_device_id",
        "description": "Neighbor device identifier discovered via CDP or LLDP",
        "data_type": "VARCHAR",
        "category": "topology",
    },
    {
        "openconfig_path": "neighbor_port_id",
        "description": "Port on the neighbor device (CDP/LLDP port ID)",
        "data_type": "VARCHAR",
        "category": "topology",
    },
    {
        "openconfig_path": "local_port_id",
        "description": "Local interface through which the neighbor was discovered",
        "data_type": "VARCHAR",
        "category": "topology",
    },
]

# Domain → seed fields mapping (extensible for future domains)
DOMAIN_SEEDS: dict[str, list[dict[str, str]]] = {
    "netops": NETOPS_STANDARD_FIELDS,
}


# ---------------------------------------------------------------------------
# Bootstrap logic
# ---------------------------------------------------------------------------


def _build_records(fields: list[dict[str, str]], embedder: Any) -> list[dict[str, Any]]:
    """Vectorize field definitions and return LanceDB-ready records."""
    import numpy as np

    records = []
    for f in fields:
        summary = (
            f"{f['openconfig_path']} | {f['description']} | {f['data_type']} | {f['category']}"
        )
        vector = embedder.encode(summary, normalize_embeddings=True).tolist()
        records.append(
            {
                "openconfig_path": f["openconfig_path"],
                "description": f["description"],
                "data_type": f["data_type"],
                "category": f["category"],
                "vector": vector,
                "source": "bootstrap",
                "created_at": __import__("datetime").datetime.utcnow().isoformat(),
            }
        )
    return records


def bootstrap(
    domain: str = "netops",
    *,
    lancedb_path: str | Path | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> dict[str, int]:
    """Seed ``{domain}_field_mappings`` LanceDB collection.

    Parameters
    ----------
    domain:
        Domain name — determines the collection name
        (``{domain}_field_mappings``) and which seed fields to write.
    lancedb_path:
        Path to the LanceDB database directory.  Defaults to
        ``.olav/databases/memory.lancedb`` (resolved from config).
    dry_run:
        When *True*, skip all writes and only report what would be inserted.
    verbose:
        Print per-field progress.

    Returns
    -------
    dict
        ``{"inserted": N, "skipped": N, "total": N}``
    """
    fields = DOMAIN_SEEDS.get(domain)
    if fields is None:
        raise ValueError(
            f"No seed fields found for domain '{domain}'. Available: {list(DOMAIN_SEEDS.keys())}"
        )

    # Resolve LanceDB path
    if lancedb_path is None:
        try:
            from olav.core.config import DATABASES_DIR

            lancedb_path = DATABASES_DIR / "memory.lancedb"
        except ImportError:
            lancedb_path = Path(".olav/databases/memory.lancedb")

    lancedb_path = Path(lancedb_path)

    collection_name = f"{domain}_field_mappings"

    if verbose:
        print(f"[bootstrap] domain={domain!r}  collection={collection_name!r}")
        print(f"[bootstrap] lancedb_path={lancedb_path}")
        print(f"[bootstrap] dry_run={dry_run}")

    if dry_run:
        print(f"[dry-run] Would seed {len(fields)} fields into '{collection_name}'.")
        for f in fields:
            print(f"  - {f['openconfig_path']} ({f['category']}): {f['description']}")
        return {"inserted": 0, "skipped": 0, "total": len(fields)}

    # Load embedder
    try:
        from olav.core.embedder import get_embedder

        embedder = get_embedder()
    except Exception as exc:
        print(f"[bootstrap] ERROR: Could not load embedder: {exc}", file=sys.stderr)
        print(
            "[bootstrap] Hint: run 'olav init' first to download the embedding model.",
            file=sys.stderr,
        )
        raise

    # Connect to LanceDB
    try:
        import lancedb

        db = lancedb.connect(str(lancedb_path))
    except ImportError:
        print(
            "[bootstrap] ERROR: lancedb not installed. Run: uv add lancedb",
            file=sys.stderr,
        )
        raise

    # Load or create the collection
    existing_names: set[str] = set()
    try:
        table = db.open_table(collection_name)
        existing_df = table.to_pandas()
        if "openconfig_path" in existing_df.columns:
            existing_names = set(existing_df["openconfig_path"].tolist())
        if verbose:
            print(
                f"[bootstrap] Opened existing table '{collection_name}' with {len(existing_names)} entries."
            )
    except Exception:
        table = None  # Will be created on first insert

    # Filter fields not yet in the collection
    new_fields = [f for f in fields if f["openconfig_path"] not in existing_names]
    skipped = len(fields) - len(new_fields)

    if not new_fields:
        print(f"[bootstrap] All {len(fields)} fields already present. Nothing to do.")
        return {"inserted": 0, "skipped": skipped, "total": len(fields)}

    if verbose:
        print(f"[bootstrap] Inserting {len(new_fields)} new fields (skipping {skipped} existing).")

    # Build records
    records = _build_records(new_fields, embedder)

    # Write to LanceDB
    if table is None:
        # First time — create the table with explicit schema inferred from records
        import pyarrow as pa

        vector_dim = len(records[0]["vector"])
        schema = pa.schema(
            [
                pa.field("openconfig_path", pa.string()),
                pa.field("description", pa.string()),
                pa.field("data_type", pa.string()),
                pa.field("category", pa.string()),
                pa.field("vector", pa.list_(pa.float32(), vector_dim)),
                pa.field("source", pa.string()),
                pa.field("created_at", pa.string()),
            ]
        )
        table = db.create_table(collection_name, data=records, schema=schema)
        if verbose:
            print(f"[bootstrap] Created table '{collection_name}' ({vector_dim}d vectors).")
    else:
        table.add(records)
        if verbose:
            print(f"[bootstrap] Appended {len(records)} records.")

    print(
        f"[bootstrap] Done: inserted={len(new_fields)}, skipped={skipped}, total={len(fields)}  "
        f"→ '{collection_name}'"
    )
    return {"inserted": len(new_fields), "skipped": skipped, "total": len(fields)}


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Seed initial standard-field vector library for OLAV domain classification.\n"
            "Populates <domain>_field_mappings LanceDB collection from built-in field definitions."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--domain",
        default="netops",
        help="Domain name to seed (default: netops)",
    )
    parser.add_argument(
        "--lancedb-path",
        default=None,
        help="Path to LanceDB database directory (default: .olav/databases/memory.lancedb)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be inserted without writing anything",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-field progress",
    )
    parser.add_argument(
        "--list-domains",
        action="store_true",
        help="List available domains and exit",
    )

    args = parser.parse_args()

    if args.list_domains:
        print("Available domains:")
        for d, fields in DOMAIN_SEEDS.items():
            print(f"  {d}: {len(fields)} standard fields")
        return

    try:
        bootstrap(
            domain=args.domain,
            lancedb_path=args.lancedb_path,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
