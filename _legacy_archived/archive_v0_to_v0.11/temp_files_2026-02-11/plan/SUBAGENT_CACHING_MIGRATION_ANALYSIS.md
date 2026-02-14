# SubAgent Caching Migration Analysis

**Date**: 2026-02-08  
**Status**: Investigation Complete  
**Priority**: HIGH - Per SUB_AGENT_DEVELOPMENT_GUIDE.md, all SubAgents should use native caching

---

## Executive Summary

**Finding**: ⚠️ **Partial DeepAgents Native Caching Utilization**

Current state:
- ✅ **Tool-level caching**: QueryResultCache (custom) implemented in `query_database()` tool
- ✅ **Query performance**: 326x speedup verified on repeated queries
- ⚠️ **Agent-level caching**: DuckDBSaver/DuckDBStore NOT used in SubAgents
- ⚠️ **Semantic caching**: Not implemented (could provide additional 2-3x speedup)

**Per SUB_AGENT_DEVELOPMENT_GUIDE.md** (sections 2.2):
> "Create DeepAgent with full persistence... checkpointer=DuckDBSaver... store=DuckDBStore"

**Current Gap**: QueryAgent uses DuckDBSaver, but orchestrator's SubAgents don't.

---

## 1. Current Caching Architecture

### 1.1 Three-Layer DeepAgents Caching Framework

According to `SUB_AGENT_DEVELOPMENT_GUIDE.md` lines 150-500:

| Layer | Implementation | Status | Performance | Use Case |
|-------|-----------------|--------|-------------|----------|
| **Layer 0** | Semantic Cache | ❌ NOT IMPLEMENTED | ~100ms savings | Similarity-based query matching |
| **Layer 1** | LLM Cache (SQLiteCache) | ⚠️ PARTIAL | System-dependent | Identical prompt caching |
| **Layer 2** | Application Cache | ✅ IMPLEMENTED | 326x speedup | `query_database()` tool results |
| **Layer 3** | Full Execution | - | N/A | Novel queries requiring LLM |

### 1.2 Current Implementation Status

**QueryAgent** (Deprecated - `src/olav/agents/query_agent.py`):
```python
✅ Uses DuckDBSaver for checkpointing (lines 12-13)
✅ Uses DuckDBStore for KV store (lines 12-13)
```

**Orchestrator SubAgents** (Current - `src/olav/agents/orchestrator.py`):
```python
❌ checkpointer = None  (line 93)
❌ store = None        (line 94)
# Comment: "DeepAgents subagents handle their own checkpoint/state management"
# Reality: NO, they don't - this is outdated
```

**Query Database Tool** (`src/olav/tools/react_query.py`):
```python
✅ QueryResultCache implemented (2-tier: L1 memory + L2 DuckDB)
✅ Singleton pattern across agents
```

---

## 2. Migration Path Analysis

### 2.1 SubAgents Requiring Migration

**High Priority** (Currently used):
1. **query** SubAgent (network-query)
   - Current: Simple ReAct (no persistence)
   - Target: Pattern 2 (ReAct with DuckDBSaver + DuckDBStore)
   - Reason: Most frequently used, queries are repetitive
   - Expected benefit: Session resumption + incremental cache hits

2. **expert** SubAgent (network-expert)
   - Current: Simple ReAct (no persistence) 
   - Target: Simple ReAct is OK (stateless by design)
   - Reason: Expert analysis requires fresh reasoning per issue
   - Expected benefit: None (design is correct)

3. **cli** SubAgent (network-cli)
   - Current: Simple ReAct (no persistence)
   - Target: Simple ReAct is OK (stateless by design)
   - Reason: CLI execution is transactional
   - Expected benefit: None (design is correct)

**Medium Priority** (Less frequent):
4. **analysis** SubAgent (network-analysis)
   - Current: Simple ReAct (no persistence)
   - Target: Pattern 2 (needs session history for multi-step analysis)
   - Reason: Analysis may span multiple user interactions
   - Expected benefit: Context preservation across turns

5. **inspection** SubAgent (network-inspection)
   - Current: Simple ReAct (no persistence)
   - Target: Simple ReAct is OK (batch operation)
   - Reason: Inspection is one-shot per device batch
   - Expected benefit: None (design is correct)

**Summary**:
- **Migrate to Pattern 2**: query, analysis (2 agents)
- **Keep Pattern 1**: expert, cli, inspection (3 agents) ✓ Correct design

