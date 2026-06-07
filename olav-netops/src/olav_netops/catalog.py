"""Catalog topics registered for the ``olav.catalog_topics`` entry-point.

The olav platform's `olav catalog` CLI aggregates topics from every
domain package via this entry-point group (ADR-0002 — core stays
domain-agnostic). olav-netops contributes the network-ops view here.
"""

from __future__ import annotations

from typing import Any


def get_catalog_topics() -> dict[str, list[dict[str, Any]]]:
    """Return netops catalog topics for ``olav catalog``.

    Structure::

        {
            "<Topic Label>": [
                {"fqname": "<schema.table>",
                 "summary": "<one-line description>",
                 "example": "<example SQL>"},
                ...
            ],
            ...
        }
    """
    return {
        "Device Inventory": [
            {
                "fqname": "netops.devices",
                "summary": "Network devices — hostname, platform, vendor, management IP, model, OS",
                "example": "SELECT hostname, platform, vendor, site FROM netops.devices;",
            },
        ],
        "Routing & Peering": [
            {
                "fqname": "netops.v_bgp_neighbors_auto",
                "summary": "BGP sessions (canonical state across vendors)",
                "example": "SELECT * FROM netops.v_bgp_neighbors_auto WHERE state != 'Established';",
            },
            {
                "fqname": "netops.v_ospf_neighbors_auto",
                "summary": "OSPF adjacencies (vendor role suffixes preserved for Cisco)",
                "example": "SELECT * FROM netops.v_ospf_neighbors_auto;",
            },
        ],
        "Topology": [
            {
                "fqname": "netops.topology_links",
                "summary": "CDP/LLDP/user-declared-protocol adjacencies",
                "example": "SELECT source_device, source_interface, destination_device, "
                           "destination_interface, discovery_protocol "
                           "FROM netops.topology_links;",
            },
            {
                "fqname": "netops.v_l2_links_auto",
                "summary": "L2 topology projection from topology_links",
                "example": "SELECT * FROM netops.v_l2_links_auto;",
            },
        ],
        "Raw Captures": [
            {
                "fqname": "netops.parsed_outputs",
                "summary": "TextFSM/PaC-parsed CLI output per (device, command, snapshot)",
                "example": "SELECT DISTINCT snapshot_id FROM netops.parsed_outputs "
                           "ORDER BY snapshot_id DESC LIMIT 5;",
            },
            {
                "fqname": "netops.raw_output_store",
                "summary": "Latest raw CLI output per (device, command) — parse-fail fallback",
                "example": "SELECT device_name, command FROM netops.raw_output_store LIMIT 10;",
            },
        ],
        "Recipes & Views": [
            {
                "fqname": "main.view_recipes",
                "summary": "Concept→raw field mappings that drive the v_*_auto views",
                "example": "SELECT command, concept, vendor_hint FROM view_recipes;",
            },
        ],
    }
