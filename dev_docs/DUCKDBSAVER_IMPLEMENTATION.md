# DuckDBSaver Implementation Guide
**Version:** 1.0  
**Date:** 2026-03-02  
**Status:** Ready for Implementation

---

## Executive Summary

你说得对——Checkpointer应该使用**DuckDB而不是SQLite**。原始设计在`src/olav/agents/agent.py`第44行已经导入了DuckDBSaver，只是因为async兼容性问题暂时改用了MemorySaver。

我们可以通过在CLI层使用**sync invoke()包装器**来解决async问题，保留DuckDB的持久化优势。

---

## Problem Analysis

### Current State (MemorySaver)
```python
# src/olav/agents/agent.py line 134-146
self.checkpointer = MemorySaver()  # ❌ In-memory, restarts lose state
```

### Why Not SQLite?
- ❌ SQLiteSaver also doesn't implement async in LangGraph
- ❌ SQLite has concurrency problems with multiple users (lock contention)
- ❌ DuckDB is more suitable for network operations context

### The Real Issue: Async Context
```python
# The problem is in run_single_query (src/olav/cli/main.py)
async def run_single_query(query: str, assistant_id: str, ...):
    ...
    result = await agent.ainvoke(input_, ...)  # ← Uses async
    # DuckDBSaver.aget_tuple() not implemented → NotImplementedError
```

**Solution:** DuckDBSaver has sync methods, but ainvoke needs async. We need a sync wrapper.

---

## Solution: Sync Invoke Wrapper

### Architecture Change

```
Before:
  CLI (async): run_single_query()
    ↓
  Agent.ainvoke()  ← Uses async interface
    ↓
  DuckDBSaver  ← get_tuple() only (sync not async)
    ❌ Tries to call aget_tuple() → NotImplementedError

After:
  CLI (async): run_single_query()
    ↓
  Agent.invoke()  ← Sync interface in async context
    ↓
  Agent.ainvoke() internally  ← Runs in thread
    ↓
  DuckDBSaver  ← get_tuple() works fine
    ✅ Sync access only, no aget_tuple needed
```

### Implementation Step 1: Update Agent Init

**File:** `src/olav/agents/agent.py` (lines 134-146)

**Change from:**
```python
try:
    from langgraph.checkpoint.memory import MemorySaver
    
    self.checkpointer = MemorySaver()
    logger.info("✓ Checkpointer initialized (MemorySaver - for async CLI support)")
except Exception as e:
    logger.warning(f"MemorySaver failed ({e}), no checkpoint support available")
```

**Change to:**
```python
try:
    import duckdb
    from langgraph.checkpoint.duckdb import DuckDBSaver
    
    # User-isolated checkpoint directory
    _username = os.environ.get("USER") or os.getlogin()
    checkpoint_dir = Path.home() / ".olav" / "checkpoints" / _username / self.agent_id
    checkpoint_dir.mkdir(parents=True, exist_ok=True)
    
    # Create DuckDB connection for checkpoints
    conn = duckdb.connect(str(checkpoint_dir / "checkpoints.duckdb"), read_only=False)
    self.checkpointer = DuckDBSaver(conn)
    logger.info(f"✓ Checkpointer initialized (DuckDBSaver): {checkpoint_dir}")
except Exception as e:
    logger.warning(f"DuckDBSaver init failed ({e}), checkpoints disabled.")
    self.checkpointer = None
```

### Implementation Step 2: Create Sync Invoke Wrapper

**File:** `src/olav/agents/agent.py` (in OLAVAgent class)

**Add method:**
```python
async def invoke_sync_checkpoint(self, input_: str | dict, thread_id: str | None = None, **kwargs) -> dict:
    """
    Sync invoke wrapper for DuckDBSaver compatibility.
    
    DuckDBSaver only supports sync checkpoint access (get_tuple),
    not async (aget_tuple). This method uses sync invoke() while
    maintaining async CLI context via asyncio.to_thread().
    
    Args:
        input_: User query or structured input
        thread_id: Session/conversation thread ID for state persistence
        **kwargs: Additional arguments to pass to invoke()
        
    Returns:
        Agent graph output
    """
    import asyncio
    
    # Wrap sync invoke in asyncio.to_thread for use in async context
    def _sync_invoke():
        if isinstance(input_, str):
            input_dict = {"messages": [{"role": "user", "content": input_}]}
        else:
            input_dict = input_
        
        config = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}
        
        return self.graph.invoke(input_dict, config=config if config else None, **kwargs)
    
    # Run sync invoke in thread pool (non-blocking in async context)
    return await asyncio.to_thread(_sync_invoke)
```

