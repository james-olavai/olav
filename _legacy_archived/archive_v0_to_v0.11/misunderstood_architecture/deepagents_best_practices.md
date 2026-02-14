# DeepAgents 架构最佳实践与原生能力分析

**日期**: 2026-02-06  
**版本**: v1.0  
**目标**: 分析 DeepAgents 框架原生能力，制定符合框架设计哲学的最佳实践方案

---

## DeepAgents 核心设计哲学

### 1. 中间件驱动架构 (Middleware-Driven)

DeepAgents 的核心理念是通过 **中间件** 来扩展功能，而不是修改核心代理逻辑。

```python
# ✅ 正确做法：使用中间件
class ResultValidationMiddleware(AgentMiddleware):
    def __call__(self, state):
        # 在这里实现结果验证逻辑
        pass

agent = create_deep_agent(
    middleware=[ResultValidationMiddleware()],
)
```

```python
# ❌ 错误做法：手动包装 agent
async def orchestrate_with_validation(query):
    result = await agent.ainvoke(query)
    if not is_valid(result):
        result = await agent.ainvoke(补充查询)
    return result
```

**设计原则**：
- 功能增强通过中间件实现
- 中间件可堆叠、可组合、可重用
- 核心 agent 保持简洁和通用

---

### 2. SubAgent 隔离与委托 (SubAgent Delegation)

SubAgent 不是"执行者"，而是"专家代理"，具有：
- **隔离的上下文窗口**（避免上下文污染）
- **专门的系统提示**（领域专家）
- **独立的工具集**（按需权限）

```python
# ✅ SubAgent 的正确定位
research_subagent = {
    "name": "research-agent",
    "description": "深度研究专家",
    "prompt": "你是一个专业的技术研究员...",
    "tools": [internet_search, web_scraper],
    "model": "openai:gpt-4o",  # 可以使用不同模型
}

# SubAgent 自己会做 ReAct 循环
# 主 agent 只需要委托任务，不需要微观管理
agent = create_deep_agent(subagents=[research_subagent])
```

**设计原则**：
- SubAgent = 独立的专家代理，不是工具函数
- 主 agent 委托任务，SubAgent 自主执行
- 通过 `task()` 工具调用 SubAgent

---

### 3. 内置工具覆盖 (Built-in Tools Coverage)

DeepAgents 已经提供了丰富的内置工具：

| 工具 | 功能 | 提供者 |
|------|------|--------|
| `write_todos` / `read_todos` | 任务规划和进度跟踪 | TodoListMiddleware |
| `ls` / `read_file` / `write_file` / `edit_file` | 文件操作 | FilesystemMiddleware |
| `glob` / `grep` | 文件搜索 | FilesystemMiddleware |
| `execute` | Shell 命令执行 | FilesystemMiddleware (需要 Sandbox backend) |
| `task` | 委托给 SubAgent | SubAgentMiddleware |

**设计原则**：
- 优先使用内置工具，不要重复造轮子
- 自定义工具应该是 **领域特定** 的（如 `nornir_execute`）
- 通用操作（文件、任务管理）已覆盖

---

### 4. LangGraph 原生集成 (Native LangGraph)

`create_deep_agent()` 返回的是 **LangGraph CompiledStateGraph**，可以：

```python
agent = create_deep_agent(...)

# ✅ 原生支持 streaming
async for chunk in agent.astream(inputs):
    print(chunk)

# ✅ 原生支持 checkpointing（会话持久化）
from langgraph.checkpoint.duckdb import DuckDBSaver
checkpointer = DuckDBSaver.from_conn_string("checkpoints.db")
agent = create_deep_agent(checkpointer=checkpointer)

# ✅ 原生支持 human-in-the-loop
agent = create_deep_agent(
    interrupt_on={"dangerous_tool": {"allowed_decisions": ["approve", "reject"]}}
)

# ✅ 原生支持 LangGraph Studio 调试
# agent 可以直接在 Studio 中可视化和调试
```

