"""E2E Test: Q04 - Routing Table Query.

Tests routing table query functionality via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_q04_route.py -v
"""

from tests.e2e.test_cli_capabilities import run_cli_query, validate_cli_response


class TestQ04RouteTable:
    """Q04: Test routing table query."""

    def test_route_table_r1(self):
        """Test routing table for R1."""
        result = run_cli_query("show routing table of R1")

        validate_cli_response(
            result,
            must_contain=["route"],
            min_length=20,
        )

        assert result.success, f"Query failed: {result.stderr}"

    def test_route_summary(self):
        """Test route summary."""
        result = run_cli_query("summarize routes")

        assert result.success, f"Query failed: {result.stderr}"
