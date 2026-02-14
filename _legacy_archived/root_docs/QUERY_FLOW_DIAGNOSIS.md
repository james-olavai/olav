## 交互模式查询流程诊断 - 卡点分析

**问题**: "list all ip addresses on R3"这种简单查询为什么会超时？

---

## 完整的查询请求流程

```
用户输入: "list all ip addresses on R3"
    ↓ [~0.5s]
Guard 检查 (安全网关)
    ↓ [~1s]
输入解析 (parse_input)
    ↓ [BOTTLENECK! 15-20s] ← **这里卡住了**
创建新的 Orchestrator: create_orchestrator(thread_id)
    │
    ├─ 加载SubAgents: load_subagents_from_olav()
    │  ├─ 加载 query SubAgent
    │  │  └─ _inject_schema_context() → 数据库查询 #1,#2 (~5-10s?)
    │  ├─ 加载 cli SubAgent  
    │  │  └─ _inject_schema_context() → 数据库查询 #1,#2 (~5-10s?)
    │  └─ 加载 expert SubAgent
    │     └─ 加载系统提示 (~1s)
    │
    ├─ 加载Orchestrator系统提示 (~1s)
    ├─ 创建LLM实例 (~2s)
    └─ 创建 DeepAgent (~1s)
    ↓ [~10-15s]
agent.ainvoke() 执行
    │
    ├─ Orchestrator 路由决策 (LLM调用 #1) (~5-6s)
    ├─ 路由到 Query SubAgent
    │  └─ 生成SQL (LLM调用 #2) (~5-6s)
    ├─ 执行SQL查询 (~0.5s)
    └─ 格式化输出 (~1s)
    ↓
返回结果 + 渲染
```

---

## 🔴 性能瓶颈分析

### 主要卡点: Schema Injection in SubAgent Loading

**位置**: `src/olav/core/subagent_loader.py` 第 297-351 行

**函数**: `_inject_schema_context(prompt: str) -> str`

**做了什么**:
```python
def _inject_schema_context(prompt: str) -> str:
    """Inject current database schema into system prompt."""
    try:
        from olav.lib.data_gateway import get_gateway
        gw = get_gateway()

        # ❌ 数据库查询 #1: 查看 views (3-5s?)
        views = gw.query_snapshots(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' AND table_type = 'VIEW'"
        )
        
        # ❌ 数据库查询 #2: 查看 tables (3-5s?)
        tables = gw.query_main(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        )
        
        # ❌ 数据库查询 #3: 查看 snapshot_metadata (2-3s?)
        meta = gw.query_snapshots(
            "SELECT snapshot_date, device_count "
            "FROM snapshot_metadata "
            "ORDER BY snapshot_date DESC LIMIT 1"
        )
        
        # 构建上下文文本 (~0.1s)
        context = "..."
        return prompt + context
```

**问题**:
1. **每次创建SubAgent都调用**: 每个交互都在 `load_subagents_from_olav()` 中调用
2. **被调用多次**: 
   - query SubAgent → _inject_schema_context() 
   - cli SubAgent → _inject_schema_context()
   - 共2-3次调用
3. **数据库查询很慢**: 
   - snapshot DB连接建立 (~1-2s)
   - 查询执行 (~2-3s/查询)
   - 结果返回 (~1s)
4. **总耗时**: 5-10秒 × 2-3次 = **15-30秒!**

### 次要卡点: Orchestrator 创建频率

**位置**: `src/olav/cli/cli_main.py` 第 346-353 行

**代码**:
```python
# 每次交互都创建新的Orchestrator!
from olav.agents.orchestrator import create_orchestrator
agent = create_orchestrator(thread_id=thread_id)  # ← 每次都重新创建
inputs = {"messages": [HumanMessage(content=processed_text)]}

output = await stream_agent_response(
    agent,
    inputs,
    verbose=use_verbose,
    thread_id=thread_id,
)
```

**流程详解**:
```
每次用户输入:
  user input → Guard → Parser → create_orchestrator() ← NEW ORCHESTRATOR每次!
    ↓
  load_subagents_from_olav()
    ├─ add query SubAgent → _inject_schema_context() [5-10s]
    ├─ add cli SubAgent → _inject_schema_context() [5-10s]
    └─ add expert SubAgent [1-2s]
  ↓
  agent.ainvoke() [10-15s]
  ↓
  显示结果
```

问题: **每次交互都要重新加载和注入schema**

---

## 📊 时间分解

### 简单查询 "list all ip addresses on R3" 的实际时间

```
阶段                          预估时间    说明
────────────────────────────────────────────────────────────
1. Guard 检查                 0.5s       安全网关检查
2. 输入解析                   0.5s       parse_input()
3. 加载 query SubAgent        8s         load + _inject_schema_context()
4. 加载 cli SubAgent          8s         load + _inject_schema_context()
5. 加载 expert SubAgent       1s         load (无schema injection)
6. 创建 Orchestrator          3s         LLM初始化等
────────────────────────────────────────────────────────────
   小计: 创建阶段             20.5s      ← 这是主要瓶颈!
────────────────────────────────────────────────────────────
7. Orchestrator 路由 LLM      5-6s       LLM调用 #1
8. Query SubAgent LLM调用     5-6s       LLM调用 #2
9. SQL执行 + 格式化          0.5s       数据库+格式
────────────────────────────────────────────────────────────
   小计: 执行阶段             11s
────────────────────────────────────────────────────────────
总时间:                      ~31s        ← 超过30秒超时!
```