**设计原则**：
- 充分利用 LangGraph 的能力（streaming, checkpointing, HITL）
- 不要绕过 LangGraph 手工实现这些功能

---

## DeepAgents 原生能力清单

### ✅ 已有的原生能力（无需自定义）

#### 1. 任务管理和进度跟踪
- **工具**: `write_todos`, `read_todos`
- **中间件**: `TodoListMiddleware`
- **功能**: 
  - 自动创建结构化任务列表
  - 跟踪任务状态（not-started, in-progress, completed）
  - 分解复杂任务为子任务

**OLAV 使用建议**：
```python
# ✅ 在 Orchestrator SKILL.md 中指导使用
system_prompt: |
  For multi-step queries:
  1. Use write_todos() to plan subtasks
  2. Execute SubAgent calls for each task
  3. Mark todos completed as done
  4. Verify all tasks complete before responding
```

#### 2. SubAgent 委托
- **工具**: `task(subagent_type, task_description)`
- **中间件**: `SubAgentMiddleware`
- **功能**:
  - 委托任务到专门的 SubAgent
  - 隔离的上下文窗口
  - 自动并发执行（如果多个 task() 调用）

**OLAV 当前状态**：✅ 已使用
```python
# orchestrator.py
subagents = load_subagents_from_olav()
agent = create_deep_agent(subagents=subagents)
```

**改进建议**：
```python
# ✅ 在 SKILL.md 中明确委托策略
system_prompt: |
  SubAgent delegation rules:
  1. query SubAgent - Simple database queries
  2. analysis SubAgent - Health checks
  3. expert SubAgent - Complex troubleshooting
  
  After SubAgent returns:
  - Validate result completeness
  - If insufficient: delegate補充任务 to另一个 SubAgent
  - If complete: format and return
```

#### 3. 文件操作和上下文卸載
- **工具**: `read_file`, `write_file`, `edit_file`, `ls`, `glob`, `grep`
- **中间件**: `FilesystemMiddleware`
- **功能**:
  - 自动将大结果保存到文件（避免上下文溢出）
  - 文件系统作为外部记忆

**OLAV 使用建议**：
```python
# ✅ 用于知识库管理
# .olav/knowledge/ 可以通过 FilesystemBackend 访问
agent = create_deep_agent(
    backend=FilesystemBackend(root_dir=".olav/knowledge/"),
)
```

#### 4. 长期记忆 (Long-term Memory)
- **Backend**: `CompositeBackend` + `StoreBackend`
- **功能**:
  - 持久化特定路径的文件
  - 跨会话保留数据

**OLAV 使用建议**：
```python
# ✅ 混合后端：工作文件临时，知识库持久
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

agent = create_deep_agent(
    backend=CompositeBackend(
        default=StateBackend(),  # 默认临时
        routes={
            "/knowledge/": StoreBackend(store=store),  # 知识库持久
            "/memories/": StoreBackend(store=store),   # 用户偏好持久
        }
    )
)
```

#### 5. 上下文自动摘要
- **中间件**: `SummarizationMiddleware`
- **功能**:
  - 当上下文超过 170k tokens 自动摘要
  - 保留最近的消息，摘要旧对话

**OLAV 当前状态**：✅ 已使用
```python
# orchestrator.py
if use_summarization:
    middleware.append(
        SummarizationMiddleware(
            model=summ_model,
            backend=backend,
            trigger=("tokens", settings.agent.summarization_trigger_tokens),
            keep=("messages", settings.agent.summarization_keep_messages),
        )
    )
```

#### 6. Human-in-the-Loop
- **中间件**: `HumanInTheLoopMiddleware`
- **配置**: `interrupt_on`
- **功能**:
  - 危险操作需要人工批准
  - 支持 approve, edit, reject

