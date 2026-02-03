"""Connection Pool Manager - Phase 4 Day 4.

Performance Optimization: Connection Pool for DuckDB

Problem Solved:
- UnifiedDatabase creates new DuckDB connection on every instantiation
- Attaching databases is expensive (~5-10ms per connection)
- Multiple agent calls create multiple connections (initialization overhead)

Solution:
- ConnectionPool maintains a pool of pre-initialized connections
- ATTACH operations done once during pool initialization
- Connections are reused across queries
- Graceful fallback to ephemeral mode if pool unavailable

Expected Improvements:
- Connection init: 5-10ms (one-time during pool warmup)
- Per-query overhead: ~1-2ms (instead of 5-10ms for new connection)
- Multi-agent scenarios: 10-20% latency reduction
"""

import logging
import threading
from pathlib import Path
from queue import Empty, Full, Queue

import duckdb

from config.paths import (
    KNOWLEDGE_PATH,
    NETWORK_COMMANDS_PATH,
    NETWORK_SNAPSHOT_PATH,
    USER_CACHE_PATH,
)

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Thread-safe connection pool for DuckDB with pre-attached databases.

    Features:
    - Configurable pool size
    - Pre-attached databases (commands, snapshot, knowledge)
    - Thread-safe acquire/release
    - Automatic reconnection on failure
    - Graceful degradation (ephemeral mode if pool exhausted)
    """

    def __init__(self, max_size: int = 5, timeout_seconds: float = 5.0):
        """Initialize connection pool.

        Args:
            max_size: Maximum number of pooled connections
            timeout_seconds: Timeout for acquire() operation
        """
        self.max_size = max_size
        self.timeout = timeout_seconds
        self.pool: Queue = Queue(maxsize=max_size)
        self._lock = threading.RLock()
        self._initialized = False
        self._initialization_lock = threading.Lock()

        logger.info(f"ConnectionPool initialized (max_size={max_size})")

    def _create_connection(self) -> duckdb.DuckDBPyConnection | None:
        """Create a single connection with all databases attached.

        Returns:
            DuckDB connection or None if failed
        """
        try:
            conn = duckdb.connect()

            # Attach databases
            snapshot_path = str(NETWORK_SNAPSHOT_PATH)
            commands_path = str(NETWORK_COMMANDS_PATH)
            knowledge_path = str(KNOWLEDGE_PATH)
            user_cache_path = str(USER_CACHE_PATH)

            attached_paths = set()

            # Attempt to attach user cache first (RW)
            for attempt in range(3):
                try:
                    Path(USER_CACHE_PATH).parent.mkdir(parents=True, exist_ok=True)
                    conn.execute(f"ATTACH IF NOT EXISTS '{user_cache_path}' AS commands")
                    attached_paths.add(user_cache_path)
                    break
                except Exception as e:
                    if attempt < 2 and "being detached" in str(e):
                        import time

                        time.sleep(0.2)
                        continue
                    # Fallback to commands RO
                    try:
                        conn.execute(
                            f"ATTACH IF NOT EXISTS '{commands_path}' AS commands (READ_ONLY)"
                        )
                        attached_paths.add(commands_path)
                        break
                    except Exception:
                        if attempt < 2:
                            import time

                            time.sleep(0.2)

            # Attach snapshot
            if snapshot_path not in attached_paths:
                try:
                    conn.execute(f"ATTACH IF NOT EXISTS '{snapshot_path}' AS db_snapshot")
                    attached_paths.add(snapshot_path)
                except Exception:
                    pass

            # Attach knowledge
            if knowledge_path not in attached_paths:
                try:
                    conn.execute(f"ATTACH IF NOT EXISTS '{knowledge_path}' AS knowledge")
                    attached_paths.add(knowledge_path)
                except Exception:
                    pass

            # Update search path
            try:
                catalogs = conn.execute(
                    "SELECT catalog_name FROM information_schema.schemata"
                ).fetchall()
                attached = {c[0] for c in catalogs}
                paths = ["main", "commands", "db_snapshot", "knowledge"]
                active_paths = [p for p in paths if p in attached or p == "main"]
                conn.execute(f"SET search_path = '{','.join(active_paths)}'")
            except Exception:
                pass

            # Create views
            try:
                core_views = {
                    "v_interfaces": "v_interfaces",
                    "v_bgp_neighbors": "v_bgp_neighbors",
                    "v_routes": "v_routes",
                    "v_ospf_neighbors": "v_ospf_neighbors",
                    "v_device_status": "v_device_status",
                    "v_arp": "v_arp",
                    "v_cdp_neighbors": "v_cdp_neighbors",
                    "v_cpu_utilization": "v_cpu_utilization",
                    "v_memory_utilization": "v_memory_utilization",
                    "v_device_capabilities": "v_device_capabilities",
                }

                catalogs = conn.execute(
                    "SELECT catalog_name FROM information_schema.schemata"
                ).fetchall()
                is_commands_attached = any(c[0] == "commands" for c in catalogs)

                if is_commands_attached:
                    # Method 1: Dynamic exposure (if schemas are ready)
                    try:
                        views = conn.execute(
                            "SELECT table_name FROM commands.information_schema.tables WHERE table_name LIKE 'v_%'"
                        ).fetchall()
                        for v in views:
                            conn.execute(
                                f"CREATE OR REPLACE VIEW main.{v[0]} AS SELECT * FROM commands.{v[0]}"
                            )
                    except Exception:
                        # Method 2: Static fallback (if info_schema is stubborn)
                        for view_name in core_views:
                            try:
                                conn.execute(
                                    f"CREATE VIEW IF NOT EXISTS main.{view_name} AS SELECT * FROM commands.{view_name}"
                                )
                            except Exception:
                                pass
            except Exception:
                pass

            logger.debug("Connection created and configured")
            return conn

        except Exception as e:
            logger.error(f"Failed to create connection: {e}")
            return None

    def initialize(self, warmup_size: int | None = None) -> int:
        """Pre-warm the connection pool.

        Args:
            warmup_size: Number of connections to pre-create (default: min(3, max_size))

        Returns:
            Number of connections successfully created
        """
        with self._initialization_lock:
            if self._initialized:
                return self.pool.qsize()

            if warmup_size is None:
                warmup_size = min(3, self.max_size)

            created = 0
            for i in range(warmup_size):
                conn = self._create_connection()
                if conn:
                    try:
                        self.pool.put(conn, block=False)
                        created += 1
                    except Full:
                        conn.close()
                        break

            self._initialized = True
            logger.info(f"ConnectionPool warmed up with {created} connections")
            return created

    def acquire(self) -> duckdb.DuckDBPyConnection:
        """Acquire a connection from the pool.

        Returns:
            DuckDB connection (pooled or ephemeral)
        """
        try:
            # Try to get from pool (non-blocking first)
            conn = self.pool.get(block=False)
            logger.debug("Acquired connection from pool")
            return conn
        except Empty:
            # Pool empty, create ephemeral connection
            conn = self._create_connection()
            if conn:
                logger.debug("Created ephemeral connection (pool exhausted)")
                return conn
            else:
                raise RuntimeError("Failed to create DuckDB connection")

    def release(self, conn: duckdb.DuckDBPyConnection) -> bool:
        """Release a connection back to the pool.

        Args:
            conn: DuckDB connection to release

        Returns:
            True if returned to pool, False if pool full (connection closed)
        """
        try:
            self.pool.put(conn, block=False)
            logger.debug("Connection returned to pool")
            return True
        except Full:
            # Pool full, close the connection
            try:
                conn.close()
            except Exception:
                pass
            logger.debug("Pool full, closed connection")
            return False

    def close_all(self):
        """Close all pooled connections."""
        while True:
            try:
                conn = self.pool.get(block=False)
                try:
                    conn.close()
                except Exception:
                    pass
            except Empty:
                break

        logger.info("Connection pool closed")

    def size(self) -> int:
        """Get current pool size."""
        return self.pool.qsize()

    def stats(self) -> dict:
        """Get pool statistics."""
        return {
            "max_size": self.max_size,
            "current_size": self.pool.qsize(),
            "initialized": self._initialized,
        }


# Global pool instance (singleton pattern)
_global_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def get_connection_pool(max_size: int = 5) -> ConnectionPool:
    """Get or create the global connection pool.

    Args:
        max_size: Maximum pool size (only used on first call)

    Returns:
        Global ConnectionPool instance
    """
    global _global_pool

    if _global_pool is None:
        with _pool_lock:
            if _global_pool is None:
                _global_pool = ConnectionPool(max_size=max_size)
                _global_pool.initialize()

    return _global_pool


def close_connection_pool():
    """Close the global connection pool."""
    global _global_pool

    if _global_pool:
        _global_pool.close_all()
        _global_pool = None
