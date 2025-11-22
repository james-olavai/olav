# OLAV 已知问题与待办事项

> **更新日期**: 2025-11-22  
> **版本**: v0.1.0  
> **状态**: Root Agent 智能调度已优化，持续排错能力已验证

---

## 🔴 严重问题 (Critical Issues)

### 1. 性能瓶颈与架构优化 ⚠️ 新增

**问题描述**:
- **响应速度极慢**: 简单查询（如 "查询 R1 的接口数量"）耗时 20+ 秒
- **处理链路不清晰**: 不确定是 LLM 推理、数据库查询还是网络 I/O 造成阻塞
- **Redis 缓存未启用**: 当前架构中 Redis 仅作为占位服务，未实现缓存逻辑

**待排查环节**:
- [ ] **LLM 推理耗时**: 
  - 测量 OpenRouter API 调用延迟
  - 评估 DeepAgents 的 SubAgent 委托开销
  - 对比 simple_agent vs root_agent 性能差异
- [ ] **数据库查询性能**:
  - PostgreSQL Checkpointer 的 `aget_tuple()` 延迟
  - OpenSearch 向量检索响应时间（RAG 未启用时应该为 0）
- [ ] **网络 I/O**:
  - SuzieQ Parquet 文件读取速度
  - NETCONF 设备连接建立时间
- [ ] **Redis 缓存机制**:
  - 当前未实现任何缓存逻辑（既无 LLM 响应缓存，也无 SuzieQ 查询缓存）
  - 需评估引入缓存的收益（是否值得增加复杂度）

**优化方向**:
1. **性能剖析**:
   - **推荐使用 LangChain Studio**（可视化性能分析）:
     ```bash
     uv add langgraph-cli[inmem]
     langgraph dev --debug-port 5678
     # 浏览器访问: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
     ```
     - ✅ 节点耗时可视化（SubAgent、LLM、Checkpointer）
     - ✅ LLM 调用统计（Token 使用、API 延迟）
     - ✅ State 大小监控（消息历史、中间变量）
     - ✅ 瓶颈高亮显示（红色标记慢速节点）
   - 备选方案：添加 `time.perf_counter()` 埋点到关键路径
   - 使用 `cProfile` 分析热点函数
   - 监控 LangGraph 执行图的节点耗时
2. **架构调整**:
   - 评估是否需要 Redis 缓存（LLM 响应、SuzieQ 查询结果）
   - 考虑异步并发优化（目前 SuzieQ 查询可能是串行的）
   - 减少不必要的 Checkpointer 写入
3. **LLM 优化**:
   - 尝试更快的模型（如 gpt-4o-mini）
   - 评估本地 Ollama 部署的性能对比
   - 减少 prompt 长度（当前 root_agent.yaml 约 150 行）

**LangChain Studio vs 自研 CLI**:
- **开发调试**：推荐 Studio（可视化性能、图形化调试、内置 HITL UI）
- **生产运维**：保留自研 CLI（SSH 友好、脚本集成、离线使用）
- **双轨并行**：Studio 排查瓶颈 → CLI 实现优化方案

**优先级**: P0 (严重影响用户体验)  
**预计工作量**: 8-12 小时（性能分析 + 优化实施）

---

### ~~2. OpenRouter/DeepSeek 与 TodoListMiddleware 不兼容~~ ✅ 已解决

**问题描述**:
- 使用 OpenRouter + DeepSeek 时，`TodoListMiddleware` 导致工具调用验证错误
- 错误: `ValidationError: invalid_tool_calls.0.args - Input should be a valid string, got dict`

**根本原因** (已查明):
- OpenRouter/DeepSeek 返回 `tool_calls[].function.arguments` 为 JSON **字符串**
- **错误修复尝试**: 预先将 arguments 从 str 转为 dict，导致 `parse_tool_call()` 调用 `json.loads()` 时抛出 `TypeError`
- TypeError 被捕获后创建 `invalid_tool_calls`，但 args 字段仍为 dict（Pydantic 期望 str）

**最终解决方案** ✅:
```python
# src/olav/core/llm.py
def _fixed_convert_dict_to_message(message_dict: dict):
    # DO NOT modify tool_calls - let parse_tool_call handle JSON parsing
    # Only fix invalid_tool_calls.args if needed
    invalid_tool_calls = message_dict.get("invalid_tool_calls")
    if invalid_tool_calls:
        for tool_call in invalid_tool_calls:
            if "args" in tool_call and isinstance(tool_call["args"], dict):
                tool_call["args"] = json.dumps(tool_call["args"])
    return _convert_dict_to_message(message_dict)
```

**验证结果** (2025-11-21):
- ✅ TodoListMiddleware 已重新启用
- ✅ 复杂查询成功（"对比 R1 和 R2 的接口数量"）
- ✅ 多设备并发查询正常
- ✅ 无 ValidationError 错误

**关键洞察**:
- **问题不在 DeepSeek 模型**，而在对 OpenRouter 格式的错误处理
- **LangChain 期望原始 JSON 字符串** - 预先解析会破坏流程
- **TodoListMiddleware 完全兼容 OpenRouter** - 只要工具调用解析正确

**状态**: ✅ 已完全解决  
**解决日期**: 2025-11-21

---

### 2. Windows 平台 ProactorEventLoop 兼容性

**问题描述**:
- `psycopg` 异步模式在 Windows 默认事件循环下报错
- 错误: `NotImplementedError: Interrupting `wait_for()` is not supported on Windows with ProactorEventLoop`

