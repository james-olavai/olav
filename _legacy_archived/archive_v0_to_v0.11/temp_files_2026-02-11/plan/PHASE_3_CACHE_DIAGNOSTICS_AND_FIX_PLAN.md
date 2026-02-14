# Phase 3: Query Cache 诊断结果和修复计划

**日期**: 2026-02-09  
**状态**: ⚠️ 诊断完成，修复计划制定

---

## 🔍 诊断结果

### 根本原因: Scenario A - Cache存在但未集成

| 项目 | 状态 | 详情 |
|------|------|------|
| Cache 数据库存在 | ✅ | query_result_cache.db (16 KB), semantic_cache.db (1.3 MB) |
| Cache 表创建 | ✅ | query_cache 表存在 |
| Cache 有数据 | ❌ | 0 条记录 (空) |
| Cache 最近写入 | ❌ | 23 小时前最后修改，现已过时 |
| query_database() 集成 | ❌ | 没有缓存调用代码 |
| 缓存导入语句 | ❌ | react_query.py 中缺少 QueryCache 导入 |

### 问题分析

```
┌─────────────────────────────────────┐
│ LLM Query 执行流程                  │
├─────────────────────────────────────┤
│ query_database(sql) called          │
│           ↓                          │
│ DataGateway.query_main(sql)         │
│           ↓                          │
│ duckdb 直接执行 SQL ❌ 无缓存       │
│           ↓                          │
│ 返回结果                             │
│                                      │
│ ⚠️ missing: Cache lookup/write     │
└─────────────────────────────────────┘
```

**关键问题**:
1. query_database() 不检查缓存
2. 查询成功后不将结果写入缓存
3. 重复查询时无法命中缓存
4. 导致所有查询都需要完整的 SQL 执行

---

## 📊 性能影响

| 指标 | 当前 | 有缓存时 | 改进 |
|------|------|---------|------|
| 首次查询 | 30-45s | 30-45s | 0% (无改变) |
| 重复查询 (缓存命中) | 30-45s | < 5s | **89% ⬇️** |
| 平均响应时间 (假设50%命中) | 32s | 17.5s | **45% ⬇️** |

---

## ✅ 修复计划 (Phase 3.1-3.3)

### Phase 3.1: 集成缓存到 query_database() (1-2 小时)

**目标**: 修改 react_query.py，使其在执行前检查缓存，执行后写入缓存

**修改步骤**:

1️⃣ **导入缓存模块**
```python
from olav.core.query_cache import QueryCache

# 全局缓存实例 (单例模式)
_query_cache = None
def get_query_cache() -> QueryCache:
    global _query_cache
    if _query_cache is None:
        _query_cache = QueryCache(db_path=CACHE_DIR / "query_result_cache.db")
    return _query_cache
```

2️⃣ **修改 query_database() 工具**
```python
@tool
def query_database(sql: str, params: list | None = None) -> str:
    """Execute SQL query with caching"""
    try:
        cache = get_query_cache()
        
        # 步骤 1: Check cache
        cache_key = f"{sql}:{json.dumps(params or [])}"
        cached_result = cache.get(cache_key)
        
        if cached_result:
            logger.info(f"✅ Cache HIT: {cache_key[:50]}...")
            return json.dumps(cached_result, indent=2, default=str)
        
        # 步骤 2: Query database if cache miss
        gw = DataGateway(db_path=get_database_path())
        results = gw.query_main(sql, params or [])
        
        # 步骤 3: Write to cache
        cache.put(cache_key, results, ttl_hours=24)
        logger.info(f"💾 Cache WRITE: {len(results)} results")
        
        return json.dumps(results, indent=2, default=str)
        
    except Exception as e:
        # 缓存失败时降级到直接查询
        logger.warning(f"Cache operation failed: {e}")
        # ... existing error handling ...
```

3️⃣ **配置缓存 TTL (生存时间)**
```python
# 在 settings.py 中配置
cache_ttl_hours = 24  # 或从 settings.cache.query_cache_ttl_hours 读取
```

**预期成果**:
- ✅ 每个查询都有 cache_key (SQL + params hash)
- ✅ 缓存命中率大幅提升
- ✅ 日志明确显示缓存状态
- ✅ 修改后首次查询性能无变化 (仍然 30-45s)
- ✅ 重复查询性能从 30-45s → < 5s

---

### Phase 3.2: 多Agent缓存共享 (30 分钟-1 小时)

**目标**: 确保当多个 Agent 执行相同查询时能共享缓存结果

