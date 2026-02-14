# Plan模式架构设计分析 (2026-02-06)

## 🎯 问题背景

**复杂场景示例：NetBox审计任务**
```
用户："审计一下现在网络数据和NetBox里有哪些不一致的，最后导出为一个CSV，如果差异少于10条直接同步"
```

**任务拆解：**
1. 查询网络实际数据（设备、接口、IP地址）
2. 查询NetBox数据库（同样的数据）
3. 对比两边数据找差异
4. 统计差异数量
5. 导出CSV文件
6. 如果差异<10条 → 确认同步 (HITL)
7. 执行同步操作

**核心问题：**
- 谁来编排这个多步任务？Orchestrator还是SubAgent？
- 任务粒度如何控制？
- 如何传导到SubAgent？

---

## 📚 DeepAgents原生Plan机制

### TodoListMiddleware（OLAV当前未启用）

**提供工具：**
- `write_todos(todos: list[dict])` - 创建任务列表
- `read_todos()` - 读取当前任务状态

**使用场景：**
```python
# Agent可以创建任务列表
write_todos([
    {"id": 1, "task": "查询网络数据", "status": "pending"},
    {"id": 2, "task": "查询NetBox数据", "status": "pending"},
    {"id": 3, "task": "对比差异", "status": "pending"},
    {"id": 4, "task": "导出CSV", "status": "pending"},
])

# 执行过程中更新状态
read_todos()  # 检查进度
write_todos([
    {"id": 1, "task": "查询网络数据", "status": "completed"},
    {"id": 2, "task": "查询NetBox数据", "status": "in_progress"},
    ...
])
```

**优点：**
- 结构化任务跟踪
- 可恢复执行（checkpoint后重启）
- LLM可见的进度状态

**缺点：**
- 需要LLM主动维护（不是自动的）
- 增加token消耗（todo list在context中）

---

## 🔑 关键澄清：Plan的真正含义

### 用户洞察（纠正之前的理解）

**Plan模式的本质 = 跨SubAgent协作编排**

```
Plan模式：Orchestrator编排多个SubAgent的协作顺序
    ↓
    query SubAgent (查网络数据) → 返回结果A
    ↓
    netbox SubAgent (查NetBox数据) → 返回结果B
    ↓
    Orchestrator综合A+B → 对比差异 → 决策

ReAct模式：SubAgent内部的自主决策
    ↓
    query SubAgent内部：选表 → 写SQL → 验证 → 返回
    netbox SubAgent内部：调API → 解析 → 验证 → 返回
```

**之前方案B的问题：**
```python
# ❌ 混淆了"内部planning"和"协作planning"
NetBoxSubAgent:
    Step 1: task(query, "查网络数据")  ← 这其实是跨SubAgent协作，不是内部planning
    Step 2: netbox_api()               ← 这才是内部决策
```

**正确理解：**
- NetBoxSubAgent调用`task(query, ...)`时，它实际上是在**触发跨SubAgent协作**
- 这种协作应该由Orchestrator编排，而不是SubAgent内部自己决定

---

## 🏗️ 四种Plan模式方案（重新设计）

### 方案A：Orchestrator手动编排（传统Plan - ⚠️ 谨慎使用）

**思路：Orchestrator作为"项目经理"编排所有步骤**

```python
Orchestrator:
    理解用户："审计NetBox数据一致性，导出CSV，差异<10自动同步"
    
    # Orchestrator自己规划：
    Plan:
        1. 查网络数据 → query SubAgent
        2. 查NetBox数据 → netbox SubAgent
        3. 对比差异 → Orchestrator自己做 or compare SubAgent
        4. 导出CSV → format_and_export
        5. 判断数量 → Orchestrator自己做
        6. 如果<10 → 同步 (HITL)
    
    # 执行：
    Step 1: result_network = task(query, "查所有设备hostname、mgmt_ip、model")
    Step 2: result_netbox = task(netbox, "查NetBox所有设备数据")
    Step 3: differences = compare(result_network, result_netbox)  # 谁来compare？
    Step 4: format_and_export(differences, "csv", "netbox_audit.csv")
    Step 5: if len(differences) < 10:
                task(netbox, "同步数据", data=differences)
```

