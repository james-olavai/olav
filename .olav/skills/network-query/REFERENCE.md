# Network Query - Reference Guide

**Note**: This guide covers queries from simple to complex. Agent automatically scales SQL based on user request complexity.

---

## 📖 Table of Contents
- [Simple Example](#simple-example-level-1)
- [⚠️ CRITICAL: Type Handling Rules](#critical-type-handling-rules) ← Read first!
- [Level 2: Intermediate Queries](#level-2-intermediate-queries)
- [Level 3: Advanced Queries](#level-3-advanced-queries)
- [Common Mistakes](#common-mistakes)
- [Quick References](#quick-references)

---

## Simple Example (Level 1)

**Simple Query = Just filtering**

```python
User: "List all core devices in HQ"
```

```sql
SELECT hostname, device_role, site
FROM devices
WHERE device_role = 'core' AND site = 'HQ'
ORDER BY hostname
```

**Pattern**: WHERE + ORDER BY = Done.

Move to next section for anything more complex.

---

## ⚠️ CRITICAL: Type Handling Rules

### Rule 1: Date/Time Math (MOST IMPORTANT - Fixes 60% of failures)

**Problem**: Mixing DATE and INTEGER causes "Conversion Error"

```sql
-- ❌ WRONG
WHERE created_at > CURRENT_DATE - 30

-- ✅ CORRECT - Always use INTERVAL
WHERE created_at > CURRENT_DATE - INTERVAL '30 days'
WHERE created_at > NOW() - INTERVAL '7 days'
WHERE created_at > NOW() - INTERVAL '24 hours'
```

**Why**: 
- `CURRENT_DATE` returns DATE type
- `30` is INTEGER
- DuckDB cannot subtract INTEGER from DATE
- Solution: Use `INTERVAL 'X days/hours'`

### Rule 2: String Type Comparisons

```sql
-- ❌ WRONG - Comparing to numbers
WHERE device_role IN (1, 2, 3)

-- ✅ CORRECT - Use string literals
WHERE device_role IN ('core', 'border', 'access')

-- ❌ WRONG - Numbers as strings
WHERE serial_number = 12345

-- ✅ CORRECT
WHERE serial_number = '12345'
```

### Rule 3: CAST Conversions

```sql
-- ✅ CORRECT - Explicit CAST when needed
WHERE EXTRACT(YEAR FROM created_at)::INTEGER = 2026
WHERE LOWER(hostname) = LOWER('R1')
```

---

## Level 2: Intermediate Queries

**Typical**: Time ranges + aggregation + basic JOINs. These are the most common operational queries.

### L2 Pattern 1: Time Range + Simple Count

```sql
-- Goal: Count interfaces with traffic in past 10 days
SELECT 
  interface_id,
  COUNT(*) as record_count,
  SUM(bytes_in) as total_bytes_in
FROM interface_stats
WHERE timestamp > NOW() - INTERVAL '10 days'  -- ✅ CRITICAL: INTERVAL!
GROUP BY interface_id
ORDER BY total_bytes_in DESC
LIMIT 10
```

**Key Points**:
- ✅ INTERVAL for date math (not DATE - INTEGER!)
- ✅ Simple GROUP BY (only columns in aggregation)
- ✅ One aggregation level

### L2 Pattern 2: Basic JOIN + Count

```sql
-- Goal: List devices with their interface count
SELECT 
  d.hostname,
  d.site,
  COUNT(i.interface_id) as interface_count
FROM devices d
LEFT JOIN interfaces i ON d.device_id = i.device_id
WHERE d.is_active = true
GROUP BY d.device_id, d.hostname, d.site
ORDER BY interface_count DESC
```

**Key Points**:
- ✅ LEFT JOIN (keeps all devices even if no interfaces)
- ✅ All GROUP BY columns must be in SELECT
- ✅ Simple aggregation (COUNT)

### L2 Pattern 3: Time Range + GROUP + Simple CASE

```sql
-- Goal: Get top 5 interfaces by traffic, classify as Active/Idle
SELECT 
  interface_id,
  interface_name,
  SUM(bytes_in) as total_bytes,
  CASE 
    WHEN SUM(bytes_in) > 1000000000 THEN 'Active'
    ELSE 'Idle'
  END as status
FROM interface_stats
WHERE timestamp > NOW() - INTERVAL '30 days'  -- ✅ INTERVAL!
GROUP BY interface_id, interface_name
ORDER BY total_bytes DESC
LIMIT 5
```

**Key Points**:
- ✅ CASE is SIMPLE (2-3 conditions max)
- ✅ CASE comparison uses aggregation function result
- ✅ No nested conditions

---

## Level 3: Advanced Queries

**Typical**: Complex multi-step operations, Window functions, or deep filtering logic.

### L3 Pattern 1: Multi-Step CTE (3 steps)

```sql
-- Goal: Find devices with increasing traffic trend
WITH recent_traffic AS (
  SELECT 
    interface_id,
    SUM(bytes_in) as bytes_in,
    DATE_TRUNC('day', timestamp)::DATE as day
  FROM interface_stats
  WHERE timestamp > NOW() - INTERVAL '14 days'
  GROUP BY interface_id, DATE_TRUNC('day', timestamp)
),
ranked_traffic AS (
  SELECT 
    interface_id, 
    bytes_in,
    day,
    ROW_NUMBER() OVER (PARTITION BY interface_id ORDER BY day) as day_rank
  FROM recent_traffic
),
trend_analysis AS (
  SELECT 
    interface_id,
    FIRST_VALUE(bytes_in) OVER (PARTITION BY interface_id ORDER BY day_rank) as first_day_bytes,
    LAST_VALUE(bytes_in) OVER (PARTITION BY interface_id ORDER BY day_rank ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) as last_day_bytes
  FROM ranked_traffic
)
SELECT 
  interface_id,
  first_day_bytes,
  last_day_bytes,
  CASE 
    WHEN last_day_bytes > first_day_bytes THEN 'Increasing'
    WHEN last_day_bytes < first_day_bytes THEN 'Decreasing'
    ELSE 'Stable'
  END as trend
FROM trend_analysis
WHERE first_day_bytes > 0
ORDER BY last_day_bytes DESC
```

**Key Points**:
- ✅ Multiple CTEs for logical steps
- ✅ ROW_NUMBER() for sequencing
- ✅ Window functions (FIRST_VALUE, LAST_VALUE)
- ✅ PARTITION BY for grouping over window
- ✅ CASE used for final classification only

### L3 Pattern 2: Complex JOIN + Multiple Aggregations

```sql
-- Goal: Find border devices with no OSPF neighbors, count their failures
WITH filtered_devices AS (
  SELECT device_id, hostname, site
  FROM devices
  WHERE device_role = 'border' AND is_active = true
),
ospf_status AS (
  SELECT 
    DISTINCT d.hostname,
    COUNT(neighbor) as ospf_neighbors
  FROM filtered_devices d
  LEFT JOIN ospf_neighbors on ON d.hostname = o.device
  WHERE o.timestamp > NOW() - INTERVAL '7 days'
  GROUP BY d.hostname, d.device_id
),
failure_data AS (
  SELECT 
    os.hostname,
    COUNT(*) as failure_count
  FROM ospf_status os
  LEFT JOIN interface_failures f ON os.hostname = f.device
    AND f.timestamp > NOW() - INTERVAL '7 days'
  WHERE os.ospf_neighbors = 0  -- Only devices with no OSPF
  GROUP BY os.hostname
)
SELECT 
  hostname,
  failure_count,
  CASE 
    WHEN failure_count > 5 THEN 'HighFailure'
    WHEN failure_count > 0 THEN 'SomeFailure'
    ELSE 'NoFailure'
  END as risk_level
FROM failure_data
ORDER BY failure_count DESC
```

**Key Points**:
- ✅ Filter early (Step 1)
- ✅ Build intermediate tables (Step 2-3)
- ✅ Final classification (Step 4)
- ✅ INTERVAL in WHERE clauses

### L3 Pattern 3: Ranked Window + Classification

```sql
-- Goal: Top 3 interfaces per device by traffic, with device context
WITH device_interface_stats AS (
  SELECT 
    d.hostname,
    d.site,
    i.interface_id,
    i.interface_name,
    SUM(ts.bytes_in + ts.bytes_out) as total_bytes,
    MAX(ts.timestamp) as last_active
  FROM devices d
  JOIN interfaces i ON d.device_id = i.device_id
  LEFT JOIN interface_stats ts ON i.interface_id = ts.interface_id
    AND ts.timestamp > NOW() - INTERVAL '30 days'
  WHERE d.is_active = true
  GROUP BY d.device_id, d.hostname, d.site, i.interface_id, i.interface_name
),
ranked_per_device AS (
  SELECT 
    hostname,
    site,
    interface_id,
    interface_name,
    total_bytes,
    last_active,
    ROW_NUMBER() OVER (PARTITION BY hostname ORDER BY total_bytes DESC) as rank
  FROM device_interface_stats
),
classified AS (
  SELECT 
    hostname,
    site,
    interface_id,
    interface_name,
    total_bytes,
    last_active,
    rank,
    CASE 
      WHEN rank = 1 THEN 'Primary'
      WHEN rank <= 3 THEN 'Secondary'
      ELSE 'Other'
    END as importance
  FROM ranked_per_device
  WHERE rank <= 3 OR total_bytes > 10000000000
)
SELECT 
  hostname,
  site,
  interface_id,
  interface_name,
  total_bytes,
  last_active,
  importance
FROM classified
ORDER BY site, hostname, rank
```

**Key Points**:
- ✅ Multiple JOINs with clear purpose
- ✅ ROW_NUMBER() for per-group ranking
- ✅ PARTITION BY groups the ranking
- ✅ Final WHERE filters on rank
- ✅ Clear classification at end

## ⚠️ Common Mistakes & How to Fix

### Mistake 1: Type Mismatch in Dates
```sql
-- ❌ FAILS - Cannot subtract INTEGER from DATE
WHERE created_at > CURRENT_DATE - 30

-- ✅ WORKS - Use INTERVAL
WHERE created_at > CURRENT_DATE - INTERVAL '30 days'
WHERE timestamp > NOW() - INTERVAL '7 days'
```

### Mistake 2: Wrong GROUP BY
```sql
-- ❌ FAILS - col1 not in GROUP BY
SELECT col1, COUNT(*) FROM table GROUP BY col2

-- ✅ WORKS - All non-aggregated columns in GROUP BY
SELECT col1, col2, COUNT(*) FROM table GROUP BY col1, col2
```

### Mistake 3: Complex Nested CASE (L2 should avoid)
```sql
-- ❌ TOO COMPLEX - Multiple conditions cause binder errors
SELECT 
  CASE 
    WHEN role = 'core' AND site = 'HQ' AND status = 'active' THEN 'Critical'
    WHEN role IN (...) AND site IN (...) THEN 'Important'
    ELSE 'Other'
  END as tier
FROM devices

-- ✅ SIMPLE - This is fine
SELECT 
  CASE 
    WHEN role = 'core' THEN 'Critical'
    ELSE 'Standard'
  END as tier
FROM devices
```

### Mistake 4: Stacking Too Many Operations (L2 trap)
```sql
-- ❌ TOO MANY - filter + group + having + case + order all at once
SELECT role, COUNT(*) as count,
  CASE WHEN COUNT(*) > 5 THEN 'Large' ELSE 'Small' END as size
FROM devices
WHERE is_active = true AND created_at > NOW() - 30  -- ❌ Wrong type!
GROUP BY role
HAVING COUNT(*) > 0
ORDER BY count DESC

-- ✅ USE CTE - Break into clear steps
WITH filtered AS (
  SELECT role FROM devices 
  WHERE is_active = true 
    AND created_at > NOW() - INTERVAL '30 days'
),
grouped AS (
  SELECT role, COUNT(*) as count
  FROM filtered
  GROUP BY role
),
classified AS (
  SELECT role, count,
    CASE WHEN count > 5 THEN 'Large' ELSE 'Small' END as size
  FROM grouped
)
SELECT role, count, size FROM classified ORDER BY count DESC
```

---

## Quick References

### Decision Matrix: When to Use What

| Scenario | Approach | Example |
|----------|----------|---------|
| Single table, WHERE only | Direct SELECT | `SELECT * FROM devices WHERE status = 'active'` |
| Single table, COUNT by group | Simple GROUP BY | `SELECT site, COUNT(*) FROM devices GROUP BY site` |
| Time range query | Use INTERVAL | `WHERE timestamp > NOW() - INTERVAL '10 days'` |
| Two tables, simple join | Simple JOIN | `SELECT d.name, COUNT(i.id) FROM devices d LEFT JOIN interfaces i ...` |
| Multiple conditions, classify | Use CTE (3 steps) | L2 Pattern 3 |
| Window functions, advanced logic | Use CTE (4+ steps) | L3 Patterns 1-3 |

### Type Handling Quick Reference

| Operation | ❌ WRONG | ✅ CORRECT |
|-----------|---------|-----------|
| Date math | `created_at > NOW() - 7` | `created_at > NOW() - INTERVAL '7 days'` |
| Date comparison | `WHERE date > CURRENT_DATE - 1` | `WHERE date > CURRENT_DATE - INTERVAL '1 day'` |
| String from number | `WHERE serial_num = 12345` | `WHERE serial_num = '12345'` |
| Year extraction | `YEAR(created_at)` | `EXTRACT(YEAR FROM created_at)` |
| Case insensitive match | `WHERE name = 'router'` | `WHERE LOWER(name) = 'router'` |

### Common Aggregation Functions

| Function | Use Case | Returns NULL if empty? |
|----------|----------|-------------------------|
| COUNT(*) | Count all rows | No (returns 0) |
| SUM(col) | Total of numeric column | Yes |
| AVG(col) | Average | Yes |
| MAX(col), MIN(col) | Highest/lowest | Yes |
| COUNT(DISTINCT col) | Unique values | No (returns 0) |

---

**Key Takeaway**: 
- **L2 queries**: Usually L2 Patterns 1-3, keep simple
- **L3 queries**: Use CTEs with 3-4 steps, add Window functions if needed
- **All queries**: Always use INTERVAL for date math

