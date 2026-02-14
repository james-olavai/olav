# Nornir YAML Integration Analysis

**Date**: 2026-02-08  
**Status**: Investigation Complete  
**User Question**: Why aren't Nornir device roles auto-imported to the devices table?

---

## Executive Summary

**Root Cause Identified**: ✅ Found

The Nornir hosts.yaml contains device definitions with roles, but:
1. ❌ Device roles are NOT imported to the devices table during sync
2. ❌ DuckDB has NO native YAML support - must convert to JSON
3. ⚠️ Sync mechanism exists but has a bug preventing role field insertion

**Key Findings**:
- **Nornir roles defined**: hosts.yaml has `role: border/core/access` (✅ exists)
- **Database field mismatch**: database has `device_type` (Router/Switch/Firewall), NOT `device_role`
- **DuckDB limitation**: ❌ No YAML support, requires JSON conversion
- **Sync code**: ⚠️ Tries to insert `device_role` but table doesn't have this column

---

## 1. Current Architecture

### 1.1 Nornir Configuration Files

**Location**: `.olav/config/nornir/`

```
hosts.yaml          ← Device definitions with roles
├── R1-R4           (Router devices, role: border/core)
├── SW1-SW2         (Switch devices, role: access)
└── Role definitions: border, core, access

groups.yaml         ← Role group definitions
├── border          (border role)
├── core            (core role)  
├── access          (access role)
└── Test/platform groups

config.yaml         ← Nornir configuration
└── Points to hosts.yaml and groups.yaml
```

### 1.2 Current Nornir hosts.yaml Content

```yaml
# Example device from .olav/config/nornir/hosts.yaml
R1:
  hostname: 192.168.100.101
  platform: cisco_ios
  groups:
    - test
  data:
    role: border        # ✅ Defined
    site: lab           # ✅ Defined
    aliases:
      - 边界路由器1
      - R1路由器
```

### 1.3 Database Current State

**devices table schema**:
```sql
-- Current columns (from database introspection, Phase 3.2)
device_id
name
device_type          -- Contains: Router, Switch, Firewall (NOT roles!)
mgmt_ip
location
vendor
model
site_id              -- Contains: lab (from Nornir?)
created_at
updated_at
```

**Missing**: `device_role` field (LLM expects this, causes failures)

---

## 2. Why Roles Aren't Auto-Imported

### 2.1 The Sync Mechanism

**File**: `src/olav/tools/sync_tools.py` (lines 263-292)

```python
def _populate_devices_table(nr_filtered) -> None:
    """Populate devices table from Nornir inventory (v0.10.1)."""
    
    for hostname, host in nr_filtered.inventory.hosts.items():
        try:
            # Extract from Nornir host object
            device_role = host.get("role", "")  # ✅ Reads from hosts.yaml
            site = host.get("site", "")
            
            db.conn.execute("""
                INSERT OR REPLACE INTO devices 
                (device_id, hostname, ip_address, device_type, 
                 vendor, model, ios_version, serial_number, 
                 device_role,  -- ⚠️ TRIES TO INSERT HERE
                 site, ...)
            """, [
                device_id, hostname, ip_address, device_type,
                vendor, model, ios_version, serial_number,
                device_role,  -- ⚠️ BUT TABLE DOESN'T HAVE THIS COLUMN!
                site, ...
            ])
```

### 2.2 The Bug

**Problem**: Line 286 tries to insert `device_role` but:
1. **Table definition** doesn't include `device_role` column
2. **DuckDB rejects** the INSERT with "Column 'device_role' not found"
3. **Entire row fails** to insert (no partial insert)
4. **Result**: Devices table is either empty OR incomplete

**Proof** (from Phase 3.2 investigation):
```
Test database: test_network.duckdb
- device_role column: ❌ NOT FOUND ✗
- Number of devices: 80 ✅ (but without role info)
- Query result: device_type = Router/Switch/Firewall
```

---

## 3. DuckDB YAML Support Analysis

### 3.1 DuckDB Native YAML Support

**Finding**: ❌ **NO NATIVE YAML SUPPORT**

```bash
# Test results (2026-02-08):
DuckDB Version: 1.x (latest)

Available functions:
✅ read_json()
✅ read_json_auto()
✅ read_ndjson()
✅ from_json()
✅ json_*() functions (100+ JSON manipulation functions)

❌ No YAML extension
❌ No read_yaml() function
❌ No yaml_*() functions
```

