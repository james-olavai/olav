# OLAV V2 重构计划：三模式隔离架构

> 📅 创建日期: 2025-12-06  
> 🔀 分支: `refactor/modes-isolation`  
> 📁 归档文档: [docs/archive/](./archive/)

---

## 1. 重构背景

### 1.1 当前问题

| 问题 | 影响 |
|------|------|
| **架构混乱** | `strategies/`, `workflows/`, `agents/` 职责重叠 |
| **死代码** | `multi_agent_orchestrator.py` 等从未被调用 |
| **硬编码回退** | `INTENT_PATTERNS_FALLBACK` 50+ 关键词 |
| **模式耦合** | Standard/Expert 共用代码路径，难以独立维护 |

### 1.2 重构目标

1. **模式隔离**: 三个模式独立目录，独立开发、测试、部署
2. **清理死代码**: 删除从未使用的 multi-agent 组件
3. **统一工具层**: 所有模式共享相同的 Schema-Aware 工具
4. **渐进式开发**: Phase 1 → 2 → 3 分阶段完成

---

## 2. 核心设计原则

| 原则 | 说明 |
|------|------|
| **架构决定行为** | 不依赖 LLM 遵守长 prompt，用代码结构强制行为 |
| **Schema-Aware** | 2 个通用工具 + 动态 Schema 发现，而非 120+ 专用工具 |
| **Funnel Debugging** | SuzieQ 宏观 → NETCONF/CLI 微观 |
| **Zero Hallucination** | Python 算子验证，LLM 只总结已验证事实 |
| **HITL Safety** | 所有写操作需人工审批 |

---

## 3. 三模式架构

```
                    ┌─────────────────────────────────┐
                    │      CLI / API Entry Point      │
                    │   -S (standard) / -E (expert)   │
                    │   inspect <profile>             │
                    └──────────────┬──────────────────┘
                                   │
    ┌──────────────────────────────┼──────────────────────────────┐
    │                              │                              │
    ▼                              ▼                              ▼
┌───────────────┐          ┌───────────────┐          ┌───────────────┐
│ STANDARD MODE │          │  EXPERT MODE  │          │INSPECTION MODE│
│   快速执行     │          │   故障分析     │          │   日常巡检    │
├───────────────┤          ├───────────────┤          ├───────────────┤
│ ✓ 单台查询    │          │ ✓ 多轮推理    │          │ ✓ YAML 驱动   │
│ ✓ 批量查询    │          │ ✓ 假设-验证   │          │ ✓ 阈值校验    │
│ ✓ 配置修改    │          │ ✓ L1-L4 诊断  │          │ ✓ 批量并发    │
│ ✓ HITL (写)   │          │ ✗ 只读        │          │ ✗ 只读        │
└───────┬───────┘          └───────┬───────┘          └───────┬───────┘
        │                          │                          │
        │  FastPath                │  DeepPath                │  BatchPath
        │                          │                          │
        └──────────────────────────┴──────────────────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │      SHARED TOOL LAYER      │
                    │                             │
                    │  • suzieq_query             │
                    │  • suzieq_schema_search     │
                    │  • netbox_api_call          │
                    │  • netconf_get / cli_show   │
                    │  • netconf_edit / cli_config│ ◄── HITL
                    │  • kb_search / syslog_search│
                    └─────────────────────────────┘
```

### 3.1 模式定位

| 模式 | 定位 | 能力 | 写权限 |
|------|------|------|--------|
| **Standard** | 快速执行日常任务 | 单台/批量查询, 配置修改 | ✅ (HITL) |
| **Expert** | 复杂故障分析定位 | 多轮推理, L1-L4 诊断 | ❌ 只读 |
| **Inspection** | 日常巡检 | YAML 驱动, 阈值校验 | ❌ 只读 |

---

## 4. 新目录结构

```
src/olav/
├── modes/                          # 🆕 三模式隔离
│   ├── __init__.py                 # Mode Protocol + 路由
│   ├── base.py                     # ModeProtocol 基类
│   │
│   ├── standard/                   # Phase 1
│   │   ├── __init__.py
│   │   ├── executor.py             # FastPath 执行器
│   │   ├── classifier.py           # UnifiedClassifier (重构自 unified_classifier.py)
│   │   └── prompts/                # 模式专用 prompts
│   │
│   ├── expert/                     # Phase 2
│   │   ├── __init__.py
│   │   ├── workflow.py             # Supervisor-Driven Workflow
│   │   ├── quick_analyzer.py       # SuzieQ 快速分析 (60% 置信)
│   │   ├── supervisor.py           # KB + Syslog → 层级决策
│   │   ├── inspectors.py           # L1-L4 并行检查器
│   │   ├── report.py               # 报告生成 + RAG 索引
│   │   └── prompts/                # 模式专用 prompts
│   │
│   └── inspection/                 # Phase 3
│       ├── __init__.py
│       ├── loader.py               # YAML 配置加载
│       ├── compiler.py             # NL → SQL 编译器 (可选)
│       ├── executor.py             # Map-Reduce 并行执行
│       ├── validator.py            # ThresholdValidator (零幻觉)
│       └── prompts/                # 模式专用 prompts
│
├── shared/                         # 🆕 共享组件 (重构自现有代码)
│   ├── __init__.py
│   ├── tools/                      # 统一工具层
│   │   ├── suzieq.py               # suzieq_query, suzieq_schema_search
│   │   ├── netbox.py               # netbox_api_call
│   │   ├── nornir.py               # netconf_get/edit, cli_show/config
│   │   ├── opensearch.py           # kb_search, syslog_search, memory_search
│   │   └── registry.py             # ToolRegistry
│   ├── hitl/                       # HITL 中间件
│   │   ├── middleware.py           # HITLMiddleware
│   │   └── prompts.py              # 审批 prompt
│   ├── confidence.py               # 置信度计算
│   └── protocols.py                # BackendProtocol 等
│
├── cli/                            # 保留 (入口调整)
├── server/                         # 保留 (入口调整)
└── core/                           # 保留 (LLM, PromptManager, Settings)
```

