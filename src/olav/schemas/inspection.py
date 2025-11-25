"""
Inspection Configuration Schema - Pydantic models for batch inspection YAML files.

This module defines the schema for declarative batch inspection tasks.
Operators can write YAML files specifying what to check, thresholds,
and expected values across multiple devices.

Example YAML:
```yaml
name: bgp_peer_check
description: Verify BGP peer counts across all routers
devices:
  - R1
  - R2
  - R3
checks:
  - name: bgp_peer_count
    tool: suzieq_query
    parameters:
      table: bgp
      state: Established
    threshold:
      field: count
      operator: ">="
      value: 2
      severity: critical
```
"""

import yaml
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator


class ThresholdRule(BaseModel):
    """
    Threshold rule for validation without LLM.
    
    Pure Python operator logic ensures deterministic, zero-hallucination checks.
    """
    field: str = Field(description="Field name in tool output to check")
    operator: Literal[">", "<", ">=", "<=", "==", "!=", "in", "not_in"] = Field(
        description="Comparison operator"
    )
    value: Union[int, float, str, List[Any]] = Field(
        description="Expected value or threshold"
    )
    severity: Literal["info", "warning", "critical"] = Field(
        default="warning",
        description="Severity level for violations"
    )
    message: Optional[str] = Field(
        default=None,
        description="Custom violation message template (supports {field}, {value}, {actual})"
    )


class CheckTask(BaseModel):
    """
    Single check task to execute on devices.
    
    Specifies what tool to run and what thresholds to validate.
    """
    name: str = Field(description="Unique check identifier")
    description: Optional[str] = Field(
        default=None,
        description="Human-readable description"
    )
    tool: str = Field(description="Tool to execute (suzieq_query, cli_tool, etc.)")
    parameters: Dict[str, Any] = Field(
        default_factory=dict,
        description="Tool-specific parameters"
    )
    threshold: Optional[ThresholdRule] = Field(
        default=None,
        description="Threshold rule for validation"
    )
    thresholds: Optional[List[ThresholdRule]] = Field(
        default=None,
        description="Multiple threshold rules (all must pass)"
    )
    enabled: bool = Field(default=True, description="Whether this check is enabled")
    
    @field_validator("thresholds", mode="before")
    @classmethod
    def validate_thresholds(cls, v, info):
        """Ensure either threshold or thresholds is specified, not both."""
        threshold = info.data.get("threshold")
        if threshold and v:
            raise ValueError("Cannot specify both 'threshold' and 'thresholds'")
        return v
    
    def get_all_thresholds(self) -> List[ThresholdRule]:
        """Get all threshold rules (from either threshold or thresholds)."""
        if self.threshold:
            return [self.threshold]
        elif self.thresholds:
            return self.thresholds
        else:
            return []


class DeviceSelector(BaseModel):
    """
    Device selector for targeting devices in batch inspection.
    
    Supports explicit lists, NetBox filters, or regex patterns.
    """
    explicit: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of device hostnames"
    )
    netbox_filter: Optional[Dict[str, Any]] = Field(
        default=None,
        description="NetBox API filter (e.g., {'role': 'router', 'site': 'DC1'})"
    )
    regex: Optional[str] = Field(
        default=None,
        description="Regex pattern to match device names"
    )
    
    @field_validator("netbox_filter", "regex", mode="before")
    @classmethod
    def validate_selectors(cls, v, info):
        """Ensure only one selector type is used."""
        explicit = info.data.get("explicit")
        netbox_filter = info.data.get("netbox_filter")
        regex = info.data.get("regex")
        
        selectors_set = sum([bool(explicit), bool(netbox_filter), bool(regex)])
        if selectors_set > 1:
            raise ValueError(
                "Cannot specify multiple device selectors (explicit, netbox_filter, regex)"
            )
        
        return v


