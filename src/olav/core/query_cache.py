"""Query Result Cache - Phase 4 Day 5-6.

Performance Optimization: Result-level caching for expensive queries

Problem:
- LLM inference: 20-30 seconds per query (4000x slower than DB)
- Repeated queries waste compute and time
- Current semantic cache in router has low hit rate

Solution:
- 2-tier cache: L1 (memory LRU) + L2 (disk SQLite)
- Cache complete query results (post-LLM)
- Intelligent key generation (normalized query + context)
- TTL-based invalidation

Expected Impact:
- Cache hit rate: 60-80% for common queries
- Latency for cached queries: <100ms (instead of 20s)
- Overall average latency reduction: 60-70%
"""

import hashlib
import json
import logging
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.paths import CACHE_DIR

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Query result cache entry."""

    key: str
    result: dict[str, Any]
    created_at: float
    ttl_seconds: int
    metadata: dict[str, Any]

    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.ttl_seconds <= 0:  # Never expire
            return False
        return (time.time() - self.created_at) > self.ttl_seconds


class QueryResultCache:
    """2-tier query result cache with LRU memory + SQLite disk.

    Architecture:
    - L1: In-memory LRU cache (fast, capacity-limited)
    - L2: SQLite disk cache (persistent, larger capacity)
    - Read: L1 → L2 → compute → write L2 → promote L1
    - Write: Write L2 immediately, promote hot entries to L1

    Features:
    - Thread-safe
    - TTL-based expiration
    - Configurable capacity
    - Query normalization for better hit rate
    """

    def __init__(
        self,
        db_path: Path | None = None,
        l1_max_size: int = 100,
        ttl_seconds: int = 3600,
    ):
        """Initialize query result cache.

        Args:
            db_path: Path to SQLite cache database
            l1_max_size: Max entries in L1 cache
            ttl_seconds: Default TTL for cache entries
        """
        self.db_path = db_path or (CACHE_DIR / "query_result_cache.db")
        self.l1_max_size = l1_max_size
        self.ttl_seconds = ttl_seconds

        # L1: In-memory LRU (OrderedDict for move_to_end support)
        self._l1_cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._l1_lock = threading.RLock()

        # L2: SQLite connection (thread-local)
        self._local = threading.local()

        # Initialize L2 database
        self._init_db()

        logger.info(f"QueryResultCache initialized (L1={l1_max_size}, TTL={ttl_seconds}s)")

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local SQLite connection."""
        if not hasattr(self._local, "conn"):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    def _init_db(self):
        """Initialize SQLite cache database schema."""
        conn = self._get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS query_cache (
                cache_key TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                ttl_seconds INTEGER NOT NULL,
                metadata_json TEXT,
                hit_count INTEGER DEFAULT 0,
                last_accessed REAL
            )
        """)

        # Index for TTL cleanup
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_created_at 
            ON query_cache(created_at)
        """)

        conn.commit()
        logger.debug("Query cache database initialized")

    @staticmethod
    def normalize_query(query_text: str) -> str:
        """Normalize query for better cache hit rate.

        Normalization:
        - Lowercase
        - Strip whitespace
        - Remove extra spaces

        Args:
            query_text: Raw query string

        Returns:
            Normalized query string
        """
        normalized = query_text.lower().strip()
        normalized = " ".join(normalized.split())  # Collapse whitespace
        return normalized

    @staticmethod
    def generate_cache_key(
        query_text: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate cache key from query + context.

        Args:
            query_text: Query string
            context: Additional context (skill_id, params, etc.)

        Returns:
            SHA256 hash as cache key
        """
        normalized = QueryResultCache.normalize_query(query_text)

        # Include context in key
        key_data = {"query": normalized}
        if context:
            key_data["context"] = context

        key_json = json.dumps(key_data, sort_keys=True)
        cache_key = hashlib.sha256(key_json.encode()).hexdigest()

        return cache_key

    def get(
        self,
        query_text: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Get cached query result.

        Args:
            query_text: Query string
            context: Additional context

        Returns:
            Cached result dict or None if miss/expired
        """
        cache_key = self.generate_cache_key(query_text, context)

        # L1 lookup
        with self._l1_lock:
            if cache_key in self._l1_cache:
                entry = self._l1_cache[cache_key]
                if not entry.is_expired():
                    logger.debug(f"Cache HIT (L1): {cache_key[:16]}...")
                    # Move to end (LRU)
                    self._l1_cache.move_to_end(cache_key)
                    return entry.result
                else:
                    # Expired, remove
                    del self._l1_cache[cache_key]
                    logger.debug(f"Cache EXPIRED (L1): {cache_key[:16]}...")

        # L2 lookup
        conn = self._get_conn()
        row = conn.execute(
            "SELECT * FROM query_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()

        if row:
            created_at = row["created_at"]
            ttl = row["ttl_seconds"]
            is_expired = (ttl > 0) and ((time.time() - created_at) > ttl)

            if not is_expired:
                result = json.loads(row["result_json"])
                metadata = json.loads(row["metadata_json"]) if row["metadata_json"] else {}

                # Update hit stats
                conn.execute(
                    "UPDATE query_cache SET hit_count = hit_count + 1, last_accessed = ? WHERE cache_key = ?",
                    (time.time(), cache_key),
                )
                conn.commit()

                # Promote to L1
                entry = CacheEntry(
                    key=cache_key,
                    result=result,
                    created_at=created_at,
                    ttl_seconds=ttl,
                    metadata=metadata,
                )
                self._promote_to_l1(entry)

                logger.debug(f"Cache HIT (L2): {cache_key[:16]}...")
                return result
            else:
                # Expired, cleanup
                conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (cache_key,))
                conn.commit()
                logger.debug(f"Cache EXPIRED (L2): {cache_key[:16]}...")

        logger.debug(f"Cache MISS: {cache_key[:16]}...")
        return None

    def set(
        self,
        query_text: str,
        result: dict[str, Any],
        context: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        """Store query result in cache.

        Args:
            query_text: Query string
            result: Query result to cache
            context: Additional context
            ttl_seconds: TTL override (default: instance TTL)
            metadata: Optional metadata
        """
        cache_key = self.generate_cache_key(query_text, context)
        ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        created_at = time.time()

        entry = CacheEntry(
            key=cache_key,
            result=result,
            created_at=created_at,
            ttl_seconds=ttl,
            metadata=metadata or {},
        )

        # Write to L2 (persistent)
        conn = self._get_conn()
        conn.execute(
            """
            INSERT OR REPLACE INTO query_cache 
            (cache_key, result_json, created_at, ttl_seconds, metadata_json, hit_count, last_accessed)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (
                cache_key,
                json.dumps(result),
                created_at,
                ttl,
                json.dumps(metadata) if metadata else None,
                created_at,
            ),
        )
        conn.commit()

        # Promote to L1 if space available
        self._promote_to_l1(entry)

        logger.debug(f"Cache SET: {cache_key[:16]}... (TTL={ttl}s)")

    def _promote_to_l1(self, entry: CacheEntry):
        """Promote entry to L1 cache (with LRU eviction)."""
        with self._l1_lock:
            # If at capacity, evict oldest
            if len(self._l1_cache) >= self.l1_max_size:
                # Remove first item (oldest)
                oldest_key = next(iter(self._l1_cache))
                del self._l1_cache[oldest_key]
                logger.debug(f"L1 eviction: {oldest_key[:16]}...")

            # Add new entry at end
            self._l1_cache[entry.key] = entry
            logger.debug(f"L1 promotion: {entry.key[:16]}...")

    def invalidate(self, query_text: str, context: dict[str, Any] | None = None):
        """Invalidate cached entry."""
        cache_key = self.generate_cache_key(query_text, context)

        # Remove from L1
        with self._l1_lock:
            if cache_key in self._l1_cache:
                del self._l1_cache[cache_key]

        # Remove from L2
        conn = self._get_conn()
        conn.execute("DELETE FROM query_cache WHERE cache_key = ?", (cache_key,))
        conn.commit()

        logger.debug(f"Cache INVALIDATE: {cache_key[:16]}...")

    def cleanup_expired(self) -> int:
        """Remove expired entries from L2.

        Returns:
            Number of entries removed
        """
        conn = self._get_conn()

        # Find expired entries
        current_time = time.time()
        cursor = conn.execute("""
            SELECT cache_key, created_at, ttl_seconds 
            FROM query_cache 
            WHERE ttl_seconds > 0
        """)

        expired_keys = []
        for row in cursor:
            if (current_time - row["created_at"]) > row["ttl_seconds"]:
                expired_keys.append(row["cache_key"])

        # Delete expired
        if expired_keys:
            placeholders = ",".join(["?"] * len(expired_keys))
            conn.execute(
                f"DELETE FROM query_cache WHERE cache_key IN ({placeholders})",
                expired_keys,
            )
            conn.commit()
            logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

        return len(expired_keys)

    def clear(self) -> None:
        """Clear all cache entries (L1 + L2).

        WARNING: This clears ALL cached results. Use only for testing.
        """
        with self._l1_lock:
            # Clear L1
            self._l1_cache.clear()
            logger.debug("Cleared L1 cache")

            # Clear L2
            conn = self._get_conn()
            conn.execute("DELETE FROM query_cache")
            conn.commit()
            logger.info("Cleared all cache entries (L1+L2)")

    def stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dict with cache stats
        """
        conn = self._get_conn()

        # L2 stats
        row = conn.execute("""
            SELECT 
                COUNT(*) as total_entries,
                SUM(hit_count) as total_hits,
                AVG(hit_count) as avg_hits_per_entry
            FROM query_cache
        """).fetchone()

        l2_total = row["total_entries"] if row else 0
        l2_hits = row["total_hits"] if row else 0

        # L1 stats
        with self._l1_lock:
            l1_size = len(self._l1_cache)

        return {
            "l1_size": l1_size,
            "l1_max_size": self.l1_max_size,
            "l2_total_entries": l2_total,
            "l2_total_hits": l2_hits,
            "ttl_seconds": self.ttl_seconds,
        }


# Global cache instance
_global_cache: QueryResultCache | None = None
_cache_lock = threading.Lock()


def get_query_cache() -> QueryResultCache:
    """Get or create global query result cache."""
    global _global_cache

    if _global_cache is None:
        with _cache_lock:
            if _global_cache is None:
                _global_cache = QueryResultCache()

    return _global_cache
