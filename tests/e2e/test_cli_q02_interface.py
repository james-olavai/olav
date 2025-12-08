"""E2E Test: Q02 - Interface Status Query.

Tests interface status query functionality via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_q02_interface.py -v
"""

from tests.e2e.test_cli_capabilities import run_cli_query, validate_cli_response


class TestQ02InterfaceStatus:
    """Q02: Test interface status query."""

    def test_interface_status_r1(self):
        """Test interface status for R1."""
        result = run_cli_query("show interfaces on R1")

        validation = validate_cli_response(
            result,
            must_contain=["interface"],
            min_length=20,
        )

        assert result.success, f"Query failed: {result.stderr}"
        assert validation.passed, f"Validation failed: {validation.details}"

    def test_interface_status_summary(self):
        """Test interface status summary."""
        result = run_cli_query("summarize interfaces")

        validate_cli_response(
            result,
            must_contain=["interface"],
            min_length=20,
        )

        assert result.success, f"Query failed: {result.stderr}"