class InspectionConfig(BaseModel):
    """
    Complete inspection configuration loaded from YAML.
    
    Defines a batch inspection job with devices, checks, and execution settings.
    """
    name: str = Field(description="Inspection job name")
    description: Optional[str] = Field(
        default=None,
        description="Job description"
    )
    devices: Union[List[str], DeviceSelector] = Field(
        description="Devices to inspect (list or selector)"
    )
    checks: List[CheckTask] = Field(
        description="Check tasks to execute",
        min_length=1
    )
    parallel: bool = Field(
        default=True,
        description="Execute checks in parallel across devices"
    )
    max_workers: int = Field(
        default=10,
        description="Max parallel workers (only if parallel=True)"
    )
    stop_on_failure: bool = Field(
        default=False,
        description="Stop inspection if any check fails critically"
    )
    output_format: Literal["json", "yaml", "table", "html"] = Field(
        default="table",
        description="Output report format"
    )
    
    @classmethod
    def from_yaml(cls, yaml_path: Union[str, Path]) -> "InspectionConfig":
        """
        Load inspection config from YAML file.
        
        Args:
            yaml_path: Path to YAML file
            
        Returns:
            InspectionConfig instance
            
        Raises:
            FileNotFoundError: If YAML file doesn't exist
            ValueError: If YAML is invalid or doesn't match schema
        """
        path = Path(yaml_path)
        if not path.exists():
            raise FileNotFoundError(f"Inspection config not found: {yaml_path}")
        
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        if not data:
            raise ValueError(f"Empty YAML file: {yaml_path}")
        
        return cls(**data)
    
    def to_yaml(self, yaml_path: Union[str, Path]):
        """
        Save inspection config to YAML file.
        
        Args:
            yaml_path: Path to save YAML file
        """
        path = Path(yaml_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(path, "w", encoding="utf-8") as f:
            yaml.dump(
                self.model_dump(exclude_none=True),
                f,
                default_flow_style=False,
                allow_unicode=True
            )
    
    def get_enabled_checks(self) -> List[CheckTask]:
        """Get only enabled checks."""
        return [check for check in self.checks if check.enabled]
    
    def get_device_list(self) -> List[str]:
        """
        Get explicit device list.
        
        Note: For DeviceSelector, this requires NetBox/regex resolution
        (handled by BatchPathStrategy).
        
        Returns:
            List of device hostnames
        """
        if isinstance(self.devices, list):
            return self.devices
        else:
            # DeviceSelector requires resolution
            return []


# Example YAML templates

EXAMPLE_BGP_CHECK = """
name: bgp_peer_audit
description: Verify BGP peer counts and states across edge routers
devices:
  explicit:
    - R1
    - R2
    - R3
checks:
  - name: bgp_established_count
    description: Ensure at least 2 BGP peers are Established
    tool: suzieq_query
    parameters:
      table: bgp
      state: Established
    threshold:
      field: count
      operator: ">="
      value: 2
      severity: critical
      message: "Device {device} has only {actual} established BGP peers (expected >= {value})"
  
  - name: bgp_no_idle_peers
    description: No BGP peers should be in Idle state
    tool: suzieq_query
    parameters:
      table: bgp
      state: Idle
    threshold:
      field: count
      operator: "=="
      value: 0
      severity: warning
      message: "Device {device} has {actual} BGP peers in Idle state"

parallel: true
max_workers: 5
stop_on_failure: false
output_format: table
"""

EXAMPLE_INTERFACE_CHECK = """
name: interface_health_check
description: Check interface error rates and utilization
devices:
  netbox_filter:
    role: router
    site: DC1
checks:
  - name: interface_errors
    tool: suzieq_query
    parameters:
      table: interfaces
    thresholds:
      - field: inputErrors
        operator: "<"
        value: 100
        severity: warning
      - field: outputErrors
        operator: "<"
        value: 100
        severity: warning
  
  - name: interface_utilization
    tool: suzieq_query
    parameters:
      table: interfaces
    threshold:
      field: utilization
      operator: "<"
      value: 80
      severity: info
      message: "Interface {field} utilization is {actual}% (threshold: {value}%)"

parallel: true
max_workers: 10
output_format: json
"""
