# OLAV v0.9.8 架构分析报告

## 用户预期架构

```
用户输入
    ↓
[Guard 层] - 意图判断（安全检查）
    ↓
[Orchestrator 层] - 二层路由
    ├─ 路由到 SubAgent
    ├─ 判断 SubAgent 结果
    ├─ 结果不充分 → 再调度补充
    ├─ 结果充分 → 整理结果
    └─ 按用户意图输出（CLI/文件）
    ↓
[SubAgent 层] - 只执行任务返回数据
    ├─ query SubAgent
    ├─ analysis SubAgent
    ├─ cli SubAgent
    └─ expert SubAgent
```

**未来扩展需求**：
- Orchestrator 能同时分发任务给多个 SubAgent 并行执行
- 统一结果输出

---

## 当前架构实现状况

### ✅ 符合预期的部分

#### 1. Guard 层 - 意图判断（安全检查）
**实现文件**：`src/olav/core/guard.py`

**工作流程**：
```python
# Step 1: Whitelist check (fast-path)
if self._is_whitelisted(user_input):
    return GuardResult(action="pass")

# Step 2: Pattern matching (deterministic)
pattern_result = self._check_patterns(user_input)
if pattern_result.action != "pass":
    return pattern_result

# Step 3: LLM classification (optional, 未来扩展)
# Step 4: Default action
return GuardResult(action="pass")
```

**功能完备性**：
- ✅ 危险命令检测（reload, reboot, erase, format）
- ✅ 配置变更控制（write memory, copy config）
- ✅ 敏感数据保护（passwords, keys, credentials）
- ✅ 白名单快速通道（show, list, get, display）
- ✅ 多语言支持（zh/en）
- ⚠️ LLM 意图分类（配置已准备，代码未实现）

**集成点**：
```python
# cli_main.py
guard = Guard(config_path=".olav/skills/guard/rules.yaml")
result = guard.check(user_input)

if result.action == "reject":
    return result.message  # 阻止执行

if result.action == "require_approval":
    confirmed = await ask_user_confirmation(result.message)
    if not confirmed:
        return "Operation cancelled"

# 继续到 Orchestrator
orchestrator = create_orchestrator()
orchestrator.ainvoke(user_input)
```

**评价**：✅ **完全符合** - Guard 层是独立的安全门卫，在 Orchestrator 之前工作

---

#### 2. Orchestrator 层 - 二层路由

**实现文件**：`src/olav/agents/orchestrator.py`

**核心功能**：
```python
def create_orchestrator(...):
    """创建基于 SubAgent 的 Orchestrator
    
    1. 动态加载 SubAgent 配置（从 .olav/OLAV.md）
    2. 创建 DeepAgents 编排器（LangGraph）
    3. 提供 SubAgent 路由和结果聚合
    """
    # 动态加载 SubAgent
    subagents = load_subagents_from_olav()
    
    # Orchestrator 自有工具（文件导出）
    orchestrator_tools = [format_and_export]
    
    # 创建 DeepAgents 编排器
    agent = create_deep_agent(
        model=orch_model,
        system_prompt=system_prompt,  # 从 SKILL.md 加载
        tools=orchestrator_tools,
        subagents=subagents,  # ← SubAgent 配置
        middleware=middleware,
        checkpointer=checkpointer,
        name="orchestrator",
    )
    
    return agent
```

**路由逻辑（在 SKILL.md 中定义）**：
```yaml
# .olav/skills/orchestrator/SKILL.md
Your role is to understand user intent and delegate to the right SubAgent:
1. query - 数据库查询、设备清单、数据导出、CSV 生成
2. analysis - 健康诊断、异常检测、性能分析
3. cli - 设备命令执行、show/configuration 命令
4. expert - 复杂多层故障排查、根因分析、拓扑感知诊断

Decision Process:
1. Parse user query to understand intent
2. Determine which SubAgent can best handle it
3. Call the appropriate SubAgent with the full context
4. Evaluate result:
   - If successful: Return to user
   - If insufficient: Upgrade to next-level SubAgent (analysis→expert, query→analysis)
5. Synthesize results if multiple SubAgents involved
```

