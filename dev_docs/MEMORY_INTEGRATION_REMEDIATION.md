# Memory Integration - Remediation Plan
**Created:** 2026-03-02  
**Status:** Ready for Implementation

---

## Quick Summary

检查发现**三个核心组件（LLM Cache、Checkpointer、LanceDB）都已实现，但多用户隔离存在严重缺陷**：

✅ **已实现**: LLM Cache、Checkpointer、LanceDB均在OLAVAgent初始化  
❌ **严重问题**: 所有缓存和存储都在**项目级别**，多用户共享（隐私 + 并发问题）  
⚠️ **设计限制**: Checkpointer使用内存级MemorySaver，重启后丢失会话

---

## P1 Priority: Fix CACHE_DIR (Critical Bug)

### Problem
```python
# 当前（错误）
CACHE_DIR = AGENT_DIR / "cache"  # = .olav/cache/
cache_path = CACHE_DIR / "llm_cache.db"  # = .olav/cache/llm_cache.db
# ❌ 所有用户共享同一个SQLite文件
```

### Solution

**File:** `src/olav/core/config.py` (around line 523)

```python
# Add after line 521:
# User-local cache directory for LLM queries (multi-user isolation)
USER_CACHE_DIR = Path.home() / ".olav" / "cache" / _username
```

**File:** `src/olav/agents/agent.py` (around line 122-127)

```python
# Before:
from olav.core.config import CACHE_DIR
cache_path = CACHE_DIR / "llm_cache.db"

# After:
from olav.core.config import USER_CACHE_DIR
cache_path = USER_CACHE_DIR / "llm_cache.db"
```

### Verification
```bash
# After fix, each user should have isolated cache:
ls ~/.olav/cache/alice/llm_cache.db    # ✓ Alice's cache only
ls ~/.olav/cache/bob/llm_cache.db      # ✓ Bob's cache only
# (NOT.olav/cache/llm_cache.db which is shared)
```

### Impact
- ✅ Fixes concurrent write conflicts
- ✅ Prevents privacy breach (users can't see each other's LLM queries)
- ✅ Allows SQLiteCache to work correctly in multi-user scenarios

---

## P2 Priority: Add User Scope to LanceDB

### Problem
```python
# Current: All users see all stored knowledge
search_knowledge("BGP troubleshooting", scope="global")
# Returns knowledge from ALL users, ALL agents
```

### Solution

**File:** `.olav/workspace/ops/tools/search_knowledge_lancedb.py` (line 30-40)

```python
# Add automatic user scoping:
@tool
def search_knowledge(
    query: str,
    limit: int = 5,
    category: str | None = None,
    scope: str | None = None,  # Keep for backward compatibility
) -> str:
    """Search knowledge base..."""
    import os
    
    # If scope not specified, use current user
    if scope is None:
        scope = os.environ.get("USER") or "default"
    
    # Or use agent-specific scope
    # scope = f"{agent_id}:{os.environ.get('USER')}"
    
    store = get_store()
    return hybrid_search(query, store, scope=scope, limit=limit, category=category)
```

### Verification
```bash
# Each agent's searches are now scoped
# User A: scope = "alice" → only alice's knowledge
# User B: scope = "bob" → only bob's knowledge
```

---

## P3 Priority: Make Checkpointer Persistent

### Problem
```python
# Current: MemorySaver (from langgraph.checkpoint.memory)
self.checkpointer = MemorySaver()
# ❌ All state lost on restart
# ❌ No session recovery possible
```

### Root Cause
- Original plan: DuckDBSaver (imported at line 44, persistent)
- Blocked by: LangGraph DuckDBSaver raises NotImplementedError in async contexts (aget_tuple not implemented)
- Current CLI is async (run_single_query uses asyncio.run with agent.ainvoke)
- Fallback: MemorySaver (non-persistent, in-memory only)

**Note on SQLite:** SQLiteSaver also has async issues + concurrency problems with SQLiteCache. Better to stick with DuckDB.

### Solution Options

**Option A (RECOMMENDED):** Fix DuckDBSaver async issue in CLI layer
```python
# src/olav/cli/main.py (run_single_query function)
# Instead of:
await execute_task(..., sync_invoke=False)  # Uses ainvoke

# Use sync wrapper for checkpointer access:
result = agent.invoke(query, thread_id=session_id)  # Sync invoke, avoids async DB issues
```

Architecture:
- Keep DuckDBSaver for persistence (as originally planned)
- Use sync invoke() wrapper in CLI that handles asyncio internally
- DuckDBSaver.get_tuple() is sync-safe, only aget_tuple() fails in async