### 4.1 删除/归档清单

| 路径 | 处理 | 原因 |
|------|------|------|
| `agents/multi_agent_orchestrator.py` | 删除 | 死代码，从未被调用 |
| `agents/query_agent.py` | 删除 | 死代码 |
| `agents/diagnose_agent.py` | 删除 | 死代码 |
| `agents/config_agent.py` | 删除 | 死代码 |
| `agents/intent_classifier.py` | 删除 | 与 unified_classifier 重复 |
| `strategies/selector.py` | 已删除 | 用户手选模式，不需要 LLM 选择 |
| `strategies/fast_path.py` | 迁移 | → `modes/standard/executor.py` |
| `strategies/deep_path.py` | 迁移 | → `modes/expert/workflow.py` |
| `strategies/batch_path.py` | 迁移 | → `modes/inspection/executor.py` |
| `workflows/supervisor_driven.py` | 迁移 | → `modes/expert/workflow.py` |

---

## 5. 分阶段开发计划

### Phase 1: Standard Mode (2-3 天)

**目标**: 快速日常操作，单台/批量查询，配置修改

#### 5.1.1 核心组件

| 组件 | 来源 | 说明 |
|------|------|------|
| `UnifiedClassifier` | 重构 `unified_classifier.py` | Intent + Tool + Params 一次 LLM |
| `FastPathExecutor` | 重构 `fast_path.py` | 单次工具调用，无迭代 |
| `ToolRegistry` | 迁移 `tools/base.py` | 工具注册与发现 |
| `HITLMiddleware` | 重构 | 写操作审批 |

#### 5.1.2 能力矩阵

| 操作类型 | 支持 | 实现方式 | HITL |
|----------|------|----------|------|
| 单台状态查询 | ✓ | `suzieq_query` | ❌ |
| 批量状态查询 | ✓ | `suzieq_query` + filters | ❌ |
| 设备清单查询 | ✓ | `netbox_api_call` (GET) | ❌ |
| 实时配置读取 | ✓ | `netconf_get` | ❌ |
| CLI Show 命令 | ✓ | `cli_show` | ❌ |
| **设备配置修改** | ✓ | `netconf_edit` | ✅ **必须** |
| **CLI Config 命令** | ✓ | `cli_config` | ✅ **必须** |
| **NetBox 创建** | ✓ | `netbox_api_call` (POST) | ✅ **必须** |
| **NetBox 修改** | ✓ | `netbox_api_call` (PUT/PATCH) | ✅ **必须** |
| **NetBox 删除** | ✓ | `netbox_api_call` (DELETE) | ✅ **必须** |

#### 5.1.2.1 HITL 触发规则

```python
# shared/hitl/middleware.py

class HITLMiddleware:
    """所有写操作必须经过 HITL 审批"""
    
    # 需要 HITL 的操作
    WRITE_OPERATIONS = {
        # 设备配置
        "netconf_edit": True,      # NETCONF edit-config
        "cli_config": True,        # CLI 配置命令
        
        # NetBox CMDB
        "netbox_api_call": {
            "POST": True,          # 创建资源
            "PUT": True,           # 完整更新
            "PATCH": True,         # 部分更新
            "DELETE": True,        # 删除资源
            "GET": False,          # 查询免审
        },
    }
    
    async def check(self, tool_name: str, params: dict) -> bool:
        """检查是否需要 HITL 审批"""
        if tool_name == "netbox_api_call":
            method = params.get("method", "GET").upper()
            return self.WRITE_OPERATIONS["netbox_api_call"].get(method, False)
        return self.WRITE_OPERATIONS.get(tool_name, False)
```

#### 5.1.3 交付物

- [ ] `src/olav/modes/standard/` 目录结构
- [ ] `executor.py`: 重构自 `fast_path.py`
- [ ] `classifier.py`: 重构自 `unified_classifier.py`
- [ ] 删除 `INTENT_PATTERNS_FALLBACK` 硬编码关键词
- [ ] 单元测试: `tests/unit/modes/test_standard.py`

---

### Phase 2: Expert Mode (3-4 天)

**目标**: 复杂故障分析，多轮推理，只读

#### 5.2.1 核心组件

| 组件 | 来源 | 说明 |
|------|------|------|
| `QuickAnalyzer` | 新建 | SuzieQ aver/path/summarize (60% 置信) |
| `Supervisor` | 新建 | KB + Syslog → 层级优先级决策 |
| `LayerInspectors` | 新建 | L1-L4 并行检查器 |
| `ReportGenerator` | 新建 | 诊断报告 + RAG 索引 |

#### 5.2.2 诊断流程

```
User Query: "R1 和 R2 之间的 BGP 为什么断了"
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Round 0: Quick Analyzer                                │
│  • suzieq.bgp.get(hostname=[R1,R2])                    │
│  • suzieq.bgp.aver() → 检测异常状态                     │
│  • 置信度: 60% (缓存数据)                               │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Round 1: Supervisor Decision                           │
│  • kb_search("BGP session down") → 历史案例            │
│  • syslog_search(hostname=[R1,R2], severity=error)     │
│  • 决策: "L3 Network 优先，需验证 neighbor config"      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Round 2+: Layer Inspectors (并行)                      │
│  • netconf_get(device=R1, xpath=/bgp/neighbors)        │
│  • netconf_get(device=R2, xpath=/bgp/neighbors)        │
│  • 置信度: 95% (实时数据)                               │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  Diagnosis Conclusion                                   │
│  • 根因: R1 neighbor IP 配置错误                        │
│  • 证据: [SuzieQ state, NETCONF config diff]           │
│  • 建议: 修改 R1 BGP neighbor 配置                     │
│  • (只读模式: 不执行修改，仅提供建议)                    │
└─────────────────────────────────────────────────────────┘
```

#### 5.2.3 交付物

