# Cache Migration: Native-Only Implementation

**Created:** 2026-02-22
**Updated:** 2026-02-23
**Status:** Draft
**Priority:** High
**Decision:** 完全删除自定义缓存，使用原生缓存系统

---

## Changelog

### 2026-02-23
- ✅ 移除 `search_cache` 幽灵引用（OLAV.md, network_ops_subagent.md）
- ✅ 归档 `scripts/clean_old_cache.py` 到 `_legacy_archived/scripts/`
- 📝 添加 SQLAlchemyCache 替代 SQLiteCache 方案
- 📝 添加 DuckDB 统一存储方案分析
- 📝 添加宏观缓存架构设计思考

---

## Executive Summary

**Decision:** 删除所有自定义缓存代码，完全依赖 LangChain + LangGraph 原生缓存。

| Before | After |
|--------|-------|
| 自定义 ResponseCache (305 行) | **DELETED** |
| LangChain SQLiteCache | ✅ 保留 |
| LangGraph Cache | ✅ 新增 |

**Rationale:**
- 自定义缓存与原生功能重叠
- 原生缓存更稳定、维护成本为零
- Snapshot-aware invalidation 价值不足以支撑 305 行代码的复杂性
- deepagents 已原生支持 LangGraph cache 参数

---

## Part 1: 删除清单

### 1.1 Files to Delete

```bash
# 完全删除
src/olav/core/response_cache.py        # 305 lines - DELETE
```

### 1.2 Code to Remove

#### `src/olav/agents/agent.py`
```python
# DELETE these lines (lines ~388-411 in invoke method)
from olav.core.response_cache import get_response_cache
cache = get_response_cache()
cached = cache.get_exact(query)
if cached:
    return {...}
# ... and ...
cache.store(query, content, source_agent="olav-ops")
```

#### `src/olav/cli/main.py`
```python
# DELETE these lines in run_single_query() (lines ~368-380)
from olav.core.response_cache import get_response_cache
# ... entire cache block

# DELETE these lines in simple_cli() (lines ~326-337)
from olav.core.response_cache import get_response_cache
cache = get_response_cache()
cached = cache.get_exact(user_input)
if cached:
    console.print(...)
    continue
```

---

## Part 2: Native Cache Architecture

### 2.1 Two-Layer Native Cache

```
┌─────────────────────────────────────────────────────────────┐
│                    LAYER 1: LLM Cache                        │
│                    LangChain SQLiteCache                     │
│                                                             │
│  What: Every llm.invoke() call                              │
│  Key: (prompt + model + params) hash                        │
│  Value: AIMessage (with tool calls)                         │
│  Location: .olav/databases/llm_cache.db                     │
│                                                             │
│  ✅ Already implemented in agent.py:107-113                 │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                   LAYER 2: Graph Cache                       │
│                   LangGraph SqliteCache                      │
│                                                             │
│  What: Node-level execution results                          │
│  Key: (node_name + input_state) hash                        │
│  Value: Node output state                                   │
│  Location: .olav/databases/graph_cache.db                   │
│                                                             │
│  ⚠️ TO BE IMPLEMENTED                                        │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 How Native Cache Works

```
User Query: "How many devices?"
         │
         ▼
┌─────────────────────────────────────┐
│  LangGraph graph.invoke()           │
│  ↓ Check graph cache                │
│  ↓ If miss, execute graph          │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Orchestrator Node                  │
│  llm.invoke("route query")          │  ← SQLiteCache checks here
│  ↓ Cache HIT? Return immediately    │  ← Same query = instant response
│  ↓ Cache MISS? Call LLM             │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  SubAgent Node                      │
│  llm.invoke("execute_sql ...")      │  ← SQLiteCache again
│  ↓ Cached at LLM level              │
└─────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Result returned to user            │
│  Graph cache stores full result     │  ← Future: cache entire flow
└─────────────────────────────────────┘
```

### 2.3 Why Native Cache is Sufficient

| Scenario | Native Behavior |
|----------|----------------|
| Identical query repeated | SQLiteCache returns cached LLM response instantly |
| Query with different wording | New LLM call (expected) |
| Data changed (new snapshot) | LLM cache still valid, but query results via tool will be fresh |

**Key insight:** The LLM doesn't store the data - it generates SQL queries. Each SQL query executes against live DuckDB. So even with cached LLM responses, the actual data query is always fresh.

```
Query 1: "How many devices?"
         ↓
