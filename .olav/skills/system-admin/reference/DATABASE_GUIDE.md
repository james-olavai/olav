# OLAV Database Guide (DuckDB)

**Version**: v1.0.0  
**Date**: 2026-02-08  
**Target**: Developers working with OLAV databases

---

## 🎯 Overview

OLAV uses **DuckDB** as its embedded analytical database. This guide covers database architecture, querying patterns, schema management, and best practices.

**Why DuckDB?**
- ✅ Embedded (no server setup)
- ✅ Fast analytical queries (columnar storage)
- ✅ SQL-compatible (PostgreSQL dialect)
- ✅ Python-native integration
- ✅ Zero configuration

---

## 📂 Database Architecture

### Three Database Files

OLAV uses a multi-database architecture:

| Database | Path | Purpose | Tables | Read/Write |
|----------|------|---------|--------|------------|
| **main.duckdb** | `.olav/db/main.duckdb` | Device metadata | `devices` | Read/Write |
| **olav.duckdb** | `.olav/db/olav.duckdb` | CLI outputs, capabilities | `raw_outputs`, `device_capabilities` | Read/Write |
| **snapshots.duckdb** | `.olav/db/snapshots.duckdb` | Query cache | `query_cache` (deprecated) | Read-only |

### Why Multiple Files?

**Separation of Concerns**:
- **main.duckdb**: Stable device metadata (inventory, properties)
- **olav.duckdb**: Dynamic operation data (CLI outputs, runtime data)
- **snapshots.duckdb**: Historical query cache (legacy)

**Benefits**:
- Easier backup (backup main.duckdb for inventory)
- Faster queries (smaller file size)
- Clear data ownership

---

## 🔗 Unified Connection Pattern (Critical)

### Problem: Separate Connections
```python
# ❌ OLD WAY - Separate connections
conn1 = duckdb.connect(".olav/db/main.duckdb")
conn2 = duckdb.connect(".olav/db/olav.duckdb")

# Can't JOIN across databases!
# WHERE clause requires hardcoded database names
```

### Solution: Unified In-Memory Connection

**Implementation** (`src/olav/lib/data_gateway.py`):

```python
import duckdb
from config.paths import DB_MAIN_PATH, DB_OLAV_PATH, DB_SNAPSHOTS_PATH

class DataGateway:
    """Unified database access layer."""
    
    def __init__(self):
        self.conn = self._create_unified_connection()
    
    def _create_unified_connection(self) -> duckdb.DuckDBPyConnection:
        """Create unified DuckDB connection with all databases attached."""
        conn = duckdb.connect(":memory:")
        
        # Attach all databases
        conn.execute(f"ATTACH '{DB_MAIN_PATH}' AS main (READ_ONLY)")
        conn.execute(f"ATTACH '{DB_OLAV_PATH}' AS olav (READ_ONLY)")
        conn.execute(f"ATTACH '{DB_SNAPSHOTS_PATH}' AS snapshots (READ_ONLY)")
        
        # Create compatibility views (no database prefix needed)
        conn.execute("CREATE VIEW devices AS SELECT * FROM main.devices")
        conn.execute("CREATE VIEW raw_outputs AS SELECT * FROM olav.raw_outputs")
        conn.execute("CREATE VIEW device_capabilities AS SELECT * FROM olav.device_capabilities")
        
        return conn
    
    def query(self, sql: str) -> pd.DataFrame:
        """Execute SQL query."""
        return self.conn.execute(sql).fetchdf()
```

**Benefits**:
- ✅ Cross-database JOINs work seamlessly
- ✅ No database prefix needed in queries
- ✅ Transparent routing
- ✅ Single connection to manage

**Usage**:
```python
from olav.lib.data_gateway import DataGateway

gateway = DataGateway()

# Query devices (from main.duckdb)
devices = gateway.query("SELECT * FROM devices LIMIT 10")

# Query CLI outputs (from olav.duckdb)
outputs = gateway.query("SELECT * FROM raw_outputs WHERE device_name = 'router-01'")

# Cross-database JOIN (magic!)
joined = gateway.query("""
    SELECT d.name, d.vendor, r.command, r.output
    FROM devices d
    JOIN raw_outputs r ON d.name = r.device_name
    WHERE d.vendor = 'cisco'
""")
```

---

## 📊 Database Schemas

### 1. main.duckdb

**Purpose**: Device metadata (inventory, properties)

#### `devices` Table

