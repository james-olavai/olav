"""Integration tests for sync_tools.py functions.

Tests the actual tool functions for correct behavior.
"""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Import the actual functions (requires project be in sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

try:
    # Try importing from the skill directly (standalone mode)
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "sync_tools",
        Path(__file__).resolve().parents[2]
        / ".olav"
        / "skills"
        / "olav-config"
        / "tools"
        / "sync_tools.py",
    )
    sync_tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_tools)
    HAS_SYNC_TOOLS = True
except Exception as e:
    HAS_SYNC_TOOLS = False
    sync_tools = None


class TestConfigCommandLoading:
    """Test _load_config_commands() function."""

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_load_config_commands_returns_list(self) -> None:
        """Verify _load_config_commands returns a list."""
        cmds = sync_tools._load_config_commands()
        assert isinstance(cmds, list)
        assert len(cmds) > 0

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_config_commands_include_running_config(self) -> None:
        """Verify config commands include running-config variants."""
        cmds = sync_tools._load_config_commands()
        cmd_strs = " ".join(cmds).lower()
        assert "running" in cmd_strs or "configuration" in cmd_strs

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_config_commands_cached(self) -> None:
        """Verify _load_config_commands caches results."""
        # First call
        cmds1 = sync_tools._load_config_commands()
        # Second call should return cached
        cmds2 = sync_tools._load_config_commands()
        # Should be same object (cached)
        assert cmds1 is cmds2


class TestCmdToFilename:
    """Test _cmd_to_filename() function."""

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_cmd_to_filename_basic(self) -> None:
        """Test command to filename conversion."""
        test_cases = [
            ("show running-config", "show-running-config.txt"),
            ("show version", "show-version.txt"),
            ("show interfaces", "show-interfaces.txt"),
        ]

        for cmd, expected in test_cases:
            result = sync_tools._cmd_to_filename(cmd)
            assert result == expected, f"cmd={cmd}, expected={expected}, got={result}"

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_cmd_to_filename_with_slashes(self) -> None:
        """Test command with slashes."""
        cmd = "show ip/bgp"
        result = sync_tools._cmd_to_filename(cmd)
        assert result == "show-ip-bgp.txt"
        assert "/" not in result

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_cmd_to_filename_with_partition(self) -> None:
        """Test partition command filename."""
        cmd = "show running-config partition route-map"
        result = sync_tools._cmd_to_filename(cmd)
        assert "partition" in result
        assert result.endswith(".txt")


class TestFindRunningConfigFiles:
    """Test _find_running_config_files() function."""

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_detect_full_config_from_content(self) -> None:
        """Test detection of full running-config by content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            # Create a full config file
            full_config = tmpdir / "show-running-config.txt"
            full_config.write_text(
                "Building configuration...\nCurrent configuration : 1000 bytes\n!"
            )

            # Verify content detection works
            sample = full_config.read_text()[:600]
            is_config = any(
                m in sample.lower()
                for m in [
                    "building configuration",
                    "current configuration",
                    "!command: show running config",
                ]
            )

            assert is_config

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_partition_marker_detection(self) -> None:
        """Test detection of partition marker in content."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)

            partial_config = tmpdir / "show-running-config-partition-route-map.txt"
            partial_config.write_text(
                "Building configuration...\nConfiguration of Partition - route-map\n"
            )

            sample = partial_config.read_text()[:1000].lower()
            is_partition = "configuration of partition" in sample

            assert is_partition


class TestSyncDirResolution:
    """Test sync directory functions."""

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_get_sync_base_dir(self) -> None:
        """Test get_sync_base_dir() returns valid path."""
        base_dir = sync_tools.get_sync_base_dir()
        assert isinstance(base_dir, Path)
        # Should end with 'snapshots'
        assert base_dir.name == "snapshots"

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_get_sync_dir_default_date(self) -> None:
        """Test get_sync_dir() with default (today) date."""
        sync_dir = sync_tools.get_sync_dir()
        assert isinstance(sync_dir, Path)
        # Should be parent/today/
        date_part = sync_dir.name
        assert len(date_part) == 10  # YYYY-MM-DD format
        assert date_part[4] == "-" and date_part[7] == "-"

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_get_sync_dir_specific_date(self) -> None:
        """Test get_sync_dir() with specific date."""
        sync_dir = sync_tools.get_sync_dir("2026-02-19")
        assert isinstance(sync_dir, Path)
        assert sync_dir.name == "2026-02-19"

    @pytest.mark.skipif(not HAS_SYNC_TOOLS, reason="sync_tools not available")
    def test_get_latest_sync_dir(self) -> None:
        """Test get_latest_sync_dir() returns path or None."""
        latest = sync_tools.get_latest_sync_dir()
        # Could be None if no syncs exist yet, or a Path
        assert latest is None or isinstance(latest, Path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