LLM generates: SELECT COUNT(*) FROM devices
         ↓
Result: 6 devices

[New snapshot taken - 2 devices added]

Query 2: "How many devices?"
         ↓
SQLiteCache returns: SELECT COUNT(*) FROM devices  ← Cached LLM response
         ↓
SQL executes against LIVE DuckDB: 8 devices  ← Fresh result!
```

**Conclusion:** LLM cache only caches the *queries*, not the *data*. Data is always fresh.

---

## Part 3: Implementation

### 3.1 Step 1: Delete ResponseCache

```bash
rm src/olav/core/response_cache.py
```

### 3.2 Step 2: Clean agent.py

Remove cache code from `invoke()` method:

```python
# src/olav/agents/agent.py
# BEFORE (lines 388-420)
async def invoke(self, query: str, thread_id: str | None = None) -> dict:
    try:
        # Check response cache FIRST  ← DELETE
        cache = get_response_cache()   ← DELETE
        cached = cache.get_exact(query) ← DELETE
        if cached:                     ← DELETE
            return {...}               ← DELETE
        
        input_data = {"messages": [{"role": "user", "content": query}]}
        # ...
        result = await self.graph.ainvoke(input_data, config=config)
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            content = last.content if hasattr(last, "content") else str(last)
            # Store successful response in cache  ← DELETE
            cache.store(query, content, ...)       ← DELETE
            return {...}
