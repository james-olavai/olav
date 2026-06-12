"""Tests for olav.core.auditor authoring helpers.

CUT 1 of the audit/auditor refactor (per ADR-0007). These were
previously MCP tools; they're now plain Python functions called
from ``run_python_simulation``.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import pytest

from olav.core.auditor import (
    analyze_thresholds,
    database_introspection,
    list_profiles,
    read_profile,
    preview_map_query,
)


# --- list_profiles / read_profile -------------------------------------------


def test_list_profiles_empty_dir(tmp_path):
    out = list_profiles(str(tmp_path / "missing"))
    assert out["count"] == 0
    assert out["profiles"] == []


def test_list_profiles_finds_md_files(tmp_path):
    (tmp_path / "alpha.md").write_text("# alpha\n")
    (tmp_path / "beta.md").write_text("# beta\n")
    (tmp_path / "ignored.txt").write_text("not a profile\n")
    out = list_profiles(str(tmp_path))
    assert out["count"] == 2
    assert sorted(out["profiles"]) == ["alpha", "beta"]


def test_read_profile_parses_yaml_frontmatter(tmp_path):
    body = (
        "---\n"
        "name: test_profile\n"
        "version: '1.0'\n"
        "jobs:\n"
        "  - name: bgp_check\n"
        "    type: sql\n"
        "    query: SELECT 1\n"
        "---\n"
        "## Body\n"
        "Sample profile.\n"
    )
    (tmp_path / "test_profile.md").write_text(body)
    out = read_profile("test_profile", str(tmp_path))
    assert out["name"] == "test_profile"
    assert out["job_count"] == 1
    assert out["jobs"][0]["name"] == "bgp_check"
    assert out["job_names"] == ["bgp_check"]


def test_read_profile_missing_returns_error(tmp_path):
    out = read_profile("nope", str(tmp_path))
    assert "error" in out
    assert "available_profiles" in out


# --- database_introspection -------------------------------------------------


def test_database_introspection_duckdb(tmp_path):
    db_path = tmp_path / "test.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE devices (name VARCHAR, ip VARCHAR)")
    con.execute("INSERT INTO devices VALUES ('R1', '1.1.1.1')")
    con.close()

    out = database_introspection(db_type="duckdb", db_path=str(db_path))
    assert out["db_type"] == "duckdb"
    assert "devices" in out["tables"]
    assert out["tables"]["devices"]["columns"] == ["name", "ip"]
    assert out["tables"]["devices"]["sample_rows"][0]["name"] == "R1"


def test_database_introspection_unsupported_type():
    with pytest.raises(ValueError):
        database_introspection(db_type="postgres")


# --- preview_map_query ---------------------------------------------------------


def test_preview_map_query_returns_rows(tmp_path):
    db_path = tmp_path / "q.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE m (v INTEGER)")
    con.executemany("INSERT INTO m VALUES (?)", [(1,), (2,), (3,)])
    con.close()

    rows = preview_map_query(
        job_type="sql",
        query="SELECT v FROM m ORDER BY v",
        db_path=str(db_path),
    )
    assert len(rows) == 3
    assert rows[0] == {"v": 1}


def test_preview_map_query_window_substitution(tmp_path):
    db_path = tmp_path / "win.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE evt (ts TIMESTAMP)")
    con.execute("INSERT INTO evt VALUES (NOW() - INTERVAL '5 min')")
    con.close()

    # The :window placeholder gets converted to an absolute cutoff
    rows = preview_map_query(
        job_type="sql",
        query="SELECT ts FROM evt WHERE ts > NOW() - INTERVAL :window",
        params={"window": "1h"},
        db_path=str(db_path),
    )
    assert len(rows) == 1


def test_preview_map_query_invalid_type():
    with pytest.raises(ValueError):
        preview_map_query(job_type="postgres", query="SELECT 1")


# --- analyze_thresholds -----------------------------------------------------


def test_analyze_thresholds_percentiles(tmp_path):
    db_path = tmp_path / "metrics.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE m (v DOUBLE)")
    con.executemany("INSERT INTO m VALUES (?)", [(float(i),) for i in range(1, 101)])
    con.close()

    out = analyze_thresholds(
        metric_query="SELECT v AS value FROM m",
        metric_name="test metric",
        higher_is_worse=True,
        unit="",
        db_path=str(db_path),
    )
    assert out["sample_count"] == 100
    dist = out["distribution"]
    # 100 evenly distributed values 1..100 — percentiles should sit near these
    assert dist["min"] == 1.0
    assert dist["max"] == 100.0
    assert 49 <= dist["p50"] <= 51
    assert 89 <= dist["p90"] <= 91
    assert out["recommendations"]["operator"] == ">="


def test_analyze_thresholds_no_data(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    con = duckdb.connect(str(db_path))
    con.execute("CREATE TABLE m (v DOUBLE)")
    con.close()

    out = analyze_thresholds(
        metric_query="SELECT v AS value FROM m",
        metric_name="empty",
        db_path=str(db_path),
    )
    assert out["sample_count"] == 0
    assert out["distribution"] is None