**问题分析：**
1. **Orchestrator需要理解业务逻辑**
   - "NetBox审计" = 查哪些字段？hostname? mgmt_ip? model? serial?
   - 如何对比？完全一致？还是允许某些字段缺失？
   
2. **对比逻辑放在哪？**
   - Orchestrator自己对比？→ 需要理解数据结构
   - 创建CompareSubAgent？→ SubAgent数量爆炸
   - NetBoxSubAgent对比？→ 那为什么要Orchestrator编排？

3. **扩展性差**
   - 10个SubAgent → Orchestrator需要理解10个业务流程
   - 每个新SubAgent → 需要更新Orchestrator的system prompt

**适用场景：**
- 简单的顺序调用（2-3个SubAgent，无复杂逻辑）
- 明确的输入输出（A的输出直接是B的输入）

**不适用：复杂业务逻辑（如NetBox审计）**

---

### 方案B：声明式依赖编排（🌟 推荐方案）

**核心思想：SubAgent在SKILL.md中声明依赖，Orchestrator根据依赖图自动编排**

**1. SubAgent声明依赖（.olav/skills/netbox-integration/SKILL.md）**

```yaml
---
name: netbox-integration
description: NetBox DCIM integration specialist

# 声明式工作流（Orchestrator读取此配置）
workflow:
  type: collaborative  # 或 independent（不需要其他SubAgent）
  
  dependencies:
    - subagent: query
      task: "查询所有设备的hostname、mgmt_ip、model、serial_number"
      output: network_devices_data
      
  execution:
    - step: fetch_netbox_data
      description: "调用NetBox API获取设备数据"
      tool: netbox_api
      
    - step: compare_data
      description: "对比network_devices_data和NetBox数据"
      inputs: [network_devices_data, netbox_devices_data]
      output: differences
      
    - step: export_report
      description: "导出差异报告"
      tool: format_and_export
      
    - step: auto_sync_decision
      condition: "len(differences) < 10"
      action: "生成同步计划，返回HITL确认"

capabilities:
  - Compare network reality with NetBox DCIM database
  - Auto-sync when differences below threshold

tools:
  - netbox_api
  - format_and_export
---
```

**2. Orchestrator读取workflow自动编排**

```python
Orchestrator:
    用户："审计NetBox数据"
    
    # 读取netbox SubAgent的workflow声明
    workflow = load_workflow("netbox-integration")
    
    # 发现依赖：需要先调用query SubAgent
    if workflow.dependencies:
        for dep in workflow.dependencies:
            dep_result = task(dep.subagent, dep.task)
            # 将结果注入到netbox SubAgent的context
            context[dep.output] = dep_result
    
    # 调用netbox SubAgent（已有依赖数据在context）
    result = task("netbox", user_query, context=context)
    
    return result
```

**3. NetBoxSubAgent执行（内部ReAct）**

```python
NetBoxSubAgent:
    # Context中已有network_devices_data（Orchestrator注入）
    
    Step 1: 调用netbox_api("GET /api/dcim/devices/")
            → netbox_devices_data
    
    Step 2: compare(network_devices_data, netbox_devices_data)
            → 发现8条差异
    
    Step 3: format_and_export(differences, "csv")
            → CSV已保存
    
    Step 4: if len(differences) < 10:
                return "发现8条差异，建议同步 (HITL)"
```

**优势：**
1. ✅ **Orchestrator不需要理解业务逻辑**
   - 只需要读取workflow声明，按依赖图执行
   - 新增SubAgent：只需添加SKILL.md，无需修改Orchestrator代码

2. ✅ **SubAgent保持专业能力**
   - 对比逻辑由NetBoxSubAgent实现（它最懂）
   - QuerySubAgent专注于优化SQL

