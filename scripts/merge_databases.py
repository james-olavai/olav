#!/usr/bin/env python3
"""
Merge network.duckdb into main.duckdb

This script merges all tables from network.duckdb into main.duckdb,
creating a unified business database.

Usage:
    uv run python scripts/merge_databases.py
"""

import duckdb
from pathlib import Path
import shutil
from datetime import datetime


def main():
    """Merge network.duckdb into main.duckdb"""
    
    # Paths
    main_db = Path(".olav/db/main.duckdb")
    network_db = Path(".olav/db/network.duckdb")
    backup_dir = Path(".olav/backups")
    
    # Validate
    if not network_db.exists():
        print("❌ network.duckdb not found. Already merged?")
        return
    
    if not main_db.exists():
        print("❌ main.duckdb not found. Please check database location.")
        return
    
    # Backup
    backup_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_main = backup_dir / f"main_backup_{timestamp}.duckdb"
    backup_network = backup_dir / f"network_backup_{timestamp}.duckdb"
    
    print(f"📦 Backing up databases...")
    shutil.copy2(main_db, backup_main)
    shutil.copy2(network_db, backup_network)
    print(f"   ✅ Backed up to {backup_dir}/")
    
    # Connect to main.duckdb
    print(f"\n🔗 Connecting to main.duckdb...")
    conn = duckdb.connect(str(main_db))
    
    # Attach network.duckdb
    print(f"🔗 Attaching network.duckdb...")
    conn.execute(f"ATTACH '{network_db}' AS network_db")
    
    # Get tables from network.duckdb
    print(f"\n📋 Listing tables in network.duckdb...")
    tables_result = conn.execute("""
        SELECT table_name 
        FROM network_db.information_schema.tables 
        WHERE table_schema = 'main'
        ORDER BY table_name
    """).fetchall()
    
    tables = [row[0] for row in tables_result]
    
    if not tables:
        print("⚠️  No tables found in network.duckdb")
        conn.close()
        return
    
    print(f"   Found {len(tables)} tables: {', '.join(tables)}")
    
    # Check for conflicts
    print(f"\n🔍 Checking for table conflicts...")
    existing_tables = [
        row[0] for row in
        conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()
    ]
    
    conflicts = set(tables) & set(existing_tables)
    
    if conflicts:
        print(f"   ⚠️  Conflicting tables: {', '.join(conflicts)}")
        print(f"   These tables exist in both databases. They will be replaced.")
        
        response = input("\n   Continue? (y/N): ")
        if response.lower() != 'y':
            print("❌ Merge cancelled.")
            conn.close()
            return
        
        # Drop conflicting tables from main
        for table in conflicts:
            print(f"   🗑️  Dropping {table} from main.duckdb...")
            conn.execute(f"DROP TABLE IF EXISTS {table}")
    
    # Copy tables
    print(f"\n📥 Copying tables to main.duckdb...")
    for table in tables:
        print(f"   Copying {table}...", end=" ")
        
        try:
            # Get row count
            count = conn.execute(f"SELECT COUNT(*) FROM network_db.{table}").fetchone()[0]
            
            # Copy table
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM network_db.{table}")
            
            # Verify
            new_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            
            if new_count == count:
                print(f"✅ ({new_count} rows)")
            else:
                print(f"⚠️  Row count mismatch: {count} → {new_count}")
        
        except Exception as e:
            print(f"❌ Error: {e}")
    
    # Detach
    conn.execute("DETACH network_db")
    
    # Verify final state
    print(f"\n✅ Merge completed!")
    print(f"\n📊 Final statistics:")
    
    all_tables = conn.execute("""
        SELECT table_name, 
               (SELECT COUNT(*) FROM information_schema.columns WHERE table_name = t.table_name) as column_count
        FROM information_schema.tables t
        WHERE table_schema = 'main'
        ORDER BY table_name
    """).fetchall()
    
    for table, col_count in all_tables:
        row_count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"   - {table}: {row_count} rows, {col_count} columns")
    
    # Close connection
    conn.close()
    
    # Archive network.duckdb
    print(f"\n📦 Archiving original network.duckdb...")
    archived_network = backup_dir / f"network_archived_{timestamp}.duckdb"
    shutil.move(network_db, archived_network)
    print(f"   ✅ Moved to {archived_network}")
    
    print(f"\n🎉 Database merge successful!")
    print(f"\n📝 Summary:")
    print(f"   - Merged {len(tables)} tables")
    print(f"   - Backups: {backup_dir}/")
    print(f"   - Original network.duckdb archived")
    print(f"\n⚠️  If issues occur, restore from backup:")
    print(f"   cp {backup_main} {main_db}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Merge cancelled by user.")
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        print(f"\n💡 Restore from backup if needed:")
        print(f"   ls -la .olav/backups/")
