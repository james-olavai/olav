"""Unit tests for unified inspection executor.

Tests the single-config inspection execution.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from olav.inspection.executor import (
    INSPECTION_CONFIG,
    DeviceCheckResult,
    InspectionReport,
    LogEvent,
    execute_inspection,
    get_inspection_config_path,
    get_schedule_config,
    load_inspection_config,
)


class TestInspectionConfigPath:
    """Tests for config path functions."""

    def test_get_inspection_config_path_returns_path(self):
        """Should return a Path object."""
        path = get_inspection_config_path()
        assert isinstance(path, Path)

    def test_config_path_ends_with_yaml(self):
        """Config path should end with .yaml."""
        path = get_inspection_config_path()
        assert path.suffix == ".yaml"

    def test_config_constant_is_correct_filename(self):
        """INSPECTION_CONFIG should be the expected filename."""
        assert INSPECTION_CONFIG == "inspection.yaml"


class TestLoadInspectionConfig:
    """Tests for load_inspection_config function."""

    def test_load_returns_dict_when_file_exists(self, tmp_path: Path):
        """Should return parsed config dict."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test-inspection
log_analysis:
  enabled: true
device_checks:
  enabled: false
            """,
            encoding="utf-8",
        )
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            config = load_inspection_config()
        
        assert isinstance(config, dict)
        assert config["name"] == "test-inspection"

    def test_load_raises_for_missing_file(self, tmp_path: Path):
        """Should raise FileNotFoundError when config file doesn't exist."""
        config_file = tmp_path / "nonexistent.yaml"
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            with pytest.raises(FileNotFoundError):
                load_inspection_config()


class TestGetScheduleConfig:
    """Tests for get_schedule_config function."""

    def test_returns_schedule_dict_when_enabled(self, tmp_path: Path):
        """Should return schedule config when enabled."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test
schedule:
  enabled: true
  cron: "0 6 * * *"
  timezone: "UTC"
            """,
            encoding="utf-8",
        )
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            schedule = get_schedule_config()
        
        assert schedule is not None
        assert schedule["enabled"] is True
        assert schedule["cron"] == "0 6 * * *"

    def test_returns_none_when_disabled(self, tmp_path: Path):
        """Should return None when schedule is disabled."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test
schedule:
  enabled: false
  cron: "0 6 * * *"
            """,
            encoding="utf-8",
        )
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            schedule = get_schedule_config()
        
        assert schedule is None

    def test_returns_none_when_no_schedule(self, tmp_path: Path):
        """Should return None when schedule section not in config."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test
log_analysis:
  enabled: true
            """,
            encoding="utf-8",
        )
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            schedule = get_schedule_config()
        
        assert schedule is None


class TestLogEvent:
    """Tests for LogEvent dataclass."""

    def test_log_event_creation(self):
        """Should create LogEvent with all fields."""
        event = LogEvent(
            timestamp="2024-01-15T10:30:00",
            device_ip="192.168.1.1",
            severity="critical",
            message="BGP peer down",
        )
        assert event.device_ip == "192.168.1.1"
        assert event.severity == "critical"


class TestDeviceCheckResult:
    """Tests for DeviceCheckResult dataclass."""

    def test_device_check_result_creation(self):
        """Should create DeviceCheckResult properly."""
        result = DeviceCheckResult(
            device="R1",
            check_name="BGP Neighbor Status",
            success=True,
            severity="critical",
            message="All neighbors OK",
        )
        assert result.device == "R1"
        assert result.success is True

    def test_device_check_result_defaults(self):
        """Should have correct defaults."""
        result = DeviceCheckResult(
            device="R1",
            check_name="Test",
            success=False,
        )
        assert result.severity == "info"
        assert result.message == ""
        assert result.error is None