**结果处理**：
```python
async def orchestrate_query(user_query: str, ...):
    """编排用户查询
    
    1. 创建 Orchestrator
    2. 执行查询（通过 SubAgent）
    3. 提取最终答案
    4. 返回结果字典
    """
    orchestrator = create_orchestrator(user_id=user_id, thread_id=thread_id)
    
    result = await orchestrator.ainvoke(
        {"messages": [HumanMessage(content=user_query)]},
        config=config,
    )
    
    # 提取最终答案
    final_answer = ""
    if result.get("messages"):
        last_msg = result["messages"][-1]
        if isinstance(last_msg, AIMessage):
            final_answer = last_msg.content
    
    return {
        "status": "complete",
        "final_answer": final_answer,
        "error_message": "",
    }
```

**评价**：⚠️ **部分符合**
- ✅ 有二层路由（通过 DeepAgents SubAgent 机制）
- ✅ 能调度不同的 SubAgent
- ⚠️ **缺失：结果判断和补充调度逻辑**
  - 当前由 **DeepAgents 框架** 自动处理 SubAgent 调度
  - **没有显式的结果充分性检查**
  - **没有显式的补充调度逻辑**
- ✅ 有结果整理（extracting final_answer from messages）
- ✅ 按用户意图输出（CLI 用 markdown，文件用 format_and_export 工具）

---

#### 3. SubAgent 层 - 执行任务返回数据

**SubAgent 定义（在 .olav/OLAV.md）**：
```yaml
### query
name: query
agent_skill: network-query
description: Database query specialist
capabilities:
  - Device inventory queries
  - SQL execution
  - Schema inspection

### expert
name: expert  
agent_skill: network-expert
description: CCIE-level Network Expert
capabilities:
  - Multi-domain expertise
  - Topology-aware analysis
  - Cross-layer correlation
```

**SubAgent 实现（以 QueryAgent 为例）**：
```python
class QueryAgent:
    async def ainvoke(self, inputs, config):
        """执行查询任务
        
        1. 检查缓存
        2. 执行 ReAct 循环
        3. 返回结果字典
        """
        # 执行工具调用
        final_state = await self.agent.ainvoke(
            {"messages": messages}, 
            config=agent_config
        )
        
        # 返回标准化结果
        return {
            "messages": [msg],
            "result": str(result_content),
            "sql_query": successful_sql,
            "error": None,
            "performance": {...}
        }
```

**评价**：✅ **基本符合**
- ✅ SubAgent 只执行任务（SQL 查询、CLI 命令、分析诊断）
- ✅ 返回标准化数据结构
- ⚠️ **但是**：SubAgent 内部有自己的 ReAct 循环（有思考和工具调用）
  - 这是合理的，因为 SubAgent 需要决定调用哪些工具
  - 但与"只执行任务返回数据"的纯粹执行者定位有偏差

---

### ❌ 不符合预期的部分

#### 问题 1：缺少显式的结果判断和补充调度

**预期**：
```python
# Orchestrator 显式检查结果
result = await subagent.execute(task)

if not is_result_sufficient(result):
    # 补充调度
    additional_result = await another_subagent.execute(補充任务)
    final_result = merge(result, additional_result)
else:
    final_result = result
```

**当前实现**：
```python
# Orchestrator 调用 DeepAgents，由框架自动处理
result = await orchestrator.ainvoke({"messages": [...]})

# 没有显式的结果检查和补充逻辑
# DeepAgents 框架内部可能有，但不可见
```

**原因**：
- 使用 DeepAgents 框架的 SubAgent 机制
- 框架封装了 SubAgent 调度逻辑
- Orchestrator 只是配置了 SubAgent 列表和系统提示

**建议**：
如果需要显式控制结果判断和补充调度，需要：
1. 方案 A：在 Orchestrator 的 system_prompt 中明确指示结果验证逻辑
2. 方案 B：实现自定义的结果验证中间件（DeepAgents middleware）
3. 方案 C：不依赖 DeepAgents SubAgent，手动实现调度逻辑

---

#### 问题 2：SubAgent 不是纯粹的执行者

**预期**：
```python
# SubAgent 只执行，不思考
class PureExecutorSubAgent:
    def execute(self, command: str) -> dict:
        # 直接执行命令
        result = run_command(command)
        return {"data": result}
```

