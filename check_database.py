#!/usr/bin/env python3
"""Quick database verification and repair script"""

import sys
from pathlib import Path

print("🔍 Checking OLAV database status...")

# Check if database exists
db_path = Path(".olav/db/main.duckdb")
if not db_path.exists():
    print(f"❌ Database not found: {db_path}")
    print("\n💡 Solution: Run 'uv run python setup_devices_in_main_db.py'")
    sys.exit(1)

# Check database content
try:
    import duckdb
    
    conn = duckdb.connect(str(db_path))
    
    # Check devices table
    try:
        device_count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        print(f"✅ devices table: {device_count} rows")
        
        if device_count == 0:
            print("⚠️  devices table is empty!")
            print("💡 Solution: Run 'uv run python setup_devices_in_main_db.py'")
        else:
            # Show sample devices
            devices = conn.execute("SELECT hostname, ip_address FROM devices LIMIT 3").fetchall()
            print("\n📱 Sample devices:")
            for d in devices:
                print(f"  - {d[0]}: {d[1]}")
                
    except Exception as e:
        print(f"❌ devices table error: {e}")
        print("💡 Solution: Run 'uv run python setup_devices_in_main_db.py'")
        sys.exit(1)
    
    # Check for views
    try:
        views = conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_type='VIEW'"
        ).fetchall()
        
        if views:
            print(f"\n✅ Found {len(views)} views:")
            for v in views:
                print(f"  - {v[0]}")
        else:
            print("\n⚠️  No views found (v_lldp, v_bgp_neighbors, etc.)")
            print("💡 This is OK if you haven't run 'olav sync' yet")
            
    except Exception as e:
        print(f"ℹ️  Views check: {e}")
    
    # Check raw_outputs table
    try:
        raw_count = conn.execute("SELECT COUNT(*) FROM raw_outputs").fetchone()[0]
        print(f"\n✅ raw_outputs table: {raw_count} rows")
        
        if raw_count == 0:
            print("⚠️  No CLI output data yet")
            print("💡 Run 'olav sync' to collect device data")
            
    except Exception as e:
        print(f"ℹ️  raw_outputs table: {e}")
    
    conn.close()
    
    print("\n" + "="*60)
    print("✅ Database check complete!")
    print("="*60)
    
except Exception as e:
    print(f"❌ Database check failed: {e}")
    sys.exit(1)
