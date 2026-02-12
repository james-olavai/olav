# Backend增强方案 - 数据库集成分析

**创建日期**: 2026-02-06  
**版本**: v0.10.1  
**关键发现**: ✅ **所有数据库基础设施已存在，零破坏性变更**

---

## 🔍 OLAV现有数据库架构（v0.10.1）

### 1. **统一数据库** (Unified Single Database)

```python
# config/paths.py
UNIFIED_DB = .olav/db/olav.duckdb  # 单一DuckDB文件
```

**包含的表**:
```sql
-- 网络数据
devices, raw_outputs, audit_logs

-- 知识库（Phase 2需要）
knowledge_sources       -- 知识来源（Skills, Reports, Solutions）
knowledge_chunks        -- 文档片段 + FTS索引 + Vector索引
```

**所有别名指向同一文件**:
```python
KNOWLEDGE_PATH = UNIFIED_DB
NETWORK_SNAPSHOT_PATH = UNIFIED_DB
NETWORK_COMMANDS_PATH = UNIFIED_DB
```

**Why统一？**:
- ✅ 避免多数据库锁冲突
- ✅ 简化JOIN查询（无需ATTACH）
- ✅ 统一备份/恢复

---

### 2. **用户本地数据库** (Per-User Isolation)

```python
# config/paths.py
USER_CHECKPOINT_PATH = ~/.olav/checkpoints/{username}.duckdb
```

**用途**:
| 组件 | 功能 | 已在使用？ |
|------|------|----------|
| **DuckDBSaver** | LangGraph checkpointer (session state) | ✅ QueryAgent |
| **DuckDBStore** | LangGraph KV store (aliases, preferences) | ✅ DataGateway |

**Why Per-User？**:
- ✅ 多用户并发（避免锁冲突）
- ✅ 用户隔离（session state不共享）
- ✅ 个性化（每个用户自己的aliases）

**已在使用的代码**:

**QueryAgent** (`src/olav/agents/query_agent.py:154`):
```python
def _init_user_database(self) -> None:
    """Initialize user-specific persistent checkpointer and store using DuckDB."""
    self._checkpointer_cm = DuckDBSaver.from_conn_string(str(USER_CHECKPOINT_PATH))
    self._store_cm = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))
    self.checkpointer = self._checkpointer_cm.__enter__()
    self.store = self._store_cm.__enter__()
```

**DataGateway** (`src/olav/lib/data_gateway.py:283`):
```python
def save_user_alias(self, skill_name, alias, canonical, type="device"):
    """保存用户别名学习（使用 DuckDBStore）"""
    conn = duckdb.connect(str(USER_CHECKPOINT_PATH))
    store = DuckDBStore(conn)
    store.setup()
    
    namespace = (skill_name, "aliases")  # e.g., ("network-query", "aliases")
    key = alias.upper()
    
    store.put(namespace, key, {
        "canonical": canonical,
        "type": type,
        "usage_count": usage_count,
        "created_at": created_at
    })
```

---

### 3. **缓存数据库** (LLM Cache)

```python
# config/paths.py
LLM_CACHE_DB = .olav/cache/olav_cache.db  # SQLite (不是DuckDB)
```

**用途**: LLM调用缓存 (TTL-based, transparent layer)

**Why SQLite？**: 轻量级，专用于缓存（不需要DuckDB的分析能力）

---

## 🎯 Backend增强方案的数据库需求

### **Phase 1: Backend配置统一** ❌ 零数据库改动

**功能**: 使用CompositeBackend路由文件读写

**数据库涉及**:
```
❌ 无 - 纯文件系统路由
```

**改动范围**:
- ✅ 修改3个agent的backend参数（代码级）
- ❌ 不涉及任何数据库schema
- ❌ 不涉及任何数据迁移

---

### **Phase 2: Learning工作流完善** ✅ 使用现有UNIFIED_DB

#### 2.1 Save Solution - 写入Markdown

**功能**: 保存故障排除案例到 `.olav/knowledge/solutions/*.md`

**数据库涉及**:
```
❌ 无 - 纯文件写入
```

**流程**:
```python
save_solution(...) → 写入.md文件到.olav/knowledge/solutions/
```

#### 2.2 Git Commit - 版本控制

**功能**: 自动Git commit知识库变更