**当前实现**：
```python
# SubAgent 有自己的 ReAct 循环
class QueryAgent:
    async def ainvoke(self, inputs, config):
        # 内部有思考和工具选择
        final_state = await self.agent.ainvoke(...)  # ← ReAct 循环
        return result
```

**原因**：
- SubAgent 需要决定调用哪些工具（query_database, list_devices, etc.）
- 这是 LangGraph ReAct agent 的标准行为

**影响**：
- ✅ 优点：SubAgent 可以处理复杂任务（多步骤，自主工具选择）
- ❌ 缺点：不符合纯粹"执行者"定位，有重叠职责
- ❌ 缺点：Orchestrator 和 SubAgent 都在做"思考"，可能导致低效

**建议**：
1. 方案 A：保持现状，SubAgent 作为"专家"而非"执行者"
2. 方案 B：简化 SubAgent，只保留工具调用，不做 ReAct 循环
3. 方案 C：区分两类 SubAgent：
   - Expert SubAgent（有 ReAct）- 复杂推理
   - Executor SubAgent（无 ReAct）- 纯粹执行

---

#### 问题 3：缺少并行执行能力

**预期**：
```python
# Orchestrator 并行调度多个 SubAgent
results = await asyncio.gather(
    query_subagent.execute(task1),
    analysis_subagent.execute(task2),
    cli_subagent.execute(task3),
)

final_result = synthesize(results)
```

**当前实现**：
```python
# DeepAgents SubAgent 是顺序调度
# 没有并行执行能力
```

**原因**：
- DeepAgents 框架的 SubAgent 机制是顺序的
- LangGraph 默认是单线程顺序执行

**建议**：
1. 实现自定义并行调度逻辑（不依赖 DeepAgents SubAgent）
2. 使用 LangGraph 的 parallel branches 功能
3. 在 Orchestrator 中手动 asyncio.gather() 多个 SubAgent

---

## 架构符合度评分

| 层级 | 预期功能 | 实现状况 | 符合度 | 备注 |
|------|---------|---------|--------|------|
| **Guard 层** | 意图判断（安全检查） | ✅ 完全实现 | **100%** | 独立模块，工作正常 |
| **Orchestrator 层** | | | | |
| ├─ 路由到 SubAgent | ✅ 已实现 | **100%** | 通过 DeepAgents SubAgent |
| ├─ 判断结果 | ❌ 缺失 | **0%** | 由框架隐式处理 |
| ├─ 补充调度 | ❌ 缺失 | **0%** | 由框架隐式处理 |
| ├─ 结果整理 | ✅ 已实现 | **100%** | 提取 final_answer |
| └─ 格式化输出 | ✅ 已实现 | **100%** | CLI markdown / 文件导出 |
| **SubAgent 层** | 只执行任务返回数据 | ⚠️ 部分实现 | **60%** | 有 ReAct 循环，不是纯执行者 |
| **并行执行** | 同时调度多个 SubAgent | ❌ 未实现 | **0%** | 未来扩展需求 |

**总体符合度**：**60%**

---

## 差距分析

### 核心差距

1. **Orchestrator 缺少显式的结果验证和补充逻辑**
   - 当前由 DeepAgents 框架隐式处理
   - 无法直接控制补充调度策略
   - 无法插入自定义验证逻辑

2. **SubAgent 定位模糊**
   - 名称叫 "SubAgent"（子代理），但功能像 "Expert"（专家）
   - 有自己的 ReAct 循环，不是纯粹执行者
   - 与 Orchestrator 职责有重叠

3. **缺少并行执行能力**
   - 无法同时调度多个 SubAgent
   - 无法充分利用异步并发优势

### 架构改进建议

#### 方案 A：保留 DeepAgents，优化使用方式

1. **在 Orchestrator SKILL.md 中明确结果验证逻辑**
   ```yaml
   system_prompt: |
     After SubAgent returns result, you MUST:
     1. Verify result completeness (check for missing fields)
     2. If insufficient:
        - Call another SubAgent for supplemental data
        - Merge results before responding
     3. If complete:
        - Format output in markdown
        - Use format_and_export for file output
   ```

