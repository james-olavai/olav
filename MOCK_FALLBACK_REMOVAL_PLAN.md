# 🚨 Mock/Fallback Removal Plan - Session 4

**Date**: 2026-02-13  
**Severity**: 🔴 CRITICAL  
**Status**: READY TO IMPLEMENT

---

## Problems Identified

### 1. **Hardcoded Default Devices** ❌
**Location**: `/home/yhvh/Olav/src/olav/agents/execution_dispatcher.py:143`

```python
if not devices:
    # Default to common devices if no specific device mentioned
    devices = ["R1"]  # ← FALLBACK!
```

**Issue**: When device extraction fails, defaults to ["R1"]

---

### 2. **/devices Command Not Working** ❌
**Location**: `/home/yhvh/Olav/src/olav/cli/commands/builtin.py:116`

```python
result = list_devices.invoke({})  # ← list_devices is not a tool!
```

**Issue**: Tries to call `.invoke()` on a regular function, causing exception

---

### 3. **CLI Status "list devices" crashes** ❌
**Last test output**:
```
❌ Error: Unknown error
```

**Root cause**: `list_devices` function doesn't have `.invoke()` method

---

## Fixes Required

### Fix 1: Remove hardcoded default devices
**File**: `src/olav/agents/execution_dispatcher.py`
**Line**: 143-146
**Change**: Raise error instead of defaulting to ["R1"]

```python
# BEFORE
if not devices:
    devices = ["R1"]
    logger.debug(f"   No devices specified, using default: {devices}")

# AFTER  
if not devices:
    return {
        "status": "error",
        "final_answer": "No devices specified in query. Please specify device name or 'all devices'.",
        "error_message": "No devices specified"
    }
```

### Fix 2: Fix /devices command to use list_devices function directly
**File**: `src/olav/cli/commands/builtin.py`
**Lines**: 96-125  
**Change**: Call the function directly, not .invoke()

```python
#BEFORE
result = list_devices.invoke({})

# AFTER
result = list_devices()
return json.dumps(result, ensure_ascii=False, indent=2)
```

### Fix 3: Remove fallback device returns in devices API
**File**: `src/olav/api/v1/devices.py`
**Lines**: 93, 93, 140, 170, 218, 307
**Change**: Return empty list or raise error, don't silently swallow exceptions

```python
# BEFORE
except Exception as e:
    logger.error(f"Failed to list devices: {e}")
    return []  # ← SILENT SWALLOW!

# AFTER
except Exception as e:
    logger.error(f"Failed to list devices: {e}")
    raise  # ← PROPAGATE ERROR!
```

---

## Items to Search & Remove

- [ ] Remove `devices = ["R1"]` default
- [ ] Fix list_devices command  
- [ ] Remove empty list fallbacks
- [ ] Check for CSV-based device sources
- [ ] Verify no LLM-generated example data
- [ ] Remove execute_sync fallback paths
- [ ] Check error swallowing in try/except blocks

---

## Validation Plan

After fixes:
1. Run `uv run olav query "list devices"` → Should work with 6 devices from DB
2. Run `uv run olav query "list all devices"` → Should list R1-R4, SW1, SW2 only
3. Run `/devices` command → Should show real data or proper error
4. Check database directly → Confirm only 6 devices exist
5. Run E2E tests → All tests pass with real data only

---

## Implementation Priority

**CRITICAL** (Must fix before any other work):
1. Remove hardcoded device defaults
2. Fix /devices command
3. Remove fallback empty lists

**HIGH** (Fix immediately after):
1. Fix error handling to propagate instead of swallow
2. Remove LLM-based example generation

---

## Files to Modify

1. `src/olav/agents/execution_dispatcher.py` - Remove device default
2. `src/olav/cli/commands/builtin.py` - Fix devices command  
3. `src/olav/api/v1/devices.py` - Remove fallback returns
4. Check for other exception handlers with silent returns

---

**Status**: Ready for implementation  
**Estimated Time**: 15-30 minutes  
**Risk**: Low (removing fallbacks, improving error messages)