**解决方案** (已应用):
```python
# 所有异步脚本开头添加
import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
```

**影响文件**:
- ✅ `scripts/test_netbox_hitl.py` - 已修复
- ✅ `src/olav/main.py` - 已修复
- ⚠️ 需检查其他异步脚本

**优先级**: P1 (已修复，需验证覆盖率)  
**预计工作量**: 1 小时 (审计所有异步入口点)

---

## 🟡 中等问题 (Medium Priority Issues)

### 3. Agent 提示词与工具描述优化 ⚠️ 新增

**问题描述**:
- **SuzieQ 高级功能未被利用**: 
  - SuzieQ 内置路由追踪功能（`path show`）可以一次性查询完整路径
  - 当前 Agent 采用"一跳跳查询"方式，多次调用 `routes` 表效率低下
  - 示例: 查询 "192.168.20.101 能否访问 192.168.10.101" 应直接调用 `path show`，而非 4 次独立查询
- **SubAgent 描述仍需优化**:
  - 虽然已将 suzieq_agent 描述从"分析历史数据"改为"查询设备状态、接口、BGP..."，但仍不够具体
  - 缺少对 SuzieQ 高级功能的提示（如 path show、topology、assert）
- **Nornir CLI Agent 功能受限**:
  - 当前未实现 Schema-Aware 查询（只能执行预定义命令）
  - 缺少黑名单机制（高危命令保护）
  - 不支持批量命令执行（需多次调用）

**待优化内容**:

1. **SuzieQ Agent 提示词增强** (`config/prompts/agents/suzieq_agent.yaml`):
   ```yaml
   ## 高级分析功能
   
   - **路径追踪** (path show): 
     - 一次性查询完整路由路径，比手动查询每跳更高效
     - 示例: `suzieq_query(table='path', method='show', src='192.168.20.101', dest='192.168.10.101')`
   
   - **拓扑发现** (topology):
     - 自动构建 LLDP/CDP 拓扑图
     - 示例: `suzieq_query(table='topology', method='get')`
   
   - **健康检查** (assert):
     - 批量验证网络状态（BGP 邻居、接口状态、路由数量）
     - 示例: `suzieq_query(table='bgp', method='assert', status='Established')`
   ```

2. **Nornir CLI Agent 功能扩展** (`src/olav/tools/nornir_tool.py` + `config/prompts/agents/cli_agent.yaml`):
   - **Schema-Aware 支持**: 
     - 集成设备平台的命令映射表（类似 SuzieQ Schema）
     - 允许 LLM 查询 "查看接口状态的命令是什么？" → `show interfaces status`
   - **黑名单机制**:
     ```python
     BLACKLIST_COMMANDS = [
         r"^reload",           # 设备重启
         r"^write\s+erase",    # 擦除配置
         r"^format\s+flash",   # 格式化存储
         r"^delete\s+/force",  # 强制删除
     ]
     ```
   - **批量命令执行**:
     ```python
     @tool
     def nornir_cli_batch(
         commands: list[str],  # 支持多条命令
         devices: list[str],
         stop_on_error: bool = False
     ):
         """Execute multiple CLI commands in sequence"""
     ```

3. **Root Agent 提示词补充** (`config/prompts/agents/root_agent.yaml`):
   - 在场景示例中添加 SuzieQ 高级功能的使用案例
   - 明确说明何时使用 CLI Agent（NETCONF 不可用或需执行特殊命令）

**优先级**: P1 (影响 Agent 智能化水平)  
**预计工作量**: 
- SuzieQ 提示词优化: 2 小时
- Nornir CLI 功能扩展: 6-8 小时（Schema-Aware + 黑名单 + 批量执行）

---

### 4. HITL 审批机制验证与生产化 ⚠️ 新增

**当前状态**:
- ✅ **配置已完成**: `interrupt_on` 已简化为 `{"netbox_api_call": True, "import_devices_from_csv": True}`
- ❌ **测试失败**: `scripts/test_netbox_hitl.py` 运行失败，Agent 未尝试执行写操作
- ⚠️ **CLI 模式不支持交互**: `main.py` 的 chat 命令无 HITL 处理逻辑，写操作会挂起

**最新进展 (2025-11-22 更新)**:
- ✅ 基础 CLI HITL 审批环节已实现 (`main.py`): 在 AIMessage 发出敏感工具调用 (`nornir_tool`, `netconf_tool`, `netbox_api_call`) 前进行交互式审批 (Y/n/i)。
- ✅ 拒绝时立即终止当前查询并返回安全中止提示。
- ⚠️ 现阶段为“前置启发式”审批：基于工具名称判断风险，尚未结合真实写操作解析和风险分级。
- ⚠️ 暂不支持参数编辑/继续流控制（计划在二阶段实现）。
- ⚠️ 未与 LangGraph 原生 interrupt/resume 状态融合，仅在流式解析层拦截。

**CLI HITL 基础实现特点**:
| 能力 | 状态 | 说明 |
|------|------|------|
| 敏感工具名称匹配 | ✅ | `nornir_tool`, `netconf_tool`, `netbox_api_call` |
| 同步终端审批 | ✅ | 阻塞等待用户输入 Y/n/i |
| 拒绝立即中止 | ✅ | 返回提示，不执行后续工具流 |
| 查看详情 (i) | ✅ | JSON 格式展示工具参数 |
| 参数编辑 | ❌ | 预留占位，后续添加 |
| 风险分级 (低/中/高) | ❌ | 后续基于命令/操作类型判定 |
| 多工具批量审批 | ❌ | 逐条审批，后续支持汇总视图 |
| 与 interrupt_on 集成 | ❌ | 目前未调用 LangGraph resume 机制 |

