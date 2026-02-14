# OLAV v0.10 性能优化指南

**日期**: 2026-02-02  
**基线**: E2E 测试结果 (14/17 通过)  
**目标**: 将 Query 冷启动从 9.2s 优化到 3.0s

---

## 📊 当前性能分析

### 查询执行时间分解

```
基础查询 (List all devices):
  ├─ LLM 初始化: ~4s
  ├─ 路由规则加载: ~0.5s
  ├─ SQL 生成: ~2s
  ├─ 数据库查询: ~0.2s
  └─ 响应格式化: ~1.5s
  = 总耗时: 9.24s

设备查询 (Show R1 interfaces):
  ├─ 同上初始化: ~4s
  ├─ 设备参数解析: ~1s
  ├─ SQL 生成 (复杂): ~5s
  ├─ 数据库查询: ~3s
  └─ 响应格式化: ~2.8s
  = 总耗时: 16.80s

多设备中文查询:
  ├─ 同上初始化: ~4s
  ├─ 中文 NER: ~2s
  ├─ 多设备规划: ~6s
  ├─ 并行查询: ~8s
  └─ 结果聚合: ~5.58s
  = 总耗时: 25.58s
```

### 关键优化机会

| 阶段 | 当前 | 潜力 | 优化方式 |
|------|------|------|---------|
| LLM 初始化 | 4.0s | 1.5s | 连接池复用 |
| 路由加载 | 0.5s | 0.1s | 内存缓存 |
| SQL 生成 | 2.0s | 0.8s | 计划缓存 |
| 数据库 | 0.2s | 0.1s | 查询优化 |
| 响应格式 | 1.5s | 0.5s | 流式输出 |
| **总计** | **9.24s** | **3.0s** | **67% 减少** |

---

## 🔧 优化实施方案

### 优化 1: LLM 连接池复用 (预期减少 2.5s)

**问题**: 每个查询都创建新的 OpenRouter 连接

**现状代码** (`src/olav/agents/query_agent_v2.py`):
```python
# 每次 ainvoke 都创建新的 LLM 客户端
llm = ChatOpenAI(
    model=model_name,
    temperature=0.3,
    api_key=api_key
)
```

**优化方案**:
```python
# 1. 在 QueryAgentV2 初始化时创建单例 LLM
class QueryAgentV2:
    _llm_instance = None
    
    def __init__(self):
        if QueryAgentV2._llm_instance is None:
            QueryAgentV2._llm_instance = ChatOpenAI(
                model=self.model_name,
                temperature=0.3,
                api_key=self.api_key,
                # 添加连接池配置
                max_retries=2,
                timeout=10.0
            )
        self.llm = QueryAgentV2._llm_instance

# 2. 支持异步连接复用
async def _get_llm(self):
    # 返回持久化的 LLM 实例
    return self._llm_instance
```

**实施步骤**:
1. 修改 `QueryAgentV2.__init__()` 添加 LLM 缓存
2. 更新 `ainvoke()` 使用缓存的 LLM
3. 添加连接生命周期管理 (清理/恢复)

**验证**:
```bash
# 执行重复查询测试
time uv run python -c "
from src.olav.agents.query_agent_v2 import QueryAgentV2
import asyncio

async def test():
    agent = QueryAgentV2()
    # 第一个查询 (包括初始化)
    r1 = await agent.query('List all devices')
    # 第二个查询 (应该更快)
    r2 = await agent.query('List all devices')
    print(f'Query 1: {len(r1)} chars')
    print(f'Query 2: {len(r2)} chars')
    
asyncio.run(test())
"
# 预期: Query 2 快 3-5倍
```

---

### 优化 2: 路由规则内存缓存 (预期减少 0.4s)

**问题**: 每个查询都从磁盘重新加载路由规则

**现状代码** (`src/olav/routing/router.py`):
```python
def load_routing_rules(self):
    with open(ROUTING_RULES_PATH, 'r') as f:
        rules = yaml.safe_load(f)
    return rules
```