**OLAV 使用建议**：
```python
# ✅ 危险网络操作需要确认
agent = create_deep_agent(
    interrupt_on={
        "nornir_execute": {
            "allowed_decisions": ["approve", "edit", "reject"]
        },
        "format_and_export": {  # 文件导出确认
            "allowed_decisions": ["approve", "edit"]
        }
    }
)
```

#### 7. Prompt Caching (Anthropic)
- **中间件**: `AnthropicPromptCachingMiddleware`
- **功能**: 自动缓存系统提示，减少成本

---

### ⚠️ 需要自定义的能力

#### 1. 结果验证和补充调度

**DeepAgents 原生支持**：❌ 无
**实现方式**：自定义中间件

```python
# 方案 1：通过 System Prompt 指导（最简单）
system_prompt: |
  Result validation:
  1. After SubAgent returns, check if result is complete
  2. Missing fields? Call another SubAgent for supplemental data
  3. All data ready? Format and return
  
  Validation checklist:
  - [ ] All requested fields present?
  - [ ] Data format correct (table/json/markdown)?
  - [ ] No errors in SubAgent response?

# 方案 2：自定义中间件（更可控）
class ResultValidationMiddleware(AgentMiddleware):
    async def __call__(self, state):
        last_msg = state["messages"][-1]
        
        # 检查最后一条消息是否来自 SubAgent
        if hasattr(last_msg, "tool_calls") and "task" in last_msg.tool_calls:
            # 验证 SubAgent 结果
            result = self.validate(last_msg)
            
            if not result["is_complete"]:
                # 注入补充任务指令
                state["messages"].append(HumanMessage(
                    content=f"Missing: {result['missing_fields']}. "
                           f"Please call {result['补充_subagent']} to获取这些数据。"
                ))
        
        return state

agent = create_deep_agent(middleware=[ResultValidationMiddleware()])
```

**推荐**：**方案 1（System Prompt）** + **方案 2（中间件作为兜底）**
- Prompt 指导 agent 自主验证（成本低，灵活）
- Middleware 强制检查（保证不遗漏）

#### 2. 并行 SubAgent 调度

**DeepAgents 原生支持**：✅ 部分支持
- `task()` 工具可以被并发调用
- 但需要 agent **自己决定** 并发

```python
# ✅ Agent 可以并发调用多个 SubAgent
# 在 system_prompt 中指导：
system_prompt: |
  Parallel execution:
  - If multiple independent subtasks exist, call task() multiple times
  - Example: Get device list + Check health → call query SubAgent and analysis SubAgent in parallel
  - Wait for all task() results before synthesizing final answer
```

**LangGraph 原生支持**：✅ 完全支持
- LangGraph 支持 **并行分支**（parallel branches）

```python
# ✅ LangGraph 手动并行（如果需要更精确控制）
from langgraph.graph import StateGraph

def route_to_parallel(state):
    # 同时调度多个 SubAgent
    return ["query_subagent", "analysis_subagent"]

graph = StateGraph()
graph.add_conditional_edges(
    "orchestrator",
    route_to_parallel,  # 返回多个节点 = 并行执行
)
```

**推荐**：
- **简单场景**：通过 System Prompt 指导 agent 并发调用 `task()`
- **复杂场景**：使用 LangGraph conditional_edges 手动并行

---

## OLAV 架构优化方案（基于 DeepAgents 最佳实践）

### 方案 A：最小改动（推荐，P0）

**目标**：在现有架构基础上，通过 **System Prompt** 实现结果验证逻辑

#### 1. 更新 Orchestrator SKILL.md

