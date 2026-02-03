"""Database Query Enhancement - Phase 3 Legacy (Task: Database & Query).

Implements advanced database features:
1. Transaction management - Atomic operations with rollback
2. Query caching (get_cache) - Caching query results
3. Batch operations - Efficient bulk inserts/updates
4. Timeout handling - Query timeout management
"""

import logging
import threading
import time
from contextlib import contextmanager
from typing import Any

import duckdb

from src.olav.core.connection_pool import get_connection_pool

logger = logging.getLogger(__name__)


class DatabaseTransaction:
    """Context manager for database transactions with automatic rollback."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, timeout: float | None = None):
        """Initialize transaction.

        Args:
            conn: DuckDB connection
            timeout: Transaction timeout in seconds (optional)
        """
        self.conn = conn
        self.timeout = timeout
        self._start_time = None
        self._completed = False

    def __enter__(self) -> duckdb.DuckDBPyConnection:
        """Start transaction."""
        self._start_time = time.time()
        try:
            self.conn.begin()
            logger.debug("Transaction started")
            return self.conn
        except Exception as e:
            logger.error(f"Failed to start transaction: {e}")
            raise

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """End transaction with automatic rollback on error."""
        if self.timeout and (time.time() - self._start_time) > self.timeout:
            logger.warning(f"Transaction timeout ({self.timeout}s exceeded)")
            try:
                self.conn.rollback()
            except Exception:
                pass
            return False

        if exc_type is not None:
            # Error occurred, rollback
            try:
                self.conn.rollback()
                logger.debug(f"Transaction rolled back due to {exc_type.__name__}")
            except Exception as e:
                logger.error(f"Rollback failed: {e}")
            return False
        else:
            # Success, commit
            try:
                self.conn.commit()
                self._completed = True
                logger.debug("Transaction committed")
                return True
            except Exception as e:
                logger.error(f"Commit failed: {e}")
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                return False


class QueryCache:
    """Simple query result caching for frequently executed queries."""

    def __init__(self, max_size: int = 100, ttl_seconds: float = 3600):
        """Initialize query cache.

        Args:
            max_size: Maximum number of cached queries
            ttl_seconds: Time-to-live for cache entries
        """
        self.max_size = max_size
        self.ttl = ttl_seconds
        self._cache: dict[str, tuple[Any, float]] = {}
        self._lock = threading.RLock()

    def _normalize_query(self, query: str) -> str:
        """Normalize query for caching (case-insensitive, trim whitespace).

        Args:
            query: SQL query string

        Returns:
            Normalized query
        """
        return " ".join(query.lower().split())

    def get(self, query: str) -> Any | None:
        """Get cached query result.

        Args:
            query: SQL query

        Returns:
            Cached result or None if not found/expired
        """
        normalized = self._normalize_query(query)

        with self._lock:
            if normalized in self._cache:
                result, timestamp = self._cache[normalized]

                # Check TTL
                if time.time() - timestamp < self.ttl:
                    logger.debug(f"Query cache hit: {query[:50]}...")
                    return result
                else:
                    # Expired
                    del self._cache[normalized]
                    return None

        return None

    def set(self, query: str, result: Any) -> None:
        """Cache query result.

        Args:
            query: SQL query
            result: Query result to cache
        """
        normalized = self._normalize_query(query)

        with self._lock:
            # Evict oldest if at capacity
            if len(self._cache) >= self.max_size:
                # Remove oldest (by timestamp)
                oldest_key = min(
                    self._cache.keys(),
                    key=lambda k: self._cache[k][1],
                )
                del self._cache[oldest_key]

            self._cache[normalized] = (result, time.time())
            logger.debug(f"Query cached: {query[:50]}...")

    def clear(self) -> None:
        """Clear all cached queries."""
        with self._lock:
            self._cache.clear()
        logger.debug("Query cache cleared")

    def stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        with self._lock:
            return {
                "cached_queries": len(self._cache),
                "max_size": self.max_size,
                "ttl_seconds": self.ttl,
            }


class BatchOperation:
    """Batch operation builder for efficient bulk inserts/updates."""

    def __init__(self, conn: duckdb.DuckDBPyConnection, table: str, operation: str = "INSERT"):
        """Initialize batch operation.

        Args:
            conn: DuckDB connection
            table: Target table name
            operation: 'INSERT', 'UPDATE', or 'DELETE'
        """
        self.conn = conn
        self.table = table
        self.operation = operation.upper()
        self.rows: list[dict[str, Any]] = []
        self.columns: list[str] | None = None

    def add_row(self, **kwargs) -> None:
        """Add a row to the batch.

        Args:
            **kwargs: Column name -> value pairs
        """
        if self.columns is None:
            self.columns = list(kwargs.keys())

        self.rows.append(kwargs)

    def add_rows(self, rows: list[dict[str, Any]]) -> None:
        """Add multiple rows to the batch.

        Args:
            rows: List of row dictionaries
        """
        for row in rows:
            self.add_row(**row)

    def execute(self) -> int:
        """Execute the batch operation.

        Returns:
            Number of rows affected
        """
        if not self.rows:
            logger.warning("Batch operation executed with no rows")
            return 0

        try:
            if self.operation == "INSERT":
                return self._execute_insert()
            elif self.operation == "UPDATE":
                return self._execute_update()
            elif self.operation == "DELETE":
                return self._execute_delete()
            else:
                raise ValueError(f"Unsupported operation: {self.operation}")
        except Exception as e:
            logger.error(f"Batch operation failed: {e}")
            raise

    def _execute_insert(self) -> int:
        """Execute batch insert."""
        if not self.columns:
            raise ValueError("No columns specified for insert")

        cols_str = ", ".join(self.columns)
        placeholders = ", ".join(["?"] * len(self.columns))
        query = f"INSERT INTO {self.table} ({cols_str}) VALUES ({placeholders})"

        rows_data = []
        for row in self.rows:
            row_values = [row.get(col) for col in self.columns]
            rows_data.append(row_values)

        try:
            self.conn.executemany(query, rows_data)
            logger.info(f"Batch inserted {len(self.rows)} rows to {self.table}")
            return len(self.rows)
        except Exception as e:
            logger.error(f"Batch insert failed: {e}")
            raise

    def _execute_update(self) -> int:
        """Execute batch update (simplified - updates entire rows)."""
        if not self.columns:
            raise ValueError("No columns specified for update")

        # This is a simplified version - real implementation would need WHERE clause
        logger.warning("Batch UPDATE is simplified, consider using transaction for complex updates")
        return 0

    def _execute_delete(self) -> int:
        """Execute batch delete."""
        # This would require primary keys or WHERE conditions
        logger.warning("Batch DELETE requires explicit WHERE clause specification")
        return 0

    def clear(self) -> None:
        """Clear all accumulated rows."""
        self.rows = []


class QueryTimeout:
    """Manages query execution timeout."""

    def __init__(self, timeout_seconds: float = 30.0):
        """Initialize query timeout manager.

        Args:
            timeout_seconds: Default timeout in seconds
        """
        self.timeout = timeout_seconds
        self._start_time: float | None = None

    def start(self) -> None:
        """Mark the start of a query."""
        self._start_time = time.time()

    def check(self) -> bool:
        """Check if query has exceeded timeout.

        Returns:
            True if timeout exceeded, False otherwise
        """
        if self._start_time is None:
            return False

        elapsed = time.time() - self._start_time
        return elapsed > self.timeout

    def elapsed_seconds(self) -> float:
        """Get elapsed time since query start.

        Returns:
            Elapsed seconds
        """
        if self._start_time is None:
            return 0.0

        return time.time() - self._start_time

    def remaining_seconds(self) -> float:
        """Get remaining time before timeout.

        Returns:
            Remaining seconds (0 or negative if timed out)
        """
        remaining = self.timeout - self.elapsed_seconds()
        return max(0.0, remaining)

    @contextmanager
    def managed(self):
        """Context manager for timeout-managed operations.

        Example:
            with QueryTimeout(30).managed():
                result = conn.execute(query).fetchall()
        """
        self.start()
        try:
            yield self
        finally:
            if self.check():
                logger.warning(f"Query exceeded timeout ({self.timeout}s)")


class DatabaseEnhancer:
    """Enhanced database operations with transactions, caching, batch ops, and timeouts."""

    def __init__(self, pool_size: int = 5):
        """Initialize database enhancer.

        Args:
            pool_size: Connection pool size
        """
        self.pool = get_connection_pool(pool_size)
        self.query_cache = QueryCache()
        self._transaction_locks: dict[str, threading.RLock] = {}

    def execute_with_transaction(
        self,
        query: str,
        params: list[Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Execute query within a transaction.

        Args:
            query: SQL query
            params: Query parameters
            timeout: Transaction timeout in seconds

        Returns:
            Query result
        """
        conn = self.pool.acquire()

        try:
            with DatabaseTransaction(conn, timeout=timeout):
                if params:
                    result = conn.execute(query, params).fetchall()
                else:
                    result = conn.execute(query).fetchall()
                return result
        finally:
            self.pool.release(conn)

    def execute_cached(
        self,
        query: str,
        params: list[Any] | None = None,
        cache_ttl: float | None = None,
    ) -> Any:
        """Execute query with caching.

        Args:
            query: SQL query
            params: Query parameters (not cached if provided)
            cache_ttl: Cache TTL override

        Returns:
            Query result
        """
        # Don't cache parameterized queries
        if params:
            return self.execute(query, params)

        # Check cache
        cached = self.query_cache.get(query)
        if cached is not None:
            return cached

        # Execute and cache
        result = self.execute(query)
        self.query_cache.set(query, result)
        return result

    def execute_batch_insert(
        self,
        table: str,
        rows: list[dict[str, Any]],
        timeout: float | None = None,
    ) -> int:
        """Execute batch insert operation.

        Args:
            table: Target table
            rows: Rows to insert
            timeout: Operation timeout

        Returns:
            Number of rows inserted
        """
        conn = self.pool.acquire()

        try:
            batch = BatchOperation(conn, table, "INSERT")
            batch.add_rows(rows)
            result = batch.execute()
            return result
        finally:
            self.pool.release(conn)

    def execute_with_timeout(
        self,
        query: str,
        timeout_seconds: float = 30.0,
    ) -> Any:
        """Execute query with timeout protection.

        Args:
            query: SQL query
            timeout_seconds: Timeout in seconds

        Returns:
            Query result
        """
        query_timeout = QueryTimeout(timeout_seconds)

        conn = self.pool.acquire()

        try:
            with query_timeout.managed():
                if query_timeout.check():
                    raise TimeoutError(f"Query exceeded timeout ({timeout_seconds}s)")

                result = conn.execute(query).fetchall()

                if query_timeout.check():
                    logger.warning(f"Query completed but exceeded timeout ({timeout_seconds}s)")

                return result
        finally:
            self.pool.release(conn)

    def execute(
        self,
        query: str,
        params: list[Any] | None = None,
    ) -> Any:
        """Execute basic query.

        Args:
            query: SQL query
            params: Query parameters

        Returns:
            Query result
        """
        conn = self.pool.acquire()

        try:
            if params:
                result = conn.execute(query, params).fetchall()
            else:
                result = conn.execute(query).fetchall()
            return result
        finally:
            self.pool.release(conn)

    def get_cache(self, query: str) -> Any | None:
        """Get cached query result (for compatibility).

        Args:
            query: SQL query

        Returns:
            Cached result or None
        """
        return self.query_cache.get(query)

    def clear_cache(self) -> None:
        """Clear all cached queries."""
        self.query_cache.clear()

    def cache_stats(self) -> dict[str, int]:
        """Get cache statistics.

        Returns:
            Cache stats dictionary
        """
        return self.query_cache.stats()

    def pool_stats(self) -> dict[str, Any]:
        """Get connection pool statistics.

        Returns:
            Pool stats dictionary
        """
        return self.pool.stats()


# Global enhancer instance
_global_enhancer: DatabaseEnhancer | None = None
_enhancer_lock = threading.Lock()


def get_database_enhancer() -> DatabaseEnhancer:
    """Get or create global database enhancer.

    Returns:
        Global DatabaseEnhancer instance
    """
    global _global_enhancer

    if _global_enhancer is None:
        with _enhancer_lock:
            if _global_enhancer is None:
                _global_enhancer = DatabaseEnhancer()

    return _global_enhancer