```sql
CREATE TABLE IF NOT EXISTS devices (
    name VARCHAR PRIMARY KEY,           -- Device hostname
    ip_address VARCHAR,                 -- Management IP
    vendor VARCHAR,                     -- cisco, huawei, etc.
    model VARCHAR,                      -- Device model
    role VARCHAR,                       -- core, access, distribution
    location VARCHAR,                   -- Physical location
    version VARCHAR,                    -- Software version
    serial_number VARCHAR,              -- Serial number
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Example Query**:
```sql
-- Get all Cisco devices
SELECT name, ip_address, model, version
FROM devices
WHERE vendor = 'cisco'
ORDER BY name;
```

---

### 2. olav.duckdb

**Purpose**: CLI outputs, device capabilities, runtime data

#### `raw_outputs` Table

```sql
CREATE TABLE IF NOT EXISTS raw_outputs (
    id INTEGER PRIMARY KEY,
    device_name VARCHAR,                -- Device hostname
    command VARCHAR,                    -- CLI command executed
    output TEXT,                        -- Raw output
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR                      -- success, error
);
```

**Example Query**:
```sql
-- Get recent 'show version' outputs
SELECT device_name, command, output, timestamp
FROM raw_outputs
WHERE command LIKE '%show version%'
ORDER BY timestamp DESC
LIMIT 10;
```

#### `device_capabilities` Table

```sql
CREATE TABLE IF NOT EXISTS device_capabilities (
    device_name VARCHAR PRIMARY KEY,
    platform VARCHAR,                   -- cisco_ios, huawei_vrp, etc.
    connection_type VARCHAR,            -- ssh, telnet
    supported_commands TEXT[],          -- Array of supported commands
    last_discovered TIMESTAMP
);
```

---

### 3. snapshots.duckdb (Legacy)

**Purpose**: Query cache (deprecated, use semantic_cache.db instead)

#### `query_cache` Table (Deprecated)

```sql
CREATE TABLE IF NOT EXISTS query_cache (
    query_hash VARCHAR PRIMARY KEY,
    query_text TEXT,
    result_data TEXT,                   -- JSON string
    cached_at TIMESTAMP
);
```

**Note**: This table is deprecated. Use `.olav/cache/semantic_cache.db` instead (SQLite-based semantic cache).

---

## 🔍 Common Query Patterns

### 1. Device Inventory Queries

```sql
-- Count devices by vendor
SELECT vendor, COUNT(*) as count
FROM devices
GROUP BY vendor
ORDER BY count DESC;

-- Get devices by role
SELECT name, ip_address, model
FROM devices
WHERE role = 'core'
ORDER BY name;

-- Find devices with specific software version
SELECT name, version, vendor
FROM devices
WHERE version LIKE '%15.2%'
ORDER BY vendor, name;
```

### 2. CLI Output Analysis

```sql
-- Get all outputs for a specific device
SELECT command, output, timestamp
FROM raw_outputs
WHERE device_name = 'router-01'
ORDER BY timestamp DESC;

-- Find failed commands
SELECT device_name, command, timestamp
FROM raw_outputs
WHERE status = 'error'
ORDER BY timestamp DESC
LIMIT 20;

-- Search outputs by keyword
SELECT device_name, command, output
FROM raw_outputs
WHERE output LIKE '%error%' OR output LIKE '%down%'
ORDER BY timestamp DESC;
```

### 3. Cross-Database JOINs

```sql
-- Join devices with their CLI outputs
SELECT 
    d.name,
    d.vendor,
    d.model,
    r.command,
    r.output,
    r.timestamp
FROM devices d
LEFT JOIN raw_outputs r ON d.name = r.device_name
WHERE d.vendor = 'cisco'
ORDER BY d.name, r.timestamp DESC;

-- Get device capabilities with metadata
SELECT 
    d.name,
    d.vendor,
    d.model,
    c.platform,
    c.supported_commands
FROM devices d
LEFT JOIN device_capabilities c ON d.name = c.device_name
WHERE d.role = 'core';
```

### 4. Aggregations & Statistics

```sql
-- Device count by vendor and role
SELECT vendor, role, COUNT(*) as count
FROM devices
GROUP BY vendor, role
ORDER BY vendor, role;

-- CLI command execution frequency
SELECT command, COUNT(*) as executions
FROM raw_outputs
WHERE timestamp > CURRENT_TIMESTAMP - INTERVAL '7 days'
GROUP BY command
ORDER BY executions DESC;

-- Average CLI output size per device
SELECT 
    device_name,
    COUNT(*) as command_count,
    AVG(LENGTH(output)) as avg_output_size
