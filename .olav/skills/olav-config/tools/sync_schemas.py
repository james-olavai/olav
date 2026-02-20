"""init_db — Initialize or migrate OLAV DuckDB schema.

olav-config is the infrastructure layer.  Any table creation or schema
migration lives here, not in src/olav/core/database.py.

Call init_db() on first setup or after a schema change.
It is idempotent — safe to call multiple times.
"""

from __future__ import annotations

import logging
from pathlib import Path

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()


@tool
def sync_schemas(force_recreate: bool = False) -> dict:
    """Create or migrate all OLAV DuckDB table schemas.

    Ensures the following tables exist in .olav/databases/main.duckdb:
      - devices           : device inventory (populated by sync_inventory)
      - commands          : command registry — which commands to collect per platform
      - schema_catalog    : JSON field index for parsed_outputs (used by olav-ops LLM)
      - parsed_outputs    : TextFSM-parsed output blobs (written by take_snapshot)
      - topology_links    : CDP/LLDP neighbour relationships
      - sync_metadata     : snapshot run metadata (timing, device count, errors)

    NOTE: audit_results table is intentionally NOT created here.
    olav-audit is a read-only governance layer; findings are written to KB instead.

    Idempotent — uses CREATE TABLE IF NOT EXISTS.
    Call this on first setup or after adding a new table definition.

    Args:
        force_recreate: DROP and recreate all tables. DESTRUCTIVE.
                        Use only in dev/test to reset state.

    Returns:
        {"status": "success", "tables": [...], "action": "created" | "verified"}
    """
    from olav.core.database import get_database

    db = get_database()

    if force_recreate:
        logger.warning("force_recreate=True — dropping all OLAV tables")
        for tbl in ("sync_metadata", "schema_catalog", "commands",
                    "parsed_outputs", "topology_links", "devices"):
            try:
                db.conn.execute(f"DROP TABLE IF EXISTS {tbl}")
            except Exception as e:
                logger.debug(f"Drop {tbl}: {e}")

    # ── devices ──────────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            device_id    VARCHAR PRIMARY KEY,
            name         VARCHAR,
            hostname     VARCHAR,
            platform     VARCHAR,
            mgmt_ip      VARCHAR,
            device_type  VARCHAR,
            device_role  VARCHAR,
            site         VARCHAR,
            location     VARCHAR,
            vendor       VARCHAR,
            model        VARCHAR,
            site_id      VARCHAR,
            created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            is_active    BOOLEAN DEFAULT TRUE
        )
    """)

    # ── commands ─────────────────────────────────────────────────────────────
    # Command registry — which CLI commands to collect per platform.
    # Written by sync_commands(); read by take_snapshot() and olav-ops.
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS commands (
            command_name   VARCHAR NOT NULL,
            platform       VARCHAR NOT NULL,
            category       VARCHAR,
            template_path  VARCHAR,
            has_template   BOOLEAN DEFAULT FALSE,
            allowed        BOOLEAN DEFAULT TRUE,
            blacklisted    BOOLEAN DEFAULT FALSE,
            pipe_allowed   BOOLEAN DEFAULT FALSE,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (command_name, platform)
        )
    """)
    for idx, col in [("idx_cmd_platform", "platform"),
                     ("idx_cmd_category", "category"),
                     ("idx_cmd_allowed", "allowed")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON commands({col})"
        )

    # ── schema_catalog ────────────────────────────────────────────────────────
    # JSON field structure index for parsed_outputs.
    # Written by sync_commands(); read by olav-ops SchemaContext at startup.
    # Enables LLM to generate: SELECT parsed_data->>'field' FROM parsed_outputs
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_catalog (
            source_type    VARCHAR NOT NULL,
            source_name    VARCHAR NOT NULL,
            platform       VARCHAR NOT NULL,
            fields         JSON    NOT NULL,
            description    VARCHAR,
            updated_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_name, platform, source_type)
        )
    """)
    for idx, col in [("idx_sc_platform", "platform"),
                     ("idx_sc_source_type", "source_type")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON schema_catalog({col})"
        )

    # ── parsed_outputs ────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS parsed_outputs_id_seq START 1
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS parsed_outputs (
            id            INTEGER PRIMARY KEY DEFAULT nextval('parsed_outputs_id_seq'),
            device_name   VARCHAR NOT NULL,
            command       VARCHAR NOT NULL,
            parsed_data   JSON    NOT NULL,
            snapshot_date DATE    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(device_name, command, snapshot_date)
        )
    """)
    for idx, col in [("idx_po_device", "device_name"),
                     ("idx_po_command", "command"),
                     ("idx_po_date", "snapshot_date")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON parsed_outputs({col})"
        )

    # ── topology_links ────────────────────────────────────────────────────────
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS topology_links (
            link_id              VARCHAR PRIMARY KEY,
            source_device        VARCHAR NOT NULL,
            source_interface     VARCHAR NOT NULL,
            destination_device   VARCHAR NOT NULL,
            destination_interface VARCHAR NOT NULL,
            discovery_protocol   VARCHAR,
            link_type            VARCHAR,
            link_status          VARCHAR DEFAULT 'up',
            link_speed           VARCHAR,
            first_seen           TIMESTAMP NOT NULL,
            last_seen            TIMESTAMP NOT NULL,
            last_verified        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status_changes       INTEGER DEFAULT 0,
            sync_date            DATE    NOT NULL,
            platform             VARCHAR,
            UNIQUE(source_device, source_interface,
                   destination_device, destination_interface, sync_date)
        )
    """)
    for idx, col in [("idx_tl_src", "source_device"),
                     ("idx_tl_dst", "destination_device"),
                     ("idx_tl_date", "sync_date")]:
        db.conn.execute(
            f"CREATE INDEX IF NOT EXISTS {idx} ON topology_links({col})"
        )

    # ── sync_metadata ─────────────────────────────────────────────────────────
    # Snapshot run metadata: timing, device counts, errors.
    # Previously created at runtime in sync_tools.py; now pre-defined here.
    db.conn.execute("""
        CREATE SEQUENCE IF NOT EXISTS sync_metadata_id_seq START 1
    """)
    db.conn.execute("""
        CREATE TABLE IF NOT EXISTS sync_metadata (
            id            INTEGER PRIMARY KEY DEFAULT nextval('sync_metadata_id_seq'),
            sync_type     VARCHAR NOT NULL,
            start_time    TIMESTAMP NOT NULL,
            end_time      TIMESTAMP,
            status        VARCHAR NOT NULL,
            device_count  INTEGER DEFAULT 0,
            success_count INTEGER DEFAULT 0,
            error_count   INTEGER DEFAULT 0,
            error_details JSON,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sm_type ON sync_metadata(sync_type)"
    )
    db.conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_sm_time ON sync_metadata(start_time)"
    )

    db.conn.commit()

    tables = ["devices", "commands", "schema_catalog",
              "parsed_outputs", "topology_links", "sync_metadata"]
    action = "recreated" if force_recreate else "verified"
    logger.info(f"sync_schemas: {action} tables: {tables}")

    return {
        "status": "success",
        "action": action,
        "tables": tables,
    }