- [ ] `src/olav/modes/expert/` 目录结构
- [ ] `quick_analyzer.py`: SuzieQ 快速分析
- [ ] `supervisor.py`: KB + Syslog 决策
- [ ] `inspectors.py`: L1-L4 并行检查
- [ ] `report.py`: 报告生成 + RAG 索引
- [ ] 单元测试: `tests/unit/modes/test_expert.py`

---

### Phase 3: Inspection Mode (2-3 天)

**目标**: 智能巡检系统 - 用户只需描述检查意图，LLM 自动选择表和条件

#### 5.3.1 设计理念

**传统方式 (硬编码)**:
```yaml
# ❌ 用户需要知道 SuzieQ 表名、字段名、阈值
tasks:
  - table: bgp
    method: get
    threshold:
      metric: "state"
      operator: "=="
      value: "Established"
```

**智能方式 (LLM 驱动)**:
```yaml
# ✅ 用户只描述意图，LLM 自动推断
checks:
  - name: "BGP邻居down"
    description: "检查BGP邻居是否有down状态"
```

#### 5.3.2 核心组件

| 组件 | 来源 | 说明 |
|------|------|------|
| `YAMLLoader` | 新建 | 加载 `config/inspections/*.yaml` |
| `IntentCompiler` | 新建 | **LLM 驱动**: 意图 → SuzieQ 查询计划 |
| `SchemaSearcher` | 复用 | 检索 suzieq-schema 索引辅助 LLM |
| `MapReduceExecutor` | 重构 `batch_path.py` | 并行执行 + 聚合 |
| `ThresholdValidator` | 新建 | Python 算子，零幻觉 |

#### 5.3.3 智能巡检配置示例

```yaml
# config/inspections/daily-core.yaml
name: "Daily Core Router Check"
description: "核心路由器每日健康检查"

targets:
  netbox_filter: "role=core&status=active"

# 智能检查项 - 用户只需描述意图
checks:
  - name: "BGP邻居异常"
    description: "检查是否有BGP邻居处于非Established状态"
    severity: critical
    
  - name: "CPU使用率过高"
    description: "检查CPU使用率是否超过80%"
    severity: warning
    
  - name: "接口错误"
    description: "检查接口是否有输入/输出错误"
    severity: warning

  - name: "OSPF邻居丢失"
    description: "检查OSPF邻居数量是否少于预期"
    severity: critical
```

#### 5.3.4 IntentCompiler 工作流

```
用户配置:
  name: "BGP邻居异常"
  description: "检查是否有BGP邻居处于非Established状态"
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  1. Schema Search (RAG)                                 │
│  • 检索 suzieq-schema 索引                              │
│  • 返回相关表: bgp, ospf, ...                           │
│  • 返回字段: state, peerHostname, asn, ...              │
└─────────────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│  2. LLM Intent Compilation                              │
│  • Prompt: "根据意图和可用 schema，生成查询计划"         │
│  • 输入: 意图 + Schema 上下文                           │
│  • 输出: 结构化查询计划 (JSON)                          │
└─────────────────────────────────────────────────────────┘
       │
       ▼
生成的查询计划:
{
  "table": "bgp",
  "method": "get",
  "filters": {},
  "validation": {
    "field": "state",
    "operator": "!=",
    "expected": "Established",
    "on_match": "report_violation"
  }
}
```

#### 5.3.5 Prompt 设计

```yaml
# config/prompts/inspection/intent_compiler.yaml
_type: prompt
input_variables:
  - check_name
  - check_description
  - schema_context
  - severity
template: |
  你是网络运维专家。根据用户的检查意图，生成 SuzieQ 查询计划。

  ## 检查项
  名称: {check_name}
  描述: {check_description}
  严重级别: {severity}

  ## 可用 Schema
  {schema_context}

  ## 输出格式 (JSON)
  {{
    "table": "选择最相关的表",
    "method": "get|summarize|unique",
    "filters": {{}},
    "validation": {{
      "field": "要检查的字段",
      "operator": "==|!=|>|<|>=|<=|contains",
      "expected": "期望值或阈值",
      "on_match": "report_violation|report_ok"
    }}
  }}

  只输出 JSON，不要其他解释。
```

#### 5.3.6 执行流程

```
olav inspect run daily-core
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  1. YAML Loader                                         │
│  • 解析 config/inspections/daily-core.yaml             │
│  • 提取 checks[] 列表                                   │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  2. Intent Compilation (LLM)                            │
│  • 对每个 check 调用 IntentCompiler                     │
│  • 生成结构化查询计划 (可缓存)                          │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  3. Target Resolution                                   │
│  • netbox_api_call(role=core&status=active)            │
│  • 返回: [R1, R2, R3, R4, R5]                          │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  4. Map-Reduce Execution (并行)                         │
│  • 根据查询计划调用 suzieq_query                        │
│  • 所有设备并行执行                                      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  5. Threshold Validation (Zero Hallucination)           │
│  • Python operator.gt/lt/eq (非 LLM)                   │
│  • 收集 violations                                      │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  6. Report Generation                                   │
│  • LLM 仅总结已验证事实                                 │
│  • 输出: Markdown/JSON 报告                            │
└─────────────────────────────────────────────────────────┘
```

#### 5.3.7 查询计划缓存

为避免重复 LLM 调用，IntentCompiler 支持缓存：

```python
class IntentCompiler:
    def __init__(self, cache_path: Path = Path("data/cache/inspection_plans")):
        self.cache_path = cache_path
    
    def compile(self, check: dict) -> dict:
        cache_key = hashlib.md5(json.dumps(check, sort_keys=True)).hexdigest()
        cache_file = self.cache_path / f"{cache_key}.json"
        
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        
        # LLM 编译
        plan = self._llm_compile(check)
        cache_file.write_text(json.dumps(plan))
        return plan
```

#### 5.3.8 向后兼容

仍支持传统的硬编码配置（适合固定巡检）：

