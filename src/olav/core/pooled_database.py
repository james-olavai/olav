"""Pooled Database Interface - Phase 4 Day 4.

Extends UnifiedDatabase to use connection pooling for improved performance.

Usage:
    # Automatic pooling (context manager recommended)
    with get_pooled_database() as db:
        result = db.query("SELECT * FROM v_interfaces")

    # Or manual
    db = get_pooled_database()
    result = db.query("SELECT ...")
    db.close()  # Returns connection to pool
"""

import threading
from typing import Any

from olav.core.connection_pool import get_connection_pool


class PooledUnifiedDatabase:
    """Unified database wrapper using connection pooling.

    Provides same interface as UnifiedDatabase but uses ConnectionPool
    for reduced initialization overhead.

    Thread-safe for multi-threaded applications.
    """

    _lock = threading.RLock()

    def __init__(self, use_pool: bool = True) -> None:
        """Initialize pooled database.

        Args:
            use_pool: If True, use connection pool; if False, create ephemeral connection
        """
        self.use_pool = use_pool
        self.pool = None
        self.conn = None

        with PooledUnifiedDatabase._lock:
            if use_pool:
                self.pool = get_connection_pool()
                self.conn = self.pool.acquire()
            else:
                # Fallback to ephemeral mode
                from olav.core.unified_database import UnifiedDatabase

                temp_db = UnifiedDatabase()
                self.conn = temp_db.conn
                self.pool = None

    def query(self, sql: str, params: list[Any] | None = None) -> list[tuple]:
        """Execute SQL query (same as UnifiedDatabase)."""
        with PooledUnifiedDatabase._lock:
            if params:
                return self.conn.execute(sql, params).fetchall()
            return self.conn.execute(sql).fetchall()

    def query_df(self, sql: str, params: list[Any] | None = None) -> Any:
        """Execute SQL query and return DataFrame."""
        with PooledUnifiedDatabase._lock:
            if params:
                return self.conn.execute(sql, params).df()
            return self.conn.execute(sql).df()

    def close(self) -> None:
        """Release connection back to pool."""
        if self.conn and self.pool:
            self.pool.release(self.conn)
            self.conn = None

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __del__(self) -> None:
        """Cleanup on deletion."""
        self.close()


def get_pooled_database(use_pool: bool = True) -> PooledUnifiedDatabase:
    """Get a pooled database instance.

    Args:
        use_pool: If True, use connection pool (recommended)

    Returns:
        PooledUnifiedDatabase instance
    """
    return PooledUnifiedDatabase(use_pool=use_pool)
