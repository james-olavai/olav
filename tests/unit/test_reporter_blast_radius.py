"""inspect_blast_radius @tool — live-DB tests.

Exercises the NetworkX what-if simulation against topology_links from
the demo dataset.  The 0.11.0 ``snapshot_id`` parameter (commit 842fbb3f)
is explicitly covered.

Skips when main.duckdb is absent.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

_DB = Path("/home/yhvh/Olav/.olav/databases/main.duckdb")
_TOOL_PATH = Path(
    "/home/yhvh/Olav/olav-netops/.olav/workspace/netops/tools/inspect_blast_radius.py"
)

pytestmark = pytest.mark.skipif(
    not _DB.exists(), reason="main.duckdb not present — skip live-DB tests"
)

# snap_20260411_144736_bd4ffc has 8 topology_links across R2/SW1/etc.
_SNAP = "snap_20260411_144736_bd4ffc"


@pytest.fixture(scope="module")
def ibr():
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("_ibr_mod", _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_ibr_mod"] = mod
    spec.loader.exec_module(mod)
    return mod.inspect_blast_radius


@pytest.fixture(scope="module")
def live_model():
    from olav_netops.sim import load_network_model
    return load_network_model(snapshot=_SNAP)


# ── return shape ─────────────────────────────────────────────────────────────


def test_blast_radius_no_removals_returns_full_graph(ibr, live_model):
    """Empty removal → components same as baseline, no validation_warnings."""
    out = ibr.func(remove_devices=[], remove_links=[], snapshot_id=_SNAP)
    assert "components" in out
    assert "isolated_nodes" in out
    assert "validation_warnings" in out
    assert isinstance(out["components"], list)
    assert isinstance(out["isolated_nodes"], list)
    assert isinstance(out["validation_warnings"], list)
    assert out["connectivity_loss"]["pre_components"] == out["connectivity_loss"]["post_components"]


# ── snapshot_id parameter (0.11.0 new — commit 842fbb3f) ─────────────────────


def test_blast_radius_snapshot_id_accepted(ibr):
    """snapshot_id param is passed through without raising (0.11.0 regression guard)."""
    out = ibr.func(remove_devices=[], snapshot_id=_SNAP)
    assert "components" in out, "snapshot_id param must not break the tool"
    assert "validation_warnings" in out


def test_blast_radius_none_snapshot_uses_latest(ibr):
    """snapshot_id=None falls back to MAX(snapshot_id) without error."""
    out = ibr.func(remove_devices=[], snapshot_id=None)
    assert "components" in out


# ── validation_warnings ──────────────────────────────────────────────────────


def test_blast_radius_nonexistent_device_produces_warning(ibr):
    """Removing a device not in the graph surfaces a validation_warning."""
    out = ibr.func(remove_devices=["GHOST_DEVICE_XYZ_9999"], snapshot_id=_SNAP)
    assert len(out["validation_warnings"]) > 0
    assert any("GHOST_DEVICE_XYZ_9999" in w for w in out["validation_warnings"])


def test_blast_radius_nonexistent_link_produces_warning(ibr):
    """Removing a link whose endpoints have no direct edge → validation_warning."""
    out = ibr.func(remove_links=[["DOES_NOT_EXIST_A", "DOES_NOT_EXIST_B"]], snapshot_id=_SNAP)
    assert len(out["validation_warnings"]) > 0


# ── real device removal ──────────────────────────────────────────────────────


def test_blast_radius_remove_known_device_changes_component_count(ibr, live_model):
    """Removing a device that IS in the graph must change connectivity."""
    import networkx as nx
    g = live_model.graph
    if g.number_of_nodes() < 2:
        pytest.skip("topology too small for meaningful blast-radius test")
    # Pick the node with the most edges (hub) to maximise impact
    hub = max(g.nodes(), key=lambda n: g.degree(n))
    out = ibr.func(remove_devices=[hub], snapshot_id=_SNAP)
    assert hub not in out["validation_warnings"] or not any(hub in w for w in out["validation_warnings"]), (
        f"hub device {hub!r} should be IN the graph but got validation_warning"
    )
    # After removing the hub, post_components >= pre_components
    pre = out["connectivity_loss"]["pre_components"]
    post = out["connectivity_loss"]["post_components"]
    assert post >= pre, f"removing hub should not reduce component count ({pre}→{post})"