```yaml
# 混合模式 - 同时支持智能和硬编码
checks:
  # 智能检查 (LLM 推断)
  - name: "BGP状态异常"
    description: "检查BGP邻居状态"
    severity: critical
  
  # 硬编码检查 (精确控制)
  - name: "CPU使用率"
    table: device           # 指定表 = 跳过 LLM
    method: get
    threshold:
      metric: "cpuUsage"
      operator: "<"
      value: 80
    severity: warning
```

#### 5.3.9 交付物

- [ ] `src/olav/modes/inspection/` 目录结构
- [ ] `loader.py`: YAML 配置加载
- [ ] `compiler.py`: IntentCompiler (LLM 驱动意图编译)
- [ ] `executor.py`: Map-Reduce 并行执行
- [ ] `validator.py`: ThresholdValidator
- [ ] `config/prompts/inspection/intent_compiler.yaml`
- [ ] `config/inspections/` 智能配置示例
- [ ] 单元测试: `tests/unit/modes/test_inspection.py`

---

## 6. 共享组件

以下组件在三个模式间 100% 共享：

| 组件 | 新路径 | 来源 |
|------|--------|------|
| `ToolRegistry` | `shared/tools/registry.py` | `tools/base.py` |
| `suzieq_*` | `shared/tools/suzieq.py` | `tools/suzieq_*.py` |
| `netbox_*` | `shared/tools/netbox.py` | `tools/netbox_*.py` |
| `nornir_*` | `shared/tools/nornir.py` | `tools/nornir_*.py` |
| `opensearch_*` | `shared/tools/opensearch.py` | `tools/opensearch_*.py` |
| `HITLMiddleware` | `shared/hitl/middleware.py` | 新建 |
| `Confidence` | `shared/confidence.py` | 新建 |
| `BackendProtocol` | `shared/protocols.py` | `execution/backends/protocol.py` |

---

## 7. 配置重构

### 7.1 config/ 目录分析

| 路径 | 当前状态 | 重构建议 |
|------|----------|----------|
| `config/prompts/` | 按 agents/strategies/workflows 组织 | 按 modes/ 重组 |
| `config/inspections/` | ✅ 已有 4 个巡检配置 | 完善 YAML schema |
| `config/settings.py` | ✅ 已有 InspectionConfig | 添加 StandardConfig/ExpertConfig |
| `config/rules/` | 存在 | 保留，inspection 使用 |

**现有 config/inspections/ 内容**:
- `bgp_peer_audit.yaml` - BGP 邻居审计
- `daily_core_check.yaml` - 日常核心检查
- `intent_based_audit.yaml` - 意图驱动审计
- `interface_health.yaml` - 接口健康检查

**现有 config/settings.py 结构** (329 行):
- ✅ `Paths` - 路径配置
- ✅ `LLMConfig` - LLM 配置
- ✅ `EmbeddingConfig` - Embedding 配置
- ✅ `InfrastructureConfig` - 基础设施配置
- ✅ `AgentConfig` - Agent 通用配置
- ✅ `InspectionConfig` - 巡检配置 (已存在!)
- ✅ `ToolConfig` - 工具配置
- ⚠️ 缺少 `StandardModeConfig` 和 `ExpertModeConfig`

### 7.2 Prompts 重组

```
config/prompts/
├── shared/                         # 共享 prompts
│   ├── tool_descriptions/          # 工具描述
│   └── hitl/                       # HITL 审批
│
├── standard/                       # Standard Mode
│   ├── classifier.yaml             # UnifiedClassifier prompt
│   └── answer_formatting.yaml      # 答案格式化
│
├── expert/                         # Expert Mode
│   ├── quick_analyzer.yaml         # 快速分析
│   ├── supervisor.yaml             # 决策 prompt
│   ├── inspectors/                 # L1-L4 检查 prompts
│   └── report.yaml                 # 报告生成
│
└── inspection/                     # Inspection Mode
    └── summary.yaml                # 巡检总结
```

### 7.3 Settings 拆分

**现有结构** (`config/settings.py`):
```python
# 已存在的配置类
class InspectionConfig:       # ✅ 巡检配置 (已完善)
    ENABLED = False
    SCHEDULE_TIME = "09:00"
    DEFAULT_PROFILE = "daily_core_check"
    PARALLEL_DEVICES = 10
    ...
```

**需要添加**:
```python
# config/settings.py 新增

class StandardModeConfig:
    """Standard mode specific settings."""
    CONFIDENCE_THRESHOLD: float = 0.7      # FastPath 置信度阈值
    ENABLE_MEMORY_RAG: bool = True         # 启用 Episodic Memory
    MAX_RETRIES: int = 2                   # 工具重试次数
    CACHE_TTL_SECONDS: int = 300           # 缓存 TTL

class ExpertModeConfig:
    """Expert mode specific settings."""
    MAX_ITERATIONS: int = 5                # 最大迭代次数
    KB_SEARCH_TOP_K: int = 5               # KB 搜索返回数量
    SYSLOG_LOOKBACK_HOURS: int = 24        # Syslog 回溯时间
    PARALLEL_INSPECTORS: int = 4           # 并行检查器数量
    QUICK_ANALYZER_CONFIDENCE: float = 0.6 # 快速分析置信度
    REALTIME_CONFIDENCE: float = 0.95      # 实时数据置信度
```

**环境变量** (`src/olav/core/settings.py`):
```python
# 已存在，结构良好 (251 行)
class EnvSettings(BaseSettings):
    # ... 现有配置 ...
    
    # 需要添加:
    default_mode: str = "standard"         # 默认模式
    standard_confidence: float = 0.7       # Standard 置信度
    expert_max_iterations: int = 5         # Expert 最大迭代
    expert_kb_top_k: int = 5               # KB 搜索数量
```

---

## 8. 测试重构

### 8.1 当前测试分析

**当前测试规模**:
- 单元测试: 37 个文件
- E2E 测试: 14 个文件
- 集成测试: 存在
- 手动测试: 存在
- 性能测试: 存在