3. ✅ **扩展性强**
   - 100个SubAgent → Orchestrator只是"依赖图执行器"
   - 支持复杂依赖（A依赖B+C，D依赖A）

**实现复杂度：中等**
- 需要实现workflow解析器
- 需要实现依赖图执行引擎

---

### 方案C：协调者SubAgent模式（🎯 超大规模场景）

**核心思想：创建专门的CoordinatorSubAgent管理跨SubAgent协作**

```python
Orchestrator:
    用户："审计NetBox数据"
    → 识别："这是复杂协作任务"
    → task(coordinator, "审计NetBox数据一致性")

CoordinatorSubAgent (专门负责协作编排的专家):
    Step 1: 分析任务："需要query + netbox协作"
    
    Step 2: task(query, "查所有设备hostname、mgmt_ip、model")
            → network_data
    
    Step 3: task(netbox, "查NetBox设备数据")
            → netbox_data
    
    Step 4: 对比数据（或 task(compare, ...）
            → differences
    
    Step 5: format_and_export(differences, "csv")
    
    Step 6: if len(differences) < 10:
                task(netbox, "同步数据", data=differences)
    
    Step 7: 返回Orchestrator："审计完成，发现8条差异，已导出CSV"
```

**优势：**
1. ✅ **Orchestrator保持轻量**
   - 只负责："这是什么类型任务？" → 分配给对应的专家
   - 不管："需要哪些步骤？"

2. ✅ **Coordinator专注于协作编排**
   - 它的专业能力就是"项目管理"
   - 知道如何调用不同SubAgent
   - 可以处理复杂的多步协作

3. ✅ **SubAgent保持纯粹**
   - query只查数据
   - netbox只管NetBox操作
   - 都不需要知道对方存在

**适用场景：**
- SubAgent数量 > 10个
- 复杂的跨专业协作（3+个SubAgent）
- 需要动态调整协作流程

**缺点：**
- CoordinatorSubAgent本身可能变成"超级大脑"
- 需要定义：什么任务需要Coordinator？什么任务直接分配？

---

### 方案D：混合模式（📦 当前可行方案）

**核心思想：简单任务走SubAgent自主，复杂协作走Orchestrator Plan**

```python
Orchestrator:
    用户："审计NetBox数据"
    
    # 询问NetBoxSubAgent：你能独立完成吗？
    capability_check = ask(netbox, "can_handle", task="审计NetBox数据")
    
    if capability_check.needs_collaboration:
        # 进入Plan模式
        dependencies = capability_check.dependencies  # ["query"]
        
        # 收集依赖数据
        context = {}
        for dep in dependencies:
            context[dep] = task(dep, capability_check.dep_tasks[dep])
        
        # 带context调用netbox
        result = task(netbox, user_query, context=context)
    else:
        # 独立执行
        result = task(netbox, user_query)
    
    return result
```

**NetBoxSubAgent的能力声明（SKILL.md）**

```yaml
collaborative_mode:
  enabled: true
  dependencies:
    query:
      description: "需要query SubAgent提供网络实际数据"
      task_template: "查询所有设备的hostname、mgmt_ip、model"
      required: true
```

**执行流程：**
1. Orchestrator先问："你需要帮助吗？"
2. NetBoxSubAgent回答："需要query SubAgent的数据"
3. Orchestrator收集依赖 → 注入context
4. NetBoxSubAgent在有context的情况下执行

**优势：**
- ✅ 渐进式实现（先支持简单场景，再扩展复杂场景）
- ✅ Orchestrator逻辑相对简单
- ✅ 兼容现有SubAgent（不需要collaborative_mode也能工作）

**当前OLAV实现：**
- 当前是简化版：SubAgent内部直接调用`task()`
- 未来可升级为混合模式

---

## 🎯 方案对比与选择

