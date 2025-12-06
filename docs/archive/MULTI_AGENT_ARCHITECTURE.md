# OLAV Multi-Agent Architecture Design

> 基于 LangChain 最佳实践的多代理系统重构方案

## 1. 当前问题分析

### 1.1 Standard Mode 现状

当前 `QueryDiagnosticWorkflow` 存在以下问题：

| 问题 | 影响 |
|------|------|
| **工具过多** (15+ tools) | LLM 选择困难，token 消耗大 |
| **职责混合** | 索引工具与诊断工具混在一起 |
| **层级不清** | 4 层漏斗工具未按优先级组织 |
| **缺乏意图分类** | 使用关键词匹配，不够智能 |

### 1.2 LangChain 最佳实践

根据 LangChain 官方建议：
- **每个代理 3-7 个工具**：减少 LLM 决策复杂度
- **单一职责原则**：每个代理专注一个任务域
- **Hub-and-Spoke 模式**：统一的编排器管理多个专业代理

## 2. 目标架构

### 2.1 Hub-and-Spoke 多代理模式

```
                    ┌─────────────────────┐
                    │   User Interface    │
                    │   (API / CLI)       │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Root Orchestrator │◄─────────────────┐
                    │   (Intent Router)   │                  │
                    └──────────┬──────────┘                  │
                               │                             │
            ┌──────────────────┼──────────────────┐         │
            │                  │                  │         │
            ▼                  ▼                  ▼         │
    ┌───────────────┐  ┌───────────────┐  ┌───────────────┐ │
    │  Query Agent  │  │ Diagnose Agent│  │ Config Agent  │ │
    │   (3 tools)   │  │   (4 tools)   │  │  (3 tools)    │ │
    └───────┬───────┘  └───────┬───────┘  └───────┬───────┘ │
            │                  │                  │         │
            │                  │                  │         │
            └──────────────────┴──────────────────┘         │
                               │                             │
                               ▼                             │
                    ┌─────────────────────┐                  │
                    │   HITL Checkpoint   │──────────────────┘
                    │  (Write Approval)   │
                    └─────────────────────┘
```

### 2.2 代理职责划分

#### Query Agent (查询代理)
**职责**: 信息检索，只读操作

| 工具 | 用途 | 层级 |
|------|------|------|
| `suzieq_query` | 缓存遥测数据查询 | L2 |
| `netbox_query` | SSOT 设备/配置查询 | L3 |
| `document_search` | 知识库文档搜索 | L1 |

#### Diagnose Agent (诊断代理)
**职责**: 问题分析，可能需要实时数据

| 工具 | 用途 | 层级 |
|------|------|------|
| `suzieq_schema_search` | 发现可用表和字段 | L2 Meta |
| `openconfig_schema_search` | 查找 YANG 路径 | L1 Meta |
| `netconf_get` | 实时设备状态读取 | L4 Read |
| `syslog_search` | 日志事件分析 | L3 |

#### Config Agent (配置代理)
**职责**: 配置变更，需要 HITL 审批

| 工具 | 用途 | HITL |
|------|------|------|
| `netconf_edit` | NETCONF edit-config | ✅ 必须 |
| `cli_config` | CLI 配置命令 | ✅ 必须 |
| `netbox_write` | NetBox 创建/更新/删除 | ✅ 必须 |

### 2.3 意图分类器

替换当前的关键词匹配，使用 LLM-based 意图分类：

```python
class IntentClassifier:
    """LLM-based intent classification for routing."""
    
    INTENTS = {
        "query": "信息查询、列表获取、状态检查（只读）",
        "diagnose": "故障诊断、问题分析、根因定位",
        "config": "配置变更、创建删除、修改设置"
    }
    
    async def classify(self, user_query: str) -> Intent:
        """Classify user intent using structured output."""
        # Use LLM with structured output
        return await self.llm.with_structured_output(Intent).ainvoke(...)
```

## 3. 实施计划

### Phase 1: 工具精简 (立即可做)

**目标**: 减少工具数量，明确工具职责

1. **移除索引工具** from `micro_tools`:
   - `index_document` → 移到独立的 ETL 脚本
   - `index_directory` → 移到独立的 ETL 脚本

2. **合并重复工具**:
   - `netbox_api_call` + `netbox_schema_search` → 保留，但只在 Config Agent
   - `netconf_execute` (get + edit) → 拆分为 `netconf_get` 和 `netconf_edit`

