# 查询超时问题诊断报告

**问题**: 交互模式下查询"list all ip addresses on R3"超时（180秒后）

**根本原因**: DeepAgents SubAgent中的多个LLM调用堆叠

---

## 问题分析

### 观察到的症状
```
⠇ ☃️ Olav is digging...
❌ Error: Query timed out after 180.0 seconds
```

### 诊断结果

从运行诊断脚本得到的日志：

1. **Orchestrator创建**: ✅ 3.48秒 (正常)
   - 工具注册: 10个工具
   - SubAgent加载: 3个(query, cli, expert)
   - LLM初始化: OpenRouter API

2. **agent.ainvoke()执行**: ❌ 10秒超时
   - 第1次LLM调用: ~5秒完成 (OpenRouter API)
   - 第2次LLM调用: ~4秒后被cancel (CancelledError)
   - **问题**: 至少3个LLM调用堆叠（Orchestrator + SubAgent routing）

---

## 性能瓶颈链

```
用户输入 "list all ip addresses on R3"
    ↓
[~5s] LLM调用 #1: Orchestrator路由决策 (query vs cli vs expert?)
    ↓
[~5s] LLM调用 #2: Query SubAgent制定SQL
    ↓
[可能] LLM调用 #3: 结果验证/格式化
    ↓ (总计: 15-25秒)
10秒超时 -> ❌ 中断
```

---

## 为什么会发生

### 1. Orchestrator → 多个SubAgent的层级调用
```python
# router.py: create_orchestrator()
agent = create_deep_agent(
    subagents=subagents,  # [query, cli, expert]
    ...
)
```

当用户输入一个查询时，DeepAgents的流程是：
1. **Tier 1**: Orchestrator LLM调用 → 决定路由到query/cli/expert
2. **Tier 2**: 选中的SubAgent (query)的LLM调用 → 生成SQL
3. **Tier 3**: 可能的验证/合并步骤

每一步都是一个独立的LLM调用，在OpenRouter上需要5-6秒（包括网络延迟）。

### 2. 交互模式超时时间过长
```python
# config/settings.py line 351
query_timeout: int = Field(
    default=180,  # 🔴 太长！
    ge=30,
    le=600,
    description="CLI query timeout in seconds"
)
```

- 180秒 = 3分钟
- 这对一个网络查询来说太长了
- 应该是15-30秒

### 3. DeepAgents异步等待问题
```python
# cli_main.py line 89-91
final_state = await asyncio.wait_for(
    agent.ainvoke(base_inputs, config=config),
    timeout=timeout,  # 180秒
)
```

虽然设置了180秒超时，但当超过10秒的总操作时间后：
- OpenRouter API可能响应缓慢
- DeepAgents的await堆叠了多个coroutines
- 整个asyncio.wait_for()被cancel

---

## 解决方案

### 方案 #1: 减少超时时间（快速修复）
```python
# config/settings.py
query_timeout: int = Field(
    default=30,  # 改为30秒
    ge=10,
    le=180,  # 最大3分钟
    description="CLI query timeout in seconds"
)
```

**优点**: 立即生效，防止长时间等待
**缺点**: 不解决根本问题（仍可能超时）

### 方案 #2: 优化LLM调用（根本修复）

#### 2a: 使用缓存减少LLM调用
```python
# 在query_orchestrator.py中添加缓存
from olav.cache import cache

def orchestrate_query_sync(user_query, ...):
    # Check cache first
    cache_key = f"query:{user_query[:50]}"
    if cache_result := cache.get(cache_key):
        return cache_result
    
    # ... execute query ...
    cache.set(cache_key, result)
    return result
```

#### 2b: 移除不必要的SubAgent路由
当前架构：
```
User Query
  ↓
Orchestrator (LLM) → Query Agent
  ↓
Query Agent (LLM) → SQL
```

优化架构：
```
User Query
  ↓
Direct Query Agent (single LLM) → SQL & execution
```

### 方案 #3: 跳过Orchestrator直接使用Query Agent（推荐）

当前问题：Query SubAgent已经能处理大多数查询，但Orchestrator还要再调用一次LLM决定路由。

```python
# 在ollav query命令中
if not enable_guard or guard.classify(query) == "DIRECT_QUERY":
    # Skip Orchestrator, use Query SubAgent directly
    from olav.agents.router import create_orchestrator
    agent = create_orchestrator()  # But only query subagent
else:
    # Full routing
    agent = create_orchestrator()
```

---

##立即修复建议

**优先级1**: 减少query_timeout
```python
# config/settings.py改动
- query_timeout: int = Field(default=180, ...)
+ query_timeout: int = Field(default=30, ...)
```

这个改动会：
✅ 防止用户卡住180秒
✅ 允许更快的失败+重试
✅ 费用最低（仅配置改动）

**优先级2**: 添加LLM缓存
```python
# 在orchestrate_query_sync开头添加缓存检查
```

---

##性能基准（预期）

| 场景 | 当前 | 优化后 |
|------|------|--------|
|  简单query(仅Orchestrator) | 5-10s | 2-3s |
| 复杂query(Orchestrator+SubAgent) | 15-25s | 5-10s |
| 缓存命中 | N/A | <1s |

---

## 推荐行动

1. **立即**: 修改config/settings.py中的query_timeout为30秒
2. **短期**: 在query_orchestrator.py中添加缓存机制
3. **中期**: 评估能否跳过Orchestrator进行直接Query SubAgent路由
4. **长期**: 考虑DeepAgents的替代方案或async优化
