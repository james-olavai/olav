"""
Metrics Collector for OLAV Guard

Collects metrics for:
- Guard routing (latency, accuracy, route type)
- Orchestrator baseline (latency, accuracy, route type)
- A/B comparison (performance gains, error rates)
- Time-series data storage in DuckDB

Usage:
```python
from olav.core.metrics_collector import get_metrics_collector

collector = get_metrics_collector()

# Record Guard routing
collector.record_guard_query(
    query="count devices",
    latency_ms=2500,
    route_type="SIMPLE",
    confidence=0.90,
    success=True,
    user_id="user123",
)

# Record Orchestrator baseline
collector.record_orchestrator_query(
    query="count devices",
    latency_ms=15000,
    route_type="SIMPLE",
    success=True,
    user_id="user123",
)

# Get comparison metrics
comparison = collector.get_comparison()
print(f"Guard Avg Latency: {comparison['guard_avg_latency_ms']:.0f}ms")
print(f"Orchestrator Avg Latency: {comparison['orchestrator_avg_latency_ms']:.0f}ms")
print(f"Improvement: {comparison['latency_improvement_percent']:.1f}%")
```
"""

import logging
import time
from datetime import datetime, timedelta, UTC
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    Collects and analyzes metrics for Guard vs Orchestrator comparison.
    
    Stores data in DuckDB with tables:
    - guard_metrics: Guard routing performance
    - orchestrator_metrics: Orchestrator baseline performance
    - metrics_summary: Hourly aggregations
    """
    
    def __init__(self, db_path: Path | str = ".olav/db/metrics.duckdb"):
        """
        Initialize metrics collector.
        
        Args:
            db_path: Path to DuckDB database for metrics storage
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
    
    def _init_db(self):
        """Initialize DuckDB tables if needed"""
        try:
            conn = duckdb.connect(str(self.db_path))
            
            # Guard metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS guard_metrics (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    timestamp TIMESTAMP DEFAULT current_timestamp,
                    query_hash VARCHAR,
                    query_preview VARCHAR,
                    latency_ms FLOAT,
                    route_type VARCHAR,
                    confidence FLOAT,
                    success BOOLEAN,
                    error_message VARCHAR,
                    user_id VARCHAR,
                    session_id VARCHAR
                )
            """)
            
            # Orchestrator metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS orchestrator_metrics (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    timestamp TIMESTAMP DEFAULT current_timestamp,
                    query_hash VARCHAR,
                    query_preview VARCHAR,
                    latency_ms FLOAT,
                    route_type VARCHAR,
                    success BOOLEAN,
                    error_message VARCHAR,
                    user_id VARCHAR,
                    session_id VARCHAR
                )
            """)
            
            # Summary table (hourly aggregations)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics_summary (
                    hour TIMESTAMP,
                    guard_count INTEGER,
                    guard_avg_latency FLOAT,
                    guard_success_rate FLOAT,
                    orchestrator_count INTEGER,
                    orchestrator_avg_latency FLOAT,
                    orchestrator_success_rate FLOAT,
                    PRIMARY KEY (hour)
                )
            """)
            
            conn.close()
            logger.info(f"Initialized metrics database: {self.db_path}")
            
        except Exception as e:
            logger.error(f"Failed to initialize metrics database: {e}")
            raise
    
    def record_guard_query(
        self,
        query: str,
        latency_ms: float,
        route_type: str,
        confidence: float,
        success: bool,
        error_message: str = "",
        user_id: str = "",
        session_id: str = "",
    ):
        """
        Record a Guard routing query.
        
        Args:
            query: Query text
            latency_ms: Query latency in milliseconds
            route_type: Route type (SIMPLE, CLI, EXPERT, MULTI_AGENT, UNKNOWN)
            confidence: Route confidence (0.0-1.0)
            success: Whether query succeeded
            error_message: Error message if failed
            user_id: User ID for metrics aggregation
            session_id: Session ID for tracking
        """
        try:
            import hashlib
            query_hash = hashlib.md5(query.encode()).hexdigest()
            query_preview = query[:100] if len(query) > 100 else query
            
            # Convert UUID to string for DuckDB compatibility
            user_id_str = str(user_id) if user_id else None
            session_id_str = str(session_id) if session_id else None
            
            conn = duckdb.connect(str(self.db_path))
            conn.execute(
                "INSERT INTO guard_metrics (query_hash, query_preview, latency_ms, route_type, confidence, success, error_message, user_id, session_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [query_hash, query_preview, latency_ms, str(route_type), float(confidence), bool(success), error_message, user_id_str, session_id_str]
            )
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to record Guard query: {e}", exc_info=True)
    
    def record_orchestrator_query(
        self,
        query: str,
        latency_ms: float,
        route_type: str,
        success: bool,
        error_message: str = "",
        user_id: str = "",
        session_id: str = "",
    ):
        """
        Record an Orchestrator baseline query.
        
        Args:
            query: Query text
            latency_ms: Query latency in milliseconds
            route_type: Route type (for categorization)
            success: Whether query succeeded
            error_message: Error message if failed
            user_id: User ID for metrics aggregation
            session_id: Session ID for tracking
        """
        try:
            import hashlib
            query_hash = hashlib.md5(query.encode()).hexdigest()
            query_preview = query[:100] if len(query) > 100 else query
            
            # Convert UUID to string for DuckDB compatibility
            user_id_str = str(user_id) if user_id else None
            session_id_str = str(session_id) if session_id else None
            
            conn = duckdb.connect(str(self.db_path))
            conn.execute(
                "INSERT INTO orchestrator_metrics (query_hash, query_preview, latency_ms, route_type, success, error_message, user_id, session_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [query_hash, query_preview, latency_ms, str(route_type), bool(success), error_message, user_id_str, session_id_str]
            )
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Failed to record Orchestrator query: {e}", exc_info=True)
    
    def get_comparison(self, hours: int = 24) -> dict[str, Any]:
        """
        Get Guard vs Orchestrator comparison metrics.
        
        Args:
            hours: Number of hours to include in comparison
            
        Returns:
            Dictionary with comparison metrics
        """
        try:
            conn = duckdb.connect(str(self.db_path))
            cutoff_time = datetime.now(UTC) - timedelta(hours=hours)
            
            #Guard metrics
            guard_result = conn.execute(f"""
                SELECT 
                    COUNT(*) as count,
                    COALESCE(AVG(latency_ms), 0) as avg_latency,
                    COALESCE(QUANTILE_CONT(latency_ms, 0.95), 0) as p95_latency,
                    COALESCE(QUANTILE_CONT(latency_ms, 0.99), 0) as p99_latency,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0), 0) as success_rate
                FROM guard_metrics
                WHERE timestamp > '{cutoff_time}'
            """).fetchall()
            
            # Orchestrator metrics
            orch_result = conn.execute(f"""
                SELECT 
                    COUNT(*) as count,
                    COALESCE(AVG(latency_ms), 0) as avg_latency,
                    COALESCE(QUANTILE_CONT(latency_ms, 0.95), 0) as p95_latency,
                    COALESCE(QUANTILE_CONT(latency_ms, 0.99), 0) as p99_latency,
                    COALESCE(SUM(CASE WHEN success THEN 1 ELSE 0 END)::FLOAT / NULLIF(COUNT(*), 0), 0) as success_rate
                FROM orchestrator_metrics
                WHERE timestamp > '{cutoff_time}'
            """).fetchall()
            
            conn.close()
            
            # Extract values
            guard_stats = guard_result[0] if guard_result else None
            orch_stats = orch_result[0] if orch_result else None
            
            if not guard_stats or not orch_stats:
                logger.debug("No metrics data available")
                return {
                    "hours": hours,
                    "guard_count": 0,
                    "guard_avg_latency_ms": 0,
                    "guard_p95_latency_ms": 0,
                    "guard_p99_latency_ms": 0,
                    "guard_success_rate": 0,
                    "orchestrator_count": 0,
                    "orchestrator_avg_latency_ms": 0,
                    "orchestrator_p95_latency_ms": 0,
                    "orchestrator_p99_latency_ms": 0,
                    "orchestrator_success_rate": 0,
                    "latency_improvement_percent": 0,
                }
            
            guard_count, guard_avg, guard_p95, guard_p99, guard_success = guard_stats
            orch_count, orch_avg, orch_p95, orch_p99, orch_success = orch_stats
            
            # Calculate improvement
            latency_improvement = 0
            if orch_avg and orch_avg > 0 and guard_avg:
                latency_improvement = ((orch_avg - float(guard_avg)) / float(orch_avg)) * 100
            
            return {
                "hours": hours,
                "guard_count": int(guard_count) if guard_count else 0,
                "guard_avg_latency_ms": float(guard_avg) if guard_avg else 0,
                "guard_p95_latency_ms": float(guard_p95) if guard_p95 else 0,
                "guard_p99_latency_ms": float(guard_p99) if guard_p99 else 0,
                "guard_success_rate": float(guard_success) if guard_success else 0,
                "orchestrator_count": int(orch_count) if orch_count else 0,
                "orchestrator_avg_latency_ms": float(orch_avg) if orch_avg else 0,
                "orchestrator_p95_latency_ms": float(orch_p95) if orch_p95 else 0,
                "orchestrator_p99_latency_ms": float(orch_p99) if orch_p99 else 0,
                "orchestrator_success_rate": float(orch_success) if orch_success else 0,
                "latency_improvement_percent": latency_improvement,
            }
            
        except Exception as e:
            logger.error(f"Failed to get comparison metrics: {e}")
            return {
                "hours": hours,
                "guard_count": 0,
                "guard_avg_latency_ms": 0,
                "guard_p95_latency_ms": 0,
                "guard_p99_latency_ms": 0,
                "guard_success_rate": 0,
                "orchestrator_count": 0,
                "orchestrator_avg_latency_ms": 0,
                "orchestrator_p95_latency_ms": 0,
                "orchestrator_p99_latency_ms": 0,
                "orchestrator_success_rate": 0,
                "latency_improvement_percent": 0,
            }
    
    def get_route_distribution(self, hours: int = 24) -> dict[str, dict[str, int]]:
        """
        Get distribution of routes for Guard and Orchestrator.
        
        Returns:
            Dictionary with route type distributions
        """
        try:
            conn = duckdb.connect(str(self.db_path))
            cutoff_time = datetime.now(UTC) - timedelta(hours=hours)
            
            guard_routes = conn.execute(f"""
                SELECT route_type, COUNT(*) as count
                FROM guard_metrics
                WHERE timestamp > '{cutoff_time}'
                GROUP BY route_type
                ORDER BY count DESC
            """).fetchall()
            
            orch_routes = conn.execute(f"""
                SELECT route_type, COUNT(*) as count
                FROM orchestrator_metrics
                WHERE timestamp > '{cutoff_time}'
                GROUP BY route_type
                ORDER BY count DESC
            """).fetchall()
            
            conn.close()
            
            return {
                "guard": {route[0]: route[1] for route in guard_routes},
                "orchestrator": {route[0]: route[1] for route in orch_routes},
            }
            
        except Exception as e:
            logger.error(f"Failed to get route distribution: {e}")
            return {"guard": {}, "orchestrator": {}}
    
    def get_error_analysis(self, hours: int = 24) -> dict[str, Any]:
        """
        Get error analysis for Guard and Orchestrator.
        
        Returns:
            Dictionary with error rates and common errors
        """
        try:
            conn = duckdb.connect(str(self.db_path))
            cutoff_time = datetime.now(UTC) - timedelta(hours=hours)
            
            guard_errors = conn.execute(f"""
                SELECT 
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as error_rate,
                    COUNT(*) as total_count
                FROM guard_metrics
                WHERE timestamp > '{cutoff_time}'
            """).fetchall()
            
            orch_errors = conn.execute(f"""
                SELECT 
                    SUM(CASE WHEN NOT success THEN 1 ELSE 0 END)::FLOAT / COUNT(*) as error_rate,
                    COUNT(*) as total_count
                FROM orchestrator_metrics
                WHERE timestamp > '{cutoff_time}'
            """).fetchall()
            
            conn.close()
            
            guard_error_rate = guard_errors[0][0] if guard_errors and guard_errors[0][0] else 0
            orch_error_rate = orch_errors[0][0] if orch_errors and orch_errors[0][0] else 0
            
            return {
                "guard_error_rate": guard_error_rate,
                "orchestrator_error_rate": orch_error_rate,
                "error_rate_difference": abs(guard_error_rate - orch_error_rate),
            }
            
        except Exception as e:
            logger.error(f"Failed to get error analysis: {e}")
            return {}
    
    def clear_old_data(self, days: int = 30):
        """
        Clear metrics data older than specified days.
        
        Args:
            days: Number of days to keep
        """
        try:
            conn = duckdb.connect(str(self.db_path))
            cutoff_time = datetime.now(UTC) - timedelta(days=days)
            
            conn.execute(f"DELETE FROM guard_metrics WHERE timestamp < '{cutoff_time}'")
            conn.execute(f"DELETE FROM orchestrator_metrics WHERE timestamp < '{cutoff_time}'")
            conn.commit()
            conn.close()
            
            logger.info(f"Cleared metrics data older than {days} days")
            
        except Exception as e:
            logger.error(f"Failed to clear old metrics: {e}")


# Global singleton instance
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector(db_path: Path | str = ".olav/db/metrics.duckdb") -> MetricsCollector:
    """Get or create singleton metrics collector"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector(db_path)
    return _metrics_collector


def reset_metrics_collector():
    """Reset singleton (for testing)"""
    global _metrics_collector
    _metrics_collector = None