class TestInspectionReport:
    """Tests for InspectionReport dataclass."""

    def test_empty_report_counts(self):
        """Empty report should have zero counts."""
        report = InspectionReport(
            name="test",
            generated_at="2024-01-15T10:30:00",
            time_range="24h",
        )
        assert report.total_checks == 0
        assert report.passed_count == 0
        assert report.failed_count == 0

    def test_report_with_device_checks(self):
        """Should correctly count passed/failed checks."""
        checks = [
            DeviceCheckResult("R1", "C1", True, "critical", "OK"),
            DeviceCheckResult("R2", "C2", False, "critical", "Failed"),
            DeviceCheckResult("R3", "C3", True, "warning", "OK"),
        ]
        report = InspectionReport(
            name="test",
            generated_at="2024-01-15T10:30:00",
            time_range="24h",
            device_check_results=checks,
        )
        assert report.total_checks == 3
        assert report.passed_count == 2
        assert report.failed_count == 1

    def test_report_to_markdown(self):
        """Should generate markdown output."""
        report = InspectionReport(
            name="Daily Inspection",
            generated_at="2024-01-15T10:30:00",
            time_range="24h",
        )
        markdown = report.to_markdown()
        assert "Daily Inspection" in markdown
        assert "2024-01-15" in markdown


class TestExecuteInspection:
    """Tests for execute_inspection function."""

    @pytest.mark.asyncio
    async def test_raises_when_config_missing(self, tmp_path: Path):
        """Should raise FileNotFoundError when config doesn't exist."""
        config_file = tmp_path / "nonexistent.yaml"
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            with pytest.raises(FileNotFoundError):
                await execute_inspection()

    @pytest.mark.asyncio
    async def test_raises_for_empty_config(self, tmp_path: Path):
        """Should raise ValueError for empty config."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text("", encoding="utf-8")
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            with pytest.raises(ValueError, match="Empty or invalid"):
                await execute_inspection()

    @pytest.mark.asyncio
    @patch("olav.inspection.executor.execute_log_analysis")
    @patch("olav.inspection.executor.execute_device_checks")
    async def test_executes_both_stages(
        self,
        mock_device: AsyncMock,
        mock_log: AsyncMock,
        tmp_path: Path,
    ):
        """Should execute both log analysis and device checks."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test-inspection
log_analysis:
  enabled: true
  index: syslog-raw
device_checks:
  enabled: true
  checks: []
            """,
            encoding="utf-8",
        )
        
        mock_log.return_value = ([], [], [])  # (critical, warning, devices)
        mock_device.return_value = []
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            report = await execute_inspection()
        
        mock_log.assert_called_once()
        mock_device.assert_called_once()
        assert isinstance(report, InspectionReport)

    @pytest.mark.asyncio
    @patch("olav.inspection.executor.execute_log_analysis")
    @patch("olav.inspection.executor.execute_device_checks")
    async def test_hours_parameter_overrides_time_range(
        self,
        mock_device: AsyncMock,
        mock_log: AsyncMock,
        tmp_path: Path,
    ):
        """Should pass hours parameter to log analysis."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test
log_analysis:
  enabled: true
  time_range: "24h"
device_checks:
  enabled: false
            """,
            encoding="utf-8",
        )
        
        mock_log.return_value = ([], [], [])
        mock_device.return_value = []
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            await execute_inspection(hours=48)
            
            # Verify log_analysis received modified config with 48h
            call_args = mock_log.call_args
            config_passed = call_args[0][0]
            assert config_passed.get("time_range") == "48h"

    @pytest.mark.asyncio
    @patch("olav.inspection.executor.execute_log_analysis")
    @patch("olav.inspection.executor.execute_device_checks")
    async def test_report_includes_critical_events(
        self,
        mock_device: AsyncMock,
        mock_log: AsyncMock,
        tmp_path: Path,
    ):
        """Should include critical events in report."""
        config_file = tmp_path / "inspection.yaml"
        config_file.write_text(
            """
name: test
log_analysis:
  enabled: true
device_checks:
  enabled: false
            """,
            encoding="utf-8",
        )
        
        critical_events = [
            {"device_ip": "192.168.1.1", "message": "BGP DOWN", "timestamp": "2024-01-15"}
        ]
        mock_log.return_value = (critical_events, [], ["192.168.1.1"])
        mock_device.return_value = []
        
        with patch("olav.inspection.executor.get_inspection_config_path", return_value=config_file):
            report = await execute_inspection()
        
        assert len(report.log_critical_events) == 1
        assert report.affected_devices == ["192.168.1.1"]
