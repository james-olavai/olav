"""execute_sql per-cell char cap — the tool-layer guardrail against raw dumps.

A single `raw_output` cell (a full `show running-config`, ~70 KB) blowing the
context window is the direct cause of the change-plan hallucination/rabbit-hole
(the model gets a wall of config text and loops parsing it). The row cap does
not help — it's ONE row with a huge cell. This deterministic per-cell cap makes
the dump physically ineffective for EVERY agent, not just via prompt steering.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_TOOL = _REPO / "src" / "olav" / "data" / "workspace" / "core" / "tools" / "execute_sql.py"


@pytest.fixture(scope="module")
def es():
    spec = importlib.util.spec_from_file_location("_es_capmod", _TOOL)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_tier_defaults_declare_cell_cap():
    from olav.core.config import TIER_DEFAULTS
    for tier in ("small", "medium", "large"):
        assert "execute_sql_max_cell_chars" in TIER_DEFAULTS[tier], (
            f"{tier} tier missing execute_sql_max_cell_chars"
        )
    # ordering sanity: small <= medium <= large
    s = TIER_DEFAULTS["small"]["execute_sql_max_cell_chars"]
    m = TIER_DEFAULTS["medium"]["execute_sql_max_cell_chars"]
    l = TIER_DEFAULTS["large"]["execute_sql_max_cell_chars"]
    assert s <= m <= l


def test_long_cell_is_truncated_with_regexp_hint(es):
    big = "R" * 70000
    rows, capped = es._cap_cells([{"device_name": "r1", "raw_output": big}], 800)
    assert capped is True
    cell = rows[0]["raw_output"]
    assert len(cell) < 1200                      # ~800 + marker, not 70000
    assert "truncated 70000 chars" in cell
    assert "regexp_extract" in cell              # names the precise-extraction fix


def test_structured_cells_untouched(es):
    rows, capped = es._cap_cells(
        [{"hostname": "r1", "ip_address": "10.0.0.1", "status": "up"}], 800
    )
    assert capped is False
    assert rows[0] == {"hostname": "r1", "ip_address": "10.0.0.1", "status": "up"}


def test_non_string_cells_pass_through(es):
    rows, capped = es._cap_cells([{"n": 12345, "flag": True, "x": None}], 800)
    assert capped is False
    assert rows[0] == {"n": 12345, "flag": True, "x": None}
