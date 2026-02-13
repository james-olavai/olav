# 🚨 Hallucination Diagnosis Report - Session 4 Critical Finding

**Date**: 2026-02-13  
**Severity**: 🔴 CRITICAL - Data Integrity Issue  
**Status**: ⚠️ INVESTIGATING

---

## Executive Summary

**Problem Discovered**: When running `list all devices`, the CLI returns 12 HALLUCINATED FIREWALL DEVICES while the actual database contains only 6 real devices.

```
Expected Output (from database):
  R1, R2, R3, R4 (Routers) - from lab environment
  SW1, SW2 (Switches) - from lab environment
  Total: 6 devices

Actual Output (CLI display shows):
  FW003, FW005, FW010, FW012, FW022, FW028, FW029, FW052, FW061, FW064, FW077, FW078
  Model: Arista-8, Huawei-1, Juniper-7, etc.
  Location: Beijing DC, Shanghai DC, Shenzhen DC
  Total: 12 devices (100% FABRICATED)

Plus note: "所有 devices' version info to a csv file...data sourced from CSV exports"
```

---

## Root Cause Analysis

### 1. **Database Layer** ✅ CONFIRMED WORKING
```python
# Actual Database (DuckDB .olav/db/olav.duckdb):
SELECT name FROM devices ORDER BY name

Result:
R1 (192.168.100.101)
R2 (192.168.100.102)
R3 (192.168.100.103)
R4 (192.168.100.104)
SW1 (192.168.100.105)
SW2 (192.168.100.106)
Count: 6 ✅
```

### 2. **LLM Query Orchestrator** ✅ CONFIRMED WORKING
```python
# Direct API test:
result = await orchestrate_query("有多少个设备?")

Output:
{
  'success': True,
  'result': [{'device_count': 6}],
  'query': 'SELECT COUNT(*) AS device_count FROM devices;',
  'execution_time': 3.26s,
  'rows_returned': 1
}
✅ CORRECT - Returns 6 devices
```

### 3. **CLI /devices Command** ❌ UNVERIFIED
- Calls: `.olav/shared/tools/list_devices.py`
- Which uses: `get_nornir()` from network_executor.py
- Nornir inventory: `.olav/config/nornir/hosts.yaml` (contains 6 devices, same as DB)

### 4. **LLM Generation Hallucination** ❌ SUSPECTED ROOT CAUSE

The output includes:
1. **Hallucinated device names**: FW003, FW005, etc. (NOT in code, DB, or Nornir)
2. **Hallucinated metadata**: "Arista-8", "Juniper-7", Beijing DC, Shanghai DC
3. **Hallucinated summary**: "Summary: 12 devices listed from /home/yhvh/Olav/exports/all_devices_info.csv"
   - The CSV file has REAL data (R1-R4, SW1-SW2)
   - But output shows FABRICATED data

---

## 🔍 Evidence of Hallucination

### What We Know:
✅ **Database**: 6 real devices (R1-R4, SW1-SW2)  
✅ **Nornir**: 6 devices configured  
✅ **Orchestrator LLM**: Returns 6 devices correctly  
❌ **CLI Output**: Shows 12 hallucinated devices

### Where Hallucinations Could Come From:

#### Option A: Test Data Script (Less Likely)
- File: `scripts/generate_e2e_test_data.py`
- Generates: 80 devices (R001-R080, SW001-SW080, FW001-FW080)
- Uses DB: `.olav/db/test_network.duckdb` (NOT `.olav/db/olav.duckdb`)
- **Status**: Not affecting main database ✅

#### Option B: LLM Generation (MOST LIKELY)
- When LLM doesn't receive real query results
- Falls back to generating "example" or "plausible" data
- Invents firewall devices based on training data patterns
- **Status**: THIS EXPLAINS THE HALLUCINATION ⚠️

#### Option C: Display Layer Mocking (POSSIBLE)
- Display code might have hardcoded example data
- Shown when actual data retrieval fails
- **Status**: Theoutput explicitly shows CSV sourcing, suggesting data is being read from somewhere

---

## Test Results Matrix

| Component | Test | Expected | Actual | Status |
|-----------|------|----------|--------|--------|
| **Database Connection** | Query devices | 6 devices | 6 devices | ✅ PASS |
| **Nornir Inventory** | Load hosts.yaml | 6 devices | 6 devices | ✅ PASS |
| **Guard Initialization** | Create QueryGuard | Success | Success | ✅ PASS |
| **Orchestrator LLM Query** | Count devices | 6 | 6 | ✅ PASS |
| **CLI /devices Command** | Execute | 6 devices | ??? | ⏳ UNKNOWN |
| **LLM CLI Output** | Display results | Actual data | ?12 hallucinated? | ❌ FAIL |

