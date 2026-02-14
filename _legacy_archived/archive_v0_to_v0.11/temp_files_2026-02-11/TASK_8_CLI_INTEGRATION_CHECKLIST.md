# Task 8: CLI Integration - Implementation Checklist

## 🎯 Quick Start

**Goal**: Integrate Guard router into CLI query command  
**File**: `src/olav/cli/cli_main.py`  
**Location**: Lines 457-510 (query() function)  
**Expected Time**: 1-2 hours  
**Impact**: Production-ready Guard routing via CLI  

---

## 📋 Step-by-Step Checklist

### Step 1: Update Imports
- [ ] At top of cli_main.py, locate: `from olav.agents.orchestrator import orchestrate_query`
- [ ] Add new imports:
```python
from olav.agents.orchestrator_v2 import orchestrate_with_guard, orchestrate_query_with_routing
from config.settings import settings
```
- [ ] Keep existing imports for fallback compatibility

### Step 2: Modify query() Function Signature
- [ ] Find: `def query(query_text: str = typer.Argument(...), debug: bool = ..., verbose: bool = ...):`
- [ ] Add optional Guard control flag:
```python
    guard: bool = typer.Option(
        None,
        "--guard/--no-guard",
        help="Use Guard routing (default: use settings)",
    ),
```
- [ ] Result: query function now accepts `guard` parameter

### Step 3: Replace Orchestrator Call
- [ ] Find: `result = asyncio.run(orchestrate_query(query_text))`
- [ ] Replace with Guard-aware routing:
```python
# Determine if Guard should be used
use_guard = guard if guard is not None else settings.agent.enable_guard_routing

try:
    if use_guard:
        # Use Guard router for optimized routing
        result = orchestrate_with_guard(query_text)
    else:
        # Fallback to sync orchestrator (v0.11.x behavior)
        from olav.agents.orchestrator import orchestrate_query_sync
        result = orchestrate_query_sync(query_text)
except Exception as e:
    console.print(f"[bold red]Error: {str(e)}[/bold red]")
    if debug:
        import traceback
        traceback.print_exc()
    raise typer.Exit(1) from None
```

### Step 4: Update Result Handling
- [ ] Find: Result display section (likely around line 480-500)
- [ ] Update to handle Guard result format (includ route info):
```python
# Display Guard routing info
if result.get("route"):
    route = result["route"]
    confidence = result.get("confidence", 0.0)
    console.print(f"[dim]Route: {route} (confidence: {confidence:.2f})[/dim]")

if result.get("execution_time"):
    latency = result["execution_time"]
    console.print(f"[dim]Latency: {latency:.1f}ms[/dim]")
```
- [ ] Keep existing status handling:
  - "complete" → show final_answer
  - "rejected" → show rejection message
  - "error" → show error_message

### Step 5: Add Error Handling for Guard Errors
- [ ] Wrap Guard call in try/except (done in Step 3)
- [ ] Handle known Guard error cases:
  - Empty query → reject with message
  - Very long query (>10k chars) → reject with message
  - LLM timeout → fallback to orchestrate_query_sync

### Step 6: Test Coverage
- [ ] Run simple query: `uv run olav query "how many devices?"`
  - Expected: <5 seconds
  - Contains: Route: SIMPLE, confidence: 0.90+
  
- [ ] Run complex query: `uv run olav query "which devices have ospf errors?"`
  - Expected: <12 seconds
  - Contains: Route: EXPERT or UNKNOWN
  
- [ ] Run dangerous query: `uv run olav query "delete all devices"`
  - Expected: Instant rejection
  - Contains: Route: REJECT, confidence: 1.0
  
- [ ] Run with --no-guard flag: `uv run olav query "count devices" --no-guard`
  - Expected: Uses old orchestrator, latency ~12s
  - No Guard route info in output

- [ ] Disable Guard globally: `OLAV_AGENT__ENABLE_GUARD_ROUTING=false uv run olav query "list devices"`
  - Expected: No Guard route info, uses sync orchestrator

### Step 7: Validation
- [ ] All 22 unit tests still pass: `uv run pytest tests/unit/test_guard.py -v`
- [ ] E2E tests still pass: `uv run pytest tests/e2e/test_guard_integration.py -v`
- [ ] CLI integration tests pass (if created)
- [ ] No import errors or syntax errors
- [ ] Backward compatibility maintained (old behavior available via --no-guard)

### Step 8: Documentation
- [ ] Update CLI help text: `uv run olav query --help`
  - Should show: `--guard/--no-guard` option
  - Should explain default behavior (uses settings)
  
- [ ] Document in README.md or DEVELOPER_INDEX.md:
  - How to use Guard from CLI
  - Performance expectations
  - How to disable if needed

---

