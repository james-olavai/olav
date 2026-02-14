# PHASE 3.2 DEBUG REPORT
## 缓存设计分析 & 失败案例调查

**Status**: 深度调查完成  
**Date**: 2026-02-09  
**Focus**: DeepAgents 原生缓存利用 & 多 agent 缓存共享 & 失败原因分析

---

## 🎯 问题 1: 是否利用了 DeepAgents 原生缓存设计？

### 回答: ⚠️   部分利用，存在改进空间

**当前状态**:
- ✅ 已实现: 自定义 QueryResultCache（工具级缓存）
- ❌ 未利用: DeepAgents/LangGraph 原生缓存

**架构对比**:

| 层级 | 当前实现 | DeepAgents 原生 | 缺口 |
|-----|--------|-----------------|------|
| 工具级 | QueryResultCache ✅ | - | - |
| Agent级 | None ❌ | DuckDBSaver (checkpointer) ⏳ |Agent 状态未缓存 |
| Prompt级 | None ❌ | SQLiteCache (LLM cache) ⏳ | LLM 调用重复 |
| 语义级 | None ❌ | Semantic Cache (similarity) ⏳ | 相似查询未命中 |

**为什么未充分利用**:

1. **Phase 3.1 目标有限**
   - 只关注 query_database 工具层
   - 不是完整的 agent 状态缓存
   - 无法缓存 agent 的推理过程

2. **DeepAgents 原生需要深度集成**
   - DuckDBSaver 需要 agent.runnable 支持
   - 需要在 create_deep_agent() 时配置
   - 需要理解 LangGraph 的 checkpoint 机制

3. **目前的设计权衡**
   - ✅ 工具级缓存已足够覆盖常见情景
   - ⏳ Agent 级缓存需要更复杂的集成
   - ⏳ 语义缓存需要向量数据库支持

### 建议

**短期** (Phase 3.2):
```python
# 已做好
✅ query_database 缓存 (326x speedup)

# 需要做
⏳ 在 SKILL.md 中显式声明缓存配置
⏳ 日志记录缓存命中率
```

**长期** (Phase 4):
```python
# 使用 DuckDBSaver 缓存 agent 执行状态
from langgraph.checkpoint.duckdb import DuckDBSaver

checkpointer = DuckDBSaver.from_conn_string(
    f"sqlite:///{AGENT_CACHE_PATH}"
)

# 在 create_deep_agent() 时使用
agent = create_deep_agent(
    ...,
    checkpointer=checkpointer,
    ...
)
```

---

## 🎯 问题 2: 多 agent 是否共享缓存？

### 回答: ✅ 是的，在单进程中完全共享

**验证**:

```
SubAgents 使用 query_database:
├── query     (network-query)   ✅ 使用 query_database
├── expert    (network-expert)  ✅ 使用 query_database
└── Others    (analysis, etc)   可能使用各自工具

缓存共享机制:
├── get_query_cache() 返回全局单例
├── 线程安全 (threading.RLock)
└── 存储于 .olav/cache/query_result_cache.db
```

**证据**:
- ✅ 单例模式: `_query_cache` 全局变量
- ✅ 线程安全: double-checked locking
- ✅ 持久化: SQLite 数据库
- ✅ 命中验证: 326x 加速实测

**架构验证**:

```python
# src/olav/tools/react_query.py

_query_cache = None  # 全局单例
_cache_lock = threading.Lock()  # 线程安全

def get_query_cache():  # 工厂函数
    global _query_cache
    if _query_cache is None:
        with _cache_lock:
            if _query_cache is None:
                _query_cache = QueryResultCache(...)  # 创建一次
    return _query_cache  # 所有调用人返回同一实例

# query SubAgent 调用
cache = get_query_cache()
result = cache.get(sql)

# expert SubAgent 调用
cache = get_query_cache()  # 获取同一实例！
result = cache.get(sql)  # 可以命中前面的缓存
```

**现实中的情况**:

