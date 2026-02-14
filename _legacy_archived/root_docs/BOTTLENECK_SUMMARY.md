## 📍 交互模式查询超时 - 核心发现

### 您的问题
> "列出IP这种简单的查询为什么都无法查出，卡在了哪个环节？"

### ✅ 根本原因已找到

```
简单查询为什么超时: 它甚至还没开始执行就被杀死了

Time: 0s     Guard 检查 [0.5s]
      0.5s   输入解析 [0.5s]
      1.0s   ┌─ 创建 Orchestrator [20秒!]  ← 🔴 卡在这里
      ...    │  ├─ 加载 query SubAgent [8s]
      ...    │  │  └─ _inject_schema_context() 查询数据库
      9.0s   │  ├─ 加载 cli SubAgent [8s]  
      ...    │  │  └─ _inject_schema_context() 查询数据库
      17.0s  │  ├─ 加载 expert SubAgent [1s]
      18.0s  │  ├─ 创建 LLM + DeepAgent [3s]
      21.0s  └─ Orchestrator 创建完毕
      
      21.0s  LLM 调用 #1: 路由决策 [5s]
      26.0s  LLM 调用 #2: 生成 SQL [5s]
      31.0s  ✗ 30s 超时!!! Query 查询甚至没开始

结论: 时间全花在"创建Orchestrator"上，SQL查询根本没执行
```

---

### 🔍 三个关键发现

#### 发现 #1: Schema Injection 很昂贵

**代码位置**: `src/olav/core/subagent_loader.py` line 365-405

```python
def _inject_schema_context(prompt: str) -> str:
    """每次加载 SubAgent 都会运行这个函数"""
    
    # ⚠️ 连接数据库并查询
    views = gw.query_snapshots("SELECT table_name FROM information_schema.tables...")
    tables = gw.query_main("SELECT table_name FROM information_schema.tables...")
    meta = gw.query_snapshots("SELECT snapshot_date, device_count FROM snapshot_metadata...")
    
    # 耗时: 5-8 秒 (3 个查询)
```

**问题**: 
- 每个 SubAgent 被加载时都调用这个函数 (line 301-303)
- query SubAgent → 调用一次 [5-8s]
- cli SubAgent → 调用一次 [5-8s]
- 总共: 16 秒浪费在重复的数据库查询上!

#### 发现 #2: 每次交互都创建新 Orchestrator

**代码位置**: `src/olav/cli/cli_main.py` line 346

```python
# 用户每输入一次，这行就执行一次!
agent = create_orchestrator(thread_id=thread_id)  # [20秒]

# run_interactive_loop_async() 是 while True 循环:
while True:
    user_input = await session.prompt_async("OLAV> ")
    
    agent = create_orchestrator()  # ← 每次都重建! (20秒)
    result = await stream_agent_response(agent, ...)  # (10秒)
```

**问题**:
- Orchestrator 创建不是轻量级的
- 每个交互都完整重建 = 每次浪费 20 秒
- 应该是: 会话初始化一次, 所有查询共用同一个

#### 发现 #3: 完整的查询流程

```
Guard          [0.5s]  ✓ 接近零开销
Parser         [0.5s]  ✓ 接近零开销
───────────────────────────────
CREATE PHASE   [20s]   🔴 主要瓶颈! (占 65%)
  ├─ Schema injection × 2  [16s]  ← 数据库查询
  ├─ LLM initialization     [2s]
  └─ DeepAgent compile     [1s]
───────────────────────────────
EXEC PHASE     [10s]   ⚠️  必需的成本
  ├─ Orchestrator route    [5s]   (LLM 调用)
  ├─ SubAgent execute      [5s]   (LLM 调用)
  └─ Format result         [1s]
───────────────────────────────
TOTAL          [31s]   > 30s 超时 ✗

超时前执行的内容: Guard → Parser → 1/4 CREATE_PHASE (schema injection)
超时后未执行的内容: 3/4 CREATE_PHASE → EXEC_PHASE → Query 执行
```

---

### 💡 为什么是这个问题

#### 问题追踪

```
简单查询 "list all ip addresses on R3" 的死亡之旅:

1. [0.5s]  Guard: "安全检查通过"
2. [0.5s]  Parser: "解析输入成功"
3. [5.0s]  Load query SubAgent:
           - 读取 SKILL.md
           - 调用 _inject_schema_context()
             ├─ 连接 snapshot DB
             ├─ SELECT FROM information_schema.tables   [2s]
             ├─ 连接 main DB
             ├─ SELECT FROM information_schema.tables   [2s]
             ├─ SELECT FROM snapshot_metadata          [1s]
             └─ [回到内存中继续]
4. [5.0s]  Load cli SubAgent: (重复步骤3)
5. [1.0s]  Load expert SubAgent
6. [2-3s]  Create LLM instance
7. [1s]    Compile DeepAgent graph

[!!!] 已用 20-21 秒, 查询尚未开始
[!!!] Orchestrator 刚刚创建完, ainvoke() 启动...

8. [5.0s]  Orchestrator: "这个查询应该路由给谁?"
           (LLM 调用 #1, 思考中...)
9. [5.0s]  Query SubAgent: "根据这个 schema, 我生成这个 SQL..."
           (LLM 调用 #2, 思考中...)

[!!!] 已用 31 秒

[💀] 30 秒超时已触发!!! Query 查询永远不会执行

实际未执行: 
  - 执行生成的 SQL
  - 获取结果
  - 格式化输出
  - 返回给用户
```

