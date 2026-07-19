"""map_engine per-job degradation — ISSUE-MAP-ENGINE-FAIL-FAST-ON-BAD-JOB.

A job whose SQL references a table the dataset doesn't have (shipped
profiles assume TextFSM views) used to kill the WHOLE profile run with a
traceback. It must degrade to a synthetic Critical 'Job Error' finding and
keep executing the remaining jobs.

Exercised through run_map_engine (the real entry point) against a real
temporary DuckDB.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "src/olav/data/workspace/audit/audit-runner/scripts/map_engine.py"

_PROFILE = """---
name: mixed_profile
version: '1.0'
persist_findings_to_db: false
max_findings_per_job: 10
jobs:
- name: bad_job_missing_view
  type: sql
  severity: Critical
  section_prompt: uses a view this dataset does not have
  query: SELECT device_name AS device, state AS metric_value, 'x' AS metric_name,
    'Critical' AS severity_hint FROM netops.v_does_not_exist_auto
- name: good_job
  type: sql
  severity: Warning
  section_prompt: valid job
  query, placeholder
---
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("map_engine_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bad_job_degrades_and_good_job_still_runs(tmp_path):
    import duckdb

    db = tmp_path / "main.duckdb"
    with duckdb.connect(str(db)) as conn:
        conn.execute("CREATE SCHEMA netops")
        conn.execute(
            "CREATE TABLE netops.devices "
            "(hostname VARCHAR, platform VARCHAR, last_seen TIMESTAMP)"
        )
        conn.execute("INSERT INTO netops.devices VALUES ('r1', 'cisco_ios', NOW())")
        conn.execute(
            "CREATE TABLE netops.topology_links (snapshot_id VARCHAR)"
        )

    good_query = (
        "SELECT hostname AS device, 1 AS metric_value, "
        "'Device Present' AS metric_name, 'Info' AS severity_hint "
        "FROM netops.devices"
    )
    profile = tmp_path / "mixed_profile.md"
    profile.write_text(
        _PROFILE.replace("  query, placeholder", f"  query: {good_query}"),
        encoding="utf-8",
    )

    mod = _load_module()
    out_path = mod.run_map_engine(
        profile_path=str(profile),
        time_window="24h",
        db_path=str(db),
        output_dir=str(tmp_path / "out"),
    )
    report = json.loads(Path(out_path).read_text(encoding="utf-8"))

    sections = report["jobs"]  # dict keyed by job name
    assert set(sections) == {"bad_job_missing_view", "good_job"}, (
        f"both jobs must appear: {list(sections)}"
    )

    bad = sections["bad_job_missing_view"]
    bad_findings = bad.get("findings", [])
    assert any(f.get("_warning") == "job_error" for f in bad_findings), (
        "missing-view job must yield a synthetic Job Error finding"
    )
    assert any("v_does_not_exist_auto" in str(f.get("reason", ""))
               or "could not execute" in str(f.get("reason", ""))
               for f in bad_findings)

    good = sections["good_job"]
    assert any(f.get("device") == "r1" for f in good.get("findings", [])), (
        "the good job must still have executed after the bad one degraded"
    )
