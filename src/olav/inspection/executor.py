"""Unified Inspection Executor.

This module provides the main entry point for network inspections.
It reads the unified config/inspections/inspection.yaml and executes
both log analysis and device health checks.

Usage:
    from olav.inspection import execute_inspection
    
    result = await execute_inspection()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from config.settings import get_path

logger = logging.getLogger(__name__)


# Default inspection config filename
INSPECTION_CONFIG = "inspection.yaml"


@dataclass
class LogEvent:
    """A log event from OpenSearch."""
    timestamp: str
    device_ip: str
    severity: str
    message: str


@dataclass
class DeviceCheckResult:
    """Result of a device health check."""
    device: str
    check_name: str
    success: bool
    severity: str = "info"
    message: str = ""
    error: str | None = None


@dataclass
class InspectionReport:
    """Complete inspection report combining log analysis and device checks."""
    
    # Metadata
    name: str
    generated_at: str
    time_range: str
    
    # Log analysis results
    log_critical_events: list[dict[str, Any]] = field(default_factory=list)
    log_warning_events: list[dict[str, Any]] = field(default_factory=list)
    affected_devices: list[str] = field(default_factory=list)
    
    # Device check results
    device_check_results: list[DeviceCheckResult] = field(default_factory=list)
    critical_violations: list[DeviceCheckResult] = field(default_factory=list)
    warning_violations: list[DeviceCheckResult] = field(default_factory=list)
    
    # Summary
    total_devices: int = 0
    devices_passed: int = 0
    devices_failed: int = 0
    
    # Suggestions
    suggested_commands: list[str] = field(default_factory=list)
    
    @property
    def passed_count(self) -> int:
        """Count of passed device checks."""
        return len([r for r in self.device_check_results if r.success])
    
    @property
    def failed_count(self) -> int:
        """Count of failed device checks."""
        return len([r for r in self.device_check_results if not r.success])
    
    @property
    def total_checks(self) -> int:
        """Total number of device checks."""
        return len(self.device_check_results)
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            f"# {self.name}",
            "",
            f"**Generated**: {self.generated_at}",
            f"**Time Range**: {self.time_range}",
            "",
        ]
        
        # Log Analysis Section
        if self.log_critical_events or self.log_warning_events:
            lines.append("## Log Analysis")
            lines.append("")
            
            if self.log_critical_events:
                lines.append(f"### Critical Events ({len(self.log_critical_events)})")
                for event in self.log_critical_events[:10]:
                    lines.append(f"- **{event.get('device_ip', 'unknown')}**: {event.get('message', '')[:100]}")
                lines.append("")
            
            if self.log_warning_events:
                lines.append(f"### Warning Events ({len(self.log_warning_events)})")
                for event in self.log_warning_events[:10]:
                    lines.append(f"- **{event.get('device_ip', 'unknown')}**: {event.get('message', '')[:100]}")
                lines.append("")
        
        # Device Check Section
        if self.device_check_results:
            lines.append("## Device Health Checks")
            lines.append("")
            lines.append(f"- **Total Devices**: {self.total_devices}")
            lines.append(f"- **Passed**: {self.devices_passed}")
            lines.append(f"- **Failed**: {self.devices_failed}")
            lines.append("")
            
            if self.critical_violations:
                lines.append(f"### Critical Violations ({len(self.critical_violations)})")
                for v in self.critical_violations[:10]:
                    lines.append(f"- **{v.device}** - {v.check_name}: {v.message}")
                lines.append("")
            
            if self.warning_violations:
                lines.append(f"### Warnings ({len(self.warning_violations)})")
                for v in self.warning_violations[:10]:
                    lines.append(f"- **{v.device}** - {v.check_name}: {v.message}")
                lines.append("")
        
        # Suggestions
        if self.suggested_commands:
            lines.append("## Suggested Commands")
            lines.append("")
            for cmd in self.suggested_commands:
                lines.append(f"```\n{cmd}\n```")
            lines.append("")
        
        return "\n".join(lines)


def get_inspection_config_path() -> Path:
    """Get the path to the unified inspection config."""
    return Path(get_path("inspections")) / INSPECTION_CONFIG


def load_inspection_config() -> dict[str, Any]:
    """Load the unified inspection configuration.
    
    Returns:
        Parsed YAML config dict.
        
    Raises:
        FileNotFoundError: If inspection.yaml doesn't exist.
        ValueError: If config is invalid.
    """
    config_path = get_inspection_config_path()
    
    if not config_path.exists():
        raise FileNotFoundError(f"Inspection config not found: {config_path}")
    
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"Failed to parse inspection config: {e}") from e
    
    if not config:
        raise ValueError(f"Empty or invalid config: {config_path}")
    
    return config


async def execute_log_analysis(config: dict[str, Any]) -> tuple[list[dict], list[dict], list[str]]:
    """Execute log analysis stage.
    
    Args:
        config: The log_analysis section of the config.
        
    Returns:
        Tuple of (critical_events, warning_events, affected_devices)
    """
    if not config.get("enabled", True):
        logger.info("Log analysis disabled, skipping")
        return [], [], []
    
    from olav.core.memory import create_opensearch_client
    
    index = config.get("index", "syslog-raw")
    time_range = config.get("time_range", "24h")
    keywords = config.get("keywords", {})
    
    critical_keywords = keywords.get("critical", [])
    warning_keywords = keywords.get("warning", [])
    
    critical_events: list[dict] = []
    warning_events: list[dict] = []
    affected_devices: set[str] = set()
    
    try:
        client = create_opensearch_client()
        
        # Search for critical events
        if critical_keywords:
            query = {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": f"now-{time_range}"}}},
                        {"bool": {"should": [
                            {"regexp": {"message": kw}} if ".*" in kw 
                            else {"match_phrase": {"message": kw}}
                            for kw in critical_keywords
                        ]}}
                    ]
                }
            }
            
            response = client.search(
                index=index,
                body={"query": query, "size": 100, "sort": [{"@timestamp": "desc"}]},
            )
            
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                critical_events.append({
                    "timestamp": source.get("@timestamp", ""),
                    "device_ip": source.get("host", source.get("device_ip", "unknown")),
                    "message": source.get("message", ""),
                    "severity": "critical",
                })
                affected_devices.add(source.get("host", source.get("device_ip", "unknown")))
        
        # Search for warning events
        if warning_keywords:
            query = {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": f"now-{time_range}"}}},
                        {"bool": {"should": [
                            {"regexp": {"message": kw}} if ".*" in kw 
                            else {"match_phrase": {"message": kw}}
                            for kw in warning_keywords
                        ]}}
                    ]
                }
            }
            
            response = client.search(
                index=index,
                body={"query": query, "size": 100, "sort": [{"@timestamp": "desc"}]},
            )
            
            for hit in response.get("hits", {}).get("hits", []):
                source = hit.get("_source", {})
                warning_events.append({
                    "timestamp": source.get("@timestamp", ""),
                    "device_ip": source.get("host", source.get("device_ip", "unknown")),
                    "message": source.get("message", ""),
                    "severity": "warning",
                })
                affected_devices.add(source.get("host", source.get("device_ip", "unknown")))
                
    except Exception as e:
        logger.warning(f"Log analysis failed: {e}")
    
    return critical_events, warning_events, list(affected_devices)


async def execute_device_checks(config: dict[str, Any]) -> list[DeviceCheckResult]:
    """Execute device health checks.
    
    Args:
        config: The device_checks section of the config.
        
    Returns:
        List of DeviceCheckResult.
    """
    if not config.get("enabled", True):
        logger.info("Device checks disabled, skipping")
        return []
    
    checks = config.get("checks", [])
    if not checks:
        return []
    
    try:
        # Note: Full implementation requires controller refactoring
        # For now, log the configured checks
        logger.info(f"Device checks configured: {len(checks)} checks")
        return []
    except Exception as e:
        logger.warning(f"Device checks failed: {e}")
        return []


async def execute_inspection(
    job_id: str | None = None,
    hours: int | None = None,
) -> InspectionReport:
    """Execute the unified network inspection.
    
    This is the main entry point for running inspections.
    It loads config/inspections/inspection.yaml and executes
    both log analysis and device health checks.
    
    Args:
        job_id: Optional job ID for progress tracking.
        hours: Override time range in hours.
        
    Returns:
        InspectionReport with combined results.
        
    Example:
        report = await execute_inspection()
        print(report.to_markdown())
    """
    config = load_inspection_config()
    
    name = config.get("name", "Network Inspection")
    log_config = config.get("log_analysis", {})
    device_config = config.get("device_checks", {})
    
    # Override time range if specified
    if hours and log_config:
        log_config["time_range"] = f"{hours}h"
    
    time_range = log_config.get("time_range", "24h") if log_config else "24h"
    
    logger.info(f"Starting inspection: {name}")
    
    # Execute log analysis
    critical_events, warning_events, affected_devices = await execute_log_analysis(log_config)
    
    # Execute device checks
    device_results = await execute_device_checks(device_config)
    
    # Build report
    report = InspectionReport(
        name=config.get("output", {}).get("title", "Network Inspection Report"),
        generated_at=datetime.now(UTC).isoformat(),
        time_range=time_range,
        log_critical_events=critical_events,
        log_warning_events=warning_events,
        affected_devices=affected_devices,
        device_check_results=device_results,
        critical_violations=[r for r in device_results if r.severity == "critical" and not r.success],
        warning_violations=[r for r in device_results if r.severity == "warning" and not r.success],
    )
    
    # Generate suggested commands based on findings
    if affected_devices:
        for device in affected_devices[:5]:
            report.suggested_commands.append(f"olav expert \"Diagnose issues on {device}\"")
    
    logger.info(f"Inspection complete: {len(critical_events)} critical, {len(warning_events)} warning events")
    
    return report


def get_schedule_config() -> dict[str, Any] | None:
    """Get schedule configuration from inspection.yaml.
    
    Returns:
        Schedule config dict or None if not configured.
    """
    try:
        config = load_inspection_config()
        schedule = config.get("schedule", {})
        if schedule.get("enabled", False):
            return schedule
        return None
    except Exception as e:
        logger.warning(f"Failed to load schedule config: {e}")
        return None


__all__ = [
    "execute_inspection",
    "load_inspection_config",
    "get_inspection_config_path",
    "get_schedule_config",
    "InspectionReport",
    "DeviceCheckResult",
    "LogEvent",
    "INSPECTION_CONFIG",
]
