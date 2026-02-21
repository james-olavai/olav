"""ResponseCache — DuckDB-backed response cache with snapshot-aware invalidation.

Design:
  - Stores (query_hash, query_text, response, source_agent, cached_at, snapshot_ts)
  - Invalidation is snapshot-based, NOT wall-clock TTL:
    - For olav-ops agent: compares snapshot_ts against the latest export directory
    - For other agents: uses a configurable max-age (default 24 h)
  - Exact-hash lookup: O(1), zero LLM calls
  - Semantic search (search_cache tool) used by Orchestrator as Tier-0 RAG

Usage:
    cache = ResponseCache()
    hit = cache.get_exact(query)
    if hit:
        return hit["response"]
    # ... run agent ...
    cache.store(query, response, source_agent="olav-ops")
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Source-agent → max TTL when snapshot timestamp is unavailable
_DEFAULT_TTL: dict[str, timedelta] = {
    "olav-ops": timedelta(hours=24),   # snapshot-based, but 24h fallback
    "olav-config": timedelta(hours=1),
    "olav-audit": timedelta(hours=48),
}
_FALLBACK_TTL = timedelta(hours=6)

# Latest snapshot discovery — look for newest exports/YYYY-MM-DD_HHMMSS/ directory
_EXPORTS_ROOT = Path("data/exports")


def _latest_snapshot_ts() -> datetime | None:
    """Return the mtime of the most-recent exports snapshot directory.

    Returns:
        Datetime of last snapshot, or None if no exports exist.
    """
    if not _EXPORTS_ROOT.exists():
        return None
    dirs = sorted(
        (d for d in _EXPORTS_ROOT.iterdir() if d.is_dir()),
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    if not dirs:
        return None
    return datetime.fromtimestamp(dirs[0].stat().st_mtime)


def _query_hash(query: str) -> str:
    """Canonical SHA-256 hash of a normalised query string.

    Args:
        query: Raw query text.

    Returns:
        32-char hex digest.
    """
    normalised = query.strip().lower()
    return hashlib.sha256(normalised.encode()).hexdigest()[:32]


class ResponseCache:
    """DuckDB-backed response cache with per-snapshot invalidation.

    Thread-safe write path: uses a separate connection per write so the
    daemon's async loop is not blocked.
    """

    _TABLE_DDL = """
        CREATE TABLE IF NOT EXISTS response_cache (
            query_hash    VARCHAR PRIMARY KEY,
            query_text    VARCHAR NOT NULL,
            response      TEXT    NOT NULL,
            source_agent  VARCHAR NOT NULL DEFAULT 'unknown',
            cached_at     TIMESTAMP NOT NULL,
            snapshot_ts   TIMESTAMP
        )
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialise cache, creating the table if it doesn't exist.

        Args:
            db_path: Path to DuckDB file. Defaults to project main.duckdb.
        """
        if db_path is None:
            from config.paths import NETWORK_DB_PATH

            db_path = NETWORK_DB_PATH
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_table()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_table(self) -> None:
        """Create response_cache table if absent, migrating old schema if needed."""
        import duckdb

        try:
            conn = duckdb.connect(str(self._db_path))
            # Check if table exists with old schema (missing source_agent column)
            tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
            if "response_cache" in tables:
                cols = {r[0] for r in conn.execute("DESCRIBE response_cache").fetchall()}
                if "source_agent" not in cols:
                    # Old schema from removed cache functions — drop and recreate
                    logger.info("ResponseCache: migrating old response_cache schema")
                    conn.execute("DROP TABLE response_cache")
            conn.execute(self._TABLE_DDL)
            conn.close()
        except Exception as exc:
            logger.warning("ResponseCache: could not init table: %s", exc)

    def _is_valid(self, row: tuple) -> bool:  # type: ignore[return]
        """Check if a cache row is still valid (not expired).

        Validation logic per source_agent:
        - olav-ops: valid only if cached AFTER the latest snapshot.
        - others:   valid if within DEFAULT_TTL.

        Args:
            row: Tuple from SELECT query_hash, cached_at, snapshot_ts, source_agent.

        Returns:
            True if cache entry is still valid, False otherwise.
        """
        _hash, cached_at, snapshot_ts, source_agent = row

        if source_agent == "olav-ops":
            latest = _latest_snapshot_ts()
            if latest is None:
                # No snapshots at all — use fallback TTL
                return datetime.now() - cached_at < _FALLBACK_TTL
            # Valid if cached AFTER the latest snapshot was written
            return cached_at >= latest

        ttl = _DEFAULT_TTL.get(source_agent, _FALLBACK_TTL)
        return datetime.now() - cached_at < ttl

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_exact(self, query: str) -> dict[str, str] | None:
        """Exact-hash lookup. Returns cached entry if valid, else None.

        Args:
            query: Raw query text to look up.

        Returns:
            Dict with 'response', 'source_agent', 'cached_at' keys, or None.
        """
        import duckdb

        qhash = _query_hash(query)
        try:
            conn = duckdb.connect(str(self._db_path), read_only=True)
            row = conn.execute(
                """
                SELECT query_hash, cached_at, snapshot_ts, source_agent, response, query_text
                FROM response_cache
                WHERE query_hash = ?
                """,
                [qhash],
            ).fetchone()
            conn.close()
        except Exception as exc:
            logger.debug("ResponseCache.get_exact error: %s", exc)
            return None

        if row is None:
            return None

        # row: query_hash, cached_at, snapshot_ts, source_agent, response, query_text
        validity_row = (row[0], row[1], row[2], row[3])
        if not self._is_valid(validity_row):
            logger.debug("ResponseCache: stale entry for hash=%s (agent=%s)", qhash, row[3])
            return None

        logger.debug("ResponseCache: HIT for hash=%s", qhash)
        return {
            "response": row[4],
            "source_agent": row[3],
            "cached_at": str(row[1]),
            "query_text": row[5],
        }

    def store(
        self,
        query: str,
        response: str,
        source_agent: str = "unknown",
    ) -> None:
        """Store a query→response pair in the cache.

        Args:
            query: Raw query text.
            response: Final formatted response string.
            source_agent: Which SubAgent produced the response.
        """
        if not response or not response.strip():
            return  # Don't cache empty responses

        import duckdb

        qhash = _query_hash(query)
        snapshot_ts = _latest_snapshot_ts()
        now = datetime.now()

        try:
            conn = duckdb.connect(str(self._db_path))
            conn.execute(
                """
                INSERT INTO response_cache
                    (query_hash, query_text, response, source_agent, cached_at, snapshot_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (query_hash) DO UPDATE SET
                    response = EXCLUDED.response,
                    source_agent = EXCLUDED.source_agent,
                    cached_at = EXCLUDED.cached_at,
                    snapshot_ts = EXCLUDED.snapshot_ts
                """,
                [qhash, query.strip(), response, source_agent, now, snapshot_ts],
            )
            conn.close()
            logger.debug(
                "ResponseCache: stored hash=%s agent=%s snapshot=%s",
                qhash,
                source_agent,
                snapshot_ts,
            )
        except Exception as exc:
            logger.warning("ResponseCache.store error: %s", exc)

    def invalidate(self, query: str) -> None:
        """Remove a specific query from the cache.

        Args:
            query: Raw query text to invalidate.
        """
        import duckdb

        qhash = _query_hash(query)
        try:
            conn = duckdb.connect(str(self._db_path))
            conn.execute("DELETE FROM response_cache WHERE query_hash = ?", [qhash])
            conn.close()
        except Exception as exc:
            logger.debug("ResponseCache.invalidate error: %s", exc)

    def clear_stale(self) -> int:
        """Remove all expired cache entries. Returns count deleted.

        Returns:
            Number of stale entries removed.
        """
        import duckdb

        try:
            conn = duckdb.connect(str(self._db_path))
            rows = conn.execute(
                "SELECT query_hash, cached_at, snapshot_ts, source_agent FROM response_cache"
            ).fetchall()

            stale = [r[0] for r in rows if not self._is_valid(r)]
            if stale:
                placeholders = ",".join(["?"] * len(stale))
                conn.execute(
                    f"DELETE FROM response_cache WHERE query_hash IN ({placeholders})",  # noqa: S608
                    stale,
                )
            conn.close()
            return len(stale)
        except Exception as exc:
            logger.debug("ResponseCache.clear_stale error: %s", exc)
            return 0


# Module-level singleton for easy import
_cache_instance: ResponseCache | None = None


def get_response_cache() -> ResponseCache:
    """Get (or create) the module-level ResponseCache singleton.

    Returns:
        Global ResponseCache instance, shared across the process.
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = ResponseCache()
    return _cache_instance