```yaml
# .olav/skills/orchestrator/SKILL.md
system_prompt: |
  You are the Orchestrator coordinating specialist SubAgents.
  
  **SubAgent Dispatch**:
  1. query - Database queries, inventory, data export
  2. analysis - Health diagnostics, anomaly detection
  3. cli - Device command execution
  4. expert - Complex troubleshooting, root cause analysis
  
  **Result Validation Protocol** (CRITICAL):
  After SubAgent returns result, you MUST:
  
  1. ✅ Check Completeness:
     - All requested fields present?
     - Data format correct (markdown table/list/json)?
     - No errors in SubAgent response?
  
  2. ❌ If Incomplete:
     - Identify missing fields: list_missing_fields()
     - Determine補充 SubAgent: 
       * Missing device data → call query SubAgent
       * Missing real-time metrics → call cli SubAgent
       * Missing diagnosis → call analysis/expert SubAgent
     - Call task(補充_subagent, "Get {missing_fields}")
     - Wait for補充 result
     - Merge results before responding
  
  3. ✅ If Complete:
     - Format output in markdown
     - Use format_and_export for file output (CSV/JSON)
     - Return final answer to user
  
  **Validation Examples**:
  
  Example 1 - Incomplete:
  User: "List all devices with their interface count"
  query SubAgent returns: [{"hostname": "R1"}, {"hostname": "R2"}]
  ❌ Missing: interface_count
  → Call query SubAgent again: "Get interface count for R1, R2"
  → Merge results: [{"hostname": "R1", "interfaces": 5}, ...]
  → Return complete table
  
  Example 2 - Complete:
  User: "Show BGP neighbors on R1"
  cli SubAgent returns: Full BGP table
  ✅ All data present
  → Format as markdown table
  → Return to user
```

#### 2. 测试验证

```python
# 测试案例 1：不完整结果 + 自动補充
query = "list all devices with their CPU usage"
result = await orchestrate_query(query)

# 期望行为:
# 1. query SubAgent returns device list (no CPU data)
# 2. Orchestrator detects missing CPU
# 3. Calls cli SubAgent to get CPU usage
# 4. Merges results
# 5. Returns complete table

# 测试案例 2：完整结果 + 直接返回
query = "show devices table"
result = await orchestrate_query(query)

# 期望行为:
# 1. query SubAgent returns complete table
# 2. Orchestrator validates: complete
# 3. Returns directly
```

**优点**：
- ✅ 零代码修改
- ✅ 利用 LLM 智能判断
- ✅ 灵活适应各种场景

**缺点**：
- ⚠️ 依赖 LLM 理解和执行提示
- ⚠️ 可能有遗漏或误判

---

### 方案 B：中间件增强（P1）

**目标**：添加 **ResultValidationMiddleware** 作为兜底保证

```python
# src/olav/middleware/result_validation.py
from langchain_core.messages import HumanMessage, AIMessage
from deepagents.middleware import AgentMiddleware

class ResultValidationMiddleware(AgentMiddleware):
    """验证 SubAgent 结果完整性，触发补充调度"""
    
    def __init__(self, validation_rules: dict[str, list[str]]):
        """
        Args:
            validation_rules: SubAgent → required_fields 映射
            例如: {
                "query": ["hostname", "ip_address"],
                "analysis": ["health_score", "issues"],
            }
        """
        self.validation_rules = validation_rules
    
    async def __call__(self, state):
        messages = state.get("messages", [])
        if not messages:
            return state
        
        last_msg = messages[-1]
        
        # 检查是否是 SubAgent 调用结果
        if not self._is_subagent_result(last_msg):
            return state
        
        # 提取 SubAgent 类型和结果
        subagent_type, result = self._extract_result(last_msg)
        
        # 验证结果
        missing_fields = self._validate_result(subagent_type, result)
        
        if missing_fields:
            # 注入補充指令
            补充_msg = HumanMessage(
                content=f"[System] Result from {subagent_type} is incomplete. "
                       f"Missing fields: {', '.join(missing_fields)}. "
                       f"Please call appropriate SubAgent to获取这些数据。"
            )
            state["messages"].append(补充_msg)
        
        return state
    
    def _is_subagent_result(self, msg) -> bool:
        # 检查是否是 tool call result for 'task'
        if hasattr(msg, "tool_calls"):
            return any("task" in tc.get("name", "") for tc in msg.tool_calls)
        return False
    
    def _extract_result(self, msg):
        # 从消息中提取 SubAgent 类型和结果
        # 实现细节省略
        pass
    
    def _validate_result(self, subagent_type: str, result: dict) -> list[str]:
        # 根据 validation_rules 检查必需字段
        required = self.validation_rules.get(subagent_type, [])
        missing = [f for f in required if f not in result]
        return missing


# orchestrator.py
from olav.middleware.result_validation import ResultValidationMiddleware

validation_rules = {
    "query": ["hostname", "ip_address"],
    "analysis": ["health_score", "recommendations"],
    "cli": ["output", "status"],
}

agent = create_deep_agent(
    subagents=subagents,
    middleware=[
        ResultValidationMiddleware(validation_rules),
        # ... 其他 middleware
    ]
)
```

