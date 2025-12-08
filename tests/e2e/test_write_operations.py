"""E2E Tests for Write Operations (Destructive Tests).

These tests perform actual write operations on devices and NetBox.
They use a safe test loopback interface that can be added/removed.

Test Loopback Specification:
    - Interface: Loopback100
    - IP Address: 100.100.100.100/32
    - Description: "OLAV-E2E-TEST - Safe to delete"

Usage:
    # Run destructive tests (requires YOLO mode)
    OLAV_YOLO_MODE=true uv run pytest tests/e2e/test_write_operations.py -v

    # Run with explicit marker
    uv run pytest tests/e2e/test_write_operations.py -m "destructive" -v

Safety:
    - All tests use dedicated test interface (Loopback100)
    - Tests clean up after themselves
    - HITL approval required unless YOLO mode enabled
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

import pytest

# Windows async compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


# ============================================
# Test Constants
# ============================================
TEST_LOOPBACK = "Loopback100"
TEST_IP = "100.100.100.100"
TEST_MASK = "255.255.255.255"
TEST_PREFIX = f"{TEST_IP}/32"
TEST_DESCRIPTION = "OLAV-E2E-TEST - Safe to delete"
TEST_DEVICE = "R1"  # Primary test device

TIMEOUT_WRITE = 60  # seconds for write operations
TIMEOUT_SYNC = 30   # seconds for NetBox sync


# ============================================
# Skip Conditions
# ============================================
def _is_yolo_mode() -> bool:
    """Check if YOLO mode is enabled."""
    return os.environ.get("OLAV_YOLO_MODE", "").lower() in ("1", "true", "yes")


pytestmark = [
    pytest.mark.destructive,
    pytest.mark.skipif(
        not _is_yolo_mode(),
        reason="Write tests require YOLO mode. Set OLAV_YOLO_MODE=true"
    ),
]


# ============================================
# Fixtures
# ============================================
@pytest.fixture(scope="module")
def test_device() -> str:
    """Get test device name from env or default."""
    return os.environ.get("OLAV_TEST_DEVICE", TEST_DEVICE)


@pytest.fixture
def ensure_loopback_removed(test_device: str):
    """Ensure test loopback is removed before and after test."""
    # Cleanup before test
    _remove_test_loopback(test_device)

    yield

    # Cleanup after test
    _remove_test_loopback(test_device)


def _remove_test_loopback(device: str) -> None:
    """Remove test loopback if it exists."""
    from tests.e2e.test_cli_capabilities import run_cli_query

    # Try to remove loopback (ignore errors if doesn't exist)
    run_cli_query(
        f"remove {TEST_LOOPBACK} from {device}",
        timeout=TIMEOUT_WRITE,
        yolo=True,
    )


# ============================================
# Helper Functions
# ============================================
def run_write_query(query: str, timeout: float = TIMEOUT_WRITE):
    """Execute a write query via CLI.

    Args:
        query: The query text to execute
        timeout: Timeout in seconds

    Returns:
        CLIResult with output and metadata
    """
    from tests.e2e.test_cli_capabilities import run_cli_query
    return run_cli_query(query, timeout=timeout, yolo=True)


def verify_interface_exists(device: str, interface: str) -> bool:
    """Verify an interface exists on a device.

    Args:
        device: Device hostname
        interface: Interface name

    Returns:
        True if interface exists
    """
    from tests.e2e.test_cli_capabilities import run_cli_query

    result = run_cli_query(f"show interface {interface} on {device}")
    return result.success and interface.lower() in result.stdout.lower()


def verify_ip_configured(device: str, ip: str) -> bool:
    """Verify an IP address is configured on a device.

    Args:
        device: Device hostname
        ip: IP address to check

    Returns:
        True if IP is configured
    """
    from tests.e2e.test_cli_capabilities import run_cli_query

    result = run_cli_query(f"check if {ip} is configured on {device}")
    return result.success and ip in result.stdout


def verify_netbox_interface(device: str, interface: str) -> bool:
    """Verify an interface exists in NetBox.

    Args:
        device: Device hostname
        interface: Interface name

    Returns:
        True if interface exists in NetBox
    """
    from tests.e2e.test_cli_capabilities import run_cli_query

    result = run_cli_query(f"find interface {interface} on {device} in NetBox")
    return result.success and interface.lower() in result.stdout.lower()


# ============================================
# Category W1: Device Write Operations
# ============================================
class TestDeviceWriteOperations:
    """Tests for device write operations."""

    @pytest.mark.order(1)
    def test_w01_add_loopback_interface(self, test_device: str, ensure_loopback_removed):
        """W01: Add test loopback interface.

        Operation: Add Loopback100 with 100.100.100.100/32
        Expected: Interface created with correct IP
        """
        query = f"add {TEST_LOOPBACK} with IP {TEST_PREFIX} and description '{TEST_DESCRIPTION}' to {test_device}"
        result = run_write_query(query)

        assert result.success, f"Failed to add loopback: {result.stderr}"

        # Verify interface was created
        time.sleep(2)  # Wait for config to apply
        assert verify_interface_exists(test_device, TEST_LOOPBACK), \
            f"{TEST_LOOPBACK} not found on {test_device}"

    @pytest.mark.order(2)
    def test_w02_verify_loopback_ip(self, test_device: str):
        """W02: Verify loopback has correct IP.

        Prerequisite: W01 must have passed
        Expected: IP 100.100.100.100 configured
        """
        assert verify_ip_configured(test_device, TEST_IP), \
            f"IP {TEST_IP} not configured on {test_device}"

    @pytest.mark.order(3)
    def test_w03_modify_loopback_description(self, test_device: str):
        """W03: Modify loopback description.

        Operation: Change description
        Expected: Description updated
        """
        new_desc = "OLAV-E2E-TEST-MODIFIED"
        query = f"change description of {TEST_LOOPBACK} on {test_device} to '{new_desc}'"
        result = run_write_query(query)

        assert result.success, f"Failed to modify description: {result.stderr}"

    @pytest.mark.order(4)
    def test_w04_remove_loopback_interface(self, test_device: str):
        """W04: Remove test loopback interface.

        Operation: Remove Loopback100
        Expected: Interface removed
        """
        query = f"remove {TEST_LOOPBACK} from {test_device}"
        result = run_write_query(query)

        assert result.success, f"Failed to remove loopback: {result.stderr}"

        # Verify interface was removed
        time.sleep(2)
        assert not verify_interface_exists(test_device, TEST_LOOPBACK), \
            f"{TEST_LOOPBACK} still exists on {test_device}"


# ============================================
# Category W2: NetBox Sync Operations
# ============================================
class TestNetBoxSyncOperations:
    """Tests for NetBox synchronization operations."""

    @pytest.mark.order(10)
    def test_w10_add_and_sync_loopback(self, test_device: str, ensure_loopback_removed):
        """W10: Add loopback and sync to NetBox.

        Operation: Add Loopback100, then sync to NetBox
        Expected: Interface appears in NetBox
        """
        # Step 1: Add loopback to device
        query1 = f"add {TEST_LOOPBACK} with IP {TEST_PREFIX} to {test_device}"
        result1 = run_write_query(query1)
        assert result1.success, f"Failed to add loopback: {result1.stderr}"

        time.sleep(2)

        # Step 2: Sync to NetBox
        query2 = f"sync interface {TEST_LOOPBACK} from {test_device} to NetBox"
        result2 = run_write_query(query2, timeout=TIMEOUT_SYNC)
        assert result2.success, f"Failed to sync to NetBox: {result2.stderr}"

        # Step 3: Verify in NetBox
        time.sleep(2)
        assert verify_netbox_interface(test_device, TEST_LOOPBACK), \
            f"{TEST_LOOPBACK} not found in NetBox for {test_device}"

    @pytest.mark.order(11)
    def test_w11_sync_ip_to_netbox(self, test_device: str):
        """W11: Sync IP address to NetBox.

        Prerequisite: W10 must have passed
        Expected: IP 100.100.100.100/32 in NetBox
        """
        query = f"sync IP {TEST_PREFIX} from {test_device} {TEST_LOOPBACK} to NetBox"
        result = run_write_query(query, timeout=TIMEOUT_SYNC)

        assert result.success, f"Failed to sync IP: {result.stderr}"

    @pytest.mark.order(12)
    def test_w12_remove_from_netbox(self, test_device: str):
        """W12: Remove interface from NetBox.

        Operation: Delete Loopback100 from NetBox
        Expected: Interface removed from NetBox
        """
        query = f"delete interface {TEST_LOOPBACK} of {test_device} from NetBox"
        result = run_write_query(query, timeout=TIMEOUT_SYNC)

        assert result.success, f"Failed to remove from NetBox: {result.stderr}"

        time.sleep(2)
        assert not verify_netbox_interface(test_device, TEST_LOOPBACK), \
            f"{TEST_LOOPBACK} still in NetBox for {test_device}"

    @pytest.mark.order(13)
    def test_w13_remove_from_device(self, test_device: str):
        """W13: Remove loopback from device (cleanup).

        Operation: Remove Loopback100 from device
        Expected: Interface removed
        """
        query = f"remove {TEST_LOOPBACK} from {test_device}"
        run_write_query(query)

        # May fail if already removed - that's OK
        time.sleep(2)
        assert not verify_interface_exists(test_device, TEST_LOOPBACK), \
            f"{TEST_LOOPBACK} still exists on {test_device}"


# ============================================
# Category W3: Bulk Operations
# ============================================
class TestBulkWriteOperations:
    """Tests for bulk write operations across multiple devices."""

    @pytest.mark.slow
    @pytest.mark.order(20)
    def test_w20_add_loopback_to_multiple_devices(self):
        """W20: Add test loopback to multiple devices.

        Operation: Add Loopback100 to all routers
        Expected: Interface created on all devices
        """
        query = f"add {TEST_LOOPBACK} with IP {TEST_PREFIX} to all routers"
        result = run_write_query(query, timeout=TIMEOUT_WRITE * 3)

        assert result.success, f"Bulk add failed: {result.stderr}"

    @pytest.mark.slow
    @pytest.mark.order(21)
    def test_w21_remove_loopback_from_multiple_devices(self):
        """W21: Remove test loopback from multiple devices.

        Operation: Remove Loopback100 from all routers
        Expected: Interface removed from all devices
        """
        query = f"remove {TEST_LOOPBACK} from all routers"
        result = run_write_query(query, timeout=TIMEOUT_WRITE * 3)

        assert result.success, f"Bulk remove failed: {result.stderr}"


# ============================================
# Report
# ============================================
@pytest.fixture(scope="session", autouse=True)
def print_write_test_summary(request):
    """Print write test summary after all tests."""
    yield

    print("\n" + "=" * 60)
    print("Write Operations E2E Test Summary")
    print("=" * 60)
    print(f"Test Interface: {TEST_LOOPBACK}")
    print(f"Test IP: {TEST_PREFIX}")
    print(f"Test Device: {TEST_DEVICE}")
    print("=" * 60)
    print("Categories:")
    print("  W1. Device Write Operations (add/modify/remove loopback)")
    print("  W2. NetBox Sync Operations (sync/delete in NetBox)")
    print("  W3. Bulk Operations (multi-device)")
    print("=" * 60)
