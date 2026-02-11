#!/usr/bin/env python3
"""Phase 3: Query Cache Diagnostic Script

Diagnoses the current state of query caching:
1. Checks if cache database exists and has entries
2. Verifies if cache is being written to
3. Checks if cache is being read during queries
4. Identifies the root cause of cache underutilization
"""

import sqlite3
from pathlib import Path
import json
from datetime import datetime

OLAV_ROOT = Path("/home/yhvh/Olav")
CACHE_DIR = OLAV_ROOT / ".olav" / "cache"
CACHE_DB_PATHS = {
    "llm_cache": CACHE_DIR / "olav_cache.db",
    "query_cache": CACHE_DIR / "query_result_cache.db",
    "semantic_cache": CACHE_DIR / "semantic_cache.db",
}

def check_cache_files_exist():
    """Check if cache database files exist."""
    print("\n" + "="*70)
    print("🔍 STEP 1: Cache Files Existence Check")
    print("="*70)
    
    for cache_name, cache_path in CACHE_DB_PATHS.items():
        exists = cache_path.exists()
        status = "✅ EXISTS" if exists else "❌ MISSING"
        size = f"({cache_path.stat().st_size / 1024:.1f} KB)" if exists else ""
        print(f"{cache_name}: {status} {size}")
        print(f"  Path: {cache_path}")
    
    return all(p.exists() for p in CACHE_DB_PATHS.values())

def check_cache_entries():
    """Check if cache databases have entries."""
    print("\n" + "="*70)
    print("🔍 STEP 2: Cache Entries Count")
    print("="*70)
    
    for cache_name, cache_path in CACHE_DB_PATHS.items():
        if not cache_path.exists():
            print(f"❌ {cache_name}: Database not found")
            continue
        
        try:
            conn = sqlite3.connect(str(cache_path))
            cursor = conn.cursor()
            
            # List all tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            if not tables:
                print(f"❌ {cache_name}: No tables found")
                conn.close()
                continue
            
            print(f"📊 {cache_name}:")
            total_entries = 0
            for table_name in tables:
                table = table_name[0]
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                total_entries += count
                print(f"  - Table '{table}': {count} entries")
            
            print(f"  📈 Total entries: {total_entries}")
            conn.close()
            
        except Exception as e:
            print(f"❌ {cache_name}: Error reading database - {e}")

def check_cache_schema():
    """Check cache database schema to understand structure."""
    print("\n" + "="*70)
    print("🔍 STEP 3: Cache Database Schema")
    print("="*70)
    
    for cache_name, cache_path in CACHE_DB_PATHS.items():
        if not cache_path.exists():
            continue
        
        try:
            conn = sqlite3.connect(str(cache_path))
            cursor = conn.cursor()
            
            # Get all tables and their columns
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = cursor.fetchall()
            
            if tables:
                print(f"\n📋 {cache_name} schema:")
                for table_name in tables:
                    table = table_name[0]
                    cursor.execute(f"PRAGMA table_info({table})")
                    columns = cursor.fetchall()
                    print(f"  Table: '{table}'")
                    for col in columns:
                        col_name, col_type = col[1], col[2]
                        print(f"    - {col_name}: {col_type}")
            
            conn.close()
        except Exception as e:
            print(f"❌ {cache_name}: Error - {e}")

def check_cache_recent_writes():
    """Check if cache has been written to recently."""
    print("\n" + "="*70)
    print("🔍 STEP 4: Recent Cache Writes")
    print("="*70)
    
    for cache_name, cache_path in CACHE_DB_PATHS.items():
        if not cache_path.exists():
            print(f"❌ {cache_name}: Database not found")
            continue
        
        # Check file modification time
        mtime = cache_path.stat().st_mtime
        mtime_age_seconds = datetime.now().timestamp() - mtime
        
        if mtime_age_seconds < 60:
            status = "✅ RECENTLY WRITTEN (< 1 minute ago)"
        elif mtime_age_seconds < 3600:
            status = f"🟡 WRITTEN {int(mtime_age_seconds / 60)} minutes ago"
        elif mtime_age_seconds < 86400:
            status = f"🟡 WRITTEN {int(mtime_age_seconds / 3600)} hours ago"
        else:
            status = f"❌ NOT WRITTEN TODAY (> {int(mtime_age_seconds / 86400)} days)"
        
        print(f"{cache_name}: {status}")

