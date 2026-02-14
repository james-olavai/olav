"""Schema cache management using DuckDB persistence."""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import duckdb

from config.paths import UNIFIED_DB

logger = logging.getLogger(__name__)


class SchemaCache:
    """Persist schema information to DuckDB for fast repeated access."""

    DB_PATH = UNIFIED_DB
    CACHE_TABLE = "schema_cache"

    @classmethod
    def initialize(cls) -> None:
        """Initialize schema_cache table and load initial schema.

        This is called once at OLAV startup.
        Takes ~8-10 seconds (only done once per session).
        """
        logger.info("📦 Initializing schema cache...")

        try:
            # Create connection
            db_path = Path(cls.DB_PATH)
            if not db_path.exists():
                logger.warning(f"Database not found at {cls.DB_PATH}")
                return

            conn = duckdb.connect(str(db_path))

            # Create cache table if it doesn't exist
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {cls.CACHE_TABLE} (
                    cache_key STRING PRIMARY KEY,
                    cache_value JSON,
                    updated_at TIMESTAMP,
                    schema_version INTEGER DEFAULT 1
                )
            """)

            # Load initial schema from database
            cls._load_schema(conn)

            logger.info("✅ Schema cache initialized\n")

        except Exception as e:
            logger.error(f"❌ Failed to initialize schema cache: {e}")

    @classmethod
    def get_schema(cls) -> Optional[Dict[str, Any]]:
        """Get cached schema from DuckDB.

        Returns:
            Dict with 'views', 'tables', 'metadata' keys, or None if error.

        Note:
            This is very fast (< 1ms) since it's a local DuckDB query.
        """
        try:
            db_path = Path(cls.DB_PATH)
            if not db_path.exists():
                logger.warning(f"Database not found at {cls.DB_PATH}")
                return None

            # Use read_only mode to avoid lock contention
            conn = duckdb.connect(str(db_path), read_only=True)

            result = conn.execute(f"""
                SELECT cache_value FROM {cls.CACHE_TABLE}
                WHERE cache_key = 'schema'
                ORDER BY updated_at DESC LIMIT 1
            """).fetchone()

            conn.close()

            if result:
                return json.loads(result[0])

            logger.warning("Schema cache is empty")
            return None

        except Exception as e:
            logger.error(f"Error reading schema cache: {e}")
            return None

    @classmethod
    def reload(cls) -> None:
        """Reload schema from database and update cache.

        This can be called by user with /reload command.
        """
        logger.info("🔄 Reloading schema cache...")

        try:
            db_path = Path(cls.DB_PATH)
            if not db_path.exists():
                logger.error(f"Database not found at {cls.DB_PATH}")
                return

            conn = duckdb.connect(str(db_path))
            cls._load_schema(conn)
            conn.close()

            logger.info("✅ Schema cache reloaded\n")

        except Exception as e:
            logger.error(f"❌ Failed to reload schema cache: {e}")

    @classmethod
    def _load_schema(cls, conn: Any) -> None:
        """Load schema from database and store in cache.

        Args:
            conn: DuckDB connection object
        """
        try:
            # Import here to avoid circular imports
            from olav.lib.data_gateway import get_gateway

            gw = get_gateway()

            logger.debug("  Querying views...")
            # Query views
            views_result = gw.query_snapshots(
                "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW'"
            )
            views_list = [str(row["table_name"]) for row in views_result if row]

            logger.debug("  Querying tables...")
            # Query tables
            tables_result = gw.query_main(
                "SELECT table_name FROM information_schema.tables WHERE table_type='BASE TABLE'"
            )
            tables_list = [str(row["table_name"]) for row in tables_result if row]

            logger.debug("  Querying metadata...")
            # Query metadata (note: table is sync_metadata with sync_date, not snapshot_date)
            metadata_result = gw.query_snapshots(
                "SELECT sync_date, device_count FROM sync_metadata ORDER BY sync_date DESC LIMIT 1"
            )
            latest_snapshot = {}
            if metadata_result and metadata_result[0]:
                latest_snapshot = {
                    "date": str(metadata_result[0].get("sync_date", metadata_result[0].get("snapshot_date", "Unknown"))),
                    "device_count": int(metadata_result[0].get("device_count", 0)) if metadata_result[0].get("device_count") else 0,
                }

            # Prepare cache data
            cache_data = {
                "views": views_list,
                "tables": tables_list,
                "metadata": latest_snapshot,
                "timestamp": datetime.now().isoformat(),
            }

            logger.debug("  Writing to cache...")
            # Update cache in database
            conn.execute(
                f"""
                INSERT INTO {cls.CACHE_TABLE} (cache_key, cache_value, updated_at, schema_version)
                VALUES (?, ?, NOW(), 1)
                ON CONFLICT (cache_key) DO UPDATE SET
                    cache_value = excluded.cache_value,
                    updated_at = NOW(),
                    schema_version = schema_version + 1
            """,
                ["schema", json.dumps(cache_data)],
            )

            logger.debug(f"    ✓ Views: {len(views_list)}")
            logger.debug(f"    ✓ Tables: {len(tables_list)}")
            logger.debug(f"    ✓ Latest snapshot: {latest_snapshot.get('date', 'N/A')}")

        except Exception as e:
            logger.error(f"Error loading schema: {e}")
            raise
