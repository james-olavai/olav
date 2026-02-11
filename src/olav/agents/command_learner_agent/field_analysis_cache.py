"""Field Analysis Cache - Tier 1 optimization.

Implements Tier 1 cache for command output field analysis to avoid
calling LLM multiple times for similar output formats.

Expected Performance Gains:
- 5-10x reduction in LLM API calls
- 50-200ms lookup time (vs 5-10s LLM analysis)
- Cost savings: $500-1000/year

Architecture:
├── Output Feature Extraction
│   ├── Line structure patterns
│   ├── Data type signatures
│   └── Column detection
├── L1: Memory cache (50 entries)
└── L2: DuckDB persistence (unlimited)
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

try:
    import duckdb
except ImportError:
    duckdb = None

logger = logging.getLogger(__name__)


def _extract_output_features(output: str) -> str:
    """Extract features from command output for caching.
    
    Creates a signature of output structure that remains stable
    even if actual values change.
    
    Args:
        output: Raw command output text
        
    Returns:
        Feature hash representing output structure
    """
    if not output:
        return hashlib.md5(b"empty").hexdigest()  # noqa: S324

    # Extract structural features
    lines = output.split('\n')
    features = []

    # 1. Line count (orders of magnitude)
    features.append(f"lines:{len(lines)//10 * 10}")

    # 2. Column detection (space-separated vs colon-separated)
    for line in lines[:5]:  # Sample first 5 lines
        if ':' in line:
            features.append("colon_sep")
        if '  ' in line:  # Multiple spaces suggest columnar data
            features.append("columnar")

    # 3. Data pattern detection
    for line in lines[:10]:
        if any(c.isdigit() for c in line):
            features.append("has_numbers")
        if any(c in line for c in ['[', '{', '(']):
            features.append("has_structures")

    # 4. Output length category
    output_kb = len(output) / 1024
    if output_kb < 1:
        features.append("size:tiny")
    elif output_kb < 10:
        features.append("size:small")
    elif output_kb < 100:
        features.append("size:medium")
    else:
        features.append("size:large")

    # Create stable hash from features
    feature_str = '|'.join(sorted(set(features)))
    return hashlib.md5(feature_str.encode()).hexdigest()  # noqa: S324


@dataclass
class FieldAnalysisResult:
    """Cached field analysis result."""

    fields: list[dict[str, Any]]
    """List of extracted fields with name, type, description"""

    output_hash: str
    """Output feature hash used for caching"""

    command: str
    """Original command"""

    platform: str
    """Network platform"""

    created_at: datetime
    """When analysis was performed"""

    llm_model: str = "gpt-4"
    """LLM model used for analysis"""

    analysis_time_ms: float = 0.0
    """Time spent on LLM analysis (for benchmarking)"""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional metadata"""

    def to_dict(self) -> dict:
        """Convert to dictionary for storage."""
        return {
            "fields": json.dumps(self.fields),
            "output_hash": self.output_hash,
            "command": self.command,
            "platform": self.platform,
            "created_at": self.created_at.isoformat(),
            "llm_model": self.llm_model,
            "analysis_time_ms": self.analysis_time_ms,
            "metadata": json.dumps(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict) -> FieldAnalysisResult:
        """Create from dictionary."""
        return cls(
            fields=json.loads(data["fields"]),
            output_hash=data["output_hash"],
            command=data["command"],
            platform=data["platform"],
            created_at=datetime.fromisoformat(data["created_at"]),
            llm_model=data.get("llm_model", "gpt-4"),
            analysis_time_ms=data.get("analysis_time_ms", 0.0),
            metadata=json.loads(data.get("metadata", "{}")),
        )


class FieldAnalysisCache:
    """Multi-tier field analysis cache (L1: Memory, L2: DuckDB).
    
    Caches field extraction results to avoid repeated LLM analysis
    for similar command outputs.
    """

    def __init__(
        self,
        cache_db: str | None = None,
        memory_cache_size: int = 50,
    ):
        """Initialize field analysis cache.
        
        Args:
            cache_db: Path to DuckDB cache file. If None, memory-only mode.
            memory_cache_size: Max entries in L1 memory cache (default: 50)
        """
        self._cache_db = cache_db
        self._memory_cache: dict[str, FieldAnalysisResult] = {}
        self._memory_order: list[str] = []
        self._memory_max = memory_cache_size

        # Statistics
        self._stats = {
            "total_get": 0,
            "hit_count": 0,
            "total_set": 0,
            "total_llm_saved": 0.0,  # Cumulative LLM seconds saved
        }

        # Initialize DuckDB
        self._db = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialize DuckDB database schema."""
        if not self._cache_db or not duckdb:
            return

        try:
            self._db = duckdb.connect(self._cache_db)

            # Create analysis cache table
            self._db.execute("""
                CREATE TABLE IF NOT EXISTS field_analysis_cache (
                    output_hash VARCHAR,
                    command VARCHAR,
                    platform VARCHAR,
                    fields VARCHAR,
                    llm_model VARCHAR,
                    analysis_time_ms DOUBLE,
                    created_at TIMESTAMP,
                    metadata VARCHAR
                )
            """)

            # Create indices for fast lookup
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_output_hash "
                "ON field_analysis_cache(output_hash)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_platform "
                "ON field_analysis_cache(command, platform)"
            )

            logger.debug(f"Field analysis cache initialized: {self._cache_db}")

        except Exception as e:
            logger.warning(f"Failed to initialize field analysis cache: {e}")
            self._db = None

    def get(
        self,
        output: str,
        command: str,
        platform: str,
    ) -> FieldAnalysisResult | None:
        """Get cached field analysis result.
        
        Lookup strategy:
        1. Output feature hash (L1 memory)
        2. Output feature hash (L2 DuckDB)
        
        Args:
            output: Command output text
            command: Command name (for context)
            platform: Platform name (for context)
            
        Returns:
            FieldAnalysisResult if found, None otherwise
        """
        self._stats["total_get"] += 1
        start_time = time.time()

        # Extract output features
        output_hash = _extract_output_features(output)

        # Strategy 1: L1 memory cache
        if output_hash in self._memory_cache:
            result = self._memory_cache[output_hash]
            # Update LRU
            if output_hash in self._memory_order:
                self._memory_order.remove(output_hash)
            self._memory_order.append(output_hash)
            self._stats["hit_count"] += 1
            self._stats["total_llm_saved"] += result.analysis_time_ms / 1000.0
            logger.debug(
                f"Field analysis cache L1 HIT "
                f"(latency: {(time.time() - start_time)*1000:.1f}ms, "
                f"saved: {result.analysis_time_ms:.0f}ms)"
            )
            return result

        # Strategy 2: L2 DuckDB
        if self._db:
            try:
                result = self._db.execute(
                    """
                    SELECT fields, command, platform, created_at, 
                           llm_model, analysis_time_ms, metadata
                    FROM field_analysis_cache
                    WHERE output_hash = ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    [output_hash],
                ).fetchall()

                if result:
                    row = result[0]
                    analysis = FieldAnalysisResult(
                        fields=json.loads(row[0]),
                        output_hash=output_hash,
                        command=row[1],
                        platform=row[2],
                        created_at=row[3],
                        llm_model=row[4],
                        analysis_time_ms=row[5],
                        metadata=json.loads(row[6]),
                    )
                    # Move to L1
                    self._memory_cache[output_hash] = analysis
                    self._memory_order.append(output_hash)
                    self._stats["hit_count"] += 1
                    self._stats["total_llm_saved"] += analysis.analysis_time_ms / 1000.0
                    logger.debug(
                        f"Field analysis cache L2 HIT "
                        f"(latency: {(time.time() - start_time)*1000:.1f}ms, "
                        f"saved: {analysis.analysis_time_ms:.0f}ms)"
                    )
                    return analysis
            except Exception as e:
                logger.debug(f"DuckDB lookup failed: {e}")

        return None

    def set(
        self,
        output: str,
        command: str,
        platform: str,
        fields: list[dict[str, Any]],
        analysis_time_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
        llm_model: str = "gpt-4",
    ) -> None:
        """Cache field analysis result.
        
        Args:
            output: Command output text
            command: Command name
            platform: Platform name
            fields: Extracted fields list
            analysis_time_ms: Time spent on LLM analysis
            metadata: Additional metadata
            llm_model: LLM model used
        """
        self._stats["total_set"] += 1

        output_hash = _extract_output_features(output)
        created_at = datetime.now()

        result = FieldAnalysisResult(
            fields=fields,
            output_hash=output_hash,
            command=command,
            platform=platform,
            created_at=created_at,
            analysis_time_ms=analysis_time_ms,
            llm_model=llm_model,
            metadata=metadata or {},
        )

        # L1: Memory cache (LRU)
        if output_hash in self._memory_order:
            self._memory_order.remove(output_hash)
        elif len(self._memory_cache) >= self._memory_max:
            # Evict oldest
            oldest_hash = self._memory_order.pop(0)
            del self._memory_cache[oldest_hash]

        self._memory_cache[output_hash] = result
        self._memory_order.append(output_hash)

        # L2: DuckDB
        if self._db:
            try:
                self._db.execute(
                    """
                    DELETE FROM field_analysis_cache WHERE output_hash = ?
                    """,
                    [output_hash],
                )
                self._db.execute(
                    """
                    INSERT INTO field_analysis_cache
                    (output_hash, command, platform, fields,
                     llm_model, analysis_time_ms, created_at, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        output_hash,
                        command,
                        platform,
                        json.dumps(fields),
                        llm_model,
                        analysis_time_ms,
                        created_at,
                        json.dumps(metadata or {}),
                    ],
                )
                logger.debug(
                    f"Field analysis cached: {command}@{platform} "
                    f"(analysis_time: {analysis_time_ms:.0f}ms)"
                )
            except Exception as e:
                logger.warning(f"Failed to cache in DuckDB: {e}")

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        hit_rate = (
            (self._stats["hit_count"] / self._stats["total_get"] * 100)
            if self._stats["total_get"] > 0
            else 0
        )

        db_size = 0
        if self._db:
            try:
                result = self._db.execute(
                    "SELECT COUNT(*) FROM field_analysis_cache"
                ).fetchall()
                if result:
                    db_size = result[0][0]
            except Exception:
                pass

        return {
            "total_get": self._stats["total_get"],
            "total_hit": self._stats["hit_count"],
            "hit_rate": f"{hit_rate:.1f}%",
            "total_set": self._stats["total_set"],
            "memory_cache_size": len(self._memory_cache),
            "memory_cache_max": self._memory_max,
            "db_entries": db_size,
            "llm_time_saved_seconds": f"{self._stats['total_llm_saved']:.1f}s",
            "estimated_cost_saved_usd": f"${int(self._stats['total_llm_saved'] * 0.001):.2f}",
        }

    def clear(self) -> None:
        """Clear all cache entries."""
        self._memory_cache.clear()
        self._memory_order.clear()
        if self._db:
            try:
                self._db.execute("DELETE FROM field_analysis_cache")
            except Exception:
                pass


# Global instance
_field_analysis_cache = None


def get_field_analysis_cache(
    cache_db: str | None = None,
) -> FieldAnalysisCache:
    """Get or create global field analysis cache instance."""
    global _field_analysis_cache
    if _field_analysis_cache is None:
        if not cache_db:
            from .config import get_config
            cache_db = get_config().cache_db

        _field_analysis_cache = FieldAnalysisCache(cache_db=cache_db)
    return _field_analysis_cache


def set_field_analysis_cache(cache: FieldAnalysisCache) -> None:
    """Set global field analysis cache instance (for testing)."""
    global _field_analysis_cache
    _field_analysis_cache = cache
