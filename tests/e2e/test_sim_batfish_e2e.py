"""Batfish integration e2e — live service smoke tests.

Exercises the full pipeline:
  netops DB → export_configs → bf.init_snapshot → bf.q.* → rows

Gates:
  BATFISH_E2E_ENABLED=1   (not set in push CI — only in nightly)
  main.duckdb must exist with demo snapshot data
  pybatfish must be installed (olav-netops[sim])
  Batfish service reachable at OLAV_BATFISH_HOST:OLAV_BATFISH_HTTP_PORT

The demo snapshot ``snap_20251102_000000_demo`` has running-config for
two devices (alpha-gs2-3850, gamma-border-4500x) which are sufficient
to validate the export → init → question pipeline.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("pybatfish", reason="pybatfish not installed — install olav-netops[sim]")

_BF_ENABLED = os.environ.get("BATFISH_E2E_ENABLED", "").strip() == "1"
_DB = Path(__file__).resolve().parents[2] / ".olav" / "databases" / "main.duckdb"

pytestmark = pytest.mark.skipif(
    not _BF_ENABLED or not _DB.exists(),
    reason="BATFISH_E2E_ENABLED=1 + main.duckdb required",
)

# Demo snapshot with running-config for 2 devices
_SNAP = "snap_20251102_000000_demo"


@pytest.fixture(scope="module", autouse=True)
def _ensure_commands_table():
    """Populate netops.commands if missing — sync_commands derives from static files."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    try:
        with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
            conn.execute("SELECT 1 FROM netops.commands LIMIT 1")
    except Exception:
        from olav_netops.command_registry import reload_hook
        reload_hook()


@pytest.fixture(scope="module")
def _batfish_q():
    from olav.core.sim.batfish_q import batfish_q
    return batfish_q


# ── connectivity ──────────────────────────────────────────────────────────────


def test_batfish_service_reachable():
    """Batfish HTTP port is up before running any question."""
    import socket
    host = os.environ.get("OLAV_BATFISH_HOST", "localhost")
    port = int(os.environ.get("OLAV_BATFISH_HTTP_PORT", "9996"))
    with socket.create_connection((host, port), timeout=10) as s:
        assert s.fileno() != -1, f"could not reach Batfish at {host}:{port}"


# ── export + init pipeline ────────────────────────────────────────────────────


def test_export_configs_produces_files():
    """export_configs writes ≥1 .cfg file for the demo snapshot."""
    import duckdb
    from olav.core.config import MAIN_DB_PATH
    from olav_netops.export.batfish import export_configs

    with duckdb.connect(str(MAIN_DB_PATH), read_only=True) as conn:
        result = export_configs(conn, snapshot_id=_SNAP)

    assert result.get("config_count", 0) >= 1, (
        f"export_configs produced no configs: {result}"
    )
    out_dir = Path(result["output_dir"]) / "configs"
    assert out_dir.is_dir(), f"configs/ dir missing at {out_dir}"
    cfg_files = list(out_dir.glob("*.cfg"))
    assert len(cfg_files) >= 1, f"no .cfg files in {out_dir}"


# ── nodeProperties (lightweight, no routing needed) ──────────────────────────


@pytest.mark.timeout(120)
def test_node_properties_returns_rows(_batfish_q):
    """nodeProperties returns ≥1 row for the demo snapshot."""
    result = _batfish_q.invoke({
        "snapshot_id": _SNAP,
        "question": "nodeProperties",
    })
    assert result["status"] == "ok", f"batfish_q error: {result.get('message')}"
    assert result["row_count"] >= 1, "nodeProperties returned 0 rows"
    assert isinstance(result["rows"], list)


@pytest.mark.timeout(120)
def test_node_properties_envelope_shape(_batfish_q):
    """Return envelope has all documented keys."""
    result = _batfish_q.invoke({
        "snapshot_id": _SNAP,
        "question": "nodeProperties",
    })
    for key in ("status", "rows", "row_count", "snapshot_id", "reference_snapshot", "message"):
        assert key in result, f"missing envelope key: {key!r}"
    assert result["snapshot_id"] == _SNAP


# ── definedStructures (validates config parse) ────────────────────────────────


@pytest.mark.timeout(120)
def test_defined_structures_returns_rows(_batfish_q):
    """definedStructures returns rows — confirms Batfish parsed configs."""
    result = _batfish_q.invoke({
        "snapshot_id": _SNAP,
        "question": "definedStructures",
    })
    assert result["status"] == "ok", f"batfish_q error: {result.get('message')}"
    assert result["row_count"] >= 1, "definedStructures returned 0 rows"


# ── snapshot caching ──────────────────────────────────────────────────────────


@pytest.mark.timeout(60)
def test_repeated_call_uses_cache(_batfish_q):
    """Second call with same snapshot_id must not re-export (cache hit)."""
    import sys
    # sim/__init__.py shadows the submodule name with the StructuredTool via
    # `from .batfish_q import batfish_q`, so `import ... as mod` returns the
    # tool.  Use sys.modules to get the actual module object directly.
    _bfq_mod = sys.modules["olav_netops.core.sim.batfish_q"]

    _batfish_q.invoke({"snapshot_id": _SNAP, "question": "nodeProperties"})
    assert _SNAP in _bfq_mod._LOADED_SNAPSHOTS, "snapshot must be cached after first call"

    # Second call — must be a cache hit (no re-export)
    _batfish_q.invoke({"snapshot_id": _SNAP, "question": "nodeProperties"})
    assert _SNAP in _bfq_mod._LOADED_SNAPSHOTS


# ── error handling ────────────────────────────────────────────────────────────


def test_unknown_question_returns_error_envelope(_batfish_q):
    """An unknown question name must return status=error, not raise."""
    result = _batfish_q.invoke({
        "snapshot_id": _SNAP,
        "question": "nonExistentQuestion_xyz_99",
    })
    assert result["status"] == "error"
    assert result.get("message"), "error envelope must include message"