```python
# src/olav/agents/agent.py
from langgraph.checkpoint.duckdb import DuckDBSaver

checkpoint_dir = Path.home() / ".olav" / "checkpoints" / _username / self.agent_id
checkpoint_dir.mkdir(parents=True, exist_ok=True)
conn = duckdb.connect(str(checkpoint_dir / "checkpoints.duckdb"), read_only=False)
self.checkpointer = DuckDBSaver(conn)
```

**Option B (DEFERRED):** Wait for LangGraph async DuckDBSaver fix
```python
# Monitor LangGraph GitHub for:
# - async aget_tuple() implementation in DuckDBSaver
# - Or alternative: use DuckDB with async wrapper
# Current issue: https://github.com/langchain-ai/langgraph/issues
```

**Option C (NOT RECOMMENDED):** Use SqliteSaver
- ❌ SQLite has concurrency issues (multiple users)
- ❌ SQLite also doesn't properly implement async in LangGraph
- ❌ Could have same NotImplementedError as DuckDBSaver

### Recommendation
- **Immediate:** Implement **Option A** (Fix async in CLI layer, keep DuckDB)
- **Rationale:** 
  - Avoids SQLite concurrency problems
  - Stays with original architecture (DuckDB)
  - Only requires CLI change, not agent-level change
  - Simpler than custom async wrapper

### Verification
```bash
# After fix:
ls ~/.olav/checkpoints/$USER/ops/checkpoints.duckdb
# Each user has isolated DuckDB checkpoints
# Restarts preserve session state
# Async compatibility works via sync CLI wrapper
```

---

## P4 Priority: Verify Thread_ID Chain

### Problem
- UI suggests multi-turn support via session_id (--session parameter)
- ainvoke() supports thread_id parameter
- **Unknown:** deepagents_cli.execute_task() actually uses its or not

### Investigation Steps

1. Add logging to track thread_id propagation:

```python
# src/olav/agents/agent.py (in ainvoke method)

async def ainvoke(self, input_: str | dict, thread_id: str | None = None, **kwargs) -> dict:
    if isinstance(input_, str):
        input_ = {"messages": [{"role": "user", "content": input_}]}
    
    config = {}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}
        logger.debug(f"[THREAD_ID LOG] Using thread_id={thread_id}")  # ← Add this
    
    result = await self.graph.ainvoke(input_, config=config if config else None, **kwargs)
    return result
```

2. Run E2E test with logging:

```bash
export OLAVDEBUG=1
olav --agent ops --session SESSION_ABC "First query"
olav --agent ops --session SESSION_ABC "Second query"
# Check if both queries appear in same thread in checkpoints
```

3. Validate in checkpoints:

```bash
# After test, verify both queries are in same thread
duckdb ~/.olav/checkpoints/yhvh/ops/checkpoints.db \
  "SELECT * FROM checkpoints WHERE thread_id = 'SESSION_ABC'"
# Should show 2+ entries for both queries
```

### Expected Output
- ✅ If working: Both queries appear under same thread_id in checkpoints
- ❌ If broken: Each query gets different thread_id, session state not preserved

---

## Implementation Checklist

### Phase 1: Fix Critical Bug (CACHE_DIR)
- [ ] Update `src/olav/core/config.py` (add USER_CACHE_DIR)
- [ ] Update `src/olav/agents/agent.py` (use USER_CACHE_DIR instead of CACHE_DIR)
- [ ] Run `uv run pytest tests/unit/test_llm_cache.py -v`
- [ ] Test manually: `olav --agent ops "test query"` and verify cache in `~/.olav/cache/{user}/`

### Phase 2: Use DuckDBSaver (NOT SQLite!)
- [ ] Update `src/olav/agents/agent.py` (import DuckDBSaver, create persistent checkpointer)
- [ ] Add user isolation: `~/.olav/checkpoints/{user}/{agent_id}/checkpoints.duckdb`
- [ ] Update `src/olav/cli/main.py` (use sync invoke() to avoid async aget_tuple issue)
- [ ] Test: Run two queries in same session, verify both in checkpoints after restart

### Phase 3: Add LanceDB User Scope  
- [ ] Update `.olav/workspace/*/tools/search_knowledge_lancedb.py` (add user scoping)
- [ ] Update LanceDB query in each agent to use user-scoped queries
- [ ] Create test: verify User A's search doesn't return User B's knowledge

### Phase 4: Verify Thread_ID Chain
- [ ] Add debug logging to graph.ainvoke()
- [ ] Create E2E test that verifies multi-turn state preservation
- [ ] Document findings in dev_docs/

---

## Testing Strategy