### Implementation Step 3: Update CLI to Use Wrapper

**File:** `src/olav/cli/main.py` (in run_single_query function, around line 360)

**Change from:**
```python
async def run_single_query(query: str, assistant_id: str, session_id: str | None = None) -> None:
    """Run a single query and exit."""
    from deepagents_cli.execution import execute_task
    from deepagents_cli.input import SessionState
    from deepagents_cli.ui import TokenTracker

    agent, backend = create_olav_agent_with_backend(assistant_id, session_id=session_id)

    session_state = SessionState(auto_approve=True)
    token_tracker = TokenTracker()

    await execute_task(
        query,
        agent,
        assistant_id,
        session_state,
        token_tracker,
        backend=backend,
    )
```

**Change to (if using direct invoke):**
```python
async def run_single_query(query: str, assistant_id: str, session_id: str | None = None) -> None:
    """Run a single query using DuckDBSaver-compatible sync wrapper."""
    from olav.agents.agent import OLAVAgent
    
    agent = OLAVAgent(agent_id=assistant_id, session_id=session_id)
    
    # Use sync wrapper instead of deepagents_cli for checkpoint compatibility
    result = await agent.invoke_sync_checkpoint(query, thread_id=session_id)
    
    # Process and display result
    if isinstance(result, dict):
        if "messages" in result:
            last_msg = result["messages"][-1]
            print(last_msg.get("content", ""))
        else:
            print(result)
    else:
        print(result)
```

**Alternative (if keeping deepagents_cli):**
```python
# Still use deepagents_cli, but make sure it calls agent.invoke_sync_checkpoint
# This would require patching deepagents_cli.execution.execute_task
```

---

## Verification Steps

### Step 1: Verify DuckDB Initialization
```bash
# After code changes, check if checkpoint DB is created
python3 << 'EOF'
import sys
sys.path.insert(0, 'src')
from olav.agents.agent import OLAVAgent

agent = OLAVAgent(agent_id='ops')
print(f"Checkpointer type: {type(agent.checkpointer).__name__}")
print(f"Is DuckDBSaver: {agent.checkpointer.__class__.__name__}")
EOF
```

**Expected output:**
```
Checkpointer type: DuckDBSaver
Is DuckDBSaver: DuckDBSaver
```

### Step 2: Check Checkpoint File
```bash
# Verify checkpoint database exists in user home
ls -lh ~/.olav/checkpoints/$USER/ops/checkpoints.duckdb

# Should show something like:
# -rw-r--r-- 1 user group 65536 Mar  2 10:00 checkpoints.duckdb
```

### Step 3: Test Single Query with State
```bash
# Run first query
olav --agent ops "First query about BGP"

# Check checkpoint was written
duckdb ~/.olav/checkpoints/$USER/ops/checkpoints.duckdb \
  "SELECT * FROM checkpoints LIMIT 1;"

# Run second query with same session_id
olav --agent ops --session SESSION_ABC "First query"
olav --agent ops --session SESSION_ABC "Second query"

# Verify both queries in checkpoint
duckdb ~/.olav/checkpoints/$USER/ops/checkpoints.duckdb \
  "SELECT thread_id, COUNT(*) as message_count FROM checkpoints GROUP BY thread_id;"
```

**Expected output (second command):**
```
┌─────────────────┬─────────────────┐
│   thread_id     │  message_count  │
├─────────────────┼─────────────────┤
│  SESSION_ABC    │        2        │
└─────────────────┴─────────────────┘
```

