"""E2E Test: S - Schema-Aware Tests.

Tests schema-aware query capabilities via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_s_schema.py -v
"""

import pytest
from tests.e2e.test_cli_capabilities import TIMEOUT_DEFAULT, run_cli_query, validate_cli_response


class TestSchemaAware:
    """Tests for schema-aware query capabilities."""

    @pytest.mark.slow
    def test_s01_table_discovery(self):
        """S01: Discover available tables."""
        result = run_cli_query("what SuzieQ tables can I query?", timeout=TIMEOUT_DEFAULT)

        validate_cli_response(
            result,
            must_contain=["table"],
            min_length=30,
        )

        assert result.success, f"Query failed: {result.stderr}"

    @pytest.mark.slow
    def test_s02_field_discovery(self):
        """S02: Discover table fields."""
        result = run_cli_query("what fields are in the BGP table?", timeout=TIMEOUT_DEFAULT)

        validate_cli_response(
            result,
            must_contain=["field"],
            min_length=30,
        )

        assert result.success, f"Query failed: {result.stderr}"

    @pytest.mark.slow
    def test_s03_method_discovery(self):
        """S03: Discover available methods."""
        result = run_cli_query("what methods can I use to query data?", timeout=TIMEOUT_DEFAULT)

        validate_cli_response(
            result,
            must_contain=["method"],
            min_length=30,
        )

        assert result.success, f"Query failed: {result.stderr}"

    def test_s04_schema_query(self):
        """S04: Query schema-aware tool."""
        result = run_cli_query("查询 BGP 表的 schema 有哪些字段")

        assert result.success, f"Query failed: {result.stderr}"
