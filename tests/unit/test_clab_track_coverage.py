import json
import sys
from pathlib import Path

_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab"
)
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from track_coverage import track_coverage

_DEFAULTS = dict(
    topology_file="topologies/bgp_2node.clab.yaml",
    layers_tested=["L3_routing"],
    features_tested=["bgp_neighbor_discovery"],
    commands_expected=["show network-instance default protocols bgp neighbor"],
    node_count=2,
    link_count=1,
)


def test_creates_new_coverage_file(tmp_path):
    cov_file = tmp_path / "coverage.json"
    result = track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="passed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=tmp_path / "results.duckdb",
        **_DEFAULTS,
    )
    assert cov_file.exists()
    assert len(result.entries) == 1
    assert result.entries[0].status == "passed"


def test_updates_existing_entry(tmp_path):
    """Re-running the same scenario overwrites the single JSON entry (last-run-wins)."""
    cov_file = tmp_path / "coverage.json"
    db = tmp_path / "results.duckdb"
    track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="failed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=db,
        **_DEFAULTS,
    )
    result = track_coverage(
        test_run_id="t2",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="passed",
        evidence_path="/ev/t2",
        coverage_file=cov_file,
        results_db=db,
        **_DEFAULTS,
    )
    assert len(result.entries) == 1
    assert result.entries[0].status == "passed"
    assert result.entries[0].test_run_id == "t2"


def test_multiple_platforms(tmp_path):
    """All platforms stored as a list on one entry (not one entry per platform)."""
    cov_file = tmp_path / "coverage.json"
    result = track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios", "juniper_junos"],
        result="passed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=tmp_path / "results.duckdb",
        **_DEFAULTS,
    )
    assert len(result.entries) == 1
    assert set(result.entries[0].platforms) == {"cisco_ios", "juniper_junos"}


def test_invalid_status_defaults_to_not_tested(tmp_path):
    cov_file = tmp_path / "coverage.json"
    result = track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="invalid_status",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=tmp_path / "results.duckdb",
        **_DEFAULTS,
    )
    assert result.entries[0].status == "not_tested"


def test_coverage_json_format(tmp_path):
    cov_file = tmp_path / "coverage.json"
    track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="passed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=tmp_path / "results.duckdb",
        **_DEFAULTS,
    )
    data = json.loads(cov_file.read_text())
    assert "entries" in data
    assert "updated_at" in data
    assert len(data["entries"]) == 1
    entry = data["entries"][0]
    assert entry["topology_file"] == "topologies/bgp_2node.clab.yaml"
    assert entry["layers_tested"] == ["L3_routing"]
    assert entry["node_count"] == 2
    assert entry["collect_method"] == "olav_cli"  # default is now olav_cli


def test_entry_fields(tmp_path):
    cov_file = tmp_path / "coverage.json"
    result = track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="passed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=tmp_path / "results.duckdb",
        **_DEFAULTS,
    )
    entry = result.entries[0]
    assert entry.platforms == ["cisco_ios"]
    assert entry.scenario == "bgp_mesh"
    assert entry.test_run_id == "t1"
    assert entry.evidence_path == "/ev/t1"
    assert entry.last_run is not None
    assert entry.topology_file == "topologies/bgp_2node.clab.yaml"


def test_preserves_other_entries(tmp_path):
    cov_file = tmp_path / "coverage.json"
    db = tmp_path / "results.duckdb"
    track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="passed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=db,
        **_DEFAULTS,
    )
    result = track_coverage(
        test_run_id="t2",
        scenario_name="ospf_basic",
        platforms=["cisco_ios"],
        result="failed",
        evidence_path="/ev/t2",
        coverage_file=cov_file,
        results_db=db,
        **_DEFAULTS,
    )
    assert len(result.entries) == 2


def test_four_valid_statuses(tmp_path):
    for status in ["not_tested", "passed", "failed", "blocked"]:
        cov_file = tmp_path / f"cov_{status}.json"
        result = track_coverage(
            test_run_id="t1",
            scenario_name="test",
            platforms=["p1"],
            result=status,
            evidence_path="/ev",
            coverage_file=cov_file,
            results_db=tmp_path / f"db_{status}.duckdb",
            **_DEFAULTS,
        )
        assert result.entries[0].status == status


def test_updated_at_changes(tmp_path):
    cov_file = tmp_path / "coverage.json"
    db = tmp_path / "results.duckdb"
    r1 = track_coverage(
        test_run_id="t1",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="passed",
        evidence_path="/ev/t1",
        coverage_file=cov_file,
        results_db=db,
        **_DEFAULTS,
    )
    r2 = track_coverage(
        test_run_id="t2",
        scenario_name="bgp_mesh",
        platforms=["cisco_ios"],
        result="failed",
        evidence_path="/ev/t2",
        coverage_file=cov_file,
        results_db=db,
        **_DEFAULTS,
    )
    assert r2.updated_at >= r1.updated_at


def test_duckdb_history_is_append_only(tmp_path):
    """JSON summary has 1 entry (upsert), but DuckDB has 2 rows (full history)."""
    import duckdb

    cov_file = tmp_path / "coverage.json"
    db = tmp_path / "results.duckdb"
    for run_id in ["t1", "t2"]:
        track_coverage(
            test_run_id=run_id,
            scenario_name="bgp_mesh",
            platforms=["cisco_ios"],
            result="passed",
            evidence_path=f"/ev/{run_id}",
            coverage_file=cov_file,
            results_db=db,
            **_DEFAULTS,
        )

    # JSON summary: only latest entry
    data = json.loads(cov_file.read_text())
    assert len(data["entries"]) == 1
    assert data["entries"][0]["test_run_id"] == "t2"

    # DuckDB: both runs present (full history)
    con = duckdb.connect(str(db))
    rows = con.execute("SELECT run_id FROM e2e_runs ORDER BY run_id").fetchall()
    con.close()
    assert [r[0] for r in rows] == ["t1", "t2"]
