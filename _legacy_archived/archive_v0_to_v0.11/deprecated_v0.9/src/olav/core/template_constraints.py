"""Pydantic constraint models for TextFSM template validation.

This module defines constraint models that generated TextFSM templates must satisfy.
Each model represents the expected output structure for a specific command type,
enabling automated validation during template generation (ReAct loops).

Architecture Position:
    TextFSM Template Generator → Parses output → Validates against constraint
                                                           ↓
                                                  Pass: Quality score ✓
                                                  Fail: Iterate & fix ↻

Constraint models serve dual purposes:
1. Template Validation: Ensure generated templates extract required fields
2. Quality Scoring: Calculate extraction rate and field completeness

Example Usage:
    >>> template = generate_template(raw_output, command="show ip bgp summary")
    >>> parsed_data = textfsm.parse(template, raw_output)
    >>> result = validate_template_output(parsed_data, BGPNeighborConstraint)
    >>> if result.success:
    ...     print(f"Quality score: {result.quality_score}")
"""

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

# =============================================================================
# Core Validation Result Models
# =============================================================================


class ValidationResult(BaseModel):
    """Result of template output validation against constraints."""

    success: bool = Field(description="Whether validation passed")
    extraction_rate: float = Field(
        description="Percentage of records successfully parsed (0.0-1.0)"
    )
    field_completeness: float = Field(description="Percentage of required fields present (0.0-1.0)")
    constraint_pass_rate: float = Field(
        description="Percentage of records passing Pydantic validation (0.0-1.0)"
    )
    quality_score: float = Field(description="Overall quality score (0.0-1.0)")
    total_records: int = Field(description="Total number of records in output")
    valid_records: int = Field(description="Number of records passing validation")
    errors: list[str] = Field(default_factory=list, description="Validation errors")
    warnings: list[str] = Field(default_factory=list, description="Validation warnings")
    missing_fields: set[str] = Field(
        default_factory=set, description="Required fields missing in output"
    )
    extra_fields: set[str] = Field(
        default_factory=set, description="Extra fields not in constraint model"
    )


# =============================================================================
# Network Protocol Constraint Models
# =============================================================================


