#!/usr/bin/env python3
"""Database completeness verification script."""
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

def check_database_completeness():
    """Check if all test devices are in the database."""
    print("=" * 70)
    print("Database Completeness Verification")
    print("=" * 70)
    
    try:
        from olav.lib.data_gateway import UnifiedDatabase
        import duckdb
        
        # Get database paths
        db = UnifiedDatabase()
        orchestrator_path = os.path.expanduser("~/.olav/data/orchestrator.duckdb")
        
        print("\n📊 Checking database locations...")
        print(f"  Orchestrator DB: {orchestrator_path}")
        print(f"  Exists: {os.path.exists(orchestrator_path)}")
        
        # Connect and query
        print("\n🔍 Querying device inventory...")
        conn = duckdb.connect(orchestrator_path, read_only=True)
        
        # List all tables
        tables = conn.execute("SELECT * FROM information_schema.tables WHERE table_schema='main'").fetchall()
        print(f"\n📋 Available tables ({len(tables)}):")
        for table in tables:
            print(f"  - {table[3]}")
        
        # Check snapshots table
        print("\n📸 Checking snapshots table...")
        try:
            snapshots = conn.execute("SELECT * FROM snapshots LIMIT 1").fetchall()
            print(f"  Snapshots table exists: ✅")
            print(f"  Sample record: {snapshots[0] if snapshots else 'Empty'}")
        except Exception as e:
            print(f"  Snapshots table error: {e}")
        
        # Check devices
        print("\n🖥️  Checking devices in database...")
        try:
            devices_query = """
            SELECT DISTINCT device_name 
            FROM snapshots 
            GROUP BY device_name 
            ORDER BY device_name
            """
            devices = conn.execute(devices_query).fetchall()
            print(f"  Total unique devices: {len(devices)}")
            for device in devices:
                print(f"    - {device[0]}")
            
            # Expected devices
            expected = {"R1", "R2", "R3", "SW1"}
            found = {d[0] for d in devices}
            missing = expected - found
            
            if not missing:
                print(f"\n✅ All expected devices found!")
            else:
                print(f"\n⚠️  Missing devices: {missing}")
                print(f"   Please run: olav snapshot collect --devices {','.join(missing)}")
                
        except Exception as e:
            print(f"  Error querying devices: {e}")
        
        # Check data freshness
        print("\n⏰ Checking data freshness...")
        try:
            freshness_query = """
            SELECT device_name, MAX(collected_at) as latest 
            FROM snapshots 
            GROUP BY device_name 
            ORDER BY latest DESC
            """
            freshness = conn.execute(freshness_query).fetchall()
            for device, timestamp in freshness:
                print(f"  {device}: {timestamp}")
        except Exception as e:
            print(f"  Error checking freshness: {e}")
        
        conn.close()
        
        print("\n" + "=" * 70)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_database_completeness()
