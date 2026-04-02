# SOP: 四段式数据采集流水线 (Network Data Collection Pipeline)

## 触发条件
用户说："采集数据" / "snapshot" / "更新网络状态" / "全量同步" / "onboard"

## 首选调用方式 — 单工具调用

```python
# ✅ 推荐: 一次工具调用完成完整流水线
run_pipeline()                         # 全量: collect → repair gaps → topology
run_pipeline(mode="snapshot_only")     # 仅采集, 不修复, 不生成 topology
run_pipeline(mode="incremental")       # 增量: 同 full, 无 HIGH gaps 时跳过 repair
run_pipeline(mode="topology_only")     # 仅重建 topology (从已有 parsed_outputs)
```

> **命名说明**: `run_pipeline` = 完整流水线入口。`collect_commands` = 仅 SSH 采集阶段（内部实现）。
> 对外统一使用 `run_pipeline`，避免 LLM 逐步编排导致的多 RTT 和中间态错误。

## 工具职责分工

| Stage | 工具 | 职责 | 返回值 |
|-------|------|------|--------|
| Stage 1+2+3 | `sync.collect_commands` | SSH 采集 → TextFSM 解析 → Diff 计算 | **dict** 含 `parse_errors` 列表 |
| Stage Learner | `learner.generate_template` + `learner.save_template` | 逐个修复解析模板 | 生成 .textfsm 文件 |
| Stage Reparse | `sync.reparse_outputs` | 仅重解析指定命令（无 SSH） | `{success, records}` |
| Stage Final | `config.discovery.run_topology_sandbox` | NetworkX 图分析 + Mermaid 生成 | edge_count 条图边 |

> **命名说明**: `collect_commands` = SSH 采集 + 解析（原 `take_snapshot`）。
> "snapshot" 是整个流程的统称，单个工具不能叫 snapshot 以免产生幻觉。

## 执行步骤

### 完整流程（首次 Onboard 或全量刷新）

```
Step 1: result = collect_commands(wait=True)
   → Stage 1: SSH 连接所有设备，保存 raw 文件到 tmp/snapshots/{date}/raw/
  → Stage 2: TextFSM 解析 → 写入 parsed_outputs 表
  → Stage 3: 对比上次快照，写入 raw_diffs 表（首次为 0）
  → 返回 dict，关键字段:
      result["snapshot_id"]    # e.g. "2026-03-02_1730"
      result["parse_errors"]   # list[{device, command, severity, raw_size, raw_file}]
      result["diff_records"]   # int

Step 2: 读 result["parse_errors"] — 直接从返回值获取，无需读文件或 SOP 规则
  → 过滤条件: severity == "high" 且 raw_size > 200
  → 逐个处理（AUTO MODE，不暂停）:

  FOR EACH gap IN [e for e in result["parse_errors"] if e["severity"]=="high" and e["raw_size"]>200]:
    a) 读原始文件: read_file(gap["raw_file"])
       ← 从磁盘读取，NO SSH！防止 malloc crash
    b) 调用 learner (AUTO MODE):
         generate_template(platform, command, raw_output)
         → 内置 LLM reflection loop，确保解析 PASS
         save_template(...)
    c) 重解析: reparse_outputs(device=gap["device"], command=gap["command"])
       ← 仅针对这一个命令，无 SSH，无全量重采集
    d) 验证: reparse_result["records"] > 0 → ✅ gap 已修复

Step 3: 所有 HIGH-priority gaps 修复完成（或无 gaps）后:
  sync_schemas()          ← schema 清洗（仅需要时）
  run_topology_sandbox()  ← 必须执行，不可跳过
  → 从 v_topo_links_clean 构建 NetworkX 图，输出 edge_count + Mermaid
  → 是后续 routing analysis、ops-diff 的基础
```

### 快速增量采集（日常运维）

```
Step 1: result = collect_commands(wait=True)
  → 自动完成 Stage 1+2+3
  → 检查 result["diff_records"] > 0 → 有配置变更
  → 检查 result["parse_errors"] → 有新的解析失败

Step 2: 报告变更
  → SELECT device_name, command, lines_changed FROM raw_diffs
    WHERE snapshot_id = result["snapshot_id"] AND lines_changed > 0
    ORDER BY lines_changed DESC LIMIT 20
```

## 关键约束

### ✅ 必须遵守
- **parse_errors 来自返回值**: LLM 直接读 `result["parse_errors"]`，**不通过读日志或 SOP 触发条件** 判断
- **learner 读磁盘**: learner 用 `read_file(gap["raw_file"])` 读 raw 文件，**不重新 SSH** 设备
- **逐个 reparse**: 每修复一个模板立即调用 `reparse_outputs(device, command)`，**不全量重采集**
- **topology 最后**: `run_topology_sandbox()` 必须在所有 learner 修复完成后才调用

### ❌ 禁止
- 调用 `collect_commands` 重新 SSH 来"刷新"已修复的命令（用 `reparse_outputs` 即可）
- 在 learner 修复未完成时调用 `run_topology_sandbox()`
- 跳过 `run_topology_sandbox()`（topology 是后续分析的基础）

## 自愈优先级

| 条件 | 优先级 | 动作 |
|------|--------|------|
| `severity=="high"` 且 `raw_size > 200` | **HIGH** | 必须修复 |
| `severity=="medium"` | MEDIUM | 可选修复 |
| raw 含 "feature not enabled" / "% Invalid" | 跳过 | 设备不支持该功能 |
| raw 含 "not enabled" 且 raw_size < 100 | 跳过 | 功能未启用 |

## 输出检查点

```bash
# 验证 Raw 文件
ls tmp/snapshots/{snapshot_id}/raw/{device}/

# 验证解析记录
duckdb .olav/databases/main.duckdb \
  "SELECT device_name, COUNT(*) FROM parsed_outputs \
   WHERE snapshot_id='{snapshot_id}' GROUP BY 1"

# 验证 Diff 记录（第二次快照后才有数据）
duckdb .olav/databases/main.duckdb \
  "SELECT device_name, command, lines_changed FROM raw_diffs \
   WHERE snapshot_id='{snapshot_id}' ORDER BY lines_changed DESC LIMIT 20"

# 验证 Topology
duckdb .olav/databases/main.duckdb \
  "SELECT COUNT(*) FROM topology_links"
```



