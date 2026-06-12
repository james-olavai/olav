"""ARCH-13: ``diff_snapshots`` reports added/removed rows per snapshot table.

Loads the tool directly from its workspace path (it's workspace-vendored,
not a Python package). Builds a tiny DuckDB on tmp_path with two
snapshots' worth of rows and asserts the diff shape.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import duckdb
import pytest


REPO = Path(__file__).resolve().parents[2]
TOOL_PATH = REPO / ".olav" / "workspace" / "netops" / "scripts" / "diff_snapshots.py"


@pytest.fixture
def diff_mod(tmp_path, monkeypatch):
    """Load the tool as a fresh module, pointing MAIN_DB_PATH at a fixture DB."""
    db_path = tmp_path / "main.duckdb"

    # Seed the fixture DB with the 4 snapshot tables the tool looks at.
    with duckdb.connect(str(db_path)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            """
            CREATE TABLE netops.parsed_outputs (
                device_name VARCHAR, command VARCHAR,
                parsed_data JSON, snapshot_id VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE netops.topology_links (
                link_id VARCHAR, source_device VARCHAR,
                destination_device VARCHAR, snapshot_id VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE netops.raw_output_store (
                device_name VARCHAR, command VARCHAR,
                raw_output TEXT, snapshot_id VARCHAR
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE netops.oc_outputs (
                device_name VARCHAR, oc_module VARCHAR, snapshot_id VARCHAR
            )
            """
        )

        # snap_A — baseline
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES "
            "('R1', 'show version', '[]', 'snap_A'),"
            "('R1', 'show clock',   '[]', 'snap_A'),"
            "('R2', 'show version', '[]', 'snap_A')"
        )
        # snap_B — R1 drops 'show clock', adds 'show interfaces';
        # R3 joins with 'show version'
        conn.execute(
            "INSERT INTO netops.parsed_outputs VALUES "
            "('R1', 'show version',   '[]', 'snap_B'),"
            "('R1', 'show interfaces','[]', 'snap_B'),"
            "('R2', 'show version',   '[]', 'snap_B'),"
            "('R3', 'show version',   '[]', 'snap_B')"
        )

        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('L1', 'R1', 'R2', 'snap_A'),"
            "('L2', 'R2', 'R3', 'snap_A')"
        )
        conn.execute(
            "INSERT INTO netops.topology_links VALUES "
            "('L1', 'R1', 'R2', 'snap_B'),"
            "('L3', 'R3', 'R4', 'snap_B')"
        )

    # Load the tool module with MAIN_DB_PATH pointed at the fixture.
    monkeypatch.setenv("OLAV_HOME", str(tmp_path))

    spec = importlib.util.spec_from_file_location("diff_snapshots_tool", TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    # Override the resolver — the tool tries olav.core.config.MAIN_DB_PATH
    # first, then falls back to <project_root>/.olav/databases/main.duckdb.
    # Force the fixture path.
    mod._main_db_path = lambda: db_path
    return mod


def test_tool_file_exists():
    assert TOOL_PATH.exists()


def _call(fn, **kwargs):
    """Invoke a tool or plain function with kwargs."""
    if hasattr(fn, "invoke"):
        return fn.invoke(kwargs)
    return fn(**kwargs)


def test_diff_parsed_outputs_added_and_removed(diff_mod):
    tool = diff_mod.diff_snapshots
    result = _call(tool,
        snapshot_id_1="snap_A",
        snapshot_id_2="snap_B",
        table_name="parsed_outputs",
    )
    assert result["status"] == "success"
    assert result["snapshot_id_1"] == "snap_A"
    assert result["snapshot_id_2"] == "snap_B"

    pd = result["tables"]["parsed_outputs"]
    assert pd["added_count"] == 2  # R1 show interfaces + R3 show version
    assert pd["removed_count"] == 1  # R1 show clock

    added_keys = {(r["device_name"], r["command"]) for r in pd["added"]}
    removed_keys = {(r["device_name"], r["command"]) for r in pd["removed"]}
    assert ("R1", "show interfaces") in added_keys
    assert ("R3", "show version") in added_keys
    assert ("R1", "show clock") in removed_keys


def test_diff_latest_resolves(diff_mod):
    tool = diff_mod.diff_snapshots
    result = _call(tool,
        snapshot_id_1="snap_A",
        snapshot_id_2="latest",
        table_name="parsed_outputs",
    )
    assert result["snapshot_id_2"] == "snap_B"


def test_diff_device_filter(diff_mod):
    tool = diff_mod.diff_snapshots
    result = _call(tool,
        snapshot_id_1="snap_A",
        snapshot_id_2="snap_B",
        table_name="parsed_outputs",
        device="R1",
    )
    pd = result["tables"]["parsed_outputs"]
    # Only R1 rows: added={show interfaces}, removed={show clock}
    assert pd["added_count"] == 1
    assert pd["removed_count"] == 1
    assert pd["added"][0]["device_name"] == "R1"


def test_diff_all_tables_aggregates_totals(diff_mod):
    tool = diff_mod.diff_snapshots
    result = _call(tool, snapshot_id_1="snap_A", snapshot_id_2="snap_B")

    assert set(result["tables"]) >= {"parsed_outputs", "topology_links"}
    topo = result["tables"]["topology_links"]
    assert topo["added_count"] == 1  # L3
    assert topo["removed_count"] == 1  # L2

    # total = sum of all per-table counts
    assert result["total_added"] == sum(
        v["added_count"] for v in result["tables"].values() if v["status"] == "ok"
    )
    assert result["total_removed"] == sum(
        v["removed_count"] for v in result["tables"].values() if v["status"] == "ok"
    )


def test_diff_topology_links_keyed_by_link_id(diff_mod):
    tool = diff_mod.diff_snapshots
    result = _call(tool,
        snapshot_id_1="snap_A",
        snapshot_id_2="snap_B",
        table_name="topology_links",
    )
    topo = result["tables"]["topology_links"]
    assert topo["key_cols"] == ["link_id"]
    assert {r["link_id"] for r in topo["added"]} == {"L3"}
    assert {r["link_id"] for r in topo["removed"]} == {"L2"}


def test_diff_unknown_table_returns_error(diff_mod):
    tool = diff_mod.diff_snapshots
    result = _call(tool,
        snapshot_id_1="snap_A",
        snapshot_id_2="snap_B",
        table_name="does_not_exist",
    )
    assert result["status"] == "error"
    assert "unknown table_name" in result["error"]