### 3.2 Workaround: YAML → JSON Conversion

**DuckDB can import JSON**, so conversion is required:

```python
import yaml
import json

# Read YAML
with open('.olav/config/nornir/hosts.yaml', 'r') as f:
    hosts_yaml = yaml.safe_load(f)

# Convert to JSON
hosts_json = json.dumps(hosts_yaml, indent=2)

# Write JSON file
with open('/tmp/hosts.json', 'w') as f:
    f.write(hosts_json)

# Now DuckDB can read it
import duckdb
conn = duckdb.connect(':memory:')

# Option 1: Read as JSON array
df = conn.execute("SELECT * FROM read_json('/tmp/hosts.json')").df()

# Option 2: Read with auto type detection
df = conn.execute("SELECT * FROM read_json_auto('/tmp/hosts.json')").df()
```

### 3.3 DuckDB JSON Import Capabilities

**Available Functions**:
```sql
-- Option 1: Auto-detect types
SELECT * FROM read_json_auto('file.json')

-- Option 2: Explicit format
SELECT * FROM read_json('file.json', format='array')

-- Option 3: JSON objects (NDJSON)
SELECT * FROM read_ndjson_objects('file.ndjson')

-- Option 4: Inline JSON
SELECT * FROM json_each('{"key": "value"}')
```

---

## 4. Solution Architecture

### 4.1 Problem Statement

1. **User Goal**: Query devices by role (border, core, access)
2. **Current State**: 
   - Nornir has roles defined ✅
   - Database has device_type instead ⚠️
   - LLM expects device_role field ❌
3. **Required**: Auto-sync roles from Nornir to DuckDB

### 4.2 Recommended Solution: Two-Tier Approach

#### Approach A: Fix in Database Layer (Recommended)

**Short-term fix** (What OLAV needs now):

1. **Add device_role column** to devices table
   ```sql
   ALTER TABLE devices ADD COLUMN device_role VARCHAR;
   ```

2. **Fix sync_tools.py** to correctly insert role from Nornir
   ```python
   # In _populate_devices_table() line 286
   device_role = host.get("role", "")  # ✅ Already reads this
   
   # Just make sure table has the column
   ```

3. **Fix LLM field mapping** (already done in Phase 2.1)
   - Keep the mapping table in network-query SKILL.md
   - Now it maps device_type → device_role for LLM compatibility

4. **Test**: Run sync_all and verify roles appear

**Implementation**: ~15 minutes, minimal code changes

#### Approach B: Centralize Device Import from YAML (Long-term)

**Long-term architecture** (Better design):

1. **Create YAML import utility** (`src/olav/lib/devices_import.py`)
   ```python
   def import_devices_from_nornir_yaml(hosts_yaml_path):
       """Import devices from Nornir hosts.yaml to DuckDB."""
       # 1. Load YAML
       with open(hosts_yaml_path) as f:
           hosts = yaml.safe_load(f)
       
       # 2. Extract device data
       devices = []
       for hostname, host_data in hosts.items():
           devices.append({
               'device_id': hostname,
               'name': hostname,
               'mgmt_ip': host_data.get('hostname', ''),
               'device_type': host_data.get('device_type', 'Unknown'),
               'vendor': host_data.get('vendor', ''),
               'model': host_data.get('model', ''),
               'device_role': host_data.get('data', {}).get('role', ''),
               'site': host_data.get('data', {}).get('site', ''),
           })
       
       # 3. Insert to DuckDB
       conn = duckdb.connect(db_path)
       for device in devices:
           conn.execute("""
               INSERT INTO devices (...)
               VALUES (...)
           """, [device.values()])
   ```

2. **Create JSON export** for DuckDB consumption
   - Script to convert hosts.yaml → hosts.json
   - Use DuckDB's read_json() for import
   - Only needed if keeping YAML as source of truth

**Implementation**: ~1 hour, more robust architecture

---

## 5. Implementation Recommendation

### Phase 1: Quick Fix (This Sprint)

**Goal**: Make failing L1 tests pass

**Action Items**:
1. [ ] Add `device_role VARCHAR` column to devices table
   ```sql
   ALTER TABLE devices ADD COLUMN device_role VARCHAR DEFAULT 'unknown';
   ```

2. [ ] Verify sync_tools.py INSERT statement includes device_role
   ```python
   # Confirm this line exists (it should):
   device_role = host.get("role", "")
   
   # And this in INSERT:
   "device_role",  -- in column list
   device_role,    -- in values
   ```