**下一阶段增强 (Phase 2)**:
1. 写操作检测：解析工具参数自动识别“配置/提交/删除”类操作。
2. 风险评分：根据操作类型 + 影响范围生成 risk_level (Low/Medium/High)。
3. 参数编辑：允许用户以 JSON 输入修改字段后继续执行。
4. 多工具合并审批：同一批次多个写操作一次性展示与批准。
5. 内置日志与审计：审批决策写入 `olav-audit` 索引 (operation, decision, actor, timestamp)。
6. LangGraph 原生中断融合：利用中断状态 `resume=approved/rejected/edited` 反馈给 Agent。

**Phase 2 实施任务清单**:
- [ ] 工具参数分类：区分 read/write；在工具包装层标记 `operation_type`。
- [ ] 风险引擎：简单规则集（如包含 `delete`, `commit`, `reload` → High）。
- [ ] 审批数据结构：`{tool, args, risk, impact, proposed_changes}`。
- [ ] 参数编辑 UI：支持 JSON 验证与回填。
- [ ] 审计写入：新增 `audit_logger` 在批准/拒绝时记录。
- [ ] LangGraph resume 集成：在拒绝/编辑时调用底层中断恢复 API。
- [ ] 批量审批缓冲：缓存一批工具调用后统一呈现 (可配置批大小 N)。

**短期验证步骤**:
```bash
uv run python -m olav.main chat "创建一个测试设备"  # 触发 netbox_api_call
uv run python -m olav.main chat "下发接口配置到 R1"  # 触发 nornir_tool
```
期望：出现 HITL 审批提示，输入 `n` 能安全拒绝，`i` 显示参数详情。

**当前限制说明**:
> 该版本 HITL 仅在流式输出层拦截工具调用，无法阻止已经进入执行阶段的异步操作。后续通过 LangGraph 原生中断实现更精细的暂停与恢复。

**问题分析**:
1. **测试脚本失败原因**:
   - LLM 可能未理解应该调用 NetBox 写操作工具
   - NetBox 工具描述不够清晰（需优化 `netbox_api_call` 的 description）
   - 测试 prompt "创建一个测试设备" 可能不够明确
2. **CLI 无 HITL 支持**:
   - 当前 `main.py` 使用 `agent.ainvoke()`，遇到中断会挂起
   - 需要改为 `agent.astream()` + 检查 `state.next` + 用户确认
3. **ChatUI 未实现**:
   - `src/olav/ui/chat_ui.py` 可能没有 HITL 交互界面
   - 需要 Web UI 展示审批界面（操作详情、决策按钮）

**待完成任务**:

1. **修复 CLI 的 HITL 处理** (`src/olav/main.py`):
   
   **方案 A: 终端 Y/N 菜单（推荐）**:
   ```python
   # 简化版 - 终端交互式审批
   async for event in agent.astream(...):
       state = agent.get_state(config)
       if state.next:  # 检测到中断
           # 展示操作摘要
           print("\n" + "="*60)
           print("🔔 需要审批的操作")
           print("="*60)
           print(f"工具: {state.next}")
           print(f"操作类型: {state.values.get('pending_tool')}")
           print(f"影响范围: {state.values.get('impact_summary')}")
           print(f"风险评估: {state.values.get('risk_level', 'Medium')}")
           print("="*60)
           
           # Y/N 菜单
           while True:
               decision = input("\n是否批准此操作？[Y/n/e(编辑)/i(详情)]: ").strip().lower()
               
               if decision in ['y', 'yes', '']:
                   print("✅ 已批准，继续执行...")
                   agent.update_state(config, Command(resume="approved"))
                   break
               elif decision in ['n', 'no']:
                   print("❌ 已拒绝，操作取消")
                   agent.update_state(config, Command(resume="rejected"))
                   return
               elif decision == 'e':
                   # 编辑参数（高级功能）
                   print("\n编辑模式（输入 JSON 格式修改参数，或直接回车保持原样）:")
                   new_params = input("> ")
                   if new_params.strip():
                       # TODO: 解析并更新参数
                       print("⚠️  编辑功能待实现")
                   continue
               elif decision == 'i':
                   # 显示详细信息
                   print("\n详细操作信息:")
                   print(json.dumps(state.values, indent=2, ensure_ascii=False))
                   continue
               else:
                   print("⚠️  无效选择，请输入 Y/n/e/i")
   ```
   
   **方案 B: 三选项模式（完整版）**:
   ```python
   # 完整版 - 支持 Approve/Edit/Reject
   decision = input("决策 [approve/edit/reject]: ").strip().lower()
   
   if decision == "approve":
       agent.update_state(config, Command(resume="approved"))
   elif decision == "reject":
       agent.update_state(config, Command(resume="rejected"))
   elif decision == "edit":
       # 交互式编辑参数
       edited_params = interactive_edit(state.values.get('tool_params'))
       agent.update_state(config, Command(resume={"action": "edit", "params": edited_params}))
   ```
   
   **实现建议**:
   - 优先使用方案 A（Y/N 菜单）- 用户体验更好，符合终端交互习惯
   - 默认选项为 Y（直接回车=批准）- 适合信任场景
   - 提供 'i' 选项查看详情 - 满足审慎用户需求
   - 'e' 编辑功能可选实现 - 降低初期开发复杂度

