"""NETOPS-ONLY DuckDB table declarations.

Registered via pyproject.toml entry-points so that the platform
``IngestManager`` can discover and create these tables at runtime::

    [project.entry-points."olav.ingest_tables"]
    parsed_outputs = "olav_netops.core.tables:ParsedOutputsTable"
    devices        = "olav_netops.core.tables:DevicesTable"
    topology_links = "olav_netops.core.tables:TopologyLinksTable"

All tables live in the ``netops`` DuckDB schema.
"""

from olav.platform.ingest_base import BaseIngestTable, ColumnDef, TableRegistry


class ParsedOutputsTable(BaseIngestTable):
    """Stores parsed CLI output from network devices.

    raw_output is no longer stored inline — it is deduplicated in
    RawOutputStoreTable and referenced via raw_output_hash.
    The raw_output column is kept for backward compatibility but is
    nulled out during ingest migration.
    """

    schema_name = "netops"
    table_name = "parsed_outputs"
    columns = [
        ColumnDef("device_name", "VARCHAR", nullable=False),
        ColumnDef("command", "VARCHAR", nullable=False),
        ColumnDef("parsed_data", "JSON"),
        ColumnDef("snapshot_id", "VARCHAR"),
        ColumnDef("raw_output", "TEXT"),       # legacy — kept for compat, will be NULL
        ColumnDef("raw_output_hash", "VARCHAR"),  # FK → raw_output_store.content_hash
        ColumnDef("ingested_at", "TIMESTAMP"),
    ]
    conflict_key = ["device_name", "command", "snapshot_id"]


class RawOutputStoreTable(BaseIngestTable):
    """Latest raw CLI output per device per command.

    Always keeps the most recent snapshot's raw output — no history,
    no dedup complexity. One row per (device_name, command).
    """

    schema_name = "netops"
    table_name = "raw_output_store"
    columns = [
        ColumnDef("device_name",  "VARCHAR",   nullable=False),
        ColumnDef("command",      "VARCHAR",   nullable=False),
        ColumnDef("raw_output",   "TEXT",      nullable=False),
        ColumnDef("snapshot_id",  "VARCHAR"),
        ColumnDef("updated_at",   "TIMESTAMP"),
    ]
    conflict_key = ["device_name", "command"]


class DevicesTable(BaseIngestTable):
    """Network device inventory."""

    schema_name = "netops"
    table_name = "devices"
    columns = [
        ColumnDef("hostname", "VARCHAR", nullable=False),
        ColumnDef("ip_address", "VARCHAR"),
        ColumnDef("platform", "VARCHAR"),
        ColumnDef("site", "VARCHAR"),
        ColumnDef("role", "VARCHAR"),
        ColumnDef("vendor", "VARCHAR"),
        ColumnDef("model", "VARCHAR"),
        ColumnDef("os_version", "VARCHAR"),
        ColumnDef("last_seen", "TIMESTAMP"),
        ColumnDef("metadata", "JSON"),
    ]
    conflict_key = ["hostname"]


class TopologyLinksTable(BaseIngestTable):
    """CDP/LLDP/OSPF-derived network topology links.

    Schema matches the operational schema used by ``_discover_topology_from_db``
    in sync_tools.py — uses ``link_id`` as primary key.
    """

    schema_name = "netops"
    table_name = "topology_links"
    columns = [
        ColumnDef("link_id",               "VARCHAR",   nullable=False),
        ColumnDef("source_device",         "VARCHAR",   nullable=False),
        ColumnDef("source_interface",      "VARCHAR",   nullable=False),
        ColumnDef("destination_device",    "VARCHAR",   nullable=False),
        ColumnDef("destination_interface", "VARCHAR",   nullable=False),
        ColumnDef("discovery_protocol",    "VARCHAR"),
        ColumnDef("link_type",             "VARCHAR"),
        ColumnDef("link_status",           "VARCHAR"),
        ColumnDef("link_speed",            "VARCHAR"),
        ColumnDef("first_seen",            "TIMESTAMP", nullable=False),
        ColumnDef("last_seen",             "TIMESTAMP", nullable=False),
        ColumnDef("last_verified",         "TIMESTAMP"),
        ColumnDef("status_changes",        "INTEGER"),
        ColumnDef("snapshot_id",           "VARCHAR",   nullable=False),
        ColumnDef("platform",             "VARCHAR"),
    ]
    conflict_key = ["link_id"]


class OcOutputsTable(BaseIngestTable):
    """Strict OpenConfig JSON per device per snapshot per OC module."""

    schema_name = "netops"
    table_name = "oc_outputs"
    columns = [
        ColumnDef("device_name", "VARCHAR", nullable=False),
        ColumnDef("snapshot_id", "VARCHAR", nullable=False),
        ColumnDef("oc_module",   "VARCHAR", nullable=False),
        ColumnDef("oc_data",     "JSON",    nullable=False),
        ColumnDef("source_cmd",  "VARCHAR"),
    ]
    conflict_key = ["device_name", "snapshot_id", "oc_module"]


# Auto-register at import time (entry-point discovery triggers this)
TableRegistry.register(ParsedOutputsTable())
TableRegistry.register(RawOutputStoreTable())
TableRegistry.register(DevicesTable())
TableRegistry.register(TopologyLinksTable())
TableRegistry.register(OcOutputsTable())
