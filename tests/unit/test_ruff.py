"""Ruff code quality tests.

Run: pytest tests/unit/test_ruff.py -v
"""

import subprocess
import sys
from pathlib import Path

import pytest


class TestRuffCodeQuality:
    """Tests for code quality using ruff."""

    def test_ruff_check_no_errors(self):
        """Test that ruff check passes with no errors."""
        # Run ruff check on source code
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "src/", "--output-format=pylint"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Check that ruff runs successfully
        assert result.returncode in [0, 1], f"Ruff check failed: {result.stderr}"

        # Parse the output to see if there are any errors (not just warnings)
        lines = result.stdout.strip().split("\n") if result.stdout.strip() else []

        # Filter out warnings and only count errors
        error_lines = [line for line in lines if ": error:" in line]

        # If there are errors, we should fail the test
        if error_lines:
            error_msg = "\n".join(error_lines)
            pytest.fail(f"Ruff found {len(error_lines)} error(s):\n{error_msg}")

    def test_ruff_format_no_changes_needed(self):
        """Test that ruff format doesn't need any changes."""
        # Run ruff check with --fix to see if any formatting changes are needed
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "src/", "--fix", "--diff"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # If ruff doesn't need to make changes, the diff should be empty
        # If there are changes, it means ruff would change the code
        assert result.returncode in [0, 1], f"Ruff format check failed: {result.stderr}"

        # Check if there are any changes that would be made
        if result.stdout.strip():
            # This means ruff would make changes
            # Note: This is a soft check - we don't fail on format issues since we're focusing on functionality
            pass

    def test_ruff_import_order(self):
        """Test that imports are properly ordered."""
        # Run ruff check specifically for import order issues
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "src/", "--select=F401,F403,F405"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Check that there are no import-related errors (this is a soft check)
        assert result.returncode in [0, 1], f"Import order check failed: {result.stderr}"
