# TDD方案修正说明

## 🎯 核心问题

**之前的错误理解**:
- 计划添加新功能: 安全SubAgent、性能SubAgent、缓存中间件、限流器等
- 总计44个测试用例，768行测试代码
- 偏离了实际需求

**正确的理解**:
- 目标: 将现有独立Agent迁移为orchestrator的SubAgent声明
- 重点: 统一架构，而非添加新功能
- 符合OLAV开发指南原则

---

## 📊 对比分析

### 错误方案 (已删除)
```
tests/unit/test_security_tools.py         (92行)  ❌ 新功能
tests/unit/test_cache_middleware.py      (117行)  ❌ 新功能  
tests/unit/test_rate_limiter.py          (159行)  ❌ 新功能
tests/e2e/test_subagent_routing.py       (163行)  ❌ 新功能
tests/e2e/test_performance_benchmark.py  (237行)  ❌ 新功能
────────────────────────────────────────────────
总计: 5个文件, 768行代码                          ❌ 全部删除
```

### 正确方案 (已创建)
```
tests/unit/test_query_subagent_migration.py    (133行)  ✅ Agent迁移
tests/unit/test_analyzer_subagent_migration.py (113行)  ✅ Agent迁移
tests/unit/test_coder_subagent_migration.py    (105行)  ✅ Agent迁移
────────────────────────────────────────────────────────
总计: 3个文件, 351行代码                              ✅ 正确方向
```

---

## 🔍 迁移目标

### 现有独立Agent (待迁移)
| 文件 | 行数 | 核心能力 | 目标SubAgent |
|------|------|---------|-------------|
| query_agent_v2.py | 730 | IntentAgent + Cache + Skill | `query` |
| analyzer.py | 651 | DB+CLI验证 + 根因分析 | `analysis` |
| coder.py | 570 | TextFSM生成 (状态机) | `template_generator` |
| **总计** | **1951** | - | **3个SubAgent** |

### orchestrator当前SubAgent (基础版)
```python
# src/olav/agents/orchestrator.py

SubAgent(name="database", ...)   # 基础DB查询
SubAgent(name="cli", ...)        # 基础CLI执行
SubAgent(name="analysis", ...)   # 基础分析
```

**问题**: orchestrator的SubAgent是基础版，独立Agent功能更强大但未集成

**目标**: 将独立Agent的能力声明到orchestrator的SubAgent配置中

---

## 🎓 TDD流程 (修正后)

### Phase 1.1: 迁移QueryAgentV2 → query SubAgent

#### RED: 测试先行
```python
# tests/unit/test_query_subagent_migration.py

@pytest.mark.asyncio
async def test_fast_path_for_simple_queries():
    """测试query SubAgent具有Fast Path能力"""
    orchestrator = create_orchestrator()
    
    start = time.time()
    result = await orchestrator.ainvoke({
        "messages": [HumanMessage(content="列出所有设备")]
    })
    duration = time.time() - start
    
    # 验收标准: 简单查询应<1秒 (Fast Path)
    assert duration < 1.0
```

运行测试:
```bash
uv run pytest tests/unit/test_query_subagent_migration.py -v
# ❌ 当前失败: API key未配置 (RED状态正确)
```

---

#### GREEN: 最小实现

**Step 1: 提取IntentAgent为中间件**
```python
# src/olav/middleware/intent_detection.py

class IntentDetectionMiddleware:
    """从QueryAgentV2提取的意图检测中间件"""
    
    def __init__(self, intent_agent: IntentAgent):
        self.intent_agent = intent_agent
    
    async def __call__(self, state, config):
        query = state["messages"][-1].content
        intent = await self.intent_agent.detect_intent(query)
        
        if intent["is_simple"]:
            # Fast Path: 直接SQL查询
            result = await self._fast_query(intent["sql"])
            return {"messages": [AIMessage(content=result)]}
        
        return state  # 复杂查询走ReAct
```

**Step 2: 增强orchestrator的query SubAgent**
```python
# src/olav/agents/orchestrator.py

from olav.middleware.intent_detection import IntentDetectionMiddleware
from olav.agents.query_agent_v2 import QueryAgentV2

def create_orchestrator():
    # 复用QueryAgentV2的组件
    query_agent = QueryAgentV2(skill_name="network-query")
    intent_middleware = IntentDetectionMiddleware(query_agent.intent_agent)
    
    subagents = [
        SubAgent(
            name="query",
            description="Network query with Fast Path and caching",
            tools=query_agent._create_tools(),
        ),
        # ... 其他SubAgents ...
    ]
    
    return create_deep_agent(
        model="gpt-4o",
        subagents=subagents,
        middleware=[intent_middleware, ...],  # 添加意图检测
    )
```

运行测试:
```bash
uv run pytest tests/unit/test_query_subagent_migration.py::test_fast_path_for_simple_queries -v
# ✅ 应该通过
```

---

#### REFACTOR: 优化代码

**Step 3: 标记QueryAgentV2为deprecated**
```python
# src/olav/agents/query_agent_v2.py

import warnings

class QueryAgentV2:
    def __init__(self, ...):
        warnings.warn(
            "QueryAgentV2 is deprecated. Use orchestrator's query SubAgent instead.",
            DeprecationWarning,
            stacklevel=2
        )
        # ... 现有代码 ...
```

**Step 4: 提取通用组件**
```python
# 将QueryAgentV2的组件移动到可复用位置
src/olav/middleware/intent_detection.py  ✅ 意图检测
src/olav/middleware/query_cache.py       ✅ 查询缓存
src/olav/core/skill_adapter.py           ✅ Skill适配器 (已存在)
```

---

## 📈 验收标准

### 功能对等性
- [ ] query SubAgent性能 ≥ 独立QueryAgentV2
- [ ] analysis SubAgent功能 ≥ 独立Analyzer
- [ ] template_generator SubAgent ≥ 独立Coder

### 架构统一性
- [ ] 所有Agent功能通过orchestrator统一入口
- [ ] SubAgent声明清晰且可扩展
- [ ] 中间件可复用

### 代码清理
- [ ] 独立Agent标记@deprecated
- [ ] 测试覆盖率>85%
- [ ] 无新增Ruff错误

---

## ⏰ 时间估算

| Phase | 任务 | 时间 |
|-------|-----|-----|
| 1.1 | QueryAgentV2迁移 | 2天 |
| 1.2 | Analyzer迁移 | 1天 |
| 1.3 | Coder迁移 | 1天 |
| 2.0 | 代码清理+文档 | 1天 |
| **总计** | **Agent统一架构** | **5天** |

vs 错误方案: 8天 (新功能开发)

---

## 🎯 核心原则

1. **不添加新功能**: 只迁移现有能力
2. **保持性能**: 迁移后性能不降级
3. **统一架构**: 所有Agent通过orchestrator
4. **TDD驱动**: 测试先行，Green→Refactor
5. **渐进式**: 一次迁移一个Agent

---

**文档版本**: v1.1 (修正版)  
**更新时间**: 2026-02-04  
**下一步**: 配置API key后运行测试，进入GREEN阶段