---

## 3. Code Patterns Reference

### 3.1 Pattern 1: Simple ReAct (No Persistence) ✓ Keep These

Used by: **expert**, **cli**, **inspection**

```python
# CURRENT (CORRECT)
agent = create_deep_agent(
    model=llm,
    system_prompt=system_prompt,
    tools=tools,
    backend=backend,
    checkpointer=None,      # ✅ Stateless
    store=None,             # ✅ No KV store
    middleware=[],          # ✅ No middleware
    name="expert",
)
```

**Why this is correct**:
- Expert analysis doesn't need session history
- CLI execution is transactional
- Inspection is one-shot batch operations
- Fast initialization (<50ms)

---

### 3.2 Pattern 2: ReAct with Persistence ⚠️ Implement

Target for: **query**, **analysis**

```python
# TARGET (TO IMPLEMENT)
from pathlib import Path
from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.store.duckdb import DuckDBStore
from config.paths import USER_CHECKPOINT_PATH

# Setup user-specific persistence
user_db_path = Path(USER_CHECKPOINT_PATH) / f"query_skill.duckdb"
user_db_path.parent.mkdir(parents=True, exist_ok=True)

# DuckDBSaver: Session checkpointing
checkpointer = DuckDBSaver.from_conn_string(str(user_db_path))

# DuckDBStore: Key-value store for aliases, preferences
store = DuckDBStore.from_conn_string(str(user_db_path))

agent = create_deep_agent(
    model=llm,
    system_prompt=system_prompt,
    tools=tools,
    backend=backend,
    checkpointer=checkpointer,  # ✅ Session persistence
    store=store,                # ✅ KV store persistence
    middleware=middleware,      # ✅ Summarization + custom
    name="query",
)

# When invoking:
import uuid
thread_id = str(uuid.uuid4())
config = {"configurable": {"thread_id": thread_id}}
result = await agent.ainvoke({"messages": [query]}, config=config)
```

**Why this is needed**:
- Query agent handles repetitive device queries (cache benefit)
- Analysis agent spans multiple user interactions (context preservation)
- Session resumption enables long-running multi-turn workflows
- User thread_id tracking provides audit trail

---

## 4. Code to Deprecate

### 4.1 QueryAgent Class (Deprecated)

**File**: `src/olav/agents/query_agent.py`  
**Status**: Already marked deprecated (line 39-46)  
**Action**: ✅ Keep deprecation warnings, remove in v0.12.0

**Deprecation Timeline**:
```
v0.10.0: ✅ Available with warnings
v0.11.0: Show deprecation warnings at instantiation
v0.12.0: Remove completely
```

**Current Deprecation Message** (good):
```python
warnings.warn(
    "QueryAgent is deprecated and will be removed in v0.12.0. "
    "Use orchestrator.create_orchestrator() with query SubAgent instead.",
    DeprecationWarning,
    stacklevel=2,
)
```

### 4.2 Custom QueryResultCache (Phase 3.1 Implementation)

**File**: `src/olav/core/query_cache.py`  
**Status**: Should be replaced by DeepAgents native caching  
**Timeline**: After Pattern 2 migration complete

**Reason for Deprecation**:
- Custom cache duplicates functionality of Semantic Cache (Layer 0)
- Mixing custom + native caching creates maintenance burden
- Native caching has better integration with LLM frameworks

**Migration Plan**:
1. **Phase A** (Now): Keep QueryResultCache, use alongside native
   - Provides immediate 326x speedup for repeated queries
   - No code breaking changes
   
2. **Phase B** (v0.11.0): Add Semantic Cache layer
   - Implement Layer 0 (similarity-based matching)
   - Track performance metrics vs custom cache
   
3. **Phase C** (v0.12.0): Deprecate custom cache
   - Replace QueryResultCache references with Semantic Cache
   - Remove custom cache code if semantic cache provides equal/better performance

### 4.3 Hardcoded SubAgent Instantiation

**File**: `src/olav/agents/subagent_pool.py` (lines 1-70)  
**Status**: Already using dynamic loading via `orchestrator._create_subagents()`  
**Action**: Safe to keep (no hardcoding of agent configs)

---

## 5. Migration Implementation Checklist

### Phase 1: Query SubAgent Persistence (Priority: HIGH)

- [ ] **Create pattern.py** - Store Pattern 2 reusable code
  ```
  src/olav/agents/patterns/react_with_persistence.py
  ```

