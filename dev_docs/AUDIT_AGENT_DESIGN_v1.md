# olav-audit: Code-as-Service Audit Agent

**Version**: v1.0 (2026-02-20)  
**Status**: 实施中  
**分支**: `feat/olav-audit`

---

## 一、动机：从预定工作流到意图驱动审计

### 现有 network-inspection 的根本问题

network-inspection skill 本质上是一个**预定工作流**——它总是执行同一套检查（CPU / 内存 / 接口），
输出同一套报告格式。用户无法用自然语言表达不同的审计目标。

```
现在（Predetermined Workflow）:
用户 "检查网络" ──→ 硬编码检查 cpu/memory/interface ──→ 固定格式报告
用户 "检查VLAN一致性" ──→ 同上（无法达成目标）
用户 "检查description规范" ──→ 同上（无法达成目标）
```

### 目标：olav-audit Agent

```
目标（Intent-Driven Audit）:
用户 "检查VLAN一致性" ──→ LLM 理解意图 ──→ 生成 AUDIT_VLAN/audit.yaml ──→ 执行 ──→ 定制报告
用户 "检查CPU/内存健康" ──→ 直接执行 AUDIT_HEALTH ──→ 健康报告
用户 "检查接口description" ──→ 生成 AUDIT_INTF_DESC/audit.yaml ──→ 合规报告
```

---

## 二、架构：Code-as-Service

### 2.1 核心理念

"Code as Service" 在这里意味着：**LLM 写配置文件，配置文件驱动执行引擎**。

```
[Design Mode]                    [Execute Mode]
用户意图                          audit_name
    │                                  │
    ▼                                  ▼
create_audit_config()         load_audit_config()
    │  LLM 生成 YAML                   │ 读 YAML
    ▼                                  ▼
validate_audit_config()       audit_engine.run()
    │ Pydantic 校验                    │
    ▼                                  ▼
config/AUDIT_X/audit.yaml     report/*.md
```

### 2.2 两种使用模式

#### Design Mode（写配置）
Agent 理解用户意图，生成 YAML 配置文件，保存到 `config/AUDIT_X/`。

```
用户: "帮我设计一个检查所有交换机 description 是否符合规范的审计"
Agent: 
  1. 理解意图 → 需要检查 interface.description 不为空
  2. 调用 create_audit_config("check interface descriptions", "AUDIT_INTF_DESC")
  3. 生成并保存 audit.yaml
  4. 返回: "已创建 AUDIT_INTF_DESC，可运行 run_audit('AUDIT_INTF_DESC')"
```

#### Execute Mode（执行审计）
Agent 选择一个已有的审计配置并执行完整 Map-Reduce 流程。

```
用户: "运行接口description审计"
Agent:
  1. 调用 list_audits() → 找到 AUDIT_INTF_DESC
  2. 调用 run_audit("AUDIT_INTF_DESC", devices=None)
  3. 返回报告路径和摘要
```

---

## 三、目录结构

```
.olav/skills/olav-audit/
├── SKILL.md                           # Skill 配置（工具列表、意图）
├── prompts/
│   └── system.md                      # Audit Agent 系统提示词
│
├── config/
│   ├── AUDIT_HEALTH/                  # 内置：网络健康检查
│   │   └── audit.yaml                 # 合并版配置（含 collect + rules + output）
│   │
│   ├── AUDIT_VLAN_CONSISTENCY/        # 由 LLM 按需生成
│   │   └── audit.yaml
│   │
│   ├── AUDIT_INTF_COMPLIANCE/         # 由 LLM 按需生成
│   │   └── audit.yaml
│   │
│   ├── target_map.yaml                # 共享：字段名映射 target → (command keywords + field names)
│   │
│   └── _templates/                    # LLM 生成用模板（不可直接运行）
│       ├── health_check.yaml          # 健康检查模板
│       ├── consistency.yaml           # 一致性检查模板
│       └── compliance.yaml            # 合规检查模板
│
└── tools/
    ├── audit_engine.py                # Config-driven Rule Engine（Reduce 阶段核心）
    ├── audit_designer.py              # Design Mode 工具（create / validate / list）
    └── audit_runner.py                # Execute Mode 工具（run_audit）
```

---

## 四、Audit YAML 统一格式

每个审计包含四个节：**META**、**COLLECT**、**RULES**、**OUTPUT**。

