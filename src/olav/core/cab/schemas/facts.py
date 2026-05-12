"""FactsEnvelope — typed container for inspector outputs.

Embedded in `DraftChangePlan.facts_collected`. Replaces the free-text
`facts_cited: list[str]` of the old submit_change_plan API — by being
schema-enforced, an empty draft is a ValidationError at construct
time rather than a runtime hard-error patched on top.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DeviceFact(BaseModel):
    """Per-device facts grounded from DB (inspect_devices output row)."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1)
    platform: str = Field(min_length=1)
    local_as: int | None = Field(default=None, ge=0)
    loopback: str | None = None
    interfaces: list[str] = Field(default_factory=list)


class TopologyEdge(BaseModel):
    """Bidirectional L2/L3 adjacency between two devices."""

    model_config = ConfigDict(extra="allow")

    source_device: str = Field(min_length=1)
    source_interface: str = Field(min_length=1)
    destination_device: str = Field(min_length=1)
    destination_interface: str = Field(min_length=1)
    discovery_protocol: str | None = None


class FactsEnvelope(BaseModel):
    """Typed envelope for everything the Analyzer's inspectors gathered.

    Required: at least one device. Topology edges may be empty when the
    relevant change doesn't depend on adjacency (e.g. vlan_add on one
    switch). Per-intent feasibility rules read what they need from
    this envelope.
    """

    model_config = ConfigDict(extra="allow")

    devices: list[DeviceFact] = Field(min_length=1)
    topology_edges: list[TopologyEdge] = Field(default_factory=list)
    # Optional per-inspector outputs; per-intent rules pick what they need.
    routing_state: dict = Field(default_factory=dict)
    blast_radius: dict = Field(default_factory=dict)
