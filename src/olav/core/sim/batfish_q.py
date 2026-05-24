"""Backward-compat shim — implementation lives in olav_netops.core.sim.batfish_q."""
try:
    from olav_netops.core.sim.batfish_q import batfish_q  # noqa: F401
    __all__ = ["batfish_q"]
except ImportError as exc:
    raise ImportError(
        "batfish_q requires olav-netops — install it with: "
        "pip install olav-netops"
    ) from exc
