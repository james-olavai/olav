#!/usr/bin/env python3
"""Reimport snapshot data with corrected schema mapping."""

import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path(__file__).parent / "src"))
sys.path.insert(0, str(Path(__file__).parent / ".olav/skills/shared/tools"))

from raw_importer import import_sync_data

# Import data from snapshot
result = import_sync_data(Path('exports/snapshots/2026-02-13'))
print(f"\nImport Results:")
print(f"  Raw commands parsed: {result.get('raw_imported', 0)}")
print(f"  Parsed JSON imported: {result.get('parsed_imported', 0)}")
print(f"\nTotal imported: {result.get('raw_imported', 0) + result.get('parsed_imported', 0)}")

# Verify data in interfaces table
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
interface_count = conn.execute("SELECT COUNT(*) FROM interfaces").fetchone()[0]
print(f"\nInterfaces table now has: {interface_count} records")

# Show sample data
print("\nSample interface records:")
samples = conn.execute("SELECT device_name, interface_name, oper_status, ip_address FROM interfaces LIMIT 5").fetchall()
for row in samples:
    print(f"  {row}")

conn.close()