**需要归档/删除的测试**:
| 文件 | 原因 |
|------|------|
| `test_selector.py` | 测试已删除的 `selector.py` |
| `test_multi_agent.py` | 测试从未使用的多代理架构 |

**需要按模式重组的测试**:
| 现有文件 | 目标位置 |
|----------|----------|
| `test_fast_path_fallback.py` | `modes/test_standard.py` |
| `test_strategies.py` | `modes/test_standard.py` |
| `test_strategy_executor.py` | `modes/test_standard.py` |
| `test_supervisor_driven.py` | `modes/test_expert.py` |
| `test_deep_dive_workflow.py` | `modes/test_expert.py` |
| `test_inspection_workflow.py` | `modes/test_inspection.py` |
| `test_batch_strategy.py` | `modes/test_inspection.py` |

### 8.2 新测试结构

```
tests/
├── conftest.py                     # 共享 fixtures
│
├── unit/
│   ├── modes/                      # 🆕 模式测试
│   │   ├── test_standard.py        # Standard mode 单元测试
│   │   ├── test_expert.py          # Expert mode 单元测试
│   │   └── test_inspection.py      # Inspection mode 单元测试
│   ├── shared/                     # 🆕 共享组件测试
│   │   ├── test_tools.py           # 共享工具测试
│   │   ├── test_hitl.py            # HITL 中间件测试
│   │   └── test_confidence.py      # 置信度计算测试
│   ├── archive/                    # 🆕 归档旧测试
│   │   ├── test_selector.py        # 已删除的 selector
│   │   └── test_multi_agent.py     # 未使用的多代理
│   └── ...                         # 保留其他测试
│
├── e2e/
│   ├── test_standard_mode.py       # Standard mode E2E (重命名)
│   ├── test_expert_mode.py         # Expert mode E2E (新增)
│   └── test_inspection_mode.py     # Inspection mode E2E (新增)
│
└── integration/
    ├── test_shared_tools.py        # 共享工具集成测试
    └── test_cross_mode.py          # 跨模式集成测试
```

**测试迁移矩阵**:

| 现有测试 | 归属模式 | 操作 |
|----------|----------|------|
| `test_fast_path_fallback.py` | Standard | 移动到 `modes/test_standard.py` |
| `test_strategies.py` | Standard | 移动到 `modes/test_standard.py` |
| `test_supervisor_driven.py` | Expert | 移动到 `modes/test_expert.py` |
| `test_deep_dive_workflow.py` | Expert | 移动到 `modes/test_expert.py` |
| `test_inspection_workflow.py` | Inspection | 移动到 `modes/test_inspection.py` |
| `test_batch_strategy.py` | Inspection | 移动到 `modes/test_inspection.py` |
| `test_selector.py` | ❌ 死测试 | 归档到 `archive/` |
| `test_multi_agent.py` | ❌ 死测试 | 归档到 `archive/` |
| `test_suzieq_*.py` | Shared | 移动到 `shared/test_tools.py` |
| `test_cli_tool.py` | Shared | 移动到 `shared/test_tools.py` |
| `test_auth.py` | Core | 保持不变 |
| `test_cache.py` | Core | 保持不变 |

### 8.3 测试覆盖目标

| 模式 | 单元测试 | E2E 测试 | 覆盖率目标 |
|------|----------|----------|------------|
| Standard | 工具调用, 分类器, HITL | 完整查询流程 | 80% |
| Expert | 各组件独立 | 诊断流程 | 70% |
| Inspection | YAML 加载, 阈值校验 | 完整巡检流程 | 80% |
| Shared | 所有共享组件 | - | 90% |

---

## 9. 环境变量

### 9.1 当前 .env 分析

**现有结构** (`src/olav/core/settings.py` - 251 行):
- ✅ LLM 配置 (provider, api_key, base_url, model_name)
- ✅ Embedding 配置
- ✅ Vision 配置
- ✅ PostgreSQL/OpenSearch/Redis 配置
- ✅ NetBox 配置
- ✅ Device 凭证
- ✅ API Server 配置
- ✅ CORS 配置
- ✅ Feature Flags (`expert_mode`, `use_dynamic_router`)
- ✅ LangSmith 配置
- ✅ Collector 配置
- ✅ Agentic RAG 配置

**结论**: 环境变量结构良好，只需添加模式相关变量。

### 9.2 新增环境变量

```bash
# .env 新增

# Mode Settings (可选，有默认值)
OLAV_DEFAULT_MODE=standard          # 默认模式: standard/expert
OLAV_STANDARD_CONFIDENCE=0.7        # Standard 置信度阈值
OLAV_EXPERT_MAX_ITERATIONS=5        # Expert 最大迭代次数
OLAV_EXPERT_KB_TOP_K=5              # KB 搜索返回数量
OLAV_EXPERT_SYSLOG_LOOKBACK=24      # Syslog 回溯时间 (小时)

# Inspection Mode (已在 config/settings.py 中配置)
# OLAV_INSPECTION_PARALLEL=10       # 并发数 (使用 InspectionConfig)
# OLAV_INSPECTION_REPORT_FORMAT=markdown
```

---

## 10. E2E 测试计划

### 10.1 现有测试分析

当前 `tests/e2e/` 已有以下测试文件：

| 文件 | 覆盖范围 | 状态 |
|------|----------|------|
| `test_cli_capabilities.py` | CLI 调用 + 5 类测试 | ✅ 可复用 |
| `test_agent_capabilities.py` | API 调用 + 7 类测试 | ✅ 可复用 |
| `test_standard_mode_tools.py` | Standard Mode 工具链 | ⚠️ 需完善 |
| `test_expert_mode_fault_injection.py` | Expert Mode 故障注入 | ⚠️ 需完善 |
| `test_cache.py` | 测试缓存 + 性能日志 | ✅ 已实现 |

### 10.2 测试分层架构

