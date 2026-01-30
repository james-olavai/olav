"""
Database Index Optimization Script

This script creates indexes on frequently queried columns to improve query performance.
Run this after initial data load or periodically to optimize the database.

Usage:
    uv run python .olav/scripts/optimize_database.py
"""

import sys
from pathlib import Path

import duckdb


def create_indexes(db_path: Path) -> None:
    """Create performance indexes on DuckDB database.
    
    Args:
        db_path: Path to DuckDB database file
    """
    print(f"📊 Optimizing database: {db_path}")
    
    conn = duckdb.connect(str(db_path))
    
    indexes = [
        # raw_outputs table indexes
        ("idx_raw_device", "raw_outputs", "(device)"),
        ("idx_raw_sync_date", "raw_outputs", "(sync_date)"),
        ("idx_raw_created_at", "raw_outputs", "(created_at)"),
        ("idx_raw_device_date", "raw_outputs", "(device, sync_date)"),
        
        # sync_metadata table indexes
        ("idx_sync_date", "sync_metadata", "(sync_date)"),
        ("idx_sync_created_at", "sync_metadata", "(created_at)"),
        
        # command_cache table indexes
        ("idx_cache_device", "command_cache", "(device)"),
        ("idx_cache_command", "command_cache", "(command)"),
    ]
    
    created = 0
    skipped = 0
    
    for index_name, table_name, columns in indexes:
        try:
            # Check if index already exists
            existing = conn.execute(
                f"SELECT COUNT(*) FROM duckdb_indexes() WHERE index_name = '{index_name}'"
            ).fetchone()[0]
            
            if existing > 0:
                print(f"  ⏭️  Index {index_name} already exists")
                skipped += 1
                continue
            
            # Create index
            conn.execute(f"CREATE INDEX {index_name} ON {table_name} {columns}")
            print(f"  ✅ Created index: {index_name} on {table_name}{columns}")
            created += 1
            
        except Exception as e:
            print(f"  ⚠️  Failed to create {index_name}: {e}")
    
    # Analyze tables for query optimization
    print("\n📈 Analyzing tables...")
    tables = ["raw_outputs", "sync_metadata", "command_cache", "device_capabilities"]
    
    for table in tables:
        try:
            conn.execute(f"ANALYZE {table}")
            print(f"  ✅ Analyzed: {table}")
        except Exception as e:
            print(f"  ⚠️  Failed to analyze {table}: {e}")
    
    conn.close()
    
    print(f"\n✅ Optimization complete: {created} indexes created, {skipped} skipped")


def main() -> int:
    """Main entry point."""
    db_path = Path(".olav/db/olav.duckdb")
    
    if not db_path.exists():
        print(f"❌ Database not found: {db_path}")
        return 1
    
    print("🔧 OLAV Database Optimization")
    print("=" * 50)
    
    create_indexes(db_path)
    
    print("=" * 50)
    print("✅ Database optimization complete")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