| 方案 | Orchestrator职责 | SubAgent调用task() | 适用场景 | 复杂度 |
|------|------------------|-------------------|----------|--------|
| **A. 手动编排** | 理解业务流程+编排 | ❌ 不允许 | 简单顺序调用（2-3步） | 低 |
| **B. 声明式依赖** | 依赖图执行器 | ❌ 不允许 | 中大型项目（5-20 SubAgent） | 中 |
| **C. Coordinator** | 任务分类 | ✅ Coordinator调用 | 超大规模（>20 SubAgent） | 高 |
| **D. 混合模式** | 能力查询+依赖收集 | ⚠️ 声明后允许 | 渐进式演进 | 中 |

### 推荐路线图

**Phase 1：当前（简化混合模式）** ✅ 已实现
- SubAgent可以调用`task(other_subagent, ...)`
- Orchestrator不管协作细节
- 适用于简单协作（1-2个依赖）

**Phase 2：声明式依赖（推荐升级）**
- 在SKILL.md中声明`dependencies: [query]`
- Orchestrator读取依赖，预先收集数据
- SubAgent不再调用`task()`，而是读取context
- 优势：Orchestrator可见协作关系，便于优化（并行执行）

**Phase 3：Coordinator模式（未来扩展）**
- 当SubAgent > 10个时引入
- 复杂协作任务交给CoordinatorSubAgent
- Orchestrator回归"任务分类"角色

---

## 📊 关键问题解答

### Q1: SubAgent能否调用task()？

**答案：取决于Plan模式选择**

| 模式 | SubAgent调用task() | 说明 |
|------|-------------------|------|
| **方案A** | ❌ 禁止 | Orchestrator手动编排所有协作 |
| **方案B** | ✅ 允许（声明式） | 在SKILL.md声明依赖，Orchestrator预收集 |
| **方案C** | ✅ 允许（Coordinator管理） | Coordinator SubAgent负责编排 |
| **方案D** | ⚠️ 当前实现 | SubAgent直接调用（简化版） |

**推荐演进路径：**
```
当前（Phase 1）：SubAgent直接调用task()（简单场景）
    ↓
升级（Phase 2）：声明式依赖（Orchestrator预收集数据）
    ↓
扩展（Phase 3）：Coordinator模式（超大规模协作）
```

### Q2: Orchestrator的局限性在哪？

**用户正确指出的问题：**

```
当SubAgent数量增多（10+个）时，Orchestrator作为LLM的局限性：

1. Token限制
   - System Prompt需要描述10+个SubAgent的能力
   - 每次决策都需要加载所有SubAgent描述
   - Context容易超限

2. 推理复杂度
   - 10个SubAgent → 45种两两组合
   - 需要理解："这个任务需要哪几个SubAgent协作？"
   - LLM容易选错或遗漏

3. 维护成本
   - 新增SubAgent → 更新Orchestrator System Prompt
   - 修改协作流程 → 重新训练/调整prompt
```

**解决方案：**

| 方案 | 如何解决局限性 |
|------|--------------|
| **声明式依赖（B）** | Orchestrator只读配置文件，不需要"理解"业务 |
| **Coordinator（C）** | 分层管理，Orchestrator只分类，Coordinator编排 |
| **混合模式（D）** | 渐进式，简单任务不走Plan，复杂任务才编排 |

### Q3: Plan vs ReAct 的清晰定义

**Plan模式（Orchestrator层面）：**
- **定义**：跨SubAgent协作编排
- **职责**：决定"谁先谁后"、"谁的输出给谁"
- **不负责**：SubAgent内部如何执行（那是ReAct的事）

**ReAct模式（SubAgent内部）：**
- **定义**：专家自主决策循环
- **职责**：选工具、写代码、验证结果
- **不负责**：其他SubAgent的事（通过task()协作or依赖注入）

**清晰边界：**
```
Orchestrator (Plan):
    "NetBox审计需要query和netbox两个SubAgent协作"
    "先执行query，将结果传给netbox"
    
query SubAgent (ReAct):
    "查哪个表？" "JOIN吗？" "索引优化？" ← 这是我的专业判断
    不管："NetBox在哪？" "如何对比？"

netbox SubAgent (ReAct):
    "调哪个API endpoint？" "如何对比数据？" ← 这是我的专业判断
    不管："网络数据从哪来？"（从context获取，Orchestrator注入）
```