```
tests/
├── unit/                           # 单元测试 (无 LLM)
│   ├── modes/
│   │   ├── test_standard_classifier.py
│   │   ├── test_expert_supervisor.py
│   │   └── test_inspection_compiler.py
│   └── shared/
│       ├── test_hitl_middleware.py
│       └── test_confidence.py
│
├── integration/                    # 集成测试 (Mock LLM)
│   ├── test_standard_workflow.py
│   ├── test_expert_workflow.py
│   └── test_inspection_workflow.py
│
└── e2e/                           # 端到端测试 (Real LLM)
    ├── test_standard_mode.py      # Phase 1 里程碑
    ├── test_expert_mode.py        # Phase 2 里程碑
    ├── test_inspection_mode.py    # Phase 3 里程碑
    ├── test_debug_mode.py         # Debug 输出验证
    └── fixtures/
        ├── sample_queries.yaml    # 标准测试查询
        └── expected_outputs.yaml  # 期望输出
```

### 10.3 Phase 1 里程碑测试 (Standard Mode)

```python
# tests/e2e/test_standard_mode.py
class TestStandardModeE2E:
    """Standard Mode 端到端测试 - Phase 1 里程碑"""
    
    # === 查询类 (Read-Only) ===
    
    @pytest.mark.parametrize("query,expected_tool,expected_keywords", [
        # SuzieQ 查询
        ("查询 R1 的 BGP 状态", "suzieq_query", ["BGP", "state"]),
        ("show interfaces on R1", "suzieq_query", ["interface"]),
        ("summarize all devices", "suzieq_query", ["device"]),
        ("查询所有设备的 OSPF 邻居", "suzieq_query", ["OSPF", "neighbor"]),
        
        # NetBox 查询
        ("列出 NetBox 中所有设备", "netbox_api_call", ["device"]),
        ("查询 R1 在 NetBox 中的信息", "netbox_api_call", ["R1"]),
        
        # Schema 发现
        ("有哪些 SuzieQ 表可用？", "suzieq_schema_search", ["table"]),
        ("BGP 表有哪些字段？", "suzieq_schema_search", ["field"]),
    ])
    def test_standard_query(self, query, expected_tool, expected_keywords):
        """验证 Standard Mode 查询正确分类和执行"""
        result = run_with_debug(query, mode="standard")
        
        # 验证工具选择
        assert result.tool_called == expected_tool
        
        # 验证输出包含关键词
        for kw in expected_keywords:
            assert kw.lower() in result.output.lower()
        
        # 验证性能
        assert result.duration_ms < 30000  # 30s 超时
    
    # === 写入类 (HITL) ===
    
    @pytest.mark.hitl
    @pytest.mark.parametrize("query,expected_tool", [
        ("配置 R1 接口 Loopback100 IP 为 10.0.0.1", "netconf_edit"),
        ("在 NetBox 中创建新设备 R99", "netbox_api_call"),
        ("更新 R1 在 NetBox 中的描述", "netbox_api_call"),
    ])
    def test_standard_write_requires_hitl(self, query, expected_tool):
        """验证写操作触发 HITL"""
        result = run_with_debug(query, mode="standard", yolo=False)
        
        # 验证 HITL 触发
        assert result.hitl_triggered
        assert result.approval_required
        
        # 验证工具选择正确
        assert result.tool_called == expected_tool
    
    # === 边界条件 ===
    
    def test_standard_unknown_device(self):
        """未知设备应优雅处理"""
        result = run_with_debug("查询 NONEXISTENT 的状态", mode="standard")
        assert result.success
        assert "no data" in result.output.lower() or "not found" in result.output.lower()
    
    def test_standard_chinese_english_mixed(self):
        """中英文混合查询"""
        result = run_with_debug("check R1 的 BGP neighbors", mode="standard")
        assert result.success
        assert "BGP" in result.output
```

### 10.4 Phase 2 里程碑测试 (Expert Mode)

```python
# tests/e2e/test_expert_mode.py
class TestExpertModeE2E:
    """Expert Mode 端到端测试 - Phase 2 里程碑"""
    
    # === 故障诊断 ===
    
    @pytest.mark.slow
    @pytest.mark.parametrize("symptom,expected_checks", [
        # BGP 故障
        (
            "R1 无法与 R2 建立 BGP",
            ["bgp", "interface", "route"]
        ),
        # OSPF 故障
        (
            "R1 的 OSPF 邻居丢失",
            ["ospf", "interface"]
        ),
        # 连通性故障
        (
            "R1 无法 ping R2 的 Loopback",
            ["route", "interface", "ping"]
        ),
    ])
    def test_expert_multi_step_diagnosis(self, symptom, expected_checks):
        """验证 Expert Mode 多步诊断"""
        result = run_with_debug(symptom, mode="expert")
        
        # 验证多步执行
        assert len(result.steps) >= 2, "Expert Mode 应执行多步"
        
        # 验证检查了相关表
        tables_checked = [s["table"] for s in result.steps if "table" in s]
        for check in expected_checks:
            assert any(check in t.lower() for t in tables_checked)
        
        # 验证有根因分析
        assert "root cause" in result.output.lower() or "根因" in result.output
    
    # === KB 引用 ===
    
    @pytest.mark.slow
    def test_expert_uses_kb(self):
        """验证 Expert Mode 引用 Knowledge Base"""
        result = run_with_debug(
            "R1 BGP 状态异常，之前解决过类似问题吗？",
            mode="expert"
        )
        
        # 验证 KB 搜索
        assert result.kb_searched
        if result.kb_hits > 0:
            assert "历史案例" in result.output or "previous" in result.output.lower()
    
    # === 迭代限制 ===
    
    @pytest.mark.slow
    def test_expert_respects_max_iterations(self):
        """验证 Expert Mode 遵守最大迭代限制"""
        result = run_with_debug(
            "分析整个网络的健康状态",  # 复杂查询
            mode="expert"
        )
        
        # 验证迭代次数 <= 配置值
        assert result.iterations <= 5  # OLAV_EXPERT_MAX_ITERATIONS
```

### 10.5 Phase 3 里程碑测试 (Inspection Mode)

