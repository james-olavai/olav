"""E2E Test: Q03 - Device Summary Query.

Tests device summary query functionality via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_q03_device.py -v
"""

from tests.e2e.test_cli_capabilities import run_cli_query, validate_cli_response


class TestQ03DeviceSummary:
    """Q03: Test device summary query."""

    def test_device_summary_all(self):
        """Test device summary for all devices."""
        result = run_cli_query("summarize all devices")

        validate_cli_response(
            result,
            must_contain=["device"],
            min_length=20,
        )

        assert result.success, f"Query failed: {result.stderr}"

    def test_device_list(self):
        """Test listing all devices."""
        result = run_cli_query("list all devices")

        assert result.success, f"Query failed: {result.stderr}"