---

## 🎯 NetBox审计场景：推荐实现

### 方案选择：声明式依赖（方案B）✅

**原因：**
1. Orchestrator不需要理解"NetBox审计"的业务逻辑
2. NetBoxSubAgent专注于自己的专业（对比、同步）
3. 扩展性强（新增SubAgent只需加配置）

### 实现步骤

**1. SubAgent定义（.olav/OLAV.md）**

```yaml
### netbox
---
name: netbox
agent_skill: netbox-integration
description: NetBox DCIM integration specialist for data sync and audit
capabilities:
  - Query NetBox API (devices, interfaces, IP addresses)
  - Compare NetBox data with network reality
  - Sync network data to NetBox (with HITL approval)
enabled: true
---
```

**2. Skill配置（.olav/skills/netbox-integration/SKILL.md）**

```yaml
---
name: netbox-integration
description: NetBox DCIM integration specialist

# 声明式协作依赖
collaborative_mode:
  enabled: true
  dependencies:
    - subagent: query
      description: "提供网络实际数据用于对比"
      task_template: "查询所有设备的hostname、mgmt_ip、model、serial_number"
      output_context_key: network_devices_data

role: |
  You are an expert at integrating network reality with NetBox DCIM database.
  
  When performing audits:
  1. You will receive network_devices_data from context (pre-collected by Orchestrator)
  2. Call netbox_api() to fetch NetBox database data
  3. Compare both datasets and identify discrepancies
  4. Generate detailed audit report
  5. If differences < threshold, propose sync action (requires HITL approval)

tools:
  - netbox_api           # Query/Update NetBox API
  - format_and_export    # Export audit results to CSV

examples:
  - input: "审计网络和NetBox的设备差异，导出CSV"
    context: 
      network_devices_data: [...]  # Pre-injected by Orchestrator
    
    execution:
      - step: "调用netbox_api获取NetBox数据"
      - step: "对比network_devices_data和netbox_data"
      - step: "生成差异报告并导出CSV"
      - step: "如果差异<10，建议同步（HITL确认）"
---
```

**3. Orchestrator自动编排逻辑**

```python
# src/olav/agents/orchestrator.py

async def orchestrate_query(user_query: str) -> dict:
    """Orchestrator with declarative dependency resolution."""
    
    # 1. 路由：识别任务类型
    subagent_name = route_to_subagent(user_query)  # "netbox"
    
    # 2. 检查依赖
    skill_config = load_skill_config(subagent_name)
    
    if skill_config.get("collaborative_mode", {}).get("enabled"):
        # 3. 收集依赖数据
        context = {}
        dependencies = skill_config["collaborative_mode"]["dependencies"]
        
        for dep in dependencies:
            # 并行执行所有依赖（优化性能）
            dep_result = await task(dep["subagent"], dep["task_template"])
            context[dep["output_context_key"]] = dep_result
        
        # 4. 带context调用目标SubAgent
        result = await task(subagent_name, user_query, context=context)
    else:
        # 独立执行（无依赖）
        result = await task(subagent_name, user_query)
    
    return result
```

**4. 执行流程**

```python
# 用户请求
"审计网络数据和NetBox的不一致，导出CSV，差异<10条直接同步"

# Orchestrator
Orchestrator:
    1. 路由：识别为"netbox"任务
    2. 读取netbox skill配置 → 发现依赖query
    3. 预执行：task(query, "查询所有设备的hostname、mgmt_ip、model")
                → network_devices_data = [...]
    4. 注入context：{"network_devices_data": [...]}
    5. 调用：task(netbox, user_query, context=context)

# NetBoxSubAgent（内部ReAct，不调用task()）
NetBoxSubAgent:
    Step 1: 从context读取network_devices_data（已有，无需task(query)）
    
    Step 2: netbox_api("GET /api/dcim/devices/?limit=1000")
            → netbox_data = [...]
    
    Step 3: 对比network_devices_data和netbox_data
            → differences = [8条差异]
    
    Step 4: format_and_export(differences, "csv", "netbox_audit.csv")
            → CSV已保存
    
    Step 5: if len(differences) < 10:
                返回："发现8条差异（已导出），建议同步 [HITL确认]"

# Orchestrator
Orchestrator:
    收到NetBoxSubAgent完整结果 → 返回用户

# HITL确认后
User: "批准同步"
Orchestrator: task(netbox, "执行同步", data=differences)
```