```python
# tests/e2e/test_inspection_mode.py
class TestInspectionModeE2E:
    """Inspection Mode 端到端测试 - Phase 3 里程碑"""
    
    # === 智能巡检 ===
    
    @pytest.mark.slow
    def test_inspection_smart_compile(self):
        """验证智能巡检意图编译"""
        # 使用智能配置
        config = {
            "name": "Test Inspection",
            "checks": [
                {
                    "name": "BGP邻居异常",
                    "description": "检查是否有BGP邻居处于非Established状态",
                    "severity": "critical"
                }
            ],
            "targets": {"netbox_filter": "role=core"}
        }
        
        result = run_inspection_with_debug(config)
        
        # 验证 LLM 生成查询计划
        assert result.plans_generated > 0
        assert "bgp" in str(result.generated_plans).lower()
        
        # 验证执行结果
        assert result.success
        assert result.report is not None
    
    # === 并行执行 ===
    
    @pytest.mark.slow
    def test_inspection_parallel_execution(self):
        """验证并行执行性能"""
        result = run_inspection_with_debug("daily-core.yaml")
        
        # 验证并行执行 (多设备同时查询)
        assert result.parallel_tasks > 1
        
        # 验证汇总报告
        assert "summary" in result.report.lower() or "总结" in result.report
    
    # === 阈值验证 ===
    
    def test_inspection_threshold_validation(self):
        """验证阈值检查 (Zero Hallucination)"""
        # 使用硬编码配置 (绕过 LLM)
        config = {
            "name": "Threshold Test",
            "checks": [
                {
                    "name": "CPU Check",
                    "table": "device",
                    "method": "get",
                    "threshold": {
                        "metric": "cpuUsage",
                        "operator": "<",
                        "value": 80
                    }
                }
            ]
        }
        
        result = run_inspection_with_debug(config)
        
        # 验证阈值由 Python 计算 (非 LLM)
        assert result.threshold_checks > 0
        assert not result.llm_threshold_eval  # LLM 不参与阈值判断
```

### 10.6 Debug 模式设计

#### 10.6.1 Debug 输出内容

```python
@dataclass
class DebugOutput:
    """Debug 模式输出结构"""
    
    # 基本信息
    query: str
    mode: str  # standard/expert/inspection
    timestamp: str
    duration_ms: float
    
    # LLM 调用详情
    llm_calls: list[LLMCallDetail]
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    
    # 工具调用链
    tool_calls: list[ToolCallDetail]
    
    # 工作流状态
    graph_states: list[GraphStateSnapshot]
    transitions: list[str]  # node1 -> node2
    
    # 流式传输
    stream_chunks: list[StreamChunk]
    stream_latency_ms: float  # 首 chunk 延迟
    
    # 执行时间分解
    time_breakdown: dict[str, float]  # {classify: 100ms, tool: 200ms, ...}


@dataclass
class LLMCallDetail:
    """LLM 调用详情"""
    call_id: str
    model: str
    prompt: str  # 完整 prompt
    response: str  # 完整响应
    prompt_tokens: int
    completion_tokens: int
    duration_ms: float
    temperature: float
    
    # Thinking 模式分析
    thinking_content: str | None  # <think> 内容 (Ollama)
    thinking_tokens: int


@dataclass
class ToolCallDetail:
    """工具调用详情"""
    tool_name: str
    input_args: dict
    output: str
    duration_ms: float
    success: bool
    error: str | None


@dataclass
class GraphStateSnapshot:
    """LangGraph 状态快照"""
    node: str
    state: dict
    timestamp: str
```

#### 10.6.2 Debug CLI 使用

```bash
# 启用 Debug 模式
uv run olav.py query "查询 R1 BGP 状态" --debug

# Debug 输出到文件
uv run olav.py query "查询 R1 BGP 状态" --debug --debug-output debug_output.json

# Debug 仅显示 LLM 调用
uv run olav.py query "查询 R1 BGP 状态" --debug --debug-llm

# Debug 仅显示工具链
uv run olav.py query "查询 R1 BGP 状态" --debug --debug-tools

# Debug 显示 Graph 状态
uv run olav.py query "查询 R1 BGP 状态" --debug --debug-graph
```

#### 10.6.3 Debug 实现

```python
# src/olav/core/debug.py
class DebugContext:
    """Debug 上下文管理器"""
    
    def __init__(self, enabled: bool = False):
        self.enabled = enabled
        self.output = DebugOutput(...)
        self._llm_interceptor: LLMInterceptor | None = None
        self._tool_interceptor: ToolInterceptor | None = None
    
    def __enter__(self):
        if self.enabled:
            # 安装 LLM 拦截器
            self._llm_interceptor = LLMInterceptor(self.output)
            self._llm_interceptor.install()
            
            # 安装工具拦截器
            self._tool_interceptor = ToolInterceptor(self.output)
            self._tool_interceptor.install()
        
        return self
    
    def __exit__(self, *args):
        if self.enabled:
            self._llm_interceptor.uninstall()
            self._tool_interceptor.uninstall()


class LLMInterceptor:
    """LLM 调用拦截器 - 记录完整 prompt/response"""
    
    def install(self):
        # Monkey-patch LangChain ChatModel
        original_invoke = ChatOpenAI.invoke
        
        def intercepted_invoke(self, messages, **kwargs):
            start = time.perf_counter()
            response = original_invoke(messages, **kwargs)
            duration = (time.perf_counter() - start) * 1000
            
            # 记录调用详情
            self.debug_output.llm_calls.append(LLMCallDetail(
                prompt=str(messages),
                response=str(response),
                duration_ms=duration,
                ...
            ))
            
            return response
        
        ChatOpenAI.invoke = intercepted_invoke
```

#### 10.6.4 Debug 输出示例

