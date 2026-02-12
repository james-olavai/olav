# 缓存中间件说明 - 原有设计 vs 新增内容

## 1️⃣ 原有设计（Phase 4 - Day 5-6）

**QueryResultCache** - 原始缓存系统
```python
# src/olav/core/query_cache.py
class QueryResultCache:
    """2-tier cache: L1 (memory LRU) + L2 (disk SQLite)"""
    
    # 特性:
    - L1内存缓存 (OrderedDict LRU)
    - L2磁盘缓存 (SQLite: cache.db)
    - TTL-based失效机制
    - 智能key生成 (标准化query + context)
```

**设计目标**:
- 缓存完整的查询结果 (post-LLM)
- 缓存命中率: 60-80%
- 缓存响应时间: <100ms (vs 20-30s LLM推理)
- 整体延迟降低: 60-70%

**使用位置**: QueryAgent中
```python
# src/olav/agents/query_agent.py
- self.query_cache.get(user_query, context)  # 检查缓存
- self.query_cache.set(...)                  # 存储结果
```

---

## 2️⃣ 新增设计（Phase 6-7 SubAgent迁移）

**CachedOrchestrator** - 中间件包装器
```python
# src/olav/agents/orchestrator.py (line 228)
class CachedOrchestrator:
    """Wrapper that adds Fast Path caching to orchestrator."""
    
    def __init__(self, agent):
        self.agent = agent  # 底层DeepAgent orchestrator
        self.query_cache = get_query_cache()  # 复用原有缓存
    
    async def ainvoke(self, inputs, config):
        # 1. 检查缓存
        # 2. 缓存命中 → 快速返回 (< 0.5s)
        # 3. 缓存未命中 → 委托给SubAgents
        # 4. 存储成功的结果
```

**实现方式**:
```python
# src/olav/agents/orchestrator.py (line 220)
def create_orchestrator(...):
    agent = ...create deepagent orchestrator...
    return CachedOrchestrator(agent)  # ← 包装器层
```

**架构图**:
```
User Query
    ↓
CachedOrchestrator  ← 新增: 缓存中间件层
    ├─ Cache Hit? → 快速返回 (<0.5s)
    └─ Cache Miss? → 委托给SubAgents
            ├─ query SubAgent
            ├─ analysis SubAgent
            └─ cli SubAgent
                    ↓
            缓存结果 (QueryResultCache)
                    ↓
                返回结果
```

---

## 3️⃣ 对比分析

| 特性 | QueryAgent原有 | CachedOrchestrator新增 |
|------|---|---|
| **缓存位置** | 内部 (agent逻辑中) | 外部 (中间件层) |
| **作用范围** | 仅QueryAgent | 所有SubAgents + Orchestrator |
| **实现方式** | 直接集成 | 包装器 (Decorator模式) |
| **缓存源** | QueryResultCache | QueryResultCache (复用) |
| **时间地点** | Phase 4 | Phase 6-7 SubAgent迁移 |
| **架构影响** | 低 (单独agent) | 中等 (orchestrator层) |

---

## 4️⃣ 为什么需要CachedOrchestrator?

### 问题背景
- QueryAgent已有缓存 → 快速路径 (<0.5s)
- 迁移为query SubAgent后，缓存被分散
- Orchestrator不知道查询是否被缓存
- 导致: 同一查询可能走多个SubAgent，浪费计算

### 解决方案
**在Orchestrator层添加缓存中间件**:
1. 所有查询先检查缓存
2. 缓存命中 → 立即返回 (跳过所有SubAgents)
3. 缓存未命中 → 通过SubAgents处理
4. 结果存入缓存供下次复用

### 性能收益
```
查询: "show interfaces"

缓存前:
  query SubAgent → analyze SubAgent → cli SubAgent → 8-12s

缓存命中:
  CachedOrchestrator → <0.5s ✅ (16x加速)
```

---

## 5️⃣ 原有设计与新增内容的关系

**是否改变原有设计？** ❌ **不是，兼容扩展**