**数据库涉及**:
```
❌ 无 - Git操作
```

**流程**:
```python
_git_commit_solution() → git add + git commit
```

#### 2.3 Auto Vectorization - 触发向量化

**功能**: 自动触发向量化命令，更新knowledge_chunks表

**数据库涉及**:
```
✅ UNIFIED_DB.knowledge_chunks  # 已存在！
```

**现有基础设施** (`src/olav/core/database.py:268`):
```sql
-- knowledge_chunks表（已创建）
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER REFERENCES knowledge_sources(id),
    file_path TEXT NOT NULL,          -- .olav/knowledge/solutions/xxx.md
    chunk_index INTEGER NOT NULL,
    title TEXT,
    content TEXT NOT NULL,
    platform TEXT,
    doc_type TEXT,
    keywords TEXT[],
    file_hash TEXT NOT NULL,          -- 增量更新判断
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- FTS索引（已创建）
CREATE INDEX IF NOT EXISTS idx_chunks_fts
ON knowledge_chunks USING FTS(title, content, keywords);
```

**向量化命令**（已实现）:
```bash
uv run olav knowledge index --incremental
```

**Backend增强方案的集成**:
```python
def _trigger_vectorization(filepath: Path) -> None:
    """Trigger vectorization for saved solution (async)."""
    # ✅ 调用现有命令，写入现有表
    subprocess.Popen(
        ["uv", "run", "olav", "knowledge", "index", "--incremental"],
        cwd=Path.cwd(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
```

**数据流**:
```
.olav/knowledge/solutions/bgp-case.md (file)
  ↓ (uv run olav knowledge index)
UNIFIED_DB.knowledge_chunks (table)
  ↓ (FTS + Vector search)
search_knowledge tool (retrieval)
```

**集成结论**:
- ✅ 表已存在 (`knowledge_chunks`)
- ✅ 索引已创建 (FTS)
- ✅ 命令已实现 (`olav knowledge index`)
- ✅ 只需调用现有命令（零schema变更）

---

### **Phase 3: Long-term Memory (StoreBackend)** ✅ 使用现有USER_CHECKPOINT_PATH

#### 3.1 跨Thread知识共享需求

**场景**: Agent从历史会话学习，跨thread可见

**示例**:
```
# Thread 1: 学习案例
Agent: save_solution("bgp-flapping-r1", ...)

# Thread 2 (新会话): 检索历史案例
Agent: read_file("/memories/learned_patterns/bgp_mtu.txt")
```

#### 3.2 DeepAgents Long-term Memory模式

**DeepAgents官方文档** (`archive/deepagents/README.md:230-250`):
```python
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from langgraph.store.memory import InMemoryStore

agent = create_deep_agent(
    backend=CompositeBackend(
        default=StateBackend(),  # 临时文件（ephemeral）
        routes={
            "/memories/": StoreBackend(store=InMemoryStore())  # 持久化
        }
    )
)
```

**说明**:
- `/memories/` 路径 → StoreBackend
- 使用 LangGraph Store 持久化
- 跨thread共享

#### 3.3 OLAV的StoreBackend集成

**关键发现**: ✅ **OLAV已经在用DuckDBStore！**

**现有使用** (`src/olav/agents/query_agent.py:154`):
```python
# QueryAgent已使用DuckDBStore
self._store_cm = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))
self.store = self._store_cm.__enter__()
```

**DataGateway aliases存储** (`src/olav/lib/data_gateway.py:283`):
```python
# 已使用namespace = (skill_name, "aliases")
store = DuckDBStore(conn)
namespace = ("network-query", "aliases")
store.put(namespace, "核心路由器", {"canonical": "R1,R2,R3"})
```

**Backend增强方案的集成**:
```python
# src/olav/core/storage.py (扩展)
def get_storage_backend(project_root: Path | None = None) -> object:
    """Get the configured storage backend for OLAV."""
    
    # ... existing code ...
    
    # ⭐ NEW: Long-term memory paths
    memory_paths = [
        agent_dir / "memories",      # 跨thread学习模式
        agent_dir / "preferences",   # 用户偏好
    ]
    
    # ⭐ NEW: StoreBackend for long-term memory
    from langgraph.store.duckdb import DuckDBStore
    from config.paths import USER_CHECKPOINT_PATH
    
    # ✅ 复用现有USER_CHECKPOINT_PATH（不需要新数据库）
    memory_store = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))
    memory_backend = StoreBackend(store=memory_store)
    
    # Create composite backend with routing
    composite = CompositeBackend(
        default=temp_backend,  # Ephemeral
        routes={
            **{str(path): persistent_backend for path in persistent_paths},
            **{str(path): memory_backend for path in memory_paths},  # ⭐ NEW
        }
    )
    
    return composite
```