```json
{
  "query": "查询 R1 BGP 状态",
  "mode": "standard",
  "timestamp": "2025-12-06T10:30:00",
  "duration_ms": 2345.67,
  
  "llm_calls": [
    {
      "call_id": "llm-001",
      "model": "qwen2.5:32b",
      "prompt": "你是网络运维专家...\n\n用户: 查询 R1 BGP 状态",
      "response": "```json\n{\"tool\": \"suzieq_query\", \"params\": {...}}\n```",
      "prompt_tokens": 256,
      "completion_tokens": 45,
      "duration_ms": 1200.5,
      "thinking_content": "用户想查询BGP状态，应该使用suzieq_query工具...",
      "thinking_tokens": 30
    }
  ],
  
  "tool_calls": [
    {
      "tool_name": "suzieq_query",
      "input_args": {"table": "bgp", "hostname": "R1", "method": "get"},
      "output": "[{\"hostname\": \"R1\", \"peer\": \"192.168.1.2\", \"state\": \"Established\"}]",
      "duration_ms": 450.2,
      "success": true
    }
  ],
  
  "graph_states": [
    {"node": "classify", "state": {"intent": "query"}, "timestamp": "..."},
    {"node": "execute_tool", "state": {"tool": "suzieq_query"}, "timestamp": "..."},
    {"node": "format_response", "state": {"output": "..."}, "timestamp": "..."}
  ],
  
  "time_breakdown": {
    "classify": 1200.5,
    "tool_execution": 450.2,
    "response_format": 694.97
  },
  
  "stream_latency_ms": 150.3,
  "total_prompt_tokens": 256,
  "total_completion_tokens": 45
}
```

### 10.7 测试执行策略

#### 10.7.1 每阶段里程碑验证

```bash
# Phase 1 完成后
uv run pytest tests/e2e/test_standard_mode.py -v --html=reports/phase1.html

# Phase 2 完成后
uv run pytest tests/e2e/test_expert_mode.py -v --html=reports/phase2.html

# Phase 3 完成后
uv run pytest tests/e2e/test_inspection_mode.py -v --html=reports/phase3.html

# 全量回归
uv run pytest tests/e2e/ -v --html=reports/full_regression.html
```

#### 10.7.2 Debug 模式用于优化

```bash
# 1. 运行测试收集 Debug 输出
OLAV_DEBUG=true uv run pytest tests/e2e/test_standard_mode.py::test_standard_query -v

# 2. 分析 LLM Token 消耗
python scripts/analyze_debug_output.py tests/e2e/logs/debug_*.json --metric tokens

# 3. 分析延迟瓶颈
python scripts/analyze_debug_output.py tests/e2e/logs/debug_*.json --metric latency

# 4. 分析 Thinking 内容 (Ollama)
python scripts/analyze_debug_output.py tests/e2e/logs/debug_*.json --metric thinking
```

#### 10.7.3 Prompt 优化循环

```
┌─────────────────────────────────────────────────────────┐
│  1. 运行测试 + Debug                                    │
│  OLAV_DEBUG=true uv run pytest test_xxx.py             │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  2. 分析 Debug 输出                                     │
│  • Token 消耗过高？→ 精简 Prompt                        │
│  • Thinking 冗余？→ 添加 /no_think                      │
│  • 工具选择错误？→ 调整 Tool Description                │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  3. 修改 Prompt (config/prompts/)                       │
│  • 精简 system prompt                                   │
│  • 优化 tool description                                │
│  • 添加 few-shot examples                               │
└─────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────┐
│  4. 重新运行测试验证                                    │
│  • Token 减少？✓                                        │
│  • 准确率保持？✓                                        │
│  • 延迟降低？✓                                          │
└─────────────────────────────────────────────────────────┘
    │
    └──────────────────────────────────────────────────────┐
                                                           │
    ┌──────────────────────────────────────────────────────┘
    │
    ▼
  重复直到满意
```

### 10.8 测试交付物

| 阶段 | 测试文件 | 用例数 | 验证内容 |
|------|----------|--------|----------|
| Phase 1 | `test_standard_mode.py` | 15+ | 查询、写入HITL、边界条件 |
| Phase 2 | `test_expert_mode.py` | 10+ | 多步诊断、KB引用、迭代限制 |
| Phase 3 | `test_inspection_mode.py` | 10+ | 智能编译、并行执行、阈值验证 |
| Debug | `test_debug_mode.py` | 5+ | Debug 输出格式、拦截器功能 |

---

## 11. 时间估算

| 阶段 | 工作量 | 预计时间 |
|------|--------|----------|
| Phase 1: Standard Mode | 中 | 2-3 天 |
| Phase 2: Expert Mode | 大 | 3-4 天 |
| Phase 3: Inspection Mode | 中 | 2-3 天 |
| 共享组件重构 | 小 | 1 天 |
| 配置/Prompt 重组 | 小 | 1 天 |
| 测试编写 | 中 | 2-3 天 |
| Debug 模式实现 | 中 | 1-2 天 |
| 集成与调试 | 中 | 2 天 |

**总计**: 约 15-19 天 (3-4 周)

---

## 12. 回滚计划

每个 Phase 独立可回滚：

1. **Phase 1 回滚**: 恢复 `strategies/fast_path.py` 入口
2. **Phase 2 回滚**: 恢复 `workflows/supervisor_driven.py` 入口
3. **Phase 3 回滚**: 恢复 `strategies/batch_path.py` 入口

所有变更都应该是渐进式的，确保每个阶段都可以独立回滚。

---

## 13. 下一步行动

1. ✅ 创建分支: `refactor/modes-isolation`
2. ✅ 归档旧文档
3. ⬜ 删除死代码 (multi-agent 组件)
4. ⬜ 创建 `src/olav/modes/` 目录结构
5. ⬜ Phase 1: Standard Mode 重构
6. ⬜ Phase 2: Expert Mode 重构
7. ⬜ Phase 3: Inspection Mode 重构
8. ⬜ 实现 Debug 模式
9. ⬜ 测试编写与集成

---

**文档版本**: 2.1  
**维护者**: AI Assistant  
**最后更新**: 2025-12-06
