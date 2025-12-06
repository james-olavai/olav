"""Inspection Mode - YAML-driven batch network inspections.

Architecture:
    YAML Config → Controller → BatchExecutor → ReportGenerator

Components:
    - InspectionModeController: Orchestrates YAML-driven inspections
    - InspectionConfig: Pydantic models for YAML config
    - CheckResult/InspectionResult: Result data classes

Capabilities:
    - YAML-driven inspection profiles
    - NetBox device scope resolution
    - Parallel batch execution
    - Threshold-based validation
    - Markdown report generation

Usage:
    from olav.modes.inspection import InspectionModeController, run_inspection
    
    # From YAML config
    result = await run_inspection("config/inspections/daily_core_check.yaml")
    print(result.to_markdown())
"""

from olav.modes.inspection.controller import (
    InspectionModeController,
    InspectionConfig,
    CheckConfig,
    ThresholdConfig,
    DeviceFilter,
    CheckResult,
    InspectionResult,
    run_inspection,
)

__all__ = [
    "InspectionModeController",
    "InspectionConfig",
    "CheckConfig",
    "ThresholdConfig",
    "DeviceFilter",
    "CheckResult",
    "InspectionResult",
    "run_inspection",
]
