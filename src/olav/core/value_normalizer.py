"""Value Normalizer — post-SchemaMapper value-level normalization.

Pipeline position:
    Raw Data → LLM/TextFSM → SchemaMapper (Keys) → ValueNormalizer (Values) → DuckDB

Purpose:
    SchemaMapper aligns *key names* across vendors (e.g. local_interface → local_port).
    ValueNormalizer normalizes *values* so DuckDB JOINs succeed across platforms:
    - Interface names: "Gi0/1" → "GigabitEthernet0/1"  (Cisco short ↔ long form)
    - MAC addresses:   "aabb.ccdd.eeff" → "aa:bb:cc:dd:ee:ff"  (Cisco → colon)

Usage:
    from olav.core.value_normalizer import ValueNormalizer

    normalizer = ValueNormalizer()
    clean = normalizer.normalize_record({"local_port": "Gi0/1", "mac_addr": "aabb.cc00.dd00"})
    # → {"local_port": "GigabitEthernet0/1", "mac_addr": "aa:bb:cc:00:dd:00"}

    # Or normalize a single interface name:
    iface = normalizer.interface_name("Gi0/0/1")
    # → "GigabitEthernet0/0/1"
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# Keys in a flat dict that hold interface names and should be canonicalized
INTERFACE_KEYS: tuple[str, ...] = (
    "local_port",
    "neighbor_port",
    "interface",
    "source_interface",
    "destination_interface",
    "local_interface",
    "neighbor_interface",
    "out_interface",
)

# Keys that hold MAC addresses and should be normalized to colon format
MAC_KEYS: tuple[str, ...] = (
    "mac_addr",
    "mac_address",
    "chassis_id",
)


class ValueNormalizer:
    """Normalize device-output values to canonical forms for reliable JOINs."""

    def __init__(self) -> None:
        self._iface_fn = self._load_iface_fn()
        self._mac_fn = self._load_mac_fn()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def normalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """Normalize all recognized value fields in a flat dict.

        Args:
            record: A flat dictionary, typically one row going into DuckDB.

        Returns:
            A new dict with normalized values; unrecognized keys are unchanged.
        """
        out = record.copy()
        for key in INTERFACE_KEYS:
            if key in out and out[key]:
                out[key] = self.interface_name(out[key])
        for key in MAC_KEYS:
            if key in out and out[key]:
                out[key] = self.mac_address(out[key])
        return out

    def interface_name(self, raw: str) -> str:
        """Return canonical long-form interface name.

        Examples:
            "Gi0/1"           → "GigabitEthernet0/1"
            "Fa0/0"           → "FastEthernet0/0"
            "Te1/0/1"         → "TenGigabitEthernet1/0/1"
            "GigabitEthernet0/1" → "GigabitEthernet0/1"  (unchanged)

        Returns raw unchanged if netutils is unavailable or normalization fails.
        """
        if not raw or not isinstance(raw, str):
            return raw
        if self._iface_fn is None:
            return raw
        try:
            result = self._iface_fn(raw)
            # canonical_interface_name returns empty string for unknown — keep raw
            return result if result else raw
        except Exception:
            return raw

    def mac_address(self, raw: str) -> str:
        """Return MAC address in two-octet colon-separated lowercase format.

        Examples:
            "aabb.ccdd.eeff"       → "aa:bb:cc:dd:ee:ff"
            "AA-BB-CC-DD-EE-FF"    → "aa:bb:cc:dd:ee:ff"
            "aabbccddeeff"         → "aa:bb:cc:dd:ee:ff"

        Returns raw unchanged if normalization fails.
        netutils format constant: MAC_COLON_TWO
        """
        if not raw or not isinstance(raw, str):
            return raw
        if self._mac_fn is None:
            return raw
        try:
            result = self._mac_fn(raw, "MAC_COLON_TWO")
            return result if result else raw
        except Exception:
            return raw

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_iface_fn():
        try:
            from netutils.interface import canonical_interface_name
            return canonical_interface_name
        except ImportError:
            logger.warning(
                "netutils not installed — interface name normalization disabled. "
                "Run: uv add netutils"
            )
            return None

    @staticmethod
    def _load_mac_fn():
        try:
            from netutils.mac import mac_to_format
            return mac_to_format
        except ImportError:
            return None


# ---------------------------------------------------------------------------
# Module-level singleton (matches SchemaMapper pattern)
# ---------------------------------------------------------------------------

_normalizer: ValueNormalizer | None = None


def get_normalizer() -> ValueNormalizer:
    """Return the singleton ValueNormalizer instance."""
    global _normalizer
    if _normalizer is None:
        _normalizer = ValueNormalizer()
    return _normalizer
