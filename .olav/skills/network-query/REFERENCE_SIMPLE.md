# Network Query - Reference for Complex Queries

**Focus: 90% of this guide is for COMPLEX queries. For simple queries, just see one example below.**

---

## 📖 Table of Contents
- [One Simple Query Example](#simple-example-just-read-this-once)
- [⚠️ CRITICAL: Type Handling Rules](#critical-type-handling-rules)
- [Complex Query Patterns](#complex-query-patterns)
- [CTE Approaches](#cte-best-practices)

---

## Simple Example (Just Read This Once)

**Simple Query = Filtering only**

```python
User: "List all core devices in HQ"
```

```sql
SELECT hostname, device_role, site
FROM devices
WHERE device_role = 'core' AND site = 'HQ'
ORDER BY hostname
```

**Pattern**: WHERE + ORDER BY = Done. That's it.

For anything more complex, skip to the next section.

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

## 🎯 COMPLEX QUERY PATTERNS

Use these patterns for multi-step, multi-operation queries.

### Pattern 1: Filter + Group + Simple Classification (2-3 operations)

```sql
-- Goal: Group devices by site, count by role, show tier
WITH grouped_data AS (
  SELECT 
    site,
    device_role,
    COUNT(*) as device_count
  FROM devices
  WHERE is_active = true
    AND created_at > NOW() - INTERVAL '30 days'  -- ✅ INTERVAL!
  GROUP BY site, device_role
)
SELECT 
  site,
  device_role,
  device_count,
  CASE 
    WHEN device_count > 10 THEN 'Large'
    WHEN device_count > 5 THEN 'Medium'
    ELSE 'Small'
  END as size
FROM grouped_data
ORDER BY site, device_count DESC
```

**Key Ideas**:
- ✅ CTE for clarity (Step 1: Filter+Group)
- ✅ Step 2: Add simple CASE
- ✅ INTERVAL for date math
- ✅ All columns in GROUP BY

### Pattern 2: Multi-Table JOIN + Counting + Classification

```sql
-- Goal: Find border devices with OSPF neighbors, classify by neighbor count
WITH ospf_data AS (
  SELECT device, output, created_at
  FROM parsed_outputs
  WHERE command = 'show ip ospf neighbor'
    AND created_at > NOW() - INTERVAL '7 days'  -- ✅ INTERVAL!
),
latest_ospf AS (
  SELECT device, output,
         ROW_NUMBER() OVER (PARTITION BY device ORDER BY created_at DESC) as rn
  FROM ospf_data
),
border_with_ospf AS (
  SELECT d.hostname, d.site, COUNT(lo.device) as has_ospf
  FROM devices d
  LEFT JOIN latest_ospf lo ON d.hostname = lo.device AND lo.rn = 1
  WHERE d.device_role = 'border' AND d.is_active = true
  GROUP BY d.hostname, d.site
),
classified AS (
  SELECT 
    hostname,
    site,
    CASE 
      WHEN has_ospf > 0 THEN 'OSPF-Enabled'
      ELSE 'No-OSPF'
    END as ospf_status
  FROM border_with_ospf
)
SELECT hostname, site, ospf_status
FROM classified
ORDER BY site, hostname
```

**Key Ideas**:
- ✅ Multiple CTEs for each logical step
- ✅ ROW_NUMBER() for "latest" selection
- ✅ LEFT JOIN for "optional data"
- ✅ Simple CASE at the end (not inside GROUP BY)

### Pattern 3: Filtering + Complex Aggregation + Export

```sql
-- Goal: Get active devices, count recent commands, classify
WITH base_data AS (
  SELECT 
    d.hostname,
    d.site,
    d.device_role,
    r.command,
    r.created_at
  FROM devices d
  LEFT JOIN parsed_outputs p ON d.hostname = p.device_name
    AND r.created_at > NOW() - INTERVAL '30 days'  -- ✅ INTERVAL!
  WHERE d.is_active = true
    AND d.device_role != 'access'
),
aggregated AS (
  SELECT 
    hostname,
    site,
    device_role,
    COUNT(DISTINCT command) as unique_commands
  FROM base_data
  WHERE command IS NOT NULL
  GROUP BY hostname, site, device_role
),
result AS (
  SELECT 
    hostname,
    site,
    device_role,
    unique_commands,
    CASE 
      WHEN unique_commands > 15 THEN 'HighActivity'
      WHEN unique_commands > 5 THEN 'MediumActivity'
      ELSE 'LowActivity'
    END as activity_level
  FROM aggregated
)
SELECT hostname, site, device_role, unique_commands, activity_level
FROM result
ORDER BY activity_level DESC, unique_commands DESC
```

**Key Ideas**:
- ✅ CTE Step 1: Base data (joins + filters)
- ✅ CTE Step 2: Aggregation (GROUP BY only the needed columns)
- ✅ CTE Step 3: Classification (simple CASE)
- ✅ CTE Step 4: Final SELECT (ordering)

---

## Advanced CTE Patterns (WITH Clause)

### When to Use CTE

| Scenario | Use CTE? | Why |
|----------|----------|-----|
| Simple WHERE only | ❌ No | Direct SELECT is clearer |
| 2 operations (WHERE + GROUP BY) | ⚠️ Optional | Clearer with CTE, works either way |
| 3+ operations | ✅ Yes | REQUIRED - prevents errors |
| Complex logic stacking | ✅ Yes | Breaks into clear steps |

### CTE Structure for Complex Queries

```sql
-- Template for 4-step complex query
WITH 
-- Step 1: Get base data (filter, join)
base_data AS (
  SELECT ... FROM ... WHERE ... AND created_at > NOW() - INTERVAL '30 days'
),

-- Step 2: Count/aggregate
aggregated AS (
  SELECT col1, col2, COUNT(*) as count
  FROM base_data
  GROUP BY col1, col2
),

-- Step 3: Classify (simple CASE)
classified AS (
  SELECT col1, col2, count,
    CASE 
      WHEN count > 10 THEN 'Large'
      ELSE 'Small'
    END as category
  FROM aggregated
)

-- Step 4: Final result
SELECT col1, col2, count, category
FROM classified
ORDER BY col2, count DESC
```

**Important Rules**:
- ✅ Filter (`WHERE`) in Step 1
- ✅ Aggregate (`GROUP BY`) in Step 2 - ALL non-aggregated columns must be in GROUP BY
- ✅ Classify (`CASE`) in Step 3 - keep CASE simple (2-3 conditions max)
- ✅ Sort (`ORDER BY`) in Step 4

---

## ⚠️ Common Mistakes & How to Fix

### Mistake 1: Type Mismatch in Dates
```sql
-- ❌ FAILS
WHERE created_at > CURRENT_DATE - 30

-- ✅ WORKS
WHERE created_at > CURRENT_DATE - INTERVAL '30 days'
```

### Mistake 2: Complex Nested CASE
```sql
-- ❌ TOO COMPLEX - causes Binder error
SELECT role,
  CASE 
    WHEN role = 'core' AND site = 'HQ' AND is_active = true THEN 'Critical'
    WHEN role IN (...) AND site IN (...) THEN 'Important'
    ELSE 'Other'
  END
FROM devices

-- ✅ SIMPLE - use CTE
WITH classified AS (
  SELECT role, 
    CASE WHEN role = 'core' THEN 'Critical'
         ELSE 'Standard'
    END as tier
  FROM devices
)
SELECT role, tier FROM classified
```

### Mistake 3: Wrong GROUP BY
```sql
-- ❌ FAILS - col1 not in GROUP BY
SELECT col1, COUNT(*) FROM table GROUP BY col2

-- ✅ WORKS - all columns in GROUP BY
SELECT col1, col2, COUNT(*) FROM table GROUP BY col1, col2
```

### Mistake 4: Stacking Too Many Operations
```sql
-- ❌ TOO MANY - filter + group + having + case + order all at once
SELECT role, COUNT(*) as count,
  CASE WHEN COUNT(*) > 5 THEN 'Large' ELSE 'Small' END as size
FROM devices
WHERE is_active = true AND created_at > NOW() - 30  -- Wrong type!
GROUP BY role
HAVING COUNT(*) > 0
ORDER BY count DESC

-- ✅ USE CTE - break into steps
WITH filtered AS (
  SELECT role FROM devices 
  WHERE is_active = true 
    AND created_at > NOW() - INTERVAL '30 days'  -- ✅ Correct!
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

## Quick Complexity Reference

**Use this to decide approach:**

```
Query Type                      Success Rate    Approach
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. WHERE only                    ✅ 100%         Direct SELECT
2. WHERE + GROUP BY              ✅ 85-95%       Direct or simple CTE
3. WHERE + GROUP + HAVING        ⚠️  70-80%      Use CTE
4. JOIN + GROUP + CASE           ⚠️  60-75%      Use multi-step CTE
5. Multiple operations (4+)      ❌ 30-50%       MUST use CTE (break into steps)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Rule: If complexity > 2, use CTE. If > 3, MUST use CTE.
```

---

## Type Handling Quick Reference

| Operation | ❌ WRONG | ✅ CORRECT |
|-----------|---------|-----------|
| Date math | `date - 30` | `date - INTERVAL '30 days'` |
| Date comparison | `created_at > NOW() - 7` | `created_at > NOW() - INTERVAL '7 days'` |
| String from number | `WHERE id = 123` | `WHERE id = '123'` |
| Year extraction | `YEAR(col)` | `EXTRACT(YEAR FROM col)` |
| Case insensitive | `WHERE col = 'cisco'` | `WHERE LOWER(col) = 'cisco'` |

---

## Index: Pattern Selection by User Query Type

| User Says | Pattern to Use | Key File |
|-----------|----------------|----------|
| "List all X devices" | Simple (WHERE only) | ⬆️ See top |
| "Count X by Y" | Pattern 1 | Multi-step CTE |
| "Devices with X neighbors" | Pattern 2 | Multi-table JOIN |
| "Group + count + classify" | Pattern 3 | 4-step CTE |
| "Recent data with classification" | CTE + ROW_NUMBER | Latest value selection |

---

**Key Takeaway**: Almost every complex query uses the same 4-step CTE pattern:
1. Filter + Join
2. Aggregate  
3. Classify (simple CASE)
4. Select result

Apply this pattern and 95%+ of queries will work.