FROM raw_outputs
GROUP BY device_name
ORDER BY command_count DESC;
```

---

## 🛠️ Schema Discovery

### Dynamic Schema Inspection

**Problem**: Hardcoded table/column names break when schema changes

**Solution**: Use `inspect_schema()` tool for dynamic discovery

```python
async def inspect_schema(
    database: str = "main",
    table_name: str | None = None
) -> dict[str, list[str]]:
    """Inspect database schema.
    
    Args:
        database: Database name (main, olav, snapshots)
        table_name: Specific table (None for all)
    
    Returns:
        Dictionary mapping table names to column lists
    """
    from olav.lib.data_gateway import DataGateway
    
    gateway = DataGateway()
    
    if table_name:
        # Get columns for specific table
        result = gateway.query(f"""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = '{database}'
              AND table_name = '{table_name}'
            ORDER BY ordinal_position
        """)
        return {table_name: result["column_name"].tolist()}
    else:
        # Get all tables and columns
        result = gateway.query(f"""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = '{database}'
            ORDER BY table_name, ordinal_position
        """)
        
        schema = {}
        for _, row in result.iterrows():
            table = row["table_name"]
            if table not in schema:
                schema[table] = []
            schema[table].append(row["column_name"])
        
        return schema
```

**Usage in Tools**:
```python
# ✅ GOOD - Dynamic schema discovery
schema = await inspect_schema("main", "devices")
columns = schema["devices"]

sql = f"SELECT {', '.join(columns)} FROM devices LIMIT 10"

# ❌ BAD - Hardcoded columns
sql = "SELECT name, ip_address, vendor FROM devices"  # Breaks if columns change
```

---

## 🚀 Performance Optimization

### 1. Use LIMIT for Exploration

```sql
-- ✅ GOOD - Fast exploration
SELECT * FROM devices LIMIT 10;

-- ❌ BAD - Scans entire table
SELECT * FROM devices;
```

### 2. Index Key Columns (If Needed)

**Note**: DuckDB is columnar, indexes are less critical than row-based DBs

```sql
-- Create index on frequently queried column
CREATE INDEX idx_devices_vendor ON devices(vendor);
CREATE INDEX idx_raw_outputs_device ON raw_outputs(device_name);
```

### 3. Use Appropriate Data Types

```sql
-- ✅ GOOD - Appropriate types
CREATE TABLE devices (
    name VARCHAR PRIMARY KEY,       -- String
    last_seen TIMESTAMP,            -- Datetime
    port_count INTEGER,             -- Number
    is_active BOOLEAN               -- Boolean
);

-- ❌ BAD - Everything as TEXT
CREATE TABLE devices (
    name TEXT,
    last_seen TEXT,  -- Should be TIMESTAMP
    port_count TEXT, -- Should be INTEGER
    is_active TEXT   -- Should be BOOLEAN
);
```

### 4. Filter Early, Aggregate Late

```sql
-- ✅ GOOD - Filter first
SELECT vendor, COUNT(*) 
FROM devices
WHERE role = 'core'  -- Filter early
GROUP BY vendor;

-- ⚠️ SLOW - Aggregate then filter
SELECT vendor, count
FROM (
    SELECT vendor, COUNT(*) as count
    FROM devices
    GROUP BY vendor
)
WHERE count > 10;  -- Filter after aggregation
```

---

## 🔄 Data Migration & Seeding

### Initial Setup

**Create databases and tables**:

```python
# scripts/init_databases.py
import duckdb
from config.paths import DB_MAIN_PATH, DB_OLAV_PATH

