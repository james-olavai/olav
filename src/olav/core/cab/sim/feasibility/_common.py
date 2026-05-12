"""Shared helpers for per-intent feasibility checks.

Kept narrow and dependency-free so each ``check()`` is just orchestration.
"""
from __future__ import annotations

from olav.core.cab.schemas import Blocker, DeviceFact, FactsEnvelope, TopologyEdge


def device_index(facts: FactsEnvelope) -> dict[str, DeviceFact]:
    """Map device name → DeviceFact for O(1) lookup."""
    return {d.name: d for d in facts.devices}


def edge_pairs(facts: FactsEnvelope) -> set[frozenset[str]]:
    """Set of unordered {a, b} pairs from topology_edges.

    Direct L2 adjacency check is direction-agnostic — an edge stored
    R3→R2 means R2 and R3 are connected.
    """
    return {
        frozenset({e.source_device, e.destination_device})
        for e in facts.topology_edges
    }


def missing_facts_blocker(scope: list[str], idx: dict[str, DeviceFact]) -> Blocker | None:
    missing = [d for d in scope if d not in idx]
    if not missing:
        return None
    return Blocker(
        code="missing_facts",
        message=(
            f"devices {missing} are in scope but not in "
            f"facts_collected.devices. The Analyzer must call "
            f"inspect_devices for every device before submitting."
        ),
        evidence={"missing_devices": missing, "facts_devices": list(idx.keys())},
    )
