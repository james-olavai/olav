from __future__ import annotations

import json
import operator as op_module
import sys
from datetime import UTC, datetime, timezone
from pathlib import Path

import duckdb

_HERE = Path(__file__).parent.resolve()
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from models import AssertionResult, AssertionsResult, ScenarioAssertion

try:
    from olav.core.config import MAIN_DB_PATH
except ImportError:
    # Fallback if olav is not installed (e.g., in minimal test environment)
    MAIN_DB_PATH = Path.cwd() / ".olav" / "databases" / "main.duckdb"

_OPERATORS = {
    "eq": op_module.eq,
    "ne": op_module.ne,
    "gt": op_module.gt,
    "gte": op_module.ge,
    "lt": op_module.lt,
    "lte": op_module.le,
}


def _eval_sql_count(
    assertion: ScenarioAssertion,
    db_path: str,
    index: int,
    test_run_id: str = "",
) -> AssertionResult:
    name = f"sql_count_{index}"
    query = (assertion.query or "").replace("{run_id}", test_run_id)
    try:
        conn = duckdb.connect(db_path, read_only=True)
        rows = conn.execute(query).fetchone()
        conn.close()
        actual = rows[0] if rows else 0
        comparator = _OPERATORS[assertion.operator]
        passed = comparator(actual, assertion.expected)
        return AssertionResult(
            name=name,
            type="sql_count",
            passed=passed,
            expected=assertion.expected,
            actual=actual,
            query_or_path=query,
            operator=assertion.operator,
        )
    except Exception as exc:
        return AssertionResult(
            name=name,
            type="sql_count",
            passed=False,
            expected=assertion.expected,
            actual=0,
            query_or_path=query,
            operator=assertion.operator,
            error=str(exc),
        )


def _eval_file_exists(
    assertion: ScenarioAssertion,
    index: int,
) -> AssertionResult:
    name = f"file_exists_{index}"
    file_path = assertion.path or ""
    actual = 1 if Path(file_path).exists() else 0
    comparator = _OPERATORS[assertion.operator]
    passed = comparator(actual, assertion.expected)
    return AssertionResult(
        name=name,
        type="file_exists",
        passed=passed,
        expected=assertion.expected,
        actual=actual,
        query_or_path=file_path,
        operator=assertion.operator,
    )


def run_assertions(
    test_run_id: str,
    assertions: list[ScenarioAssertion],
    db_path: str | Path | None = None,
    output_dir: Path | None = None,
) -> AssertionsResult:
    """Run assertions against DuckDB database.

    Args:
        test_run_id: Test run identifier
        assertions: List of assertions to evaluate
        db_path: Path to DuckDB (default: MAIN_DB_PATH from OLAV config)
        output_dir: Where to write assertions.json (default: current dir)

    Returns:
        AssertionsResult with all assertion outcomes
    """
    if db_path is None:
        db_path = str(MAIN_DB_PATH)
    else:
        db_path = str(db_path)

    if output_dir is None:
        output_dir = Path(".")
    else:
        output_dir = Path(output_dir)

    results: list[AssertionResult] = []

    for i, assertion in enumerate(assertions):
        if assertion.type == "sql_count":
            results.append(_eval_sql_count(assertion, db_path, i, test_run_id=test_run_id))
        elif assertion.type == "file_exists":
            results.append(_eval_file_exists(assertion, i))

    passed_count = sum(1 for r in results if r.passed)
    failed_count = len(results) - passed_count

    output = AssertionsResult(
        test_run_id=test_run_id,
        assertions=results,
        passed_count=passed_count,
        failed_count=failed_count,
        timestamp=datetime.now(UTC).isoformat(),
        status="passed" if failed_count == 0 else "failed",
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "assertions.json").write_text(output.model_dump_json(indent=2))

    return output
