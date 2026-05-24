"""Backward-compat shim — implementation lives in olav_netops.core.sim.batfish_capability."""
try:
    from olav_netops.core.sim.batfish_capability import (  # noqa: F401
        BATFISH_VENDOR_SUPPORT,
        batfish_capability,
    )
    __all__ = ["BATFISH_VENDOR_SUPPORT", "batfish_capability"]
except ImportError as exc:
    raise ImportError(
        "batfish_capability requires olav-netops — install it with: "
        "pip install olav-netops"
    ) from exc
