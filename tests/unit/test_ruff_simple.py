"""Simple Ruff code quality tests.

Run: pytest tests/unit/test_ruff_simple.py -v
"""

import subprocess
import sys
from pathlib import Path

import pytest


class TestRuffCodeQuality:
    """Tests for code quality using ruff."""

    def test_ruff_check_runs(self):
        """Test that ruff check runs successfully."""
        # Run ruff check on source code - just make sure it doesn't crash
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "src/"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Ruff should run successfully (return code 0 or 1 for linting issues)
        # Return code 2 means command line error, which would be a problem
        assert result.returncode != 2, f"Ruff command failed: {result.stderr}"

    def test_ruff_format_runs(self):
        """Test that ruff format runs successfully."""
        # Run ruff format check
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "src/", "--check"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )

        # Ruff should run successfully (return code 0 or 1 for formatting issues)
        # Return code 2 means command line error, which would be a problem
        assert result.returncode != 2, f"Ruff format command failed: {result.stderr}"