```yaml
# config/AUDIT_HEALTH/audit.yaml

# --- 元信息 ---
name: "Network Health Check"
version: "1.0.0"
description: "CPU, memory, interface health monitoring"
type: health_check          # health_check | consistency | compliance | custom
created_at: "2026-02-20"
created_by: "builtin"       # builtin | llm_generated | user_manual

# --- Map 阶段：收集什么 ---
collect:
  intents:                  # 对应 network-inspection 的 category keywords
    - cpu_utilization
    - memory_utilization
    - interface_status
    - bgp_neighbors
    - ospf_neighbors

# --- Reduce 阶段：规则列表 ---
rules:
  - name: cpu_high
    target: cpu_percent              # 引用 target_map.yaml 中的 target 键
    condition: greater_than          # 条件枚举
    warning: 70
    critical: 90
    unit: percent
    recommendation: "CPU 过高，检查是否有异常进程"

  - name: memory_high
    target: memory_percent
    condition: greater_than
    warning: 75
    critical: 90
    unit: percent
    recommendation: "内存过高，考虑清理 buffer 或升级"

  - name: interface_down
    target: interface.status
    condition: not_equals
    expected: "up"
    severity: critical
    filter:
      exclude_pattern: "^(Loopback|Management|Mgmt).*"
    recommendation: "接口 down，检查物理连接或配置"

  - name: description_missing
    target: interface.description
    condition: is_empty
    severity: warning
    filter:
      exclude_pattern: "^(Loopback|Management|Vlan1$)"
    recommendation: "接口缺少 description，补充文档"

  - name: vlan_consistent          # 跨设备一致性（未来扩展）
    target: vlan.vlan_id
    condition: consistent_across_devices
    scope: "group:access_switches"
    severity: warning
    recommendation: "VLAN 配置不一致，检查接入层交换机"

# --- Report 阶段：如何展示 ---
output:
  title: "Network Health Report"
  filename_pattern: "audit_{audit_name}_{timestamp}.md"
  sections:
    - type: header
      fields: [date, overall_health, scope, device_summary, anomaly_count]
    - type: device_health_table
      columns: [device, status, health_score, anomaly_count, commands_inspected]
    - type: anomaly_table
      severity_filter: []            # [] = 全部显示
    - type: recommendations
      max_items: 20
    - type: footer
```

---

## 五、条件类型枚举（Rule Conditions）

| 条件 | 数据类型 | 必需参数 | 说明 |
|------|---------|---------|------|
| `greater_than` | numeric | `warning` / `critical` | 数值超限 |
| `less_than` | numeric | `warning` / `critical` | 数值低于 |
| `not_equals` | string | `expected` | 状态不符 |
| `equals` | string | `expected` | 状态匹配 |
| `is_empty` | string | — | 字段为空 |
| `not_empty` | string | — | 字段非空 |
| `in_set` | string | `allowed: [...]` | 不在允许集合 |
| `not_in_set` | string | `forbidden: [...]` | 在禁止集合 |
| `matches_pattern` | string | `pattern` | 正则匹配 |
| `not_matches_pattern` | string | `pattern` | 正则不匹配 |
| `consistent_across_devices` | any | `scope` | 跨设备一致性（Phase 2） |

---

## 六、Schema-Aware 字段发现（schema_inspector.py）

**设计动机**：target_map 原来列出具体字段名（`[cpu_5_sec, five_sec_cpu, cpu_util, ...]`），
这是**设计时的猜测**，跨平台时会静默丢失数据。schema_inspector 把字段发现推迟到运行时：

```
旧设计（静态）:   audit_engine → target_map.fields 列表 → 硬编码字段名
新设计（动态）:
  1. DB: devices.platform → {device: platform}     (知道设备是什么平台)
  2. DB: parsed_outputs.parsed_data JSON 键         (知道实际存在哪些字段)
  3. schema_inspector 评分 → 语义最接近的字段名   (动态发现，不猜)
```

**评分算法** (`_score_field(field_name, hint_words)`):

| 匹配方式 | 分数 |
|---------|------|
| 完全相等 | 1.0 |
| 以 hint 开头/结尾 | 0.8 |
| hint 是 field 的完整 token（下划线分隔） | 0.5 |
| hint 是 field 的子串 | 0.3 |
| 无匹配 | 0.0 |

