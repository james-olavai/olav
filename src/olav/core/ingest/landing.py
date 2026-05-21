"""Backward-compat shim — implementation lives in olav_netops.core.ingest.landing.

``ingest_snapshot`` is a netops-domain function: it manages netops schema,
migrations, and ETL.  The canonical location is the olav-netops package.
This shim re-exports so existing callers (tests, etc.) don't need updating.
"""
from __future__ import annotations

try:
    from olav_netops.core.ingest.landing import (  # noqa: F401
        IngestResult,
        ingest_snapshot,
    )
    __all__ = ["IngestResult", "ingest_snapshot"]
except ImportError as exc:
    raise ImportError(
        "ingest_snapshot requires olav-netops — install it with: "
        "pip install olav-netops"
    ) from exc
