# OLAV Memory Integration Audit
**Generated:** 2026-03-02  
**Status:** ⚠️ PARTIAL - Issues Found

---

## Executive Summary

检查发现 **缓存、多用户隔离、LanceDB长期记忆** 的集成存在以下问题：

| 组件 | 状态 | 严重程度 | 说明 |
|------|------|--------|------|
| **LLM Cache (SQLiteCache)** | ✅ 实现 | 🔴 高 | CACHE_DIR配置错误，多用户**共享同一缓存DB**，无隔离 |
| **Checkpointer (MemorySaver)** | ✅ 实现 | 🟡 中 | 支持thread_id，但异步兼容问题使用MemorySaver（非持久) |
| **LanceDB长期记忆** | ✅ 实现 | 🟡 中 | 在OLAVAgent中初始化，但**未验证各agents实际使用** |
| **Thread_ID传播** | ⚠️ 部分 | 🟡 中 | CLI支持--session参数，但deepagents_cli执行链中**thread_id传入不确定** |
| **多用户会话隔离** | ❌ 缺失 | 🔴 高 | Checkpoints使用内存，重启后丢失；LanceDB无用户隔离 |

---

## 详细发现

### 1. LLM Cache —— CRITICAL BUG 🔴

**当前实现** (`src/olav/agents/agent.py#L122-L127`):

```python
from olav.core.config import CACHE_DIR

cache_path = CACHE_DIR / "llm_cache.db"
cache_path.parent.mkdir(parents=True, exist_ok=True)
try:
    langchain.llm_cache = SQLiteCache(database_path=str(cache_path))
```

**CACHE_DIR定义** (`src/olav/core/config.py#L523`):

```python
CACHE_DIR = AGENT_DIR / "cache"  # 错误：项目级别，不是用户级别!
```

**问题**:
- ❌ CACHE_DIR = `.olav/cache/llm_cache.db` — **项目全局共享**
- ❌ 多用户场景：所有用户共享同一个SQLite缓存文件
- ❌ 并发问题：多用户同时写入会导致锁竞争，可能数据损坏
- ❌ 隐私问题：一个用户的LLM查询缓存被其他用户看到

**应该是**:
```python
# 用户隔离的缓存目录
USER_CACHE_DIR = Path.home() / ".olav" / "cache" / _username
```

---

### 2. Checkpointer —— PARTIAL IMPLEMENTATION 🟡

**实现状态**:
- ✅ OLAVAgent中创建InMemorySaver（async兼容版本）
- ✅ ainvoke()支持thread_id参数
- ✅ thread_id传入config["configurable"]
- ❌ DuckDBSaver (原计划) 被改为MemorySaver

**问题**:
- 🟡 MemorySaver是**内存级别**，重启后失效
- 🟡 多用户不隔离 — 所有用户的checkpoints都在同一个内存中
- ⚠️ 原plan是使用DuckDBSaver（已在第44行导入），但因asyncio兼容问题被弃用

**代码证据** (`src/olav/agents/agent.py#1-50行`):

```python
# 第44行：DuckDBSaver已导入（表明原设计）
from langgraph.checkpoint.duckdb import DuckDBSaver

# 第21-27行：文档注释说应该用DuckDBSaver
"""
Architecture:
- LangGraph DuckDBSaver for checkpoint/persistence (persistent across restarts)
"""
```

**为什么被弃用** (`src/olav/agents/agent.py#L134-L146`):

```python
# Checkpointer — use MemorySaver for async compatibility 
# (DuckDB doesn't support aget_tuple)
# TODO: Switch back to DuckDBSaver once LangGraph fixes async support

try:
    from langgraph.checkpoint.memory import MemorySaver
    self.checkpointer = MemorySaver()
    logger.info("✓ Checkpointer initialized (MemorySaver - for async CLI support)")
except Exception as e:
    logger.warning(f"MemorySaver failed ({e}), no checkpoint support available")
```

**关键点：应该坚持DuckDB，不用SQLite**:
- ❌ SQLiteSaver在LangGraph中也不实现async
- ❌ SQLite并发问题（多用户同时写）  
- ✅ DuckDB是原始设计，应该改进CLI层以支持DuckDBSaver

---

### 3. LanceDB 长期记忆 —— INITIALIZED BUT UNVERIFIED 🟡

**实现状态**:
- ✅ LangGraphLanceDBStore在OLAVAgent初始化
- ✅ 传入create_deep_agent的store参数
- ✅ 搜索工具集成了LanceDB (search_knowledge_lancedb.py)

**问题**:
1. ⚠️ **未验证各agent实际使用** — 虽然store创建，但是否真正被agents调用不确定
2. 🟡 **无用户/scope隔离** — LanceDB中所有agents共享同一个内存库
3. 🟡 **search_knowledge工具** — 支持scope参数，但默认"global"

**证据**:

