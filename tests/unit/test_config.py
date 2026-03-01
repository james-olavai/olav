"""Unit tests for config module.

Tests for legacy config/settings.py, config/paths.py.
NOTE: These tests are for the OLD API - the new config system is in olav.core.config.
Run: pytest tests/unit/test_config.py -v
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))


# Skip all tests in this module - they test legacy API
pytestmark = pytest.mark.skip(reason="Legacy API tests - use olav.core.config instead")


class TestSettings:
    """Tests for old config/settings.py - SKIPPED"""

    def test_settings_default_values(self):
        from config.settings import Settings

        settings = Settings()
        assert settings.llm_model_name is not None
        assert settings.llm_temperature is not None

    def test_settings_database_defaults(self):
        from config.settings import Settings

        settings = Settings()
        assert settings.database.main_db == Path(".olav/databases/main.duckdb")

    def test_settings_execution_defaults(self):
        from config.settings import Settings

        settings = Settings()
        assert settings.execution.use_textfsm is True


class TestPaths:
    """Tests for old config/paths.py - SKIPPED"""

    def test_paths_import(self):
        from config.paths import PROJECT_ROOT, MAIN_DB_PATH

        assert PROJECT_ROOT is not None


class TestTasksConfig:
    """Tests for old config/tasks.py - SKIPPED"""

    def test_tasks_import(self):
        from config.tasks import TaskSchedulerSettings

        assert TaskSchedulerSettings is not None
