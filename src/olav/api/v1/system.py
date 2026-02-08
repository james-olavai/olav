"""Phase 1.4: System Operations API - Health, stats, and system monitoring.

Provides:
- System health checks
- Performance statistics
- Database statistics
- Cache performance metrics
- Operational controls (restart, etc.)
"""

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from config.paths import CACHE_DIR, UNIFIED_DB
from olav.core.query_cache import QueryResultCache
from olav.core.unified_database import UnifiedDatabase

logger = logging.getLogger(__name__)


@dataclass
class SystemHealth:
    """System health status."""
    status: str  # "healthy", "degraded", "unhealthy"
    timestamp: str
    database: dict[str, Any]
    cache: dict[str, Any]
    storage: dict[str, Any]


@dataclass
class SystemStatistics:
    """System statistics."""
    uptime_seconds: float
    start_time: str
    cpu_percent: float
    memory_percent: float
    total_requests: int
    total_errors: int
    average_response_time_ms: float


# Global system start time
_system_start_time = datetime.now()
_request_stats = {
    "total_requests": 0,
    "total_errors": 0,
    "total_response_time_ms": 0,
}


def get_system_health() -> dict[str, Any]:
    """Get system health status.
    
    Returns:
        Dict with overall status ("healthy", "degraded", "unhealthy")
        and component-specific health details
        
    Example:
        >>> health = get_system_health()
        >>> print(health["status"])
        "healthy"
    """
    timestamp = datetime.now().isoformat()

    # Check database
    db_health = _check_database_health()

    # Check cache
    cache_health = _check_cache_health()

    # Check storage
    storage_health = _check_storage_health()

    # Determine overall status
    components_ok = [
        db_health["status"] == "ok",
        cache_health["status"] == "ok",
        storage_health["status"] == "ok",
    ]

    if all(components_ok):
        overall_status = "healthy"
    elif sum(components_ok) >= 2:
        overall_status = "degraded"
    else:
        overall_status = "unhealthy"

    return {
        "status": overall_status,
        "timestamp": timestamp,
        "database": db_health,
        "cache": cache_health,
        "storage": storage_health,
        "components_ok": sum(components_ok),
        "components_total": len(components_ok),
    }


