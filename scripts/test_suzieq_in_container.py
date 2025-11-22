#!/usr/bin/env python3
"""Test SuzieQ inside Docker container."""

from suzieq.sqobjects import get_sqobject
from suzieq.shared.context import SqContext

# Initialize context with explicit paths
ctxt = SqContext(cfg={
    'data-directory': '/suzieq/parquet',
    'schema-directory': '/usr/local/lib/python3.9/site-packages/suzieq/config/schema'
})

# Test 1: Device table
print("=" * 60)
print("Test 1: Device table")
print("=" * 60)
device = get_sqobject('device')(context=ctxt)
df = device.get()
print(f"Total devices: {len(df)}")
if len(df) > 0:
    print(df[['namespace', 'hostname', 'model', 'version']].to_string())
else:
    print("No devices found")
print()

# Test 2: Interfaces table
print("=" * 60)
print("Test 2: Interfaces table (R1)")
print("=" * 60)
interfaces = get_sqobject('interfaces')(context=ctxt)
df = interfaces.get(hostname='R1')
print(f"Total interfaces: {len(df)}")
if len(df) > 0:
    print(df[['namespace', 'hostname', 'ifname', 'state', 'adminState']].to_string())
else:
    print("No interfaces found for R1")
print()

# Test 3: Summarize interfaces
print("=" * 60)
print("Test 3: Interfaces summary")
print("=" * 60)
df = interfaces.summarize()
print(f"Summary records: {len(df)}")
if len(df) > 0:
    print(df.to_string())
else:
    print("No summary data")