### 关键优势

1. ✅ **Orchestrator不理解业务**
   - 只读取`collaborative_mode`配置
   - 自动收集依赖数据
   - 不需要知道"NetBox审计是什么"

2. ✅ **SubAgent不调用task()**
   - 所有依赖数据从context获取
   - 专注于自己的专业能力（对比、同步）

3. ✅ **扩展性强**
   - 新增SubAgent：只需创建SKILL.md
   - 新增依赖：只需修改`dependencies`配置
   - Orchestrator代码零修改

4. ✅ **性能优化**
   - Orchestrator可以并行执行所有依赖
   - 例如：同时查网络数据和NetBox数据（如果独立）

---

## 📋 TodoListMiddleware 使用场景

### 什么时候需要TodoList？

| 场景 | 是否需要 | 原因 |
|------|---------|------|
| **单SubAgent任务** | ❌ | ReAct循环足够 |
| **2-3个SubAgent协作** | ❌ | 声明式依赖足够 |
| **4-10个SubAgent协作** | ⚠️ 可选 | 提升用户体验（进度可见） |
| **并行任务** | ✅ 推荐 | Orchestrator跟踪多任务进度 |
| **超长任务（>30分钟）** | ✅ 推荐 | 防止context丢失，支持恢复 |

### 实现示例

```python
# 用户："审计NetBox数据一致性，同时生成全网拓扑图，并导出健康检查报告"

Orchestrator:
    # 识别：3个独立任务，可并行
    
    # 创建TodoList
    write_todos([
        {"id": 1, "task": "NetBox审计", "subagent": "netbox", "status": "pending"},
        {"id": 2, "task": "拓扑图生成", "subagent": "topology", "status": "pending"},
        {"id": 3, "task": "健康检查", "subagent": "inspection", "status": "pending"},
    ])
    
    # 并行执行（async）
    results = await asyncio.gather(
        task(netbox, "审计NetBox数据"),
        task(topology, "生成全网拓扑图"),
        task(inspection, "健康检查报告"),
    )
    
    # 更新进度
    write_todos([...全部标记completed...])
    
    # 综合结果
    return 综合报告(results)
```

---

## 📋 总结与建议（修正版）

### 核心设计原则

1. **Plan = 跨SubAgent协作编排**
   - **职责**：决定谁先谁后、数据流向
   - **实现者**：Orchestrator（通过依赖声明）或 Coordinator SubAgent
   - **不负责**：SubAgent内部如何执行

2. **ReAct = SubAgent内部决策**
   - **职责**：选工具、写代码、验证结果
   - **实现者**：各个专家SubAgent
   - **不负责**：其他SubAgent的专业领域

3. **关键区别**

| 层级 | Plan模式 | ReAct模式 |
|------|---------|-----------|
| **范围** | 跨SubAgent | SubAgent内部 |
| **决策者** | Orchestrator/Coordinator | 专家自己 |
| **粒度** | SubAgent级别 | 工具/步骤级别 |
| **例子** | "先query，再netbox，再对比" | "SELECT哪个表？JOIN吗？" |

### Orchestrator的局限性与解决方案

**问题（用户正确指出）：**
```
SubAgent数量增多（10+个）→ Orchestrator局限性暴露：
1. Token限制：需要加载所有SubAgent描述
2. 推理复杂度：10个SubAgent → 45种组合
3. 维护成本：新增SubAgent → 更新Orchestrator prompt
```

**解决方案对比：**

