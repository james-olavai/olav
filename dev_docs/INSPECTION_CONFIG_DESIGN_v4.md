# Inspection Config & Report Template Design (v4.0)

**Date**: 2026-02-19  
**Status**: Design — pending implementation  
**Supersedes**: `thresholds.yaml` (split into `inspection_config.yaml`)

---

## 背景与问题

当前架构存在三个缺口：

| 缺口 | 现状 | 应该是 |
|---|---|---|
| 命令选择 | `CATEGORY_KEYWORDS` 硬编码关键字匹配 NTC | LLM 首次读 inspection_items 描述，写入配置 |
| 阈值来源 | `thresholds.yaml` 存在但无生成入口（run_real_inspection.py 已删） | 首次运行自动生成，用户拥有修改权 |
| 报告格式 | 完全由 LLM 即兴决定 | 用户在 YAML 里声明结构，LLM 按模板填内容 |

---

## 设计方案

### 一、职责分层

```
┌─────────────────────────────────────────────────────────┐
│  SKILL.md inspection_items         用户定义"检查什么"      │
│  （name + description）            用户唯一需要关心的地方   │
└───────────────────┬─────────────────────────────────────┘
                    │ 第一次运行 / SKILL.md 变更时
                    ▼
┌─────────────────────────────────────────────────────────┐
│  inspection_config.yaml            自动生成，用户可覆盖    │
│  ├── skill_fingerprint             SKILL.md 变更检测      │
│  ├── platform_commands             平台→命令映射           │
│  ├── thresholds                    异常检测阈值            │
│  └── report_template               报告格式模板            │
└───────────────────┬─────────────────────────────────────┘
                    │ 每次运行
                    ▼
┌─────────────────────────────────────────────────────────┐
│  take_snapshot → execute_sql → aggregate → LLM report   │
│  完全确定性（命令固定，阈值固定，格式固定）                   │
└─────────────────────────────────────────────────────────┘
```

---

### 二、`inspection_config.yaml` 完整结构

路径：`.olav/skills/network-inspection/config/inspection_config.yaml`

