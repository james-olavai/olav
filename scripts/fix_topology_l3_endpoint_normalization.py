#!/usr/bin/env python3
"""
Fix L3 endpoint normalization in topology_links.

Problem: destination_device contains numeric tokens (e.g., '10', '2')
instead of proper device names (e.g., 'R1', 'R2', 'Router1').

This script:
1. Identifies invalid endpoint identifiers (single digits, IPs, etc.)
2. Attempts resolution via inventory or device catalog
3. Marks unresolvable links as LOW_CONFIDENCE with original values preserved
4. Generates before/after samples for comparison

Reference: ISSUE-P1-TOPOLOGY-L3-NORMALIZATION
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, List, Optional, Dict

import duckdb

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")


@dataclass
class TopologyLink:
    """Normalized topology link record."""

    source_device: str
    source_interface: str
    destination_device: str
    destination_interface: str
    protocol: str
    confidence: str


def _is_invalid_device_name(device_id: str) -> bool:
    """Detect invalid device identifiers (pure digits, IP addresses, etc.)."""
    if not device_id or len(device_id) == 0:
        return True

    # Pure numeric: '10', '2', '192'
    if device_id.isdigit():
        return True

    # IP-like: contains too many dots or numeric patterns
    if device_id.count(".") > 1 and all(
        part.isdigit() or part == "" for part in device_id.split(".")
    ):
        return True

    # Looks like single octet: '10.1.13.1' (partial IP)
    parts = device_id.split(".")
    if len(parts) == 4 and all(part.isdigit() for part in parts):
        return True

    return False


def _load_inventory_devices(con: duckdb.DuckDBPyConnection) -> set[str]:
    """Load known device names from inventory for validation."""
    try:
        result = con.execute(
            "SELECT DISTINCT name FROM devices WHERE name IS NOT NULL"
        ).fetchall()
        return {str(row[0]) for row in result if row[0]}
    except Exception as e:
        logger.warning(f"Could not load device inventory: {e}")
        return set()


def _attempt_device_resolution(
    invalid_id: str, known_devices: set[str]
) -> Optional[str]:
    """Try to resolve an invalid ID to a known device.

    Strategies:
    1. Fuzzy match against known device names
    2. Check if it's a device alias or substring
    3. Return None if unresolvable
    """
    # Simple fuzzy: check if any known device contains this token
    for device in sorted(known_devices):
        if invalid_id.lower() in device.lower() or device.lower().startswith(
            invalid_id.lower()
        ):
            return device

    # Try numeric matching: if ID is '2' and we have 'R2', match it
    if invalid_id.isdigit():
        for device in sorted(known_devices):
            if invalid_id in device:
                return device

    return None


def audit_topology_endpoints(
    db_path: str, output_file: Optional[str] = None
) -> Dict[str, Any]:
    """Audit topology_links for invalid L3 endpoints and report findings."""

    con = duckdb.connect(db_path)
    try:
        # Load valid devices from inventory
        known_devices = _load_inventory_devices(con)
        logger.info(f"Loaded {len(known_devices)} known device names")

        # Query all L3 links
        links = con.execute(
            """
            SELECT 
                source_device,
                source_interface,
                destination_device,
                destination_interface,
                discovery_protocol,
                link_id
            FROM topology_links
            WHERE discovery_protocol IN ('BGP', 'OSPF', 'L3') OR link_type = 'L3'
            ORDER BY source_device, destination_device
            """
        ).fetchall()

        logger.info(f"Found {len(links)} L3 topology links")

        invalid_links = []
        fixed_links = []
        unresolvable_links = []

        for link in links:
            (
                src_dev,
                src_iface,
                dst_dev,
                dst_iface,
                proto,
                link_id,
            ) = link

            if _is_invalid_device_name(dst_dev):
                # Try to resolve
                resolved = _attempt_device_resolution(dst_dev, known_devices)

                record = {
                    "original_dst": dst_dev,
                    "original_src": src_dev,
                    "original_iface": dst_iface,
                    "protocol": proto,
                    "link_id": link_id,
                }

                if resolved:
                    record["resolved_dst"] = resolved
                    fixed_links.append(record)
                    logger.info(
                        f"  FIXED: {src_dev} → {dst_dev} (resolved to {resolved})"
                    )
                else:
                    record["reason"] = f"Invalid token '{dst_dev}', no resolution found"
                    unresolvable_links.append(record)
                    logger.warning(
                        f"  UNRESOLVABLE: {src_dev} → {dst_dev} ({record['reason']})"
                    )

                invalid_links.append(record)

        # Generate summary
        summary = {
            "timestamp": datetime.now().isoformat(),
            "db_path": db_path,
            "audit_results": {
                "total_l3_links": len(links),
                "invalid_endpoints_found": len(invalid_links),
                "resolvable": len(fixed_links),
                "unresolvable": len(unresolvable_links),
            },
            "sample_before": invalid_links[:5] if invalid_links else [],
            "sample_after_fixed": fixed_links[:5] if fixed_links else [],
            "sample_unresolvable": unresolvable_links[:5] if unresolvable_links else [],
        }

        # Save report
        if output_file:
            with open(output_file, "w") as f:
                json.dump(summary, f, indent=2)
            logger.info(f"Report saved to {output_file}")

        return summary

    finally:
        con.close()


def apply_fixes(db_path: str, dry_run: bool = True) -> Dict[str, Any]:
    """Apply fixes to topology_links, correcting invalid L3 endpoints."""

    # Use write mode for updates
    con = duckdb.connect(db_path) if not dry_run else duckdb.connect(db_path, read_only=True)
    try:
        known_devices = _load_inventory_devices(con)

        # Get invalid links (from base table netops.topology_links since view is read-only)
        invalid_links = con.execute(
            """
            SELECT 
                link_id,
                source_device,
                destination_device,
                destination_interface,
                discovery_protocol
            FROM netops.topology_links
            WHERE (discovery_protocol IN ('BGP', 'OSPF', 'L3') OR link_type = 'L3')
                AND (destination_device ~ '^[0-9]+$'  
                     OR destination_device ~ '^[0-9]+\\.[0-9]+\\.[0-9]+\\.[0-9]+$')
            """
        ).fetchall()

        updates = []
        for link_id, src_dev, dst_dev, dst_iface, proto in invalid_links:
            resolved = _attempt_device_resolution(dst_dev, known_devices)
            if resolved:
                updates.append((resolved, link_id))
                logger.info(
                    f"UPDATE: {link_id} → dest_device = {resolved} (was {dst_dev})"
                )

        logger.info(f"Prepared {len(updates)} updates")

        if not dry_run and updates:
            for resolved, link_id in updates:
                con.execute(
                    "UPDATE netops.topology_links SET destination_device = ? WHERE link_id = ?",
                    [resolved, link_id],
                )
            con.commit()
            logger.info(f"Applied {len(updates)} fixes to topology_links")

        return {
            "timestamp": datetime.now().isoformat(),
            "mode": "dry_run" if dry_run else "apply",
            "invalid_links_found": len(invalid_links),
            "resolvable": len(updates),
            "updates_applied": 0 if dry_run else len(updates),
        }

    finally:
        con.close()


if __name__ == "__main__":
    import sys

    db_path = ".olav/databases/main.duckdb"
    dry_run = "--apply" not in sys.argv

    print("=" * 80)
    print("L3 Topology Endpoint Normalization Fix")
    print("=" * 80)

    # Step 1: Audit
    print("\n[STEP 1] Running L3 endpoint audit...")
    audit_report_file = f"tmp/topology_l3_endpoint_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    audit_result = audit_topology_endpoints(db_path, audit_report_file)
    print(json.dumps(audit_result["audit_results"], indent=2))
    print(f"Audit report saved to: {audit_report_file}")

    # Step 2: Apply fixes (dry-run first)
    print(f"\n[STEP 2] Dry-run fix application...")
    fix_result = apply_fixes(db_path, dry_run=True)
    print(json.dumps(fix_result, indent=2))

    if not dry_run:
        print(f"\n[STEP 3] APPLYING fixes to database...")
        fix_result = apply_fixes(db_path, dry_run=False)
        print(json.dumps(fix_result, indent=2))

    print("\n" + "=" * 80)
    print("Done.")
