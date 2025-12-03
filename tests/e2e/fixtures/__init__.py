"""Shared fixtures for E2E tests.

This module provides common fixtures and utilities for E2E testing.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Generator

import pytest

# Windows async compatibility
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ============================================
# Environment Fixtures
# ============================================
@pytest.fixture(scope="session")
def project_root() -> Path:
    """Get project root path."""
    return PROJECT_ROOT


@pytest.fixture(scope="session")
def test_data_dir() -> Path:
    """Get test data directory."""
    data_dir = PROJECT_ROOT / "tests" / "e2e" / "test_data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


@pytest.fixture
def yolo_mode() -> Generator[None, None, None]:
    """Enable YOLO mode (auto-approve HITL) for testing."""
    original = os.environ.get("OLAV_YOLO_MODE")
    os.environ["OLAV_YOLO_MODE"] = "true"
    yield
    if original:
        os.environ["OLAV_YOLO_MODE"] = original
    else:
        os.environ.pop("OLAV_YOLO_MODE", None)


@pytest.fixture
def clean_env() -> Generator[dict, None, None]:
    """Provide a clean environment for testing."""
    original_env = os.environ.copy()
    yield original_env
    # Restore original environment
    os.environ.clear()
    os.environ.update(original_env)


# ============================================
# Mock Data Fixtures
# ============================================
@pytest.fixture
def sample_bgp_response() -> dict:
    """Sample BGP query response for validation."""
    return {
        "table": "bgp",
        "data": [
            {
                "hostname": "R1",
                "peer": "10.1.1.2",
                "peerHostname": "R2",
                "state": "Established",
                "asn": 65001,
                "peerAsn": 65002,
                "vrf": "default",
            },
            {
                "hostname": "R1",
                "peer": "10.1.1.3",
                "peerHostname": "R3",
                "state": "Idle",
                "asn": 65001,
                "peerAsn": 65003,
                "vrf": "default",
            },
        ],
    }


@pytest.fixture
def sample_interface_response() -> dict:
    """Sample interface query response for validation."""
    return {
        "table": "interface",
        "data": [
            {
                "hostname": "R1",
                "ifname": "GigabitEthernet0/0",
                "state": "up",
                "adminState": "up",
                "ipAddressList": ["10.1.1.1/24"],
            },
            {
                "hostname": "R1",
                "ifname": "GigabitEthernet0/1",
                "state": "down",
                "adminState": "up",
                "ipAddressList": ["10.1.2.1/24"],
            },
        ],
    }


@pytest.fixture
def sample_device_response() -> dict:
    """Sample device query response for validation."""
    return {
        "table": "device",
        "data": [
            {
                "hostname": "R1",
                "os": "eos",
                "version": "4.25.0",
                "vendor": "Arista",
                "model": "vEOS",
            },
            {
                "hostname": "R2",
                "os": "eos",
                "version": "4.25.0",
                "vendor": "Arista",
                "model": "vEOS",
            },
        ],
    }


# ============================================
# Validation Helpers
# ============================================
class ResponseValidator:
    """Helper class for validating agent responses."""
    
    @staticmethod
    def has_tool_call(response: str, tool_name: str) -> bool:
        """Check if response indicates a tool was called."""
        tool_patterns = [
            f"calling {tool_name}",
            f"using {tool_name}",
            f"tool: {tool_name}",
            f"[{tool_name}]",
        ]
        response_lower = response.lower()
        return any(p.lower() in response_lower for p in tool_patterns)
    
    @staticmethod
    def has_data_table(response: str) -> bool:
        """Check if response contains structured data (table)."""
        table_patterns = [
            "│",  # Table border
            "┌",  # Table corner
            "├",  # Table separator
            "|",  # Simple table
            "---",  # Markdown table
        ]
        return any(p in response for p in table_patterns)
    
    @staticmethod
    def has_summary(response: str) -> bool:
        """Check if response contains summary information."""
        summary_patterns = [
            "summary",
            "total",
            "count",
            "result",
            "found",
        ]
        response_lower = response.lower()
        return any(p in response_lower for p in summary_patterns)
    
    @staticmethod
    def is_error_response(response: str) -> bool:
        """Check if response indicates an error."""
        error_patterns = [
            "error",
            "failed",
            "exception",
            "traceback",
            "not found",
        ]
        response_lower = response.lower()
        return any(p in response_lower for p in error_patterns)
    
    @staticmethod
    def contains_device_name(response: str, device: str) -> bool:
        """Check if response mentions a specific device."""
        return device.lower() in response.lower()
    
    @staticmethod
    def contains_protocol(response: str, protocol: str) -> bool:
        """Check if response mentions a specific protocol."""
        return protocol.lower() in response.lower()


@pytest.fixture
def validator() -> ResponseValidator:
    """Provide response validator instance."""
    return ResponseValidator()


# ============================================
# Async Helpers
# ============================================
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ============================================
# Pytest Configuration
# ============================================
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )
    config.addinivalue_line(
        "markers", "requires_server: tests requiring OLAV server"
    )
    config.addinivalue_line(
        "markers", "requires_hitl: tests requiring HITL approval"
    )
    config.addinivalue_line(
        "markers", "requires_netbox: tests requiring NetBox connection"
    )
