"""DuckDB database module for OLAV v0.9.

This module provides the core database functionality for storing and querying
audit logs and command caches.

NOTE: The capabilities table has been removed in v0.9 and replaced by the
file-based CommandRegistry (see olav.core.registry). Command discovery and
validation is now handled through TextFSM templates rather than database entries.
"""

from pathlib import Path

import duckdb


class OlavDatabase:
    """OLAV database manager using DuckDB.

    This database stores:
    - audit_logs: Execution history and audit trail
    - command_cache: Cached command outputs (optional, not used in MVP)

    NOTE: The capabilities table has been removed. Use CommandRegistry for
    command discovery and validation.
    """

    def __init__(self, db_path: str | Path | None = None, read_only: bool = False) -> None:
        """Initialize database connection.

        Args:
            db_path: Path to DuckDB database file
            read_only: Whether to open in read-only mode (default: False)
        """
        if db_path is None:
            from config.paths import NETWORK_DB_PATH

            db_path = NETWORK_DB_PATH

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to DuckDB
        self.conn = duckdb.connect(str(self.db_path), read_only=read_only)

        # Initialize schema (skip if read-only)
        if not read_only:
            self._init_schema()

    def _init_schema(self) -> None:
        """Create database tables if they don't exist.
        
        OLAV v2.0 simplified schema - only 3 core tables:
        1. devices - Nornir device inventory
        2. parsed_outputs - TextFSM/Genie parsed JSON
        3. topology_links - CDP/LLDP neighbor relationships
        """
        # Devices table (device metadata - v0.11.0 unified with Nornir import)
        # Note: This is auto-populated by sync_inventory() from hosts.yaml
        # DO NOT modify schema manually - always use sync_inventory() for updates
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id VARCHAR PRIMARY KEY,
                name VARCHAR,
                hostname VARCHAR,
                platform VARCHAR,
                mgmt_ip VARCHAR,
                device_type VARCHAR,
                device_role VARCHAR,
                site VARCHAR,
                location VARCHAR,
                vendor VARCHAR,
                model VARCHAR,
                site_id VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE
            )
        """)

        # Topology links table (v0.10.2 - network topology with history)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS topology_links (
                link_id VARCHAR PRIMARY KEY,
                source_device VARCHAR NOT NULL,
                source_interface VARCHAR NOT NULL,
                destination_device VARCHAR NOT NULL,
                destination_interface VARCHAR NOT NULL,
                discovery_protocol VARCHAR,
                link_type VARCHAR,
                link_status VARCHAR DEFAULT 'up',
                link_speed VARCHAR,
                first_seen TIMESTAMP NOT NULL,
                last_seen TIMESTAMP NOT NULL,
                last_verified TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status_changes INTEGER DEFAULT 0,
                sync_date DATE NOT NULL,
                platform VARCHAR,
                UNIQUE(source_device, source_interface, destination_device, destination_interface, sync_date)
            )
        """)
        
        # Indexes for topology queries
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topology_src ON topology_links(source_device)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topology_dst ON topology_links(destination_device)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_topology_sync_date ON topology_links(sync_date)
        """)

        # Parsed outputs table (TextFSM/Genie parsed JSON)
        self.conn.execute("""
            CREATE SEQUENCE IF NOT EXISTS parsed_outputs_id_seq START 1
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS parsed_outputs (
                id INTEGER PRIMARY KEY DEFAULT nextval('parsed_outputs_id_seq'),
                device_name VARCHAR NOT NULL,
                command VARCHAR NOT NULL,
                parsed_data JSON NOT NULL,
                snapshot_date DATE NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(device_name, command, snapshot_date)
            )
        """)

        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_parsed_device ON parsed_outputs(device_name)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_parsed_command ON parsed_outputs(command)
        """)
        self.conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_parsed_date ON parsed_outputs(snapshot_date)
        """)

        # Note: All other tables removed in v2.0 DeepAgents simplification
        # - device_capabilities → removed (LLM handles capability detection)
        # - sync_metadata → removed (not used)
        # - knowledge_chunks → removed (moved to separate system)
        # - audit_logs → removed (use structured logging instead)
        # - routes, bgp_neighbors, ospf_neighbors, vlans, arp_table → removed (use parsed_outputs)
        # - system_info, health_scores → removed (use parsed_outputs)

    def close(self) -> None:
        """Close the database connection."""
        self.conn.close()

    def __enter__(self) -> "OlavDatabase":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        """Context manager exit."""
        self.close()


# Global database instance
_db_instance: OlavDatabase | None = None


def get_database(db_path: str | Path | None = None, read_only: bool = False) -> OlavDatabase:
    """Get the global database instance.

    Args:
        db_path: Optional database path (uses default if not provided)
        read_only: Whether to open in read-only mode

    Returns:
        OlavDatabase instance
    """
    global _db_instance

    if _db_instance is None:
        _db_instance = OlavDatabase(db_path, read_only=read_only)

    return _db_instance


def reset_database() -> None:
    """Reset the global database instance.

    Use this in tests to ensure clean state between test runs.
    """
    global _db_instance
    if _db_instance is not None:
        try:
            _db_instance.close()
        except Exception:  # noqa: S110
            pass
        _db_instance = None


# =============================================================================
# Note: init_knowledge_db(), init_topology_db(), init_structured_tables() removed
