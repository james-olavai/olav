"""reporter/diff_snapshots.py — live-DB integration tests.

Exercises cross-snapshot structural diff against the real demo dataset.
Skips automatically when main.duckdb is absent.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_DB = Path(__file__).resolve().parents[2] / ".olav/databases/main.duckdb"
_SCRIPT = Path(
    Path(__file__).resolve().parents[2] / "olav-netops/.olav/workspace/netops/reporter/scripts/diff_snapshots.py"
)

# Two snapshots that exist in the demo dataset with different row counts
_SNAP_LARGE = "snap_20260411_144736_bd4ffc"   # 43 parsed_outputs, 8 topology_links
_SNAP_SMALL = "snap_20260410_204722_deb003"   # 2 parsed_outputs, 0 topology_links

pytestmark = pytest.mark.skipif(
    not _DB.exists(), reason="main.duckdb not present — skip live-DB tests"
)


@pytest.fixture(scope="module")
def ds():
    spec = importlib.util.spec_from_file_location("_ds_mod", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ds_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


# ── basic contract ───────────────────────────────────────────────────────────


def test_diff_two_snapshots_success_shape(ds):
    """Diff between two known snapshots returns the documented shape."""
    out = ds.diff_snapshots(snapshot_id_1=_SNAP_SMALL, snapshot_id_2=_SNAP_LARGE)
    assert out["status"] == "success"
    assert out["snapshot_id_1"] == _SNAP_SMALL
    assert out["snapshot_id_2"] == _SNAP_LARGE
    assert "tables" in out
    assert "total_added" in out
    assert "total_removed" in out
    assert isinstance(out["total_added"], int)
    assert isinstance(out["total_removed"], int)


def test_diff_has_all_four_tables(ds):
    """Default call (table_name=None) covers all four tables."""
    out = ds.diff_snapshots(snapshot_id_1=_SNAP_SMALL, snapshot_id_2=_SNAP_LARGE)
    assert out["status"] == "success"
    for tbl in ("parsed_outputs", "topology_links", "raw_output_store", "oc_outputs"):
        assert tbl in out["tables"], f"missing table {tbl!r}"


def test_diff_large_vs_small_has_additions(ds):
    """Going from smaller → larger snapshot should have net additions."""
    out = ds.diff_snapshots(snapshot_id_1=_SNAP_SMALL, snapshot_id_2=_SNAP_LARGE)
    assert out["status"] == "success"
    # snap_large has more parsed_outputs than snap_small
    po = out["tables"]["parsed_outputs"]
    assert po["added_count"] > 0, "expected rows added when moving from smaller to larger snap"


# ── 'latest' resolution ──────────────────────────────────────────────────────


def test_diff_latest_keyword_resolves(ds):
    """snapshot_id_2='latest' resolves to the actual latest snapshot id."""
    out = ds.diff_snapshots(snapshot_id_1=_SNAP_SMALL, snapshot_id_2="latest")
    assert out["status"] == "success"
    assert out["snapshot_id_2"] != "latest", "'latest' must be resolved to a real id"
    assert out["snapshot_id_2"] == _SNAP_LARGE, (
        f"expected latest to be {_SNAP_LARGE!r}, got {out['snapshot_id_2']!r}"
    )


# ── single-table filter ──────────────────────────────────────────────────────


def test_diff_single_table_filter(ds):
    """table_name='parsed_outputs' only returns that one table."""
    out = ds.diff_snapshots(
        snapshot_id_1=_SNAP_SMALL,
        snapshot_id_2=_SNAP_LARGE,
        table_name="parsed_outputs",
    )
    assert out["status"] == "success"
    assert list(out["tables"].keys()) == ["parsed_outputs"]


def test_diff_unknown_table_returns_error(ds):
    """Passing an unknown table_name returns error status, not an exception."""
    out = ds.diff_snapshots(
        snapshot_id_1=_SNAP_SMALL,
        snapshot_id_2=_SNAP_LARGE,
        table_name="nonexistent_table",
    )
    assert out["status"] == "error"
    assert "nonexistent_table" in out["error"]


# ── device filter ────────────────────────────────────────────────────────────


def test_diff_device_filter_accepted(ds):
    """Device filter is recorded in the response and does not crash."""
    out = ds.diff_snapshots(
        snapshot_id_1=_SNAP_SMALL,
        snapshot_id_2=_SNAP_LARGE,
        table_name="parsed_outputs",
        device="R2",
    )
    assert out["status"] == "success"
    assert out["device"] == "R2"


# ── missing DB ───────────────────────────────────────────────────────────────


def test_diff_missing_db_returns_error(ds, tmp_path):
    """Non-existent DB path returns error status without raising."""
    import importlib.util as _il, sys as _sys
    # Reload the module with a patched MAIN_DB_PATH
    fake_path = tmp_path / "no_such.duckdb"
    from unittest.mock import patch
    with patch.object(ds, "_main_db_path", return_value=fake_path):
        out = ds.diff_snapshots(snapshot_id_1="snap_A", snapshot_id_2="snap_B")
    assert out["status"] == "error"
    assert "not found" in out["error"]