2. **优化 NetBox 工具描述** (`src/olav/tools/netbox_tool.py`):
   - 明确说明 `netbox_api_call` 可以执行写操作
   - 添加示例: "创建设备: netbox_api_call(endpoint='dcim/devices', method='POST', data={...})"

3. **实现 ChatUI 的 HITL 界面** (`src/olav/ui/chat_ui.py`):
   - 检测 LangGraph 中断
   - 展示审批卡片（操作摘要、影响范围、风险评估）
   - 提供 Approve/Edit/Reject 按钮

4. **编写可复现的 HITL 测试**:
   - 创建 `scripts/test_hitl_simple.py`
   - 直接调用 NetBox 写操作工具（绕过 LLM 理解问题）
   - 验证 `interrupt_on` 配置生效

**优先级**: P1 (安全合规核心功能)  
**预计工作量**: 
- CLI HITL 支持: 4 小时
- ChatUI HITL 界面: 8-12 小时（需前端交互）
- 简化测试脚本: 2 小时

---

### 5. NetBox 集成未完全验证

**问题描述**:
- NetBox 作为 Single Source of Truth，但未完整测试
- 缺少设备清单同步验证
- 标签过滤逻辑 (`olav-managed`, `suzieq-monitor`) 未测试

**待验证功能**:
- [ ] 动态拉取设备清单 (`NBInventory`)
- [ ] 设备角色和站点过滤
- [ ] 标签过滤逻辑
- [ ] inventory.csv ↔ NetBox 双向对齐

**优先级**: P1 (影响数据准确性)  
**预计工作量**: 4-6 小时

---

### 6. SuzieQ 数据采集未验证 ✅ 部分验证

### 6. SuzieQ 数据采集未验证 ✅ 部分验证

**问题描述**:
- ~~SuzieQ 容器运行但未执行真实采集~~ ✅ **已验证正常**
- ~~Parquet 数据目录为空~~ ✅ **已确认有数据**
- ~~`suzieq_query` 工具未在真实数据上测试~~ ✅ **已测试成功**

**验证结果** (2025-11-22):
- ✅ **Poller 正常运行**: `olav-suzieq-poller` 容器运行正常
- ✅ **数据采集正常**: 最近 5 分钟内生成了 6 个设备的 Parquet 文件
  - 设备: R1, R2, R3, R4, SW1, SW2
  - 数据表: interfaces, routes, bgp, ospf, arpnd 等
- ✅ **工具查询成功**: 
  - "查询 R1 的接口数量" → 返回 5 个接口
  - "192.168.20.101 能否访问 192.168.10.101" → 完整路由路径分析

**待完成任务**:
- [x] 配置 SuzieQ 采集任务 (基于 NetBox 标签) - ✅ 已配置
- [x] 验证 Parquet 数据生成 - ✅ 已验证
- [x] 测试 `get/summarize/unique/aver` 方法 - ✅ 已测试 get/summarize
- [ ] 测试 SuzieQ 高级功能 (`path show`, `topology`, `assert`) - ⚠️ 待测试

**优先级**: P2 (基础功能已验证，高级功能待测试)  
**预计工作量**: 2-4 小时（测试高级功能）

---

### 7. OpenSearch 三层 RAG 索引未完全建立 ⚠️ 部分验证

**问题描述**:
- **第 1 层 RAG (Episodic Memory)** - ✅ **已测试工作良好**
  - 索引: `olav-episodic-memory` - 历史成功路径索引
  - 工具: `search_episodic_memory` 已修复并验证
  - 状态: 向量检索正常，可返回历史操作案例
- **第 2 层 RAG (Schema Index)** - ⚠️ **待测试**
  - 索引: `openconfig-schema` - OpenConfig YANG 路径索引
  - 索引: `suzieq-schema` - SuzieQ Avro 字段索引
  - 工具: `search_openconfig_schema`, `suzieq_schema_search`
  - 状态: 索引可能已创建，但未验证查询功能
- **第 3 层 RAG (Documents)** - ⚠️ **待测试**
  - 索引: `olav-docs` - RFC、厂商文档向量索引
  - 工具: `search_documents`（可能未实现）
  - 状态: 文档嵌入流水线未验证

**测试结果** (2025-11-22):
- ✅ **第 1 层验证成功**: 
  - 工具: `search_episodic_memory` 已从类方法改为独立 async 函数
  - 修复: 移除 `@tool` 装饰器冲突，消除 `self` 参数暴露
  - 查询: 可正常返回历史成功路径（User Intent → XPath 映射）
- ❌ **第 2 层未测试**: Schema 索引存在性未知
- ❌ **第 3 层未测试**: 文档嵌入流水线未实现

**待完成任务**:
- [x] 修复第 1 层 RAG 工具 (`search_episodic_memory`) - ✅ 已完成
- [ ] 验证第 2 层索引存在性:
  ```bash
  curl http://localhost:9200/_cat/indices?v | grep -E "openconfig|suzieq"
  ```
- [ ] 测试第 2 层工具:
  - `search_openconfig_schema("如何配置 BGP neighbor")` → 应返回 XPath
  - `suzieq_schema_search("查询接口状态的字段")` → 应返回 Avro Schema
- [ ] 修复 `init_schema.py` 执行错误（如果索引不存在）
- [ ] 实现 `suzieq_schema_etl.py`（如果索引不存在）
- [ ] 实现第 3 层文档嵌入流水线
- [ ] 创建 mapping 模板（统一向量维度、分词器配置）