## 🧪 Testing Scenarios

After implementation, verify these scenarios work:

### Scenario 1: Guard Enabled (Default)
```bash
$ uv run olav query "show me device status"
🛡️ Guard analyzing query...
Route: SIMPLE (confidence: 0.92)
Latency: 3.2ms

[Result showing device status...]
```

### Scenario 2: Guard Disabled via Flag
```bash
$ uv run olav query "show me device status" --no-guard
[Old orchestrator behavior, ~12s latency, no route info]
```

### Scenario 3: Guard Disabled via Environment
```bash
$ OLAV_AGENT__ENABLE_GUARD_ROUTING=false uv run olav query "show devices"
[Old orchestrator behavior, ~12s latency]
```

### Scenario 4: Dangerous Query
```bash
$ uv run olav query "delete all devices from database"
❌ Query rejected
Reason: Dangerous operation - DELETE statement detected
Route: REJECT (confidence: 1.0)
```

### Scenario 5: Complex Query
```bash
$ uv run olav query "which devices have ospf errors and haven't been updated in 30 days"
Route: EXPERT (confidence: 0.87)
Latency: 8456.2ms

[Complex query result...]
```

---

## 🔍 Common Issues & Solutions

### Issue: Import Error - "No module named 'orchestrate_with_guard'"
**Solution**: 
- Verify: `src/olav/agents/orchestrator_v2.py` exists
- Check: `from olav.agents.orchestrator_v2 import orchestrate_with_guard`
- Run: `uv run python -c "from olav.agents.orchestrator_v2 import orchestrate_with_guard"`

### Issue: "Guard: settings.agent not found"
**Solution**:
- Verify: `config/settings.py` has agent field with Guard config
- Import: `from config.settings import settings`
- Access: `settings.agent.enable_guard_routing` (not settings.agent_settings)

### Issue: Latency Still ~12s (Guard not working)
**Solution**:
- Check: `enable_guard_routing = True` in settings or .env
- Run: `uv run olav query "count devices" 2>&1 | grep Route`
- If no route printed: Check exception handling
- If Route shows but slow: Verify heuristic matching working (test unit tests)

### Issue: "orchestrate_query_sync not found"
**Solution**:
- Add fallback import: `from olav.agents.orchestrator import orchestrate_query_sync`
- Confirm file exists: `src/olav/agents/orchestrator.py`

---

## 📊 Success Criteria

✅ **CLI Integration is successful when**:

1. **Guard routing activated**
   - [ ] Simple queries show Route: SIMPLE, latency <5s
   - [ ] Complex queries show Route: EXPERT, latency <12s
   - [ ] Dangerous queries show Route: REJECT, instant
   
2. **Feature flag working**
   - [ ] `--guard` flag forces Guard on
   - [ ] `--no-guard` flag forces Guard off
   - [ ] Settings default honored when flag not specified
   
3. **Backward compatibility maintained**
   - [ ] Old behavior available via `--no-guard`
   - [ ] Environment variable `OLAV_AGENT__ENABLE_GUARD_ROUTING` respected
   - [ ] Settings file `.olav/settings.json` respected
   
4. **No breaking changes**
   - [ ] All existing tests pass
   - [ ] CLI still works for all other commands
   - [ ] Error handling doesn't break on edge cases
   
5. **Output looks good**
   - [ ] Route information displayed clearly
   - [ ] Latency information shown
   - [ ] Results unchanged (same data, just faster)

---

## ⏱️ Time Breakdown

| Task | Estimated | Actual |
|------|-----------|--------|
| Update imports | 5 min | ? |
| Modify function signature | 5 min | ? |
| Replace orchestrator call | 10 min | ? |
| Update result handling | 10 min | ? |
| Error handling | 15 min | ? |
| Testing (6 scenarios) | 30 min | ? |
| Documentation | 15 min | ? |
| **Total** | **90 min** | ? |

---

## 🚀 Next After Task 8

Once CLI integration complete:
1. Run performance benchmarks: `uv run python scripts/benchmark_guard.py`
2. Commit code with message: "Task 8: CLI Guard integration complete"
3. Begin Task 9: Feature flag & gradual rollout infrastructure
4. Schedule Phase 2: Multi-agent handler implementation

---

## 📞 Questions?

- **Guard Logic**: See `.olav/skills/guard/SKILL.md` (classification rules)
- **Implementation Details**: See `src/olav/agents/guard.py` (code)
- **Integration Pattern**: See `src/olav/agents/orchestrator_v2.py` (routing logic)
- **CLI Guide**: See `docs/CLI_GUARD_INTEGRATION.md` (full implementation guide)

**Status**: ✅ Ready to implement  
**Next**: See `PHASE_1_GUARD_COMPLETION_REPORT.md` for overall progress
