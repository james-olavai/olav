"""olav_netops Batfish-backed sim primitives."""

from .batfish_capability import BATFISH_VENDOR_SUPPORT, batfish_capability
from .batfish_q import batfish_q

__all__ = ["batfish_q", "batfish_capability", "BATFISH_VENDOR_SUPPORT"]