**优先级**: 
- 第 1 层: ✅ P0 已完成
- 第 2 层: P1 (影响 Schema-Aware 查询)
- 第 3 层: P2 (影响文档检索智能化)

**预计工作量**: 
- 第 2 层验证: 2-4 小时
- 第 3 层实现: 8-12 小时

---

### 8. FastAPI/LangServe 未实现

**问题描述**:
- `serve()` 命令仅为占位循环
- 缺少 HTTP API 端点
- 无法通过 Web 调用 Agent

**待实现端点**:
- [ ] `GET /health` - 健康检查
- [ ] `POST /chat` - 对话接口
- [ ] `GET /devices` - 设备列表
- [ ] `GET /schema/search` - Schema 查询
- [ ] `POST /agent/invoke` - Agent 调用
- [ ] WebSocket 流式响应

**优先级**: P2 (影响生产部署)  
**预计工作量**: 8-12 小时

---

## 🟢 低优先级问题 (Low Priority Issues)

### 9. 日志系统不完善

**问题**:
- 只有 stdout 日志，无文件持久化
- 缺少日志轮转 (rotation)
- 缺少结构化日志 (JSON)

**待改进**:
- [ ] 接入 `LoggingConfig.LOG_FILE`
- [ ] 添加 `RotatingFileHandler`
- [ ] 实现 JSON 格式日志
- [ ] 集成 ELK/Loki (可选)

**优先级**: P3  
**预计工作量**: 4 小时

---

### 10. 单元测试覆盖率不足

**当前状态**: 11 passed / 9 skipped

**待补充测试**:
- [ ] SuzieQ 工具 Mock 测试
- [ ] OpenSearch RAG 工具测试
- [ ] Nornir Sandbox 执行测试
- [ ] 端到端 API 测试 (需 FastAPI 先完成)

**优先级**: P3  
**预计工作量**: 8-10 小时

---

### 11. 审计日志未持久化

**问题**:
- NETCONF/CLI 执行结果未记录到 OpenSearch
- 缺少操作审计索引
- 无法追溯历史操作

**待实现**:
- [ ] 创建 `olav-audit` 索引
- [ ] 在 `NornirSandbox.execute()` 中写入审计
- [ ] 实现审计查询接口

**优先级**: P3 (安全合规需求)  
**预计工作量**: 4-6 小时

---

### 12. 初始化 ETL 无幂等性

**问题**:
- `olav-init` 重复运行可能造成重复索引
- 缺少 `data/bootstrap/init.ok` 哨兵文件检查

**待改进**:
- [ ] 添加索引存在性检查
- [ ] 实现幂等写入逻辑
- [ ] 添加 `--force-reinit` 参数

**优先级**: P3  
**预计工作量**: 2-3 小时

---

## ✅ 已解决问题 (Resolved Issues)

### ✅ Root Agent 智能工具调度优化 (2025-11-22)
- **问题**: Root Agent 需要明确指定工具名称（如 "使用 SuzieQ 查询..."）才能正常工作
- **根本原因**:
  1. **SubAgent 描述过于抽象**: suzieq_agent 描述为 "分析网络历史数据"，LLM 无法理解应该用它查询接口数量
  2. **Root Agent prompt 僵化**: 固定的 "知识检索阶段使用 rag_agent" 流程，限制了智能选择
- **解决方案**:
  1. **具体化 SubAgent 描述** (`src/olav/agents/suzieq_agent.py`):
     ```python
     description=(
         "查询和分析网络设备状态、接口信息、BGP/OSPF 邻居关系、路由表、"
         "ARP/NDP 表等网络数据（基于 SuzieQ 历史数据）。"
         "适用场景：设备接口统计、BGP 邻居状态、路由可达性分析、网络拓扑发现等。"
     )
     ```
  2. **重构 Root Agent prompt** (`config/prompts/agents/root_agent.yaml`):
     - 删除僵化的 "1. 知识检索阶段 → 2. 历史分析阶段" 流程
     - 添加场景化分类（场景 1: 网络数据查询 → suzieq_agent）
     - 添加快速选择指南表格（问 "有多少"、"状态如何" → suzieq_agent）
     - 添加复杂场景示例（路由可达性排查、批量设备上线）
- **验证结果**:
  - ✅ **智能调度成功**: "查询 R1 的接口数量" → 自动选择 suzieq-analyzer（无需明确指定）
  - ✅ **持续排错能力**: "192.168.20.101 能否访问 192.168.10.101" → 自动推理路由路径（R4 → R2 → R1 → R3），验证每一跳状态
  - ✅ **响应质量提升**: 完整的接口统计、状态分析、风险提示、建议操作
- **解决日期**: 2025-11-22

### ✅ 第 1 层 RAG (Episodic Memory) 工具修复 (2025-11-22)
- **问题**: `search_episodic_memory` 工具报错 `TypeError: StructuredTool._run() got multiple values for argument 'self'`
- **根本原因**: 
  - `@tool` 装饰器错误应用在类方法上
  - LangChain 期望独立函数，而非类方法
  - 类方法的 `self` 参数与工具参数冲突