def check_query_database_integration():
    """Check if query_database tool uses cache."""
    print("\n" + "="*70)
    print("🔍 STEP 5: query_database Tool Integration")
    print("="*70)
    
    react_query_path = OLAV_ROOT / "src" / "olav" / "tools" / "react_query.py"
    
    if not react_query_path.exists():
        print(f"❌ Could not find react_query.py at {react_query_path}")
        return
    
    content = react_query_path.read_text()
    
    # Check for cache usage patterns
    cache_patterns = [
        ("SemanticQueryCache", "Cache class usage"),
        ("QueryCache", "Query cache integration"),
        ("cache.get", "Cache read operations"),
        ("cache.put", "Cache write operations"),
        ("query_cache", "Query cache field"),
    ]
    
    print("Checking query_database() for cache integration:")
    found_cache_pattern = False
    for pattern, description in cache_patterns:
        if pattern in content:
            print(f"✅ Found: {description} (pattern: {pattern})")
            found_cache_pattern = True
    
    if not found_cache_pattern:
        print("❌ No cache integration patterns found in query_database()")
        print("\n⚠️  DIAGNOSIS: query_database tool does NOT use caching")
        print("   This explains the zero cache entries")
    
    # Check for import statements
    if "QueryCache" in content or "SemanticQueryCache" in content:
        print("✅ Cache imports found")
    else:
        print("❌ No cache imports found in react_query.py")

def diagnose_root_cause():
    """Determine the root cause of cache issues."""
    print("\n" + "="*70)
    print("🎯 ROOT CAUSE ANALYSIS")
    print("="*70)
    
    # Scenario A: Cache exists but not integrated
    cache_exists = any(p.exists() for p in CACHE_DB_PATHS.values())
    
    react_query_path = OLAV_ROOT / "src" / "olav" / "tools" / "react_query.py"
    content = react_query_path.read_text() if react_query_path.exists() else ""
    cache_integration_found = "QueryCache" in content or "cache" in content.lower()
    
    print("\nDiagnosis:")
    
    if not cache_exists:
        print("❌ Scenario C (Likely): Cache database not initialized")
        print("   - SemanticQueryCache defined but never instantiated")
        print("   - Database tables never created")
        print("   Action: Create cache initialization in get_settings() or at module load time")
        
    elif cache_integration_found:
        print("🟡 Scenario B (Possible): Cache exists but has bugs")
        print("   - Database exists but not being written to")
        print("   - May have permission or SQL issues")
        print("   Action: Add logging to cache write operations")
        
    else:
        print("🔴 Scenario A (Most Likely): Cache exists but NOT integrated")
        print("   - SemanticQueryCache code exists (database files)")
        print("   - query_database() doesn't call cache methods")
        print("   - Cache is orphaned (no reads/writes happening)")
        print("   Action: Integrate cache into query_database() tool")
    
    print("\n" + "="*70)
    print("RECOMMENDATIONS:")
    print("="*70)
    print("""
For Scenario A (Cache not integrated):
1. Modify query_database() in react_query.py to:
   - Check cache before executing SQL
   - Write successful results to cache
   - Use cache hits for identical queries

For Scenario B (Cache has bugs):
1. Add logging to cache.put() and cache.get()
2. Check SQLite transaction handling
3. Verify TTL expiration not deleting all entries

For Scenario C (Cache not initialized):
1. Add cache database initialization
2. Create tables on first access
3. Ensure proper permissions for write operations
    """)

def main():
    print("\n" + "="*70)
    print("🔧 OLAV v0.10.2 Query Cache Diagnostic Tool - Phase 3")
    print("="*70)
    
    # Run all diagnostics
    files_exist = check_cache_files_exist()
    check_cache_entries()
    if files_exist:
        check_cache_schema()
    check_cache_recent_writes()
    check_query_database_integration()
    diagnose_root_cause()
    
    print("\n✅ Diagnostic complete. Check recommendations above.")

if __name__ == "__main__":
    main()