def _check_database_health() -> dict[str, Any]:
    """Check database connectivity and status."""
    try:
        db = UnifiedDatabase()

        # Test query
        result = db.query("SELECT COUNT(*) FROM information_schema.tables")
        if result:
            return {
                "status": "ok",
                "response_time_ms": 10,  # Placeholder
            }
    except Exception as e:
        logger.warning(f"Database health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }

    return {
        "status": "error",
        "error": "Connection failed",
    }


def _check_cache_health() -> dict[str, Any]:
    """Check cache status."""
    try:
        cache = QueryResultCache(db_path=CACHE_DIR / "query_result_cache.db")
        stats = cache.stats()

        return {
            "status": "ok",
            "l1_entries": stats.get("l1_size", 0),
            "l2_entries": stats.get("l2_total_entries", 0),
            "ttl_seconds": stats.get("ttl_seconds", 3600),
        }
    except Exception as e:
        logger.warning(f"Cache health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


def _check_storage_health() -> dict[str, Any]:
    """Check storage availability."""
    try:
        stat = os.statvfs("/")
        available = stat.f_bavail * stat.f_frsize
        total = stat.f_blocks * stat.f_frsize
        used = (stat.f_blocks - stat.f_bfree) * stat.f_frsize

        # Healthy if > 10% free
        percent_free = (available / total) * 100 if total > 0 else 0

        return {
            "status": "ok" if percent_free > 10 else "warning",
            "available_bytes": available,
            "total_bytes": total,
            "used_bytes": used,
            "percent_free": percent_free,
        }
    except Exception as e:
        logger.warning(f"Storage health check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


def get_system_stats() -> dict[str, Any]:
    """Get system statistics.
    
    Returns:
        Dict with uptime, CPU%, memory%, request counts, etc.
        
    Example:
        >>> stats = get_system_stats()
        >>> print(f"Uptime: {stats['uptime_seconds']}s")
    """
    uptime = (datetime.now() - _system_start_time).total_seconds()

    # CPU and memory info (stub without psutil)
    cpu_percent = 0.0
    memory_percent = 0.0

    # Calculate average response time
    if _request_stats["total_requests"] > 0:
        avg_response_time = _request_stats["total_response_time_ms"] / _request_stats["total_requests"]
    else:
        avg_response_time = 0.0

    return {
        "status": "running",
        "uptime_seconds": uptime,
        "start_time": _system_start_time.isoformat(),
        "current_time": datetime.now().isoformat(),
        "cpu_percent": cpu_percent,
        "memory_percent": memory_percent,
        "total_requests": _request_stats["total_requests"],
        "total_errors": _request_stats["total_errors"],
        "average_response_time_ms": avg_response_time,
    }


def get_database_stats() -> dict[str, Any]:
    """Get database statistics.
    
    Returns:
        Dict with table count, sizes, record counts, etc.
        
    Example:
        >>> stats = get_database_stats()
        >>> print(f"Tables: {stats['table_count']}")
    """
    try:
        db = UnifiedDatabase()

        # Get table count
        tables = db.query("SELECT COUNT(*) as cnt FROM information_schema.tables WHERE table_schema = 'main'")
        table_count = tables[0][0] if tables else 0

        # Get record counts per table
        table_rows = {}
        table_list = db.query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'")

        for table in table_list:
            table_name = table[0]
            try:
                # Use quoted identifier to prevent SQL injection
                count = db.query(f'SELECT COUNT(*) as cnt FROM "{table_name}"')
                table_rows[table_name] = count[0][0] if count else 0
            except Exception as e:
                logger.debug(f"Failed to count rows in {table_name}: {e}")
                table_rows[table_name] = 0

        # Get database size (approximate)
        db_path = Path(UNIFIED_DB)
        if db_path.exists():
            size_bytes = db_path.stat().st_size
        else:
            size_bytes = 0

        return {
            "status": "ok",
            "table_count": table_count,
            "table_rows": table_rows,
            "size_bytes": size_bytes,
            "tables": list(table_rows.keys()),
        }
    except Exception as e:
        logger.error(f"Database stats retrieval failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


def get_cache_performance() -> dict[str, Any]:
    """Get cache performance metrics.
    
    Returns:
        Dict with hit rate, eviction stats, entry counts, etc.
        
    Example:
        >>> perf = get_cache_performance()
        >>> print(f"Hit rate: {perf['hit_rate']:.2%}")
    """
    try:
        cache = QueryResultCache(db_path=CACHE_DIR / "query_result_cache.db")
        stats = cache.stats()

        # Calculate hit rate
        total_hits = stats.get("l2_total_hits") or 0
        total_entries = stats.get("l1_size", 0) + stats.get("l2_total_entries", 0)

        if total_entries > 0:
            hit_rate = total_hits / total_entries if total_entries > 0 else 0.0
        else:
            hit_rate = 0.0

        return {
            "status": "ok",
            "hit_rate": hit_rate,
            "l1_entries": stats.get("l1_size", 0),
            "l1_max_entries": stats.get("l1_max_size", 100),
            "l2_entries": stats.get("l2_total_entries", 0),
            "total_hits": total_hits,
            "ttl_seconds": stats.get("ttl_seconds", 3600),
            "evictions": 0,  # Not tracked in QueryResultCache
        }
    except Exception as e:
        logger.error(f"Cache performance retrieval failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


def restart_cache() -> dict[str, Any]:
    """Restart the cache system.
    
    Clears all cache entries and reinitializes.
    
    Returns:
        Dict with status and cleared entry count
        
    Example:
        >>> result = restart_cache()
        >>> print(f"Cleared {result['cleared_entries']} entries")
    """
    try:
        cache = QueryResultCache(db_path=CACHE_DIR / "query_result_cache.db")

        # Get count before clearing
        stats_before = cache.stats()
        before_count = (stats_before.get("l1_size", 0) +
                       stats_before.get("l2_total_entries", 0))

        # Clear cache
        cache.clear()

        logger.info(f"Cache restarted, cleared {before_count} entries")

        return {
            "status": "success",
            "action": "cache_restarted",
            "cleared_entries": before_count,
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        logger.error(f"Cache restart failed: {e}")
        return {
            "status": "error",
            "error": str(e),
        }


def get_version() -> str:
    """Get system version.
    
    Returns:
        Version string (e.g., "0.10.2")
        
    Example:
        >>> version = get_version()
        >>> print(f"OLAV {version}")
    """
    # Read from pyproject.toml or use hardcoded version
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib

    try:
        with open("pyproject.toml", "rb") as f:
            pyproject = tomllib.load(f)
            return pyproject.get("project", {}).get("version", "0.10.2")
    except Exception:
        return "0.10.2"  # Fallback version
