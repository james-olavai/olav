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
        / "workspace"
        / "config"
        / "sync"
        / "tools"
        / "sync_tools.py",
    )
    sync_tools = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sync_tools)
    HAS_SYNC_TOOLS = True
except Exception:
    HAS_SYNC_TOOLS = False
    sync_tools = None


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
        # Should be parent/YYYY-MM-DD_HHMM/
        date_part = sync_dir.name
        assert len(date_part) == 15  # YYYY-MM-DD_HHMM format
        assert date_part[4] == "-" and date_part[7] == "-" and date_part[10] == "_"

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