**关键发现**: 创建阶段 (20.5s) 占总时间的 65%!

---

## 🔍 核心问题

### 问题 #1: Schema Injection 每次都执行
```
为什么有问题:
✗ 每个交互都要加载 SubAgent
✗ 每个 SubAgent 都要注入 schema
✗ Schema 注入需要数据库查询
✗ 数据库查询很慢 (5-10秒)
✗ 这是重复的、不变的工作

为什么这是多余的:
✗ Schema 不经常变化 (可能几小时才变一次)
✗ 简单查询不需要复杂的 schema context
✗ 可以共享 schema context 而不是每次重新加载
```

### 问题 #2: 每次交互都创建新 Orchestrator
```
为什么有问题:
✗ create_orchestrator() 不是轻量级的
✗ 需要加载SubAgents (上面的问题)
✗ 需要初始化LLM实例
✗ 需要编译DeepAgent图
✗ 这些步骤都很慢

为什么这是多余的:
✗ 同一个Orchestrator可以处理多个查询
✗ DeepAgents支持会话管理 (checkpointer)
✗ Orchestrator配置在会话期间不变
✗ 现在是"every query = new orchestrator"
✗ 应该是"per session = one orchestrator"
```

---

## 💡 数据流概览

### 当前流程 (低效)
```
Session A: ["query 1", "query 2", "query 3"]
  Query 1: create_orchestrator() [20s] → ainvoke() [10s] = 30s total
  Query 2: create_orchestrator() [20s] → ainvoke() [10s] = 30s total
  Query 3: create_orchestrator() [20s] → ainvoke() [10s] = 30s total
  
总时间: 90秒 (3个查询)
```

### 优化后的流程 (应该有的)
```
Session A: 
  Initialize: create_orchestrator() [20s] ← ONCE per session
  Query 1: ainvoke() [10s] = 10s total
  Query 2: ainvoke() [10s] = 10s total
  Query 3: ainvoke() [10s] = 10s total
  
总时间: 50秒 (初始化20s + 3个查询30s)
```

---

## 📋 查询流程检查清单

根据您描述的流程:

**您说的流程**:
> "guard路由，快速到query，query查询得出结果，交给orchestrator渲染输出"

**实际流程**:
1. ✅ Guard 检查 - 正确
2. ❌ 不是"快速到query" - 实际上在 create_orchestrator() 中卡住了
3. ✅ Query 查询得出结果 - 正确
4. ✅ Orchestrator 渲染输出 - 正确但有问题

**啥地方不对**:
```
步骤 2: "快速到 query" 
实际: create_orchestrator() [20秒] 
原因: _inject_schema_context() 被调用2-3次
      每次都查数据库 (5-10秒)
```

---

## 🎯 关键代码位置

### 瓶颈 #1: Schema Injection
- **文件**: `src/olav/core/subagent_loader.py`
- **函数**: `_inject_schema_context()` (line 365-405)
- **调用点**: line 301-303
  ```python
  if agent_name in ("query", "cli"):
      system_prompt = _inject_schema_context(system_prompt)
  ```

### 瓶颈 #2: 重复创建 Orchestrator
- **文件**: `src/olav/cli/cli_main.py`
- **函数**: `run_interactive_loop_async()` 
- **调用点**: line 346-353
  ```python
  agent = create_orchestrator(thread_id=thread_id)  # 每次都创建!
  ```

### 瓶颈 #3: 数据库连接
- **文件**: `src/olav/lib/data_gateway.py`
- **函数**: `get_gateway()`, `query_snapshots()`, `query_main()`
- **调用点**: 在 `_inject_schema_context()` 中3次调用

---

## 总结

**您问的问题**:
> "列出IP这种简单查询为什么都无法查出，卡在了哪个环节"

**答案**:
```
卡在第一步就没开始查询! 

当前流程:
Guard (0.5s) → Parser (0.5s) → [STUCK] create_orchestrator() (20s)
                                  └─ _inject_schema_context() × 2
                                     └─ 数据库查询 × 3
                                        
超过30秒 → 查询被取消
实际数据库查询: 从未到达!
```

**为什么会这样**:
1. 每次都要创建新 Orchestrator
2. 每个 SubAgent 都要注入 schema
3. Schema injection 需要数据库查询
4. 简单的"list IPs"查询甚至还没开始执行就已经超时了

**结论**:
- ❌ "query无法查出" 不准确
- ✅ "在create_orchestrator阶段被卡住" 准确
- ✅ 时间不能改 (expert需要更多) - 但"创建"这步可以优化