```yaml
# Network Inspection Configuration
# =================================
# Auto-generated on first run by LLM + NTC templates.
# Edit this file to customize commands, thresholds, and report format.
# Regenerated automatically when SKILL.md inspection_items change.
#
# Sections:
#   skill_fingerprint  — change detection, do not edit manually
#   platform_commands  — which CLI command to run per item per platform
#   thresholds         — anomaly detection limits
#   report_template    — report structure and output format

# ── 变更检测 ─────────────────────────────────────────────────────────
# DO NOT EDIT: automatically maintained by _init_inspection_config()
skill_fingerprint:
  items_hash: "sha256:abc123..."   # hash of inspection_items names+descriptions
  generated_at: "2026-02-19T10:00:00"
  generated_by: "llm-init"        # "llm-init" | "user-override"
  platforms_seen: [cisco_ios, juniper_junos]

# ── 平台命令映射 ──────────────────────────────────────────────────────
# Key: inspection_item name (must match SKILL.md inspection_items[].name)
# Value: best CLI command for this platform (LLM-selected from NTC database)
# Override: change any value here to force a specific command
platform_commands:
  cisco_ios:
    device_info:          "show version"
    cpu_utilization:      "show processes cpu"
    memory_utilization:   "show processes memory sorted"
    environment:          "show environment all"
    interface_status:     "show interfaces status"
    interface_errors:     "show interfaces"
    neighbor_discovery:   "show cdp neighbors detail"
    mac_address_table:    "show mac address-table"
    routing_table:        "show ip route"
    ospf_neighbors:       "show ip ospf neighbor"
    bgp_neighbors:        "show ip bgp summary"
    arp_table:            "show arp"

  juniper_junos:
    device_info:          "show version"
    cpu_utilization:      "show chassis routing-engine"
    memory_utilization:   "show chassis routing-engine"
    interface_status:     "show interfaces terse"
    interface_errors:     "show interfaces extensive"
    neighbor_discovery:   "show lldp neighbors"
    routing_table:        "show route summary"
    ospf_neighbors:       "show ospf neighbor"
    bgp_neighbors:        "show bgp summary"

  arista_eos:
    device_info:          "show version"
    cpu_utilization:      "show processes top once"
    memory_utilization:   "show version"
    interface_status:     "show interfaces status"
    neighbor_discovery:   "show lldp neighbors"
    ospf_neighbors:       "show ip ospf neighbor"
    bgp_neighbors:        "show ip bgp summary"

# ── 异常检测阈值 ──────────────────────────────────────────────────────
# warning: triggers ⚠️ annotation, -5 health score
# critical: triggers 🔴 annotation, -20 health score
thresholds:
  cpu_utilization:
    warning: 70
    critical: 90
    unit: percent

  memory_utilization:
    warning: 75
    critical: 90
    unit: percent

  interface_errors:
    in_errors:  {warning: 1,  critical: 10, unit: count_per_min}
    out_errors: {warning: 1,  critical: 10, unit: count_per_min}
    crc_errors: {warning: 0,  critical: 5,  unit: count_per_min}

  ospf_neighbors:
    expected_state: "FULL"          # any other state = warning

  bgp_neighbors:
    expected_state: "Established"   # any other state = critical

  routing_table:
    min_routes: 1                   # 0 routes = critical

# ── 报告模板 ──────────────────────────────────────────────────────────
# 用户在这里定义报告的标题和章节结构
# LLM 读取此模板并按结构填入内容，不自由发挥章节顺序
report_template:
  language: "zh-CN"                 # "zh-CN" | "en-US"
  format: "markdown"                # "markdown" | "json" (json = structured data only)

  # 报告标题
  title: "网络健康巡检报告"

  # 章节定义 — 按此顺序生成，content_hint 告诉 LLM 每节写什么
  sections:
    - id: executive_summary
      title: "📊 执行摘要"
      required: true
      content_hint: |
        总体健康分数（0-100），设备状态统计表（正常/警告/严重数量），
        最严重问题一句话概括。不超过100字。

    - id: device_matrix
      title: "📱 设备状态矩阵"
      required: true
      content_hint: |
        表格：设备名 | 健康分 | 状态 | 异常数量 | 执行命令数
        每行一个设备，按健康分升序排列（最差在最前）。

    - id: anomalies
      title: "🔍 异常详情"
      required: true
      include_when: "anomaly_count > 0"
      content_hint: |
        按严重程度分组（🔴 严重 / ⚠️ 警告）。
        每条异常：设备名、指标名、当前值、阈值、建议措施。
        L1（物理层）→ L2（链路层）→ L3（网络层）顺序排列。

    - id: baseline_comparison
      title: "📈 基线对比"
      required: false
      include_when: "previous_snapshot_exists"
      content_hint: |
        与上次快照对比：变化的指标、新增异常、消除的异常。
        仅显示有变化的内容，无变化不输出本节。

    - id: recommendations
      title: "💡 建议措施"
      required: true
      content_hint: |
        按优先级排序的行动清单：
        P1（立即）→ P2（本周）→ P3（优化建议）
        每条措施：设备、问题、具体建议命令或操作步骤。

    - id: threshold_suggestions
      title: "🎯 阈值调整建议"
      required: false
      include_when: "has_threshold_suggestion"
      content_hint: |
        如果某指标连续3次检查均在阈值 ±10% 范围内，建议调整阈值。
        格式：指标名 | 当前阈值 | 建议新阈值 | 原因
        提醒用户：修改 inspection_config.yaml thresholds 节应用更改。

    - id: next_inspection
      title: "⏭️ 下次巡检"
      required: true
      content_hint: |
        当前调度计划（从 cron 读取），下次运行时间，
        如果有严重异常建议提前手动触发 take_snapshot。
```

---

### 三、SKILL.md 变更检测机制

**原理**：对 `inspection_items` 的 `name` + `description` 字段计算 SHA-256，存入 `skill_fingerprint.items_hash`。每次运行前比对，不一致则重新生成 `platform_commands`。

```python
import hashlib, yaml

def _compute_skill_fingerprint(inspection_items: list[dict]) -> str:
    """Compute deterministic hash of inspection_items names and descriptions."""
    content = "\n".join(
        f"{item['name']}:{item.get('description', '')}"
        for item in sorted(inspection_items, key=lambda x: x["name"])
    )
    return "sha256:" + hashlib.sha256(content.encode()).hexdigest()[:16]

def _needs_regeneration(config_path: Path, current_fingerprint: str) -> bool:
    """Return True if inspection_config.yaml is missing or skill changed."""
    if not config_path.exists():
        return True
    with open(config_path) as f:
        config = yaml.safe_load(f)
    stored = config.get("skill_fingerprint", {}).get("items_hash", "")
    return stored != current_fingerprint
```

**行为**：

