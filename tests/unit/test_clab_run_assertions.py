import json
import sys
from pathlib import Path

import duckdb

_SKILL_DIR = (
    Path(__file__).resolve().parents[2] / ".olav" / "workspace" / "ops" / "lab"
)
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR / "scripts"))

from models import ScenarioAssertion
from run_assertions import run_assertions


def _make_db(tmp_path, table="parsed_outputs", rows=3):
    db_path = str(tmp_path / "test.duckdb")
    conn = duckdb.connect(db_path)
    conn.execute(f"CREATE TABLE {table} (id INTEGER)")
    for i in range(rows):
        conn.execute(f"INSERT INTO {table} VALUES ({i + 1})")
    conn.close()
    return db_path


def test_sql_count_eq_passes(tmp_path):
    db_path = _make_db(tmp_path, rows=3)
    assertions = [
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="eq",
            expected=3,
        ),
    ]
    result = run_assertions("t1", assertions, db_path=db_path, output_dir=tmp_path / "ev")
    assert result.status == "passed"
    assert result.passed_count == 1


def test_sql_count_eq_fails(tmp_path):
    db_path = _make_db(tmp_path, rows=3)
    assertions = [
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="eq",
            expected=5,
        ),
    ]
    result = run_assertions("t1", assertions, db_path=db_path, output_dir=tmp_path / "ev")
    assert result.status == "failed"
    assert result.failed_count == 1


def test_file_exists_passes(tmp_path):
    target = tmp_path / "somefile.txt"
    target.write_text("data")
    assertions = [
        ScenarioAssertion(
            type="file_exists",
            path=str(target),
            operator="eq",
            expected=1,
        ),
    ]
    result = run_assertions("t1", assertions, db_path=None, output_dir=tmp_path / "ev")
    assert result.status == "passed"


def test_file_exists_fails(tmp_path):
    assertions = [
        ScenarioAssertion(
            type="file_exists",
            path=str(tmp_path / "missing.txt"),
            operator="eq",
            expected=1,
        ),
    ]
    result = run_assertions("t1", assertions, db_path=None, output_dir=tmp_path / "ev")
    assert result.status == "failed"


def test_all_operators(tmp_path):
    db_path = _make_db(tmp_path, rows=3)
    cases = [
        ("eq", 3, True),
        ("ne", 5, True),
        ("gt", 2, True),
        ("gte", 3, True),
        ("lt", 4, True),
        ("lte", 3, True),
    ]
    for op, expected, should_pass in cases:
        assertions = [
            ScenarioAssertion(
                type="sql_count",
                query="SELECT COUNT(*) FROM parsed_outputs",
                operator=op,
                expected=expected,
            ),
        ]
        ev_dir = tmp_path / f"ev_{op}"
        result = run_assertions("t1", assertions, db_path=db_path, output_dir=ev_dir)
        assert result.assertions[0].passed is should_pass, f"Operator {op} failed"


def test_mixed_pass_fail(tmp_path):
    db_path = _make_db(tmp_path, rows=3)
    assertions = [
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="eq",
            expected=3,
        ),
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="eq",
            expected=99,
        ),
    ]
    result = run_assertions("t1", assertions, db_path=db_path, output_dir=tmp_path / "ev")
    assert result.status == "failed"
    assert result.passed_count == 1
    assert result.failed_count == 1


def test_all_pass(tmp_path):
    db_path = _make_db(tmp_path, rows=3)
    assertions = [
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="eq",
            expected=3,
        ),
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="gt",
            expected=0,
        ),
    ]
    result = run_assertions("t1", assertions, db_path=db_path, output_dir=tmp_path / "ev")
    assert result.status == "passed"
    assert result.passed_count == 2


def test_assertions_json_written(tmp_path):
    db_path = _make_db(tmp_path, rows=1)
    assertions = [
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM parsed_outputs",
            operator="eq",
            expected=1,
        ),
    ]
    ev_dir = tmp_path / "ev"
    run_assertions("t1", assertions, db_path, ev_dir)
    assert (ev_dir / "assertions.json").exists()


def test_sql_error_fails_gracefully(tmp_path):
    db_path = _make_db(tmp_path, rows=1)
    assertions = [
        ScenarioAssertion(
            type="sql_count",
            query="SELECT COUNT(*) FROM nonexistent_table",
            operator="eq",
            expected=0,
        ),
    ]
    result = run_assertions("t1", assertions, db_path, tmp_path / "ev")
    assert result.status == "failed"
    assert result.assertions[0].error is not None


def test_query_or_path_field(tmp_path):
    db_path = _make_db(tmp_path, rows=1)
    query = "SELECT COUNT(*) FROM parsed_outputs"
    assertions = [
        ScenarioAssertion(type="sql_count", query=query, operator="eq", expected=1),
    ]
    result = run_assertions("t1", assertions, db_path, tmp_path / "ev")
    assert result.assertions[0].query_or_path == query