### Unit Tests
```bash
# Test user cache isolation
uv run pytest tests/unit/test_llm_cache_isolation.py

# Test LanceDB scope isolation  
uv run pytest tests/unit/test_lancedb_scope_isolation.py
```

### E2E Tests
```bash
# Test multi-turn session persistence
uv run pytest tests/e2e/test_session_recovery.py

# Test multi-user concurrent access
uv run pytest tests/e2e/test_multiuser_isolation.py
```

### Manual Verification
```bash
# 1. Check config
uv run python3 -c "from olav.core.config import USER_CACHE_DIR; print(USER_CACHE_DIR)"

# 2. Run query and check cache
olav --agent ops "test query"
ls ~/.olav/cache/$USER/llm_cache.db

# 3. Check LanceDB
duckdb .olav/databases/memory.lancedb "SELECT * FROM memory LIMIT 1"

# 4. Check checkpoints
sqlite3 ~/.olav/checkpoints/$USER/ops/checkpoints.db ".tables"
```

---

## Configuration After Fix

```
Home Directory (~)
├── .olav/
│   ├── cache/
│   │   ├── alice/
│   │   │   └── llm_cache.db          ✅ User-isolated
│   │   └── bob/
│   │       └── llm_cache.db          ✅ User-isolated
│   ├── checkpoints/
│   │   ├── alice/
│   │   │   └── ops/
│   │   │       └── checkpoints.duckdb  ✅ User + agent isolated (DuckDB)
│   │   └── bob/
│   │       └── ops/
│   │           └── checkpoints.duckdb  ✅ User + agent isolated (DuckDB)
│   ├── history/
│   │   └── alice.log                 ✅ Already per-user
│   ├── sessions/
│   │   └── SESSION_ID/               ✅ Already per-user
│   └── logs/
│       └── users/
│           ├── alice.log             ✅ Already per-user
│           └── bob.log               ✅ Already per-user

Project Directory (.olav)
├── cache/                            ❌ REMOVE (move to ~/.olav/cache)
├── databases/
│   ├── main.duckdb                   ✅ Project-level (read-only to agents)
│   └── memory.lancedb                ⚠️ Add user scope in queries
└── workspace/
    └── ops/
        └── tools/
            └── search_knowledge_lancedb.py  ⚠️ Add user scoping
```

---

## Risk Assessment

### Risk: Breaking Changes
- **Impact:** Code that expects CACHE_DIR to be `.olav/cache` will break
- **Mitigation:** Check all uses of CACHE_DIR in codebase
- **Search:** `grep -r "CACHE_DIR" src/ --include="*.py"`

### Risk: Performance
- **Impact:** Multiple SQLite files might be slower than one shared file
- **Mitigation:** Each user only accesses their own cache (no contention)
- **Expected:** Better performance due to reduced lock contention

### Risk: Storage
- **Impact:** Multiple cache files (one per user)
- **Mitigation:** Cache files are typically small (<10MB per user)
- **Acceptable:** Storage cost is minimal

---

## Success Criteria

When all fixes are implemented:

✅ **CACHE_DIR Fixed**
- [ ] No .olav/cache/llm_cache.db (project-level) in use
- [ ] Each user has ~/.olav/cache/{user}/llm_cache.db
- [ ] Multiple users can query concurrently without conflicts

✅ **LanceDB Scoped**
- [ ] search_knowledge() uses user scope by default
- [ ] User A cannot see User B's stored knowledge
- [ ] Scope filter works in all agent tools

✅ **Checkpointer Persistent**
- [ ] Checkpoints survive process restart
- [ ] Each user/agent has isolated checkpoint directory
- [ ] Multi-turn state correctly preserved

✅ **Thread_ID Verified**
- [ ] --session parameter actually preserves state
- [ ] Multi-turn conversations appear in same checkpoint thread
- [ ] Documented behavior in test/code comments

---

## Timeline Estimate

| Phase | Task | Effort | Time | Note |
|-------|------|--------|------|------|
| P1 | Fix CACHE_DIR + test | 1h | 1h | Move to ~/.olav/cache/{user}/ |
| P2 | Use DuckDBSaver + fix CLI async | 2h | 2h | Sync invoke() wrapper, keep DuckDB design |
| P3 | Add LanceDB scope | 1.5h | 1.5h | Add user scope to search queries |
| P4 | Verify thread_id chain | 1.5h | 1.5h | E2E test for session persistence |
| **Total** | | **6h** | **6h** | Keep DuckDB, avoid SQLite concurrency issues |

---

## References

- AGENTS.md: Multi-user security section
- copilot-instructions.md: Anti-patterns section (multi-user)
- dev_docs/MEMORY_INTEGRATION_AUDIT.md: Detailed analysis