### Step 4: Test Session Recovery
```bash
# Run query with session
olav --agent ops --session RECOVERY_TEST "Store this in memory"

# Kill process (or let it exit)

# Reconnect to same session
olav --agent ops --session RECOVERY_TEST "What did we store?"

# Agent should be able to reference state from first query
```

### Step 5: Test Multi-User Isolation
```bash
# As user 'alice'
$ olav --agent ops --session ALICE_SESSION "query 1"

# Check checkpoint directory
$ ls ~/.olav/checkpoints/alice/ops/checkpoints.duckdb

# As user 'bob' (different user or sudo)
$ olav --agent ops --session BOB_SESSION "query 2"

# Check bob's checkpoint directory  
$ ls ~/.olav/checkpoints/bob/ops/checkpoints.duckdb

# Verify alice can't see bob's checkpoints
$ duckdb ~/.olav/checkpoints/alice/ops/checkpoints.duckdb \
    "SELECT * FROM checkpoints WHERE thread_id = 'BOB_SESSION';"
# Should return empty (no results)
```

---

## Implementation Checklist

- [ ] Update imports in `src/olav/agents/agent.py` (duckdb, DuckDBSaver)
- [ ] Replace MemorySaver with DuckDBSaver init code
- [ ] Add user-isolated checkpoint directory creation
- [ ] Create `invoke_sync_checkpoint()` async wrapper method
- [ ] Update `src/olav/cli/main.py` to use wrapper (or integrate with deepagents_cli)
- [ ] Add `_username` import/usage from config
- [ ] Test Step 1: Verify DuckDBSaver type
- [ ] Test Step 2: Check checkpoint file exists
- [ ] Test Step 3: Verify multi-turn state in checkpoints
- [ ] Test Step 4: Test session recovery after restart
- [ ] Test Step 5: Test multi-user isolation
- [ ] Update documentation in agent.py docstring
- [ ] Commit changes with message: "feat(checkpointer): Use DuckDBSaver for persistent state"

---

## Why This Works

### Async Compatibility Without Async DB
1. `ainvoke()` needs async interface for LangGraph
2. `DuckDBSaver.get_tuple()` is sync-only (no async version)
3. `asyncio.to_thread()` runs sync code in thread pool, returns awaitable
4. No blocking, no event loop conflicts

### User Isolation
```
~/.olav/checkpoints/
├── alice/
│   └── ops/
│       └── checkpoints.duckdb  (only alice can access)
└── bob/
    └── ops/
        └── checkpoints.duckdb  (only bob can access)
```

### Persistent State
```
DuckDB Engine (persistent)
  ├── checkpoints table: [thread_id, values, ...]
  └── Survives process restart ✅

vs.

MemorySaver (in-memory)
  └── Lost on process exit ❌
```

---

## Comparison: Before vs After

| Aspect | Before (MemorySaver) | After (DuckDBSaver) |
|--------|----------------------|---------------------|
| **Persistence** | ❌ Lost on restart | ✅ Survives restart |
| **Multi-turn** | ❌ No state recovery | ✅ State recovered by thread_id |
| **User isolation** | ❌ All in one memory | ✅ ~/.olav/checkpoints/{user}/ |
| **Async compatibility** | ✅ Works with ainvoke | ✅ Works via asyncio.to_thread |
| **Architecture fit** | ⚠️ Fallback | ✅ Original design |

---

## Related Issues & Links

- Original issue: DuckDBSaver `aget_tuple()` not implemented in LangGraph
- Workaround: Use sync `invoke()` + `asyncio.to_thread()`
- References:
  - `src/olav/agents/agent.py` line 44 (DuckDBSaver import)
  - `src/olav/agents/agent.py` line 21-27 (design docs)
  - LangGraph docs: [Checkpoint Design](https://langchain-ai.github.io/langgraph/concepts/)

---

## Questions?

If `asyncio.to_thread()` approach has issues, alternatives:
1. Create custom async wrapper for DuckDB (more complex)
2. Wait for LangGraph to implement `aget_tuple()` in DuckDBSaver
3. Use separate thread for agent logic (threading approach)

But Option 1 (sync wrapper via asyncio.to_thread) is simplest and matches Python stdlib patterns.