**判断者分工**：

| 阶段 | 任务 | 判断者 | 原因 |
|------|------|--------|------|
| **预热（一次）** | 哪个字段代表 CPU / 接口名 / BGP 状态？ | **LLM**（主） | 语义理解，代码做不准 |
| 预热（一次） | `"Established/2d"` 等于 established？ | **LLM**（主） | 语义解读，aliases 穷举不完 |
| 预热：platform_override 精确命中 | 字段名已明确配置 | 配置（直接使用） | 无需 LLM |
| 预热：无 LLM 可用 | 回退到最高评分候选 | 评分算法（兜底） | 降级路径 |
| **Reduce（每行）** | `greater_than 80` 是否违规？ | 纯代码 | 数学逻辑，确定性 |
| **Reduce（每行）** | 字段发现 / 值归一化 | 缓存命中（已预热） | 0 LLM 调用 |

**LLM 接入原则（"使用 LLM 能力，不要写复杂逻辑"）**：

评分算法 `_score_field()` 保留，但**仅用于排序候选字段**，供 LLM prompt 参考，不再作为放行判断：

```
OLD (两级门控):                        NEW (LLM 主判，评分辅助排序):
  score ≥ 0.5 → 纯评分直接用            scored = sort by _score_field()
  score < 0.5 → LLM                     if llm:  → LLM 看排好的候选列表
                                         else:    → 最高评分兜底（无 LLM 时）
```

**架构：`prewarm_resolution_cache()` 预热（Reduce 前调用一次）**

```
audit_runner.run_audit()
  ├─ step3:   _query_parsed_outputs()              ← 获取今天的 DB 行
  ├─ step3.5: prewarm_resolution_cache()           ← LLM 预热（仅此一次）
  │     ├─ platform_override 精确命中 → 直接写缓存（0 LLM 调用）
  │     ├─ 其他所有字段 → 先评分排序 → LLM 语义判断 → 写缓存
  │     └─ per_row 值字段 → _llm_normalize_value() 扫描所有状态值
  └─ step4:   run_audit_reduce()                   ← discover_*() 全为缓存命中
       └─ audit_engine（零 LLM 引用，框架独立）
```

LLM 只在 pre-warm 阶段调用；`audit_engine.py` 在 Reduce 运行时**无任何 LLM 引用**。

**运行效果验证**：
```
cisco_ios   + show processes cpu → cpu_5_sec           (platform_override，0 LLM)
arista_eos  + show processes top → five_sec_cpu         (platform_override，0 LLM)
juniper_qfx (未知新平台)         → cpu_utilization_5sec  (LLM 语义判断 ✓)
未知平台     + proc_load_avg     → "CPU utilization"    (LLM 语义判断 ✓)
BGP state   "Established/2d"    → established           (LLM 值归一化 ✓)
```

---

## 七、target_map.yaml（意图映射）

target_map.yaml 只声明每个 target 的**意图**，不再列具体字段名。字段由 schema_inspector 在运行时从 `parsed_outputs` 发现。

```yaml
targets:
  cpu_percent:
    type: scalar
    command_keywords: [cpu, processes]   # 匹配含这些词的命令
    field_hints: [cpu, five_sec, util]   # 字段语义提示词（评分用，不是字段名列表）
    platform_overrides:                  # 可选精确映射
      cisco_ios: cpu_5_sec
      arista_eos: five_sec_cpu
    # ❌ 不再有 fields: [cpu_5_sec, five_sec_cpu, cpu_util, ...]

  memory_percent:
    type: computed_ratio                  # 重命名：原 computed
    command_keywords: [memory]
    numerator_hints: [used, alloc]       # 分子字段提示词
    denominator_hints: [total, free]     # 分母字段提示词
    # ❌ 不再有 numerator_fields / denominator_fields

  interface.status:
    type: per_row
    command_keywords: [interface, brief]
    row_key_hints: [interface, intf, port, name]  # 实体标识字段提示词
    field_hints: [link_status, status, oper_status]  # 值字段提示词
    value_aliases:                       # 归一化：平台差异消除
      connected: up
      notconnect: down
    platform_overrides:
      cisco_ios: { key_field: interface, value_field: link_status }
      arista_eos: { key_field: port, value_field: status }
    # ❌ 不再有 row_key_fields / value_fields

  bgp.state:
    type: per_row
    command_keywords: [bgp, summary]
    row_key_hints: [bgp_neigh, neighbor, peer]
    field_hints: [state, session_state, bgp_state]
    platform_overrides:
      cisco_ios: { key_field: bgp_neigh, value_field: state }
      arista_eos: { key_field: peer, value_field: session_state }
```

