"""Cache Manager: DuckDB-based semantic cache for Guard decisions.

Responsibilities:
1. Initialize cache table in DuckDB
2. Check cache for similar queries (semantic lookup)
3. Store classification decisions (write-through)
4. Report cache statistics and metrics

Cache Strategy:
- Hash-based exact matching (MD5 of query text)
- TTL-based expiration (configurable, default 1 hour)
- Access counter and statistics
- Stored in skill-specific directory (.olav/skills/olav-guard/db/)

Performance targets:
- Lookup: 10-50ms
- Hit rate: ~45% (empirical)
- Write: <5ms
"""

import hashlib
import logging
from pathlib import Path
from typing import Any, Optional

import duckdb

from config.settings import settings

logger = logging.getLogger(__name__)

# Use skill-specific directory for cache
SKILLS_DIR = Path(".olav") / "skills"


class CacheManager:
    """DuckDB-based semantic query cache for Guard routing.
    
    Stores classification decisions with TTL and access tracking.
    """
    
    def __init__(self, cache_db_path: Optional[Path] = None):
        """Initialize cache manager.
        
        Args:
            cache_db_path: Path to DuckDB cache file.
                          Defaults to .olav/skills/olav-guard/db/guard_cache.duckdb
        """
        if cache_db_path is None:
            cache_db_path = SKILLS_DIR / "olav-guard" / "db" / "guard_cache.duckdb"
        
        self.cache_db_path = cache_db_path
        self.cache_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_ttl = settings.agent.guard_cache_ttl
        
        try:
            self.cache_conn = duckdb.connect(str(self.cache_db_path))
            self._init_cache_table()
            logger.info(f"✅ Guard cache initialized at {self.cache_db_path}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Guard cache: {e}")
            self.cache_conn = None
    
    def _init_cache_table(self):
        """Create semantic cache table if not exists."""
        if not self.cache_conn:
            return
        
        try:
            self.cache_conn.execute("""
                CREATE TABLE IF NOT EXISTS query_classifications (
                    query_hash VARCHAR PRIMARY KEY,
                    query_text VARCHAR,
                    route_code VARCHAR,
                    confidence DOUBLE,
                    reasoning VARCHAR,
                    risk_level VARCHAR DEFAULT 'safe',
                    detected_intent VARCHAR,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 1
                )
            """)
            
            # Create index for performance
            self.cache_conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_timestamp 
                ON query_classifications(timestamp DESC)
            """)
            
            self.cache_conn.commit()
            logger.debug("✅ Guard cache table initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize cache table: {e}")
    
    def check_cache(self, query: str) -> Optional[dict[str, Any]]:
        """Stage 2: Check semantic cache for similar queries.
        
        Time budget: 10-50ms
        Expected hit rate: ~45%
        
        Strategy:
        1. Hash-based exact match (MD5)
        2. TTL check (configurable, default 1 hour)
        3. Update access counter
        
        Args:
            query: User query string
        
        Returns:
            Dict with cached decision or None if not found/expired
        """
        if not self.cache_conn:
            return None
        
        try:
            query_hash = hashlib.md5(query.encode()).hexdigest()
            
            # Query cache with TTL check
            result = self.cache_conn.execute(f"""
                SELECT route_code, confidence, reasoning, risk_level, detected_intent, access_count
                FROM query_classifications
                WHERE query_hash = ?
                AND timestamp > CURRENT_TIMESTAMP - INTERVAL {self.cache_ttl} second
            """, [query_hash]).fetchone()
            
            if result:
                route_code, confidence, reasoning, risk_level, intent, access_count = result
                
                # Update access counter (non-blocking)
                try:
                    self.cache_conn.execute("""
                        UPDATE query_classifications
                        SET access_count = access_count + 1
                        WHERE query_hash = ?
                    """, [query_hash])
                    self.cache_conn.commit()
                except Exception as e:
                    logger.debug(f"⚠️  Failed to update cache counter: {e}")
                
                return {
                    "route_code": route_code,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "risk_level": risk_level,
                    "detected_intent": intent,
                    "cache_hit": True,
                }
        except Exception as e:
            logger.debug(f"⚠️  Cache lookup error: {e}")
        
        return None
    
    def cache_decision(self, query: str, decision: dict[str, Any]):
        """Save classification decision to cache (write-through).
        
        Args:
            query: User query string
            decision: RouteDecision dict containing:
                - code: RouteCode
                - confidence: float
                - reasoning: str
                - risk_level: str
                - detected_intent: str
        """
        if not self.cache_conn:
            return
        
        try:
            query_hash = hashlib.md5(query.encode()).hexdigest()
            
            self.cache_conn.execute("""
                INSERT OR REPLACE INTO query_classifications 
                (query_hash, query_text, route_code, confidence, reasoning, risk_level, detected_intent, timestamp, access_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 1)
            """, [
                query_hash,
                query[:500],  # Limit text to 500 chars
                decision.get("code", "UNKNOWN"),
                decision.get("confidence", 0.0),
                decision.get("reasoning", ""),
                decision.get("risk_level", "safe"),
                decision.get("detected_intent", "")
            ])
            self.cache_conn.commit()
            
        except Exception as e:
            logger.debug(f"⚠️  Failed to cache decision: {e}")
    
    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics for monitoring.
        
        Returns:
            Dict with cache statistics or error status
        """
        if not self.cache_conn:
            return {"status": "cache_disabled"}
        
        try:
            stats = self.cache_conn.execute("""
                SELECT 
                    COUNT(*) as total_entries,
                    COUNT(DISTINCT route_code) as unique_routes,
                    AVG(confidence) as avg_confidence,
                    AVG(access_count) as avg_access_count,
                    MAX(timestamp) as latest_entry
                FROM query_classifications
            """).fetchone()
            
            if stats:
                return {
                    "total_entries": stats[0],
                    "unique_routes": stats[1],
                    "avg_confidence": round(float(stats[2] or 0), 3),
                    "avg_access_count": round(float(stats[3] or 0), 2),
                    "latest_entry": str(stats[4]) if stats[4] else None,
                    "status": "active"
                }
        except Exception as e:
            logger.debug(f"⚠️  Failed to get cache stats: {e}")
        
        return {"status": "error"}
    
    def clear_expired(self):
        """Remove expired entries from cache.
        
        Called periodically or on demand for maintenance.
        """
        if not self.cache_conn:
            return
        
        try:
            result = self.cache_conn.execute(f"""
                DELETE FROM query_classifications
                WHERE timestamp <= CURRENT_TIMESTAMP - INTERVAL {self.cache_ttl} second
            """)
            self.cache_conn.commit()
            
            deleted_count = result.rows_affected if hasattr(result, 'rows_affected') else 0
            if deleted_count > 0:
                logger.info(f"🧹 Cache cleanup: removed {deleted_count} expired entries")
        except Exception as e:
            logger.error(f"❌ Cache cleanup failed: {e}")
