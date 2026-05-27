"""topology/discover_recipe + save_recipe — unit + live-DB tests.

discover_recipe: tests the DB query helpers (_candidate_commands,
_sample_parsed_entry) without triggering an LLM call.

save_recipe: tests structural validation (no DB write needed for
rejection cases) and a live write round-trip when main.duckdb exists.

Skips live-DB tests when main.duckdb is absent.
"""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch, MagicMock

import duckdb
import pytest

_DB = Path("/home/yhvh/Olav/.olav/databases/main.duckdb")
_DISCOVER_SCRIPT = Path(
    "/home/yhvh/Olav/olav-netops/.olav/workspace/netops/topology/scripts/discover_recipe.py"
)
_SAVE_SCRIPT = Path(
    "/home/yhvh/Olav/olav-netops/.olav/workspace/netops/topology/scripts/save_recipe.py"
)


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def dr():
    return _load(_DISCOVER_SCRIPT, "_dr_mod")


@pytest.fixture(scope="module")
def sr():
    return _load(_SAVE_SCRIPT, "_sr_mod")


# ── discover_recipe: DB query helpers (live DB) ──────────────────────────────


@pytest.mark.skipif(not _DB.exists(), reason="main.duckdb not present")
def test_candidate_commands_finds_bgp_commands(dr):
    """_candidate_commands returns show bgp commands for cisco_ios platform."""
    con = duckdb.connect(str(_DB), read_only=True)
    try:
        cmds = dr._candidate_commands(con, "bgp", "cisco_ios")
    finally:
        con.close()
    assert isinstance(cmds, list)
    assert len(cmds) > 0, "expected BGP-related commands for cisco_ios in demo dataset"
    assert any("bgp" in c.lower() for c in cmds)


@pytest.mark.skipif(not _DB.exists(), reason="main.duckdb not present")
def test_candidate_commands_unknown_vendor_returns_empty(dr):
    """Unknown vendor → no matching commands, not an error."""
    con = duckdb.connect(str(_DB), read_only=True)
    try:
        cmds = dr._candidate_commands(con, "bgp", "nonexistent_vendor_xyz")
    finally:
        con.close()
    assert cmds == []


@pytest.mark.skipif(not _DB.exists(), reason="main.duckdb not present")
def test_sample_parsed_entry_returns_dict_or_none(dr):
    """_sample_parsed_entry returns a dict or None — never raises."""
    con = duckdb.connect(str(_DB), read_only=True)
    try:
        result = dr._sample_parsed_entry(con, "show bgp all summary", "cisco_ios")
    finally:
        con.close()
    assert result is None or isinstance(result, dict)


# ── save_recipe: structural validation (no DB needed) ───────────────────────


_VALID_RECIPE = textwrap.dedent("""\
    command: show ip bgp summary
    concept: bgp_summary
    vendor_hint: cisco_ios
    field_mappings:
      neighbor_ip: bgp_neighbor
      neighbor_as: neighbor_as
      state: state_or_prefixes_received
""")


def test_save_recipe_missing_command_field(sr, tmp_path):
    """Missing 'command' field → ok=False."""
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe("concept: bgp_summary\nfield_mappings: {}")
    assert out["ok"] is False
    assert "command" in out["error"]


def test_save_recipe_missing_concept_field(sr, tmp_path):
    """Missing 'concept' field → ok=False."""
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe("command: show bgp\nfield_mappings: {}")
    assert out["ok"] is False
    assert "concept" in out["error"]


def test_save_recipe_missing_field_mappings(sr, tmp_path):
    """Missing 'field_mappings' → ok=False."""
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe("command: show bgp\nconcept: bgp_summary")
    assert out["ok"] is False
    assert "field_mappings" in out["error"]


def test_save_recipe_bad_vendor(sr, tmp_path):
    """Unknown vendor_hint → ok=False."""
    bad = _VALID_RECIPE.replace("cisco_ios", "unknown_vendor_xyz")
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe(bad)
    assert out["ok"] is False
    assert "vendor_hint" in out["error"]


def test_save_recipe_empty_field_mappings_non_directive(sr, tmp_path):
    """Empty field_mappings with non-@ command → ok=False."""
    empty_mappings = textwrap.dedent("""\
        command: show bgp summary
        concept: bgp_summary
        vendor_hint: cisco_ios
        field_mappings: {}
    """)
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe(empty_mappings)
    assert out["ok"] is False
    assert "field_mappings" in out["error"]


def test_save_recipe_invalid_yaml(sr, tmp_path):
    """Malformed YAML → ok=False."""
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe(": bad: yaml: [unclosed")
    assert out["ok"] is False
    assert "YAML" in out["error"] or "parse" in out["error"].lower()


# ── save_recipe: live round-trip ─────────────────────────────────────────────


@pytest.mark.skipif(not _DB.exists(), reason="main.duckdb not present")
def test_save_recipe_valid_writes_file(sr, tmp_path):
    """Valid recipe with matching data in the DB writes file + UPSERTs to view_recipes."""
    import yaml

    # force=False to also validate dry-run returns rows (bgp data exists in demo set)
    with patch.object(sr, "_user_recipes_dir", return_value=tmp_path):
        out = sr.save_recipe(_VALID_RECIPE)

    assert out["ok"] is True, f"save_recipe failed: {out.get('error')}"
    assert out["entries_written"] == 1
    # YAML file written to tmp_path
    recipe_files = list(tmp_path.glob("*.yaml"))
    assert len(recipe_files) == 1
    parsed = yaml.safe_load(recipe_files[0].read_text())
    if isinstance(parsed, list):
        parsed = parsed[0]
    assert parsed["command"] == "show ip bgp summary"
    assert parsed["concept"] == "bgp_summary"
    # Dry-run row count recorded
    assert "bgp_summary/cisco_ios" in out["diagnostics"]["dry_run_counts"]
    assert out["diagnostics"]["dry_run_counts"]["bgp_summary/cisco_ios"] > 0
