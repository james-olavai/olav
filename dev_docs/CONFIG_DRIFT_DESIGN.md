# Config Drift Detection — Design Document (v2, 简化版)

**Status**: 设计完成，待实施  
**Date**: 2026-02-20  
**Replaced**: 原设计 v1 过度复杂（新规则条件 + 新报告节 + golden baseline 基础设施），已废弃

---

## 1. 设计原则

- **一个工具**: `diff_snapshot`，两个 agent 各放一份，纯 difflib，无框架依赖
- **工具驱动**: 不改 audit rule engine，不加新条件类型，不加新报告节类型
- **独立 audit 配置**: 新建 `AUDIT_CONFIG_DRIFT.yaml`，专用于漂移追踪；**不改 AUDIT_HEALTH**
- **Cron 触发**: 每日自动运行 `run_audit("AUDIT_CONFIG_DRIFT")`，结果写入报告目录

---

## 2. 工具设计：`diff_snapshot`

### 位置

```
.olav/skills/olav-ops/tools/diff_snapshot.py    # olav-ops 交互式使用
.olav/skills/olav-audit/tools/diff_snapshot.py  # olav-audit 审计使用（内容相同）
```

两份文件内容完全相同（内联复制，不跨 skill 导入）。

### 函数签名

```python
@tool
def diff_snapshot(
    device: str,
    command: str,
    date_a: str | None = None,
    date_b: str | None = None,
    sections: list[str] | None = None,
    context_lines: int = 3,
) -> dict:
    """Compare raw CLI output snapshots between two dates to detect drift.

    Reads files from exports/snapshots/{date}/raw/{device}/{cmd-slug}.txt
    and returns a unified diff. Any command with a raw snapshot can be compared.

    Args:
        device:        Device hostname, e.g. "R1".
        command:       CLI command name, e.g. "show running-config".
                       Converted to slug (spaces → dashes, lowercase) for file lookup.
                       Supports fuzzy match: "running config" finds "show-running-config.txt".
        date_a:        Baseline date, one of:
                         "YYYY-MM-DD"  — specific snapshot date
                         None          — auto: most recent snapshot date BEFORE date_b
        date_b:        Target date, one of:
                         "YYYY-MM-DD"  — specific snapshot date
                         None          — today (datetime.now().strftime("%Y-%m-%d"))
        sections:      Optional list of IOS section keywords to restrict the diff
                       (prefix match on top-level config lines).
                       Examples: ["aaa", "line vty", "ip access-list", "interface",
                                  "router bgp", "router ospf", "ntp", "banner"]
                       None = diff the entire file.
        context_lines: Lines of unchanged context shown around each change. Default 3.

    Returns on success:
        {
            "status": "success",
            "device": "R1",
            "command": "show running-config",
            "date_a": "2026-02-19",
            "date_b": "2026-02-20",
            "added_lines": 4,
            "removed_lines": 1,
            "changed_lines": 5,
            "diff": "--- 2026-02-19/R1\n+++ 2026-02-20/R1\n@@...",
            "summary": "5 lines changed (+4/-1). Sections: ip access-list, line vty.",
        }

    Returns on error:
        {"status": "error", "message": "No snapshot found for R1 on 2026-02-18"}

    Examples:
        diff_snapshot("R1", "show running-config")
        diff_snapshot("R1", "show running-config", date_a="2026-02-14")
        diff_snapshot("R1", "show running-config", sections=["aaa", "line vty"])
        diff_snapshot("R2", "show ip ospf neighbor", date_a="2026-02-19")
    """
```

### 核心实现逻辑