| 场景 | 行为 |
|---|---|
| 首次运行 | 生成完整 inspection_config.yaml |
| SKILL.md 未改变 | 直接读 platform_commands，跳过 LLM 查询 |
| SKILL.md 新增/修改 inspection_items | 仅重新生成 platform_commands（保留用户修改的 thresholds 和 report_template） |
| 用户在文件里改了 platform_commands | `generated_by: "user-override"` 标记，跳过自动覆盖 |

---

### 四、LLM 命令选择流程（首次 / 变更时）

```python
def _llm_select_commands(
    item_name: str,
    item_description: str,
    platform: str,
    ntc_candidates: list[str],  # 来自 NTC 关键字预筛选
) -> str:
    """Ask LLM to select best command from NTC candidates for this inspection item."""
    # ntc_candidates 是先用关键字筛出的候选命令列表（5-20个）
    # LLM 只做最终选择，不凭空生成命令
    prompt = f"""
Platform: {platform}
Inspection item: {item_name}
Description: {item_description}

Available NTC template commands (choose exactly one):
{chr(10).join(f"- {cmd}" for cmd in ntc_candidates)}

Select the single best command that covers the inspection item's description.
Return ONLY the command string, nothing else.
"""
    # 调用 LLM，返回单行命令字符串
    return llm.invoke(prompt).content.strip()
```

**关键约束**：LLM 只从 `ntc_candidates` 列表中选择，不能输出列表之外的命令。这保证了命令来自 NTC templates 数据库（有对应解析器）。

---

### 五、实施步骤

**Phase A：配置文件初始化**（`inspection.py`）

1. `_init_inspection_config()` — 首次 `manage_inspection_schedule` 调用时触发
2. 如果 `inspection_config.yaml` 不存在或 fingerprint 不匹配：
   - 读 SKILL.md `inspection_items`
   - 读 Nornir inventory 获取实际平台列表
   - 对每个 platform + item：NTC 预筛选 → LLM 选一个
   - 写入 `platform_commands` + 默认 `thresholds` + 默认 `report_template`
   - 保留已有文件中用户修改过的 `thresholds` 和 `report_template` 节

**Phase B：`take_snapshot` 读配置**（`snapshot.py`）

1. 读 `inspection_config.yaml platform_commands[platform][item_name]`
2. Fallback：`CATEGORY_KEYWORDS` NTC 匹配（保持向后兼容）

**Phase C：`aggregate_inspection_results` 读阈值**（`aggregation.py`）

1. `_load_thresholds()` 改为读 `inspection_config.yaml thresholds`
2. 当前的 `thresholds.yaml` 作为 legacy fallback

**Phase D：LLM 报告渲染**（`prompts/system.md`）

1. 在 system.md 中加入："读取 `inspection_config.yaml report_template`，严格按 `sections` 顺序生成报告，每节使用 `content_hint` 描述的内容。不得添加 YAML 中未定义的章节。"
2. `include_when` 条件由 LLM 判断（基于 aggregate 结果）

---

### 六、文件新旧对应关系

| 旧文件 | 状态 | 新文件 |
|---|---|---|
| `config/thresholds.yaml` | 保留作 legacy fallback，最终废弃 | `config/inspection_config.yaml thresholds` 节 |
| `config/command_resolver.py` | 已删除 2026-02-19 | `inspection_config.yaml platform_commands` 节 |
| `tools/report_formatter.py` | 已删除 2026-02-19 | `inspection_config.yaml report_template` 节 + LLM |

---

### 七、用户工作流

```
# 1. 定义要检查什么（SKILL.md）
olav admin "帮我在 inspection 中加入检查 BGP prefix count 的项目"
# → ConfigAgent 修改 SKILL.md inspection_items
# → 下次 take_snapshot 前自动重新生成 platform_commands

# 2. 自定义命令（直接编辑文件）
vim .olav/skills/network-inspection/config/inspection_config.yaml
# 修改 platform_commands.cisco_ios.bgp_neighbors 到你想要的命令
# 系统检测到 generated_by: "user-override" 后不再覆盖

# 3. 调整阈值
vim .olav/skills/network-inspection/config/inspection_config.yaml
# 修改 thresholds.cpu_utilization.warning: 85

# 4. 自定义报告格式
vim .olav/skills/network-inspection/config/inspection_config.yaml
# 修改 report_template.language: "en-US"
# 删除不需要的 sections
# 修改 content_hint 调整每节内容风格

# 5. 运行
olav inspect
# → 读 inspection_config.yaml，确定性执行，LLM 按模板生成报告
```

---

**版本**: v4.0  
**下一步**: Phase A 实施（`inspection.py` 加入 `_init_inspection_config()`）