**优化方案**:
```python
class QueryRouter:
    _rules_cache = None
    _cache_time = None
    
    @staticmethod
    def load_routing_rules():
        import time
        current_time = time.time()
        
        # 如果缓存存在且小于 1 小时，直接返回
        if (QueryRouter._rules_cache and 
            current_time - QueryRouter._cache_time < 3600):
            return QueryRouter._rules_cache
        
        # 从磁盘加载并缓存
        with open(ROUTING_RULES_PATH, 'r') as f:
            QueryRouter._rules_cache = yaml.safe_load(f)
            QueryRouter._cache_time = current_time
        
        return QueryRouter._rules_cache
```

**验证**:
```bash
# 执行多个查询，第二次应该使用缓存
uv run python tests/00_e2e_production_test.py --stage 4
```

---

### 优化 3: SQL 计划缓存 (预期减少 1.2s)

**问题**: LLM 每次都生成新的 SQL，即使是相同的查询类型

**实施方案**:
```python
# src/olav/sql/plan_cache.py (新文件)
from functools import lru_cache
import hashlib

class SQLPlanCache:
    @staticmethod
    @lru_cache(maxsize=100)
    def get_plan_hash(query_normalized: str) -> str:
        """生成查询的规范化哈希值"""
        return hashlib.md5(query_normalized.encode()).hexdigest()
    
    @staticmethod
    def get_cached_plan(query: str, max_age_seconds: int = 3600):
        """从缓存获取执行计划"""
        query_hash = SQLPlanCache.get_plan_hash(query)
        cache_key = f"sql_plan_{query_hash}"
        
        # 从 Redis/内存缓存获取
        cached_plan = CACHE.get(cache_key)
        if cached_plan:
            return cached_plan
        return None
    
    @staticmethod
    def cache_plan(query: str, plan: str):
        """缓存新的执行计划"""
        query_hash = SQLPlanCache.get_plan_hash(query)
        cache_key = f"sql_plan_{query_hash}"
        CACHE.set(cache_key, plan, ttl=3600)
```

**集成到 QueryAgentV2**:
```python
async def execute(self, query: str):
    # 1. 检查缓存的执行计划
    cached_plan = SQLPlanCache.get_cached_plan(query)
    if cached_plan:
        # 直接使用缓存的计划
        results = self.db.execute(cached_plan)
        return results
    
    # 2. 生成新的执行计划
    plan = await self.llm.generate_sql_plan(query)
    
    # 3. 缓存该计划
    SQLPlanCache.cache_plan(query, plan)
    
    # 4. 执行
    results = self.db.execute(plan)
    return results
```

---

### 优化 4: 响应流式输出 (预期减少 0.5s)

**问题**: 等待完整响应后才输出，导致用户感知延迟

**方案**: 实现流式响应

```python
# src/olav/agents/streaming_agent.py (新文件)
from typing import AsyncIterator

class StreamingQueryAgent:
    async def stream_query(self, query: str) -> AsyncIterator[str]:
        """流式返回查询结果"""
        # 1. 快速响应初始确认
        yield f"🔄 Processing query: {query[:50]}...\n"
        
        # 2. 流式返回中间结果
        async for chunk in self.llm.stream_response(query):
            yield chunk
        
        # 3. 最后返回完整结果
        results = await self.execute_query(query)
        yield f"\n✅ Results:\n{results}"
```

**CLI 集成**:
```python
async def cli_main():
    agent = StreamingQueryAgent()
    async for output in agent.stream_query(user_input):
        print(output, end='', flush=True)
```

---

## 🚀 性能优化路线图

### Phase 1: 快速胜利 (本周)
- [ ] 优化 1: LLM 连接池 (预期: -2.5s)
- [ ] 优化 2: 路由缓存 (预期: -0.4s)
- **小计**: -2.9s (从 9.2s → 6.3s)

### Phase 2: 中等努力 (下周)
- [ ] 优化 3: SQL 计划缓存 (预期: -1.2s)
- [ ] 优化 4: 响应流式输出 (预期: -0.5s)
- **小计**: -1.7s (从 6.3s → 4.6s)

