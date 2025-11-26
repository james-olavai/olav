"""
Test script for NetBox Bidirectional Sync.

Demonstrates:
1. DiffEngine comparing SuzieQ data with NetBox
2. NetBoxReconciler applying corrections
3. Report generation

Run with: uv run python scripts/test_sync.py
"""

import asyncio
import logging
from datetime import datetime

from olav.sync import (
    DiffEngine,
    DiffResult,
    DiffSeverity,
    DiffSource,
    EntityType,
    NetBoxReconciler,
    ReconciliationReport,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_sample_report() -> ReconciliationReport:
    """Create a sample reconciliation report for demo."""
    report = ReconciliationReport(
        timestamp=datetime.now(),
        device_scope=["R1", "R2", "SW1"],
    )
    
    # Add some matches
    for _ in range(45):
        report.add_match()
    
    # Add sample diffs
    diffs = [
        # MTU mismatch - auto-correctable
        DiffResult(
            entity_type=EntityType.INTERFACE,
            device="R1",
            field="GigabitEthernet0/1.mtu",
            network_value=1500,
            netbox_value=9000,
            severity=DiffSeverity.INFO,
            source=DiffSource.SUZIEQ,
            auto_correctable=True,
            netbox_id=123,
            netbox_endpoint="/api/dcim/interfaces/",
        ),
        # Interface missing in NetBox
        DiffResult(
            entity_type=EntityType.INTERFACE,
            device="R1",
            field="existence",
            network_value="GigabitEthernet0/3",
            netbox_value="missing",
            severity=DiffSeverity.WARNING,
            source=DiffSource.SUZIEQ,
            auto_correctable=False,
        ),
        # IP address mismatch
        DiffResult(
            entity_type=EntityType.IP_ADDRESS,
            device="R2",
            field="existence",
            network_value="10.1.1.5/24",
            netbox_value="missing",
            severity=DiffSeverity.WARNING,
            source=DiffSource.SUZIEQ,
            auto_correctable=False,
            additional_context={"interface": "GigabitEthernet0/0"},
        ),
        # Software version mismatch - auto-correctable
        DiffResult(
            entity_type=EntityType.DEVICE,
            device="SW1",
            field="software_version",
            network_value="17.3.2",
            netbox_value="16.12.4",
            severity=DiffSeverity.INFO,
            source=DiffSource.SUZIEQ,
            auto_correctable=True,
            netbox_id=456,
            netbox_endpoint="/api/dcim/devices/",
        ),
        # Interface enabled mismatch - requires HITL
        DiffResult(
            entity_type=EntityType.INTERFACE,
            device="R2",
            field="GigabitEthernet0/2.enabled",
            network_value=False,
            netbox_value=True,
            severity=DiffSeverity.WARNING,
            source=DiffSource.SUZIEQ,
            auto_correctable=False,
            netbox_id=789,
            netbox_endpoint="/api/dcim/interfaces/",
        ),
    ]
    
    for diff in diffs:
        report.add_diff(diff)
    
    # Set totals
    report.missing_in_netbox = 2
    
    return report


async def test_reconciler_dry_run():
    """Test reconciler in dry run mode."""
    print("\n" + "=" * 60)
    print("Testing NetBoxReconciler (Dry Run)")
    print("=" * 60)
    
    report = create_sample_report()
    
    reconciler = NetBoxReconciler(dry_run=True)
    results = await reconciler.reconcile(report, auto_correct=True, require_hitl=True)
    
    print(f"\nProcessed {len(results)} differences:")
    for result in results:
        print(f"  - {result.diff.device}/{result.diff.field}: {result.action.value}")
        print(f"    Message: {result.message}")
    
    print(f"\nStats: {reconciler.get_stats()}")


def test_report_generation():
    """Test report generation."""
    print("\n" + "=" * 60)
    print("Testing Report Generation")
    print("=" * 60)
    
    report = create_sample_report()
    
    print("\n--- JSON Summary ---")
    summary = report.to_dict()
    print(f"Total Entities: {summary['total_entities']}")
    print(f"Matched: {summary['matched']}")
    print(f"Mismatched: {summary['mismatched']}")
    print(f"Missing in NetBox: {summary['missing_in_netbox']}")
    print(f"By Type: {summary['summary_by_type']}")
    print(f"By Severity: {summary['summary_by_severity']}")
    
    print("\n--- Markdown Report ---")
    print(report.to_markdown())


def test_diff_engine_parsing():
    """Test DiffEngine parsing functions."""
    print("\n" + "=" * 60)
    print("Testing DiffEngine Parsing")
    print("=" * 60)
    
    engine = DiffEngine()
    
    # Test SuzieQ interface parsing
    suzieq_data = {
        "data": [
            {
                "hostname": "R1",
                "ifname": "Gi0/1",
                "state": "up",
                "adminState": "up",
                "mtu": 1500,
                "description": "Uplink to Core",
            },
            {
                "hostname": "R1",
                "ifname": "Gi0/2",
                "state": "down",
                "adminState": "down",
                "mtu": 9000,
            },
        ]
    }
    
    interfaces = engine._parse_suzieq_interfaces(suzieq_data, "R1")
    print(f"\nParsed {len(interfaces)} interfaces from SuzieQ:")
    for name, data in interfaces.items():
        print(f"  - {name}: {data}")
    
    # Test NetBox parsing
    netbox_data = {
        "results": [
            {
                "id": 1,
                "name": "Gi0/1",
                "enabled": True,
                "mtu": 1500,
                "description": "Uplink",
                "type": {"value": "1000base-t"},
            },
            {
                "id": 2,
                "name": "Gi0/3",
                "enabled": True,
                "mtu": 1500,
            },
        ]
    }
    
    nb_interfaces = engine._parse_netbox_interfaces(netbox_data)
    print(f"\nParsed {len(nb_interfaces)} interfaces from NetBox:")
    for name, data in nb_interfaces.items():
        print(f"  - {name}: {data}")
    
    # Test diff generation
    report = ReconciliationReport(device_scope=["R1"])
    engine._diff_interfaces("R1", interfaces, nb_interfaces, report)
    
    print(f"\nDiff Results:")
    print(f"  Matched: {report.matched}")
    print(f"  Mismatched: {report.mismatched}")
    print(f"  Missing in NetBox: {report.missing_in_netbox}")
    print(f"  Missing in Network: {report.missing_in_network}")
    
    for diff in report.diffs:
        print(f"  - {diff.field}: {diff.network_value} vs {diff.netbox_value}")


def test_rules():
    """Test auto-correct and HITL rules."""
    print("\n" + "=" * 60)
    print("Testing Rules")
    print("=" * 60)
    
    from olav.sync.rules import (
        is_safe_auto_correct,
        requires_hitl_approval,
        get_hitl_prompt,
    )
    
    # MTU change - safe
    mtu_diff = DiffResult(
        entity_type=EntityType.INTERFACE,
        device="R1",
        field="Gi0/1.mtu",
        network_value=1500,
        netbox_value=9000,
        severity=DiffSeverity.INFO,
        source=DiffSource.SUZIEQ,
    )
    print(f"\nMTU change:")
    print(f"  Safe to auto-correct: {is_safe_auto_correct(mtu_diff)}")
    print(f"  Requires HITL: {requires_hitl_approval(mtu_diff)}")
    
    # Enabled change - HITL required
    enabled_diff = DiffResult(
        entity_type=EntityType.INTERFACE,
        device="R1",
        field="Gi0/1.enabled",
        network_value=False,
        netbox_value=True,
        severity=DiffSeverity.WARNING,
        source=DiffSource.SUZIEQ,
    )
    print(f"\nEnabled change:")
    print(f"  Safe to auto-correct: {is_safe_auto_correct(enabled_diff)}")
    print(f"  Requires HITL: {requires_hitl_approval(enabled_diff)}")
    
    print(f"\nHITL Prompt Preview:")
    print(get_hitl_prompt(enabled_diff))


async def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("NetBox Bidirectional Sync - Test Suite")
    print("=" * 60)
    
    test_diff_engine_parsing()
    test_rules()
    test_report_generation()
    await test_reconciler_dry_run()
    
    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
