"""Topology sync utility functions.

Provides helpers used by the topology normalizer to distinguish IP addresses
from hostnames and to strip domain suffixes from FQDNs.
"""

from __future__ import annotations

import ipaddress


def _is_ip(value: str | None) -> bool:
    """Return True if *value* is a valid IPv4 or IPv6 address, False otherwise.

    Args:
        value: String to test (may be None or empty).

    Returns:
        bool — True only for strict IP address notation (e.g. "10.1.24.2",
        "::1"), False for hostnames, bare octets, or empty/None values.
    """
    if not value:
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def _strip_domain(value: str | None) -> str | None:
    """Strip domain suffix from an FQDN, leaving the bare hostname.

    IP addresses are returned unchanged to avoid corrupting dotted notation.

    Args:
        value: Hostname or FQDN (may be None or empty).

    Returns:
        Bare hostname (first label only) for FQDNs, original value for plain
        hostnames and IPs, or None/empty-string pass-through.

    Examples:
        >>> _strip_domain("R3.local")
        'R3'
        >>> _strip_domain("10.1.24.2")
        '10.1.24.2'
        >>> _strip_domain("R1")
        'R1'
    """
    if value is None:
        return None
    if not value:
        return value
    # Preserve IP addresses — never split on dots for numeric addresses
    if _is_ip(value):
        return value
    # Strip domain: return only the first DNS label
    if "." in value:
        return value.split(".")[0]
    return value
