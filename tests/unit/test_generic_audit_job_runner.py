"""Phase F-Audit prototype tests (rev 273, 2026-05-12).

Audit-side counterpart to ``test_generic_intent_handler.py``. Same
contract style:
  * schema discovery + load
  * SQL / lancedb (stubbed) / http_probe execution
  * args default + required validation
  * finding_shape enforcement
  * zero-edit add of a new job type via http_probe.job.yaml only

Success criteria mirror rev 271 CAB prototype:
  - existing job types (sql) execute correctly via the YAML schema
    path, returning rows identical to map_engine._execute_sql_job
  - http_probe runs through the same dispatcher with ZERO map_engine
    code edit — only adding the schema YAML + the executor function
  - shape-mismatch failures are surfaced early with named columns
"""
from __future__ import annotations

import pytest

from olav.core.auditor.generic_job_runner import (
    list_job_types,
    load_job_schema,
    run_audit_job,
)


# ── Stub DuckDB connection ──────────────────────────────────────────


class _StubResult:
    def __init__(self, columns: list[str], rows: list[tuple]):
        self.description = [(c,) for c in columns]
        self._rows = rows

    def fetchall(self):
        return self._rows


class _StubDB:
    """Map (normalised SQL prefix) → (columns, rows)."""

    def __init__(self, fixtures: dict[str, tuple[list[str], list[tuple]]]):
        self._fix = fixtures
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql: str, params: dict | None = None):
        self.calls.append((sql, params or {}))
        # Match by SQL prefix (first 80 chars normalised) for simplicity.
        norm = " ".join(sql.split())
        for k, v in self._fix.items():
            if k in norm:
                return _StubResult(*v)
        return _StubResult([], [])


# ── 1. Schema discovery ────────────────────────────────────────────


def test_list_job_types_includes_three_seeded_schemas():
    types = list_job_types()
    assert "sql" in types
    assert "lancedb" in types
    assert "http_probe" in types


def test_load_sql_job_schema():
    s = load_job_schema("sql")
    assert s["job_type"] == "sql"
    assert s["executor"] == "olav.core.auditor.executors:execute_sql_job"
    assert s["args"]["query"]["required"] is True
    assert s["args"]["max_findings"]["default"] == 50


def test_load_unknown_job_schema_raises():
    with pytest.raises(FileNotFoundError, match="audit job schema not found"):
        load_job_schema("totally_unknown_job_type_xyz")


# ── 2. SQL executor via generic dispatcher ─────────────────────────


def test_sql_job_runs_through_generic_dispatcher():
    db = _StubDB({
        "FROM (SELECT device":
            (
                ["device", "metric_value", "metric_name", "severity_hint"],
                [
                    ("R1", 3, "BGP Neighbor Count", "Info"),
                    ("R2", 0, "BGP Neighbor Count", "Critical"),
                ],
            ),
    })
    job = {
        "name": "BGP_COUNT",
        "type": "sql",
        "query": "SELECT device, COUNT(*) AS metric_value, 'BGP Neighbor Count' AS metric_name, 'Info' AS severity_hint FROM netops.v_bgp_neighbors_auto GROUP BY device",
        "max_findings": 50,
    }
    out = run_audit_job(job, db_conn=db)
    assert out["job_type"] == "sql"
    assert out["count"] == 2
    assert out["findings"][0]["device"] == "R1"
    assert out["findings"][1]["severity_hint"] == "Critical"
    assert out["executor"] == "olav.core.auditor.executors:execute_sql_job"


def test_sql_job_missing_required_query_raises():
    with pytest.raises(ValueError, match="missing required arg 'query'"):
        run_audit_job({"name": "X", "type": "sql"}, db_conn=_StubDB({}))


def test_sql_job_max_findings_default_applies():
    """When the Profile omits max_findings, schema default = 50 kicks in
    (verifiable by checking the LIMIT clause the executor wraps)."""
    captured: dict = {}

    class _Captor:
        def execute(self, sql, params=None):
            captured["sql"] = sql
            return _StubResult(
                ["device", "metric_value", "metric_name", "severity_hint"],
                [],
            )

    run_audit_job(
        {"type": "sql", "query": "SELECT 1 AS x"},
        db_conn=_Captor(),
    )
    assert "LIMIT 50" in captured["sql"]


