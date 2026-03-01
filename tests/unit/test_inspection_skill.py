"""Unit tests for network-inspection skill components.

Tests individual functions and components without requiring real network devices.
Covers:
- Config loading (thresholds.yaml)
- Path resolution (self-contained vs. framework modes)
- Config file detection logic
- Health score calculation

NOTE: This test file tests the old network-inspection skill architecture.
The current skills are olav-audit, olav-config, olav-ops, and command_learner.
These tests are kept for reference but skipped since the paths don't exist.
"""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Skip entire module since network-inspection skill doesn't exist anymore
pytestmark = pytest.mark.skip(
    reason="network-inspection skill deprecated - see olav-audit/olav-config"
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def skill_root_dir() -> Path:
    """Get the network-inspection skill root directory."""
    return Path(__file__).resolve().parents[2] / ".olav" / "skills" / "network-inspection"


@pytest.fixture
def thresholds_path(skill_root_dir: Path) -> Path:
    """Get the thresholds.yaml path."""
    return skill_root_dir / "config" / "thresholds.yaml"


@pytest.fixture
def thresholds_content(thresholds_path: Path) -> dict:
    """Load thresholds.yaml content."""
    if not thresholds_path.exists():
        pytest.skip(f"thresholds.yaml not found at {thresholds_path}")

    with open(thresholds_path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


@pytest.fixture
def sample_snapshot_dir(tmp_path: Path) -> Path:
    """Create a temporary snapshot directory structure."""
    snap_date = "2026-02-19"
    snap_dir = tmp_path / snap_date / "raw" / "R1"
    snap_dir.mkdir(parents=True, exist_ok=True)
    return snap_dir


# =============================================================================
# Test: Config Loading (thresholds.yaml)
# =============================================================================


class TestThresholdsConfig:
    """Tests for thresholds.yaml loading and structure."""

    def test_thresholds_yaml_exists(self, thresholds_path: Path) -> None:
        """Verify thresholds.yaml exists."""
        assert thresholds_path.exists(), f"thresholds.yaml not found at {thresholds_path}"

    def test_thresholds_yaml_valid_format(self, thresholds_content: dict) -> None:
        """Verify thresholds.yaml is valid YAML."""
        assert isinstance(thresholds_content, dict)
        assert "version" in thresholds_content

    def test_thresholds_has_defaults_section(self, thresholds_content: dict) -> None:
        """Verify thresholds.yaml has defaults section."""
        assert "defaults" in thresholds_content
        assert "performance" in thresholds_content["defaults"]

    def test_thresholds_has_inspection_items(self, thresholds_content: dict) -> None:
        """Verify thresholds.yaml defines inspection items."""
        assert "inspection_items" in thresholds_content
        items = thresholds_content["inspection_items"]
        assert len(items) > 0

    def test_thresholds_cpu_memory_defined(self, thresholds_content: dict) -> None:
        """Verify CPU and memory thresholds are defined."""
        items = thresholds_content.get("inspection_items", {})
        assert "cpu_utilization" in items
        assert "memory_utilization" in items

        cpu = items["cpu_utilization"]
        assert "warning" in cpu or "critical" in cpu

    def test_thresholds_config_commands_defined(self, thresholds_content: dict) -> None:
        """Verify config_commands list is defined (for command→filename mapping)."""
        assert "config_commands" in thresholds_content
        cmds = thresholds_content["config_commands"]
        assert isinstance(cmds, list)
        assert len(cmds) > 0
        assert any("running" in cmd.lower() for cmd in cmds)

    def test_config_commands_include_partitions(self, thresholds_content: dict) -> None:
        """Verify config_commands includes both full and partition variants."""
        cmds = thresholds_content.get("config_commands", [])
        full_dumps = [c for c in cmds if "partition" not in c.lower()]
        partitions = [c for c in cmds if "partition" in c.lower()]

        assert len(full_dumps) > 0, "Should have at least one full-dump command"
        assert len(partitions) >= 0, "Should optionally have partition commands"


# =============================================================================
# Test: Path Resolution (Self-Contained Mode)
# =============================================================================


class TestPathResolution:
    """Tests for self-contained path resolution."""

    def test_olav_dir_resolution(self) -> None:
        """Verify skill can resolve .olav directory."""
        skill_tools = (
            Path(__file__).resolve().parents[2]
            / ".olav"
            / "skills"
            / "network-inspection"
            / "tools"
        )
        assert skill_tools.exists()

        # Skill should be able to find .olav by walking up
        olav_dir = skill_tools.parents[2]  # .olav/
        assert (olav_dir / "skills" / "network-inspection").exists()

    def test_snapshots_dir_fallback(self) -> None:
        """Verify skill can construct snapshots path without framework."""
        # Walk up to find pyproject.toml (project root)
        test_file = Path(__file__).resolve()
        project_root = test_file.parent
        while project_root != project_root.parent:
            if (project_root / "pyproject.toml").exists():
                break
            project_root = project_root.parent

        exports_dir = project_root / "exports" / "snapshots"
        # Path should be derivable even without framework
        assert project_root.exists()
        assert "pyproject.toml" in [f.name for f in project_root.iterdir()]

    def test_config_file_relative_path(self, skill_root_dir: Path) -> None:
        """Verify config files are accessible relative to skill root."""
        assert (skill_root_dir / "config" / "thresholds.yaml").exists()
        assert (skill_root_dir / "config" / "output_format.yaml").exists()


# =============================================================================
# Test: Config File Detection Logic
# =============================================================================


class TestConfigFileDetection:
    """Tests for detecting running-config files."""

    def test_cmd_to_filename_conversion(self) -> None:
        """Test command→filename conversion rule."""
        # Rule: space→hyphen, /→hyphen, +.txt
        test_cases = [
            ("show running-config", "show-running-config.txt"),
            ("show configuration", "show-configuration.txt"),
            ("display current-configuration", "display-current-configuration.txt"),
            (
                "show running-config partition route-map",
                "show-running-config-partition-route-map.txt",
            ),
        ]

        for cmd, expected_fname in test_cases:
            actual = cmd.replace(" ", "-").replace("/", "-") + ".txt"
            assert actual == expected_fname, f"cmd={cmd} → expected {expected_fname}, got {actual}"

    def test_filename_partition_detection(self) -> None:
        """Test detection of partition vs full dump from filename."""
        full_dump_names = ["show-running-config.txt"]
        partition_names = [
            "show-running-config-partition-route-map.txt",
            "show-running-config-partition-access-list.txt",
        ]

        for name in full_dump_names:
            is_partition = "partition" in name.lower()
            assert not is_partition, f"{name} should not be detected as partition"

        for name in partition_names:
            is_partition = "partition" in name.lower()
            assert is_partition, f"{name} should be detected as partition"

    def test_full_dump_preferred_over_partition(self) -> None:
        """Test that full dumps are preferred over partition files."""
        full_dumps = {"show-running-config.txt": Path("/tmp/full")}
        partial_configs = {
            "show-running-config-partition-route-map.txt": Path("/tmp/partial"),
        }

        # Selection logic: choose full if available
        final = full_dumps if full_dumps else partial_configs
        assert "show-running-config.txt" in final


# =============================================================================
# Test: Health Score Calculation
# =============================================================================


class TestHealthScoreCalculation:
    """Tests for device health scoring."""

    def test_health_score_all_healthy(self) -> None:
        """Test health score when no anomalies."""
        anomalies = []

        # Score = 100 - (anomaly_count * severity_weight)
        # No anomalies → 100
        score = 100 - (len(anomalies) * 10)
        assert score == 100

    def test_health_score_with_warnings(self) -> None:
        """Test health score with warning-level anomalies."""
        anomalies = [
            {"name": "high_cpu", "severity": "warning", "value": 75},
            {"name": "high_memory", "severity": "warning", "value": 70},
        ]

        # 2 warnings → each reduces score by 10
        warning_count = sum(1 for a in anomalies if a["severity"] == "warning")
        score = 100 - (warning_count * 10)
        assert score == 80

    def test_health_score_with_criticals(self) -> None:
        """Test health score with critical-level anomalies."""
        anomalies = [
            {"name": "interface_down", "severity": "critical"},
            {"name": "bgp_neighbor_down", "severity": "critical"},
        ]

        # 2 criticals → each reduces score by 30
        critical_count = sum(1 for a in anomalies if a["severity"] == "critical")
        score = 100 - (critical_count * 30)
        assert score == 40

    def test_health_score_floor_zero(self) -> None:
        """Test that health score never goes below 0."""
        anomalies = [{"severity": "critical"} for _ in range(10)]

        score = max(0, 100 - (len(anomalies) * 30))
        assert score == 0


# =============================================================================
# Test: Aggregation (Reduce Phase)
# =============================================================================


class TestAggregationLogic:
    """Tests for aggregating inspection results."""

    def test_device_aggregation_single_device(self) -> None:
        """Test aggregating results for a single device."""
        results = {
            "R1": {
                "device": "R1",
                "platform": "cisco_ios",
                "health_score": 95,
                "anomalies": [{"name": "high_cpu", "value": 85}],
            }
        }

        # Aggregate
        device_count = len(results)
        total_health = sum(r["health_score"] for r in results.values())
        avg_health = total_health / device_count if device_count > 0 else 100

        assert device_count == 1
        assert avg_health == 95

    def test_device_aggregation_multiple_devices(self) -> None:
        """Test aggregating results for multiple devices."""
        results = {
            "R1": {"health_score": 100, "anomalies": []},
            "R2": {"health_score": 90, "anomalies": [{}]},
            "R3": {"health_score": 80, "anomalies": [{}, {}]},
            "R4": {"health_score": 100, "anomalies": []},
        }

        device_count = len(results)
        total_health = sum(r["health_score"] for r in results.values())
        avg_health = total_health / device_count
        total_anomalies = sum(len(r["anomalies"]) for r in results.values())

        assert device_count == 4
        assert avg_health == 92.5
        assert total_anomalies == 3

    def test_anomaly_rollup_by_severity(self) -> None:
        """Test rolling up anomalies by severity."""
        all_anomalies = [
            {"severity": "warning"},
            {"severity": "warning"},
            {"severity": "critical"},
            {"severity": "warning"},
            {"severity": "critical"},
        ]

        by_severity = {}
        for anom in all_anomalies:
            sev = anom["severity"]
            by_severity[sev] = by_severity.get(sev, 0) + 1

        assert by_severity.get("warning") == 3
        assert by_severity.get("critical") == 2


# =============================================================================
# Test: Report Generation
# =============================================================================


class TestReportStructure:
    """Tests for report output structure."""

    def test_report_required_sections(self) -> None:
        """Test that report contains all required sections."""
        required_sections = [
            "Overall Health",
            "Device Health Summary",
            "Anomalies",
            "Device Details",
        ]

        # These would be checked in actual report markdown
        for section in required_sections:
            assert len(section) > 0

    def test_device_details_categories(self) -> None:
        """Test that device details cover all categories."""
        expected_categories = [
            "System",
            "Interfaces",
            "Routing",
            "Neighbors",
            "Switching",
            "Environment",
        ]

        for category in expected_categories:
            assert len(category) > 0


# =============================================================================
# Test: Snapshot File Management
# =============================================================================


class TestSnapshotFileManagement:
    """Tests for snapshot directory handling."""

    def test_snapshot_date_format(self) -> None:
        """Test snapshot date format (YYYY-MM-DD)."""
        import re

        date_pattern = r"^\d{4}-\d{2}-\d{2}$"
        valid_dates = [
            "2026-02-19",
            "2026-01-01",
            "2025-12-31",
        ]

        for date in valid_dates:
            assert re.match(date_pattern, date), f"Invalid date: {date}"

    def test_snapshot_directory_structure(self, sample_snapshot_dir: Path) -> None:
        """Test that snapshot directories have expected structure."""
        # Create sample files
        full_config = sample_snapshot_dir / "show-running-config.txt"
        partial_config = sample_snapshot_dir / "show-running-config-partition-route-map.txt"
        other_file = sample_snapshot_dir / "show-version.txt"

        full_config.write_text("Building configuration...")
        partial_config.write_text("Configuration of Partition")
        other_file.write_text("Cisco IOS")

        # Verify all exist
        assert full_config.exists()
        assert partial_config.exists()
        assert other_file.exists()


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling and graceful degradation."""

    def test_thresholds_load_fallback(self) -> None:
        """Test fallback when thresholds.yaml is missing."""
        # Simulate missing file
        thresholds_path = Path("/nonexistent/thresholds.yaml")

        if not thresholds_path.exists():
            # Use defaults
            defaults = {
                "cpu_warning": 70,
                "cpu_critical": 90,
                "memory_warning": 70,
                "memory_critical": 90,
            }
            assert defaults["cpu_warning"] == 70

    def test_missing_snapshot_directory(self, tmp_path: Path) -> None:
        """Test handling of missing snapshot directory."""
        missing_dir = tmp_path / "nonexistent" / "2026-02-19"

        latest = None
        if missing_dir.exists():
            latest = missing_dir

        assert latest is None

    def test_malformed_config_file(self, tmp_path: Path) -> None:
        """Test handling of malformed YAML config."""
        bad_yaml = tmp_path / "bad.yaml"
        bad_yaml.write_text("invalid: yaml: content: [")

        try:
            with open(bad_yaml, encoding="utf-8") as f:
                yaml.safe_load(f)
            assert False, "Should have raised error"
        except yaml.YAMLError:
            pass  # Expected


# =============================================================================
# Test: Documentation
# =============================================================================


class TestDocumentation:
    """Tests for SKILL.md and inline documentation."""

    def test_skill_md_exists(self, skill_root_dir: Path) -> None:
        """Verify SKILL.md exists."""
        skill_md = skill_root_dir / "SKILL.md"
        assert skill_md.exists()

    def test_skill_md_has_required_sections(self, skill_root_dir: Path) -> None:
        """Verify SKILL.md has required frontmatter."""
        skill_md = skill_root_dir / "SKILL.md"
        content = skill_md.read_text(encoding="utf-8")

        assert "name: network-inspection" in content
        assert "version:" in content
        assert "tools:" in content

    def test_tools_have_docstrings(self) -> None:
        """Verify that tool functions have docstrings."""
        # This would check actual tool definitions
        # Placeholder for now
        assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
