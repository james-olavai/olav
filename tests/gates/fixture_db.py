"""A synthetic netops database the gate suites can actually run against.

The gate suites used to guard on a real lab: `_HAS_LAB_DATA` queried
`main.duckdb` and skipped everything when it was empty, which in CI is always.
74 of 74 tests skipped on every run, so the suites proved nothing beyond
importing — and that is how three of them rotted for months without anyone
noticing (dev_docs/115 §13).

They also could not have passed with real data. They asserted against
`v_topo_links_clean`, `v_device_neighbors_summary`, `v_interfaces` and
`v_bgp_neighbors`, none of which exist on a production install — the 11 views
a real machine has are all `v_*_auto`, and no commit in the repo's history ever
created the others. The gates were written against one developer's hand-made
recipe views.

So this module builds the data instead of hoping for it. Two rules keep it
honest:

* **The tables are synthetic; the views are the product's.** Rows are written
  by hand, then `olav_netops.core.view_builder.finalise_ingest` — the same
  function `/netops_init` and `take_snapshot` call — builds every view. A gate
  asserting on `v_show_version_auto` is therefore asserting on shipped SQL, not
  on a copy of it. Had the fixture defined the views too, the suite would only
  have been testing itself.
* **The shape is taken from a real install**, not invented: column names and
  types were read off the demo machine's `main.duckdb`.

The data is deliberately small and deliberately awkward — two snapshots, a
device with no neighbours, mixed LLDP and CDP — because a fixture that only
contains the happy path lets the happy path be the only thing that works.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

# Two snapshots so "latest wins" logic has something to get wrong.
SNAPSHOT_OLD = "snap_20260101_000000"
SNAPSHOT_NEW = "snap_20260102_000000"

# Four devices. `edge-2` deliberately has no topology links: a gate that
# assumes every device has a neighbour should say so rather than pass by luck.
DEVICES = [
    ("core-1", "10.0.0.1", "cisco_ios", "site-a", "core"),
    ("core-2", "10.0.0.2", "cisco_ios", "site-a", "core"),
    ("edge-1", "10.0.1.1", "cisco_ios", "site-b", "edge"),
    ("edge-2", "10.0.1.2", "cisco_ios", "site-b", "edge"),
]

# Five commands per device — the minimum coverage gate expects at least five.
COMMANDS = [
    ("show version", {"version": "15.5(3)M", "hostname": "{host}"}),
    ("show ip interface brief", {"interface": "GigabitEthernet0/0", "status": "up"}),
    ("show interfaces", {"interface": "GigabitEthernet0/0", "link_status": "up"}),
    ("show cdp neighbors", {"neighbor": "peer", "local_interface": "Gi0/0"}),
    ("show inventory", {"name": "Chassis", "pid": "ISR4331"}),
]

# LLDP and CDP, both directions of one pair, plus a second protocol — enough
# for the taxonomy and canonicalisation gates to have real work to do.
LINKS = [
    ("core-1", "GigabitEthernet0/0", "core-2", "GigabitEthernet0/0", "lldp"),
    ("core-2", "GigabitEthernet0/0", "core-1", "GigabitEthernet0/0", "lldp"),
    ("core-1", "GigabitEthernet0/1", "edge-1", "GigabitEthernet0/0", "cdp"),
    ("edge-1", "GigabitEthernet0/0", "core-1", "GigabitEthernet0/1", "cdp"),
]


def _create_schema(con: Any) -> None:
    """Column names and types as read off a real install."""
    con.execute("CREATE SCHEMA IF NOT EXISTS netops")
    con.execute("""
        CREATE TABLE netops.devices (
            hostname VARCHAR, ip_address VARCHAR, platform VARCHAR,
            site VARCHAR, role VARCHAR, vendor VARCHAR, model VARCHAR,
            os_version VARCHAR, environment VARCHAR,
            last_seen TIMESTAMP, metadata JSON
        )
    """)
    con.execute("""
        CREATE TABLE netops.parsed_outputs (
            device_name VARCHAR, command VARCHAR, parsed_data JSON,
            snapshot_id VARCHAR, raw_output VARCHAR, raw_output_hash VARCHAR,
            ingested_at TIMESTAMP, platform VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE netops.topology_links (
            link_id VARCHAR, source_device VARCHAR, source_interface VARCHAR,
            destination_device VARCHAR, destination_interface VARCHAR,
            discovery_protocol VARCHAR, link_type VARCHAR, link_status VARCHAR,
            link_speed VARCHAR, first_seen TIMESTAMP, last_seen TIMESTAMP,
            last_verified TIMESTAMP, status_changes INTEGER,
            snapshot_id VARCHAR, platform VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE netops.commands (
            platform VARCHAR, command VARCHAR, safe_command VARCHAR,
            parser_type VARCHAR, parser_path VARCHAR, blacklisted BOOLEAN,
            pipe_allowed BOOLEAN, backup_only BOOLEAN, synced_at TIMESTAMP
        )
    """)


def _populate(con: Any) -> None:
    now = datetime(2026, 1, 2, 12, 0, 0)

    con.executemany(
        "INSERT INTO netops.devices VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (h, ip, plat, site, role, "cisco", "ISR4331", "15.5(3)M",
             "lab", now, json.dumps({"role_source": "fixture"}))
            for h, ip, plat, site, role in DEVICES
        ],
    )

    con.executemany(
        "INSERT INTO netops.commands VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("cisco_ios", cmd, cmd.replace(" ", "_"), "ntc",
             f"/parsers/{cmd.replace(' ', '_')}.textfsm", False, True, False, now)
            for cmd, _ in COMMANDS
        ],
    )

    rows = []
    for snapshot in (SNAPSHOT_OLD, SNAPSHOT_NEW):
        for host, *_ in DEVICES:
            for cmd, shape in COMMANDS:
                parsed = {k: (v.format(host=host) if isinstance(v, str) else v)
                          for k, v in shape.items()}
                rows.append((
                    host, cmd, json.dumps([parsed]), snapshot,
                    f"{cmd} output for {host}\n", f"hash-{host}-{cmd}",
                    now, "cisco_ios",
                ))
    con.executemany(
        "INSERT INTO netops.parsed_outputs VALUES (?,?,?,?,?,?,?,?)", rows
    )

    link_rows = []
    for snapshot in (SNAPSHOT_OLD, SNAPSHOT_NEW):
        for src, src_if, dst, dst_if, proto in LINKS:
            link_rows.append((
                f"{src}:{src_if}->{dst}:{dst_if}:{snapshot}",
                src, src_if, dst, dst_if, proto, "l2", "up", "1G",
                now - timedelta(days=1), now, now, 0, snapshot, "cisco_ios",
            ))
    con.executemany(
        "INSERT INTO netops.topology_links VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        link_rows,
    )


def build(db_path: Path) -> Path:
    """Create the fixture database, views included, and return its path.

    Views come from `finalise_ingest`, the product's own builder, so what the
    gates assert on is shipped SQL. It logs and continues on failure rather
    than raising (view building is advisory), so this checks afterwards that it
    actually produced something — a silently viewless fixture would turn every
    view gate green by making it vacuous.
    """
    import duckdb

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        _create_schema(con)
        _populate(con)

        from olav_netops.core.view_builder import finalise_ingest

        finalise_ingest(con)

        views = {
            r[0] for r in con.execute(
                "SELECT view_name FROM duckdb_views() WHERE schema_name='netops'"
            ).fetchall()
        }
        if not views:
            raise AssertionError(
                "finalise_ingest produced no views — it swallows its own "
                "failures, so without this check every view gate would pass "
                "by having nothing to check"
            )
    finally:
        con.close()
    return db_path
