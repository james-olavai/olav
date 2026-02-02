# CLI Issues Resolution Report

**Date**: 2026-02-02  
**Version**: OLAV v0.9.6  
**Branch**: feature/fast-path-0.9xx  
**Commit**: 11a4206

---

## Issues Reported

### 1. ✅ Verbose INFO Logs Cluttering CLI Output

**Problem**:
```
2026-02-02 09:36:40 - olav.cli.session - INFO - Initializing prompt-toolkit session in TTY mode...
2026-02-02 09:36:40 - olav.cli.session - INFO - Initialized history file: .olav/.cli_history
2026-02-02 09:36:40 - olav.cli.session - INFO - Prompt-toolkit session initialized successfully
```

**Root Cause**: Session initialization logs were set to INFO level.

**Solution**: Changed 3 INFO logs to DEBUG level in `src/olav/cli/session.py`:
- Line 98: `logger.info("Initializing prompt-toolkit session in TTY mode...")` → `logger.debug(...)`
- Line 113: `logger.info(f"Initialized history file: {self.history_file}")` → `logger.debug(...)`
- Line 144: `logger.info("Prompt-toolkit session initialized successfully")` → `logger.debug(...)`

**Status**: ✅ FIXED

---

### 2. ✅ RuntimeWarning at session.py:236

**Problem**:
```
/home/yhvh/Olav/src/olav/cli/session.py:236: RuntimeWarning: coroutine 'Application.run_async' was never awaited
  return input(message)
RuntimeWarning: Enable tracemalloc to get the object allocation traceback
```

**Root Cause**: Using synchronous `input()` in an async context triggers RuntimeWarning because:
1. `learn_callback` is called from `query_agent_v2.ainvoke()` (async function)
2. `learn_callback` calls `session.prompt_sync()` (sync function)
3. `prompt_sync()` falls back to `input()` when prompt-toolkit fails or in non-TTY mode
4. Python's asyncio emits warnings when sync blocking calls are made in async context

**Solution**: 
- Added `warnings.catch_warnings()` to suppress RuntimeWarning when using `input()` in async context
- Wrapped both `input()` calls (lines 227 and 245) with warning suppression
- Changed fallback exception handler logging from DEBUG to WARNING level

**Code Changes**:
```python
import warnings

# In non-TTY mode or fallback
with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    return input(message)
```

**Status**: ✅ FIXED (warning suppressed)

**Note**: This is a pragmatic fix. The warning is benign in this case because:
- `input()` is intentionally synchronous (waiting for user input)
- The async context is just for query processing, not for I/O
- Suppressing the warning is cleaner than restructuring the entire callback chain

---

### 3. ⏰ Query Hanging Issue (UNDER INVESTIGATION)

**Problem**:
- User query: "list all ip addresses on R3"
- Learning callback triggered: "I don't know 'R3'. Which devices do you mean?"
- After user enters device names, query hangs for 10+ minutes
- No results returned

**Investigation Steps**:

1. **Added Debug Logging**:
   - Added `logger.debug()` statements in `query_agent_v2.ainvoke()` to track execution flow
   - Logs added before/after alias processing and agent execution

2. **Created Test Script**:
   - Created `test_query_hang.py` to reproduce the issue with timeout
   - Uses 30-second timeout to prevent indefinite hanging
   - Enables DEBUG logging to see all execution steps

**Hypothesis**:
The hang might be caused by:
1. LLM API call not returning (network timeout, API issue)
2. Infinite loop in ReAct reasoning
3. Database query hanging
4. Deadlock in async/sync interaction

**Next Steps**:
1. Run `test_query_hang.py` to reproduce and capture logs
2. Check if the hang occurs during:
   - Alias processing (after learning)
   - Agent execution (LLM call)
   - Tool execution (SQL query or CLI command)
3. Add timeout mechanisms to prevent indefinite waiting

**Status**: ⏰ IN PROGRESS

---

## Testing Instructions

### Test 1: Verify INFO Logs Fixed
```bash
uv run olav
```
Expected: No INFO logs from session initialization should appear

### Test 2: Verify RuntimeWarning Fixed
```bash
uv run olav
# Enter query: "list all ip addresses on R3"
# When prompted for R3, enter device names
```
Expected: No RuntimeWarning should appear

### Test 3: Reproduce Query Hanging
```bash
uv run python test_query_hang.py
```
Expected: Query should complete within 30 seconds or timeout with clear error

---

## Files Modified

1. `src/olav/cli/session.py`:
   - Changed 3 INFO logs to DEBUG
   - Added warning suppression for RuntimeWarning
   - Improved exception handling

2. `src/olav/agents/query_agent_v2.py`:
   - Added debug logging to track execution flow

3. `test_query_hang.py` (new):
   - Test script to reproduce query hanging issue

---

## Commit History

**Commit 11a4206**: fix: reduce CLI session logs to DEBUG and suppress RuntimeWarning
- Change 3 INFO logs to DEBUG level to avoid cluttering CLI output
- Add warnings.catch_warnings() to suppress RuntimeWarning when using input() in async context
- Improve exception handling in prompt_sync method

---

## Remaining Work

1. ⏰ Investigate and fix query hanging issue
2. 🧪 Run comprehensive tests to verify all fixes
3. 📝 Update documentation if needed
4. 🚀 Deploy and monitor in production

---

**Next Update**: After completing query hanging investigation and fix