2. **实现自定义结果验证中间件**
   ```python
   class ResultValidationMiddleware:
       def __call__(self, state):
           result = state["messages"][-1]
           if not is_complete(result):
               # 触发补充调度
               state["need_supplemental"] = True
           return state
   ```

3. **接受 SubAgent 的专家定位**
   - 重命名：SubAgent → SpecialistAgent
   - 明确定位：不是执行者，是领域专家
   - 保留 ReAct 循环（专家需要推理能力）

#### 方案 B：重新设计架构，放弃 DeepAgents SubAgent

1. **Orchestrator 手动调度**
   ```python
   class Orchestrator:
       async def orchestrate(self, query):
           # 1. 路由决策
           target_agent = self.route(query)
           
           # 2. 调用 SubAgent
           result = await target_agent.execute(query)
           
           # 3. 验证结果
           if not self.is_sufficient(result):
               # 补充调度
               supplemental = await self.get_supplemental_data(result)
               result = self.merge(result, supplemental)
           
           # 4. 格式化输出
           return self.format_output(result)
   ```

2. **SimpleExecutorSubAgent**
   ```python
   class SimpleExecutorSubAgent:
       """纯粹执行者，不做推理"""
       def execute(self, task):
           # 直接调用工具
           tool = self.get_tool(task.tool_name)
           result = tool(**task.params)
           return {"data": result}
   ```

3. **并行执行支持**
   ```python
   # Orchestrator 可以并行调度
   results = await asyncio.gather(
       query_agent.execute(task1),
       analysis_agent.execute(task2),
   )
   ```

#### 方案 C：混合架构

1. **保留 DeepAgents 用于复杂任务**
   - Expert SubAgent: 有 ReAct，处理复杂推理
   - Analysis SubAgent: 有 ReAct，处理诊断分析

2. **简化执行层**
   - Query Executor: 无 ReAct，直接 SQL 查询
   - CLI Executor: 无 ReAct，直接命令执行

3. **Orchestrator 分层调度**
   ```python
   if is_simple_query(query):
       # 使用 Executor（快速）
       result = await query_executor.execute(query)
   else:
       # 使用 Expert SubAgent（完整 ReAct）
       result = await expert_subagent.ainvoke(query)
   ```

---

## 结论

### 当前架构优点

1. ✅ **Guard 层独立且完整** - 安全门卫功能完备
2. ✅ **基于成熟框架** - DeepAgents/LangGraph 稳定可靠
3. ✅ **动态加载配置** - SubAgent 在 OLAV.md 中定义，零代码扩展
4. ✅ **工具能力丰富** - SubAgent 可以调用多种工具

### 当前架构缺陷

1. ❌ **缺少显式结果验证** - 由框架隐式处理，不可控
2. ❌ **SubAgent 定位模糊** - 既像专家又像执行者
3. ❌ **无并行执行能力** - 顺序调度，效率受限
4. ❌ **职责重叠** - Orchestrator 和 SubAgent 都在做推理

### 最终建议

**推荐 方案 C（混合架构）**：

1. **保留 DeepAgents 框架**（不要重复造轮子）
2. **区分两类 Agent**：
   - **Expert SubAgent**（保留 ReAct）- 复杂推理任务
   - **Simple Executor**（无 ReAct）- 简单执行任务
3. **在 Orchestrator 中实现显式调度逻辑**：
   ```python
   class EnhancedOrchestrator:
       async def orchestrate(self, query):
           # 1. 路由决策
           if is_simple(query):
               result = await self.executor.execute(query)
           else:
               result = await self.expert_subagent.ainvoke(query)
           
           # 2. 显式结果验证
           if not self.validator.is_sufficient(result):
               supplemental = await self.supplement(result)
               result = self.merge(result, supplemental)
           
           # 3. 格式化输出
           return self.formatter.format(result)
   ```
4. **支持并行执行**（在 Orchestrator 中手动 asyncio.gather）

**实施优先级**：
1. **P0（立即）**：在 Orchestrator SKILL.md 中明确结果验证指令
2. **P1（短期）**：实现简单执行器（SimpleExecutor）用于快速查询
3. **P2（中期）**：实现显式结果验证逻辑
4. **P3（长期）**：支持并行 SubAgent 调度

---

**报告日期**：2026-02-06  
**OLAV 版本**：v0.9.8