**Namespace设计**:
```python
# 现有namespace
("network-query", "aliases")         → 设备别名
("network-expert", "aliases")        → 专家术语

# ⭐ NEW: Long-term memory namespaces
("network-query", "memories")        → Query agent学到的模式
("network-expert", "memories")       → Expert agent学到的诊断经验
("orchestrator", "preferences")      → 用户偏好设置
```

**数据存储**:
```python
# Agent写入记忆
agent.write_file("/memories/bgp_patterns.txt", "MTU mismatch causes flapping")
  ↓ (CompositeBackend routes to StoreBackend)
DuckDBStore.put(("network-expert", "memories"), "bgp_patterns", {...})
  ↓ (写入到USER_CHECKPOINT_PATH)
~/.olav/checkpoints/{username}.duckdb (store表)
```

**集成结论**:
- ✅ DuckDBStore已在使用
- ✅ USER_CHECKPOINT_PATH已存在
- ✅ namespace机制已验证（aliases在用）
- ✅ 只需添加新namespace（零schema变更）
- ✅ 自动跨thread共享（DuckDBStore特性）

---

### **Phase 4: 审计日志** (可选) ❌ 不需要新数据库

**功能**: 记录文件操作审计日志

**数据库涉及**:
```
方案A: 文件日志 (.olav/logs/filesystem_audit.log)  ← 推荐
方案B: 写入UNIFIED_DB.audit_logs表（已存在）
```

**推荐**: 使用文件日志（简单、独立、易查看）

---

## 📊 数据库集成总结

### **完美集成！零破坏性变更！**

| Backend功能 | 需要的数据库 | OLAV现状 | 集成方式 | 数据库改动 |
|------------|------------|---------|---------|-----------|
| **Phase 1: Backend配置** | ❌ 不需要 | N/A | 代码级（3处） | ❌ 无 |
| **Phase 2.1: Save Solution** | ❌ 不需要 | N/A | 文件写入 | ❌ 无 |
| **Phase 2.2: Git Commit** | ❌ 不需要 | N/A | Git命令 | ❌ 无 |
| **Phase 2.3: Auto Vectorize** | knowledge_chunks | ✅ 已存在 | 调用现有命令 | ❌ 无 |
| **Phase 3: Long-term Memory** | DuckDBStore | ✅ 已在用 | 添加新namespace | ❌ 无 |
| **Phase 4: 审计日志** | 文件日志 | N/A | 文件追加 | ❌ 无 |

### **关键优势**

#### 1. ✅ **零Schema变更**
```
所有需要的表已经存在：
- knowledge_chunks (Phase 2)
- user checkpoint store (Phase 3)
```

#### 2. ✅ **零数据迁移**
```
不需要：
- 创建新数据库
- 迁移历史数据
- 修改现有表结构
```

#### 3. ✅ **完全兼容现有架构**
```
UNIFIED_DB (v0.10.1):
  ├─ devices, raw_outputs (网络数据)
  ├─ audit_logs (命令审计)
  └─ knowledge_chunks (知识库) ← Phase 2使用

USER_CHECKPOINT_PATH (per-user):
  ├─ checkpoints (session state)
  └─ store (aliases + memories) ← Phase 3扩展
```

#### 4. ✅ **渐进式增强**
```
Phase 1 → 无数据库改动
Phase 2 → 调用现有vectorization
Phase 3 → 扩展现有DuckDBStore
Phase 4 → 可选文件日志
```

---

## 🔧 数据库操作详解

### **Phase 2: 向量化流程**

#### 1. 文件写入
```python
# src/olav/core/learning.py
save_solution("bgp-flapping-r1", ...) →
  filepath.write_text(content)  # .olav/knowledge/solutions/bgp-flapping-r1.md
```

#### 2. Git版本控制
```python
_git_commit_solution(filepath) →
  git add .olav/knowledge/solutions/bgp-flapping-r1.md
  git commit -m "chore(knowledge): auto-save solution - bgp-flapping-r1"
```