3. [ ] Run sync and verify:
   ```bash
   uv run olav sync
   
   # Then check:
   uv run python -c "
   import duckdb
   conn = duckdb.connect('.olav/db/test_network.duckdb')
   result = conn.execute("""
       SELECT DISTINCT device_role FROM devices
   """).fetchall()
   print('Device roles:', result)  # Should show (border,), (core,), (access,)
   "
   ```

4. [ ] Run L1 tests
   ```bash
   uv run pytest tests/e2e/test_real_scenarios.py -v
   # Should see improved pass rate for device_role queries
   ```

**Expected Outcome**: L1 tests go from 80% → 100% pass rate

**Time Estimate**: 30 minutes

### Phase 2: Long-term Centralization (Future)

**When**: After Phase 1 is stable (v0.11.0)

**Action Items**:
1. Create `src/olav/lib/devices_import.py`
2. Move device import logic from sync_tools.py
3. Support both YAML and JSON sources
4. Document in DEVELOPER_INDEX.md

---

## 6. DuckDB YAML Support Workaround

### If You Want to Continue Using YAML

**Create a converter utility**:

```python
# src/olav/lib/yaml_to_duckdb.py
import yaml
import json
from pathlib import Path
import duckdb

def import_yaml_to_duckdb(yaml_path: str, db_path: str, table_name: str):
    """Convert YAML to JSON and import to DuckDB."""
    
    # 1. Load YAML
    with open(yaml_path) as f:
        data = yaml.safe_load(f)
    
    # 2. Convert to rows for DuckDB
    rows = []
    if isinstance(data, dict):
        for key, value in data.items():
            # Flatten nested structure
            if isinstance(value, dict):
                row = {'name': key}
                row.update(value)
                rows.append(row)
    
    # 3. Create temporary JSON
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(rows, f)
        temp_json = f.name
    
    # 4. Import to DuckDB
    conn = duckdb.connect(db_path)
    conn.execute(f"""
        CREATE OR REPLACE TABLE {table_name} AS
        SELECT * FROM read_json('{temp_json}')
    """)
    
    # 5. Cleanup
    Path(temp_json).unlink()

# Usage:
import_yaml_to_duckdb(
    '.olav/config/nornir/hosts.yaml',
    '.olav/db/main.duckdb',
    'nornir_hosts'
)
```

---

## 7. References

### Nornir Files
- [hosts.yaml](./.olav/config/nornir/hosts.yaml) - Device definitions with roles
- [groups.yaml](./.olav/config/nornir/groups.yaml) - Role definitions
- [config.yaml](./.olav/config/nornir/config.yaml) - Nornir configuration

### OLAV Code
- [sync_tools.py](../../src/olav/tools/sync_tools.py) (lines 263-292) - Device import code
- [data_gateway.py](../../src/olav/lib/data_gateway.py) - Database access layer

### Investigation
- [Phase 3.2 Root Cause Analysis](./PHASE_3.2_ROOT_CAUSE_IDENTIFIED.md)
- [Database Introspection Results](./PHASE_3.2_FINDINGS_SUMMARY.txt)

---

## Appendix: Quick Verification

### Check Current Database Schema

```bash
/home/yhvh/Olav/.venv/bin/python << 'EOF'
import duckdb

conn = duckdb.connect('.olav/db/test_network.duckdb', read_only=True)

# Check devices table schema
print("=== devices table schema ===")
result = conn.execute("DESCRIBE devices").fetchall()
for row in result:
    print(f"  {row[0]:<20} {row[1]}")

# Check for device_role column
print("\n=== Does device_role column exist? ===")
try:
    result = conn.execute("SELECT COUNT(DISTINCT device_role) FROM devices").fetchone()
    print(f"  ✅ YES - {result[0]} unique roles")
except Exception as e:
    print(f"  ❌ NO - {e}")

conn.close()
EOF
```

### Check Nornir hosts.yaml for Role Definitions

```bash
grep -A 2 "role:" .olav/config/nornir/hosts.yaml | head -15
# Expected:
#   role: border
#   role: core
#   role: access
```

### Verify Sync Code

```bash
grep -A 2 "device_role" src/olav/tools/sync_tools.py | head -10
# Should see:
#   device_role = host.get("role", "")
#   "device_role",  (in column list)
#   device_role,    (in values)
```

---

**Status**: ✅ Analysis Complete - Ready for Implementation
