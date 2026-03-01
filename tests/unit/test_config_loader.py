"""Test Config Loader - Three-Tier Configuration Priority.

This test verifies the config loading priority:
1. Environment variables (highest)
2. User config (~/.olav/config.json)
3. Project config (.olav/config/*)
4. Blueprint defaults (src/olav/core/defaults.py)

TDD: Tests should FAIL until the config system is properly implemented.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# Test constants
TEST_MODEL = "gpt-4o"
TEST_PROVIDER = "anthropic"
TEST_PORT = 5515


class TestConfigLoaderPriority:
    """Test configuration priority chain."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def temp_user_home(self):
        """Create a temporary user home directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_env_overrides_project(self, temp_project, monkeypatch):
        """Test that environment variables override project config.

        Priority: Env > Project > Blueprint
        """
        # Set environment variable
        monkeypatch.setenv("OLAV_LLM_MODEL", TEST_MODEL)
        monkeypatch.setenv("OLAV_LLM_PROVIDER", TEST_PROVIDER)

        # Mock project root to our temp directory
        monkeypatch.chdir(temp_project)

        # Create project config
        project_config_dir = temp_project / ".olav" / "config"
        project_config_dir.mkdir(parents=True, exist_ok=True)
        api_config = project_config_dir / "api.json"
        api_config.write_text(json.dumps({"llm": {"model": "gpt-3.5-turbo", "provider": "openai"}}))

        # Reset the config singleton
        from olav.core import config as config_module

        config_module._config = None
        config_module.ConfigLoader._loaded = False
        config_module.ConfigLoader._instance = None

        # Import and test config
        from olav.core.config import reload_config, get_llm_config

        # Force reload with new mock paths
        with patch("olav.core.config._PROJECT_ROOT", temp_project):
            with patch("olav.core.config._CONFIG_DIR", temp_project / ".olav" / "config"):
                reload_config()
                config = get_llm_config()

                # Environment should win
                assert config.model == TEST_MODEL, f"Expected {TEST_MODEL}, got {config.model}"
                assert config.provider == TEST_PROVIDER

    def test_env_overrides_defaults(self, temp_project, monkeypatch):
        """Test that environment variables override blueprint defaults.

        Priority: Env > Project > Blueprint
        """
        # Only set environment variable, no project config
        monkeypatch.setenv("OLAV_LLM_MODEL", TEST_MODEL)
        monkeypatch.chdir(temp_project)

        # Don't create any config files - should use defaults + env override
        # Reset the config singleton
        from olav.core import config as config_module

        config_module._config = None
        config_module.ConfigLoader._loaded = False
        config_module.ConfigLoader._instance = None

        from olav.core.config import reload_config, get_llm_config

        with patch("olav.core.config._PROJECT_ROOT", temp_project):
            reload_config()
            config = get_llm_config()

            # Environment should override default
            assert config.model == TEST_MODEL

    def test_project_overrides_defaults(self, temp_project, monkeypatch):
        """Test that project config overrides blueprint defaults.

        Priority: Env > Project > Blueprint
        """
        monkeypatch.chdir(temp_project)

        # Clear any env vars
        monkeypatch.delenv("OLAV_LLM_MODEL", raising=False)
        monkeypatch.delenv("OLAV_LLM_PROVIDER", raising=False)

        # Create project config (use exist_ok=True to handle existing dirs)
        project_config_dir = temp_project / ".olav" / "config"
        project_config_dir.mkdir(parents=True, exist_ok=True)
        api_config = project_config_dir / "api.json"
        api_config.write_text(json.dumps({"llm": {"model": TEST_MODEL, "provider": TEST_PROVIDER}}))

        # Reset the config singleton
        from olav.core import config as config_module

        config_module._config = None
        config_module.ConfigLoader._loaded = False
        config_module.ConfigLoader._instance = None

        from olav.core.config import reload_config, get_llm_config

        with patch("olav.core.config._PROJECT_ROOT", temp_project):
            with patch("olav.core.config._CONFIG_DIR", temp_project / ".olav" / "config"):
                reload_config()
                config = get_llm_config()

                # Project should override default
                assert config.model == TEST_MODEL, f"Expected {TEST_MODEL}, got {config.model}"
                assert config.provider == TEST_PROVIDER


class TestPathsConfig:
    """Test PathsConfig resolution."""

    @pytest.fixture
    def temp_project(self):
        """Create a temporary project directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    def test_resolve_absolute_path(self, temp_project, monkeypatch):
        """Test that PathsConfig can derive correct absolute paths."""
        monkeypatch.chdir(temp_project)

        # Create project config with paths
        project_config_dir = temp_project / ".olav" / "config"
        project_config_dir.mkdir(parents=True, exist_ok=True)
        paths_config = project_config_dir / "paths.json"
        paths_config.write_text(
            json.dumps(
                {
                    "databases_dir": ".olav/databases",
                    "logs_dir": ".olav/logs",
                }
            )
        )

        # Reset config singleton
        from olav.core import config as config_module

        config_module._config = None
        config_module.ConfigLoader._loaded = False
        config_module.ConfigLoader._instance = None

        from olav.core.config import reload_config, get_paths_config

        with patch("olav.core.config._PROJECT_ROOT", temp_project):
            with patch("olav.core.config._CONFIG_DIR", temp_project / ".olav" / "config"):
                reload_config()
                paths = get_paths_config()

                # Should resolve to absolute paths
                assert "databases" in paths.databases_dir
                assert paths.databases_dir.startswith(
                    str(temp_project)
                ) or paths.databases_dir.startswith(".olav")

    def test_resolve_with_explicit_base(self, temp_project):
        """Test path resolution with explicit base path."""
        from olav.core.config import PathsConfig

        # Create config with relative paths
        data = {
            "databases_dir": ".olav/databases",
            "logs_dir": ".olav/logs",
        }

        class MockLoader:
            def _env_override(self, section, key, default):
                return default

        paths = PathsConfig(data, MockLoader())

        # Should be able to resolve relative to project root
        assert paths.databases_dir is not None