#### 3. 触发向量化
```python
_trigger_vectorization(filepath) →
  subprocess.Popen(["uv", "run", "olav", "knowledge", "index", "--incremental"])
```

#### 4. 向量化命令执行（现有）
```bash
# .olav/commands/reload-knowledge.py
uv run olav knowledge index --incremental
  ↓
KnowledgeEmbedder.index_documents()
  ↓
for file in .olav/knowledge/solutions/*.md:
    if file_hash changed:
        chunks = split_document(file)
        for chunk in chunks:
            INSERT INTO UNIFIED_DB.knowledge_chunks (
                file_path, title, content, keywords, file_hash
            ) VALUES (...)
```

#### 5. 数据查询（现有）
```python
# src/olav/tools/capabilities.py
search_knowledge.invoke({"query": "BGP flapping", "limit": 5})
  ↓
SELECT * FROM knowledge_chunks
WHERE content MATCH 'BGP flapping'  -- FTS search
ORDER BY rank
LIMIT 5
```

**数据库表状态**:
```sql
-- Before save_solution
SELECT COUNT(*) FROM knowledge_chunks WHERE file_path LIKE '%bgp-flapping-r1.md';
-- Result: 0

-- After vectorization
SELECT COUNT(*) FROM knowledge_chunks WHERE file_path LIKE '%bgp-flapping-r1.md';
-- Result: 3 (假设文档分成3个chunks)
```

---

### **Phase 3: Long-term Memory流程**

#### 1. Agent写入记忆
```python
# Agent通过write_file调用
agent.write_file("/memories/bgp_patterns.txt", "MTU mismatch causes flapping")
  ↓ (CompositeBackend路由)
backend.write("/memories/bgp_patterns.txt", ...)
  ↓ (StoreBackend处理)
store.put(
    namespace=("network-expert", "memories"),
    key="bgp_patterns",
    value={"content": "MTU mismatch causes flapping", "created_at": "2026-02-06"}
)
```

#### 2. 数据库写入（DuckDBStore）
```sql
-- USER_CHECKPOINT_PATH的store表（DuckDBStore自动创建）
INSERT INTO store (
    namespace,    -- ('network-expert', 'memories')
    key,          -- 'bgp_patterns'
    value,        -- JSON: {"content": "...", "created_at": "..."}
    created_at,
    updated_at
) VALUES (
    '["network-expert", "memories"]',
    'bgp_patterns',
    '{"content": "MTU mismatch causes flapping", "created_at": "2026-02-06"}',
    CURRENT_TIMESTAMP,
    CURRENT_TIMESTAMP
);
```

#### 3. 跨Thread读取（新会话）
```python
# Thread 2: 新会话
agent.read_file("/memories/bgp_patterns.txt")
  ↓ (CompositeBackend路由)
backend.read("/memories/bgp_patterns.txt")
  ↓ (StoreBackend处理)
item = store.get(
    namespace=("network-expert", "memories"),
    key="bgp_patterns"
)
return item.value["content"]  # "MTU mismatch causes flapping"
```

#### 4. 数据库查询
```sql
-- USER_CHECKPOINT_PATH
SELECT value FROM store
WHERE namespace = '["network-expert", "memories"]'
  AND key = 'bgp_patterns';

-- Result: {"content": "MTU mismatch causes flapping", "created_at": "2026-02-06"}
```

**跨Thread共享的关键**:
```
所有thread共享同一个 USER_CHECKPOINT_PATH
  ↓
Thread 1 写入 → store表
Thread 2 读取 → 同一个store表
  ↓
实现知识积累（不需要额外数据库）
```

---

## 🎯 数据库使用建议

### **1. UNIFIED_DB (Production)**
```python
# 用途：网络数据 + 知识库（只读为主）
from config.paths import UNIFIED_DB

conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
result = conn.execute("SELECT * FROM knowledge_chunks WHERE ...").fetchall()
conn.close()
```

### **2. USER_CHECKPOINT_PATH (User-Local)**
```python
# 用途：Session state + Aliases + Memories（读写）
from config.paths import USER_CHECKPOINT_PATH
from langgraph.store.duckdb import DuckDBStore

store = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH))

# 写入新namespace
store.put(("network-expert", "memories"), "pattern1", {...})

# 读取
item = store.get(("network-expert", "memories"), "pattern1")
```