**优点**：
- ✅ 强制验证，不依赖 LLM
- ✅ 可配置验证规则
- ✅ 兜底保证

**缺点**：
- ⚠️ 需要维护 validation_rules
- ⚠️ 增加代码复杂度

---

### 方案 C：简化执行器（P2）

**目标**：为简单查询创建 **无 ReAct 的快速执行器**

```python
# src/olav/agents/simple_executor.py
class SimpleExecutor:
    """简单执行器：无 ReAct 循环，直接调用工具"""
    
    def __init__(self, tools: dict[str, Callable]):
        self.tools = tools
    
    async def execute(self, task: dict[str, Any]) -> dict[str, Any]:
        """
        Args:
            task: {
                "tool": "query_database",
                "params": {"query": "SELECT * FROM devices"}
            }
        
        Returns:
            {"data": [...], "error": None}
        """
        tool_name = task["tool"]
        params = task.get("params", {})
        
        tool = self.tools.get(tool_name)
        if not tool:
            return {"data": None, "error": f"Tool '{tool_name}' not found"}
        
        try:
            result = await tool(**params)
            return {"data": result, "error": None}
        except Exception as e:
            return {"data": None, "error": str(e)}


# orchestrator.py
from olav.agents.simple_executor import SimpleExecutor

# 创建简单执行器
simple_executor = SimpleExecutor(tools={
    "query_database": query_database,
    "list_devices": list_devices,
})

# Orchestrator 决策：简单查询 → SimpleExecutor，复杂任务 → SubAgent
async def orchestrate(query):
    if is_simple_query(query):
        # 快速通道：直接执行工具
        task = parse_query_to_task(query)  # LLM 提取工具和参数
        result = await simple_executor.execute(task)
    else:
        # 完整 ReAct：调用 SubAgent
        result = await orchestrator.ainvoke(...)
    
    return result
```

**优点**：
- ✅ 快速通道，无 ReAct 开销
- ✅ 适合简单查询（80% 场景）
- ✅ 降低 LLM 调用成本

**缺点**：
- ⚠️ 需要 LLM 提取工具和参数（仍有一次 LLM 调用）
- ⚠️ 丧失 ReAct 的自我纠错能力

---

### 方案 D：LangGraph 手动并行（P3）

**目标**：利用 LangGraph `conditional_edges` 实现并行 SubAgent 调度

