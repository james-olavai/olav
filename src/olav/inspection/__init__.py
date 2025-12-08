"""OLAV Inspection Package.

This package provides unified inspection execution for network health audits.
Configuration is read from config/inspections/inspection.yaml.

Usage:
    from olav.inspection import execute_inspection
    
    # Run the unified inspection
    report = await execute_inspection()
    print(report.to_markdown())
    
    # Override time range
    report = await execute_inspection(hours=48)
"""

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

__all__ = [
    # Main entry point
    "execute_inspection",
    # Config utilities
    "load_inspection_config",
    "get_inspection_config_path",
    "get_schedule_config",
    "INSPECTION_CONFIG",
    # Data classes
    "InspectionReport",
    "DeviceCheckResult",
    "LogEvent",
]