class TestConfigDefaults:
    """Test default configuration values."""

    def test_defaults_module_exists(self):
        """Test that defaults.py exists and has required values."""
        from olav.core import defaults

        # Check required default configs exist
        assert hasattr(defaults, "DEFAULT_LLM_CONFIG")
        assert hasattr(defaults, "DEFAULT_EMBEDDING_CONFIG")
        assert hasattr(defaults, "DEFAULT_PATHS_CONFIG")
        assert hasattr(defaults, "DEFAULT_RUNTIME_CONFIG")

    def test_default_llm_values(self):
        """Test default LLM configuration values."""
        from olav.core.defaults import DEFAULT_LLM_CONFIG

        assert DEFAULT_LLM_CONFIG["provider"] == "openai"
        assert DEFAULT_LLM_CONFIG["model"] == "gpt-4-turbo"
        assert DEFAULT_LLM_CONFIG["temperature"] == 0.1

    def test_default_embedding_values(self):
        """Test default embedding configuration values."""
        from olav.core.defaults import DEFAULT_EMBEDDING_CONFIG

        assert DEFAULT_EMBEDDING_CONFIG["mode"] == "local"
        assert "local" in DEFAULT_EMBEDDING_CONFIG
        assert DEFAULT_EMBEDDING_CONFIG["local"]["device"] == "cpu"

    def test_default_paths_values(self):
        """Test default path configuration values."""
        from olav.core.defaults import DEFAULT_PATHS_CONFIG

        assert "databases_dir" in DEFAULT_PATHS_CONFIG
        assert DEFAULT_PATHS_CONFIG["databases_dir"] == ".olav/databases"


class TestConfigLoaderModule:
    """Test ConfigLoader module-level functions."""

    def test_get_config_singleton(self):
        """Test that get_config returns a singleton."""
        from olav.core.config import get_config

        config1 = get_config()
        config2 = get_config()

        # Should be the same instance
        assert config1 is config2

    def test_get_llm_config(self):
        """Test get_llm_config helper function."""
        from olav.core.config import get_llm_config

        llm_config = get_llm_config()

        # Should have required properties
        assert hasattr(llm_config, "provider")
        assert hasattr(llm_config, "model")
        assert hasattr(llm_config, "temperature")

    def test_get_paths_config(self):
        """Test get_paths_config helper function."""
        from olav.core.config import get_paths_config

        paths_config = get_paths_config()

        # Should have required properties
        assert hasattr(paths_config, "databases_dir")
        assert hasattr(paths_config, "workspace_dir")

    def test_reload_config(self):
        """Test config reload function."""
        from olav.core.config import reload_config

        # Should not raise
        config = reload_config()
        assert config is not None


# Run tests if executed directly
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