```python
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
_SNAPSHOTS = _PROJECT_ROOT / "exports" / "snapshots"

# IOS metadata lines that change every snapshot — excluded from changed_lines count
_METADATA_PATTERNS = [
    "Current configuration :",
    "! Last configuration change at",
    "Building configuration",
]

def _to_slug(command: str) -> str:
    return command.strip().lower().replace(" ", "-")

def _find_file(device: str, cmd_slug: str, date: str) -> Path:
    """Exact match then word-based fuzzy match (same logic as audit_engine._extract_raw_text)."""
    base = _SNAPSHOTS / date / "raw" / device
    exact = base / f"{cmd_slug}.txt"
    if exact.exists():
        return exact
    words = cmd_slug.split("-")
    for f in sorted(base.glob("*.txt")):
        if all(w in f.stem for w in words):
            return f
    raise FileNotFoundError(f"No file matching '{cmd_slug}' for {device} on {date}")

def _resolve_date_a(device: str, cmd_slug: str, date_b: str) -> str:
    """Auto-detect most recent snapshot before date_b with the target file."""
    candidates = sorted(
        d for d in _SNAPSHOTS.iterdir()
        if d.is_dir() and d.name not in ("latest",) and d.name < date_b
        and any(True for _ in [_find_file(device, cmd_slug, d.name)] if True)
    )
    # (use try/except around _find_file in the real implementation)
    if not candidates:
        raise FileNotFoundError(f"No prior snapshot for {device}/{cmd_slug} before {date_b}")
    return candidates[-1].name

def _extract_sections(text: str, sections: list[str]) -> str:
    """Return only lines belonging to the named IOS config sections (prefix match)."""
    lines, result, in_section = text.splitlines(), [], False
    for line in lines:
        is_top = line.strip() and not line.startswith((" ", "\t"))
        if is_top:
            in_section = any(line.lower().startswith(s.lower()) for s in sections)
        if in_section:
            result.append(line)
        elif line.strip() == "!" and in_section:
            result.append(line)
            in_section = False
    return "\n".join(result)

def _count_significant(diff_lines: list[str]) -> tuple[int, int]:
    """(added, removed) excluding IOS metadata churn lines."""
    added = removed = 0
    for line in diff_lines:
        if not any(p in line for p in _METADATA_PATTERNS):
            if line.startswith("+") and not line.startswith("+++"):
                added += 1
            elif line.startswith("-") and not line.startswith("---"):
                removed += 1
    return added, removed
```

---

## 3. AUDIT_CONFIG_DRIFT.yaml — 是否单独创建？

**结论：是，应该单独创建。**

| 问题 | AUDIT_HEALTH 嵌入 | 独立 AUDIT_CONFIG_DRIFT |
|------|------------------|------------------------|
| 关注点分离 | 健康检查混入变更审计 | 两份报告职责清晰 |
| 调度灵活性 | 每次健康检查都收 configs（耗时） | 独立调度，可定义不同频率 |
| 任意命令 | AUDIT_HEALTH 无此用途 | 可追踪 running-config 以外的任意命令 |
| 无历史快照时 | AUDIT_HEALTH 整体降级 | 独立失败，不影响健康检查 |

### Audit 流程（不修改 rule engine）

```
AUDIT_CONFIG_DRIFT 工作流:
  1. collect.intents: [configs]  → take_snapshot 已完成
  2. 少量 raw_contains/raw_not_contains 规则  → 产出结构化 findings（利用现有引擎）
  3. LLM Analyze 阶段（per_device）：
       - audit agent 调用 diff_snapshot(device, "show running-config")
       - 获取完整 diff，附入报告
  4. 写 exports/reports/audit_config_drift_{timestamp}.md
```

不需要修改 audit rule engine，不需要新条件类型。diff 全文通过 LLM Analyze 自然附入报告。

### AUDIT_CONFIG_DRIFT.yaml 内容

```yaml
name: "Configuration Drift Detection"
version: "1.0.0"
description: "Detects running-config drift vs previous snapshot; full diff in LLM analysis"
type: compliance
created_at: "2026-02-20"
created_by: builtin

collect:
  intents:
    - configs

rules:
  # 少量规则作为结构化 findings（不是 drift 的主要检测手段）
  - name: config_changed_timestamp
    target: running-config
    condition: raw_contains
    command: "show running-config"
    pattern: "Last configuration change"
    severity: info
    recommendation: "Config has been changed; review diff in analysis section"

output:
  title: "Configuration Drift Report"
  filename_pattern: "audit_config_drift_{timestamp}.md"
  sections:
    - type: header
      fields: [date, scope, device_summary]
    - type: per_device_analysis
    - type: footer

analysis:
  per_device:
    enabled: true
    instructions: |
      Call diff_snapshot(device="{device}", command="show running-config") to get
      the full running-config diff between today and the most recent prior snapshot.

      Report:
      1. The diff output verbatim (truncate at 60 lines with "[...truncated]" if longer)
      2. Which IOS sections changed (aaa, acl, interfaces, routing, line vty, etc.)
      3. Assessment: routine (scheduled maintenance) or suspicious (off-hours, security
         section, unexpected keywords like "no service password-encryption")
      4. Recommendation: approve+document, rollback, or investigate
      5. If diff_snapshot returns error (no prior snapshot), say so clearly.

      Format as markdown with a collapsible diff block.
      Prose: 3-5 sentences after the diff.
```

---

## 4. Cron 任务

在 `.olav/cron/tasks.yaml` 中追加（格式以现有任务为准）：