- **解决方案**:
  1. **移除类方法的 `@tool` 装饰器**
  2. **创建独立的 async 包装函数**:
     ```python
     # src/olav/tools/opensearch_tool.py
     class OpenSearchRAGTool:
         async def search_episodic_memory(self, intent: str):  # 无 @tool
             ...
     
     # 独立的 async 包装函数
     @tool
     async def search_episodic_memory(intent: str) -> list[dict[str, Any]]:
         """Search episodic memory..."""
         query = {...}
         results = await _opensearch_rag_tool.memory.search_schema(
             index="olav-episodic-memory",
             query=query,
             size=3,
         )
         return results
     ```
- **验证结果**:
  - ✅ 工具调用成功，无 `self` 参数错误
  - ✅ 可正常查询历史成功路径（User Intent → XPath 映射）
  - ✅ Root Agent 可正常调用第 1 层 RAG
- **解决日期**: 2025-11-22

### ✅ PostgreSQL Checkpointer 设置问题
- **问题**: `'_GeneratorContextManager' has no attribute 'setup'`
- **解决方案**: 使用 `AsyncPostgresSaver` + `async with` 模式
- **文档**: `docs/CHECKPOINTER_SETUP.md`, `docs/CHECKPOINTER_FIX_SUMMARY.md`
- **解决日期**: 2025-11-21

### ✅ LLM 工具调用 JSON 解析错误 (最终版本)
- **问题**: `invalid_tool_calls.0.args - Input should be a valid string, got dict`
- **根本原因**: 
  - OpenRouter/DeepSeek 返回 `tool_calls[].function.arguments` 为 JSON 字符串
  - 之前的修复尝试**预先解析** arguments 为 dict，导致 `parse_tool_call()` 在调用 `json.loads()` 时抛出 `TypeError`
  - TypeError 被捕获并创建 `invalid_tool_calls`，其 `args` 字段为 dict（但 Pydantic 期望 str）
- **最终解决方案**: 
  - **不修改** `tool_calls[].function.arguments` - 保持为 JSON 字符串
  - 让 LangChain 的 `parse_tool_call()` 自然处理 JSON 解析
  - 只修复 `invalid_tool_calls.args`（如果出现）- dict → str
- **关键代码**:
  ```python
  # src/olav/core/llm.py
  def _fixed_convert_dict_to_message(message_dict: dict):
      # DO NOT modify tool_calls - let parse_tool_call handle it
      # Only fix invalid_tool_calls.args if needed
      invalid_tool_calls = message_dict.get("invalid_tool_calls")
      if invalid_tool_calls:
          for tool_call in invalid_tool_calls:
              if "args" in tool_call and isinstance(tool_call["args"], dict):
                  tool_call["args"] = json.dumps(tool_call["args"])
      return _convert_dict_to_message(message_dict)
  ```
- **验证结果**:
  - ✅ 工具调用成功解析
  - ✅ `invalid_tool_calls` 为空
  - ✅ R1 NETCONF 查询成功返回接口状态
- **解决日期**: 2025-11-21

### ✅ CLI 交互式对话实现
- **问题**: 用户无法使用 `chat` 命令
- **解决方案**: 实现完整的 CLI 对话循环 + PostgreSQL 会话持久化
- **文件**: `src/olav/main.py`
- **解决日期**: 2025-11-21

### ✅ OpenConfig/NETCONF 功能验证
- **问题**: 无法确认真实设备是否支持 OpenConfig
- **解决方案**: 
  - 创建 `scripts/test_openconfig_support.py` 测试工具
  - 验证 Cisco IOS-XE 设备 (192.168.100.101-102) 完全支持 OpenConfig
  - 更新 R1/R2 设备清单为 `cisco_iosxe` 平台
  - 成功通过 NETCONF 查询 R1 接口状态
- **测试结果**:
  - ✅ 74 个 OpenConfig 模型支持
  - ✅ NETCONF 连接成功 (端口 830)
  - ✅ 实际查询返回结构化接口数据
- **解决日期**: 2025-11-21


---

## 📋 待办事项优先级排序

### Sprint 1: 核心功能完善 (1-2 周) ✅ 90% 完成
1. ✅ **[已完成]** 修复 Checkpointer 设置问题
2. ✅ **[已完成]** 修复 LLM 工具调用解析
3. ✅ **[已完成]** 实现 CLI 交互式对话
4. ✅ **[已完成]** 验证 OpenConfig/NETCONF 功能 (R1/R2 查询成功)
5. ✅ **[已完成]** 解决 TodoListMiddleware 问题 (已修复并重新启用)
6. ✅ **[已完成]** 优化 Root Agent 智能调度 (SubAgent 描述 + prompt 重构)
7. ✅ **[已完成]** 验证 SuzieQ 数据采集 (Poller 正常，基础查询成功)
8. ⚠️ **[P0]** 性能优化与架构分析 (响应速度过慢，需排查瓶颈)

### Sprint 2: Agent 智能化增强 (2-3 周) ⚠️ 50% 完成
9. ✅ **[已完成]** 修复第 1 层 RAG 工具 (search_episodic_memory)
10. ⚠️ **[P1]** Agent 提示词与工具描述优化
   - SuzieQ 高级功能提示 (path show, topology, assert)
   - Nornir CLI Schema-Aware + 黑名单 + 批量执行
11. ⚠️ **[P1]** HITL 审批机制验证与生产化
    - CLI HITL 支持 (终端 Y/N 菜单实现)
    - ChatUI HITL 界面
    - 简化测试脚本验证
12. ⚠️ **[P1]** 验证第 2 层 RAG (Schema Index)
    - 检查 openconfig-schema、suzieq-schema 索引存在性
    - 测试 search_openconfig_schema、suzieq_schema_search 工具