---

## 八、工具清单

### Design Mode 工具 (`audit_designer.py`)

| 工具 | 签名 | 说明 |
|------|------|------|
| `list_audits` | `() → list[dict]` | 扫 config/ 目录，返回可用审计列表 |
| `validate_audit_config` | `(audit_name: str) → dict` | Pydantic 格式校验，返回校验结果 |
| `create_audit_config` | `(name: str, intent: str, audit_type: str) → dict` | LLM 根据 intent 写 YAML 并保存 |

### Execute Mode 工具 (`audit_runner.py`)

| 工具 | 签名 | 说明 |
|------|------|------|
| `run_audit` | `(audit_name: str, devices, output_dir) → dict` | 完整 Map-Reduce 管道 |

### 内部函数 (`audit_engine.py`)

| 函数 | 签名 | 说明 |
|------|------|------|
| `load_audit_config` | `(audit_name: str) → AuditConfig` | 加载并校验 YAML |
| `run_audit_reduce` | `(sql_rows: list, config: AuditConfig) → dict` | 纯 Reduce 阶段 |
| `_evaluate_rule` | `(rule, device, rows, target_map) → list[Finding]` | 单规则评估 |

---

## 九、Map-Reduce 阶段变化

### Map 阶段（take_snapshot）

改动最小：从 audit.yaml `collect.intents` 读取，映射到 snapshot 的 categories。

```python
# 新：从 audit config 读 intents
config = load_audit_config("AUDIT_HEALTH")
categories = resolve_intents_to_categories(config.collect.intents)
take_snapshot(categories=categories, wait=True)
```

`intent → category` 的映射使用 snapshot.py 已有的 `CATEGORY_KEYWORDS`。

### Reduce 阶段（audit_engine）

核心重构：从硬编码字段提取 → config-driven rule engine。

```python
# 旧：hardcoded in aggregation.py
if "cpu" in command or "processes" in command:
    for field in ("cpu_5_sec", "cpu_1_min", ...):  # 硬编码

# 新：config-driven in audit_engine.py
target_def = target_map.targets["cpu_percent"]
value = _extract_from_rows(target_def, device_rows)
findings = _check_condition(rule, device, value)
```

### 是否需要格式校验层？

**是的，必须。** LLM 生成的 YAML 可能有结构错误，在执行 Map 阶段（SSH 命令耗时）之前必须校验。

校验使用 **Pydantic v2** 模型（项目已有依赖）：

```python
class AuditRule(BaseModel):
    name: str
    target: str
    condition: Literal["greater_than", "less_than", "not_equals", ...]
    warning: float | None = None
    critical: float | None = None
    ...

class AuditConfig(BaseModel):
    name: str
    type: Literal["health_check", "consistency", "compliance", "custom"]
    collect: CollectConfig
    rules: list[AuditRule]
    output: OutputConfig
```

---

## 十、与现有架构的关系

### olav-audit vs network-inspection

| 方面 | network-inspection | olav-audit |
|------|-------------------|------------|
| 角色 | 预定工作流 | 意图驱动审计 |
| 检查内容 | 硬编码 SKILL.md | YAML 配置驱动 |
| 阈值 | 固定 thresholds.yaml | 每个 audit 独立 rules |
| 报告格式 | 固定 output_format.yaml | 每个 audit 独立 output |
| 扩展方式 | 修改 Python 代码 | 写新的 audit.yaml |
| LLM 角色 | 调度工具 | 写配置 + 调度工具 |

**两者共存**：network-inspection 保持现状（健康检查用，已稳定），
olav-audit 是新能力层（支撑任意意图审计）。

### OLAV.md 注册

```yaml
subagents:
  - name: olav-audit
    description: >
      Handles intent-driven network audits. Can design new audit configs
      (thresholds, output format) from user intent, then execute them.
      Use for compliance checks, consistency verification, custom audits.
    skills: [olav-audit]
    prompt: olav-audit/prompts/system.md
```

