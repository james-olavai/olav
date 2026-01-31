"""
OLAV Unified Cache Manager

Simplified per-agent caching strategy as per user requirements:
- K.I.S.S. design (Keep It Simple, Stupid)
- Per-agent DuckDB isolation (one file per agent)
- Simple true/false matching (no complex confidence scores)
- Three-level caching: Whitelist → Agent Cache → Neural Router
"""

import duckdb
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


class AgentCache:
    """Per-agent cache with simple true/false logic."""

    def __init__(self, cache_file: Path):
        """Initialize agent cache with DuckDB."""
        self.cache_file = Path(cache_file)
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Connect to DuckDB
        self.conn = duckdb.connect(str(self.cache_file), read_only=False)
        
        # Initialize schema
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize cache schema."""
        try:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    query TEXT PRIMARY KEY,
                    result JSON,
                    hit_count INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            logger.info(f"Cache schema initialized: {self.cache_file}")
        except Exception as e:
            logger.error(f"Failed to initialize cache schema: {e}")

    def get(self, query: str) -> dict | None:
        """Get cached result for exact query match.

        Args:
            query: User query string

        Returns:
            {'result': ..., 'hit': True} if exact match found
            None if not found
        """
        try:
            result = self.conn.execute(
                "SELECT result, hit_count FROM cache WHERE query = ?",
                [query.strip()]
            ).fetchone()
            
            if result:
                data = json.loads(result[0])
                # Update hit_count
                self.conn.execute(
                    "UPDATE cache SET hit_count = hit_count + 1, last_used = CURRENT_TIMESTAMP WHERE query = ?",
                    [query.strip()]
                )
                
                return {
                    'result': data,
                    'hit': True,
                    'hit_count': result[1] + 1
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Cache get failed: {e}")
            return None

    def set(self, query: str, result: dict) -> None:
        """Cache result for exact query match.

        Args:
            query: User query string
            result: Result dictionary to cache
        """
        try:
            # Insert or replace
            self.conn.execute("""
                INSERT OR REPLACE INTO cache (query, result, hit_count, created_at, last_used)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """, [query.strip(), json.dumps(result, default=str)])
            
            logger.debug(f"Cached query: {query[:30]}...")
            
        except Exception as e:
            logger.error(f"Cache set failed: {e}")

    def clear(self, older_than_days: int = 7) -> int:
        """Clear old cache entries."""
        try:
            self.conn.execute("""
                DELETE FROM cache WHERE created_at < (CURRENT_TIMESTAMP - INTERVAL ? DAY)
            """, [older_than_days])
            
            deleted = self.conn.execute("SELECT changes()").fetchone()[0]
            logger.info(f"Cleared {deleted} old cache entries (older than {older_than_days} days)")
            
            return deleted
            
        except Exception as e:
            logger.error(f"Cache clear failed: {e}")
            return 0

    def get_stats(self) -> dict:
        """Get cache statistics."""
        try:
            total = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            unique = self.conn.execute("SELECT COUNT(DISTINCT query) FROM cache").fetchone()[0]
            total_hits = self.conn.execute("SELECT SUM(hit_count) FROM cache").fetchone()[0]
            
            return {
                'total_entries': total,
                'unique_queries': unique,
                'total_hits': total_hits,
                'avg_hit_count': round(total_hits / total, 2) if total > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Failed to get cache stats: {e}")
            return {}

    def close(self) -> None:
        """Close database connection."""
        try:
            self.conn.close()
            logger.debug(f"Cache connection closed: {self.cache_file}")
        except Exception:
            pass


class UnifiedCacheManager:
    """Unified cache manager for all agents.

    Manages per-agent DuckDB caches:
    - database.cache/database.duckdb
    - cli.cache/cli.duckdb
    - bgp.cache/bgp.duckdb
    - routing.cache/routing.duckdb
    """

    def __init__(self, cache_dir: str = ".olav/agent_cache"):
        """Initialize unified cache manager."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Cache instances for each agent
        self.caches = {}
        self._load_existing_caches()

    def _load_existing_caches(self) -> None:
        """Load existing agent cache instances."""
        # Try to load common agent caches
        agent_names = ['database', 'cli', 'bgp', 'routing']
        
        for agent_name in agent_names:
            cache_file = self.cache_dir / f"{agent_name}.duckdb"
            if cache_file.exists():
                try:
                    self.caches[agent_name] = AgentCache(cache_file)
                    logger.info(f"Loaded cache for agent: {agent_name}")
                except Exception as e:
                    logger.error(f"Failed to load cache for {agent_name}: {e}")
                    self.caches[agent_name] = None

    def get_agent_cache(self, agent_name: str) -> AgentCache | None:
        """Get cache instance for specific agent.

        Args:
            agent_name: Name of agent (database, cli, bgp, routing, etc.)

        Returns:
            AgentCache instance or None if agent not found
        """
        return self.caches.get(agent_name)

    def check_global_whitelist(self, query: str) -> dict | None:
        """Check if query matches global command whitelist.

        This is Tier 0.5 - HIGHEST PRIORITY (bypasses all caching).

        Args:
            query: User query string

        Returns:
            {'match': True, 'sql': ...} if exact match in whitelist
            None otherwise
        """
        # Load whitelist
        whitelist_file = Path(".olav/config/command_whitelist.yaml")
        if not whitelist_file.exists():
            return None
        
        try:
            import yaml
            import re
            
            with open(whitelist_file) as f:
                whitelist_config = yaml.safe_load(f)
                command_whitelist = whitelist_config.get('command_whitelist', {})
            
            # Exact match (no fuzzy matching, as per user requirement)
            for pattern, sql in command_whitelist.items():
                if re.fullmatch(pattern, query.strip()):
                    return {
                        'match': True,
                        'sql': sql,
                        'source': 'whitelist'
                    }
            
            return None
            
        except Exception as e:
            logger.error(f"Whitelist check failed: {e}")
            return None

    def close_all(self) -> None:
        """Close all cache connections."""
        for cache in self.caches.values():
            if cache:
                cache.close()

    def get_all_stats(self) -> dict:
        """Get statistics for all agent caches."""
        all_stats = {}
        
        for agent_name, cache in self.caches.items():
            if cache:
                try:
                    stats = cache.get_stats()
                    all_stats[agent_name] = stats
                except Exception as e:
                    logger.error(f"Failed to get stats for {agent_name}: {e}")
                    all_stats[agent_name] = {}
        
        return all_stats