13. 🟡 **[P1]** 验证 NetBox 集成 (设备清单同步、标签过滤)
14. 🟡 **[P2]** 实现第 3 层 RAG (Documents)
    - 文档分块与嵌入流水线
    - olav-docs 索引创建

### Sprint 3: 生产就绪 (3-4 周)
15. 🟡 **[P2]** 实现 FastAPI/LangServe HTTP API
16. 🟢 **[P3]** 完善日志系统
17. 🟢 **[P3]** 实现审计日志持久化
17. 🟢 **[P3]** 提升单元测试覆盖率
18. 🟢 **[P3]** 添加 ETL 幂等性
19. 🟢 **[P3]** 编写真实设备测试用例

---

## 📚 相关文档

### 核心文档 (保留)
- `docs/DESIGN.md` - 架构设计说明
- `docs/CHECKPOINTER_SETUP.md` - Checkpointer 配置指南
- `docs/CHECKPOINTER_FIX_SUMMARY.md` - Checkpointer 问题总结
- `docs/NETBOX_AGENT_HITL.md` - HITL 审批流程
- `QUICKSTART.md` - 快速启动指南
- `README.MD` - 项目总览

### 归档文档 (历史参考)
- `archive/docs_archived_20251121/CURRENT_ISSUES.md` - 旧版问题列表
- `archive/docs_archived_20251121/IMPLEMENTATION.md` - 实现总结
- `archive/docs_archived_20251121/OPENROUTER_CONFIG_REPORT.md` - OpenRouter 配置
- `archive/docs_archived_20251121/QUICK_REFERENCE.md` - 快速参考
- `archive/docs_archived_20251121/REAL_DEVICE_TESTING.md` - 真实设备测试
- `archive/docs_archived_20251121/TEST_EXECUTION_SUMMARY.md` - 测试执行总结
- `archive/docs_archived_20251121/TEST_REPORT.md` - 测试报告

---

## 🎯 下一步行动建议

### 立即执行 (本周) ⚠️ 更新
1. **性能瓶颈排查** (P0) - **推荐使用 LangChain Studio**:
   ```bash
   # 安装 LangGraph CLI
   uv add langgraph-cli[inmem]
   
   # 启动开发服务器（带调试端口）
   langgraph dev --debug-port 5678
   
   # 浏览器访问 Studio
   # https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024
   
   # 执行测试查询："查询 R1 的接口数量"
   # 查看性能分析：
   #   - 哪个节点最慢（LLM / Checkpointer / SubAgent）
   #   - LLM API 延迟是多少
   #   - State 序列化开销
   #   - 总执行时间分布
   ```
   - **Studio 优势**：
     - ✅ 可视化性能剖析（节点耗时图）
     - ✅ LLM 调用追踪（Token、延迟、成本）
     - ✅ Checkpointer 监控（读写频率）
     - ✅ 内存/State 大小分析
   - **备选方案**：使用 `cProfile` 分析热点函数
   - 目标: 将响应时间从 20+ 秒降低到 5 秒以内

2. **Agent 提示词优化** (P1):
   - SuzieQ Agent: 添加 `path show`、`topology`、`assert` 使用指南
   - Root Agent: 补充 SuzieQ 高级功能的场景示例
   - Nornir CLI Agent: 实现 Schema-Aware + 黑名单机制

3. **HITL 机制验证** (P1):
   - **方案 A**: 使用 Studio 内置 HITL UI（推荐开发调试）
   - **方案 B**: 实现 CLI 终端 Y/N 菜单（生产运维）
   - 编写简化测试脚本（直接调用写操作工具）
   - 验证 `interrupt_on` 配置生效

4. **验证第 2 层 RAG** (P1):
   - 检查 openconfig-schema、suzieq-schema 索引是否存在
   - 测试 search_openconfig_schema、suzieq_schema_search 工具
   - 如索引不存在，运行 init_schema.py、suzieq_schema_etl.py

### 短期目标 (2-4 周)
5. **完成 NetBox 集成验证**:
   - 测试 `NBInventory` 插件
   - 验证标签过滤逻辑
   - 确保 inventory.csv ↔ NetBox 双向对齐

6. **实现 ChatUI 的 HITL 界面**:
   - 检测 LangGraph 中断
   - 展示审批卡片（操作摘要、影响范围）
   - 提供 Approve/Edit/Reject 按钮

7. **实现第 3 层 RAG**:
   - 文档分块与嵌入流水线
   - 创建 olav-docs 索引
   - 验证文档检索功能

### 中期目标 (1-2 月)
8. **实现 HTTP API**:
   - FastAPI 基础骨架
   - 核心端点 (/chat, /health)
   - WebSocket 流式响应

9. **生产化部署**:
   - 完善日志系统
   - 添加监控告警
   - 实现审计日志
   - 编写运维文档

---

## 📊 项目健康度评估

| 维度 | 状态 | 评分 | 说明 |
|------|------|------|------|
| **核心架构** | ✅ | 9/10 | 设计完善，已验证 |
| **基础功能** | ✅ | 9/10 | CLI 可用，工具正常，智能调度优化完成 |
| **Agent 智能化** | ⚠️ | 7/10 | 智能调度已优化，提示词需进一步增强 |
| **性能表现** | ❌ | 4/10 | 响应速度过慢（20+ 秒），需紧急优化 |
| **数据集成** | ⚠️ | 6/10 | SuzieQ 已验证，NetBox 待测试 |
| **RAG 能力** | ⚠️ | 4/10 | 第 1 层已验证，第 2、3 层待测试 |
| **HITL 机制** | ⚠️ | 5/10 | 配置完成，CLI 终端菜单待实现 |
| **生产就绪度** | ❌ | 3/10 | 缺 API/日志/审计 |