```python
# src/olav/agents/parallel_orchestrator.py
from langgraph.graph import StateGraph
from typing import Literal

def should_parallelize(state) -> list[str]:
    """决定是否并行调度多个 SubAgent"""
    query = state["messages"][-1].content
    
    # 示例：如果查询需要多个数据源
    if "health" in query and "topology" in query:
        return ["analysis_subagent", "query_subagent"]
    
    # 单个 SubAgent
    return ["query_subagent"]


def create_parallel_orchestrator():
    graph = StateGraph()
    
    # 添加节点
    graph.add_node("router", route_query)
    graph.add_node("query_subagent", query_subagent)
    graph.add_node("analysis_subagent", analysis_subagent)
    graph.add_node("synthesizer", synthesize_results)
    
    # 并行分支
    graph.add_conditional_edges(
        "router",
        should_parallelize,  # 返回 list[str] = 并行节点
    )
    
    # 所有分支汇聚到 synthesizer
    graph.add_edge("query_subagent", "synthesizer")
    graph.add_edge("analysis_subagent", "synthesizer")
    
    graph.set_entry_point("router")
    graph.set_finish_point("synthesizer")
    
    return graph.compile()
```

**优点**：
- ✅ 精确控制并行逻辑
- ✅ 充分利用异步并发
- ✅ 适合固定的并行模式

**缺点**：
- ⚠️ 需要手动定义图结构
- ⚠️ 灵活性不如 DeepAgents SubAgent

---

## 推荐实施路线

### Phase 1 (P0) - 立即实施

1. **更新 Orchestrator SKILL.md**
   - 添加详细的结果验证协议
   - 提供具体的验证示例
   - 指导如何補充数据

2. **测试验证**
   - 创建测试用例（完整结果 vs 不完整结果）
   - 验证 Orchestrator 能否自主補充

**预期效果**：
- Orchestrator 能主动验证 SubAgent 结果
- 自动调度補充 SubAgent 补全数据
- 零代码改动，风险最低

---

### Phase 2 (P1) - 短期优化

1. **实现 ResultValidationMiddleware**
   - 作为兜底保证机制
   - 配置验证规则

2. **实现 SimpleExecutor**
   - 用于 80% 的简单查询
   - 降低 ReAct 开销

**预期效果**：
- 提升简单查询性能（减少 50% LLM 调用）
- 强制结果验证（不依赖 LLM）

---

### Phase 3 (P2) - 中期增强

1. **HITL 集成**
   - 危险操作需要确认（nornir_execute）
   - 文件导出需要确认（format_and_export）

2. **Long-term Memory**
   - 知识库持久化（.olav/knowledge/）
   - 用户偏好持久化（.olav/memories/）

**预期效果**：
- 更安全的操作流程
- 跨会话学习能力

---

### Phase 4 (P3) - 长期扩展

1. **LangGraph 手动并行**
   - 用于固定的并行模式
   - 如：同时查询拓扑 + 健康数据

2. **自定义 Backend**
   - 集成 OLAV 数据库（main.duckdb）
   - FilesystemBackend 访问 .olav/knowledge/

**预期效果**：
- 极致性能优化
- 深度定制化能力

---

## 总结：DeepAgents 最佳实践

### ✅ DO

1. **使用 Middleware 扩展功能** - 不要手动包装 agent
2. **System Prompt 指导行为** - 详细的验证和流程说明
3. **SubAgent = 专家代理** - 接受其有 ReAct 循环
4. **利用内置工具** - write_todos, task(), filesystem tools
5. **充分利用 LangGraph** - streaming, checkpointing, HITL
6. **CompositeBackend 管理记忆** - 临时 + 持久混合

### ❌ DON'T

1. **不要绕过 DeepAgents 手动调度** - 失去框架优势
2. **不要重复内置工具** - 文件操作、任务管理已有
3. **不要把 SubAgent 当工具函数** - 它们是独立代理
4. **不要在 System Prompt 中重复 Middleware 指令** - 框架已注入
5. **不要忽略 LangGraph 能力** - 使用 conditional_edges, parallel branches

---

**下一步行动**：
1. 立即实施 Phase 1（更新 SKILL.md）
2. 创建测试用例验证結果補充逻辑
3. 根据测试结果决定是否需要 Phase 2（中间件）

**关键指标**：
- 結果完整率（首次查询即完整的比例）
- 平均補充次数（每个查询需要几次補充）
- 用户满意度（結果是否符合预期）