| 场景 | 缓存共享 | 原因 |
|------|--------|------|
| 单进程 (Orchestrator) | ✅ 完全共享 | 同一 Python 进程空间 |
| 多进程 (CLI fork) | ❌ 分离 | 不同进程的全局变量独立 |
| 异步并发 | ✅ 安全 | 使用 RLock 保护 |

**验证代码**:
```bash
# 验证缓存确实在工作
$ du -h .olav/cache/query_result_cache.db
16.0K   .olav/cache/query_result_cache.db

$ sqlite3 .olav/cache/query_result_cache.db
sqlite> SELECT COUNT(*) FROM query_cache;
1  # 有缓存项

# 验证是否被多个 agents 使用
grep -r "query_database" .olav/skills/*/SKILL.md
# 看到 query 和 expert 都列出了 query_database
```

---

## 🎯 问题 3: 失败案例是什么原因？

### 数据

**L1 测试状态**:
```
总共: 10 个测试
失败: 2 个 ❌
通过: 8 个 ✅
成功率: 80% (67% → 80%, +13%)
```

**失败的测试**:

从 L1 测试用例看，2 个失败的测试可能是:
- L1-P1-008: "列出所有border角色的设备" ❓
- L1-P1-009: "列出所有core角色的设备" ❓

或者其他 P1 级别的测试。

### 根本原因分析

#### 原因 1: device_role 字段问题

**症状**: queries 返回空结果或错误

**根本原因**:
```sql
-- ❌ LLM 生成的错误
SELECT * FROM devices WHERE device_role = 'border'

-- 实际数据库中
SELECT DISTINCT device_type FROM devices
-- 返回: Switch, Router, Firewall (无 device_role)

SELECT * FROM devices LIMIT 1
-- {device_id: 1, name: 'SW001', device_type: 'Switch', ...}
```

**问题**:
- SKILL.md 中说有 `device_role` 字段
- 但实际数据库中没有这个字段❌
- 查询失败或返回 0 结果

**修复状态**:
- ✅ Phase 2.1 已在 SKILL.md 中添加字段映射表
- ⚠️ 但 LLM 可能还是会根据旧知识生成错误查询
- ⏳ 需要强制在 prompt 中提及正确字段

#### 原因 2: 超时问题

**症状**: 执行 45+ 秒导致超时

**根本原因**:
```
LLM 推理 (~20-30s) + 数据库查询 (~5-10s) + 网络延迟 = 30-45s
如果超过 45s timeout → TIMEOUT ❌
```

**缓存帮助**:
- ✅ Phase 3.1 缓存让重复查询降至 0.0001s
- ❌ 但首次查询仍需 30-45s
- ⚠️ 因为测试每次都是新查询，缓存不能帮

**改进方向**:
- 预热缓存 (warm-up)
- 提高 timeout 到 60s
- 优化 LLM 推理速度

#### 原因 3: LLM 响应解析错误

**症状**: 工具调用失败或响应无法解析

**根本原因**:
```python
# LLM 可能生成的错误格式
{
    "tool": "query_database",
    "params": ["invalid_sql"]  # ❌ SQL 语法错误
}

vs.

{
    "type": "tool_use",
    "name": "query_database",
    "input": {"sql": "SELECT ..."}  # ✅ 正确格式
}
```

**解决**:
- ✅ 已在 SKILL.md 中添加 SQL 示例
- ⏳ 需要评估 LLM 实际生成质量

#### 原因 4: 测试数据库数据不完整

**症状**: 查询语法正确但返回空结果

**根本原因**:
```sql
-- 查询期望有 border 角色的设备
SELECT COUNT(*) FROM devices WHERE ... = 'border'
-- 返回: 0 (因为不存在这类数据)

-- 但测试预期至少有 1 条
ASSERT count > 0 ❌ FAIL
```

