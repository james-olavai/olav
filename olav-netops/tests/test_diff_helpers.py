"""Tests for olav_netops.core.diff helpers (R91 Step 3 fold).

Smoke + behaviour tests on a tiny in-memory DuckDB so the helpers
can be exercised without the real production DB. Each helper takes
two snapshot IDs and returns a dict envelope.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

import olav.core.config as _olav_cfg


# --- diff_sql_state --------------------------------------------------------


@pytest.fixture
def db_with_two_snapshots(tmp_path, monkeypatch):
    db = tmp_path / "main.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""
        CREATE TABLE neighbors (
            device_name VARCHAR, neighbor_id VARCHAR,
            state VARCHAR, snapshot_id VARCHAR
        )
    """)
    con.executemany(
        "INSERT INTO neighbors VALUES (?, ?, ?, ?)",
        [
            ("R1", "10.0.0.2", "Full",  "snap_t1"),
            ("R1", "10.0.0.3", "Full",  "snap_t1"),
            ("R1", "10.0.0.2", "Full",  "snap_t2"),  # unchanged
            ("R1", "10.0.0.4", "Full",  "snap_t2"),  # new
        ],
    )
    con.close()
    monkeypatch.setattr(_olav_cfg, "MAIN_DB_PATH", db)
    # Re-import helpers AFTER patch so they pick up the new path
    import importlib
    import olav_netops.core.diff.sql_state as _ss
    import olav_netops.core.diff.topology_drift as _td
    import olav_netops.core.diff.routing_drift as _rd
    importlib.reload(_ss)
    importlib.reload(_td)
    importlib.reload(_rd)
    return db


def test_diff_sql_state_finds_added_and_removed(db_with_two_snapshots):
    from olav_netops.core.diff.sql_state import diff_sql_state
    out = diff_sql_state("neighbors", "snap_t1", "snap_t2")
    assert out["status"] == "success"
    assert out["total_missing"] == 1   # 10.0.0.3 dropped
    assert out["total_new"] == 1       # 10.0.0.4 added
    assert any(r["neighbor_id"] == "10.0.0.3" for r in out["missing_in_t2"])
    assert any(r["neighbor_id"] == "10.0.0.4" for r in out["new_in_t2"])


def test_diff_sql_state_unknown_table_no_crash(db_with_two_snapshots):
    from olav_netops.core.diff.sql_state import diff_sql_state
    # Empty columns → returns empty diff (no error)
    out = diff_sql_state("not_a_real_table", "snap_t1", "snap_t2")
    assert out["status"] == "success"
    assert out["total_missing"] == 0


# --- diff_topology_drift ---------------------------------------------------


@pytest.fixture
def db_with_topo_snapshots(tmp_path, monkeypatch):
    db = tmp_path / "main.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""
        CREATE TABLE topology_links (
            source_device VARCHAR, source_interface VARCHAR,
            dest_device VARCHAR, dest_interface VARCHAR,
            discovery_protocol VARCHAR, link_type VARCHAR,
            link_status VARCHAR, snapshot_id VARCHAR
        )
    """)
    con.executemany(
        "INSERT INTO topology_links VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("R1", "ge-0/0/1", "R2", "Et0/1", "lldp", "physical", "up",   "t1"),
            ("R1", "ge-0/0/2", "R3", "Et0/1", "lldp", "physical", "up",   "t1"),
            ("R1", "ge-0/0/1", "R2", "Et0/1", "lldp", "physical", "down", "t2"),  # status changed
            # R1↔R3 link missing in t2 (link_down)
            ("R2", "ge-0/0/2", "R4", "Et0/2", "lldp", "physical", "up",   "t2"),  # new link
        ],
    )
    con.close()
    monkeypatch.setattr(_olav_cfg, "MAIN_DB_PATH", db)
    import importlib
    import olav_netops.core.diff.topology_drift as _td
    importlib.reload(_td)
    return db


def test_diff_topology_drift_classifies_changes(db_with_topo_snapshots):
    from olav_netops.core.diff.topology_drift import diff_topology_drift
    out = diff_topology_drift("t1", "t2")
    assert out["status"] == "success"
    assert any(link["dest"] == "R3" for link in out["links_down"])
    assert any(link["dest"] == "R4" for link in out["links_up"])
    assert any(c["new_status"] == "down" for c in out["status_changes"])


# --- diff_configs (file-based, no DB needed) -------------------------------


@pytest.fixture
def snapshot_tree(tmp_path, monkeypatch):
    snap = tmp_path / "snapshots"
    (snap / "t1" / "raw" / "R1").mkdir(parents=True)
    (snap / "t2" / "raw" / "R1").mkdir(parents=True)
    (snap / "t1" / "raw" / "R1" / "show-running-config.txt").write_text(
        "version 15.1\nhostname R1\n!\nrouter ospf 1\n network 1.1.1.0\n!\n",
        encoding="utf-8",
    )
    (snap / "t2" / "raw" / "R1" / "show-running-config.txt").write_text(
        "version 15.1\nhostname R1\n!\nrouter ospf 1\n network 1.1.1.0\n network 2.2.2.0\n!\n",
        encoding="utf-8",
    )

    import olav_netops.core.diff.configs as _cfg_mod
    monkeypatch.setattr(_cfg_mod, "_SNAPSHOTS", snap)
    return snap


def test_diff_configs_detects_added_line(snapshot_tree):
    from olav_netops.core.diff.configs import diff_configs
    out = diff_configs(
        device="R1",
        command="show running-config",
        snapshot_id_1="t1",
        snapshot_id_2="t2",
    )
    assert out["status"] == "success"
    assert out["added_lines"] >= 1
    assert "2.2.2.0" in out["diff"]


def test_diff_configs_missing_file_errors(snapshot_tree):
    from olav_netops.core.diff.configs import diff_configs
    out = diff_configs(
        device="R99",
        command="show running-config",
        snapshot_id_1="t1",
        snapshot_id_2="t2",
    )
    assert out["status"] == "error"


def test_diff_configs_compact_caps_at_40_lines(snapshot_tree, tmp_path):
    """Compact mode trims long diffs; full=True returns everything."""
    from olav_netops.core.diff.configs import diff_configs
    # Build a long diff by writing two long but different files
    d1 = tmp_path / "snapshots" / "t1" / "raw" / "R1" / "show-foo.txt"
    d2 = tmp_path / "snapshots" / "t2" / "raw" / "R1" / "show-foo.txt"
    d1.parent.mkdir(parents=True, exist_ok=True)
    d2.parent.mkdir(parents=True, exist_ok=True)
    d1.write_text("\n".join(f"line-old-{i}" for i in range(100)) + "\n")
    d2.write_text("\n".join(f"line-new-{i}" for i in range(100)) + "\n")

    compact = diff_configs(
        device="R1", command="show foo",
        snapshot_id_1="t1", snapshot_id_2="t2",
    )
    assert compact["status"] == "success"
    # Compact diff has the [compact mode] marker
    assert "compact mode" in compact["diff"]

    full = diff_configs(
        device="R1", command="show foo",
        snapshot_id_1="t1", snapshot_id_2="t2",
        full=True,
    )
    assert "compact mode" not in full["diff"]