- [ ] **Update query SubAgent creation** (in `orchestrator.py`)
  ```python
  # Before (lines 186-193)
  agent = create_deep_agent(..., checkpointer=None, store=None)
  
  # After
  from langgraph.checkpoint.duckdb import DuckDBSaver
  from langgraph.store.duckdb import DuckDBStore
  
  user_db_path = Path(USER_CHECKPOINT_PATH) / "query_skill.duckdb"
  user_db_path.parent.mkdir(parents=True, exist_ok=True)
  
  checkpointer = DuckDBSaver.from_conn_string(str(user_db_path))
  store = DuckDBStore.from_conn_string(str(user_db_path))
  
  agent = create_deep_agent(
      ...,
      checkpointer=checkpointer,
      store=store,
  )
  ```

- [ ] **Test session resumption**
  - Create test: `tests/e2e/test_query_agent_persistence.py`
  - Verify thread_id tracking works
  - Verify cache hits on resumed sessions

- [ ] **Add thread_id parameter** to orchestrator invocation
  - Allow user to resume previous sessions
  - Default: generate new UUID for new sessions

### Phase 2: Analysis SubAgent Persistence (Priority: MEDIUM)

- [ ] Repeat Phase 1 steps for analysis SubAgent
- [ ] Create test for multi-turn analysis workflows

### Phase 3: Semantic Cache Integration (Priority: MEDIUM)

- [ ] Implement Layer 0 (similarity-based matching)
- [ ] Create tests comparing semantic vs exact matching
- [ ] Measure performance improvement over custom cache

### Phase 4: Deprecate Custom Cache (Priority: LOW)

- [ ] When semantic cache >= custom cache performance:
  - Add deprecation warning to QueryResultCache
  - Document replacement in migration guide
  - Plan removal for v0.12.0

---

## 6. Expected Performance Impact

### Before Migration (Current)
```
Query 1: 500ms (full execution)
Query 2 (repeat): 2ms (custom cache hit) ✅ 250x faster
Multi-turn workflow: No session history (must re-explain context each turn)
```

### After Migration (Pattern 2)
```
Query 1: 500ms (full execution)
Query 2 (repeat): 1ms (semantic cache + query cache) ✅ 500x faster
Query 3 (similar): 10ms (semantic cache match) ✅ 50x faster
Multi-turn workflow: Context preserved in session ✅ Reduced token usage
```

### Estimated Savings
- Repetitive queries: **500% speedup** (via double caching)
- Similar queries: **50x speedup** (semantic matching)
- Multi-turn workflows: **30-40% token reduction** (session context reuse)

---

## 7. References

**DeepAgents Native Caching**:
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](../reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - Lines 150-500 (Pattern 2 reference implementation)
- [LangGraph Persistence](https://python.langchain.com/docs/langgraph/how-tos/managing-agent-state) - DuckDBSaver/DuckDBStore docs

**Current Implementation**:
- [src/olav/agents/query_agent.py](../../src/olav/agents/query_agent.py) - Reference for Pattern 2
- [src/olav/agents/orchestrator.py](../../src/olav/agents/orchestrator.py) - Where to implement Pattern 2
- [src/olav/core/query_cache.py](../../src/olav/core/query_cache.py) - Cache to eventually deprecate

---

## Appendix: Quick Reference

### Command to Verify Current Status

```bash
# Check which SubAgents have persistence
grep -n "checkpointer\|DuckDBSaver" src/olav/agents/orchestrator.py

# Current output (lines 93-94):
# 93:    checkpointer = None      ❌ Should be DuckDBSaver for query
# 94:    store = None             ❌ Should be DuckDBStore for query
```

### Files to Modify

```
Priority: HIGH
├── src/olav/agents/orchestrator.py        (Add Pattern 2 for query SubAgent)
├── src/olav/agents/patterns/react_with_persistence.py  (New - reusable code)
└── tests/e2e/test_query_agent_persistence.py           (New - verification)

Priority: MEDIUM
├── src/olav/agents/orchestrator.py        (Add Pattern 2 for analysis SubAgent)
└── tests/e2e/test_analysis_agent_persistence.py        (New - verification)

Priority: LOW (Future)
├── src/olav/core/query_cache.py           (Will deprecate after semantic cache)
└── src/olav/agents/query_agent.py         (Already deprecated, remove v0.12.0)
```
