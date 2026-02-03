"""Test fixtures for OLAV testing."""

import pytest
import shutil
from pathlib import Path


@pytest.fixture
def empty_snapshot_db():
    """Create an empty database for testing fallback behavior.

    This fixture creates a minimal empty database to test what happens
    when database views are missing and the agent needs to fall back to CLI.
    """
    from olav.core.unified_database import UnifiedDatabase

    # Use temporary database
    original_db = Path(".olav/db/olav.duckdb")
    backup_db = Path(".olav/db/olav.duckdb.backup")

    # Backup existing database
    if original_db.exists():
        shutil.copy(original_db, backup_db)

    # Create new empty database with minimal schema
    db = UnifiedDatabase()
    db.conn.execute("CREATE TABLE IF NOT EXISTS main.semantic_cache (id INTEGER)")

    yield db

    # Restore backup
    if backup_db.exists():
        shutil.copy(backup_db, original_db)
        backup_db.unlink()


@pytest.fixture
def minimal_snapshot_db():
    """Create minimal snapshot with test data.

    This fixture creates a database with minimal test views to test
    query behavior when data exists but is incomplete.
    """
    from olav.core.unified_database import UnifiedDatabase

    db = UnifiedDatabase()

    # Create test views
    db.conn.execute("""
        CREATE OR REPLACE VIEW main.test_devices AS
        SELECT * FROM (VALUES ('R1', 'Cisco', 'IOS'), ('R2', 'Cisco', 'IOS'))
        AS t(device, vendor, platform)
    """)

    yield db

    # Cleanup
    db.conn.execute("DROP VIEW IF EXISTS main.test_devices")
