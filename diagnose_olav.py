#!/usr/bin/env python3
"""Diagnostic script to check OLAV issues"""

import sys
import time
from pathlib import Path

print("=" * 80)
print("OLAV Diagnostic Report")
print("=" * 80)

# 问题1: 启动时间诊断
print("\n1. Startup Time Analysis")
print("-" * 40)
start = time.time()

try:
    import olav
    import_time = time.time() - start
    print(f"✅ Import olav: {import_time:.2f}s")
except Exception as e:
    print(f"❌ Import failed: {e}")
    sys.exit(1)

# Check database files
print("\n2. Database Check")
print("-" * 40)
db_path = Path(".olav/db/main.duckdb")
if db_path.exists():
    size_mb = db_path.stat().st_size / (1024 * 1024)
    print(f"✅ Database exists: {db_path} ({size_mb:.2f} MB)")
    
    # Check tables
    try:
        import duckdb
        conn = duckdb.connect(str(db_path))
        
        # List tables
        tables = conn.execute("SHOW TABLES").fetchall()
        print(f"\n📊 Tables in database: {len(tables)}")
        for table in tables:
            count = conn.execute(f"SELECT COUNT(*) FROM {table[0]}").fetchone()[0]
            print(f"  - {table[0]}: {count} rows")
        
        # Check devices table specifically
        if any(t[0] == 'devices' for t in tables):
            devices = conn.execute("SELECT hostname, ip_address FROM devices LIMIT 5").fetchall()
            print(f"\n🖥️  Sample devices:")
            for d in devices:
                print(f"  - {d[0]} ({d[1]})")
        else:
            print("⚠️  No 'devices' table found")
        
        # Check views
        views = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_type='VIEW'").fetchall()
        print(f"\n👁️  Views: {len(views)}")
        for view in views[:5]:
            print(f"  - {view[0]}")
        
        conn.close()
    except Exception as e:
        print(f"❌ Database query failed: {e}")
else:
    print(f"❌ Database not found: {db_path}")

# Check CLI components
print("\n3. CLI Component Check")
print("-" * 40)
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import WordCompleter
    print("✅ prompt_toolkit available")
    
    # Test completer
    completer = WordCompleter(['list', 'show', 'describe', 'query'], ignore_case=True)
    print("✅ WordCompleter works")
except Exception as e:
    print(f"❌ CLI component error: {e}")

# Check query execution
print("\n4. Query Execution Test")
print("-" * 40)
try:
    from olav.lib.data_gateway import query_database
    
    result = query_database("SELECT hostname FROM devices LIMIT 3")
    if result and len(result) > 0:
        print(f"✅ Query successful: {len(result)} rows")
        print(f"  Sample: {result[0]}")
    else:
        print("⚠️  Query returned empty result")
except Exception as e:
    print(f"❌ Query failed: {e}")

# Check cache
print("\n5. Cache Check")
print("-" * 40)
cache_db = Path(".olav/cache/semantic_cache.db")
if cache_db.exists():
    size_kb = cache_db.stat().st_size / 1024
    print(f"✅ Cache exists: {size_kb:.2f} KB")
else:
    print(f"⚠️  Cache not found: {cache_db}")

# Performance summary
print("\n" + "=" * 80)
print("DIAGNOSIS SUMMARY")
print("=" * 80)
print(f"Import time: {import_time:.2f}s")
print(f"Database: {'✅ OK' if db_path.exists() else '❌ MISSING'}")
print(f"CLI: {'✅ OK' if 'PromptSession' in dir() else '❌ ERROR'}")
print("=" * 80)