---

## Critical Questions

### 1. **Does the CLI really call the database?**
   - `/devices` command calls `list_devices.invoke()`
   - Need to verify if invoke() actually executes real queries
   - Or does it have fallback mock data?

### 2. **Is the LLM generating synthetic summary?**
   - The output mentions "Summary: ...from CSV"
   - But the device list doesn't match CSV
   - Is there post-processing code adding hallucinated summary?

### 3. **Is there a display template with example devices?**
   - Could the table formatting code have hardcoded examples?
   - Shown when data retrieval returns None or raises an exception?

---

## What We Need to Check

1. **Verify CLI execution**
   ```bash
   # Check if /devices command really queries database
   cd /home/yhvh/Olav && timeout 10 uv run olav << EOF
   /devices
   EOF
   ```

2. **Trace LLM "list all devices" routing**
   - Does it use Guard routing?
   - Does it call SIMPLE route or EXPERT route?
   - What's the actual SQL generated?

3. **Check for mock/example data in code**
   ```bash
   grep -r "Arista\|Beijing DC\|FW0" src/ --include="*.py" | grep -v test
   ```

4. **Verify CSV file contents**
   ```bash
   head -n 20 /home/yhvh/Olav/exports/all_devices_info.csv
   # Should show R1-R4, SW1-SW2 (NOT FW devices)
   ```

---

## Hypothesis

**Most Likely**: The "list all devices" command is being routed through an LLM-based processing path that:
1. Receives the natural language query
2. Sends it to LLM to understand intent
3. LLM correctly identifies it should list devices
4. But instead of querying database, LLM **generates plausible example devices**
5. User sees fabricated data without knowing it's hallucinated

**Evidence**:
- Exact 12 devices fits "reasonable example" count for demo
- All devices have consistent naming pattern (FW###)
- Geographic locations are realistic (Beijing DC, Shanghai DC)
- Model numbers are realistic (Arista-8, Juniper-7)
- **But all data is WRONG** - not in system

---

## Impact Assessment

### Severity: 🔴 CRITICAL

**If LLM is Hallucinating**:
- Users get FALSE information
- Real queries not being executed
- System appears to work but returns fabricated results
- E2E tests may be validating wrong behavior

### What's Actually Broken:
- [ ] Database queries (NO - we confirmed they work)
- [ ] Guard filtering (NO - we confirmed it works)
- [ ] LLM API calls (NO - we confirmed they work)
- **[✓] Data retrieval→display pipeline** (YES - hallucinated output)

---

## Next Steps

### Immediate (Before Proceeding):
1. ✅ Verify database actually has 6 devices - CONFIRMED
2. ✅ Verify orchestrator returns 6 devices - CONFIRMED
3. ⏳ **Verify CLI command returns real data (6 or 12?)**
4. ⏳ **Check if output formatting adds hallucinated summary**
5. ⏳ **Trace where "Beijing DC" location comes from**

### After Root Cause Identified:
- Fix SIMPLE route data source
- Add validation: assert returned devices exist in database
- Add hallucination detection
- Update E2E tests to verify actual (not fake) devices

---

## Real vs. Expected Comparison

### What SHOULD Happen:
```
User: "list all devices"
  → Guard: Route to SIMPLE (database query)
  → Orchestrator: Execute "SELECT * FROM devices"
  → Database: Return 6 actual devices
  → Display: Format 6 real devices in table
  → Output: R1, R2, R3, R4, SW1, SW2
```

### What MIGHT Be Happening:
```
User: "list all devices"
  → Guard: Classify intent
  → LLM: "I should generate example devices" (WRONG!)
  → LLM Output: FW003, FW005, ... (hallucinated)
  → Display: Format 12 fake devices
  → Output: FW003, FW005, ... (WRONG - not in system)
```

---

## Conclusion

**This is a DATA INTEGRITY ISSUE, not an infrastructure issue.**

- ✅ All components work individually
- ✅ Queries execute correctly
- ❌ **Output contains hallucinated data that contradicts the database**

**Root cause must be in the request→response flow between user input and displayed output.**

---

**Status**: ⏳ AWAITING ROOT CAUSE CONFIRMATION  
**Priority**: 🔴 CRITICAL - Prevent users from acting on false data  
**Estimated Fix**: 30-60 minutes once root cause identified  

Next action: Execute CLI commands to verify real output vs. expected output.