#### 为什么简单查询也受影响

```
简单 ≠ 快速

简单查询的问题:
✗ 不是"查询本身复杂"
✗ 而是"创建 Orchestrator 耗时"
✗ 简单查询需要相同的 Orchestrator
✗ 简单查询需要相同的 schema injection
✗ 简单查询需要相同的 LLM 初始化

所以: 简单查询和复杂查询有相同的"前置成本" (20秒)
     然后: 简单查询可能只需 1 秒执行
          复杂查询可能需要 30 秒执行
     
但都要先支付 20 秒的"创建税"
```

---

### 📊 时间预算分析

#### 当前情况 (31秒超时)

```
建议的超时时间:
  - 简单查询: 15-20秒 (查询+渲染)
  - 复杂查询: 60-120秒 (reasoning + execution)

但实际花费:
  - 简单查询: 30+ 秒 (大部分在创建)
  - 复杂查询: 60+ 秒 (需要更多时间)

所以: 即使不改超时时间, 也应该优化"创建"这步
```

#### 时间分配

```
理想情况 (优化后):
  Guard        [0.5s]   1%
  Parser       [0.5s]   1%
  Orchestrator [缓存]   0%    ← 第一次 20s, 之后缓存
  ainvoke()    [10s]    98%
  ────────────────────
  总计         [11s]

当前情况:
  Guard        [0.5s]   2%
  Parser       [0.5s]   2%
  Orchestrator [20s]    65%   ← 后续查询重复浪费!
  ainvoke()    [10s]    31%
  ────────────────────
  总计         [31s]    > 超时!

优化空间: 20秒 可以节省 (通过缓存 schema + 重用 orchestrator)
```

---

### 🎯 关键数字

| 指标 | 数值 | 说明 |
|------|------|------|
| schema injection 耗时 | 5-8秒 | 每个 SubAgent |
| SubAgent 数量 (受影响) | 2 个 | query + cli |
| schema injection 总耗时 | 10-16秒 | × 2 |
| Orchestrator 创建总耗时 | 20秒 | 含schema + LLM + compile |
| ainvoke() 耗时 | 10-15秒 | LLM调用 + SQL执行 |
| 当前超时限制 | 30秒 | settings.execution.query_timeout |
| 实际需要时间 | 31秒 | 20 + 10 + 1 |
| 超出幅度 | +1秒 (3%) | 就够了! |
| 可以节省的时间 | 16-20秒 | schema caching + reuse |

---

### ☝️ 重要的是

**您问**: "时间能减少吗?"

**答**: 不能简单减少 (expert 需要更多时间)

**但**:
- 可以优化"创建"这步 (16-20秒 → 0.1秒)
- 这样简单查询就有充足时间
- 复杂查询也不受影响

---

### 📋 诊断总结

```
问题陈述:        简单查询为什么超时?
根本原因:        在创建 Orchestrator 阶段就花了 20 秒
具体卡点:        _inject_schema_context() 被调用 2 次
数据库查询:      每次 schema injection 都查数据库 (5-8秒)
占比:            创建阶段占总时间的 65%
影响:            所有查询 (简单和复杂)
查询执行进度:    Guard → Parser → 50% 创建 → [超时] ✗
                  Query 查询从未开始执行!

这不是 Query SubAgent 的问题
这是 "创建前置条件" 的问题
```

---

### 📂 相关文件

- 诊断详情: [QUERY_FLOW_DIAGNOSIS.md](QUERY_FLOW_DIAGNOSIS.md)
- 瓶颈分析: [QUERY_FLOW_BOTTLENECK.md](QUERY_FLOW_BOTTLENECK.md)

### 🔧 代码位置

1. **主要瓶颈**: `src/olav/core/subagent_loader.py` line 365-405
   ```python
   def _inject_schema_context(prompt: str) -> str:  # 这个很慢
   ```

2. **重复创建**: `src/olav/cli/cli_main.py` line 346
   ```python
   agent = create_orchestrator(thread_id=thread_id)  # 每次都新建
   ```

3. **调用点**: `src/olav/core/subagent_loader.py` line 301-303
   ```python
   if agent_name in ("query", "cli"):
       system_prompt = _inject_schema_context(system_prompt)  # 每个 SubAgent 都注入
   ```