**修改内容**:
```python
# 使用全局缓存实例的单例模式
from threading import Lock

_cache_lock = Lock()
_query_cache = None

def get_query_cache() -> QueryCache:
    global _query_cache
    if _query_cache is None:
        with _cache_lock:  # 线程安全
            if _query_cache is None:
                _query_cache = QueryCache(
                    db_path=CACHE_DIR / "query_result_cache.db",
                    shared_mode=True  # 支持多进程访问
                )
    return _query_cache
```

**预期成果**:
- ✅ 多个 Agent 共享同一个缓存数据库
- ✅ 第一个 Agent 查询结果被第二个 Agent 直接使用
- ✅ 无需多次查询相同数据

---

### Phase 3.3: 缓存性能验证 (30 分钟)

**目标**: 验证缓存修复的性能改进

**验证步骤**:

1️⃣ **运行重复查询测试**
```bash
# 第一次查询 (缓存写入)
uv run olav query "有多少个设备?" 
# Expected: 30-45s

# 立即重复查询 (缓存读取)
uv run olav query "有多少个设备?" 
# Expected: < 5s ⬇️ 80% 改进
```

2️⃣ **检查缓存统计**
```bash
uv run olav ask "show me cache statistics"
# Expected: {"query_cache": {"entries": 1, "hit_rate": 50%}}
```

3️⃣ **多Agent缓存共享测试**
```bash
# 同时运行两个查询
uv run olav query "有多少个接口?" &
sleep 1
uv run olav query "有多少个接口?"
# Expected: 第二个查询从缓存读取 < 5s
```

**成功标准**:
- ✅ 首次查询: 30-45s (无变化)
- ✅ 重复查询: < 5s (缓存命中)
- ✅ 缓存表有数据 (> 0 entries)
- ✅ 缓存命中率 > 50%
- ✅ 日志显示缓存操作

---

## 📊 预期改进

### 单次运行改进
- 首次查询: 32s → 32s (0%, 无改变)
- 重复查询: 32s → 4s (87% ⬇️)
- 混合 (假设50%缓存率): 32s → 18s (44% ⬇️)

### 完整测试套件改进

**假设场景**: L1 测试套件 (10 个查询，其中 3 个重复相同的数据)

| 指标 | 无缓存 | 有缓存 | 改进 |
|------|-------|--------|------|
| 总时间 | 320s | 192s | 40% ⬇️ |
| 平均响应 | 32s | 19.2s | 40% ⬇️ |
| 慢查询数 | 10/10 | 7/10 | 30% |

---

## 🔧 实施检查清单

- [ ] Phase 3.1: 集成缓存到 query_database() (1-2 小时)
  - [ ] 导入 QueryCache 模块
  - [ ] 添加全局缓存实例
  - [ ] 修改 query_database() 添加缓存检查/写入
  - [ ] 添加日志记录缓存操作
  - [ ] 验证 SQL 正确运行

- [ ] Phase 3.2: 多Agent缓存共享 (30 分钟-1 小时)
  - [ ] 实现单例模式
  - [ ] 添加线程安全锁
  - [ ] 配置 shared_mode=True
  - [ ] 测试并发访问

- [ ] Phase 3.3: 性能验证 (30 分钟)
  - [ ] 运行重复查询测试
  - [ ] 验证缓存统计信息
  - [ ] 测试多Agent共享
  - [ ] 生成性能报告

---

## ⏱️ 时间估计

| 阶段 | 时间 | 工作量 |
|------|------|--------|
| Phase 3.1 | 1-2 小时 | 中等 (代码修改 + 测试) |
| Phase 3.2 | 30 分钟-1 小时 | 轻量 (主要是配置) |
| Phase 3.3 | 30 分钟 | 轻量 (验证测试) |
| **总计** | **2-3.5 小时** | **可在今天完成** |

---

## 📋 成功标准 (验收标准)

✅ **功能验收**:
- [ ] query_database() 成功读取缓存
- [ ] query_database() 成功写入缓存  
- [ ] 多个 Agent 共享缓存结果
- [ ] 缓存失败时正确降级

✅ **性能验收**:
- [ ] 首次查询: < 45s
- [ ] 重复查询: < 5s
- [ ] 缓存命中率: > 50%
- [ ] 缓存未导致副作用

✅ **可靠性验收**:
- [ ] 缓存不损害查询准确性
- [ ] 过期缓存被正确清理
- [ ] 没有引入竞态条件
- [ ] 日志清晰记录缓存操作

---

## 📖 参考资源

- 缓存工具: `src/olav/tools/system_tools/cache_tools.py`
- 缓存配置: `config/settings.py` (CacheSettings)
- 缓存测试: 待创建

---

**总体评价**: ✅ 诊断完成，根本原因已识别。修复计划清晰，可在 2-3.5 小时内完成实施。预期性能改进 40-87% (取决于缓存命中率)。