### Phase 3: 深度优化 (2周后)
- [ ] 数据库查询优化 (预期: -0.6s)
- [ ] 中文 NER 加速 (预期: -0.8s)
- **小计**: -1.4s (从 4.6s → 3.2s)

**最终目标**: 3.0s ✅

---

## 📈 预期结果

### 优化前后对比

```
优化前:
  ├─ 基础查询: 9.24s
  ├─ 设备查询: 16.80s
  └─ 中文查询: 25.58s
  = 平均: 17.2s

优化后 (目标):
  ├─ 基础查询: 3.0s (-67%)
  ├─ 设备查询: 5.2s (-69%)
  └─ 中文查询: 8.6s (-66%)
  = 平均: 5.6s (-67%)
```

### 用户体验改进

| 场景 | 当前 | 优化后 | 感知 |
|------|------|--------|------|
| CLI 响应 | 9.2s | 3.0s | "立即" |
| 报告生成 | 25.6s | 8.6s | "流畅" |
| 批量查询 | 100+s | 30s | "实用" |

---

## 🔍 监控和验证

### 性能指标收集

```python
# src/olav/monitoring/performance.py (新文件)
import time
from dataclasses import dataclass

@dataclass
class PerformanceMetric:
    stage: str
    duration: float
    timestamp: str
    memory_mb: float
    
class PerformanceMonitor:
    def __init__(self):
        self.metrics = []
    
    def record(self, stage: str, duration: float):
        import psutil
        import datetime
        
        metric = PerformanceMetric(
            stage=stage,
            duration=duration,
            timestamp=datetime.datetime.now().isoformat(),
            memory_mb=psutil.Process().memory_info().rss / 1024 / 1024
        )
        self.metrics.append(metric)
    
    def export_report(self, filename: str):
        import json
        with open(filename, 'w') as f:
            json.dump(
                [asdict(m) for m in self.metrics],
                f,
                indent=2
            )
```

### 验证脚本

```bash
#!/bin/bash
# scripts/perf_benchmark.sh

echo "🚀 OLAV Performance Benchmark"
echo "================================"

# 基准查询
echo "Running 10 iterations of basic query..."
for i in {1..10}; do
    time uv run python -c "
        from src.olav.agents.query_agent_v2 import QueryAgentV2
        import asyncio
        
        async def test():
            agent = QueryAgentV2()
            await agent.query('List all devices')
        
        asyncio.run(test())
    " 2>&1 | grep real
done

echo ""
echo "✅ Benchmark complete. Check logs for detailed results."
```

---

## 📋 实施检查清单

- [ ] **Phase 1** (本周)
  - [ ] 1.1 修改 QueryAgentV2 添加 LLM 单例
  - [ ] 1.2 测试 LLM 连接池复用
  - [ ] 1.3 实现路由规则缓存
  - [ ] 1.4 验证性能提升 (目标: 6.3s)

- [ ] **Phase 2** (下周)
  - [ ] 2.1 创建 SQL 计划缓存模块
  - [ ] 2.2 集成缓存到 QueryAgentV2
  - [ ] 2.3 实现流式响应
  - [ ] 2.4 验证性能提升 (目标: 4.6s)

- [ ] **Phase 3** (2周后)
  - [ ] 3.1 数据库查询优化 (索引)
  - [ ] 3.2 中文 NER 加速
  - [ ] 3.3 最终验收测试
  - [ ] 3.4 生产部署 (目标: 3.0s)

- [ ] **监控和文档**
  - [ ] 创建性能监控工具
  - [ ] 生成性能基准报告
  - [ ] 更新文档
  - [ ] 团队培训

---

## 🎯 关键指标

| 指标 | 当前 | 目标 | 进度 |
|------|------|------|------|
| P95 延迟 | 25.6s | 5.0s | 📊 20% |
| 缓存命中率 | 0% | 80% | 📊 0% |
| 吞吐量 (QPS) | 3-5 | 10-20 | 📊 30% |
| 用户满意度 | 60% | 95% | 📊 待测 |

---

**版本**: 1.0  
**作者**: OLAV Development Team  
**最后更新**: 2026-02-02
