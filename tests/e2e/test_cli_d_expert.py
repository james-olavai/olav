"""E2E Test: D - Expert Mode (Deep Dive) Tests.

Tests expert mode capabilities via CLI.

Usage:
    uv run pytest tests/e2e/test_cli_d_expert.py -v
"""

import pytest
from tests.e2e.test_cli_capabilities import TIMEOUT_DEFAULT, run_cli_query, validate_cli_response


class TestExpertMode:
    """Tests for expert mode (deep dive) capabilities."""

    @pytest.mark.slow
    def test_d01_diagnosis(self):
        """D01: Test multi-step diagnosis."""
        result = run_cli_query(
            "analyze why R1 cannot reach R2",
            mode="expert",
            timeout=TIMEOUT_DEFAULT,
        )

        validate_cli_response(
            result,
            must_contain=["R1", "R2"],
            min_length=50,
        )

        assert result.success, f"Query failed: {result.stderr}"

    @pytest.mark.slow
    def test_d02_root_cause(self):
        """D02: Test root cause analysis."""
        result = run_cli_query(
            "why is BGP flapping on R1?",
            mode="expert",
            timeout=TIMEOUT_DEFAULT,
        )

        validate_cli_response(
            result,
            must_contain=["BGP"],
            min_length=30,
        )

        assert result.success, f"Query failed: {result.stderr}"

    @pytest.mark.slow
    def test_d03_network_health(self):
        """D03: Test comprehensive network health check."""
        result = run_cli_query(
            "检查整个网络的健康状态",
            mode="expert",
            timeout=TIMEOUT_DEFAULT,
        )

        assert result.success, f"Query failed: {result.stderr}"
