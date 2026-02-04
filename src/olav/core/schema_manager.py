"""Database Schema Version Management for OLAV.

Implements schema versioning and migration framework to prevent production data corruption
during upgrades. Addresses ISSUE-008.

Design:
- schema_version table tracks applied migrations
- Migration scripts in .olav/migrations/ (optional, can be code-based)
- Auto-migration on startup
- Supports rollback

Usage:
    from olav.core.schema_manager import ensure_schema, get_current_version
    
    # On startup
    await ensure_schema(db_path)
    
    # Check version
    version = get_current_version(db_path)
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

logger = logging.getLogger(__name__)

# Current schema version
CURRENT_SCHEMA_VERSION = "1.0.0"

# Schema definitions for each version
SCHEMA_DEFINITIONS = {
    "1.0.0": {
        "query_cache": """
            CREATE TABLE IF NOT EXISTS query_cache (
                cache_key TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                ttl_seconds INTEGER NOT NULL,
                metadata_json TEXT,
                hit_count INTEGER DEFAULT 0,
                last_accessed TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_cache_created_at ON query_cache(created_at);
            CREATE INDEX IF NOT EXISTS idx_cache_key ON query_cache(cache_key);
        """,
        "schema_version": """
            CREATE TABLE IF NOT EXISTS schema_version (
                version VARCHAR PRIMARY KEY,
                applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                description VARCHAR
            );
        """,
    }
}


class SchemaManager:
    """Manages database schema versions and migrations."""

    def __init__(self, db_path: str | Path):
        """Initialize schema manager.
        
        Args:
            db_path: Path to DuckDB database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def get_current_version(self) -> str | None:
        """Get current schema version from database.
        
        Returns:
            Version string (e.g., "1.0.0") or None if no version table exists
        """
        try:
            conn = duckdb.connect(str(self.db_path))
            result = conn.execute(
                "SELECT version FROM schema_version ORDER BY applied_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            logger.debug(f"No schema_version table found: {e}")
            return None

    def create_version_table(self) -> None:
        """Create schema_version table if it doesn't exist."""
        conn = duckdb.connect(str(self.db_path))
        conn.execute(SCHEMA_DEFINITIONS["1.0.0"]["schema_version"])
        conn.commit()
        conn.close()
        logger.info("Created schema_version table")

    def apply_migration(
        self, version: str, description: str = "", sql: str = ""
    ) -> None:
        """Apply a migration to the database.
        
        Args:
            version: Version string (e.g., "1.0.0")
            description: Migration description
            sql: SQL statements to execute
        """
        conn = duckdb.connect(str(self.db_path))
        
        try:
            # Execute migration SQL
            if sql:
                conn.execute(sql)
            
            # Record migration
            conn.execute(
                "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                [version, description or f"Schema version {version}"]
            )
            conn.commit()
            logger.info(f"Applied migration: {version} - {description}")
        except Exception as e:
            conn.rollback()
            logger.error(f"Migration failed for {version}: {e}")
            raise
        finally:
            conn.close()

    def ensure_schema(self, target_version: str = CURRENT_SCHEMA_VERSION) -> bool:
        """Ensure database schema is at target version.
        
        Args:
            target_version: Target schema version (default: CURRENT_SCHEMA_VERSION)
        
        Returns:
            True if migration was needed and applied, False if already at target version
        """
        current_version = self.get_current_version()
        
        if current_version == target_version:
            logger.debug(f"Schema already at version {target_version}")
            return False
        
        if current_version is None:
            # Fresh database - create version table first
            self.create_version_table()
            
            # Apply all schemas for target version
            if target_version in SCHEMA_DEFINITIONS:
                all_sql = "\n".join(SCHEMA_DEFINITIONS[target_version].values())
                self.apply_migration(
                    target_version,
                    f"Initial schema creation for {target_version}",
                    all_sql
                )
                logger.info(f"Initialized database with schema {target_version}")
                return True
        else:
            # TODO: Implement version comparison and incremental migrations
            logger.warning(
                f"Schema migration from {current_version} to {target_version} not yet implemented"
            )
            return False
        
        return False


# Convenience functions for global use
def get_current_version(db_path: str | Path) -> str | None:
    """Get current schema version of a database.
    
    Args:
        db_path: Path to DuckDB database
    
    Returns:
        Version string or None
    """
    manager = SchemaManager(db_path)
    return manager.get_current_version()


def ensure_schema(db_path: str | Path, version: str = CURRENT_SCHEMA_VERSION) -> bool:
    """Ensure database schema is at specified version.
    
    Args:
        db_path: Path to DuckDB database
        version: Target schema version (default: CURRENT_SCHEMA_VERSION)
    
    Returns:
        True if migration was applied, False if already at target version
    """
    manager = SchemaManager(db_path)
    return manager.ensure_schema(version)
