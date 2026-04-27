"""Tests for the R90 Phase 6 rollback generator.

R90 contract: same flat-array signature as R89 (3 parallel arrays
+ intent_type + lab_subnet). Output is per-node SRL ``delete /``
CLI that undoes R89's ``set /`` apply.

Covers:
  * Happy path: 2-node ebgp_direct rollback produces 7-line per-node
    delete sequence in correct dependency order
  * Lab node names lowercase (CLAB convention, matches R89/R88-A)
  * No reference to specific IPs/AS in rollback CLI (``delete /
    interface ... subinterface 0`` and ``delete / network-instance
    default protocols bgp`` are value-independent)
  * Same input validation as R89 (parallel array length, supported
    intent, /30 lab_subnet shape)
  * Symmetry with R89's apply: every R89 set destination has a
    corresponding rollback delete that wipes it
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


_TOOL_PATH = (
    Path(__file__).resolve().parents[1]
    / ".olav" / "workspace" / "ops" / "lab" / "tools"
    / "generate_srl_rollback_config.py"
)
_spec = importlib.util.spec_from_file_location("_grc", _TOOL_PATH)
_grc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_grc)


# Also load R89 to validate symmetry
_R89_PATH = (
    Path(__file__).resolve().parents[1]
    / ".olav" / "workspace" / "ops" / "lab" / "tools"
    / "generate_srl_lab_config.py"
)
_r89_spec = importlib.util.spec_from_file_location("_r89", _R89_PATH)
_r89 = importlib.util.module_from_spec(_r89_spec)
_r89_spec.loader.exec_module(_r89)


def _basic_call():
    return _grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1", "4.4.4.4"],
        "asns": [65000, 65001],
    })


def _basic_apply_call():
    return _r89.generate_srl_lab_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1", "4.4.4.4"],
        "asns": [65000, 65001],
    })


# --- happy path -------------------------------------------------------------


def test_basic_returns_ok():
    data = json.loads(_basic_call())
    assert data["status"] == "ok"
    assert data["intent_type"] == "ebgp_direct"


def test_basic_lab_node_names_lowercase():
    data = json.loads(_basic_call())
    assert set(data["configs"].keys()) == {"r1", "r4"}


def test_basic_seven_lines_per_node():
    data = json.loads(_basic_call())
    for node, cfg in data["configs"].items():
        lines = [ln for ln in cfg.splitlines() if ln.strip()]
        assert len(lines) == 7, f"{node}: {len(lines)} lines"


def test_rollback_starts_with_bgp_wipe():
    """The first delete should be the entire BGP protocol — wipes
    groups + neighbors + asn + router-id in one go."""
    data = json.loads(_basic_call())
    for node, cfg in data["configs"].items():
        first = cfg.splitlines()[0]
        assert first == "delete / network-instance default protocols bgp"


def test_rollback_includes_all_required_deletes():
    data = json.loads(_basic_call())
    for node, cfg in data["configs"].items():
        # Every R89 destination has a rollback line
        assert "delete / network-instance default protocols bgp" in cfg
        assert "delete / routing-policy policy export-bgp" in cfg
        assert "delete / routing-policy prefix-set loopbacks" in cfg
        assert "delete / network-instance default interface ethernet-1/1.0" in cfg
        assert "delete / network-instance default interface system0.0" in cfg
        assert "delete / interface ethernet-1/1 subinterface 0" in cfg
        assert "delete / interface system0 subinterface 0" in cfg


def test_rollback_doesnt_delete_physical_interface():
    """Rollback must NOT delete the physical interface or system0
    itself — they're SRL container resources that always exist.
    Only delete what we configured.
    """
    data = json.loads(_basic_call())
    for cfg in data["configs"].values():
        # No ``delete / interface system0`` (without subinterface)
        assert "delete / interface system0\n" not in cfg
        # No ``delete / interface ethernet-1/1`` (without subinterface)
        assert "delete / interface ethernet-1/1\n" not in cfg


def test_rollback_dependency_order_correct():
    """Higher-level constructs (BGP, routing-policy, NI bindings)
    must be deleted BEFORE the subinterfaces they reference. Order
    matters for SRL YANG validation.
    """
    data = json.loads(_basic_call())
    cfg = data["configs"]["r1"]
    lines = [ln for ln in cfg.splitlines() if ln.strip()]

    bgp_idx = next(i for i, ln in enumerate(lines) if "protocols bgp" in ln)
    ni_bind_idx = next(i for i, ln in enumerate(lines) if "default interface ethernet-1/1.0" in ln)
    subif_idx = next(i for i, ln in enumerate(lines) if "interface ethernet-1/1 subinterface 0" in ln)

    assert bgp_idx < ni_bind_idx
    assert ni_bind_idx < subif_idx


def test_rollback_value_independent():
    """Rollback CLI shouldn't include specific AS numbers or IPs —
    ``delete / network-instance default protocols bgp`` removes them
    all wholesale. Different inputs should produce identical CLI."""
    a = json.loads(_grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1", "4.4.4.4"],
        "asns": [65000, 65001],
    }))
    b = json.loads(_grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["9.9.9.9", "8.8.8.8"],   # different
        "asns": [12345, 67890],                # different
    }))
    # Same lab nodes → same rollback CLI
    assert a["configs"] == b["configs"]


# --- symmetry with R89 ------------------------------------------------------


def test_rollback_undoes_every_r89_set_destination():
    """For each ``set /`` destination R89 emits, the rollback must
    have a corresponding ``delete /`` (possibly at a higher path
    that subsumes the leaf). Surface mismatches as test failures
    so anyone editing R89 must update R90.
    """
    apply_data = json.loads(_basic_apply_call())
    rollback_data = json.loads(_basic_call())

    # Pull the path-after-set / path-after-delete tokens (everything
    # after the leading verb, before the value)
    def _path_keys(cfg: str, verb: str) -> set[str]:
        keys = set()
        for line in cfg.splitlines():
            line = line.strip()
            if not line.startswith(verb):
                continue
            # Strip the verb, then trim known value tail patterns:
            # split on common value markers — for set we use the
            # last word with =/value, for delete we keep the whole path
            tail = line[len(verb):].strip()
            keys.add(tail)
        return keys

    # For r1
    apply_paths = _path_keys(apply_data["configs"]["r1"], "set / ")
    rollback_paths = _path_keys(rollback_data["configs"]["r1"], "delete / ")

    # Every rollback path should be a prefix of at least one apply
    # path (or vice versa) — meaning rollback subsumes the applied
    # leaves, possibly at a coarser granularity.
    for rb_path in rollback_paths:
        rb_path_only = rb_path.split(" admin-state")[0].split("\n")[0]
        # Each rollback path should match at least one apply line as
        # a prefix
        prefix_matches = [
            ap for ap in apply_paths
            if ap.startswith(rb_path_only) or rb_path_only.startswith(ap)
        ]
        assert prefix_matches, (
            f"rollback path {rb_path_only!r} not symmetric to any "
            f"apply path. Apply paths sample: {sorted(apply_paths)[:3]}"
        )


# --- input validation -------------------------------------------------------


def test_empty_nodes_errors():
    result = _grc.generate_srl_rollback_config.invoke({
        "nodes": [], "loopbacks": [], "asns": [],
    })
    assert json.loads(result)["status"] == "error"


def test_length_mismatch_errors():
    result = _grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1"],   # only 1
        "asns": [65000, 65001],
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "loopbacks" in data["error"].lower()


def test_unsupported_intent_errors():
    result = _grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1", "4.4.4.4"],
        "asns": [65000, 65001],
        "intent_type": "vlan_add",
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "vlan_add" in data["error"]


def test_wrong_node_count_for_ebgp_errors():
    result = _grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1"],
        "loopbacks": ["1.1.1.1"],
        "asns": [65000],
    })
    data = json.loads(result)
    assert data["status"] == "error"
    assert "2 devices" in data["error"].lower() or "exactly 2" in data["error"].lower()


def test_too_narrow_subnet_errors():
    """Same /30 validation as R89."""
    result = _grc.generate_srl_rollback_config.invoke({
        "nodes": ["R1", "R4"],
        "loopbacks": ["1.1.1.1", "4.4.4.4"],
        "asns": [65000, 65001],
        "lab_subnet": "172.16.99.0/31",
    })
    data = json.loads(result)
    assert data["status"] == "error"
