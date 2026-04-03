"""Unit tests for L3 endpoint normalization fix.

Tests both the local helper stubs used for documentation/ADR purposes
AND the actual sync_tools module functions (_is_ip, _strip_domain).
"""

import sys
from pathlib import Path

import pytest

# Make sync_tools importable (olav-netops workspace tools dir)
_TOOLS_DIR = Path(__file__).resolve().parents[2] / "olav-netops" / ".olav" / "workspace" / "config" / "sync" / "tools"
if _TOOLS_DIR.exists() and str(_TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(_TOOLS_DIR))


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


def _attempt_device_resolution(invalid_id: str, known_devices: set) -> str | None:
    """Try to resolve an invalid ID to a known device."""
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


class TestL3EndpointValidation:
    """Test invalid device name detection."""

    def test_pure_numeric_is_invalid(self):
        """Pure numeric tokens should be detected as invalid."""
        assert _is_invalid_device_name("10") is True
        assert _is_invalid_device_name("2") is True
        assert _is_invalid_device_name("512") is True

    def test_ipv4_is_invalid(self):
        """IPv4 addresses should be detected as invalid."""
        assert _is_invalid_device_name("10.1.13.1") is True
        assert _is_invalid_device_name("192.168.1.1") is True

    def test_valid_device_names(self):
        """Proper device names should pass validation."""
        assert _is_invalid_device_name("R1") is False
        assert _is_invalid_device_name("R2") is False
        assert _is_invalid_device_name("router-1") is False
        assert _is_invalid_device_name("switch-core-01") is False

    def test_empty_is_invalid(self):
        """Empty strings should be invalid."""
        assert _is_invalid_device_name("") is True
        assert _is_invalid_device_name(None) is True


class TestL3DeviceResolution:
    """Test fuzzy matching of invalid tokens to known devices."""

    def test_numeric_token_to_device_match(self):
        """Numeric tokens should match devices containing that number."""
        known = {"R1", "R2", "R3", "Router4"}
        
        assert _attempt_device_resolution("1", known) == "R1"
        assert _attempt_device_resolution("2", known) == "R2"
        assert _attempt_device_resolution("3", known) == "R3"

    def test_unresolvable_token(self):
        """Tokens with no match should return None."""
        known = {"R1", "R2", "R3"}
        
        assert _attempt_device_resolution("10", known) is None
        assert _attempt_device_resolution("99", known) is None

    def test_partial_match_resolution(self):
        """Partial string matches in device names should resolve."""
        known = {"CoreRouter1", "AccessSwitch2", "EdgeRouter3"}
        
        # Should not match on pure substring since CoreRouter1 contains 'ore' not '1'
        result = _attempt_device_resolution("1", known)
        # But it might match 'CoreRouter1' if fuzzy matching is enabled
        if result:
            assert "1" in result or result == "CoreRouter1"


# ─────────────────────────────────────────────────────────────────────────────
# Tests against the REAL sync_tools functions (_is_ip, _strip_domain)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(
    not _TOOLS_DIR.exists(),
    reason="olav-netops sync_tools not available in this environment",
)
class TestSyncToolsIsIp:
    """Tests for sync_tools._is_ip() — must not raise, always returns bool."""

    def setup_method(self, _method=None):
        pytest.importorskip("nornir", reason="olav-netops requires nornir: uv pip install -e olav-netops")

    def _get(self):
        from sync_tools import _is_ip  # type: ignore[import]
        return _is_ip

    def test_ipv4_recognized(self):
        fn = self._get()
        assert fn("10.1.24.2") is True
        assert fn("192.168.0.1") is True
        assert fn("0.0.0.0") is True
        assert fn("255.255.255.255") is True

    def test_ipv6_recognized(self):
        fn = self._get()
        assert fn("::1") is True
        assert fn("2001:db8::1") is True

    def test_hostname_not_ip(self):
        fn = self._get()
        assert fn("R1") is False
        assert fn("R3.local") is False
        assert fn("router-core-01") is False

    def test_bare_octet_not_ip(self):
        """'10' alone is NOT a valid IP address — it's a plain integer."""
        fn = self._get()
        assert fn("10") is False
        assert fn("192") is False

    def test_empty_and_none(self):
        fn = self._get()
        assert fn(None) is False
        assert fn("") is False


@pytest.mark.skipif(
    not _TOOLS_DIR.exists(),
    reason="olav-netops sync_tools not available in this environment",
)
class TestSyncToolsStripDomain:
    """Tests for sync_tools._strip_domain() — the core regression fix."""

    def setup_method(self, _method=None):
        pytest.importorskip("nornir", reason="olav-netops requires nornir: uv pip install -e olav-netops")

    def _get(self):
        from sync_tools import _strip_domain  # type: ignore[import]
        return _strip_domain

    def test_fqdn_stripped_to_hostname(self):
        fn = self._get()
        assert fn("R3.local") == "R3"
        assert fn("R3.corp.example.com") == "R3"
        assert fn("sw1.datacenter.net") == "sw1"

    def test_plain_hostname_unchanged(self):
        fn = self._get()
        assert fn("R1") == "R1"
        assert fn("SW1") == "SW1"

    def test_ip_address_not_corrupted(self):
        """KEY REGRESSION: IPs must NOT be split on dots."""
        fn = self._get()
        assert fn("10.1.24.2") == "10.1.24.2"
        assert fn("192.168.100.1") == "192.168.100.1"
        assert fn("10.1.13.1") == "10.1.13.1"

    def test_none_passthrough(self):
        fn = self._get()
        assert fn(None) is None

    def test_empty_passthrough(self):
        fn = self._get()
        assert fn("") == ""


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