def init_main_db():
    """Initialize main.duckdb with device metadata."""
    conn = duckdb.connect(str(DB_MAIN_PATH))
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS devices (
            name VARCHAR PRIMARY KEY,
            ip_address VARCHAR,
            vendor VARCHAR,
            model VARCHAR,
            role VARCHAR,
            location VARCHAR,
            version VARCHAR,
            serial_number VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    conn.close()

def init_olav_db():
    """Initialize olav.duckdb with CLI data tables."""
    conn = duckdb.connect(str(DB_OLAV_PATH))
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_outputs (
            id INTEGER PRIMARY KEY,
            device_name VARCHAR,
            command VARCHAR,
            output TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS device_capabilities (
            device_name VARCHAR PRIMARY KEY,
            platform VARCHAR,
            connection_type VARCHAR,
            supported_commands TEXT[],
            last_discovered TIMESTAMP
        )
    """)
    
    conn.close()

if __name__ == "__main__":
    init_main_db()
    init_olav_db()
    print("✅ Databases initialized")
```

### Seed Sample Data

```python
# scripts/seed_data.py
import duckdb
from config.paths import DB_MAIN_PATH

def seed_devices():
    """Seed sample device data."""
    conn = duckdb.connect(str(DB_MAIN_PATH))
    
    devices = [
        ("router-01", "192.168.1.1", "cisco", "ISR4451", "core", "HQ", "15.6(3)M", "FOC12345"),
        ("switch-01", "192.168.1.2", "cisco", "C9300", "access", "Floor1", "16.12.04", "FOC67890"),
        ("router-02", "192.168.1.3", "huawei", "NE40E", "core", "HQ", "V800R011C10", "2102351ABC"),
    ]
    
    conn.executemany("""
        INSERT OR REPLACE INTO devices 
        (name, ip_address, vendor, model, role, location, version, serial_number)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, devices)
    
    conn.close()
    print(f"✅ Seeded {len(devices)} devices")

if __name__ == "__main__":
    seed_devices()
```

---

## 💾 Backup & Recovery

### Backup Strategy

```bash
# Backup main.duckdb (device inventory)
cp .olav/db/main.duckdb backups/main_$(date +%Y%m%d).duckdb

# Backup olav.duckdb (CLI outputs)
cp .olav/db/olav.duckdb backups/olav_$(date +%Y%m%d).duckdb

# Export to CSV (portable backup)
python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
conn.execute('COPY devices TO \"backups/devices_$(date +%Y%m%d).csv\" (HEADER)')
"
```

### Recovery from Backup

```bash
# Restore from backup
cp backups/main_20260208.duckdb .olav/db/main.duckdb

# Import from CSV
python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
conn.execute('CREATE TABLE devices AS SELECT * FROM read_csv_auto(\"backups/devices_20260208.csv\")')
"
```

---

## 🐛 Debugging & Troubleshooting

### Check Database Exists

```python
from config.paths import DB_MAIN_PATH

if not DB_MAIN_PATH.exists():
    print(f"❌ Database not found: {DB_MAIN_PATH}")
else:
    print(f"✅ Database exists: {DB_MAIN_PATH}")
```

### Inspect Tables

```bash
# Using DuckDB CLI
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
print(conn.execute('SHOW TABLES').fetchall())
"

# Output: [('devices',)]
```

### Check Row Counts

```bash
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
print('Devices:', conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0])
"
```

### Query Slow? Check Execution Plan

```sql
EXPLAIN SELECT * FROM devices WHERE vendor = 'cisco';
```

---

## 📋 Database Tasks Checklist

### Setup Tasks
- [ ] Initialize databases (`scripts/init_databases.py`)
- [ ] Seed sample data (`scripts/seed_data.py`)
- [ ] Verify tables exist
- [ ] Test unified connection

### Development Tasks
- [ ] Use DataGateway for queries
- [ ] Dynamic schema discovery
- [ ] Validate SQL before execution
- [ ] Handle errors gracefully

### Maintenance Tasks
- [ ] Regular backups (weekly/daily)
- [ ] Monitor database file sizes
- [ ] Clean up old CLI outputs (if needed)
- [ ] Verify data integrity

---

## 🚫 Anti-Patterns

### 1. DO NOT Hardcode Database Names in SQL

```sql
-- ❌ BAD - Hardcoded database prefix
SELECT * FROM main.devices WHERE name = 'router-01';

-- ✅ GOOD - Use views (no prefix needed)
SELECT * FROM devices WHERE name = 'router-01';
```

### 2. DO NOT Use Multiple Connections

```python
# ❌ BAD - Separate connections
conn1 = duckdb.connect(".olav/db/main.duckdb")
conn2 = duckdb.connect(".olav/db/olav.duckdb")

# ✅ GOOD - Unified connection
from olav.lib.data_gateway import DataGateway
gateway = DataGateway()
```

### 3. DO NOT Hardcode Paths

```python
# ❌ BAD
db_path = ".olav/db/main.duckdb"

# ✅ GOOD
from config.paths import DB_MAIN_PATH
db_path = DB_MAIN_PATH
```

### 4. DO NOT Use SELECT * in Production

```sql
-- ❌ BAD - Returns all columns (wasteful)
SELECT * FROM devices;

-- ✅ GOOD - Select only needed columns
SELECT name, ip_address, vendor FROM devices;
```

---

## 📚 References

### Documentation
- [ARCHITECTURE.md](ARCHITECTURE.md) - Database architecture overview
- [CONFIGURATION_REFERENCE.md](CONFIGURATION_REFERENCE.md) - Database paths
- [TOOL_DEVELOPMENT_GUIDE.md](TOOL_DEVELOPMENT_GUIDE.md) - Database tools

### Code References
- `src/olav/lib/data_gateway.py` - Unified database access
- `src/olav/tools/react_query.py` - Database query tools
- `config/paths.py` - Database path constants

### External Resources
- [DuckDB Documentation](https://duckdb.org/docs/)
- [DuckDB SQL Reference](https://duckdb.org/docs/sql/introduction)
- [DuckDB Python API](https://duckdb.org/docs/api/python/overview)

---

**Version**: v1.0.0 (2026-02-08)  
**Status**: ✅ Production Reference