3. **更新 prompt 配置**:
   - 添加工具优先级指导
   - 明确每层工具的使用场景

### Phase 2: 意图分类器 (短期)

**目标**: 替换关键词匹配，智能路由

1. **创建 `IntentClassifier`**:
   ```
   src/olav/agents/intent_classifier.py
   ```

2. **定义意图 schema**:
   ```
   config/prompts/agents/intent_classifier.yaml
   ```

3. **集成到 Root Orchestrator**:
   - 替换 `_detect_workflow_type()` 方法

### Phase 3: 多代理拆分 (中期)

**目标**: 实现 Hub-and-Spoke 架构

1. **创建专业代理**:
   ```
   src/olav/agents/
   ├── query_agent.py      # 3 tools
   ├── diagnose_agent.py   # 4 tools
   └── config_agent.py     # 3 tools (all HITL)
   ```

2. **更新 Root Orchestrator**:
   - 使用意图分类器路由
   - 支持 Agent Handoff (Diagnose → Config)

3. **统一 HITL 处理**:
   - 所有写操作通过 Config Agent
   - Config Agent 自动触发 HITL interrupt

## 4. 文件变更清单

### 4.1 需要修改的文件

| 文件 | 变更类型 | 描述 |
|------|----------|------|
| `src/olav/workflows/query_diagnostic.py` | 修改 | 移除索引工具 |
| `src/olav/tools/nornir_tool.py` | 修改 | 拆分 get/edit 方法 |
| `config/prompts/strategies/deep_path/micro_diagnosis.yaml` | 修改 | 添加工具优先级 |

### 4.2 需要新建的文件

| 文件 | 用途 |
|------|------|
| `src/olav/agents/intent_classifier.py` | 意图分类器 |
| `src/olav/agents/query_agent.py` | 查询代理 |
| `src/olav/agents/diagnose_agent.py` | 诊断代理 |
| `src/olav/agents/config_agent.py` | 配置代理 |
| `config/prompts/agents/intent_classifier.yaml` | 意图分类 prompt |
| `config/prompts/agents/query_agent.yaml` | 查询代理 prompt |
| `config/prompts/agents/diagnose_agent.yaml` | 诊断代理 prompt |
| `config/prompts/agents/config_agent.yaml` | 配置代理 prompt |

### 4.3 需要归档的文件

| 文件 | 原因 |
|------|------|
| `src/olav/tools/document_tools.py` (index 部分) | 索引功能移到 ETL |

## 5. Agent Handoff 机制

### 5.1 场景示例

用户: "诊断 R1 的 BGP 问题，如果发现配置错误就修复"

```
1. Root Orchestrator
   ├── Intent: "diagnose" + "config" (复合意图)
   └── Route to: Diagnose Agent (first)

2. Diagnose Agent
   ├── 使用 suzieq_query 检查 BGP 状态
   ├── 使用 netconf_get 获取 BGP 配置
   ├── 发现问题: neighbor 配置错误
   └── 返回: {issue: "...", suggested_fix: "..."}

3. Root Orchestrator
   ├── 检测到需要配置变更
   └── Route to: Config Agent (handoff)

4. Config Agent
   ├── 准备 edit-config payload
   ├── 触发 HITL interrupt
   ├── 用户审批
   └── 执行配置变更
```

### 5.2 Handoff 实现

```python
class RootOrchestrator:
    async def run(self, query: str):
        intent = await self.intent_classifier.classify(query)
        
        # Phase 1: Execute primary intent
        if intent.primary == "diagnose":
            result = await self.diagnose_agent.run(query)
            
            # Check for handoff signal
            if result.needs_config_change:
                # Phase 2: Handoff to Config Agent
                config_result = await self.config_agent.run(
                    task=result.suggested_fix,
                    context=result.diagnosis_context
                )
                return self._merge_results(result, config_result)
        
        return result
```

## 6. 测试策略

### 6.1 单元测试

```python
# tests/unit/test_intent_classifier.py
def test_query_intent():
    assert classifier.classify("列出所有设备") == Intent.QUERY

def test_diagnose_intent():
    assert classifier.classify("为什么 BGP 邻居断开") == Intent.DIAGNOSE

def test_config_intent():
    assert classifier.classify("创建 VLAN 100") == Intent.CONFIG
```

### 6.2 E2E 测试

参考现有的 `tests/e2e/test_standard_mode_tools.py`，扩展：

- 测试意图路由正确性
- 测试 Agent Handoff 流程
- 测试 HITL 触发时机