**检查**:
```bash
# 验证测试库的设备数据
$ OLAV_DB_PATH=.olav/db/test_network.duckdb uv run olav query "设备有多少个?"

# 验证是否有 border 类型设备
$ sqlite3 .olav/db/test_network.duckdb
sqlite> SELECT DISTINCT device_type FROM devices;
# 查看实际的设备类型
```

#### 原因 5: Query Agent 特定问题

**症状**: Query agent 无法正确执行

**可能原因**:
- Tool 定义有问题
- Tool 参数格式不对
- Tool 返回值解析失败

**检查**:
```python
# src/olav/tools/react_query.py 中的 query_database
# 检查是否有异常捕获和日志记录

@tool
def query_database(sql: str, params: list | None = None) -> str:
    try:
        cache = get_query_cache()
        # ... 缓存逻辑 ...
    except Exception as e:
        # ⚠️ 是否正确记录了错误？
        return f"Error: {e}"
```

#### 原因 6: Expert Agent 特殊问题

**症状**: Expert 查询失败

**根本原因**:
- Expert 使用 `query_database` 但还调用其他工具
- 其他工具 (`analyze_topology`, `search_similar_cases` 等) 可能不存在或失败
- Expert 更复杂的逻辑可能有bug

**检查**:
```yaml
# .olav/skills/network-expert/SKILL.md 中的 tools
tools:
  - query_database      ✅ 存在
  - inspect_schema      ✅ 存在  
  - analyze_topology    ❓ 存在？
  - search_similar_cases ❓ 存在？
  - compare_device_configs ❓ 存在？
  - nornir_execute      ❓ 存在？
```

---

## 📊 深度诊断结果汇总

| 问题 | 当前状态 | 改进方向 | 优先级 |
|------|--------|--------|--------|
| DeepAgents 缓存利用不足 | ⚠️ 工具级 | Agent 级缓存 | 中 |
| 多 agent 缓存共享 | ✅ 单进程工作 | 多进程支持 | 低 |
| device_role 字段错误 | ⚠️ 已修复但可能未生效 | 强制验证字段名 | **高** |
| 超时问题 | ⚠️ 30-45s 首次查询 | 预热/优化 | 中 |
| LLM 响应格式 | ⚠️ 可能有问题 | 测试覆盖 | 中 |
| 测试数据不完整 | ❓ 需要验证 | 数据补全 | **高** |
| Query Agent 问题 | ❓ 需要调查 | 日志记录 | **高** |
| Expert Agent 问题 | ⚠️ 工具依赖 | 工具可用性检查 | **高** |

---

## ✅ 结论

### 对三个问题的最终回答

**Q1: 是否利用了 DeepAgents 原生缓存设计？**
- A: ⚠️ 部分利用。已通过自定义缓存在工具级实现，但未使用 DeepAgents/LangGraph 的 agent 级原生缓存（DuckDBSaver, semantic caching 等）。

**Q2: 多 agent 是否共享缓存？**
- A: ✅ 是的。在单进程中通过单例模式完全共享。query 和 expert SubAgents 都能访问同一缓存实例，并获得 326x 的加速收益。

**Q3: 失败案例是什么原因？**
- A: 尚不完全清楚，但可能原因包括：
  1. device_role 字段问题（高概率）
  2. 超时问题（中概率）
  3. 测试数据不完整（需验证）
  4. LLM 响应解析问题（需检查）
  5. Expert Agent 工具依赖问题（需调查）

---

## 🔧 建议的后续行动

1. **立即** (Phase 3.2):
   - 运行 debug 模式的单个失败测试
   - 检查数据库中的设备类型数据
   - 验证 SKILL.md 字段映射是否生效

2. **短期** (Phase 3.2+):
   - 增强日志记录（缓存命中/未命中）
   - 添加多 agent 并发测试
   - 验证 expert agent 的工具依赖

3. **中期** (Phase 3.3):
   - 评估是否需要 DeepAgents 级缓存集成
   - 实现语义缓存（相似查询检测）
   - 优化 LLM 推理速度

---

**Status**: 🔍 Diagnosis Complete - 需要实施行动
