"""E2E Test: Q01 - BGP Status Query.

Tests basic BGP status query functionality via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_q01_bgp_status.py -v
"""

from tests.e2e.test_cli_capabilities import run_cli_query, validate_cli_response


class TestQ01BGPStatus:
    """Q01: Test BGP status query."""

    def test_bgp_status_r1(self):
        """Test BGP status check for R1."""
        result = run_cli_query("check R1 BGP status")

        validation = validate_cli_response(
            result,
            must_contain=["BGP"],
            min_length=20,
        )

        assert result.success, f"Query failed: {result.stderr}"
        assert validation.passed, f"Validation failed: {validation.details}"

    def test_bgp_status_all_devices(self):
        """Test BGP status summary for all devices."""
        result = run_cli_query("summarize BGP status")

        validate_cli_response(
            result,
            must_contain=["BGP"],
            min_length=20,
        )

        assert result.success, f"Query failed: {result.stderr}"
