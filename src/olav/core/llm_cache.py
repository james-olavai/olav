#!/usr/bin/env python3
"""
LLM Cache Configuration - Setup embedding cache and response caching for OLAV.

Uses LangChain's SQLiteCache for lightweight, portable caching.
Compatible with .olav/databases/llm_cache.db from Phase 2.
"""

import os
import logging
from pathlib import Path
from typing import Optional

try:
    from langchain.globals import set_llm_cache
    from langchain_community.cache import SQLiteCache
except ImportError:
    SQLiteCache = None
    set_llm_cache = None

logger = logging.getLogger(__name__)


class LLMCacheManager:
    """Manage LLM response caching using SQLite."""

    def __init__(self, cache_db_path: str = ".olav/databases/llm_cache.db"):
        """Initialize LLM cache manager.

        Args:
            cache_db_path: Path to SQLite cache database
        """
        self.cache_db_path = Path(cache_db_path)
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache: Optional[SQLiteCache] = None

    def initialize(self) -> bool:
        """Initialize the LLM cache.

        Returns:
            True if cache initialized successfully
        """
        if SQLiteCache is None or set_llm_cache is None:
            logger.warning("LangChain cache not available. Skipping cache setup.")
            return False

        try:
            # Create SQLiteCache instance
            self.cache = SQLiteCache(database_path=str(self.cache_db_path))

            # Set as global LLM cache for LangChain
            set_llm_cache(self.cache)

            logger.info(f"LLM cache initialized at {self.cache_db_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize LLM cache: {e}")
            return False

    def clear_cache(self) -> bool:
        """Clear all cached LLM responses.

        Returns:
            True if cache cleared successfully
        """
        if self.cache_db_path.exists():
            try:
                # Clear cache by removing the database
                self.cache_db_path.unlink()
                logger.info("LLM cache cleared")
                return True
            except Exception as e:
                logger.error(f"Failed to clear cache: {e}")
                return False
        return True

    def get_cache_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        stats = {
            "path": str(self.cache_db_path),
            "exists": self.cache_db_path.exists(),
            "size_mb": 0.0
        }

        if self.cache_db_path.exists():
            size_bytes = self.cache_db_path.stat().st_size
            stats["size_mb"] = round(size_bytes / (1024 * 1024), 2)

        return stats


# Global cache manager instance
_cache_manager: Optional[LLMCacheManager] = None


def get_cache_manager(cache_db_path: str = ".olav/databases/llm_cache.db") -> LLMCacheManager:
    """Get or create the global LLM cache manager.

    Args:
        cache_db_path: Path to cache database

    Returns:
        LLMCacheManager instance
    """
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = LLMCacheManager(cache_db_path)
    return _cache_manager


def setup_llm_cache(cache_db_path: str = ".olav/databases/llm_cache.db") -> bool:
    """Setup LLM cache globally.

    Args:
        cache_db_path: Path to cache database

    Returns:
        True if setup successful
    """
    manager = get_cache_manager(cache_db_path)
    return manager.initialize()


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)

    # Test cache setup
    if setup_llm_cache():
        manager = get_cache_manager()
        stats = manager.get_cache_stats()
        print(json.dumps(stats, indent=2))
    else:
        print("Failed to setup LLM cache")