```yaml
- name: daily-config-drift-audit
  description: "Detect running-config drift vs previous day snapshot"
  schedule: "30 2 * * *"    # 每日 02:30（Cron A snapshot 完成后 30 min）
  command: "uv run olav-audit run_audit AUDIT_CONFIG_DRIFT"
  enabled: true
```

> **前提**：Cron A（02:00）的 `take_snapshot` 已包含 `configs` category。  
> 若仅收集 system/interfaces/routing/neighbors，需在 Cron A 的 categories 中加入 `configs`，或单独加一条 02:00 的 configs-only snapshot 任务。

---

## 5. SKILL.md 更新

### olav-ops

```yaml
tools:
  # ... 现有工具 ...
  - diff_snapshot    # ← 新增
```

**LLM 调用示例**：

| 用户输入 | 工具调用 |
|---------|---------|
| "R1 最近配置变了什么？" | `diff_snapshot("R1", "show running-config")` |
| "对比 R2 的 AAA 和 VTY 配置" | `diff_snapshot("R2", "show running-config", sections=["aaa","line vty"])` |
| "变更窗口前后 OSPF 邻居有变化？" | `diff_snapshot("R1", "show ip ospf neighbor", date_a="2026-02-19")` |
| "跨一周对比 BGP 摘要" | *循环每台设备* `diff_snapshot(d, "show ip bgp summary", date_a="2026-02-13")` |

### olav-audit

```yaml
tools:
  # ... 现有工具 ...
  - diff_snapshot    # ← 新增：供 LLM Analyze 阶段调用
```

---

## 6. 实施顺序

### Phase 1 — diff_snapshot 工具

1. 实现 `.olav/skills/olav-ops/tools/diff_snapshot.py`
2. 复制到 `.olav/skills/olav-audit/tools/diff_snapshot.py`
3. 更新两个 `SKILL.md` 工具列表
4. 写 `tests/e2e/test_diff_snapshot.py`（见下）

### Phase 2 — AUDIT_CONFIG_DRIFT

1. 创建 `.olav/skills/olav-audit/config/AUDIT_CONFIG_DRIFT.yaml`
2. 写 `tests/e2e/test_audit_config_drift.py`

### Phase 3 — Cron 注册

1. 确认 Cron A 是否已包含 configs category
2. 追加 `daily-config-drift-audit` 至 tasks.yaml
3. `olav task schedule` 注册到系统 crontab

---

## 7. 测试设计

### `tests/e2e/test_diff_snapshot.py`

```
TestDiffSnapshotTool
  test_auto_previous_detects_r1_drift          # date_a=None → 找 2026-02-19
  test_correct_changed_line_count              # R1: 4 lines changed (+4/-0 net)
  test_metadata_lines_excluded_from_count      # "Current configuration" 行不计入
  test_section_filter_ip_access_list           # 只 diff ACL 节，找到新内容
  test_section_filter_no_match_zero_changes    # sections 无变化 → changed_lines=0
  test_explicit_date_a                         # date_a="2026-02-14" 正常工作
  test_any_command_works                       # command="show ip route" 也能 diff
  test_missing_device_returns_error
  test_no_prior_snapshot_returns_error
  test_same_date_a_b_zero_changes
  test_fuzzy_command_match                     # "running config" 仍能找到文件
```

### `tests/e2e/test_audit_config_drift.py`

```
TestAuditConfigDriftYaml
  test_yaml_loads_valid
  test_collect_intents_include_configs

TestRunAuditConfigDrift
  test_run_audit_returns_success
  test_report_file_created
```

---

## 8. 决策记录（v1 → v2 简化）

| 决策 | v1 | v2 | 理由 |
|------|----|----|------|
| audit rule engine | 新增 `config_drifted` 条件 | **不改** | 现有 raw_contains + LLM analyze 已足够 |
| 报告渲染 | 新增 `config_drift_table` 节 | **不改** | LLM 输出 markdown diff 更灵活 |
| Golden baseline | `.olav/baselines/` + pin 工具 | **不实现** | YAGNI；`date_a=YYYY-MM-DD` 可手动指定 |
| AUDIT_HEALTH | 追加 drift 规则 | **不改** | 关注点分离 |
| 工具数量 | 2（diff + pin） | **1**（diff_snapshot） | 够用就好 |

---

## 参考：真实漂移数据

R1 在 2026-02-19 → 2026-02-20 之间真实漂移（可直接用于测试，无需 mock）：

```diff
250a251,253
> ip access-list standard 1
>  10 permit 192.168.100.0 0.0.0.255
>  remark Permit_Mgmt
285a289
>  access-class 1 in
```

`changed_lines` 预期值：**4**（排除元数据行后新增 4 行，无删除）。
