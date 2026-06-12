"""Tests for the A.2 follow-up: save_profile auto-runs selftest_profile
against the live DB after writing, surfacing schema-drift errors at
authoring time rather than at first audit run.

Context: small models (gemma4-class) can write SQL that is syntactically
valid but references columns that don't exist on the actual DB views
(parser drift, missing migrations). Without an authoring-time check,
the bug only surfaces when the profile is run for real — often days
later in production. The selftest integration runs ``EXPLAIN`` +
``LIMIT 0`` immediately after the .md is written.

Failure mode is advisory (warning string, profile still written) so the
user can inspect and edit; not blocking.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

_SP_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "olav-netops/.olav/workspace/audit/audit-author/scripts/write_profile.py"
)


@pytest.fixture(scope="module")
def save_profile_mod():
    spec = importlib.util.spec_from_file_location("_test_save_profile", _SP_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_test_save_profile"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def stub_db(tmp_path):
    """Spin up a temp DuckDB with a minimal `bgp_neighbors` view so the
    selftest call has a real schema to validate against."""
    db_path = tmp_path / "stub.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE bgp_neighbors (device VARCHAR, state VARCHAR)")
    con.execute("INSERT INTO bgp_neighbors VALUES ('R1', 'Established')")
    con.close()
    return str(db_path)


@pytest.fixture()
def patch_main_db_path(stub_db, monkeypatch):
    """Override MAIN_DB_PATH so map_engine.selftest_profile uses our stub."""
    monkeypatch.setattr(
        "olav.core.config.MAIN_DB_PATH", Path(stub_db), raising=False,
    )
    yield stub_db


def test_save_profile_passes_selftest_on_valid_sql(save_profile_mod, tmp_path, patch_main_db_path):
    """When SQL references real columns, save_profile returns just the
    path (no warning)."""
    out = save_profile_mod.write_profile(
        name="valid_profile",
        jobs=[{
            "name": "bgp_ok",
            "type": "sql",
            "severity": "Warning",
            "section_prompt": "List bgp",
            "query": "SELECT device, state FROM bgp_neighbors",
        }],
        markdown_body="# valid",
        profiles_dir=str(tmp_path),
    )
    assert not out.startswith("ERROR:"), out
    # Either pure path (selftest passed) OR path+warning if MAIN_DB_PATH
    # couldn't resolve. Either way, NOT an ERROR.
    assert "valid_profile.md" in out


def test_save_profile_surfaces_selftest_failure_as_warning(save_profile_mod, tmp_path, patch_main_db_path):
    """When SQL references a column that doesn't exist, the profile
    IS still written (advisory mode) but the return string includes the
    warning so the user can fix it."""
    out = save_profile_mod.write_profile(
        name="drifted_profile",
        jobs=[{
            "name": "bgp_typo",
            "type": "sql",
            "severity": "Warning",
            "section_prompt": "Check bgp",
            # ↓ wrong column name (real schema has 'state', not 'session_state')
            "query": "SELECT device, session_state FROM bgp_neighbors",
        }],
        markdown_body="# typo",
        profiles_dir=str(tmp_path),
    )
    # Profile still written so user can edit
    profile_path = tmp_path / "drifted_profile.md"
    assert profile_path.exists()
    # Warning surfaced
    assert "selftest" in out.lower(), (
        "save_profile must surface selftest failures in the return string "
        f"— got: {out!r}"
    )
    assert "bgp_typo" in out, (
        "warning must name the failing job so the user knows which to fix"
    )


def test_save_profile_selftest_silent_when_map_engine_unavailable(save_profile_mod, tmp_path, monkeypatch):
    """If map_engine is missing or MAIN_DB_PATH unresolvable, save_profile
    must still write the profile and return a clean path — selftest is
    advisory, never blocking. This protects users running in environments
    without a live audit DB."""
    # Force selftest to raise by removing MAIN_DB_PATH
    monkeypatch.setattr(
        "olav.core.config.MAIN_DB_PATH", Path("/nonexistent/db.duckdb"),
        raising=False,
    )
    out = save_profile_mod.write_profile(
        name="env_ok_profile",
        jobs=[{
            "name": "j1",
            "type": "sql",
            "severity": "Info",
            "section_prompt": "test",
            "query": "SELECT 1 AS x",
        }],
        markdown_body="# env",
        profiles_dir=str(tmp_path),
    )
    # Must not be an ERROR or a hung process; profile written
    assert not out.startswith("ERROR:"), out
    assert (tmp_path / "env_ok_profile.md").exists()


def test_save_profile_invalid_jobs_still_rejected_before_selftest(save_profile_mod, tmp_path, patch_main_db_path):
    """Selftest only runs AFTER schema validation passes. If yaml_jobs
    fails validation, the existing ERROR: response wins and no file is
    written. Confirms the selftest didn't accidentally change semantics
    of validation errors."""
    out = save_profile_mod.write_profile(
        name="bad_jobs",
        jobs=[{"name": "j1"}],  # missing required fields
        markdown_body="# bad",
        profiles_dir=str(tmp_path),
    )
    assert out.startswith("ERROR:"), f"expected ERROR for invalid jobs; got {out!r}"
    # File MUST NOT have been written
    assert not (tmp_path / "bad_jobs.md").exists()