a) LanceDB初始化 (`src/olav/agents/agent.py#L148-L155`):
```python
self.store = None
try:
    db_path = self.olav_base_path / "databases" / "memory.lancedb"
    self.store = LangGraphLanceDBStore(db_path=str(db_path))
    logger.info(f"✓ Long-term memory store initialized (LanceDB): {db_path}")
except Exception as e:
    logger.warning(f"LanceDBStore init failed: {e}. Long-term memory disabled.")
```

b) 创建graph时传入store (`src/olav/agents/agent.py#L164-L170`):
```python
self.graph = create_deep_agent(
    model=self.llm,
    tools=orchestrator_tools,
    system_prompt=self._get_orchestrator_prompt(olav_config),
    checkpointer=self.checkpointer,
    store=self.store,  # ← 传入LanceDB store
    subagents=subagents,
)
```

c) 搜索工具支持scope，但默认"global" (`/.olav/workspace/ops/tools/search_knowledge_lancedb.py`):
```python
@tool
def search_knowledge(
    query: str,
    limit: int = 5,
    category: str | None = None,
    scope: str | None = "global",  # ← 默认全局
) -> str:
```

---

### 4. Thread_ID 传播链路 —— PARTIAL CHAIN ⚠️

**链路分析**:

```
CLI Layer:
  olav --session USER_SESSION_ID "query"         ← session参数支持
        ↓
main.py run_single_query(query, assistant_id, session_id)
        ↓
create_olav_agent_with_backend(..., session_id=session_id)
        ↓
OLAVAgent(..., session_id=session_id)           ← 接收session_id
        ↓
Agent Layer:
  ainvoke(input_, thread_id=...)                  ← 支持thread_id参数
        ↓
config = {"configurable": {"thread_id": thread_id}}
        ↓
graph.ainvoke(input_, config=config)

MISSING LINK:
  deepagents_cli.execute_task()                   ← 第三方库，
                                                    不确定是否传入thread_id
```

**问题**:
- ⚠️ 不确定deepagents_cli中的execute_task是否真的使用thread_id
- ⚠️ 即使ainvoke支持thread_id，如果execute_task没有传入也无用

---

### 5. 多用户会话隔离 —— MISSING 🔴

**设计意图** (来自 `AGENTS.md` 和 `copilot-instructions.md`):
```markdown
## 4. MULTI-USER SECURITY (V0.11.0+)

1.  **Concurrency**: Multiple users **WILL** operate on the same project.
2.  **Isolation**: Users must have their own private checkpoint and cache 
    files in `~/.olav/`.
3.  **Auditing**: Every CLI command **MUST** be logged to `.olav/logs/users/{user}.log`.
```

**实际实现**:
- ❌ Checkpoints: MemorySaver（内存级），所有用户共享
- ❌ LLM Cache: `.olav/cache/llm_cache.db`（项目级），所有用户共享
- ❌ LanceDB: `.olav/databases/memory.lancedb`（项目级），所有用户共享
- ✅ Audit Logs: `~/.olav/logs/users/{user}.log` — 这个是正确的

---

## 根本原因分析

### 为什么会有这些问题？

1. **配置管理不一致**:
   - User-local paths: USER_HISTORY_DIR, USER_SESSION_DIR `~/.olav/`
   - But CACHE_DIR, databases: `.olav/` （项目级）
   - 混杂导致多用户隔离不完整

2. **设计时项目级数据库架构**:
   - DuckDB为主（`.olav/databases/main.duckdb`）
   - LanceDB跟随（`.olav/databases/memory.lancedb`）
   - 假设单个项目 + 单个用户
   - 未考虑到多用户共享同一项目的场景

3. **异步兼容性折衷**:
   - 想要DuckDBSaver（持久化）但因asyncio问题无法使用
   - 落回MemorySaver（非持久化，内存级）
   - 损失了会话恢复能力

4. **第三方库依赖不清**:
   - deepagents_cli黑盒化
   - 不确定thread_id/session是否真正被使用
   - 设计依赖了第三方库的功能但未验证

---

## 影响评估

### 场景1: 多用户同时使用OLAV

**当前行为**:
```
User A: "query_A" 
  → LLM Cache hit检查 → 写入 llm_cache.db (lock)
User B: "query_B"
  → LLM Cache hit检查 → 等待lock → timeout或锁竞争 ❌
```

**结果**: SQLiteCache并发错误，可能导致缓存损坏

### 场景2: 会话恢复

**当前行为**:
```
User A启动第一个查询:
  checkpointer = MemorySaver()  # 新的内存实例
  → 查询执行，checkpoints存入内存
用户关闭连接重启:
  checkpointer = MemorySaver()  # 新的内存实例！
  → 之前的checkpoints丢失 ❌
```

**结果**: 会话无法恢复，LangGraph的有状态特性被破坏

### 场景3: 长期记忆跨会话

**当前行为**:
```
查询1: search_knowledge("BGP troubleshooting")
  → scope="global" → LanceDB中存储
查询2: search_knowledge("BGP troubleshooting")  
  → 获取同一个global scope → 包含所有用户的知识 ❌
```

**结果**: 知识库无法隔离，安全风险

---

## 修复建议 （优先级）

### 🔴 P1: 修复LLM Cache多用户隔离