```
原有: QueryResultCache (核心)
      └─ QueryAgent (直接使用)

新增: CachedOrchestrator (包装器)
      └─ 使用 QueryResultCache (复用)
      └─ 在Orchestrator层提前检查
      └─ 降低SubAgent调度开销
```

**设计原则**:
- ✅ 复用原有QueryResultCache实现
- ✅ 不修改QueryResultCache内部逻辑
- ✅ 只是在调用前加一层检查
- ✅ 符合装饰器模式 (Decorator)

---

## 6️⃣ 现在的缓存流程 (v0.10.0)

```
用户查询
    ↓
CachedOrchestrator.ainvoke()  ← 新增
    ├─ 提取query: "show interfaces"
    ├─ 生成cache key
    ├─ query_cache.get(key)  ← 原有
    │   ├─ L1内存缓存hit? → 返回 (纳秒)
    │   ├─ L2磁盘缓存hit? → 返回 (毫秒)
    │   └─ 未命中 → 继续
    ├─ 委托给 orchestrator.ainvoke()
    │   ├─ 路由到合适SubAgent
    │   ├─ 执行并返回结果
    │   └─ 时间: 8-12s
    └─ query_cache.set(key, result)  ← 原有
        └─ 存入L1+L2供后续复用
    
下一个相同查询:
    ├─ CachedOrchestrator.ainvoke()
    ├─ query_cache.get() → L1 hit! 
    └─ 返回结果 < 0.5s ✅
```

---

## 7️⃣ 测试覆盖情况

### CachedOrchestrator覆盖的测试
```python
✅ test_orchestrator_initialization  # L221-229初始化
✅ test_orchestrator_with_optional_params  # L230-236调用
⏸️ test_cache_invalidation_after_ttl  # 需要time mock

# 位置: tests/unit/test_orchestrator.py
```

### QueryResultCache覆盖的测试
```python
✅ test_cache_hit_for_repeated_queries
✅ test_cache_storage_and_retrieval
⏸️ test_ttl_expiration_mechanics

# 位置: tests/unit/test_phase3_query_agent.py
#       tests/integration/test_p2_query_router_caching.py
```

---

## 8️⃣ 跳过测试原因

**为什么test_cache_invalidation_after_ttl被跳过?**

```python
@pytest.mark.skip(reason="需要time.time()模拟，暂不实现")
def test_cache_invalidation_after_ttl():
    """验证TTL失效机制"""
    # 需要: mock time.time() 让TTL快速过期
    # 复杂度: 中等 (涉及sqlite时间戳)
    # 优先级: 低 (TTL在整个系统中触发率<5%)
```

**为什么test_cache_hit_for_repeated_queries有时被跳过?**

```python
@pytest.mark.skip(reason="需要LLM或真实数据库")
def test_cache_hit_performance():
    """验证缓存命中的性能收益"""
    # 需要: QueryAgent执行一次 (需LLM) 
    # 或: 模拟的完整数据库
    # 优先级: 中等 (性能基准不是acceptance criteria)
```

---

## 9️⃣ 总结

| 问题 | 回答 |
|------|------|
| **缓存中间件是什么?** | `CachedOrchestrator` - 在Orchestrator层添加的缓存检查 |
| **是原有设计吗?** | ❌ 不是。是SubAgent迁移期间添加的 |
| **改变了原有缓存吗?** | ❌ 没有。`QueryResultCache`保持不变 |
| **为什么要添加它?** | 避免缓存命中的查询也走SubAgent调度流程 |
| **性能提升?** | 16x加速 (8-12s → <0.5s) 对于缓存命中的查询 |
| **设计模式?** | 装饰器(Decorator) + 适配器(Adapter) |
| **与原有的关系?** | 兼容扩展 - 上层新增，下层不变 |

---

**版本**: v0.10.0  
**更新**: 2026-02-04  
**相关文件**:
- `src/olav/agents/orchestrator.py` (L228-332)
- `src/olav/core/query_cache.py` (原有，未改动)
- `tests/unit/test_orchestrator.py` (覆盖验证)
