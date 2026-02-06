# Network Query - Reference Documentation

## Table of Contents
- [Complete Table Schema](#complete-table-schema)
- [Advanced DuckDB Usage](#advanced-duckdb-usage)
- [Complex Query Examples](#complex-query-examples)
- [Performance Optimization](#performance-optimization)
- [Common Mistakes & Solutions](#common-mistakes--solutions)

---

## Complete Table Schema

### Core Tables (Always Available)

#### devices - Network Device Inventory
**Purpose**: Master inventory of all network devices
**Primary Key**: `hostname`

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| hostname | VARCHAR | Unique device name | "R1", "SW1" |
| ip_address | VARCHAR | Management IP | "192.168.1.1" |
| vendor | VARCHAR | Equipment vendor | "Cisco", "Arista", "Juniper" |
| model | VARCHAR | Device model | "ASR1001-X", "N9K-C9300" |
| ios_version | VARCHAR | Software version | "16.12.04", "9.2.3.5" |
| device_role | VARCHAR | Network function | "core", "distribution", "access", "bgp" |
| site | VARCHAR | Physical location | "HQ", "DC1", "branch-01" |
| serial_number | VARCHAR | Hardware serial | "FDO12345ABC" |
| is_active | BOOLEAN | Device availability | true, false |
| created_at | TIMESTAMP | First seen | 2025-12-01 10:30:00 |
| updated_at | TIMESTAMP | Last update | 2026-01-15 14:22:00 |

**Useful Queries**:
```sql
-- Count devices by role
SELECT device_role, COUNT(*) as count FROM devices GROUP BY device_role

-- Find all active core devices
SELECT hostname, ip_address FROM devices 
WHERE is_active = true AND device_role = 'core'

-- Devices by vendor
SELECT vendor, COUNT(*) as count FROM devices GROUP BY vendor
```

---

#### raw_outputs - Raw CLI Command Results
**Purpose**: Cache of all executed show commands (text format)
**Primary Key**: `id` (auto-increment)

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| id | INTEGER | Unique record ID | 12345 |
| device | VARCHAR | Target device hostname | "R1" |
| command | VARCHAR | CLI command executed | "show ip interface brief" |
| output | TEXT | Raw command output | "Interface    IP Address..." |
| sync_date | DATE | Collection date | 2026-01-15 |
| created_at | TIMESTAMP | Record creation | 2026-01-15 10:30:00 |
| parser_used | VARCHAR | Parser template | "cisco_ios_show_interfaces" |
| parsed_output | VARCHAR | Structured data (if available) | JSON string |

**Important Notes**:
- `output` column contains FULL raw CLI text (multi-line)
- `device` column matches `devices.hostname` (use for JOINs)
- Multiple records per device (one per command per sync)
- `command` is the unique identifier for analyzing what was captured

**Useful Queries**:
```sql
-- List all unique commands captured
SELECT DISTINCT command FROM raw_outputs ORDER BY command

-- Count how many times each command was captured
SELECT command, COUNT(*) as executions 
FROM raw_outputs 
GROUP BY command 
ORDER BY executions DESC

-- Recent outputs for a device (last 24h)
SELECT command, output, created_at FROM raw_outputs
WHERE device = 'R1' AND created_at > NOW() - INTERVAL 24 HOURS
ORDER BY created_at DESC

-- Find which devices have a specific command captured
SELECT DISTINCT device FROM raw_outputs 
WHERE command = 'show ip ospf neighbor'
```

---

### Typical Queries by Data Type

| Need | Table | WHERE Clause |
|------|-------|--------------|
| Device list/metadata | `devices` | `device_role = 'X'` |
| Interface info | `raw_outputs` | `command = 'show ip interface brief'` |
| BGP neighbors | `raw_outputs` | `command = 'show ip bgp summary'` |
| OSPF neighbors | `raw_outputs` | `command = 'show ip ospf neighbor'` |
| Routing table | `raw_outputs` | `command = 'show ip route'` |
| CDP/LLDP neighbors | `raw_outputs` | `command = 'show cdp neighbors detail'` |
| Device version | `raw_outputs` | `command = 'show version'` |
| ARP table | `raw_outputs` | `command = 'show arp'` |
| BGP config | `raw_outputs` | `command = 'show ip bgp config'` |

---

## Advanced DuckDB Usage

### 1. Aggregate Functions

**COUNT**: Number of rows matching condition
```sql
-- How many commands per device?
SELECT device, COUNT(*) as total_commands
FROM raw_outputs
GROUP BY device
ORDER BY total_commands DESC
```

**SUM, AVG, MIN, MAX**: Numerical operations
```sql
-- Not typically used on network data, but example:
SELECT COUNT(DISTINCT command) as unique_commands_captured
FROM raw_outputs
WHERE created_at > NOW() - INTERVAL 7 DAYS
```

**DISTINCT**: Remove duplicates
```sql
-- List all unique commands captured across network
SELECT DISTINCT command FROM raw_outputs ORDER BY command

-- Count how many devices have captured each command
SELECT command, COUNT(DISTINCT device) as devices_with_command
FROM raw_outputs
GROUP BY command
```

---

### 2. Window Functions (Advanced Analysis)

**ROW_NUMBER**: Rank rows within a group
```sql
-- Rank commands by how many times they appear (per device)
SELECT device, command, COUNT(*) as executions,
       ROW_NUMBER() OVER (PARTITION BY device ORDER BY COUNT(*) DESC) as rank
FROM raw_outputs
GROUP BY device, command
-- Shows most-executed commands per device
```

**LAG/LEAD**: Compare row to previous/next
```sql
-- Track when each command was last run (for change detection)
SELECT device, command, created_at,
       LAG(created_at) OVER (PARTITION BY device, command ORDER BY created_at) as previous_run
FROM raw_outputs
ORDER BY device, command, created_at DESC
-- Helps detect command sync intervals
```

---

### 3. Common Table Expressions (WITH)

**Purpose**: Create temporary named result sets for complex queries

```sql
-- Find devices with captured data in the last 24 hours
WITH recent_syncs AS (
  SELECT DISTINCT device
  FROM raw_outputs
  WHERE created_at > NOW() - INTERVAL 24 HOURS
)
SELECT d.hostname, d.ip_address, d.device_role
FROM devices d
WHERE d.hostname IN (SELECT device FROM recent_syncs)
ORDER BY d.hostname
```

**Multi-step analysis with CTE:**
```sql
-- Identify OSPF-enabled devices and their neighbors
WITH ospf_outputs AS (
  SELECT device, output
  FROM raw_outputs
  WHERE command = 'show ip ospf neighbor'
    AND created_at > NOW() - INTERVAL 7 DAYS
),
ospf_devices AS (
  SELECT DISTINCT device FROM ospf_outputs
)
SELECT d.hostname, d.ip_address, d.device_role, COUNT(o.id) as ospf_captures
FROM devices d
JOIN ospf_devices od ON d.hostname = od.device
LEFT JOIN raw_outputs o ON d.hostname = o.device AND o.command = 'show ip ospf neighbor'
GROUP BY d.hostname, d.ip_address, d.device_role
ORDER BY ospf_captures DESC
```

---

### 4. Date/Time Operations

**NOW()**: Current timestamp
**INTERVAL**: Time duration (HOUR, DAY, WEEK, MONTH, YEAR)
**DATE_TRUNC()**: Round timestamp to interval

```sql
-- Data from past 24 hours
SELECT * FROM raw_outputs 
WHERE created_at > NOW() - INTERVAL 24 HOURS

-- Data from today
SELECT * FROM raw_outputs
WHERE DATE_TRUNC('day', created_at) = DATE_TRUNC('day', NOW())

-- Data from past week, grouped by day
SELECT DATE_TRUNC('day', created_at) as day, COUNT(*) as captures
FROM raw_outputs
WHERE created_at > NOW() - INTERVAL 7 DAYS
GROUP BY DATE_TRUNC('day', created_at)
ORDER BY day DESC
```

---

### 5. String Operations

**LIKE**: Pattern matching
**ILIKE**: Case-insensitive pattern matching
**CONTAINS**: Check if string contains substring

```sql
-- Find all "show ip" commands
SELECT DISTINCT command FROM raw_outputs
WHERE command LIKE 'show ip%'

-- Find interface commands (case-insensitive for vendor differences)
SELECT DISTINCT command FROM raw_outputs
WHERE command ILIKE '%interface%'

-- Search output for specific content
SELECT device, command FROM raw_outputs
WHERE output CONTAINS 'down' AND created_at > NOW() - INTERVAL 1 DAY
```

---

### 6. CASE Statements (Conditional Logic)

**Purpose**: Create conditional columns

```sql
-- Classify devices by role and count their commands
SELECT 
  d.hostname,
  d.device_role,
  CASE 
    WHEN d.device_role = 'core' THEN 'Critical'
    WHEN d.device_role IN ('distribution', 'border') THEN 'Important'
    ELSE 'Standard'
  END as tier,
  COUNT(r.id) as total_snapshots
FROM devices d
LEFT JOIN raw_outputs r ON d.hostname = r.device
GROUP BY d.hostname, d.device_role, tier
ORDER BY tier, d.hostname
```

---

### 7. LIMIT and OFFSET (Pagination)

**LIMIT N**: Return only first N rows
**OFFSET N**: Skip first N rows

```sql
-- Get latest 100 command outputs
SELECT * FROM raw_outputs
ORDER BY created_at DESC
LIMIT 100

-- Pagination: Get rows 101-200
SELECT * FROM raw_outputs
ORDER BY created_at DESC
LIMIT 100 OFFSET 100
```

---

## Complex Query Examples

### Example 1: Multi-Layer Analysis
**Goal**: "Show which core and distribution devices have OSPF configured and how many neighbors they have"

```sql
WITH ospf_data AS (
  SELECT device, output, created_at
  FROM raw_outputs
  WHERE command = 'show ip ospf neighbor'
    AND created_at > NOW() - INTERVAL 7 DAYS
),
latest_ospf AS (
  SELECT device, output,
         ROW_NUMBER() OVER (PARTITION BY device ORDER BY created_at DESC) as rn
  FROM ospf_data
)
SELECT 
  d.hostname,
  d.ip_address,
  d.device_role,
  COUNT(DISTINCT lo.device) as ospf_configured,
  MAX(lo.output) as latest_neighbors_output
FROM devices d
LEFT JOIN latest_ospf lo ON d.hostname = lo.device AND lo.rn = 1
WHERE d.device_role IN ('core', 'distribution') AND d.is_active = true
GROUP BY d.hostname, d.ip_address, d.device_role
ORDER BY d.device_role, d.hostname
```

### Example 2: Change Detection
**Goal**: "Identify devices where commands changed since last capture"

```sql
WITH ranked_commands AS (
  SELECT 
    device,
    command,
    output,
    created_at,
    ROW_NUMBER() OVER (PARTITION BY device, command ORDER BY created_at DESC) as rank
  FROM raw_outputs
  WHERE created_at > NOW() - INTERVAL 7 DAYS
),
current_and_previous AS (
  SELECT 
    device,
    command,
    MAX(CASE WHEN rank = 1 THEN output END) as current_output,
    MAX(CASE WHEN rank = 2 THEN output END) as previous_output
  FROM ranked_commands
  GROUP BY device, command
)
SELECT device, command, 
       CASE WHEN current_output != previous_output THEN 'CHANGED' ELSE 'SAME' END as status
FROM current_and_previous
WHERE current_output IS NOT NULL AND previous_output IS NOT NULL
  AND current_output != previous_output
ORDER BY device, command
```

### Example 3: Coverage Analysis
**Goal**: "Which devices have the fewest commands captured? What's missing?"

```sql
WITH device_commands AS (
  SELECT device, COUNT(DISTINCT command) as unique_commands
  FROM raw_outputs
  WHERE created_at > NOW() - INTERVAL 7 DAYS
  GROUP BY device
),
all_commands AS (
  SELECT DISTINCT command FROM raw_outputs
),
expected_count AS (
  SELECT COUNT(*) as total_unique_commands FROM all_commands
)
SELECT 
  d.hostname,
  d.device_role,
  dc.unique_commands,
  ec.total_unique_commands,
  (ec.total_unique_commands - dc.unique_commands) as missing_commands,
  ROUND(100.0 * dc.unique_commands / ec.total_unique_commands, 1) as coverage_percent
FROM devices d
LEFT JOIN device_commands dc ON d.hostname = dc.device
CROSS JOIN expected_count ec
WHERE d.is_active = true
ORDER BY coverage_percent ASC, d.hostname
```

---

## Performance Optimization

### 1. Add Time Filters
**Always filter by date when possible** - dramatically improves query speed:

```sql
-- SLOW (scans entire raw_outputs table)
SELECT device, output FROM raw_outputs WHERE command = 'show interfaces'

-- FAST (only scans recent data)
SELECT device, output FROM raw_outputs 
WHERE command = 'show interfaces'
  AND created_at > NOW() - INTERVAL 7 DAYS
```

### 2. Use WHERE Before COUNT
**Filter before aggregation**:

```sql
-- SLOW (counts all rows, then filters)
SELECT * FROM (
  SELECT device, COUNT(*) FROM raw_outputs GROUP BY device
) WHERE COUNT > 100

-- FAST (filters first, then counts)
SELECT device, COUNT(*) FROM raw_outputs 
GROUP BY device 
HAVING COUNT(*) > 100
```

### 3. SELECT Only Needed Columns
**Avoid SELECT *:**

```sql
-- SLOW (retrieves large output field when not needed)
SELECT * FROM raw_outputs WHERE device = 'R1'

-- FAST (only retrieve needed columns)
SELECT device, command, created_at FROM raw_outputs WHERE device = 'R1'
```

### 4. Use LIMIT for Large Results
**Preview data before full retrieval:**

```sql
-- SLOW (returns all raw_outputs - potentially millions of rows)
SELECT * FROM raw_outputs WHERE command = 'show interfaces'

-- FAST (preview first 100, understand structure)
SELECT * FROM raw_outputs WHERE command = 'show interfaces' LIMIT 100
```

---

## Common Mistakes & Solutions

### Mistake 1: Assuming Specific Columns Exist

```sql
-- ❌ FAILS if column doesn't exist
SELECT interface_name FROM raw_outputs

-- ✅ WORKS - Always verify first
SELECT * FROM raw_outputs LIMIT 1  -- See what columns actually exist
```

**Solution**: Run `inspect_schema('raw_outputs')` before building queries

---

### Mistake 2: Using Per-Device Loops Instead of Joins

```sql
-- ❌ SLOW & WRONG (queries each device individually)
FOR EACH device:
  SELECT output FROM raw_outputs WHERE device = device

-- ✅ FAST & RIGHT (single query with JOIN)
SELECT d.hostname, r.output
FROM devices d
JOIN raw_outputs r ON d.hostname = r.device
WHERE r.command = 'show interfaces'
```

---

### Mistake 3: Assuming Raw Text is Structured

```sql
-- ❌ FAILS (raw_outputs.output is raw CLI text, not JSON)
SELECT JSON_EXTRACT(output, '$.interfaces') FROM raw_outputs

-- ✅ WORKS (must parse the text manually)
SELECT device, output FROM raw_outputs WHERE command = 'show interfaces'
-- Then parse the multi-line text output in application code
```

---

### Mistake 4: Ignoring Time Filters

```sql
-- ❌ SLOW QUERY (scans entire history)
SELECT COUNT(*) FROM raw_outputs

-- ✅ FAST QUERY (scans only recent data)
SELECT COUNT(*) FROM raw_outputs 
WHERE created_at > NOW() - INTERVAL 24 HOURS
```

---

### Mistake 5: Case Sensitivity in Joins

```sql
-- ❌ May fail if case doesn't match exactly
SELECT d.hostname, r.output
FROM devices d
JOIN raw_outputs r ON d.hostname = r.device

-- ✅ WORKS (if case mismatches, use LOWER)
SELECT d.hostname, r.output
FROM devices d
JOIN raw_outputs r ON LOWER(d.hostname) = LOWER(r.device)
```

---

## Quick Reference Cheat Sheet

```sql
-- List everything
SELECT * FROM devices LIMIT 10

-- Device count per role
SELECT device_role, COUNT(*) FROM devices GROUP BY device_role

-- Commands captured
SELECT DISTINCT command FROM raw_outputs ORDER BY command

-- Recent data
SELECT * FROM raw_outputs 
WHERE created_at > NOW() - INTERVAL 24 HOURS

-- Join devices with commands
SELECT d.hostname, r.command, r.created_at
FROM devices d
JOIN raw_outputs r ON d.hostname = r.device
ORDER BY d.hostname, r.created_at DESC

-- Grouped by command (most recent per command per device)
SELECT d.hostname, r.command, MAX(r.created_at) as latest
FROM devices d
JOIN raw_outputs r ON d.hostname = r.device
GROUP BY d.hostname, r.command
ORDER BY d.hostname

-- Find data gaps (devices without recent data)
SELECT d.hostname, MAX(r.created_at) as latest_capture
FROM devices d
LEFT JOIN raw_outputs r ON d.hostname = r.device
WHERE d.is_active = true
GROUP BY d.hostname
ORDER BY latest_capture ASC NULLS FIRST
```

