"""E2E Test: X - Error Handling Tests.

Tests error handling and edge cases via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_x_error_handling.py -v
"""

import subprocess

from tests.e2e.test_cli_capabilities import (
    CLI_PATH,
    PROJECT_ROOT,
    run_cli_query,
    validate_cli_response,
)


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    def test_x01_unknown_device(self):
        """X01: Handle unknown device gracefully."""
        result = run_cli_query("check BGP on NONEXISTENT_DEVICE_XYZ")

        # Should not crash, may return no data message
        output = result.stdout.lower()
        graceful_responses = ["no data", "not found", "unknown", "empty", "error", "没有"]
        has_graceful = any(r in output for r in graceful_responses)

        # Either succeeds with no data message or fails gracefully
        assert result.success or has_graceful, f"Should handle gracefully: {result.stderr}"

    def test_x02_empty_filter(self):
        """X02: Handle empty result gracefully."""
        result = run_cli_query("find BGP peers with ASN 99999")

        # Should succeed even with no results
        assert result.success, f"Query failed: {result.stderr}"

    def test_x03_chinese_query(self):
        """X03: Support Chinese language queries."""
        result = run_cli_query("查询 R1 的 BGP 状态")

        # Should understand Chinese
        validate_cli_response(
            result,
            must_contain=["BGP"],
            min_length=20,
        )

        assert result.success, f"Chinese query failed: {result.stderr}"

    def test_x04_help_command(self):
        """X04: Show help correctly."""
        # Test the actual help via --help flag
        result = subprocess.run(
            ["uv", "run", "python", str(CLI_PATH), "--help"],
            check=False, capture_output=True,
            text=True,
            timeout=30,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode == 0
        assert "OLAV" in result.stdout or "olav" in result.stdout.lower()

    def test_x05_version_command(self):
        """X05: Show version correctly."""
        result = subprocess.run(
            ["uv", "run", "python", str(CLI_PATH), "version"],
            check=False, capture_output=True,
            text=True,
            timeout=30,
            cwd=PROJECT_ROOT,
        )

        assert result.returncode == 0

    def test_x06_json_output(self):
        """X06: Test JSON output format."""
        result = run_cli_query("你好", json_output=True)

        # JSON output should contain valid structure
        assert result.success, f"Query failed: {result.stderr}"
        assert "queries" in result.stdout or "responses" in result.stdout, \
            f"Should have JSON structure: {result.stdout[:200]}"
