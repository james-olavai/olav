"""DuckDB database module for OLAV v0.9.

This module provides the core database functionality for storing and querying
audit logs and command caches.

NOTE: The capabilities table has been removed in v0.9 and replaced by the
file-based CommandRegistry (see olav.core.registry). Command discovery and
validation is now handled through TextFSM templates rather than database entries.
"""

from pathlib import Path

# Thread lock for concurrent database access
from threading import Lock

import duckdb

_db_lock = Lock()


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
            from olav.core.config import MAIN_DB_PATH

            db_path = MAIN_DB_PATH

        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Connect to DuckDB
        self.conn = duckdb.connect(str(self.db_path), read_only=read_only)

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
    """Get the global database instance with thread-safe access.

    Args:
        db_path: Optional database path (uses default if not provided)
        read_only: Whether to open in read-only mode

    Returns:
        OlavDatabase instance
    """
    global _db_instance

    with _db_lock:
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