```

```python
# AFTER
async def invoke(self, query: str, thread_id: str | None = None) -> dict:
    """Invoke the orchestrator with a natural language query."""
    try:
        input_data = {"messages": [{"role": "user", "content": query}]}
        config = None
        if self.checkpointer:
            config = {"configurable": {"thread_id": thread_id or f"thread-{id(input_data)}"}}
        
        logger.info(f"[invoke] query={query[:100]!r}")
        result = await self.graph.ainvoke(input_data, config=config)
        
        messages = result.get("messages", [])
        if messages:
            last = messages[-1]
            content = last.content if hasattr(last, "content") else str(last)
            return {
                "status": "success",
                "response": content,
                "thread_id": thread_id or "default",
            }
        return {"status": "error", "message": "No response generated"}
    except Exception as e:
        logger.error(f"Agent invocation failed: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}
```

### 3.3 Step 3: Clean main.py

Simplify `run_single_query()`:

```python
# src/olav/cli/main.py
# BEFORE
async def run_single_query(query: str, assistant_id: str) -> None:
    """Run a single query and exit."""
    from deepagents_cli.config import COLORS
    from rich.markdown import Markdown
    # Use OLAVAgent.invoke() which handles cache check AND storage internally
    from olav.agents.agent import OLAVAgent
    olav_agent = OLAVAgent(enable_checkpointer=False, enable_store=True)
    # invoke() returns: {status, response, thread_id, cached?}
    result = await olav_agent.invoke(query)
    if result["status"] == "success":
        # Show cache indicator if this was a cache hit
        if result.get("cached"):
            console.print("\n[green]⚡ Cache hit[/green]...")
        console.print(Markdown(result["response"]), style=COLORS.get("agent", "cyan"))
    else:
        console.print(f"[red]Error:[/red] {result.get('message', 'Unknown error')}")
```

```python
# AFTER
async def run_single_query(query: str, assistant_id: str) -> None:
    """Run a single query and exit.
    
    Uses native LangChain SQLiteCache for LLM call deduplication.
    No application-level cache needed.
    """
    from deepagents_cli.config import COLORS
    from rich.markdown import Markdown
    from olav.agents.agent import OLAVAgent
    
    olav_agent = OLAVAgent(enable_checkpointer=False, enable_store=True)
    result = await olav_agent.invoke(query)
    
    if result["status"] == "success":
        console.print(Markdown(result["response"]), style=COLORS.get("agent", "cyan"))
    else:
        console.print(f"[red]Error:[/red] {result.get('message', 'Unknown error')}")
```

Simplify `simple_cli()`:

```python
# BEFORE (in simple_cli)
        # Check response cache FIRST (bypass LLM if hit)
        from olav.core.response_cache import get_response_cache
        from rich.markdown import Markdown

        cache = get_response_cache()
        cached = cache.get_exact(user_input)
        if cached:
            console.print(
                "\n[green]⚡ Cache hit[/green] [dim](returning cached response)[/dim]\n"
            )
            console.print(Markdown(cached["response"]), style=COLORS.get("agent", "cyan"))
            continue

        # Execute task (streaming, no cache storage for interactive mode)
        await execute_task(...)
```

```python
# AFTER
        # Execute task - LangChain SQLiteCache handles LLM call deduplication
        await execute_task(
            user_input,
            agent,
            assistant_id,
            session_state,
            token_tracker,
            backend=backend,
        )
```

### 3.4 Step 4: Add LangGraph Cache (Optional Enhancement)

For future optimization, pass cache to `create_deep_agent()`:

```python
# src/olav/agents/agent.py
from langgraph.cache.memory import InMemoryCache
# OR
from langgraph.cache.sqlite import SqliteCache

class OLAVAgent:
    def __init__(self, ...):
        # ... existing code ...
        
        # LangGraph node-level cache (optional, for advanced caching)
        self._graph_cache = InMemoryCache()  # Or SqliteCache for persistence
    
    def _build_graph(self) -> CompiledStateGraph:
        return create_deep_agent(
            model=self.llm,
            tools=self._get_tools(),
            cache=self._graph_cache,  # ← Enable node caching
            # ... other params
        )
```

**Note:** This is optional. LangChain SQLiteCache alone is sufficient for most use cases.

---

## Part 4: Database Schema Cleanup

### 4.1 Tables to Drop

The `response_cache` table in `main.duckdb` is no longer needed:

```sql
-- Run this to clean up
DROP TABLE IF EXISTS response_cache;
```

Or via admin command:
```bash
uv run olav admin db --drop-table response_cache
```

### 4.2 Files to Keep

| File | Keep? | Purpose |
|------|-------|---------|
| `.olav/databases/main.duckdb` | ✅ | Network data |
| `.olav/databases/llm_cache.db` | ✅ | LangChain LLM cache |
| `.olav/databases/agent.duckdb` | ✅ | Checkpointer state |
| `.olav/databases/memory_store.duckdb` | ✅ | Long-term memory |

---

## Part 5: File Changes Summary

| File | Action | Lines Changed |
|------|--------|---------------|
| `src/olav/core/response_cache.py` | **DELETE** | -305 |
| `src/olav/agents/agent.py` | **MODIFY** | -25 |
| `src/olav/cli/main.py` | **MODIFY** | -30 |
| `src/olav/cli/admin.py` | **MODIFY** | -1 (remove llm_cache.db reference if any) |

**Net result:** ~360 lines removed, simpler architecture.

---

## Part 6: Testing

### 6.1 Verify Native Cache Works

```bash
# First query - should call LLM
uv run olav "How many devices?"
# Check logs for LLM call

# Second identical query - should use SQLiteCache
uv run olav "How many devices?"
# Should be much faster, no LLM call in logs
```

### 6.2 Verify Data Freshness

```bash
# Query 1
uv run olav "How many devices?"
# Output: 6 devices

# Take new snapshot (if applicable)
# ... snapshot process ...

# Query 2 (identical wording)
uv run olav "How many devices?"
# Output: Should reflect new data (because SQL runs against live DB)
```

### 6.3 Check Database Files

```bash
# LLM cache should exist and have content
ls -la .olav/databases/llm_cache.db

# Check cache size
sqlite3 .olav/databases/llm_cache.db "SELECT COUNT(*) FROM cache;"
```

---

## Part 7: Migration Verification

### Before Migration
- [ ] Document current cache behavior
- [ ] Run test queries to establish baseline performance

### After Migration
- [ ] Confirm `response_cache.py` is deleted
- [ ] Confirm no imports of `response_cache` remain
- [ ] Verify `llm_cache.db` exists and grows with usage
- [ ] Verify duplicate queries are faster
- [ ] Verify data freshness is maintained

### Commands to Verify

```bash
# Check no references to response_cache
grep -r "response_cache" src/
grep -r "ResponseCache" src/
grep -r "get_response_cache" src/

# Should only find references to llm_cache
grep -r "llm_cache" src/
```

---

## Part 8: Rollback Plan

If native caching proves insufficient:

```bash
# 1. Restore response_cache.py from git
git checkout HEAD -- src/olav/core/response_cache.py

# 2. Restore agent.py and main.py cache code
git checkout HEAD -- src/olav/agents/agent.py
git checkout HEAD -- src/olav/cli/main.py

# 3. Clear native cache to start fresh
rm .olav/databases/llm_cache.db
```

---

## Part 9: References

- [LangChain LLM Caching](https://python.langchain.com/docs/integrations/llm_caching)
- [LangGraph Cache](https://langchain-ai.github.io/langgraph/how-tos/cache/)
- [deepagents create_deep_agent()](../_legacy_archived/archive_v0_to_v0.11/deepagents/libs/deepagents/deepagents/graph.py)

---

## Appendix: Why Snapshot-Aware Invalidation Isn't Needed

**Previous concern:** "Data changes, but cache doesn't expire"

**Reality:**
1. LLM cache stores the *query*, not the *data*
2. SQL queries always execute against live DuckDB
3. Data freshness is guaranteed by the tool execution layer

**Example:**
```
Cached LLM response: "SELECT COUNT(*) FROM devices WHERE site='lab'"
Fresh SQL execution: Returns current count from live DB
```

The LLM guides HOW to query, not WHAT the result is. The result is always fresh.

---

## Part 10: DuckDB 统一存储方案 (2026-02-23)

### 10.1 当前架构（4 个独立文件）

```
.olav/databases/
├── main.duckdb          (19MB)   # 业务数据 (devices, parsed_outputs, topology_links)
├── agent.duckdb         (12KB)   # LangGraph Checkpointer (对话状态)
├── memory_store.duckdb  (780KB)  # LangGraph Store (长期记忆)
└── llm_cache.db         (45KB)   # LLM 缓存 (SQLite)
```

### 10.2 技术可行性分析

| 组件 | 能否共享连接 | 说明 |
|------|-------------|------|
| **DuckDBSaver** | ✅ 支持 | `DuckDBSaver(conn=shared_conn)` |
| **DuckDBStore** | ✅ 支持 | `DuckDBStore(conn=shared_conn)` |
| **SQLAlchemyCache** | ✅ 支持 | SQLAlchemy 引擎可共享 |
| **业务数据** | ✅ 支持 | 同一连接 |

### 10.3 统一 vs 分离的权衡

| 维度 | 统一方案 | 分离方案 |
|------|---------|---------|
| **备份/恢复** | ⚠️ 全量备份，无法单独恢复某部分 | ✅ 可按需备份各组件 |
| **并发** | ⚠️ 单连接写入瓶颈 | ✅ 独立连接无竞争 |
| **隔离** | ⚠️ 表名冲突风险 | ✅ 天然隔离 |
| **调试** | ✅ 单点查看所有状态 | ⚠️ 需检查多个文件 |
| **迁移** | ⚠️ 迁移脚本更复杂 | ✅ 组件独立迁移 |
| **存储** | ✅ 单文件压缩效率高 | ⚠️ 多文件元数据开销 |

### 10.4 推荐方案：半统一架构

**保留 2 个数据库：**

```
.olav/databases/
├── main.duckdb           # 业务数据 + Checkpointer + Store
│   ├── devices           # 业务表
│   ├── parsed_outputs    # 业务表
│   ├── topology_links    # 业务表
│   ├── checkpoint_writes # LangGraph 原生表
│   ├── checkpoint_blobs  # LangGraph 原生表
│   └── store             # LangGraph Store 表
│
└── llm_cache.duckdb      # LLM 缓存（独立）
```

**理由：**
1. **LLM 缓存独立**：高频读写、生命周期不同、可单独清理
2. **状态与业务统一**：Checkpointer/Store 与业务数据紧密关联，共享连接减少开销
3. **迁移友好**：LLM 缓存可随时删除重建，不影响业务状态

### 10.5 替换 SQLiteCache → SQLAlchemyCache

```python
# ❌ 旧方案（已弃用）
from langchain_community.cache import SQLiteCache
langchain.llm_cache = SQLiteCache(database_path=".olav/databases/llm_cache.db")

# ✅ 新方案（推荐）
import sqlalchemy
from langchain_core.globals import set_llm_cache
from langchain_community.cache import SQLAlchemyCache

# 创建 DuckDB 引擎
engine = sqlalchemy.create_engine("duckdb:///.olav/databases/llm_cache.duckdb")
set_llm_cache(SQLAlchemyCache(engine))
```

### 10.6 统一 Checkpointer/Store 到 main.duckdb

```python
# agent.py 修改
class OLAVAgent:
    def __init__(self, ...):
        # 共享连接
        import duckdb
        self._main_conn = duckdb.connect(
            str(self.olav_base_path / "databases" / "main.duckdb")
        )
        
        # Checkpointer 使用共享连接
        self.checkpointer = DuckDBSaver(conn=self._main_conn)
        
        # Store 使用共享连接
        self.store = DuckDBStore(self._main_conn)
```

---

## Part 11: 宏观缓存架构设计思考 (2026-02-23)

### 11.1 OLAV 的缓存层次

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Layer 0: 语义缓存 (未实现)                           │
│                     Semantic Cache for Fast Routing                     │
│                                                                         │
│  目的：让 Orchestrator 快速识别相似意图，跳过 LLM 路由                   │
│  实现：Embedding + 向量搜索 (DuckDB VSS 或 Qdrant)                      │
│  场景："有多少设备?" ≈ "设备数量是多少?" → 相同路由                     │
│  优先级：P3 (可选优化)                                                  │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Layer 1: LLM 精确缓存                               │
│                     SQLAlchemyCache + DuckDB                            │
│                                                                         │
│  目的：避免重复的 LLM 调用（相同 prompt + params）                       │
│  实现：SQLAlchemyCache(engine=duckdb)                                   │
│  场景：用户重复问完全相同的问题                                          │
│  优先级：P0 (已实现，需迁移到 DuckDB)                                   │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Layer 2: Graph 节点缓存                             │
│                     LangGraph InMemoryCache                             │
│                                                                         │
│  目的：缓存 Graph 节点执行结果，避免重复计算                             │
│  实现：InMemoryCache() 或 SqliteCache                                   │
│  场景：同一会话内，相同输入的节点不重复执行                              │
│  优先级：P1 (待实现)                                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Layer 3: 对话状态持久化                             │
│                     DuckDBSaver (Checkpointer)                          │
│                                                                         │
│  目的：跨会话保持对话上下文                                             │
│  实现：LangGraph DuckDBSaver                                            │
│  场景：用户可以继续之前的对话                                            │
│  优先级：P0 (已实现)                                                    │
└─────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                     Layer 4: 长期记忆存储                               │
│                     DuckDBStore                                         │
│                                                                         │
│  目的：跨线程持久化重要信息                                             │
│  实现：LangGraph DuckDBStore                                            │
│  场景：记住用户偏好、设备别名等                                          │
│  优先级：P0 (已实现)                                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

### 11.2 DeepAgents/LangGraph 原生能力映射

| 能力 | 原生组件 | OLAV 当前状态 | 建议 |
|------|---------|--------------|------|
| LLM 缓存 | `SQLAlchemyCache` | SQLite (旧API) | → 迁移到 DuckDB |
| 节点缓存 | `InMemoryCache` | 未使用 | → 启用 |
| 对话状态 | `DuckDBSaver` | ✅ 已使用 | 保持 |
| 长期记忆 | `DuckDBStore` | ✅ 已使用 | 保持 |
| 语义缓存 | 无原生 | 未实现 | 可选实现 |

### 11.3 语义缓存设计（可选）

**为什么需要语义缓存？**
- 用户可能用不同措辞问相同意图
- "设备数量" vs "有多少设备" vs "device count"
- 减少不必要的 LLM 路由调用

**实现方案：**

```python
# 使用 DuckDB VSS 扩展实现向量搜索
# .olav/skills/shared/tools/semantic_cache.py

import duckdb
from langchain_openai import OpenAIEmbeddings

conn = duckdb.connect("main.duckdb")
conn.execute("INSTALL vss; LOAD vss;")

# 创建语义缓存表
conn.execute("""
    CREATE TABLE IF NOT EXISTS semantic_cache (
        id INTEGER PRIMARY KEY,
        query_text VARCHAR,
        embedding FLOAT[1536],
        route_target VARCHAR,
        created_at TIMESTAMP DEFAULT NOW()
    )
""")

# 创建向量索引
conn.execute("""
    CREATE INDEX IF NOT EXISTS semantic_idx 
    ON semantic_cache USING HNSW (embedding)
""")

def get_semantic_route(query: str, threshold: float = 0.95) -> str | None:
    """查找语义相似的缓存路由"""
    embedding = OpenAIEmbeddings().embed_query(query)
    result = conn.execute("""
        SELECT route_target, cosine_similarity(embedding, ?) as score
        FROM semantic_cache
        WHERE score > ?
        ORDER BY score DESC
        LIMIT 1
    """, [embedding, threshold]).fetchone()
    return result[0] if result else None
```

### 11.4 实施优先级

| 优先级 | 任务 | 工作量 | 收益 |
|--------|------|--------|------|
| **P0** | 迁移 SQLiteCache → SQLAlchemyCache | 10min | 消除弃用警告 |
| **P0** | 统一 Checkpointer/Store 到 main.duckdb | 30min | 减少文件数 |
| **P1** | 启用 LangGraph InMemoryCache | 5min | 节点级缓存 |
| **P3** | 实现语义缓存（可选） | 2-4h | 优化路由效率 |

### 11.5 设计原则

1. **优先使用原生组件**：不自己造轮子
2. **分层缓存**：每一层解决不同问题
3. **数据新鲜度**：LLM 缓存只缓存「怎么查」，不缓存「查什么」
4. **可清理性**：LLM 缓存应该可以随时删除而不影响业务
5. **渐进增强**：先实现 P0，再根据需要添加高级功能

---

## Part 12: 清理记录 (2026-02-23)

### 已完成

| 任务 | 文件 | 状态 |
|------|------|------|
| 移除 search_cache 幽灵引用 | `.olav/OLAV.md` | ✅ |
| 移除 search_cache 文档 | `.olav/skills/olav-ops/prompts/network_ops_subagent.md` | ✅ |
| 归档清理脚本 | `scripts/clean_old_cache.py` → `_legacy_archived/scripts/` | ✅ |

### 待完成

| 任务 | 优先级 | 状态 |
|------|--------|------|
| 迁移 SQLiteCache → SQLAlchemyCache | P0 | ⏳ |
| 统一 Checkpointer 到 main.duckdb | P0 | ⏳ |
| 统一 Store 到 main.duckdb | P1 | ⏳ |
| 启用 InMemoryCache | P1 | ⏳ |