---

## 十一、实施阶段

| 阶段 | 内容 | 风险 |
|------|------|------|
| Phase 1 ✅ | 目录结构 + SKILL.md + AUDIT_HEALTH/audit.yaml | 低 |
| Phase 2 ✅ | target_map.yaml + audit_engine.py（每设备规则） | 中 |
| Phase 3 ✅ | audit_designer.py + audit_runner.py | 低 |
| Phase 4 ✅ | OLAV.md 注册 + E2E 测试 | 低 |
| Phase 5 | cross-device rules（consistent_across_devices） | 高 |

---

## 十二、E2E 验收标准

```
✅ list_audits() 返回 AUDIT_HEALTH
✅ validate_audit_config("AUDIT_HEALTH") 无错误
✅ create_audit_config() 生成有效且可通过校验的 YAML
✅ run_audit("AUDIT_HEALTH") 连接真实设备，产出报告文件
✅ 报告文件包含真实设备名（R1, R2, SW1...），不含假设备名
✅ Agent 可用自然语言触发: "设计一个检查BGP邻居的审计，然后执行"
```

---

## 十三、LLM-First 简化（Phase 5）

**目标**：消除所有静态硬编码，让 LLM 在 prewarm 阶段一次性完成所有语义解析。

### 13.1 三处硬编码及其消除方式

| 旧硬编码 | 文件 | 消除方式 |
|----------|------|----------|
| `intent_to_category` 9条dict | `audit_runner._intents_to_categories()` | 调用 `schema_inspector.map_intents_to_categories()`，LLM 语义映射 |
| `value_aliases` per_row块 | `target_map.yaml` interface/bgp/ospf | 移除；LLM 在 `_prewarm_values()` 中一次性学习平台字符串 |
| 静态推荐模板字符串 | `audit_engine.generate_audit_report()` | 新增 `generate_ai_analysis()` + `ai_analysis` report section |

### 13.2 关键设计原则

**扩展点**：新增任意 intent 名（如 `"ntp_latency"`）自动被 LLM 映射到正确 category，无需改 Python 代码。

**值规范化**：设备返回 `"connected"` / `"notconnect"` / `"full"` 等平台差异字符串，LLM 在 prewarm 时读取 audit config 中的 `expected`/`allowed`/`forbidden` 字段，一次性建立归一化缓存，Reduce 阶段直接查找，零 LLM 延迟。

**AI 分析段**（opt-in）：在 `audit.yaml` `output.sections` 中添加 `type: ai_analysis` 后，报告末尾自动生成 LLM 专家分析——识别跨设备模式、根因、优先修复建议。

### 13.3 schema_inspector API 变化

```python
# 新增
map_intents_to_categories(intents, known_categories, llm=None) -> list[str]

# 签名更新（新增 audit_config 参数）
prewarm_resolution_cache(..., audit_config=None)
_prewarm_values(..., audit_config=None)

# 值解析优先级（已调整）
normalize_value(raw, target_def, target_name="")
  # 1. _value_normalization_cache（LLM prewarm 结果）
  # 2. value_aliases（target_def 中若有，向后兼容）
  # 3. raw 原值
```

### 13.4 新增 Phase 5 进度行

| 阶段 | 内容 | 状态 |
|------|------|------|
| Phase 5a ✅ | schema_inspector: LLM 基础设施 (_get_llm, _llm_pick_field, _llm_normalize_value) | 完成 |
| Phase 5b ✅ | schema_inspector: prewarm helpers 移除 CONFIDENCE_THRESHOLD 门控 | 完成 |
| Phase 5c ✅ | schema_inspector: map_intents_to_categories() | 完成 |
| Phase 5d ✅ | schema_inspector: _prewarm_values() 接受 audit_config | 完成 |
| Phase 5e ✅ | audit_runner: 移除硬编码 intent_to_category dict | 完成 |
| Phase 5f ✅ | audit_runner: prewarm 传入 audit_config=config | 完成 |
| Phase 5g ✅ | target_map.yaml: 移除全部 value_aliases 块 | 完成 |
| Phase 5h ✅ | audit_engine: generate_ai_analysis() + ai_analysis section | 完成 |
| Phase 5i ✅ | AUDIT_HEALTH/audit.yaml: 启用 ai_analysis output section | 完成 |
