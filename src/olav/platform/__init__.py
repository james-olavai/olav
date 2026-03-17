"""OLAV Platform public API layer.

Domain packages (olav-netops, olav-k8sops, etc.) import from here
instead of internal olav.core modules.

Stability guarantee
-------------------
This module is the **Stable Public API** (dev_docs/olav_platform.md §11.7).
Backward compatibility is maintained within minor versions.

Quickstart
----------
::

    from olav.platform import (
        DomainAgent,        # Protocol — implement this in your domain agent
        BaseDomainAgent,    # Optional concrete base class
        BaseIngestTable,    # Subclass to declare your DuckDB tables
        ColumnDef,          # Column definition helper
        TableRegistry,      # Register tables so IngestManager auto-creates them
    )
"""

from olav.platform.agent_base import BaseDomainAgent
from olav.platform.extensions import DomainAgent
from olav.platform.ingest_base import BaseIngestTable, ColumnDef, TableRegistry

__all__ = [
    "DomainAgent",
    "BaseDomainAgent",
    "BaseIngestTable",
    "ColumnDef",
    "TableRegistry",
]