### **3. LLM_CACHE_DB (Transparent)**
```python
# 用途：LLM调用缓存（自动管理，无需手动操作）
# 由olav.core.query_cache自动处理
```

---

## ✅ 实施检查清单

### **Phase 1: Backend配置** (无数据库改动)
- [ ] 修改 `create_olav_agent` 添加backend参数
- [ ] 修改 `create_orchestrator` 添加backend参数
- [ ] 修改 `QueryAgent.__init__` 使用get_storage_backend
- [ ] ✅ 验证：文件路由正确（ephemeral vs persistent）

### **Phase 2: Learning工作流** (使用UNIFIED_DB)
- [ ] 增强 `save_solution` 添加auto_commit参数
- [ ] 实现 `_git_commit_solution` 函数
- [ ] 实现 `_trigger_vectorization` 函数
- [ ] ✅ 验证：`SELECT * FROM knowledge_chunks WHERE file_path LIKE '%xxx.md'`

### **Phase 3: Long-term Memory** (扩展USER_CHECKPOINT_PATH)
- [ ] 扩展 `get_storage_backend` 添加memory_paths
- [ ] 配置StoreBackend使用现有USER_CHECKPOINT_PATH
- [ ] 添加新namespace: `("skill", "memories")`
- [ ] ✅ 验证：`SELECT * FROM store WHERE namespace = '["skill", "memories"]'`

### **Phase 4: 审计日志** (可选，文件日志)
- [ ] 实现文件日志追加 `.olav/logs/filesystem_audit.log`
- [ ] 或：复用UNIFIED_DB.audit_logs表
- [ ] ✅ 验证：日志文件存在 or SELECT * FROM audit_logs

---

## 🚀 数据库性能优化建议

### **1. 查询优化（已优化）**
```sql
-- UNIFIED_DB的索引（已创建）
CREATE INDEX idx_chunks_fts ON knowledge_chunks USING FTS(...);
CREATE INDEX idx_chunks_file_path ON knowledge_chunks(file_path);
CREATE INDEX idx_chunks_source ON knowledge_chunks(source_id);
```

### **2. 并发控制（已解决）**
```
策略：Per-User数据库隔离
- UNIFIED_DB: 只读为主（多用户共享）
- USER_CHECKPOINT_PATH: 每用户独立（避免锁）
```

### **3. 向量化性能**
```bash
# 增量模式（推荐）
uv run olav knowledge index --incremental  # 只更新changed files

# 全量模式（重建）
uv run olav knowledge index --reset  # 清空重建
```

---

## 📚 参考文档

### **OLAV数据库文档**
- `config/paths.py` - 数据库路径定义
- `src/olav/core/database.py` - knowledge_chunks表schema
- `src/olav/lib/data_gateway.py` - DuckDBStore使用示例
- `src/olav/agents/query_agent.py` - Checkpointer + Store初始化

### **DeepAgents Backend文档**
- `archive/deepagents/README.md` (lines 200-260) - Backend系统
- Long-term Memory示例 (lines 230-250)

### **LangGraph Store文档**
- DuckDBStore API
- Namespace机制
- 跨thread共享

---

## 🎉 总结

### **数据库集成的完美性**

Backend增强方案可以**完美集成**到OLAV现有数据库架构：

1. ✅ **零Schema变更** - 所有表已存在
2. ✅ **零数据迁移** - 不需要新数据库
3. ✅ **零破坏性影响** - 不修改现有数据
4. ✅ **渐进式增强** - 可分阶段实施
5. ✅ **100%兼容** - 复用现有基础设施

### **推荐实施路径**

```
Week 1: Phase 1 (Backend配置)
  ✅ 无数据库改动
  ✅ 风险：极低
  
Week 2: Phase 2 (Learning工作流)
  ✅ 调用现有vectorization
  ✅ 写入现有knowledge_chunks表
  ✅ 风险：低
  
Week 3: Phase 3 (Long-term Memory)
  ✅ 扩展现有DuckDBStore
  ✅ 添加新namespace
  ✅ 风险：低
```

**数据库视角的Backend增强**：这是一个**零风险的架构优化**，而不是数据库重构项目 🚀
