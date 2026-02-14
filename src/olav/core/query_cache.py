"""Query Cache - LLM Response Caching for Fast Query Execution

Caches the generated SQL queries to avoid repeated LLM calls.
This dramatically speeds up repeated queries.

Examples:
- First "list all devices": 15s (LLM call) + 0.5s (DB query)
- Second "list all devices": <0.1s (cache hit)
- Speedup: 150x faster on cache hit!
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

from config.paths import CACHE_DIR

logger = logging.getLogger(__name__)


class QueryCache:
    """Simple file-based cache for query results.
    
    Caches both the LLM-generated SQL and the results.
    TTL (Time-To-Live) can be configured to invalidate old caches.
    """

    def __init__(self, cache_dir: Path | str | None = None, ttl_seconds: int = 3600):
        """Initialize cache.
        
        Args:
            cache_dir: Directory to store cache files. Defaults to .olav/cache/
            ttl_seconds: Cache Time-To-Live in seconds. Default 1 hour.
        """
        if cache_dir is None:
            cache_dir = CACHE_DIR
        else:
            cache_dir = Path(cache_dir)

        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_seconds

        # Create cache directory if it doesn't exist
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"[QueryCache] Initialized with dir: {self.cache_dir}, TTL: {ttl_seconds}s")

    def _get_cache_key(self, query: str) -> str:
        """Generate cache key from query string.
        
        Use SHA256 hash to handle long queries and special characters.
        """
        query_normalized = query.strip().lower()
        query_hash = hashlib.sha256(query_normalized.encode()).hexdigest()
        return query_hash[:12]  # Use first 12 chars of hash

    def _get_cache_file(self, cache_key: str) -> Path:
        """Get cache file path for given key."""
        return self.cache_dir / f"{cache_key}.json"

    def get(self, query: str) -> dict[str, Any] | None:
        """Get cached result for query.
        
        Args:
            query: User query string
            
        Returns:
            Cached result dict if found and valid, None otherwise
        """
        cache_key = self._get_cache_key(query)
        cache_file = self._get_cache_file(cache_key)

        # Check if cache file exists
        if not cache_file.exists():
            logger.debug(f"[QueryCache] Miss (no file): {cache_key}")
            return None

        try:
            # Load cache
            with open(cache_file) as f:
                cached = json.load(f)

            # Check TTL
            cached_at = cached.get("cached_at", 0)
            age = time.time() - cached_at

            if age > self.ttl_seconds:
                logger.debug(f"[QueryCache] Expired: {cache_key} (age: {age:.0f}s > {self.ttl_seconds}s)")
                cache_file.unlink()  # Delete expired cache
                return None

            logger.info(f"[QueryCache] ✅ Hit: {cache_key} (age: {age:.0f}s, {age/3600:.1f}h old)")
            return cached.get("result")

        except Exception as e:
            logger.warning(f"[QueryCache] Error reading cache: {e}")
            return None

    def set(self, query: str, result: dict[str, Any]) -> None:
        """Cache query result.
        
        Args:
            query: User query string
            result: Query result dict returned by orchestrate_query_sync()
        """
        cache_key = self._get_cache_key(query)
        cache_file = self._get_cache_file(cache_key)

        try:
            cached_data = {
                "query": query,
                "cached_at": time.time(),
                "ttl_seconds": self.ttl_seconds,
                "result": result,
            }

            with open(cache_file, "w") as f:
                json.dump(cached_data, f, indent=2, default=str)

            logger.debug(f"[QueryCache] Cached: {cache_key}")

        except Exception as e:
            logger.warning(f"[QueryCache] Error writing cache: {e}")

    def clear(self) -> None:
        """Clear all cached queries."""
        try:
            import shutil

            if self.cache_dir.exists():
                shutil.rmtree(self.cache_dir)
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info("[QueryCache] Cleared all cached queries")
        except Exception as e:
            logger.warning(f"[QueryCache] Error clearing cache: {e}")

    def get_stats(self) -> dict[str, int]:
        """Get cache statistics.
        
        Returns:
            Dict with 'total_cached' and 'total_size_bytes'
        """
        total_cached = 0
        total_size = 0

        try:
            for cache_file in self.cache_dir.glob("*.json"):
                total_cached += 1
                total_size += cache_file.stat().st_size
        except Exception as e:
            logger.warning(f"[QueryCache] Error getting stats: {e}")

        return {
            "total_cached": total_cached,
            "total_size_bytes": total_size,
        }