```python
# src/olav/core/config.py (line ~523)
_username = os.environ.get("USER") or os.getlogin()
USER_CACHE_DIR = Path.home() / ".olav" / "cache" / _username

# src/olav/agents/agent.py (line ~122)
from olav.core.config import USER_CACHE_DIR

cache_path = USER_CACHE_DIR / "llm_cache.db"
```

**验证**:
```bash
# 用户A
$ ls -la ~/.olav/cache/alice/llm_cache.db  # 只有alice的缓存

# 用户B
$ ls -la ~/.olav/cache/bob/llm_cache.db    # 只有bob的缓存
```

### � P2: 修复DuckDBSaver异步兼容问题（推荐）

不用SQLite，应该坚持DuckDB设计。只需要在CLI层修改：

```python
# src/olav/agents/agent.py (第134-146行)
# 改为：
from langgraph.checkpoint.duckdb import DuckDBSaver
import duckdb

checkpoint_dir = Path.home() / ".olav" / "checkpoints" / _username / self.agent_id
checkpoint_dir.mkdir(parents=True, exist_ok=True)
conn = duckdb.connect(str(checkpoint_dir / "checkpoints.duckdb"), read_only=False)
self.checkpointer = DuckDBSaver(conn)

# src/olav/cli/main.py (修改run_single_query)
# 使用sync invoke()而不是async ainvoke()来避免aget_tuple问题
result = await agent.invoke(query, thread_id=session_id)  # Sync invoke in async context
```

**验证**:
```bash
# DuckDB checkpoints现在是持久化的
ls ~/.olav/checkpoints/$USER/ops/checkpoints.duckdb

# 重启后查询仍然可以恢复
duckdb ~/.olav/checkpoints/$USER/ops/checkpoints.duckdb "SELECT * FROM checkpoints"
```

### 🟡 P3: 验证deepagents中的thread_id传入

需要在deepagents_cli的execute_task中添加logging或调试：

```python
# deepagents_cli核心代码（需要深入investigate）
await execute_task(..., thread_id=session_id)  # 是否真的用了？
```

### 🟡 P4: 验证LanceDB在各agent中的实际使用

创建E2E测试：
```python
# 测试long-term semantic memory是否真的被存储和检索
agent.invoke("Store fact: BGP is for routing")
agent.invoke("Retrieve fact about BGP")
# 检查LanceDB中是否有记录
```

### 🟢 P5: 添加User Scope到LanceDB

```python
# search_knowledge_lancedb.py
# 改进scope隔离
scope = os.environ.get("USER") or "default"  # 使用用户名而不是"global"
```

---

## 验证检查清单

### ✅ 已验证
- [x] OLAVAgent.__init__()创建LLM缓存、checkpointer、LanceDB store
- [x] ainvoke()方法支持thread_id参数
- [x] create_deep_agent传入store参数
- [x] search_knowledge_lancedb工具存在

### ⚠️ 需要验证
- [ ] `deepagents_cli.execute_task()`是否真的使用thread_id参数
- [ ] LanceDB store是否在真实查询中被调用
- [ ] MemorySaver中的checkpoints是否在多轮对话中正确累积
- [ ] SQLiteCache并发场景下是否有锁问题

### ❌ 需要修复
- [ ] CACHE_DIR改为用户隔离的USER_CACHE_DIR (P1)
- [ ] 使用DuckDBSaver替代MemorySaver，修正CLI async问题 (P2)
- [ ] 验证deepagents_cli中thread_id的实际使用 (P3)
- [ ] 验证LanceDB在agent中的实际被调用 (P4)
- [ ] LanceDB scope改为使用username而不是"global" (P5)

---

## 相关代码文件

| 文件 | 行号 | 内容 |
|------|------|------|
| `src/olav/agents/agent.py` | 122-127 | LLM Cache初始化 |
| `src/olav/agents/agent.py` | 148-155 | LanceDB初始化 |
| `src/olav/agents/agent.py` | 315-343 | ainvoke/invoke方法 |
| `src/olav/core/config.py` | 523 | CACHE_DIR定义 |
| `src/olav/core/config.py` | 519-521 | USER_HISTORY_DIR, USER_SESSION_DIR定义 |
| `.olav/workspace/*/tools/search_knowledge_lancedb.py` | 30-50 | scope参数定义 |
| `src/olav/cli/main.py` | 360-378 | run_single_query中session_id处理 |

---

## 结论

**总体状态**: ⚠️ **PARTIAL - 代码存在但未完全集成**

虽然所有三个组件（LLM Cache、Checkpointer、LanceDB）都已实现，但：

1. 🔴 **多用户隔离破坏严重** — Cache和LanceDB无隔离，存在并发安全风险
2. 🟡 **Checkpointer无持久化** — 会话无法跨重启恢复
3. ⚠️ **Thread_ID链路不确定** — 设计上支持但实际传入不清楚
4. ⚠️ **缺少E2E验证** — 各component虽然存在但实际使用情况未验证

**建议优先修复P1（CACHE_DIR）和P2（验证thread_id链路）**。
