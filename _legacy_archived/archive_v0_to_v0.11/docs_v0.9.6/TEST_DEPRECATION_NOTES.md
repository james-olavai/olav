# ⚠️ 测试文件弃用说明

> **日期**: 2026-02-02  
> **版本**: v0.10.0  
> **原因**: 缓存系统重构，旧测试不再适用

---

## 🚫 已弃用的测试文件

### 1. tests/unit/test_phase6_fastpath_cache.py

**弃用原因**:
- 测试旧的 `QueryRouter._check_semantic_cache()` 方法
- 该方法已在 v0.10.0 中移除

**失败测试**:
```python
# ❌ DEPRECATED
def test_router_has_cache_check_method(self):
    assert hasattr(router, '_check_semantic_cache')

def test_router_cache_check_returns_decision_or_none(self):
    result = await router._check_semantic_cache(query)
    
def test_router_route_includes_cache_check(self):
    assert 'semantic_cache' in decision.timings
```

**新的等效测试**: 
- 应使用 `tests/performance_cache_benchmark.py`
- 测试 `olav.cache.cache.get_intent()` 和 Guard 功能

**处理方式**:
- [ ] 标记测试为 `@pytest.mark.skip(reason="Deprecated: use new cache system")`
- [ ] 或完全移除该文件

---

### 2. tests/test_fastpath_cache_performance.py

**弃用原因**:
- 期望 QueryRouter 返回 "Cache hit" 消息
- QueryRouter 已不再包含缓存逻辑（移至 IntentAgent）

**失败测试**:
```python
# ❌ DEPRECATED
def test_fastpath_cache_hit_performance(self):
    assert 'Cache hit' in decision.message
    
def test_fastpath_multiple_cache_hits(self):
    assert 'Cache hit' in decision.message
```

**新的等效测试**:
- 应测试 `IntentAgent` 的缓存命中
- 使用 `tests/performance_cache_benchmark.py` 的完整场景

**处理方式**:
- [ ] 标记测试为 `@pytest.mark.skip(reason="Cache moved to IntentAgent")`
- [ ] 或重写为测试 IntentAgent 的缓存功能

---

## ✅ 仍然有效的测试

### 保留测试文件
| 文件 | 状态 | 说明 |
|------|------|------|
| `tests/00_e2e_acceptance_test.py` | ✅ 有效 | E2E 验收测试 |
| `tests/performance_phase1_test.py` | ✅ 有效 | Phase 1 性能测试 |
| `tests/performance_phase2_test.py` | ✅ 有效 | Phase 2 性能测试 |
| `tests/performance_cache_benchmark.py` | ✅ **新增** | 统一缓存性能测试 |

---

## 📝 迁移指南

### 对于开发者

**如果需要测试缓存功能**:
```python
# ❌ OLD (不再适用)
from olav.core.query_router import QueryRouter
router = QueryRouter()
decision = await router._check_semantic_cache(query)

# ✅ NEW (推荐)
from olav.cache import cache

# 测试 Guard
blocked, reason = cache.check_blacklist(query)
rejected, msg = cache.check_rejected(query)

# 测试缓存
cached = cache.get_intent(query, match_mode="exact", confidence_threshold=1.0)
cache.set_intent(query, plan)
```

**如果需要性能基准测试**:
```bash
# ❌ OLD
pytest tests/test_fastpath_cache_performance.py

# ✅ NEW
uv run python tests/performance_cache_benchmark.py
# 生成详细报告: exports/reports/cache_performance_*.md
```

---

## 🔧 修复方案

### 方案 A: 标记为跳过 (快速)

```python
# tests/unit/test_phase6_fastpath_cache.py
import pytest

@pytest.mark.skip(reason="Cache system refactored in v0.10.0")
class TestPhase6RouterCacheIntegration:
    pass

@pytest.mark.skip(reason="Cache system refactored in v0.10.0")
class TestPhase6CachePerformance:
    pass
```

### 方案 B: 完全移除 (推荐)

```bash
# 移动到 archive
mv tests/unit/test_phase6_fastpath_cache.py archive/deprecated_tests/
mv tests/test_fastpath_cache_performance.py archive/deprecated_tests/

# 或直接删除
git rm tests/unit/test_phase6_fastpath_cache.py
git rm tests/test_fastpath_cache_performance.py
```

### 方案 C: 重写测试 (完整)

创建新的测试文件 `tests/unit/test_olav_cache.py`:
```python
import pytest
from olav.cache import cache

class TestOlavCache:
    async def test_exact_mode_match(self):
        query1 = "R1 的 BGP 状态"
        cache.set_intent(query1, {"action": "test"})
        result = cache.get_intent(query1, match_mode="exact", confidence_threshold=1.0)
        assert result is not None
        
    async def test_fuzzy_mode_match(self):
        query1 = "R1 的 BGP 状态"
        cache.set_intent(query1, {"action": "test"})
        query2 = "R1的BGP状态"  # 略有不同
        result = cache.get_intent(query2, match_mode="fuzzy", confidence_threshold=0.85)
        assert result is not None
```

---

## 📊 测试结果状态

### 当前状态 (v0.10.0)
```
✅ 35 passed
❌ 8 failed (全部来自弃用测试)
⏭️ 1 skipped
```

### 预期状态 (修复后)
```
✅ 35 passed
⏭️ 9 skipped (弃用测试)
```

或

```
✅ 35 passed (弃用测试已移除)
```

---

## 🎯 推荐行动

**立即行动** (v0.10.0):
1. 标记 `test_phase6_fastpath_cache.py` 为 `@pytest.mark.skip`
2. 标记 `test_fastpath_cache_performance.py` 为 `@pytest.mark.skip`

**短期计划** (v0.10.1):
1. 移动弃用测试到 `archive/deprecated_tests/`
2. 创建新的 `tests/unit/test_olav_cache.py`

**长期计划** (v0.11.0):
1. 完全删除弃用测试文件
2. 确保新测试覆盖率 > 70%

---

**状态**: ⏳ 待处理  
**优先级**: P2 (中等)  
**影响**: 不影响核心功能，仅测试失败