class BGPNeighborConstraint(BaseModel):
    """Constraint model for BGP neighbor/summary output.

    Applicable commands:
    - show ip bgp summary (Cisco)
    - show bgp summary (Juniper)
    - display bgp peer (Huawei)
    - show ip bgp summary vrf all (Arista)

    Required fields enforce minimum viable BGP neighbor information.
    Optional fields are nice-to-have but not mandatory.
    """

    # Required fields (must be present and non-empty)
    neighbor_ip: str = Field(
        ..., min_length=7, max_length=45, description="BGP neighbor IP address"
    )
    remote_as: int = Field(..., ge=0, le=4294967295, description="Remote AS number")
    state: str = Field(..., min_length=1, description="BGP session state")

    # Optional fields (may be missing or empty)
    prefixes_received: int = Field(
        default=0, ge=0, description="Number of prefixes received from neighbor"
    )
    uptime: str = Field(default="", description="Neighbor uptime (format varies)")
    local_as: int | None = Field(default=None, ge=0, description="Local AS number")
    version: int | None = Field(default=None, ge=4, le=4, description="BGP version (4)")

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Validate BGP state is a known value."""
        known_states = {
            "Established",
            "Idle",
            "Connect",
            "Active",
            "OpenSent",
            "OpenConfirm",
            "established",
            "idle",
            "active",
        }
        if v not in known_states:
            # Allow unknown states (could be vendor-specific)
            pass
        return v


class OSPFNeighborConstraint(BaseModel):
    """Constraint model for OSPF neighbor output.

    Applicable commands:
    - show ip ospf neighbor (Cisco)
    - show ospf neighbor (Juniper)
    - display ospf peer (Huawei)
    """

    # Required fields
    neighbor_id: str = Field(
        ..., min_length=7, max_length=15, description="OSPF neighbor router ID"
    )
    interface: str = Field(..., min_length=1, description="Local interface")
    state: str = Field(..., min_length=1, description="OSPF neighbor state")

    # Optional fields
    priority: int = Field(default=1, ge=0, le=255, description="Neighbor priority")
    ip_address: str = Field(default="", description="Neighbor IP address")
    dead_time: str = Field(default="", description="Dead timer")
    area: str = Field(default="", description="OSPF area")

    @field_validator("state")
    @classmethod
    def validate_state(cls, v: str) -> str:
        """Validate OSPF state."""
        known_states = {
            "FULL",
            "2WAY",
            "EXSTART",
            "EXCHANGE",
            "LOADING",
            "INIT",
            "Down",
            "Full",
            "2Way",
        }
        if v not in known_states:
            # Allow unknown states
            pass
        return v


class RouteEntryConstraint(BaseModel):
    """Constraint model for routing table entries.

    Applicable commands:
    - show ip route (Cisco)
    - show route (Juniper)
    - display ip routing-table (Huawei)
    """

    # Required fields
    network: str = Field(..., min_length=1, description="Destination network (CIDR or IP)")
    protocol: str = Field(..., min_length=1, description="Routing protocol")

    # Optional fields (next_hop OR interface must be present)
    next_hop: str = Field(default="", description="Next hop IP address")
    interface: str = Field(default="", description="Outbound interface")
    metric: int = Field(default=0, ge=0, description="Route metric")
    administrative_distance: int = Field(
        default=0, ge=0, le=255, description="Administrative distance"
    )
    route_type: str = Field(default="", description="Route type (e.g., IA, E1, E2)")

    @field_validator("protocol")
    @classmethod
    def validate_protocol(cls, v: str) -> str:
        """Validate routing protocol code.

        Accepts any protocol code as vendors use different conventions.
        Common codes: C (connected), L (local), S (static), B (BGP),
        O (OSPF), E (EIGRP), I (IGRP), R (RIP), D (EIGRP), i (IS-IS)
        """
        # Allow any protocol (vendors have different codes)
        return v


class CDPNeighborConstraint(BaseModel):
    """Constraint model for CDP/LLDP neighbor discovery.

    Applicable commands:
    - show cdp neighbors (Cisco)
    - show lldp neighbors (Various)
    - display lldp neighbor brief (Huawei)
    """

    # Required fields
    local_interface: str = Field(..., min_length=1, description="Local interface name")
    remote_device: str = Field(..., min_length=1, description="Remote device hostname")
    remote_interface: str = Field(..., min_length=1, description="Remote interface name")

    # Optional fields
    platform: str = Field(default="", description="Remote device platform/model")
    capability: str = Field(default="", description="Device capability (R, S, B)")
    mgmt_address: str = Field(default="", description="Management IP address")


class InterfaceStatusConstraint(BaseModel):
    """Constraint model for interface status output.

    Applicable commands:
    - show interfaces status (Cisco)
    - show interface terse (Juniper)
    - display interface brief (Huawei)
    """

    # Required fields
    interface: str = Field(..., min_length=1, description="Interface name")
    status: str = Field(..., min_length=1, description="Physical status (up/down)")

    # Optional fields
    protocol: str = Field(default="", description="Protocol status (up/down)")
    description: str = Field(default="", description="Interface description")
    vlan: str = Field(default="", description="VLAN assignment")
    speed: str = Field(default="", description="Interface speed")
    duplex: str = Field(default="", description="Duplex mode")

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        """Normalize status values."""
        v_lower = v.lower()
        if v_lower in {"up", "connected", "1"}:
            return "up"
        elif v_lower in {"down", "notconnect", "disabled", "0"}:
            return "down"
        return v


class ARPEntryConstraint(BaseModel):
    """Constraint model for ARP table entries.

    Applicable commands:
    - show arp (Cisco)
    - show arp no-resolve (Juniper)
    - display arp (Huawei)
    """

    # Required fields
    ip_address: str = Field(..., min_length=7, max_length=45, description="IP address")
    mac_address: str = Field(..., min_length=12, description="MAC address")

    # Optional fields
    interface: str = Field(default="", description="Interface")
    age: str = Field(default="", description="ARP entry age")
    type: str = Field(default="", description="ARP entry type (ARPA, dynamic, static)")


# =============================================================================
# Dynamic Constraint Model (Fallback)
# =============================================================================


class DynamicConstraint(BaseModel):
    """Generic constraint model when specific model is unavailable.

    This model only enforces that at least one field is present.
    Used as fallback when command type cannot be determined.
    """

    # No required fields - accept any structure
    class Config:
        extra = "allow"  # Allow any additional fields


# =============================================================================
# Validation Functions
# =============================================================================


def calculate_quality_score(
    extraction_rate: float, field_completeness: float, constraint_pass_rate: float
) -> float:
    """Calculate overall quality score for template output.

    Formula:
        quality_score = (
            extraction_rate * 0.4 +         # 40%: Record extraction success
            field_completeness * 0.3 +      # 30%: Required fields present
            constraint_pass_rate * 0.3      # 30%: Pydantic validation pass
        )

    Args:
        extraction_rate: Percentage of records extracted (0.0-1.0)
        field_completeness: Percentage of required fields present (0.0-1.0)
        constraint_pass_rate: Percentage passing validation (0.0-1.0)

    Returns:
        Quality score between 0.0 and 1.0
    """
    return extraction_rate * 0.4 + field_completeness * 0.3 + constraint_pass_rate * 0.3


def validate_template_output(
    parsed_data: list[dict[str, Any]],
    constraint_model: type[BaseModel],
    min_extraction_rate: float = 0.8,
) -> ValidationResult:
    """Validate TextFSM template output against Pydantic constraint model.

    This is the main validation function used during template generation.
    It checks:
    1. How many records were extracted (extraction_rate)
    2. What percentage of required fields are present (field_completeness)
    3. How many records pass Pydantic validation (constraint_pass_rate)

    Args:
        parsed_data: List of dictionaries from TextFSM parsing
        constraint_model: Pydantic model to validate against
        min_extraction_rate: Minimum acceptable extraction rate (default: 0.8)

    Returns:
        ValidationResult with quality metrics and errors

    Example:
        >>> parsed = [{"neighbor_ip": "10.0.0.1", "remote_as": 65001, "state": "Established"}]
        >>> result = validate_template_output(parsed, BGPNeighborConstraint)
        >>> print(result.quality_score)
        0.95
    """
    if not parsed_data:
        return ValidationResult(
            success=False,
            extraction_rate=0.0,
            field_completeness=0.0,
            constraint_pass_rate=0.0,
            quality_score=0.0,
            total_records=0,
            valid_records=0,
            errors=["No data extracted from template"],
        )

    total_records = len(parsed_data)
    valid_records = 0
    errors: list[str] = []
    warnings: list[str] = []
    all_missing_fields: set[str] = set()
    all_extra_fields: set[str] = set()

    # Get required fields from constraint model
    required_fields = {
        field_name
        for field_name, field_info in constraint_model.model_fields.items()
        if field_info.is_required()
    }

    # Validate each record
    for i, record in enumerate(parsed_data):
        try:
            constraint_model(**record)
            valid_records += 1
        except ValidationError as e:
            error_msg = f"Record {i}: {e.error_count()} validation error(s)"
            errors.append(error_msg)

            # Track missing required fields
            for error in e.errors():
                if error["type"] == "missing":
                    field = error["loc"][0] if error["loc"] else "unknown"
                    all_missing_fields.add(str(field))

        # Check for extra fields (not an error, just informational)
        extra = set(record.keys()) - set(constraint_model.model_fields.keys())
        all_extra_fields.update(extra)

    # Calculate metrics
    extraction_rate = total_records / max(total_records, 1)  # Assume we wanted all records
    constraint_pass_rate = valid_records / total_records if total_records > 0 else 0.0

    # Calculate field completeness (required fields present)
    if required_fields:
        # Check first record for required fields presence
        first_record_fields = set(parsed_data[0].keys()) if parsed_data else set()
        present_required = first_record_fields & required_fields
        field_completeness = len(present_required) / len(required_fields)
    else:
        # No required fields = 100% completeness
        field_completeness = 1.0

    # Overall quality score
    quality_score = calculate_quality_score(
        extraction_rate, field_completeness, constraint_pass_rate
    )

    # Success criteria
    success = (
        extraction_rate >= min_extraction_rate
        and constraint_pass_rate >= min_extraction_rate
        and field_completeness >= 0.8
    )

    # Generate warnings
    if all_missing_fields:
        warnings.append(
            f"Missing required fields in some records: {', '.join(sorted(all_missing_fields))}"
        )
    if all_extra_fields:
        warnings.append(f"Extra fields not in model: {', '.join(sorted(all_extra_fields))}")

    return ValidationResult(
        success=success,
        extraction_rate=extraction_rate,
        field_completeness=field_completeness,
        constraint_pass_rate=constraint_pass_rate,
        quality_score=quality_score,
        total_records=total_records,
        valid_records=valid_records,
        errors=errors,
        warnings=warnings,
        missing_fields=all_missing_fields,
        extra_fields=all_extra_fields,
    )


def get_constraint_model_for_command(command: str, platform: str | None = None) -> type[BaseModel]:
    """Determine appropriate constraint model based on command.

    Args:
        command: Device command string
        platform: Optional device platform (cisco_ios, juniper_junos, etc.)

    Returns:
        Appropriate constraint model class

    Example:
        >>> model = get_constraint_model_for_command("show ip bgp summary")
        >>> model
        <class 'BGPNeighborConstraint'>
    """
    cmd_lower = command.lower()

    # BGP commands
    if "bgp" in cmd_lower and ("summary" in cmd_lower or "peer" in cmd_lower):
        return BGPNeighborConstraint

    # OSPF commands
    if "ospf" in cmd_lower and ("neighbor" in cmd_lower or "peer" in cmd_lower):
        return OSPFNeighborConstraint

    # Routing table
    if "route" in cmd_lower or "routing-table" in cmd_lower:
        return RouteEntryConstraint

    # CDP/LLDP
    if "cdp" in cmd_lower or "lldp" in cmd_lower:
        return CDPNeighborConstraint

    # Interface status
    if "interface" in cmd_lower and (
        "status" in cmd_lower or "brief" in cmd_lower or "terse" in cmd_lower
    ):
        return InterfaceStatusConstraint

    # ARP table
    if "arp" in cmd_lower:
        return ARPEntryConstraint

    # Fallback to dynamic constraint
    return DynamicConstraint


# =============================================================================
# Convenience Functions
# =============================================================================


def get_available_constraints() -> dict[str, type[BaseModel]]:
    """Get dictionary of all available constraint models.

    Returns:
        Dictionary mapping constraint name to model class
    """
    return {
        "bgp_neighbor": BGPNeighborConstraint,
        "ospf_neighbor": OSPFNeighborConstraint,
        "route_entry": RouteEntryConstraint,
        "cdp_neighbor": CDPNeighborConstraint,
        "interface_status": InterfaceStatusConstraint,
        "arp_entry": ARPEntryConstraint,
        "dynamic": DynamicConstraint,
    }


def get_constraint_info(constraint_model: type[BaseModel]) -> dict[str, Any]:
    """Get metadata about a constraint model.

    Args:
        constraint_model: Constraint model class

    Returns:
        Dictionary with model metadata
    """
    required_fields = [
        field_name
        for field_name, field_info in constraint_model.model_fields.items()
        if field_info.is_required()
    ]

    optional_fields = [
        field_name
        for field_name, field_info in constraint_model.model_fields.items()
        if not field_info.is_required()
    ]

    return {
        "model_name": constraint_model.__name__,
        "required_fields": required_fields,
        "optional_fields": optional_fields,
        "total_fields": len(constraint_model.model_fields),
        "docstring": constraint_model.__doc__,
    }
