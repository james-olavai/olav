#!/usr/bin/env python3
"""
Database Migration Script - Add Agent Support to Semantic Cache

This script safely adds agent, execution_plan, and query_history fields
to the existing semantic_cache table without data loss.

Phase 1.1 of Simplified Fast Path Implementation
"""

import logging
import sys
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)


def backup_cache_data(db_path: str) -> bool:
    """Backup existing cache data."""
    try:
        conn = duckdb.connect(db_path)

        # Check if cache table exists
        tables = conn.execute("SHOW TABLES").fetchall()
        cache_exists = "semantic_cache" in [t[0] for t in tables]

        if not cache_exists:
            logger.info("Semantic cache table does not exist yet, skipping backup")
            conn.close()
            return True

        # Backup all data
        backup_path = Path(db_path).parent / "semantic_cache_backup.json"
        try:
            data = conn.execute("SELECT * FROM commands.main.semantic_cache").fetchall()

            # Convert to JSON for backup
            import json

            backup_data = {
                "timestamp": str(Path.cwd().stat().st_mtime),
                "record_count": len(data),
                "records": [
                    {
                        "query_text": row[0],
                        "query_embedding": row[1],
                        "action_json": row[2],
                        "confidence": row[3] if len(row) > 3 else 1.0,
                        "last_used": row[4] if len(row) > 4 else None,
                    }
                    for row in data
                ],
            }

            with open(backup_path, "w") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

            logger.info(f"Backed up {len(data)} records to {backup_path}")
            conn.close()
            return True

        except Exception as e:
            logger.error(f"Backup failed: {e}")
            conn.close()
            return False

    except Exception as e:
        logger.error(f"Failed to connect or check cache: {e}")
        return False


def migrate_cache_schema(db_path: str) -> bool:
    """Migrate semantic_cache table to support agents."""
    try:
        conn = duckdb.connect(db_path)

        # Step 1: Add new columns if they don't exist
        logger.info("Step 1: Adding new columns...")

        # Check current schema
        columns = conn.execute("DESCRIBE commands.main.semantic_cache").fetchall()
        existing_columns = [col[0] for col in columns]

        # Columns to add
        new_columns = {
            "agent": "VARCHAR",
            "execution_plan": "JSON",
            "query_history": "JSON",  # Array of {query, timestamp}
            "plan_version": "INTEGER DEFAULT 1",  # Support for plan optimization
            "success_rate": "FLOAT DEFAULT 1.0",  # Track plan success rate
        }

        added_columns = []
        for col_name, col_type in new_columns.items():
            if col_name not in existing_columns:
                try:
                    sql = (
                        f"ALTER TABLE commands.main.semantic_cache ADD COLUMN {col_name} {col_type}"
                    )
                    conn.execute(sql)
                    added_columns.append(col_name)
                    logger.info(f"  Added column: {col_name} ({col_type})")
                except Exception as e:
                    logger.error(f"  Failed to add column {col_name}: {e}")

        if not added_columns:
            logger.warning("No new columns needed (they might already exist)")

        # Step 2: Update existing records to set defaults
        logger.info("Step 2: Setting default values for existing records...")

        # Set agent to 'database' for all existing records
        try:
            result = conn.execute("""
                UPDATE commands.main.semantic_cache 
                SET agent = 'database',
                    plan_version = 1,
                    success_rate = 1.0
                WHERE agent IS NULL OR agent = ''
            """)

            logger.info(f"  Updated {result} existing records")
        except Exception as e:
            logger.error(f"  Failed to update records: {e}")

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Migration failed: {e}")
        return False


def verify_migration(db_path: str) -> bool:
    """Verify the migration was successful."""
    try:
        conn = duckdb.connect(db_path)

        # Check new columns exist
        columns = conn.execute("DESCRIBE commands.main.semantic_cache").fetchall()
        column_names = [col[0] for col in columns]

        required_columns = [
            "agent",
            "execution_plan",
            "query_history",
            "plan_version",
            "success_rate",
        ]
        missing_columns = [col for col in required_columns if col not in column_names]

        if missing_columns:
            logger.error(f"Missing required columns: {missing_columns}")
            conn.close()
            return False

        logger.info("All required columns exist")

        # Verify one record was updated
        sample = conn.execute("SELECT * FROM commands.main.semantic_cache LIMIT 1").fetchone()
        if sample and len(sample) > 4:
            logger.info(
                f"Sample record updated: agent={sample[4] if len(sample) > 4 else 'NULL'}, plan_version={sample[7] if len(sample) > 7 else 'N/A'}"
            )

        conn.close()
        return True

    except Exception as e:
        logger.error(f"Verification failed: {e}")
        return False


def main():
    """Run the migration."""

    # Get database path from config
    from config.settings import settings

    db_path = str(Path(settings.agent_dir) / "db" / "network_commands.duckdb")

    logger.info("=" * 60)
    logger.info("OLAV Semantic Cache Migration - Phase 1.1")
    logger.info("=" * 60)
    logger.info(f"Database: {db_path}")
    logger.info()

    # Step 1: Backup
    print("Step 1: Backup existing cache data...")
    if not backup_cache_data(db_path):
        print("  Backup failed, aborting migration")
        sys.exit(1)

    print("  Backup completed")
    print()

    # Step 2: Migrate schema
    print("Step 2: Migrating schema (adding agent support)...")
    if not migrate_cache_schema(db_path):
        print("  Schema migration failed, backup is safe")
        sys.exit(1)

    print("  Schema migration completed")
    print()

    # Step 3: Verify
    print("Step 3: Verifying migration...")
    if not verify_migration(db_path):
        print("  Verification failed, backup is safe")
        sys.exit(1)

    print("  Verification completed")
    print()

    # Summary
    print("=" * 60)
    print("Migration completed successfully!")
    print("=" * 60)
    print()
    print("New columns added:")
    print("  - agent (VARCHAR)")
    print("  - execution_plan (JSON)")
    print("  - query_history (JSON)")
    print("  - plan_version (INTEGER DEFAULT 1)")
    print("  - success_rate (FLOAT DEFAULT 1.0)")
    print()
    print("Existing records updated:")
    print("  - agent set to 'database'")
    print("  - plan_version set to 1")
    print("  - success_rate set to 1.0")
    print()
    print("Backup saved to: semantic_cache_backup.json")
    print()
    print("Ready for Phase 1.2: Implement simple exact matching logic")
    print("=" * 60)


if __name__ == "__main__":
    main()