# ── 3. http_probe — zero-edit new job type ─────────────────────────


def test_http_probe_schema_loaded():
    s = load_job_schema("http_probe")
    assert s["job_type"] == "http_probe"
    assert s["executor"] == "olav.core.auditor.executors:execute_http_probe"
    assert s["args"]["urls"]["required"] is True


def test_http_probe_unhealthy_path_no_network(monkeypatch):
    """No live network needed: monkey-patch urlopen to raise.

    Verifies the executor surfaces the failure as Critical severity
    with metric_value=0 and an error description in metric_name.
    """
    from urllib.error import URLError

    def _raise(*a, **kw):
        raise URLError("Network is unreachable")

    monkeypatch.setattr(
        "olav.core.auditor.executors.urlopen", _raise,
    )

    out = run_audit_job(
        {
            "type": "http_probe",
            "urls": ["http://fake.local/health", "http://other.local/ping"],
            "timeout_s": 1,
        },
        db_conn=None,  # http_probe needs no DB
    )
    assert out["job_type"] == "http_probe"
    assert out["count"] == 2
    for f in out["findings"]:
        assert f["severity_hint"] == "Critical"
        assert f["metric_value"] == 0
        assert "URLError" in f["metric_name"]
        # The schema's finding_shape required all 4 columns
        assert set(f.keys()) >= {"device", "metric_value", "metric_name", "severity_hint"}


def test_http_probe_healthy_path(monkeypatch):
    """Stub urlopen to return 200 — verify Info severity + latency
    metric population."""

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(
        "olav.core.auditor.executors.urlopen", lambda *a, **kw: _FakeResp(),
    )

    out = run_audit_job(
        {
            "type": "http_probe",
            "urls": ["http://fast.local/ok"],
            "expected_status": 200,
        },
        db_conn=None,
    )
    assert out["count"] == 1
    f = out["findings"][0]
    assert f["device"] == "http://fast.local/ok"
    assert f["severity_hint"] == "Info"
    assert "HTTP 200 OK" in f["metric_name"]
    # metric_value is latency in ms — should be ≥ 0
    assert f["metric_value"] >= 0


# ── 4. Finding-shape enforcement ────────────────────────────────────


def test_executor_returning_wrong_shape_raises():
    """An executor that drops required columns must fail fast."""

    # Register a temporary bad executor by monkey-patching the resolved path.
    from olav.core.auditor import executors as _ex

    def _bad_executor(args, db_conn):
        return [{"device": "R1"}]  # missing metric_value / metric_name / severity_hint

    _ex.execute_sql_job = _bad_executor  # type: ignore[assignment]

    try:
        with pytest.raises(ValueError, match="missing required columns"):
            run_audit_job(
                {"type": "sql", "query": "SELECT 1"},
                db_conn=_StubDB({}),
            )
    finally:
        # Restore real implementation so other tests in this module +
        # following modules aren't poisoned.
        import importlib
        importlib.reload(_ex)


# ── 5. Executor resolution edge cases ──────────────────────────────


def test_unresolvable_executor_path(monkeypatch, tmp_path):
    """When a schema points at a non-existent module/function,
    run_audit_job surfaces the import error clearly."""
    # Write a synthetic schema with a bad executor path into a temp
    # location and patch _schemas_dir to read from it.
    from olav.core.auditor import generic_job_runner as gjr

    schemas = tmp_path / "audit_job_schemas"
    schemas.mkdir()
    (schemas / "bogus.job.yaml").write_text(
        "job_type: bogus\n"
        "args: {x: {type: string, required: true}}\n"
        "executor: 'olav.no_such_module:no_such_function'\n"
    )

    monkeypatch.setattr(gjr, "_schemas_dir", lambda: schemas)

    with pytest.raises(ImportError, match="not importable"):
        run_audit_job({"type": "bogus", "x": "hi"}, db_conn=None)