**总体评分**: **6.5/10** - 核心可用，智能调度优化完成，第 1 层 RAG 已验证

**关键改进点**:
- ✅ **智能调度**: SubAgent 描述具体化 + Root prompt 场景化（从 "需要明确指定" → "自动选择"）
- ✅ **持续排错**: 路由可达性分析验证成功（自动推理 4 跳路径）
- ✅ **第 1 层 RAG**: search_episodic_memory 工具修复完成，历史成功路径检索正常
- ⚠️ **性能瓶颈**: 响应速度过慢，需紧急排查（LLM、Checkpointer、I/O）
- ⚠️ **提示词优化**: SuzieQ 高级功能未利用（path show vs 逐跳查询）
- ⚠️ **第 2、3 层 RAG**: Schema Index 和 Documents Index 待验证

---

## 📞 技术支持

**遇到问题?**
1. 查看 `docs/` 目录下的专题文档
2. 查看 `QUICKSTART.md` Section 9 (已知问题)
3. 查看归档文档 `archive/docs_archived_20251121/`
4. 提交 GitHub Issue (待创建仓库)

**最后更新**: 2025-11-22 02:45 UTC+8

**本次更新摘要**:
- ✅ Root Agent 智能调度优化完成（SubAgent 描述 + prompt 重构）
- ✅ SuzieQ 数据采集验证完成（Poller 正常，基础查询成功）
- ✅ 第 1 层 RAG 工具修复完成（search_episodic_memory 异步包装）
- ⚠️ 新增性能瓶颈问题（P0 优先级，响应速度过慢）
- ⚠️ 新增 Agent 提示词优化需求（SuzieQ 高级功能、Nornir CLI Schema-Aware）
- ⚠️ 新增 HITL 验证与生产化任务（CLI 终端 Y/N 菜单、ChatUI 支持待实现）
- ⚠️ 新增第 2、3 层 RAG 验证任务（Schema Index 和 Documents Index）

---

## 🔄 HITL / 白名单 最新增量 (2025-11-22)

**已完成**:
- 基础 CLI HITL 审批（写操作前 Y/n/i 交互）。
- 动态白名单文件 `config/cli_whitelist.yaml`（批准后自动追加 JSON 签名）。
- 支持工具：`cli_tool` 配置命令、`netconf_tool` edit-config、`nornir_tool`（后续扩展）、`netbox_api_call` 写操作。
- 自动持久化：批准后立即写入文件并可挂载到容器以实现跨运行保留。

**待完成**:
| 项目 | 描述 | 优先级 |
|------|------|--------|
| 风险分级 | 根据命令类型打标签 (Low/Medium/High) | P1 |
| 解析写意图 | 更精准识别写操作（不依赖字符串包含） | P1 |
| 批量审批 | 多个写操作集中显示一次审批 | P2 |
| 参数编辑 | 在审批界面可 JSON 修改参数后继续 | P2 |
| 审计日志 | 批准/拒绝写入 `olav-audit` 索引 | P2 |
| ChatUI 集成 | 图形化 HITL 卡片（Web 或 TUI） | P2 |
| LangGraph 中断融合 | 使用原生 `resume=approved/rejected/edited` 状态 | P1 |
| 容器挂载文档 | 在 docker-compose 中挂载 `config/` 以持久化白名单 | P1 |

**容器挂载示例（待加入 compose）**:
```yaml
  olav-app:
    volumes:
      - ./config:/app/config:rw
```

---

## ✅ / ⚠️ 总体剩余问题快照 (2025-11-22)

| 分类 | 状态 | 关键剩余工作 |
|------|------|--------------|
| 性能 P0 | ⚠️ | 添加 NETCONF/CLI 计时；启用 LangChain Studio；缓存 schema 查询 |
| HITL 第二阶段 | ⚠️ | 风险分级、批量审批、审计索引、参数编辑、LangGraph 中断融合 |
| RAG 层 2/3 | ⚠️ | 验证 `openconfig-schema` / `suzieq-schema` 索引；实现文档嵌入流水线 |
| NetBox 集成 | ⚠️ | 标签过滤与设备清单同步验证；双向对齐 inventory.csv |
| FastAPI API | ⚠️ | 实现 /health, /chat, WebSocket 流式接口 |
| 日志系统 | ⚠️ | 结构化 JSON + 文件轮转 + 采集到集中平台 |
| 审计日志 | ⚠️ | 写操作审计持久化到 OpenSearch `olav-audit` |
| 单测覆盖率 | ⚠️ | SuzieQ 高级方法、HITL 分支、RAG 层 2/3、Nornir Sandbox |
| ETL 幂等性 | ⚠️ | 索引存在检查，添加哨兵文件，`--force-reinit` 参数 |
| Timing 未完成 | ⚠️ | 已有 SuzieQ 装饰器；需扩展到 NETCONF/CLI 并汇总到最终响应 |

**下一优先序列**:
1. 性能与计时补全（P0）
2. HITL 风险分级与审计（P1）
3. Schema 索引验证（P1）
4. NetBox 全量验证（P1）
5. FastAPI 基础框架（P2）

---