## 7. 时间估算

| 阶段 | 工作量 | 预计时间 |
|------|--------|----------|
| Phase 1: 工具精简 | 小 | 1-2 小时 |
| Phase 2: 意图分类器 | 中 | 2-4 小时 |
| Phase 3: 多代理拆分 | 大 | 4-8 小时 |
| 测试和调试 | 中 | 2-4 小时 |

**总计**: 约 1-2 个工作日

## 8. 回滚计划

如果新架构出现问题：

1. **Phase 1 回滚**: 恢复 `query_diagnostic.py` 的工具列表
2. **Phase 2 回滚**: 在 Root Orchestrator 中切换回关键词匹配
3. **Phase 3 回滚**: 保留多代理但使用单代理模式运行

所有变更都应该是渐进式的，确保每个阶段都可以独立回滚。

---

**文档版本**: 1.0  
**创建日期**: 2025-12-03  
**作者**: AI Assistant (基于 LangChain 最佳实践)

---

## 9. 实施完成总结

### 9.1 已创建的文件

| 文件 | 用途 | 状态 |
|------|------|------|
| `src/olav/agents/base.py` | BaseAgent 协议和抽象基类 | ✅ 完成 |
| `src/olav/agents/intent_classifier.py` | LLM-based 意图分类器 | ✅ 完成 |
| `src/olav/agents/query_agent.py` | 查询代理 (3 tools) | ✅ 完成 |
| `src/olav/agents/diagnose_agent.py` | 诊断代理 (4 tools) | ✅ 完成 |
| `src/olav/agents/config_agent.py` | 配置代理 (3 tools, HITL) | ✅ 完成 |
| `src/olav/agents/multi_agent_orchestrator.py` | 多代理编排器 | ✅ 完成 |
| `config/prompts/agents/intent_classifier/system.yaml` | 意图分类 prompt | ✅ 完成 |
| `tests/unit/test_multi_agent.py` | 单元测试 | ✅ 完成 |

### 9.2 已修改的文件

| 文件 | 变更 | 状态 |
|------|------|------|
| `src/olav/workflows/query_diagnostic.py` | 移除索引工具 | ✅ 完成 |
| `src/olav/tools/nornir_tool.py` | 添加 netconf_get, netconf_edit, cli_show, cli_config | ✅ 完成 |
| `config/prompts/workflows/query_diagnostic/micro_diagnosis.yaml` | 添加工具优先级指导 | ✅ 完成 |
| `src/olav/agents/__init__.py` | 导出新代理 | ✅ 完成 |

### 9.3 工具拆分

**之前 (2 个通用工具):**
- `netconf_tool(operation="get-config"/"edit-config")`
- `cli_tool(command=... / config_commands=...)`

**之后 (4 个专用工具):**
| 工具 | 类型 | HITL |
|------|------|------|
| `netconf_get` | 只读 | ❌ |
| `netconf_edit` | 写入 | ✅ |
| `cli_show` | 只读 | ❌ |
| `cli_config` | 写入 | ✅ |

### 9.4 代理工具分配

| Agent | Tools | Count |
|-------|-------|-------|
| **Query Agent** | suzieq_query, netbox_api_call, search_documents | 3 |
| **Diagnose Agent** | suzieq_schema_search, search_openconfig_schema, netconf_get, syslog_search | 4 |
| **Config Agent** | netconf_edit, cli_config, netbox_api_call | 3 |

### 9.5 向后兼容性

- **保留**: `WorkflowOrchestrator` 和 `create_workflow_orchestrator()` 继续可用
- **新增**: `MultiAgentOrchestrator` 和 `create_multi_agent_orchestrator()` 作为新入口点
- **兼容**: 旧工具 `netconf_tool`, `cli_tool` 仍然可用，新工具是额外添加的

### 9.6 使用新架构

```python
# 新架构入口
from olav.agents import create_multi_agent_orchestrator

orchestrator = await create_multi_agent_orchestrator()
result = await orchestrator.route("查询 R1 的 BGP 状态", thread_id="user-123")

print(f"意图: {result.intent.primary}")
print(f"使用代理: {result.agent_used}")
print(f"是否发生 Handoff: {result.handoff_occurred}")
```

### 9.7 下一步

1. 在 API 层添加可选的多代理模式切换
2. 为每个代理创建独立的 prompt 配置文件
3. 添加 Agent Handoff 的 E2E 测试
4. 性能基准测试：多代理 vs 单工作流
