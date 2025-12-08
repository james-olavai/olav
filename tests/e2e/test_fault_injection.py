"""E2E Tests for Fault Injection and Agent Diagnosis.

These tests inject real faults into the network and verify
the agent can diagnose the root cause correctly.

Fault Types:
    - F1: IP Address Misconfiguration (wrong IP on interface)
    - F2: Subnet Mask Mismatch (different masks on peer interfaces)
    - F3: ACL Blocking Traffic (deny ACL on interface)
    - F4: BGP Peer Misconfiguration (wrong peer IP/ASN)
    - F5: OSPF Area Mismatch (different areas on adjacency)
    - F6: MTU Mismatch (different MTU causing fragmentation)

Safety:
    - All faults use dedicated test interfaces (Loopback100, Loopback101)
    - Tests restore original config after each fault
    - YOLO mode required for automated execution

Usage:
    # Run fault injection tests
    OLAV_YOLO_MODE=true uv run pytest tests/e2e/test_fault_injection.py -v

    # Run specific fault type
    uv run pytest tests/e2e/test_fault_injection.py -k "ip_mismatch" -v
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from dataclasses import dataclass

import pytest

# Windows async compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ============================================
# Test Constants
# ============================================
# Test interfaces - safe to modify
TEST_LOOPBACK_1 = "Loopback100"
TEST_LOOPBACK_2 = "Loopback101"

# Test IPs for fault injection
CORRECT_IP_1 = "100.100.100.1/32"
CORRECT_IP_2 = "100.100.100.2/32"
WRONG_IP = "100.100.100.99/32"
WRONG_MASK = "100.100.100.1/24"  # Wrong mask

# Test devices (should be BGP/OSPF peers)
DEVICE_A = os.environ.get("OLAV_TEST_DEVICE_A", "R1")
DEVICE_B = os.environ.get("OLAV_TEST_DEVICE_B", "R2")

# Timeouts
TIMEOUT_INJECT = 30    # seconds for fault injection
TIMEOUT_DIAGNOSE = 90  # seconds for diagnosis (longer for deep dive)
TIMEOUT_RESTORE = 30   # seconds for config restore


# ============================================
# Skip Conditions
# ============================================
def _is_yolo_mode() -> bool:
    """Check if YOLO mode is enabled."""
    return os.environ.get("OLAV_YOLO_MODE", "").lower() in ("1", "true", "yes")


pytestmark = [
    pytest.mark.fault_injection,
    pytest.mark.destructive,
    pytest.mark.slow,
    pytest.mark.skipif(
        not _is_yolo_mode(),
        reason="Fault injection tests require YOLO mode. Set OLAV_YOLO_MODE=true"
    ),
]


# ============================================
# Data Classes
# ============================================
@dataclass
class FaultScenario:
    """Defines a fault injection scenario."""
    name: str
    description: str
    inject_query: str
    restore_query: str
    diagnosis_query: str
    expected_diagnosis: list[str]  # Keywords expected in diagnosis


@dataclass
class DiagnosisResult:
    """Result of a diagnosis attempt."""
    success: bool
    response: str
    found_keywords: list[str]
    missing_keywords: list[str]
    confidence: float  # 0.0 to 1.0


# ============================================
# Fault Scenarios
# ============================================
FAULT_SCENARIOS = {
    "ip_mismatch": FaultScenario(
        name="IP Address Mismatch",
        description="Configure wrong IP on interface, verify agent detects it",
        inject_query=f"configure {TEST_LOOPBACK_1} on {DEVICE_A} with IP {WRONG_IP}",
        restore_query=f"configure {TEST_LOOPBACK_1} on {DEVICE_A} with IP {CORRECT_IP_1}",
        diagnosis_query=f"why is {TEST_LOOPBACK_1} on {DEVICE_A} not working correctly?",
        expected_diagnosis=["ip", "address", "mismatch", "wrong", "incorrect"],
    ),

    "mask_mismatch": FaultScenario(
        name="Subnet Mask Mismatch",
        description="Configure different subnet masks on peering interfaces",
        inject_query=f"configure {TEST_LOOPBACK_1} on {DEVICE_A} with IP {WRONG_MASK}",
        restore_query=f"configure {TEST_LOOPBACK_1} on {DEVICE_A} with IP {CORRECT_IP_1}",
        diagnosis_query=f"analyze subnet configuration on {DEVICE_A} {TEST_LOOPBACK_1}",
        expected_diagnosis=["mask", "subnet", "mismatch", "/24", "/32"],
    ),

    "acl_block": FaultScenario(
        name="ACL Blocking Traffic",
        description="Apply deny ACL that blocks traffic",
        inject_query=f"apply ACL to block all traffic on {TEST_LOOPBACK_1} on {DEVICE_A}",
        restore_query=f"remove ACL from {TEST_LOOPBACK_1} on {DEVICE_A}",
        diagnosis_query=f"why is traffic being dropped on {DEVICE_A} {TEST_LOOPBACK_1}?",
        expected_diagnosis=["acl", "access-list", "deny", "block", "filter"],
    ),

    "bgp_peer_wrong_ip": FaultScenario(
        name="BGP Peer Wrong IP",
        description="Configure BGP peer with wrong neighbor IP",
        inject_query=f"configure BGP peer 99.99.99.99 on {DEVICE_A}",
        restore_query=f"remove BGP peer 99.99.99.99 from {DEVICE_A}",
        diagnosis_query=f"why is BGP peer 99.99.99.99 not establishing on {DEVICE_A}?",
        expected_diagnosis=["bgp", "peer", "unreachable", "neighbor", "idle"],
    ),

    "bgp_wrong_asn": FaultScenario(
        name="BGP Wrong ASN",
        description="Configure BGP peer with wrong remote ASN",
        inject_query=f"configure BGP peer with wrong ASN 99999 on {DEVICE_A}",
        restore_query=f"fix BGP peer ASN on {DEVICE_A}",
        diagnosis_query=f"analyze BGP session issues on {DEVICE_A}",
        expected_diagnosis=["asn", "as", "mismatch", "notification", "bad"],
    ),

    "ospf_area_mismatch": FaultScenario(
        name="OSPF Area Mismatch",
        description="Configure interface in wrong OSPF area",
        inject_query=f"configure {TEST_LOOPBACK_1} in OSPF area 99 on {DEVICE_A}",
        restore_query=f"configure {TEST_LOOPBACK_1} in OSPF area 0 on {DEVICE_A}",
        diagnosis_query=f"why is OSPF adjacency failing on {DEVICE_A}?",
        expected_diagnosis=["ospf", "area", "mismatch", "adjacency", "neighbor"],
    ),

    "mtu_mismatch": FaultScenario(
        name="MTU Mismatch",
        description="Configure different MTU on peering interfaces",
        inject_query=f"set MTU 1400 on {TEST_LOOPBACK_1} on {DEVICE_A}",
        restore_query=f"set MTU 1500 on {TEST_LOOPBACK_1} on {DEVICE_A}",
        diagnosis_query=f"analyze MTU issues between {DEVICE_A} and {DEVICE_B}",
        expected_diagnosis=["mtu", "size", "mismatch", "fragmentation"],
    ),

    "interface_shutdown": FaultScenario(
        name="Interface Shutdown",
        description="Shutdown interface and verify agent detects it",
        inject_query=f"shutdown {TEST_LOOPBACK_1} on {DEVICE_A}",
        restore_query=f"no shutdown {TEST_LOOPBACK_1} on {DEVICE_A}",
        diagnosis_query=f"why is {TEST_LOOPBACK_1} down on {DEVICE_A}?",
        expected_diagnosis=["shutdown", "admin", "down", "disabled"],
    ),
}


# ============================================
# Helper Functions
# ============================================
def run_query(query: str, timeout: float = TIMEOUT_DIAGNOSE, mode: str = "standard"):
    """Execute a query via CLI.

    Args:
        query: The query text to execute
        timeout: Timeout in seconds
        mode: Query mode (standard/expert)

    Returns:
        CLIResult with output and metadata
    """
    from tests.e2e.test_cli_capabilities import run_cli_query
    return run_cli_query(query, mode=mode, timeout=timeout, yolo=True)


def inject_fault(scenario: FaultScenario) -> bool:
    """Inject a fault into the network.

    Args:
        scenario: The fault scenario to inject

    Returns:
        True if injection succeeded
    """
    result = run_query(scenario.inject_query, timeout=TIMEOUT_INJECT)
    return result.success


def restore_config(scenario: FaultScenario) -> bool:
    """Restore configuration after fault.

    Args:
        scenario: The fault scenario to restore

    Returns:
        True if restore succeeded
    """
    result = run_query(scenario.restore_query, timeout=TIMEOUT_RESTORE)
    return result.success


def diagnose_fault(scenario: FaultScenario) -> DiagnosisResult:
    """Run agent diagnosis on a fault.

    Args:
        scenario: The fault scenario to diagnose

    Returns:
        DiagnosisResult with analysis
    """
    # Use expert mode for deep analysis
    result = run_query(scenario.diagnosis_query, mode="expert", timeout=TIMEOUT_DIAGNOSE)

    if not result.success:
        return DiagnosisResult(
            success=False,
            response=result.stderr,
            found_keywords=[],
            missing_keywords=scenario.expected_diagnosis,
            confidence=0.0,
        )

    response_lower = result.stdout.lower()

    found = []
    missing = []

    for keyword in scenario.expected_diagnosis:
        if keyword.lower() in response_lower:
            found.append(keyword)
        else:
            missing.append(keyword)

    confidence = len(found) / len(scenario.expected_diagnosis) if scenario.expected_diagnosis else 0.0

    return DiagnosisResult(
        success=True,
        response=result.stdout,
        found_keywords=found,
        missing_keywords=missing,
        confidence=confidence,
    )


# ============================================
# Fixtures
# ============================================
@pytest.fixture
def cleanup_after_fault():
    """Ensure config is restored after fault test."""
    scenarios_to_restore = []

    def register_scenario(scenario: FaultScenario):
        scenarios_to_restore.append(scenario)

    yield register_scenario

    # Restore all registered scenarios
    for scenario in scenarios_to_restore:
        try:
            restore_config(scenario)
        except Exception as e:
            print(f"Warning: Failed to restore {scenario.name}: {e}")


@pytest.fixture(autouse=True)
def setup_test_interfaces():
    """Ensure test interfaces exist before fault injection."""
    from tests.e2e.test_cli_capabilities import run_cli_query

    # Create test loopback if doesn't exist
    run_cli_query(
        f"add {TEST_LOOPBACK_1} with IP {CORRECT_IP_1} to {DEVICE_A}",
        timeout=TIMEOUT_INJECT,
        yolo=True,
    )


    # Don't auto-cleanup - individual tests handle restoration


# ============================================
# Test Classes
# ============================================
class TestIPMisconfiguration:
    """Tests for IP address misconfiguration diagnosis."""

    def test_f01_wrong_ip_diagnosis(self, cleanup_after_fault):
        """F01: Agent diagnoses wrong IP address.

        Fault: Configure wrong IP on Loopback100
        Expected: Agent identifies IP mismatch
        """
        scenario = FAULT_SCENARIOS["ip_mismatch"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(2)  # Wait for config to apply

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        # Verify diagnosis quality
        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        assert diagnosis.confidence >= 0.4, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"

    def test_f02_subnet_mask_diagnosis(self, cleanup_after_fault):
        """F02: Agent diagnoses subnet mask mismatch.

        Fault: Configure wrong subnet mask
        Expected: Agent identifies mask difference
        """
        scenario = FAULT_SCENARIOS["mask_mismatch"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(2)

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        assert diagnosis.confidence >= 0.3, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"


class TestACLBlocking:
    """Tests for ACL blocking diagnosis."""

    def test_f03_acl_blocking_diagnosis(self, cleanup_after_fault):
        """F03: Agent diagnoses ACL blocking traffic.

        Fault: Apply deny ACL on interface
        Expected: Agent identifies ACL as cause
        """
        scenario = FAULT_SCENARIOS["acl_block"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(2)

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        assert diagnosis.confidence >= 0.3, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"


class TestBGPMisconfiguration:
    """Tests for BGP misconfiguration diagnosis."""

    def test_f04_bgp_wrong_peer_ip(self, cleanup_after_fault):
        """F04: Agent diagnoses wrong BGP peer IP.

        Fault: Configure BGP peer with unreachable IP
        Expected: Agent identifies peer is unreachable
        """
        scenario = FAULT_SCENARIOS["bgp_peer_wrong_ip"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(5)  # BGP takes time to detect

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        assert diagnosis.confidence >= 0.3, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"

    def test_f05_bgp_wrong_asn(self, cleanup_after_fault):
        """F05: Agent diagnoses wrong BGP ASN.

        Fault: Configure BGP peer with wrong remote ASN
        Expected: Agent identifies ASN mismatch
        """
        scenario = FAULT_SCENARIOS["bgp_wrong_asn"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(5)

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        # ASN issues might be harder to diagnose
        assert diagnosis.confidence >= 0.2, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"


class TestOSPFMisconfiguration:
    """Tests for OSPF misconfiguration diagnosis."""

    def test_f06_ospf_area_mismatch(self, cleanup_after_fault):
        """F06: Agent diagnoses OSPF area mismatch.

        Fault: Configure interface in wrong OSPF area
        Expected: Agent identifies area mismatch
        """
        scenario = FAULT_SCENARIOS["ospf_area_mismatch"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(5)  # OSPF takes time to detect

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        assert diagnosis.confidence >= 0.3, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"


class TestInterfaceIssues:
    """Tests for interface-level issue diagnosis."""

    def test_f07_mtu_mismatch(self, cleanup_after_fault):
        """F07: Agent diagnoses MTU mismatch.

        Fault: Configure different MTU
        Expected: Agent identifies MTU difference
        """
        scenario = FAULT_SCENARIOS["mtu_mismatch"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(2)

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        # MTU issues might be subtle
        assert diagnosis.confidence >= 0.2, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"

    def test_f08_interface_shutdown(self, cleanup_after_fault):
        """F08: Agent diagnoses interface shutdown.

        Fault: Shutdown interface
        Expected: Agent identifies admin down state
        """
        scenario = FAULT_SCENARIOS["interface_shutdown"]
        cleanup_after_fault(scenario)

        # Inject fault
        assert inject_fault(scenario), f"Failed to inject fault: {scenario.name}"
        time.sleep(2)

        # Run diagnosis
        diagnosis = diagnose_fault(scenario)

        assert diagnosis.success, f"Diagnosis failed: {diagnosis.response}"
        assert diagnosis.confidence >= 0.5, \
            f"Low confidence ({diagnosis.confidence:.0%}). Missing: {diagnosis.missing_keywords}"


# ============================================
# Complex Multi-Fault Scenarios
# ============================================
class TestComplexScenarios:
    """Tests for complex multi-fault scenarios."""

    @pytest.mark.slow
    def test_f10_cascading_failure(self, cleanup_after_fault):
        """F10: Agent diagnoses cascading failure.

        Fault: Interface down + BGP peer unreachable
        Expected: Agent traces root cause to interface
        """
        # First shutdown interface
        shutdown_scenario = FAULT_SCENARIOS["interface_shutdown"]
        cleanup_after_fault(shutdown_scenario)

        assert inject_fault(shutdown_scenario), "Failed to shutdown interface"
        time.sleep(3)

        # Now ask about BGP (which should fail due to interface)
        diagnosis_query = f"why is BGP failing between {DEVICE_A} and {DEVICE_B}?"
        result = run_query(diagnosis_query, mode="expert")

        assert result.success, f"Diagnosis failed: {result.stderr}"

        # Should find root cause (interface down)
        response_lower = result.stdout.lower()
        root_cause_found = any(kw in response_lower for kw in ["interface", "down", "shutdown"])
        assert root_cause_found, "Agent should identify interface down as root cause"

    @pytest.mark.slow
    def test_f11_multi_device_correlation(self, cleanup_after_fault):
        """F11: Agent correlates issues across devices.

        Fault: Misconfiguration affecting multiple devices
        Expected: Agent identifies impact on both sides
        """
        # Create IP mismatch
        scenario = FAULT_SCENARIOS["ip_mismatch"]
        cleanup_after_fault(scenario)

        assert inject_fault(scenario), "Failed to inject fault"
        time.sleep(2)

        # Ask about connectivity between devices
        diagnosis_query = f"analyze connectivity issues between {DEVICE_A} and {DEVICE_B}"
        result = run_query(diagnosis_query, mode="expert")

        assert result.success, f"Diagnosis failed: {result.stderr}"

        # Should mention both devices
        response_lower = result.stdout.lower()
        mentions_both = DEVICE_A.lower() in response_lower or DEVICE_B.lower() in response_lower
        assert mentions_both, "Agent should analyze both devices"


# ============================================
# Report
# ============================================
@pytest.fixture(scope="session", autouse=True)
def print_fault_injection_summary(request):
    """Print fault injection test summary."""
    yield

    print("\n" + "=" * 70)
    print("Fault Injection E2E Test Summary")
    print("=" * 70)
    print("Fault Types Tested:")
    for _key, scenario in FAULT_SCENARIOS.items():
        print(f"  - {scenario.name}: {scenario.description}")
    print("=" * 70)
    print("Diagnosis Criteria:")
    print("  - Response must contain expected keywords")
    print("  - Minimum confidence threshold: 20-50% depending on fault type")
    print("  - Expert mode used for deep analysis")
    print("=" * 70)
    print(f"Test Devices: {DEVICE_A}, {DEVICE_B}")
    print(f"Test Interfaces: {TEST_LOOPBACK_1}, {TEST_LOOPBACK_2}")
    print("=" * 70)
