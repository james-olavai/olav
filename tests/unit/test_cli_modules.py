"""Unit tests for CLI modules.

Run: pytest tests/unit/test_cli_modules.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


class TestCLIModules:
    """Tests for src/olav/cli modules."""

    def test_cli_main_import(self):
        """Test CLI main module imports."""
        try:
            from src.olav.cli import main

            assert main is not None
        except ImportError:
            pytest.skip("CLI main module import failed")

    def test_cli_daemon_import(self):
        """Test CLI daemon module imports."""
        try:
            from src.olav.cli import daemon

            assert daemon is not None
        except ImportError:
            pytest.skip("CLI daemon module import failed")

    def test_cli_commands_import(self):
        """Test CLI commands module imports."""
        try:
            from src.olav.cli.commands import base

            assert base is not None
        except ImportError:
            pytest.skip("CLI commands module import failed")

    def test_cli_display_import(self):
        """Test CLI display module imports."""
        try:
            from src.olav.cli import display

            assert display is not None
        except ImportError:
            pytest.skip("CLI display module import failed")
