# Guard双层架构设计方案

**版本**: v1.0.0  
**日期**: 2026-02-11  
**状态**: 🟡 设计阶段  
**作者**: OLAV架构团队

---

## 📋 目录

- [1. 执行摘要](#1-执行摘要)
- [2. 当前架构问题](#2-当前架构问题)
- [3. Guard双层架构设计](#3-guard双层架构设计)
- [4. 核心组件设计](#4-核心组件设计)
- [5. 路由决策算法](#5-路由决策算法)
- [6. 缓存策略](#6-缓存策略)
- [7. 性能预期](#7-性能预期)
- [8. 实施计划](#8-实施计划)
- [9. 测试策略](#9-测试策略)
- [10. 风险评估](#10-风险评估)

---

## 1. 执行摘要

### 1.1 设计目标

**核心理念**: 将90%的路由决策能力前置到Guard层，简化Orchestrator为纯执行调度器。

**关键收益**:
- ⚡ **性能**: 简单查询从12秒 → 2秒（83% ⬇️）
- 🎯 **准确性**: 利用语义缓存，重复查询<100ms
- 🛡️ **安全性**: 危险命令秒级拦截（无需LLM推理）
- 🧩 **架构**: Orchestrator职责减少70%，降低复杂度

### 1.2 设计原则

✅ **Guard优先** - 90%的查询由Guard直接路由  
✅ **Orchestrator兜底** - 处理不确定和失败重试  
✅ **保持兼容** - 不破坏现有SubAgent机制  
✅ **渐进部署** - 通过环境变量控制启用/禁用

---

## 2. 当前架构问题

### 2.1 问题诊断

#### **Problem 1: Orchestrator过载**

```python
# 当前 orchestrate_query_sync() 的职责（7个）
def orchestrate_query_sync(query):
    1. QueryComplexityScorer.score()     # 3-4秒 LLM调用
    2. SchemaDataValidator.check()       # 1-2秒 数据库查询
    3. 加载Expert SKILL.md               # 文件I/O
    4. 加载Query SKILL.md                # 文件I/O
    5. 构建System Prompt (500+ chars)   # 字符串拼接
    6. LLM推理生成SQL                    # 4-5秒 LLM调用
    7. 解析<cli_needed>/<export>标签     # 正则匹配
```

**问题**:
- 总延迟: 8-14秒（70%时间在LLM推理）
- 复杂度: 1600+行代码，多重嵌套
- 可维护性: 职责不清晰，难以测试

#### **Problem 2: 重复工作**

```
Query 1: "有多少个设备?"
  → QueryComplexityScorer (3秒)
  → Query Agent LLM (5秒)
  → 总计: 8秒

Query 2: "有多少个设备?" (相同查询)
  → QueryComplexityScorer (3秒) ❌ 重复推理
  → Query Agent LLM (5秒)        ❌ 缓存未命中
  → 总计: 8秒                     ❌ 无改善
```

**根本原因**: 没有统一的语义缓存层。

#### **Problem 3: 无差异化处理**

```
简单查询: "count devices?"     → 8秒 (过度设计)
复杂查询: "为什么OSPF不稳定?"  → 12秒 (合理)
```

**问题**: 所有查询都走相同的慢路径。

---

## 3. Guard双层架构设计

### 3.1 架构对比图

#### **当前架构（单层）**

```
用户Query
  ↓
┌─────────────────────────────────────────┐
│ Orchestrator                            │
│  1. Complexity Scoring (3-4秒)          │
│  2. Schema Validation (1-2秒)           │
│  3. Load SKILL.md                       │
│  4. Build Prompt                        │
│  5. LLM Inference (4-5秒)               │
│  6. Parse Response                      │
│  └─→ Route to SubAgent                  │
└─────────────────────────────────────────┘
  ↓
SubAgent (Query/CLI/Expert)

总延迟: 8-14秒
```

#### **Guard双层架构（新设计）**

```
用户Query
  ↓
═══════════════════════════════════════════
🛡️ LAYER 1: Guard (快速分类层)
═══════════════════════════════════════════
  1. 语义缓存查询 (10-50ms)
  2. 危险命令检测 (规则匹配, <10ms)
  3. 快速分类 (LLM推理, 1-2秒)
  4. 置信度评估
  ↓
┌─────────────────────────────────────────┐
│ 路由决策 (conf > 0.85?)                 │
│                                         │
│  HIGH CONFIDENCE (90%)                  │
│    ├─ REJECT    → 直接拒绝 (<100ms)     │
│    ├─ SIMPLE    → Query Agent (5秒)     │
│    ├─ CLI       → CLI Agent (3秒)       │
│    └─ EXPERT    → Expert Agent (8秒)    │
│                                         │
│  LOW CONFIDENCE (10%)                   │
│    └─ UNKNOWN   → Orchestrator (12秒)   │
└─────────────────────────────────────────┘
  ↓
═══════════════════════════════════════════
⚙️ LAYER 2: Orchestrator (智能调度层)
═══════════════════════════════════════════
  仅处理:
  - Guard不确定的查询 (10%)
  - SubAgent escalation请求
  - 多轮对话和规划
  
  职责简化:
  ❌ 删除 QueryComplexityScorer
  ❌ 删除 初始路由逻辑
  ✅ 保留 Multi-agent协调
  ✅ 保留 Escalation处理

总延迟:
- 简单查询(缓存): <100ms (99% ⬇️)
- 简单查询(无缓存): 2-5秒 (50-70% ⬇️)
- 复杂查询: 8-12秒 (20-30% ⬇️)
- 不确定查询: 12-15秒 (无变化)
```

### 3.2 职责划分表

| 组件 | 职责 | 输入 | 输出 | 延迟 |
|------|------|------|------|------|
| **Guard** | 快速分类和路由决策 | User query | Route decision | 0.1-2秒 |
| ├─ 危险命令检测 | 规则匹配（黑名单） | Query | REJECT/PASS | <10ms |
| ├─ 语义缓存 | 查询缓存历史分类 | Query | Cached route | 10-50ms |
| ├─ 快速分类器 | LLM分类（5类） | Query | Route + Conf | 1-2秒 |
| └─ 置信度阈值 | 决定是否直达SubAgent | Confidence | Go/Fallback | <1ms |
| **Orchestrator** | 智能调度和异常处理 | Complex query | Final answer | 10-15秒 |
| ├─ 不确定查询规划 | 多步骤推理 | Unknown query | Execution plan | 3-5秒 |
| ├─ Escalation处理 | SubAgent请求重新路由 | <cli_needed> | Re-route | 5-8秒 |
| └─ 多轮对话 | 上下文管理 | Conversation | Context state | 持久化 |
| **SubAgents** | 专业领域执行 | Routed query | Domain answer | 3-8秒 |
| ├─ Query Agent | SQL生成和执行 | Simple query | SQL result | 3-5秒 |
| ├─ CLI Agent | 实时设备查询 | CLI command | Device output | 2-4秒 |
| └─ Expert Agent | 根因分析和建议 | Complex problem | RCA report | 8-12秒 |

### 3.3 Orchestrator职责详解（新架构）

#### **3.3.1 职责变化对比**

| 职责类别 | 当前架构（v0.11.x） | Guard架构（v0.12.0） | 变化 |
|---------|-------------------|---------------------|------|
| **路由决策** | ✅ 100%负责 | ❌ 0%（Guard接管） | 删除 |
| **复杂度评分** | ✅ QueryComplexityScorer | ❌ 删除 | 删除 |
| **Schema验证** | ✅ SchemaDataValidator | ✅ 保留（Expert路由时） | 保留 |
| **不确定查询规划** | ⚠️ 隐式处理 | ✅ 显式职责 | 增强 |
| **Escalation处理** | ✅ 解析标签 | ✅ 统一接口 | 增强 |
| **多轮对话** | ✅ Checkpointer | ✅ 保留 | 保留 |
| **Multi-agent协调** | ⚠️ 有限支持 | ✅ 核心职责 | 增强 |
| **结果格式化** | ✅ Export标签解析 | ✅ 保留 | 保留 |

**总结**: 
- **删除**: 路由决策、复杂度评分（~40%代码）
- **保留**: Escalation、多轮对话、协调（~30%代码）
- **增强**: 智能规划、错误恢复（+30%新代码）

#### **3.3.2 核心职责清单（6大职责）**

##### **职责1: 不确定查询的智能规划 (UNKNOWN类型)**

**触发条件**:
- Guard置信度 < 0.85
- 查询模糊："帮我看看网络"
- 多意图查询："先查设备再分析问题"

**处理流程**:
```python
def handle_unknown_query(query: str) -> dict:
    """Orchestrator的智能规划能力（不确定查询）。
    
    Examples:
    - "网络有什么问题?" → 需要分解为：
      1. 列出设备
      2. 检查状态
      3. 分析异常
    
    - "帮我看看" → 需要澄清：
      1. 看什么？设备/接口/日志？
      2. 范围？全部/特定设备？
      3. 目的？监控/排障/审计？
    """
    # Step 1: 分解意图（Multi-intent parsing）
    intents = parse_multiple_intents(query)
    
    # Step 2: 生成执行计划
    plan = create_execution_plan(intents)
    
    # Step 3: 顺序/并行执行
    results = execute_plan(plan)
    
    # Step 4: 汇总结果
    return synthesize_results(results)
```

**示例**:
```
Query: "网络有什么问题?"

Orchestrator规划:
1. SubAgent: Query → 查询设备健康状态
2. SubAgent: Query → 查询接口错误统计
3. SubAgent: Expert → 分析异常模式
4. Orchestrator → 汇总并生成报告

输出: "发现3个设备有接口错误，Expert建议检查光模块..."
```

##### **职责2: SubAgent Escalation处理**

**触发条件**:
- Query Agent返回 `<cli_needed>`
- Query Agent返回 `<escalate_to_expert>`
- CLI Agent返回 `<need_expert_analysis>`
- SubAgent执行失败需要降级

**处理逻辑**:
```python
def handle_escalation(
    original_query: str,
    agent_response: dict,
    escalation_type: str
) -> dict:
    """处理SubAgent的escalation请求。
    
    Escalation类型:
    1. <cli_needed>: Query Agent → CLI Agent
    2. <escalate_to_expert>: Query Agent → Expert Agent
    3. <need_expert_analysis>: CLI Agent → Expert Agent
    4. Failure: Any Agent → Retry/Downgrade
    """
    
    if escalation_type == "cli_needed":
        # Step 1: 提取需要的CLI命令
        cli_commands = extract_cli_commands(agent_response)
        
        # Step 2: 路由到CLI Agent
        cli_result = cli_agent.execute(cli_commands)
        
        # Step 3: 回到Query Agent补充context
        return query_agent.retry_with_context(
            original_query,
            cli_context=cli_result
        )
    
    elif escalation_type == "escalate_to_expert":
        # Step 1: 提取已获取的数据
        existing_data = extract_data_context(agent_response)
        
        # Step 2: 路由到Expert Agent
        return expert_agent.analyze(
            original_query,
            data_context=existing_data
        )
    
    # ... 其他escalation类型
```

**流程图**:
```
用户Query: "为什么接口有错误?"
  ↓
Guard → SIMPLE (置信度 0.82, 边缘case)
  ↓
Query Agent → 查询接口错误数据
  └─ 发现: "有100+错误，但不知道原因"
  └─ 返回: <escalate_to_expert>原因不明，需要RCA</escalate_to_expert>
  ↓
Orchestrator检测到escalation
  ↓
重新路由 → Expert Agent
  ├─ 输入: 原始query + Query Agent的数据
  └─ 输出: "根因分析：光模块老化..."
  ↓
Orchestrator汇总
  └─ 最终答案 = Query数据 + Expert分析
```

##### **职责3: 多轮对话和上下文管理**

**场景**:
- 用户追问："上面的设备有哪些接口？"
- 参考前文："R1的那个错误解决了吗？"
- 上下文延续："继续分析"

**技术实现**:
```python
class OrchestratorContext:
    """Orchestrator维护的会话上下文。"""
    
    def __init__(self, thread_id: str):
        self.thread_id = thread_id
        self.conversation_history: list[dict] = []
        self.last_query_result: dict | None = None
        self.referenced_entities: dict[str, Any] = {}  # "R1", "那个错误"
        
    def add_turn(self, query: str, response: dict):
        """添加对话轮次。"""
        self.conversation_history.append({
            "query": query,
            "response": response,
            "timestamp": datetime.now()
        })
        
        # 提取实体引用
        self._extract_entities(query, response)
    
    def resolve_reference(self, query: str) -> str:
        """解析指代消解。
        
        Examples:
        - "上面的设备" → self.last_query_result["devices"]
        - "R1的那个错误" → self.referenced_entities["R1"]["errors"][0]
        """
        if "上面" in query or "上述" in query:
            # 引用上一轮结果
            return self._inject_last_result(query)
        
        if "那个" in query or "这个" in query:
            # 指代消解
            return self._resolve_demonstrative(query)
        
        return query
```

**示例对话**:
```
Turn 1:
User: "有多少个设备?"
Orchestrator: Guard → SIMPLE → Query Agent
Response: "6个设备"
Context: devices = [R1, R2, R3, R4, SW1, SW2]

Turn 2:
User: "上面的设备有哪些接口?" (指代消解)
Orchestrator: 
  1. resolve_reference() → "R1,R2,R3,R4,SW1,SW2有哪些接口?"
  2. Guard → SIMPLE → Query Agent
Response: "总计48个接口，详情..."

Turn 3:
User: "R1的接口有错误吗?" (实体引用)
Orchestrator:
  1. 检测到"R1"在上下文中
  2. Guard → SIMPLE → Query Agent
Response: "R1的Gi0/1有3个input errors"
Context: R1.errors = {"Gi0/1": 3}

Turn 4:
User: "为什么?" (省略主语，需要上下文)
Orchestrator:
  1. resolve_reference() → "为什么R1的Gi0/1有errors?"
  2. Guard → EXPERT (分析类查询)
  3. Expert Agent分析
Response: "根因：光模块老化导致CRC错误..."
```

##### **职责4: Multi-agent协调（复杂任务分解）**

**触发条件**:
- 任务需要多个SubAgent协作
- 数据需要跨Agent整合
- 顺序/并行执行优化

**示例场景1: 顺序协调**
```
Query: "导出所有接口错误超过10的设备配置"

Orchestrator协调:
Step 1: Query Agent → 查询接口错误 > 10的设备
  └─ Result: [R1, R3]

Step 2: CLI Agent → 获取R1, R3的running-config
  └─ Result: {R1: "config...", R3: "config..."}

Step 3: Query Agent (export tool) → 格式化为CSV
  └─ Result: "configs_export.csv"

Orchestrator汇总: "已导出2个设备配置到configs_export.csv"
```

**示例场景2: 并行协调**
```
Query: "生成网络健康报告"

Orchestrator并行协调:
┌─ Query Agent → 设备统计
├─ Query Agent → 接口统计  
├─ Expert Agent → 拓扑分析
└─ CLI Agent → 实时CPU/内存

等待所有完成 (asyncio.gather)
  ↓
Orchestrator汇总:
  - 设备: 6台 (5 up, 1 down)
  - 接口: 48个 (45 up, 3 down)
  - 拓扑: OSPF稳定，BGP有1个session down
  - 资源: 平均CPU 23%, 内存 45%
  
生成报告: "network_health_report.md"
```

**示例场景3: 跨系统协调（MULTI_AGENT路由 - 未来场景）**

🎯 **Orchestrator的核心定位**: Multi-agent跨系统协调引擎

当Guard识别为`MULTI_AGENT`类型时，Orchestrator发挥其核心价值——协调多个数据源/系统之间的交叉验证。

```
Query: "NetBox和数据库的设备信息是否一致?"

Guard分类:
  ├─ 检测关键词: "NetBox", "数据库", "是否一致"
  ├─ 匹配MULTI_AGENT_INDICATORS: "netbox.*vs.*database"
  └─ Route: MULTI_AGENT (conf=0.88)

Orchestrator Multi-agent协调:
  ┌─────────────────────────────────────────────┐
  │ Step 1: 并行查询两个数据源                    │
  │                                               │
  │   Thread 1: NetBox SubAgent                   │
  │   └─ API调用: GET /api/dcim/devices/          │
  │      └─ Result: [                            │
  │           {name: "R1", role: "core", ...},    │
  │           {name: "R2", role: "core", ...},    │
  │           {name: "SW1", role: "access", ...}  │
  │         ]                                     │
  │                                               │
  │   Thread 2: Query Agent (DuckDB)              │
  │   └─ SQL: SELECT * FROM devices              │
  │      └─ Result: [                            │
  │           {name: "R1", role: "core", ...},    │
  │           {name: "R3", role: "distribution"}, │
  │           {name: "SW1", role: "access", ...}  │
  │         ]                                     │
  └─────────────────────────────────────────────┘
                    ↓
  ┌─────────────────────────────────────────────┐
  │ Step 2: Orchestrator数据对比（核心能力）      │
  │                                               │
  │   对比算法:                                   │
  │   1. 设备名称对比 (name matching)             │
  │   2. 字段差异检测 (field diff)                │
  │   3. 缺失设备识别 (missing detection)         │
  │                                               │
  │   差异检测结果:                               │
  │   ✅ 一致: R1 (role: core)                   │
  │   ⚠️  差异: SW1 role不一致                   │
  │      - NetBox: "access"                      │
  │      - DuckDB: "access"                      │
  │   ❌ 缺失: R2 (仅在NetBox)                    │
  │   ❌ 缺失: R3 (仅在DuckDB)                    │
  └─────────────────────────────────────────────┘
                    ↓
  ┌─────────────────────────────────────────────┐
  │ Step 3: 生成对比报告                        │
  │                                               │
  │   Orchestrator汇总:                          │
  │   - 总设备: NetBox 3台, DuckDB 3台           │
  │   - 一致: 1台 (R1)                          │
  │   - 差异: 0台                               │
  │   - NetBox独有: 1台 (R2)                    │
  │   - DuckDB独有: 1台 (R3)                    │
  │                                               │
  │   建议: 同步R2到DuckDB, 确认R3是否已下线      │
  └─────────────────────────────────────────────┘
```

**更多未来场景（MULTI_AGENT路由）**:

```
Scenario 1: IP地址管理对比
Query: "验证DNS解析与实际IP配置是否一致"

Orchestrator协调:
  ├─ DNS SubAgent → 查询域名解析
  ├─ CLI Agent → 查询接口IP配置
  └─ Orchestrator → 对比并生成不一致报告

Scenario 2: 配置合规性检查
Query: "对比数据库快照和实时配置的差异"

Orchestrator协调:
  ├─ Query Agent → 读取历史配置快照（database）
  ├─ CLI Agent → 获取当前running-config（real-time）
  └─ Orchestrator → Diff算法 + 高亮变更

Scenario 3: 跨CMDB验证
Query: "交叉检查CMDB和网络拓扑的一致性"

Orchestrator协调:
  ├─ CMDB SubAgent → 查询服务器-交换机连接关系
  ├─ Query Agent → 查询LLDP拓扑（v_lldp view）
  └─ Orchestrator → 检测物理连接与CMDB登记的差异
```

**Orchestrator的Multi-agent协调能力矩阵**:

| 协调类型 | 数据源数量 | 执行模式 | 复杂度 | 应用场景 |
|---------|----------|---------|--------|---------|
| **单源单Agent** | 1 | 直接路由 | 低 | Guard直达（90%） |
| **单源多Agent** | 1 | 顺序/escalation | 中 | Query → Expert |
| **多源并行** | 2+ | 并行查询 | 中 | 健康报告生成 |
| **多源对比** | 2+ | 并行+Diff | 高 | NetBox vs DB ⭐ |
| **多源融合** | 3+ | 并行+Merge | 高 | CMDB+DNS+Topo |

**🔑 为什么MULTI_AGENT类型对未来至关重要？**

1. **可扩展性**: 每增加一个SubAgent（NetBox, IPAM, CMDB），只需注册到Orchestrator
2. **隔离性**: 单个SubAgent只关注自己的数据源，Orchestrator负责集成
3. **测试性**: 可以单独测试每个SubAgent，Orchestrator的对比逻辑也独立
4. **性能**: 并行查询多个数据源，避免串行等待
5. **智能**: Orchestrator可以使用LLM分析差异、生成建议

**代码示例（未来实现）**:

```python
# src/olav/agents/orchestrator_multi_agent.py

async def handle_multi_agent_query(query: str) -> dict:
    """Handle MULTI_AGENT routed queries.
    
    Core capability: Coordinate multiple SubAgents and compare results.
    """
    
    # Step 1: 识别需要的SubAgents
    required_agents = identify_required_agents(query)
    # Example: ["netbox", "query"]
    
    # Step 2: 并行查询所有Agent
    async with asyncio.TaskGroup() as tg:
        tasks = {
            agent: tg.create_task(invoke_subagent(agent, query))
            for agent in required_agents
        }
    
    # Step 3: 收集结果
    results = {agent: task.result() for agent, task in tasks.items()}
    
    # Step 4: 数据对比/融合（Orchestrator核心能力）
    comparison = compare_multi_source_data(results)
    
    # Step 5: 生成报告
    return {
        "status": "complete",
        "final_answer": format_comparison_report(comparison),
        "comparison_details": comparison,
        "sources": list(results.keys())
    }


def compare_multi_source_data(results: dict) -> dict:
    """Compare data from multiple sources.
    
    This is Orchestrator's core value for MULTI_AGENT queries.
    """
    # Extract data from each source
    netbox_data = results.get("netbox", {}).get("data", [])
    db_data = results.get("query", {}).get("data", [])
    
    # Comparison logic
    matches = []
    diffs = []
    netbox_only = []
    db_only = []
    
    # Match by device name (or other key)
    netbox_devices = {d["name"]: d for d in netbox_data}
    db_devices = {d["name"]: d for d in db_data}
    
    all_device_names = set(netbox_devices.keys()) | set(db_devices.keys())
    
    for name in all_device_names:
        netbox_dev = netbox_devices.get(name)
        db_dev = db_devices.get(name)
        
        if netbox_dev and db_dev:
            # Both sources have this device
            diff = diff_devices(netbox_dev, db_dev)
            if diff:
                diffs.append({"name": name, "diff": diff})
            else:
                matches.append(name)
        elif netbox_dev:
            netbox_only.append(name)
        else:
            db_only.append(name)
    
    return {
        "matches": matches,
        "diffs": diffs,
        "netbox_only": netbox_only,
        "db_only": db_only,
        "summary": {
            "total_devices": len(all_device_names),
            "consistent": len(matches),
            "inconsistent": len(diffs),
            "missing_in_db": len(netbox_only),
            "missing_in_netbox": len(db_only)
        }
    }
```

**协调模式**:
```python
class MultiAgentCoordinator:
    """Multi-agent协调器。"""
    
    async def execute_sequential(self, tasks: list[Task]) -> list[Result]:
        """顺序执行（有依赖）。"""
        results = []
        context = {}
        
        for task in tasks:
            # 注入前序结果作为context
            result = await task.execute(context=context)
            results.append(result)
            context.update(result.context)
        
        return results
    
    async def execute_parallel(self, tasks: list[Task]) -> list[Result]:
        """并行执行（无依赖）。"""
        return await asyncio.gather(*[
            task.execute() for task in tasks
        ])
    
    async def execute_dag(self, dag: DAG) -> dict[str, Result]:
        """DAG执行（部分依赖）。"""
        # 拓扑排序 + 并行化
        return await dag.execute_optimized()
```

##### **职责5: 失败重试和降级处理**

**处理策略**:
```python
class FailureRecoveryPolicy:
    """故障恢复策略。"""
    
    RETRY_STRATEGIES = {
        # SubAgent失败 → 重试3次
        "agent_timeout": {
            "max_retries": 3,
            "backoff": "exponential",  # 1s, 2s, 4s
            "fallback": "downgrade_to_simple"
        },
        
        # LLM推理失败 → 降级到规则
        "llm_error": {
            "max_retries": 1,
            "fallback": "heuristic_fallback"
        },
        
        # 数据库查询失败 → 缓存 or CLI
        "database_error": {
            "max_retries": 2,
            "fallback": "cache_or_cli"
        },
        
        # Guard误判 → 降级到Orchestrator
        "guard_low_confidence": {
            "max_retries": 0,
            "fallback": "orchestrator_planning"
        }
    }


async def handle_agent_failure(
    agent: str,
    query: str,
    error: Exception,
    retry_count: int
) -> dict:
    """SubAgent失败处理。"""
    
    logger.error(f"Agent {agent} failed: {error}")
    
    # Step 1: 检查是否可重试
    if retry_count < 3:
        logger.info(f"Retrying {agent} (attempt {retry_count + 1}/3)")
        await asyncio.sleep(2 ** retry_count)  # Exponential backoff
        return await agent.execute(query)
    
    # Step 2: 降级处理
    logger.warning(f"Max retries reached, downgrading...")
    
    if agent == "Expert" and "query" in query.lower():
        # Expert失败 → 降级到Query Agent
        return await query_agent.execute(query)
    
    elif agent == "Query" and "<cli_needed>" not in error.message:
        # Query失败（非schema问题）→ 降级到简单统计
        return {
            "status": "downgraded",
            "final_answer": "查询部分失败，仅返回基础统计...",
            "error_message": str(error)
        }
    
    # Step 3: 无法降级 → 返回错误
    return {
        "status": "failed",
        "final_answer": f"查询失败: {str(error)}",
        "error_message": str(error)
    }
```

**降级路径**:
```
Expert失败 → Query Agent (简化分析)
  ↓ 失败
Query Agent → Heuristic Rules (统计规则)
  ↓ 失败
Heuristic → Error Message (告知用户)
```

##### **职责6: 结果汇总和格式化**

**功能**:
- 解析 `<export_format>` 标签
- 调用 `format_and_export` 工具
- 生成最终用户友好输出

**代码示例**:
```python
def finalize_response(
    agent_response: dict,
    original_query: str
) -> dict:
    """Orchestrator最终响应格式化。"""
    
    # Step 1: 检查是否需要导出
    export_pattern = r'<export_format>(.*?)</export_format>'
    export_match = re.search(export_pattern, agent_response["final_answer"])
    
    if export_match:
        export_format = export_match.group(1).strip()
        
        # 调用export工具
        from olav.tools.data_export import format_and_export
        
        export_result = format_and_export(
            data=agent_response["data"],
            format=export_format,
            query=original_query
        )
        
        # 更新响应
        agent_response["final_answer"] += f"\n\n已导出到: {export_result['file_path']}"
        agent_response["export_path"] = export_result["file_path"]
    
    # Step 2: 添加metadata
    agent_response["metadata"] = {
        "route": agent_response.get("route", "unknown"),
        "cache_hit": agent_response.get("cache_hit", False),
        "latency_ms": agent_response.get("latency_ms", 0),
        "timestamp": datetime.now().isoformat()
    }
    
    return agent_response
```

#### **3.3.3 职责边界（Guard vs Orchestrator）**

| 场景 | Guard职责 | Orchestrator职责 | 决策点 |
|------|----------|-----------------|--------|
| **简单查询（高置信度）** | ✅ 分类 + 路由 | ❌ 不参与 | Guard置信度 ≥ 0.85 |
| **简单查询（低置信度）** | ⚠️ 分类（不确定） | ✅ 智能规划 | Guard置信度 < 0.85 |
| **复杂查询（明确）** | ✅ 识别为EXPERT | ❌ 直接路由到Expert | Guard置信度 ≥ 0.85 |
| **复杂查询（模糊）** | ⚠️ UNKNOWN | ✅ 分解意图 + 规划 | Guard无法分类 |
| **跨系统协作（新增）** | ✅ 识别为MULTI_AGENT | ✅ 协调多数据源对比 | Guard检测跨系统关键词 |
| **Escalation** | ❌ 不处理 | ✅ 重新路由 | SubAgent返回标签 |
| **多轮对话** | ❌ 无状态（每轮独立分类） | ✅ 上下文管理 | Thread ID追踪 |
| **Multi-agent** | ⚠️ 识别(MULTI_AGENT) | ✅ 协调多Agent（核心） | 任务需要2+数据源 |
| **失败重试** | ❌ 不参与 | ✅ 重试 + 降级 | Agent执行失败 |

**关键变化（v0.12.0）**:
- 🆕 **MULTI_AGENT类型**: Guard可识别跨系统协作查询（对比、验证、交叉检查）
- 🎯 **Orchestrator定位强化**: 从"不确定查询fallback"升级为**Multi-agent协调核心引擎**
- 🚀 **未来可扩展**: NetBox, CMDB, IPAM等SubAgent仅需注册到Orchestrator

**决策流程图**:
```
用户Query
  ↓
Guard分类 (4阶段: 危险检测 → 缓存 → 启发式 → LLM)
  ↓
┌───────────────────────────────────────────────┐
│ 置信度 ≥ 0.85 → 直接路由 (85-90%)            │
├───────────────────────────────────────────────┤
│  ├─ REJECT      → 立即拒绝 (<10ms)            │
│  ├─ SIMPLE      → Query Agent (2-5秒)         │
│  ├─ CLI         → CLI Agent (3-6秒)           │
│  ├─ EXPERT      → Expert Agent (8-12秒)       │
│  └─ MULTI_AGENT → Orchestrator协调 (10-20秒)  │ ← 🆕 新增
│                    └─ 并行查询多数据源         │
│                    └─ 数据对比/融合            │
│                    └─ 生成对比报告             │
└───────────────────────────────────────────────┘
  ↓
SubAgent执行
  ├─ 成功 → 返回结果
  └─ Escalation → Orchestrator接管
      ├─ <cli_needed> → 重路由到CLI
      ├─ <escalate_to_expert> → 重路由到Expert
      └─ Failure → 重试/降级
  ↓
┌───────────────────────────────────────────────┐
│ 置信度 < 0.85 → Orchestrator规划 (10-15%)    │
├───────────────────────────────────────────────┤
│  └─ UNKNOWN     → 智能规划                    │
│      ├─ 分解意图                             │
│      ├─ 生成执行计划                         │
│      ├─ 协调Multi-agent                      │
│      ├─ 处理失败重试                         │
│      └─ 汇总结果                             │
└───────────────────────────────────────────────┘
```

**MULTI_AGENT路由示例流程**:
```
Query: "NetBox和数据库的设备信息是否一致?"
  ↓
Guard分类
  ├─ Stage 3: 启发式匹配MULTI_AGENT_INDICATORS
  │   └─ Regex匹配: "netbox.*vs.*database"
  └─ Result: MULTI_AGENT (conf=0.88)
  ↓
直接路由到Orchestrator（而非SubAgent）
  ↓
Orchestrator Multi-agent协调
  ├─ 识别需要的Agent: [NetBox, Query]
  ├─ 并行查询:
  │   ├─ NetBox SubAgent → API获取设备列表
  │   └─ Query Agent → DuckDB查询设备表
  ├─ 数据对比:
  │   ├─ 一致: R1, SW1
  │   ├─ NetBox独有: R2
  │   └─ DuckDB独有: R3
  └─ 生成对比报告（表格+建议）
```

#### **3.3.4 代码量对比（LOC = Lines of Code）**

| 模块 | 当前v0.11.x | Guard架构v0.12.0 | 变化 |
|------|------------|-----------------|------|
| **路由逻辑** | 450 LOC | 0 LOC (→ Guard) | -450 ❌ |
| **复杂度评分** | 150 LOC | 0 LOC (删除) | -150 ❌ |
| **Schema验证** | 80 LOC | 50 LOC (简化) | -30 🔻 |
| **Escalation处理** | 200 LOC | 300 LOC (增强) | +100 ✅ |
| **智能规划** | 100 LOC (隐式) | 400 LOC (显式) | +300 ✅ |
| **Multi-agent协调** | 50 LOC (有限) | 250 LOC (核心) | +200 ✅ |
| **上下文管理** | 120 LOC | 180 LOC (增强) | +60 ✅ |
| **失败重试** | 80 LOC | 150 LOC (增强) | +70 ✅ |
| **结果格式化** | 100 LOC | 120 LOC | +20 ✅ |
| **总计** | ~1330 LOC | ~1450 LOC | +120 (但职责更清晰) |

**关键变化**:
- ❌ **删除**: QueryComplexityScorer, 初始路由（600 LOC）
- ✅ **增强**: 智能规划, Multi-agent协调（720 LOC）
- 🎯 **净增**: +120 LOC，但**职责单一化**，**可测试性提升**

---

## 4. 核心组件设计

### 4.1 Guard Agent架构

#### **4.1.1 Guard的SKILL配置**

```yaml
# .olav/skills/guard/SKILL.md
---
name: query-guard
version: 1.0.0
description: |
  Query classification guard with semantic caching.
  Routes 90% of queries directly to SubAgents.
type: classifier
category: routing
intent: classification

tools:
  - check_dangerous_patterns   # 危险命令检测
  - query_semantic_cache       # 语义缓存查询
  - classify_query_fast        # 快速LLM分类

prompts:
  system: |
    You are a query classification specialist for network operations.
    
    **Your ONLY job**: Classify queries into 6 categories.
    
    ## Classification Categories
    
    ### 0. REJECT (危险/无关命令)
    - 危险操作: shutdown, reload, delete, format, erase
    - 无关话题: weather, stocks, recipes, jokes
    - 恶意请求: SQL injection, path traversal
    
    Response: <route>REJECT</route><confidence>1.0</confidence>
    Example: "shutdown all devices" → REJECT
    
    ### 1. SIMPLE (简单数据库查询)
    - 关键词: count, list, show, filter, export
    - 数据源: 设备清单, 接口状态, 配置快照
    - 无需推理: 直接SQL即可解决
    
    Response: <route>SIMPLE</route><confidence>0.90</confidence>
    Examples:
    - "有多少个设备?" → SIMPLE
    - "列出所有core设备" → SIMPLE
    - "导出接口信息到CSV" → SIMPLE
    
    ### 2. CLI (实时设备数据)
    - 关键词: real-time, current, now, 实时, 当前
    - 数据源: 设备CLI命令
    - 动态性: 需要最新状态，数据库可能过期
    
    Response: <route>CLI</route><confidence>0.85</confidence>
    Examples:
    - "R1当前CPU使用率" → CLI
    - "BGP session状态" → CLI
    - "show running-config实时output" → CLI
    
    ### 3. EXPERT (复杂分析/诊断)
    - 关键词: why, analyze, diagnose, optimize, recommend
    - 任务: RCA, 设计建议, 故障排查, 性能优化
    - 推理深度: 需要CCIE级别专业知识
    
    Response: <route>EXPERT</route><confidence>0.90</confidence>
    Examples:
    - "为什么OSPF邻居不稳定?" → EXPERT
    - "如何优化VLAN设计?" → EXPERT
    - "诊断BGP路由黑洞" → EXPERT
    
    ### 4. MULTI_AGENT (多Agent协作任务)
    - 关键词: compare, verify, cross-check, validate, 对比, 验证, 交叉检查
    - 数据源: 需要多个数据源/系统协作
    - 场景: NetBox vs Database, CLI vs Snapshot, IP vs DNS
    
    Response: <route>MULTI_AGENT</route><confidence>0.88</confidence>
    Examples:
    - "NetBox和数据库的设备信息是否一致?" → MULTI_AGENT
    - "对比数据库记录和实时CLI输出" → MULTI_AGENT
    - "验证DNS解析与实际IP配置" → MULTI_AGENT
    - "交叉检查CMDB和网络拓扑" → MULTI_AGENT
    
    ⚠️ **CRITICAL**: MULTI_AGENT is the FUTURE-PROOF category!
    When in doubt between EXPERT and multi-data-source, choose MULTI_AGENT.
    Orchestrator is specifically designed as Multi-agent coordinator.
    
    ### 5. UNKNOWN (不确定/多意图)
    - 模糊查询: "帮我看看网络"
    - 多步骤: "先查设备，再分析问题"
    - 需要规划: 无法一次性分类
    
    Response: <route>UNKNOWN</route><confidence>0.30</confidence>
    Example: "网络有什么问题?" → UNKNOWN
    
    ## Response Format (CRITICAL)
    
    You MUST respond in this exact format:
    
    ```xml
    <route>CATEGORY</route>
    <confidence>0.0-1.0</confidence>
    <reasoning>One sentence explanation</reasoning>
    ```
    
    ## Classification Rules
    
    1. **Always include all 3 tags** (route, confidence, reasoning)
    2. **Confidence >= 0.85 → Direct routing** (fast path)
    3. **Confidence < 0.85 → Fallback to Orchestrator**
    4. **When unsure → UNKNOWN** (let Orchestrator plan)
    5. **Safety first → REJECT** (even with 1% doubt)
    
    ## Examples
    
    Query: "有多少个设备?"
    ```xml
    <route>SIMPLE</route>
    <confidence>0.95</confidence>
    <reasoning>Simple count query, database has devices table</reasoning>
    ```
    
    Query: "为什么BGP不通?"
    ```xml
    <route>EXPERT</route>
    <confidence>0.92</confidence>
    <reasoning>Root cause analysis needs expert diagnosis</reasoning>
    ```
    
    Query: "shutdown all routers"
    ```xml
    <route>REJECT</route>
    <confidence>1.0</confidence>
    <reasoning>Dangerous command, shutdown operation not allowed</reasoning>
    ```
    
    Query: "网络怎么样?"
    ```xml
    <route>UNKNOWN</route>
    <confidence>0.40</confidence>
    <reasoning>Vague query, needs clarification or planning</reasoning>
    ```
---
```

#### **4.1.2 Guard核心代码**

```python
# src/olav/agents/guard.py

from dataclasses import dataclass
from enum import Enum
from typing import Any
import re

from langchain_core.messages import HumanMessage
from deepagents import create_deep_agent
from langgraph.checkpoint.duckdb import DuckDBSaver

from config.paths import get_checkpoint_path
from config.settings import settings
from olav.core.llm import LLMFactory
from olav.core.logging_config import get_logger

logger = get_logger(__name__)


class RouteCode(Enum):
    """Query route categories."""
    REJECT = "REJECT"           # 危险/无关命令
    SIMPLE = "SIMPLE"           # 简单数据库查询
    CLI = "CLI"                 # 实时设备数据
    EXPERT = "EXPERT"           # 复杂分析诊断
    MULTI_AGENT = "MULTI_AGENT" # 多Agent协作任务（未来扩展关键）
    UNKNOWN = "UNKNOWN"         # 不确定，需要Orchestrator规划


@dataclass
class RouteDecision:
    """Guard routing decision."""
    code: RouteCode
    confidence: float      # 0.0-1.0
    reasoning: str
    cache_hit: bool = False
    
    def should_direct_route(self) -> bool:
        """Check if confidence is high enough for direct routing."""
        return self.confidence >= 0.85


class QueryGuard:
    """Query classification guard with semantic caching.
    
    Responsibilities:
    1. Dangerous command detection (rule-based, <10ms)
    2. Semantic cache lookup (DuckDB, 10-50ms)
    3. Fast LLM classification (1-2 seconds)
    4. Confidence-based routing decision
    
    Design Principles:
    - Fast first: Try cache before LLM
    - Safety first: Reject dangerous patterns immediately
    - Simple first: Most queries (70%) should be SIMPLE
    - Defer uncertainty: Unknown queries go to Orchestrator
    """
    
    # Dangerous command patterns (regex)
    DANGEROUS_PATTERNS = [
        r'\b(shutdown|reload|reboot|restart|erase|format|delete)\b',
        r'\bno\s+(ip|interface|routing|vlan)',  # Cisco 'no' commands
        r'\brm\s+-rf\b',  # Unix deletion
        r'\bdrop\s+(table|database)\b',  # SQL injection
        r'\b(inject|exploit|hack)\b',
    ]
    
    # Simple query indicators (regex)
    SIMPLE_INDICATORS = [
        r'^(count|list|show|display|export|save)\b',
        r'\b(how many|多少|几个)\b',
        r'\ball\s+(devices|interfaces|routers|switches)\b',
    ]
    
    # CLI query indicators
    CLI_INDICATORS = [
        r'\b(real-time|realtime|current|now|live|实时|当前)\b',
        r'\b(cpu|memory|bandwidth|utilization)\s+(usage|used)\b',
        r'\bshow\s+(running-config|startup-config|version)\b',
    ]
    
    # Expert query indicators
    EXPERT_INDICATORS = [
        r'^(why|how to|analyze|diagnose|optimize|recommend|为什么|如何|分析|诊断|优化)\b',
        r'\b(root cause|rca|troubleshooting|故障排查)\b',
        r'\b(design|architecture|best practice|最佳实践)\b',
    ]
    
    # Multi-agent query indicators (FUTURE-PROOF for NetBox, CMDB, etc.)
    MULTI_AGENT_INDICATORS = [
        r'\b(compare|verify|cross-check|validate|对比|验证|交叉检查|一致性)\b',
        r'\b(netbox|cmdb|dns|ipam)\s+(vs|versus|和|与)\b',
        r'\b(database|db)\s+(vs|versus|和|与)\s+(cli|real-time|实时)\b',
        r'\b(snapshot|历史)\s+(vs|versus|和|与)\s+(current|当前|实时)\b',
    ]
    
    def __init__(self):
        """Initialize Guard with LLM and cache."""
        self.llm = LLMFactory.get_chat_model(temperature=0.1)  # Low temp for consistency
        
        # Initialize semantic cache (DuckDB checkpointer)
        import duckdb
        checkpoint_path = get_checkpoint_path("guard")
        self.cache_conn = duckdb.connect(str(checkpoint_path))
        self.checkpointer = DuckDBSaver(self.cache_conn)
        
        # Initialize cache table if not exists
        self._init_cache_table()
        
        logger.info("🛡️ Guard initialized with semantic caching")
    
    def _init_cache_table(self):
        """Create semantic cache table."""
        self.cache_conn.execute("""
            CREATE TABLE IF NOT EXISTS query_classifications (
                query_hash VARCHAR PRIMARY KEY,
                query_text VARCHAR,
                route_code VARCHAR,
                confidence FLOAT,
                reasoning VARCHAR,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                hit_count INTEGER DEFAULT 0
            )
        """)
        self.cache_conn.commit()
    
    def classify(self, query: str) -> RouteDecision:
        """Classify query with multi-stage approach.
        
        Stage 1: Dangerous pattern check (rule-based, <10ms)
        Stage 2: Semantic cache lookup (10-50ms)
        Stage 3: Fast heuristic check (regex, <5ms)
        Stage 4: LLM classification (1-2 seconds)
        
        Args:
            query: User's natural language query
            
        Returns:
            RouteDecision with code, confidence, reasoning
        """
        query_lower = query.lower()
        
        # ═══════════════════════════════════════════════════════
        # STAGE 1: Dangerous Pattern Check (Rule-based)
        # ═══════════════════════════════════════════════════════
        if self._is_dangerous(query_lower):
            logger.warning(f"🚫 Dangerous pattern detected: {query[:50]}...")
            return RouteDecision(
                code=RouteCode.REJECT,
                confidence=1.0,
                reasoning="Dangerous operation detected",
                cache_hit=False
            )
        
        # ═══════════════════════════════════════════════════════
        # STAGE 2: Semantic Cache Lookup
        # ═══════════════════════════════════════════════════════
        cache_result = self._check_cache(query)
        if cache_result:
            logger.info(f"⚡ Cache hit: {query[:50]}... → {cache_result.code.value}")
            return cache_result
        
        # ═══════════════════════════════════════════════════════
        # STAGE 3: Fast Heuristic Check (Regex)
        # ═══════════════════════════════════════════════════════
        heuristic_result = self._fast_heuristic_check(query_lower)
        if heuristic_result and heuristic_result.confidence >= 0.85:
            logger.info(f"🎯 Heuristic match: {query[:50]}... → {heuristic_result.code.value}")
            self._cache_decision(query, heuristic_result)
            return heuristic_result
        
        # ═══════════════════════════════════════════════════════
        # STAGE 4: LLM Classification (Fallback)
        # ═══════════════════════════════════════════════════════
        logger.debug(f"🤖 LLM classification: {query[:50]}...")
        llm_result = self._llm_classify(query)
        self._cache_decision(query, llm_result)
        return llm_result
    
    def _is_dangerous(self, query: str) -> bool:
        """Check if query matches dangerous patterns."""
        for pattern in self.DANGEROUS_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return True
        return False
    
    def _check_cache(self, query: str) -> RouteDecision | None:
        """Check semantic cache for similar queries.
        
        Strategy:
        1. Exact match (query_text = ?)
        2. Fuzzy match (Levenshtein distance < 3)
        3. Semantic embedding (future: vector similarity)
        """
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        result = self.cache_conn.execute("""
            SELECT route_code, confidence, reasoning, hit_count
            FROM query_classifications
            WHERE query_hash = ?
            AND timestamp > NOW() - INTERVAL '1 hour'
        """, [query_hash]).fetchone()
        
        if result:
            route_code, confidence, reasoning, hit_count = result
            
            # Update hit count
            self.cache_conn.execute("""
                UPDATE query_classifications
                SET hit_count = hit_count + 1
                WHERE query_hash = ?
            """, [query_hash])
            self.cache_conn.commit()
            
            return RouteDecision(
                code=RouteCode(route_code),
                confidence=confidence,
                reasoning=reasoning,
                cache_hit=True
            )
        
        return None
    
    def _fast_heuristic_check(self, query: str) -> RouteDecision | None:
        """Fast regex-based heuristic classification.
        
        Returns decision only if confidence >= 0.85.
        Otherwise returns None (fallback to LLM).
        """
        # Check SIMPLE indicators
        for pattern in self.SIMPLE_INDICATORS:
            if re.search(pattern, query, re.IGNORECASE):
                return RouteDecision(
                    code=RouteCode.SIMPLE,
                    confidence=0.90,
                    reasoning="Simple query pattern detected (heuristic)",
                    cache_hit=False
                )
        
        # Check CLI indicators
        for pattern in self.CLI_INDICATORS:
            if re.search(pattern, query, re.IGNORECASE):
                return RouteDecision(
                    code=RouteCode.CLI,
                    confidence=0.88,
                    reasoning="CLI real-time data indicator (heuristic)",
                    cache_hit=False
                )
        
        # Check MULTI_AGENT indicators (BEFORE EXPERT - priority for cross-system)
        for pattern in self.MULTI_AGENT_INDICATORS:
            if re.search(pattern, query, re.IGNORECASE):
                return RouteDecision(
                    code=RouteCode.MULTI_AGENT,
                    confidence=0.88,
                    reasoning="Multi-agent cross-system query detected (heuristic)",
                    cache_hit=False
                )
        
        # Check EXPERT indicators
        for pattern in self.EXPERT_INDICATORS:
            if re.search(pattern, query, re.IGNORECASE):
                return RouteDecision(
                    code=RouteCode.EXPERT,
                    confidence=0.87,
                    reasoning="Expert analysis keyword detected (heuristic)",
                    cache_hit=False
                )
        
        return None
    
    def _llm_classify(self, query: str) -> RouteDecision:
        """LLM-based classification (slowest, most accurate)."""
        from pathlib import Path
        
        # Load Guard SKILL.md prompt
        skill_path = Path(".olav/skills/guard/SKILL.md")
        if skill_path.exists():
            with open(skill_path, 'r', encoding='utf-8') as f:
                skill_content = f.read()
                # Extract prompt (after frontmatter)
                if '---' in skill_content:
                    parts = skill_content.split('---')
                    if len(parts) >= 3:
                        system_prompt = parts[2].strip()
                    else:
                        system_prompt = skill_content
                else:
                    system_prompt = skill_content
        else:
            # Fallback to inline prompt
            system_prompt = """Classify this query into: REJECT, SIMPLE, CLI, EXPERT, UNKNOWN.
            
Response format:
<route>CATEGORY</route>
<confidence>0.0-1.0</confidence>
<reasoning>explanation</reasoning>"""
        
        user_message = f"{system_prompt}\n\nQuery: {query}"
        
        response = self.llm.invoke([HumanMessage(content=user_message)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        
        # Parse response
        route_match = re.search(r'<route>(.*?)</route>', response_text, re.IGNORECASE)
        conf_match = re.search(r'<confidence>(.*?)</confidence>', response_text, re.IGNORECASE)
        reason_match = re.search(r'<reasoning>(.*?)</reasoning>', response_text, re.IGNORECASE | re.DOTALL)
        
        if not (route_match and conf_match):
            logger.warning(f"⚠️ LLM classification failed to parse: {response_text[:100]}")
            return RouteDecision(
                code=RouteCode.UNKNOWN,
                confidence=0.30,
                reasoning="LLM parsing failed, defaulting to Orchestrator",
                cache_hit=False
            )
        
        route_str = route_match.group(1).strip().upper()
        try:
            route_code = RouteCode(route_str)
        except ValueError:
            logger.warning(f"⚠️ Invalid route code: {route_str}")
            route_code = RouteCode.UNKNOWN
        
        try:
            confidence = float(conf_match.group(1).strip())
            confidence = max(0.0, min(1.0, confidence))  # Clamp
        except ValueError:
            confidence = 0.50
        
        reasoning = reason_match.group(1).strip() if reason_match else "No reasoning provided"
        
        return RouteDecision(
            code=route_code,
            confidence=confidence,
            reasoning=reasoning,
            cache_hit=False
        )
    
    def _cache_decision(self, query: str, decision: RouteDecision):
        """Save classification to cache."""
        import hashlib
        query_hash = hashlib.md5(query.encode()).hexdigest()
        
        self.cache_conn.execute("""
            INSERT OR REPLACE INTO query_classifications 
            (query_hash, query_text, route_code, confidence, reasoning, timestamp, hit_count)
            VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, 0)
        """, [
            query_hash,
            query,
            decision.code.value,
            decision.confidence,
            decision.reasoning
        ])
        self.cache_conn.commit()
    
    def get_cache_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        result = self.cache_conn.execute("""
            SELECT 
                COUNT(*) as total_entries,
                SUM(hit_count) as total_hits,
                AVG(confidence) as avg_confidence
            FROM query_classifications
            WHERE timestamp > NOW() - INTERVAL '24 hours'
        """).fetchone()
        
        if result:
            total_entries, total_hits, avg_confidence = result
            hit_rate = (total_hits / total_entries * 100) if total_entries > 0 else 0
            
            return {
                "total_entries": total_entries,
                "total_hits": total_hits,
                "hit_rate_pct": round(hit_rate, 2),
                "avg_confidence": round(avg_confidence, 3) if avg_confidence else 0
            }
        
        return {
            "total_entries": 0,
            "total_hits": 0,
            "hit_rate_pct": 0,
            "avg_confidence": 0
        }


# ═══════════════════════════════════════════════════════════
# Module-level singleton
# ═══════════════════════════════════════════════════════════

_guard_instance: QueryGuard | None = None


def get_guard() -> QueryGuard:
    """Get singleton Guard instance."""
    global _guard_instance
    if _guard_instance is None:
        _guard_instance = QueryGuard()
    return _guard_instance
```

### 4.2 简化后的Orchestrator

```python
# src/olav/agents/orchestrator_v2.py (新版本)

from typing import Any
from olav.agents.guard import get_guard, RouteCode
from olav.agents.query_agent import QueryAgent
from olav.core.logging_config import get_logger

logger = get_logger(__name__)


def orchestrate_with_guard(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Guard-first orchestration with fallback to intelligent planning.
    
    Architecture:
    
    Layer 1: Guard (90% of queries)
      ├─ REJECT → Return rejection immediately
      ├─ SIMPLE → Query Agent (direct route)
      ├─ CLI    → CLI Agent (direct route)
      ├─ EXPERT → Expert Agent (direct route)
      └─ UNKNOWN → Fallback to Layer 2
    
    Layer 2: Orchestrator (10% of queries)
      ├─ Intelligent planning
      ├─ Multi-step reasoning
      └─ Escalation handling
    
    Args:
        user_query: User's natural language query
        user_id: User identifier
        thread_id: Thread identifier
        
    Returns:
        Dictionary with status, final_answer, error_message
    """
    logger.info(f"🚀 [Orchestrate] Guard-first routing: {user_query[:50]}...")
    
    # ═══════════════════════════════════════════════════════
    # LAYER 1: Guard Classification
    # ═══════════════════════════════════════════════════════
    guard = get_guard()
    route = guard.classify(user_query)
    
    logger.info(
        f"  🛡️ Guard: {route.code.value} "
        f"(conf={route.confidence:.2f}, "
        f"cache={route.cache_hit})"
    )
    
    # ───────────────────────────────────────────────────────
    # High Confidence → Direct Routing (90%)
    # ───────────────────────────────────────────────────────
    if route.should_direct_route():
        logger.info(f"  ⚡ Fast path: Direct routing to {route.code.value}")
        
        # REJECT: Return immediately
        if route.code == RouteCode.REJECT:
            return {
                "status": "rejected",
                "final_answer": (
                    f"🚫 Query rejected: {route.reasoning}\n\n"
                    f"I'm a network operations assistant and cannot process "
                    f"dangerous or unrelated commands. Please rephrase your query."
                ),
                "error_message": f"Rejected by Guard: {route.reasoning}",
            }
        
        # SIMPLE: Query Agent
        elif route.code == RouteCode.SIMPLE:
            result = _route_to_query_agent(user_query, user_id, thread_id)
            
            # Check for escalation requests
            if result["status"] == "needs_cli_data":
                logger.info("  🔄 Query Agent requested CLI escalation")
                return _route_to_cli_agent(user_query, user_id, thread_id)
            elif result["status"] == "needs_expert":
                logger.info("  🔄 Query Agent requested Expert escalation")
                return _route_to_expert_agent(user_query, user_id, thread_id)
            
            return result
        
        # CLI: CLI Agent
        elif route.code == RouteCode.CLI:
            return _route_to_cli_agent(user_query, user_id, thread_id)
        
        # EXPERT: Expert Agent
        elif route.code == RouteCode.EXPERT:
            return _route_to_expert_agent(user_query, user_id, thread_id)
    
    # ───────────────────────────────────────────────────────
    # Low Confidence → Orchestrator Planning (10%)
    # ───────────────────────────────────────────────────────
    logger.info(
        f"  🤔 Low confidence ({route.confidence:.2f}), "
        f"fallback to Orchestrator planning"
    )
    return _orchestrator_planning_fallback(user_query, user_id, thread_id)


def _route_to_query_agent(
    query: str,
    user_id: str | None,
    thread_id: str | None
) -> dict[str, Any]:
    """Route to Query Agent (simplified)."""
    logger.debug("  → Query Agent...")
    
    # Use existing orchestrate_query_sync but skip complexity scoring
    from olav.agents.orchestrator import orchestrate_query_sync
    
    # TODO: Refactor orchestrate_query_sync to accept skip_scoring=True
    return orchestrate_query_sync(query, user_id, thread_id)


def _route_to_cli_agent(
    query: str,
    user_id: str | None,
    thread_id: str | None
) -> dict[str, Any]:
    """Route to CLI Agent for real-time data."""
    logger.debug("  → CLI Agent...")
    
    # TODO: Implement CLI Agent route
    return {
        "status": "not_implemented",
        "final_answer": "CLI Agent routing not yet implemented",
        "error_message": "",
    }


def _route_to_expert_agent(
    query: str,
    user_id: str | None,
    thread_id: str | None
) -> dict[str, Any]:
    """Route to Expert Agent for complex analysis."""
    logger.debug("  → Expert Agent...")
    
    # Use existing Expert routing from orchestrate_query_sync
    from olav.agents.orchestrator import orchestrate_query_sync
    
    # Force expert mode by setting high complexity score
    return orchestrate_query_sync(query, user_id, thread_id)


def _orchestrator_planning_fallback(
    query: str,
    user_id: str | None,
    thread_id: str | None
) -> dict[str, Any]:
    """Fallback to full Orchestrator intelligence."""
    logger.debug("  → Orchestrator Planning Mode...")
    
    # Use existing orchestrate_query_sync with full logic
    from olav.agents.orchestrator import orchestrate_query_sync
    return orchestrate_query_sync(query, user_id, thread_id)
```

---

## 5. 路由决策算法

### 5.1 分类决策树

```
┌─────────────────────────────────────────────────────────┐
│ Query Input: "有多少个设备?"                             │
└────────────────────┬────────────────────────────────────┘
                     ↓
        ┌────────────────────────────┐
        │ Stage 1: Dangerous Check   │
        │ Regex: DANGEROUS_PATTERNS  │
        │ Time: <10ms                │
        └────────┬───────────────────┘
                 │ Not dangerous
                 ↓
        ┌────────────────────────────┐
        │ Stage 2: Cache Lookup      │
        │ DuckDB: query_hash         │
        │ Time: 10-50ms              │
        └────────┬───────────────────┘
                 │ Cache miss
                 ↓
        ┌────────────────────────────┐
        │ Stage 3: Heuristic Check   │
        │ Regex: SIMPLE_INDICATORS   │
        │ Time: <5ms                 │
        └────────┬───────────────────┘
                 │ Match: "有多少"
                 ↓
        ┌────────────────────────────┐
        │ Result: SIMPLE             │
        │ Confidence: 0.90           │
        │ Cache: Save to DuckDB      │
        └────────┬───────────────────┘
                 ↓
        ┌────────────────────────────┐
        │ Decision: Direct Route     │
        │ Target: Query Agent        │
        │ Expected: 3-5 seconds      │
        └────────────────────────────┘
```

### 5.2 置信度阈值设计

```python
# Confidence thresholds
CONFIDENCE_THRESHOLDS = {
    "direct_route": 0.85,    # High confidence → Direct to SubAgent
    "uncertain": 0.50,       # Medium → Could be either
    "orchestrator": 0.85,    # Low → Fallback to Orchestrator
}

# Route confidence targets (design goals)
ROUTE_CONFIDENCE_TARGETS = {
    RouteCode.REJECT: 0.95,  # Safety critical
    RouteCode.SIMPLE: 0.90,  # High accuracy needed
    RouteCode.CLI: 0.88,     # Some ambiguity ok
    RouteCode.EXPERT: 0.87,  # Better over-route than under
    RouteCode.UNKNOWN: 0.40, # Explicitly low
}
```

### 5.3 分类准确性目标

| Route | Precision (正确率) | Recall (召回率) | F1-Score | 业务影响 |
|-------|-------------------|----------------|----------|---------|
| REJECT | 100% | 95% | 0.97 | 误拒严重 ❌ |
| SIMPLE | 90% | 85% | 0.87 | 误判可重试 🟡 |
| CLI | 85% | 80% | 0.82 | 数据过期风险 🟡 |
| EXPERT | 88% | 90% | 0.89 | 过度路由ok ✅ |
| UNKNOWN | N/A | N/A | N/A | 兜底机制 ✅ |

**解读**:
- **REJECT**: 必须100%正确（不能误杀正常查询）
- **SIMPLE**: 允许10%误判（失败后可escalate）
- **EXPERT**: 宁可over-route（Expert能处理简单query）

---

## 6. 缓存策略

### 6.1 缓存层次架构

```
┌─────────────────────────────────────────────────────┐
│ L1: 危险命令缓存 (In-Memory Set)                     │
│   - TTL: Infinite (static blacklist)                │
│   - Hit Rate: 2-5%                                   │
│   - Latency: <1ms                                    │
└─────────────────────────────────────────────────────┘
                     ↓ (miss)
┌─────────────────────────────────────────────────────┐
│ L2: 语义分类缓存 (DuckDB)                            │
│   - TTL: 1 hour (configurable)                      │
│   - Hit Rate: 40-60% (repeat queries)                │
│   - Latency: 10-50ms                                 │
│   - Storage: query_classifications table             │
└─────────────────────────────────────────────────────┘
                     ↓ (miss)
┌─────────────────────────────────────────────────────┐
│ L3: SubAgent执行缓存 (DeepAgents DuckDBSaver)        │
│   - TTL: Per tool (e.g., query_database: 5 min)     │
│   - Hit Rate: 30-40%                                 │
│   - Latency: 50-100ms                                │
│   - Storage: LangGraph checkpointer                  │
└─────────────────────────────────────────────────────┘
```

### 6.2 缓存失效策略

```python
# Cache TTL Configuration
CACHE_TTL = {
    # Guard classification cache
    "classification": {
        RouteCode.REJECT: 86400,    # 24 hours (stable blacklist)
        RouteCode.SIMPLE: 3600,     # 1 hour (data may change)
        RouteCode.CLI: 300,         # 5 minutes (volatile)
        RouteCode.EXPERT: 7200,     # 2 hours (analysis stable)
        RouteCode.UNKNOWN: 1800,    # 30 minutes (may clarify)
    },
    
    # SubAgent execution cache
    "execution": {
        "query_database": 300,      # 5 minutes (data freshness)
        "inspect_schema": 3600,     # 1 hour (schema rarely changes)
        "cli_execute": 60,          # 1 minute (real-time data)
        "expert_analysis": 7200,    # 2 hours (analysis reusable)
    }
}


# Cache invalidation triggers
class CacheInvalidationTrigger:
    """Events that should invalidate cache."""
    
    DATABASE_UPDATE = "db_update"      # New snapshot imported
    CONFIG_CHANGE = "config_change"    # Device config modified
    TOPOLOGY_CHANGE = "topo_change"    # Network topology altered
    MANUAL_CLEAR = "manual_clear"      # User explicit clear
```

### 6.3 缓存预热策略

```python
# Preload common queries at startup
PRELOAD_QUERIES = [
    "有多少个设备?",
    "列出所有设备",
    "show devices",
    "count devices",
    "list routers",
    "设备清单",
]


def preload_guard_cache():
    """Preload Guard cache with common queries."""
    guard = get_guard()
    
    for query in PRELOAD_QUERIES:
        logger.debug(f"Preloading: {query}")
        guard.classify(query)  # Force classification and cache
    
    stats = guard.get_cache_stats()
    logger.info(f"✅ Guard cache preloaded: {stats['total_entries']} entries")
```

---

## 7. 性能预期

### 7.1 延迟对比表

| 查询类型 | 当前架构 | Guard架构 | 改进 | 备注 |
|---------|---------|-----------|------|------|
| **简单查询（缓存命中）** | 9-12秒 | **50-100ms** | **99% ⬇️** | L2缓存命中 |
| **简单查询（缓存未命中）** | 9-12秒 | **2-5秒** | **58-72% ⬇️** | 跳过复杂度评分 |
| **简单查询（启发式）** | 9-12秒 | **3-5秒** | **50-72% ⬇️** | 跳过LLM分类 |
| **CLI查询（缓存命中）** | 10-14秒 | **100-200ms** | **98% ⬇️** | 直达CLI Agent |
| **CLI查询（无缓存）** | 10-14秒 | **3-6秒** | **57-70% ⬇️** | 跳过复杂度评分 |
| **复杂查询（Expert）** | 12-18秒 | **8-15秒** | **22-33% ⬇️** | 跳过初始路由 |
| **不确定查询** | 12-18秒 | **12-18秒** | **0% 无变化** | 完整Orchestrator |
| **危险命令拒绝** | 8-12秒 | **<10ms** | **99.9% ⬇️** | 规则秒杀 |

### 7.2 吞吐量预期

```
并发查询测试 (100 queries, mixed workload)

当前架构:
- Avg latency: 11.2 seconds
- Throughput: ~9 queries/sec (parallel)
- Total time: ~11 seconds (100 queries)

Guard架构:
- Avg latency: 3.8 seconds (66% improvement)
- Throughput: ~26 queries/sec (parallel)
- Total time: ~4 seconds (100 queries)

Improvement: 2.8x throughput increase
```

### 7.3 缓存命中率预期

基于实际用户查询模式分析：

```python
# Query distribution in production (estimated)
QUERY_DISTRIBUTION = {
    "SIMPLE": 0.65,         # 65% - "count", "list", "show" (从70%调整)
    "CLI": 0.10,            # 10% - "real-time", "current"
    "EXPERT": 0.13,         # 13% - "why", "analyze", "optimize" (从15%调整)
    "MULTI_AGENT": 0.05,    # 5%  - "compare", "verify", "cross-check" (🆕 新增)
    "REJECT": 0.02,         # 2%  - dangerous/unrelated
    "UNKNOWN": 0.05,        # 5%  - ambiguous (从3%调整)
}

# Note: MULTI_AGENT initially 5%, expected to grow to 15-20% as NetBox, CMDB, IPAM integrate

# Repeat query patterns (same user asks same question)
REPEAT_RATE = 0.45  # 45% of queries are repeats within 1 hour

# Expected cache hit rates
L1_HIT_RATE = 0.02   # Dangerous commands (rare but instant)
L2_HIT_RATE = 0.45   # Classification cache (repeat queries)
L3_HIT_RATE = 0.30   # Execution cache (SubAgent results)

# Overall cache benefit
OVERALL_CACHE_BENEFIT = (
    L1_HIT_RATE * 0.99 +    # 2% queries save 99% time
    L2_HIT_RATE * 0.85 +    # 45% save 85% time
    L3_HIT_RATE * 0.40      # 30% save 40% time
) = 0.50  # 50% weighted average improvement
```

**结论**: 平均响应时间从11秒 → **5.5秒**（50%改善）

---

## 8. 实施计划

### 8.1 Phase 1: Guard基础实现（Week 1）

**目标**: 实现Guard核心功能，不影响现有系统

| 任务 | 工作量 | 依赖 | 交付物 |
|------|--------|------|--------|
| 创建Guard SKILL.md | 2h | - | `.olav/skills/guard/SKILL.md` |
| 实现QueryGuard类 | 4h | SKILL.md | `src/olav/agents/guard.py` |
| 实现危险命令检测 | 1h | QueryGuard | `DANGEROUS_PATTERNS` |
| 实现启发式分类 | 2h | QueryGuard | `_fast_heuristic_check()` |
| 实现LLM分类 | 3h | QueryGuard | `_llm_classify()` |
| 实现DuckDB缓存 | 3h | QueryGuard | `query_classifications` table |
| 单元测试 | 4h | 所有上述 | `tests/unit/test_guard.py` |

**总计**: 19小时（2-3个工作日）

### 8.2 Phase 2: Orchestrator集成（Week 2）

**目标**: 将Guard集成到现有Orchestrator，支持AB测试

| 任务 | 工作量 | 依赖 | 交付物 |
|------|--------|------|--------|
| 创建orchestrator_v2.py | 4h | Guard | `src/olav/agents/orchestrator_v2.py` |
| 实现路由逻辑 | 3h | orchestrator_v2 | `orchestrate_with_guard()` |
| 实现SubAgent路由器 | 3h | orchestrator_v2 | `_route_to_*()` functions |
| 实现escalation处理 | 2h | orchestrator_v2 | Escalation detection |
| 添加环境变量开关 | 1h | orchestrator_v2 | `ENABLE_GUARD_ROUTING` |
| 集成到CLI入口 | 2h | orchestrator_v2 | `src/olav/cli.py` |
| E2E测试 | 6h | 所有上述 | `tests/e2e/test_guard_integration.py` |

**总计**: 21小时（3个工作日）

### 8.3 Phase 3: 性能优化（Week 3）

**目标**: 优化缓存策略，达到设计目标性能

| 任务 | 工作量 | 依赖 | 交付物 |
|------|--------|------|--------|
| 实现缓存预热 | 2h | Guard | `preload_guard_cache()` |
| 实现智能TTL | 3h | Guard cache | Dynamic TTL adjustment |
| 优化正则表达式 | 2h | Heuristics | Compiled regex patterns |
| 实现缓存统计 | 2h | Guard | `get_cache_stats()` |
| 性能基准测试 | 4h | Phase 2 | Benchmark report |
| 调优阈值参数 | 3h | Benchmark | Optimal confidence thresholds |

**总计**: 16小时（2个工作日）

### 8.4 Phase 4: 生产部署（Week 4）

**目标**: AB测试、监控、文档、生产发布

| 任务 | 工作量 | 依赖 | 交付物 |
|------|--------|------|--------|
| AB测试框架 | 3h | Phase 2 | 50/50流量分配 |
| 监控仪表盘 | 3h | AB测试 | Grafana/metrics |
| 性能对比报告 | 2h | AB测试 | Performance comparison |
| 用户文档 | 3h | 所有功能 | User guide update |
| 开发者文档 | 3h | 所有功能 | Developer guide |
| 生产配置 | 2h | - | Production .env |
| 灰度发布 | 2h | AB测试 | Gradual rollout plan |

**总计**: 18小时（2-3个工作日）

---

### 8.5 总体时间线

```
Week 1: Guard Implementation
├── Day 1-2: Core Guard logic
├── Day 3: Unit testing
└── Deliverable: Working Guard (standalone)

Week 2: Orchestrator Integration
├── Day 1-2: orchestrator_v2.py
├── Day 3: E2E testing
└── Deliverable: Guard-enabled Orchestrator (feature flag)

Week 3: Performance Optimization
├── Day 1: Caching improvements
├── Day 2: Benchmarking & tuning
└── Deliverable: Production-ready performance

Week 4: Production Deployment
├── Day 1: AB testing
├── Day 2: Documentation
├── Day 3: Gradual rollout
└── Deliverable: Full production deployment

Total: 4 weeks (20 working days)
Risk Buffer: +1 week (for debugging/issues)
```

---

## 9. 测试策略

### 9.1 单元测试（Guard）

```python
# tests/unit/test_guard.py

import pytest
from olav.agents.guard import QueryGuard, RouteCode


class TestQueryGuard:
    """Test Guard classification accuracy."""
    
    def test_dangerous_patterns(self):
        """Test dangerous command detection."""
        guard = QueryGuard()
        
        # Positive cases (should reject)
        assert guard.classify("shutdown all devices").code == RouteCode.REJECT
        assert guard.classify("reload router").code == RouteCode.REJECT
        assert guard.classify("erase nvram").code == RouteCode.REJECT
        
        # Negative cases (should pass)
        assert guard.classify("show devices").code != RouteCode.REJECT
        assert guard.classify("count routers").code != RouteCode.REJECT
    
    def test_simple_classification(self):
        """Test SIMPLE query classification."""
        guard = QueryGuard()
        
        test_cases = [
            "有多少个设备?",
            "count all routers",
            "list devices",
            "show interfaces",
        ]
        
        for query in test_cases:
            result = guard.classify(query)
            assert result.code == RouteCode.SIMPLE
            assert result.confidence >= 0.85
    
    def test_cli_classification(self):
        """Test CLI query classification."""
        guard = QueryGuard()
        
        test_cases = [
            "R1当前CPU使用率",
            "real-time BGP status",
            "show running-config now",
        ]
        
        for query in test_cases:
            result = guard.classify(query)
            assert result.code == RouteCode.CLI
            assert result.confidence >= 0.80
    
    def test_expert_classification(self):
        """Test EXPERT query classification."""
        guard = QueryGuard()
        
        test_cases = [
            "为什么OSPF邻居不稳定?",
            "analyze BGP route flapping",
            "optimize VLAN design",
        ]
        
        for query in test_cases:
            result = guard.classify(query)
            assert result.code == RouteCode.EXPERT
            assert result.confidence >= 0.80
    
    def test_cache_hit(self):
        """Test semantic cache functionality."""
        guard = QueryGuard()
        
        # First call (cache miss)
        result1 = guard.classify("有多少个设备?")
        assert not result1.cache_hit
        
        # Second call (cache hit)
        result2 = guard.classify("有多少个设备?")
        assert result2.cache_hit
        assert result2.code == result1.code
    
    def test_confidence_thresholds(self):
        """Test confidence-based routing decisions."""
        guard = QueryGuard()
        
        # High confidence (>= 0.85) should direct route
        high_conf = guard.classify("count devices")
        assert high_conf.should_direct_route()
        
        # Ambiguous query should have low confidence
        low_conf = guard.classify("帮我看看网络")
        assert not low_conf.should_direct_route()
```

### 9.2 E2E测试（集成）

```python
# tests/e2e/test_guard_integration.py

import pytest
import time
from olav.agents.orchestrator_v2 import orchestrate_with_guard


@pytest.mark.e2e
class TestGuardIntegration:
    """Test Guard integration with Orchestrator."""
    
    def test_simple_query_fast_path(self):
        """Simple query should use fast path (<3 seconds)."""
        start = time.time()
        result = orchestrate_with_guard("有多少个设备?")
        elapsed = time.time() - start
        
        assert result["status"] == "complete"
        assert elapsed < 3.0, f"Expected <3s, got {elapsed:.2f}s"
    
    def test_simple_query_cached(self):
        """Repeated simple query should be cached (<1 second)."""
        # First call (warm up cache)
        orchestrate_with_guard("count devices")
        
        # Second call (should be cached)
        start = time.time()
        result = orchestrate_with_guard("count devices")
        elapsed = time.time() - start
        
        assert result["status"] == "complete"
        assert elapsed < 1.0, f"Expected <1s (cached), got {elapsed:.2f}s"
    
    def test_dangerous_command_rejection(self):
        """Dangerous command should be rejected immediately."""
        start = time.time()
        result = orchestrate_with_guard("shutdown all devices")
        elapsed = time.time() - start
        
        assert result["status"] == "rejected"
        assert "危险" in result["final_answer"] or "dangerous" in result["final_answer"].lower()
        assert elapsed < 0.1, f"Expected <100ms, got {elapsed:.2f}s"
    
    def test_expert_routing(self):
        """Complex query should route to Expert."""
        result = orchestrate_with_guard("为什么OSPF邻居不稳定?")
        
        assert result["status"] in ["complete", "needs_cli_data"]
        # Should contain analysis (not just data listing)
        assert len(result["final_answer"]) > 100
    
    def test_unknown_fallback(self):
        """Ambiguous query should fallback to Orchestrator."""
        result = orchestrate_with_guard("帮我看看网络")
        
        # Should complete (even if asking for clarification)
        assert result["status"] in ["complete", "needs_clarification"]
```

### 9.3 性能基准测试

```python
# tests/benchmark/test_guard_performance.py

import pytest
import time
import statistics
from olav.agents.orchestrator import orchestrate_query_sync  # Old
from olav.agents.orchestrator_v2 import orchestrate_with_guard  # New


@pytest.mark.benchmark
class TestGuardPerformance:
    """Benchmark Guard vs current architecture."""
    
    TEST_QUERIES = [
        "有多少个设备?",
        "列出所有路由器",
        "count switches",
        "show all interfaces",
    ]
    
    def test_old_architecture_latency(self):
        """Baseline: Current Orchestrator latency."""
        latencies = []
        
        for query in self.TEST_QUERIES:
            start = time.time()
            orchestrate_query_sync(query)
            elapsed = time.time() - start
            latencies.append(elapsed)
        
        avg_latency = statistics.mean(latencies)
        print(f"\n[OLD] Average latency: {avg_latency:.2f}s")
        
        assert avg_latency > 8.0, "Baseline should be >8s"
    
    def test_guard_architecture_latency(self):
        """Guard: New architecture latency."""
        latencies = []
        
        for query in self.TEST_QUERIES:
            start = time.time()
            orchestrate_with_guard(query)
            elapsed = time.time() - start
            latencies.append(elapsed)
        
        avg_latency = statistics.mean(latencies)
        print(f"\n[GUARD] Average latency: {avg_latency:.2f}s")
        
        assert avg_latency < 5.0, "Guard should be <5s"
    
    def test_cache_effectiveness(self):
        """Test cache hit rate improvement."""
        # Warm up cache
        for query in self.TEST_QUERIES:
            orchestrate_with_guard(query)
        
        # Measure cached performance
        latencies = []
        for query in self.TEST_QUERIES:
            start = time.time()
            orchestrate_with_guard(query)
            elapsed = time.time() - start
            latencies.append(elapsed)
        
        avg_latency = statistics.mean(latencies)
        print(f"\n[GUARD CACHED] Average latency: {avg_latency:.4f}s")
        
        assert avg_latency < 0.5, "Cached queries should be <500ms"
```

---

## 10. 风险评估

### 10.1 技术风险

| 风险 | 概率 | 影响 | 缓解策略 | 责任人 |
|------|------|------|---------|--------|
| Guard误分类导致体验下降 | 🟡 中 (30%) | 🔴 高 | 1. 保留escalation机制<br>2. 低置信度fallback<br>3. A/B测试验证 | 架构师 |
| 缓存导致数据过期 | 🟡 中 (25%) | 🟡 中 | 1. 智能TTL策略<br>2. CLI查询短TTL<br>3. 手动清除接口 | 后端工程师 |
| DuckDB缓存性能瓶颈 | 🟢 低 (15%) | 🟡 中 | 1. 缓存表索引优化<br>2. 定期清理过期记录<br>3. 监控查询性能 | DBA |
| LLM分类不稳定（temperature） | 🟡 中 (20%) | 🟡 中 | 1. 设置低temperature (0.1)<br>2. Few-shot examples<br>3. 结构化输出验证 | AI工程师 |
| Orchestrator简化破坏现有功能 | 🟢 低 (10%) | 🔴 高 | 1. 保留完整fallback<br>2. 充分E2E测试<br>3. Feature flag灰度 | QA团队 |

### 10.2 业务风险

| 风险 | 概率 | 影响 | 缓解策略 |
|------|------|------|---------|
| 用户习惯改变抵触 | 🟢 低 (5%) | 🟢 低 | 响应更快，应该无抵触 |
| 分类错误投诉增加 | 🟡 中 (20%) | 🟡 中 | 提供"用back to Orchestrator"选项 |
| 缓存复杂度增加运维成本 | 🟢 低 (10%) | 🟢 低 | 自动化监控+清理脚本 |

### 10.3 Rollback计划

```python
# Emergency rollback (if Guard causes issues)

# Step 1: Disable Guard via environment variable
export ENABLE_GUARD_ROUTING=false

# Step 2: Restart service
systemctl restart olav

# Step 3: Verify fallback to old architecture
olav query "test query"  # Should use orchestrate_query_sync

# Step 4: Investigate issues
tail -f logs/olav.log | grep -i guard

# Step 5: Fix and re-enable
export ENABLE_GUARD_ROUTING=true
systemctl restart olav
```

---

## 11. 监控指标

### 11.1 Guard性能指标

```python
# Metrics to monitor in production

GUARD_METRICS = {
    "classification_latency_ms": {
        "p50": 100,   # 50th percentile
        "p95": 500,   # 95th percentile
        "p99": 1500,  # 99th percentile
    },
    "cache_hit_rate_pct": {
        "target": 45,  # Target 45% hit rate
        "alarm": 30,   # Alert if < 30%
    },
    "classification_accuracy_pct": {
        "target": 90,  # Target 90% accuracy
        "alarm": 80,   # Alert if < 80%
    },
    "route_distribution": {
        "SIMPLE": 0.70,   # Expected 70%
        "CLI": 0.10,
        "EXPERT": 0.15,
        "REJECT": 0.02,
        "UNKNOWN": 0.03,
    }
}
```

### 11.2 Grafana仪表盘

```
┌─────────────────────────────────────────────────────────┐
│ Guard Performance Dashboard                             │
├─────────────────────────────────────────────────────────┤
│                                                         │
│ [Latency]         [Cache Hit Rate]   [Route Distribution]│
│  ┌─────────┐       ┌─────────┐        ┌─────────┐     │
│  │  2.1s   │       │   48%   │        │ SIMPLE   │     │
│  │ (-65%)  │       │ (+30%)  │        │   72%    │     │
│  └─────────┘       └─────────┘        └─────────┘     │
│                                                         │
│ [Classification Accuracy]  [Errors]                     │
│  ┌─────────┐                ┌─────────┐               │
│  │  92%    │                │    3    │               │
│  │ (Target: 90%)            │  /hour  │               │
│  └─────────┘                └─────────┘               │
│                                                         │
│ [Top Queries - Last Hour]                              │
│  1. "有多少个设备?" (45x, 98% cached)                   │
│  2. "列出所有设备" (23x, 87% cached)                    │
│  3. "show devices" (18x, 72% cached)                   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## 12. 附录

### 12.1 术语表

| 术语 | 定义 | 示例 |
|------|------|------|
| **Guard层** | 预路由分类层，负责快速决策 | QueryGuard类 |
| **Orchestrator层** | 智能调度层，处理复杂场景 | orchestrate_with_guard() |
| **直接路由** | 高置信度（>=0.85）绕过Orchestrator | SIMPLE → Query Agent |
| **Fallback** | 低置信度交给Orchestrator规划 | UNKNOWN → Full planning |
| **Escalation** | SubAgent请求重新路由 | <cli_needed>, <escalate_to_expert> |
| **L1/L2/L3缓存** | 三层缓存架构 | 内存/DuckDB/LangGraph |

### 12.2 相关文档

- [ARCHITECTURE.md](../reference/ARCHITECTURE.md) - 当前架构说明
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](../reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - SubAgent开发指南
- [CONFIGURATION_REFERENCE.md](../reference/CONFIGURATION_REFERENCE.md) - 配置参考

### 12.3 联系方式

**技术负责人**: OLAV架构团队  
**文档维护**: docs@olav.ai  
**问题反馈**: https://github.com/your-org/olav/issues

---

**END OF DOCUMENT**

---

**版本历史**:
- v1.0.0 (2026-02-11): 初始设计方案