| 方案 | Token消耗 | 推理复杂度 | 维护成本 | 扩展性 |
|------|----------|-----------|---------|--------|
| **A. 手动编排** | 高 | 高 | 高 | 差 |
| **B. 声明式依赖** | 低 | 低 | 低 | 优秀 |
| **C. Coordinator** | 中 | 中 | 中 | 良好 |
| **D. 混合模式** | 中 | 中 | 中 | 良好 |

**推荐：声明式依赖（方案B）**  
原因：Orchestrator只读配置，不需要"推理"业务逻辑

### 实施路线图（更新）

**Phase 1：当前（简化版）** ✅ 已实现
- SubAgent可以调用`task(other_subagent, ...)`
- 适用于简单协作（1-2个依赖）
- **问题**：NetBoxSubAgent调用`task(query)`时，它实际是在做"协作编排"

**Phase 2：声明式依赖（推荐升级）** 🎯 下一步
- 在SKILL.md中声明`dependencies: [query]`
- Orchestrator读取依赖，**预先收集数据**
- SubAgent不再调用`task()`，而是从**context读取**
- **优势**：
  - Orchestrator可见协作关系
  - 支持并行执行依赖（性能优化）
  - SubAgent专注于自己的专业能力

**Phase 3：Coordinator模式（未来扩展）**
- 当SubAgent > 10个时引入
- 复杂协作任务交给CoordinatorSubAgent
- Orchestrator回归"任务分类"角色

### NetBox场景实现清单（更新）

**Phase 2实现（声明式依赖）：**

- [ ] **创建`.olav/skills/netbox-integration/SKILL.md`**
  - 声明`collaborative_mode`配置
  - 定义`dependencies: [query]`
  - 指定`output_context_key: network_devices_data`

- [ ] **实现`netbox_api`工具**
  - REST API封装（GET/POST/PUT/DELETE）
  - 支持设备、接口、IP地址查询
  - 支持批量同步操作

- [ ] **在`.olav/OLAV.md`注册`netbox` SubAgent**
  - 添加SubAgent声明
  - 关联`agent_skill: netbox-integration`

- [ ] **增强Orchestrator依赖解析**
  ```python
  # src/olav/agents/orchestrator.py
  def resolve_dependencies(subagent_name):
      skill = load_skill_config(subagent_name)
      if skill.get("collaborative_mode", {}).get("enabled"):
          return skill["collaborative_mode"]["dependencies"]
      return []
  ```

- [ ] **实现context注入机制**
  ```python
  context = {}
  for dep in dependencies:
      context[dep["output_context_key"]] = await task(dep["subagent"], dep["task"])
  
  result = await task(subagent_name, user_query, context=context)
  ```

- [ ] **测试完整流程**
  - 审计 → 对比 → 导出CSV → 同步（HITL）
  - 验证：NetBoxSubAgent不调用`task(query)`
  - 验证：从context读取`network_devices_data`

- [ ] **(可选) 启用TodoListMiddleware**
  - 仅用于大型并行任务
  - 提升进度可见性

### 关键收获

1. ✅ **Plan ≠ 让Orchestrator编排所有细节**
   - Plan = 跨SubAgent协作编排
   - 不是SubAgent内部的步骤编排

2. ✅ **SubAgent调用task()的问题**
   - 它混淆了"内部决策"和"协作编排"
   - 更好的方式：依赖声明 + context注入

3. ✅ **Orchestrator局限性的正确应对**
   - 不是让它"更聪明"（理解更多业务）
   - 而是让它"更机械"（读配置、执行依赖图）

4. ✅ **扩展性的关键**
   - 新增SubAgent：只需创建SKILL.md
   - Orchestrator代码零修改
   - 支持100+个SubAgent而不会token爆炸

---

**版本：** v0.9.8 (Plan模式架构设计 - 修正版)  
**最后更新：** 2026-02-06  
**相关文档：** 
- [架构正确理解](architecture_correct_understanding.md)
- [Code Quality Audit](99_audit.md)
