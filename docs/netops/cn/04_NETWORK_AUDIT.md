# 网络审计 Agent (Network Audit Agent)

审计 Agent 用于在整个网络中执行**计划内或按需的健康检查**。你只需向其提供一个 **Profile (配置文件)** —— 即一份关于检查内容的声明性规范 —— 它就会查询快照数据库、检测异常、将事件关联为故障簇，并生成一份包含可直接运行的 **运维剧本 (Ops Playbook)** 的结构化报告。

Profiles **始终由 设计器 (Designer) 子 Agent 生成和修改** —— 永远不要进行手动编辑。设计器会内省实时数据库模式，针对真实数据试运行每个查询，并将验证后的配置文件保存到磁盘。

### 🔍 审计 Agent 是多维度的健康检查系统

不同于单点查询工具，审计 Agent 在**多个维度**上运作：

| 维度 | 能力 | 例子 |
|------|------|------|
| **当前状态快照** | 查询最新快照中的任何数据（接口、邻接、路由、配置等） | "有多少个 BGP 邻接不处于 Established 状态？" |
| **跨快照漂移检测** | 对比快照之间的变化，识别配置/状态的偏移 | "哪些接口在过去 3 天内状态变过？" |
| **异常检测 (Z-score)** | 基于每个设备的历史基线，识别统计学离群值 | "R1 的 CPU 相对它自己的历史突增了吗？" |
| **语义日志搜索** | 通过向量搜索在 Syslog 中智能匹配故障关键词 | "过去 24 小时有哪些严重故障日志？" |
| **事件聚类** | 将散落的发现关联为拓扑上的故障簇 | "哪些设备故障实际上是有根本原因的？" |
| **配置审计** | 追踪配置变更，检测不符合基线的漂移 | "哪些设备配置偏离了标准模板？" |

这些维度结合起来，才能完成简单查询工具无法做到的**自动化全量审计**和**根因联动分析**。

---

## 使用设计器创建 Profile

**设计器 (Designer)** 是负责制作和验证审计配置文件的子 Agent。其功能包括：

1. 内省实时的 DuckDB/LanceDB 方案 —— 绝不猜测列名。
2. 在保存之前针对真实数据试运行每个查询。
3. （可选）运行 `analyze_thresholds` 来计算 P50/P90/P95 分布，从而实现数据驱动的阈值。
4. 将验证后的配置文件写入 `.olav/workspace/audit/profiles/<name>.md`。

### 调用设计器

**有两种选择：交互式对话或管道指令。**

**选项 1 — 交互式对话**（设计器会提出澄清性问题）

当你有一个粗略的想法但希望设计器细化细节时，请使用此选项。

```bash
uv run python -m olav --agent audit
> 为我设计一个 BGP 健康检查配置文件 (BGP health profile)
```

设计器会响应：
```
该配置文件应重点关注什么？
- 当前的 BGP 邻居状态？
- 随时间变化的 BGP 会话振荡 (flaps)？
- 前缀数量异常？
- 以上所有内容？

另外，你希望为每个检查设置什么严重程度级别？
```

然后你可以交互式地细化你的需求。

**选项 2 — 详细指令**（设计器立即执行）

当你已经有明确的规范并希望快速、非交互式地执行时，请使用此选项。

```bash
uv run python -m olav --agent audit
> 设计一个名为 "bgp_health" 的审计配置文件，检查：
  1. 不处于 Established 状态的 BGP 邻居（严重/Critical）
  2. 快照之间的 BGP 会话状态变化（严重/Critical）
  3. 接收到的前缀数量较前一快照下降 >20%（警告/Warning）
  使用数据驱动的阈值。语言：中文。
```

设计器会立即内省方案、试运行查询、分析阈值并保存 —— 无需反复沟通。

### 示例：health_full_drift（内置配置文件）

以下提示词生成了内置的 `health_full_drift` 配置文件 —— 你可以将它作为理解设计器生成内容的起点，或者逐字运行它以从头开始重新创建该配置文件。

**提示词：**

```
设计一个名为 "health_full_drift" 的综合网络健康审计配置文件。

它应涵盖：

1. 异常检测 (Z-score, 每个设备的基线, 阈值 2.5)：
   - CPU 利用率（来自 parsed_outputs 的 5 秒平均值）
   - 内存利用率百分比

2. 当前状态检查 (SQL, Critical)：
   - 不处于 'up' 状态的物理接口（排除 Loopback, Management, Vlan, Tunnel）
   - 不处于 Established 状态的 BGP 邻居
   - 不处于 FULL 或 2WAY 状态的 OSPF 邻居
   - 处于 err-disable 状态的交换机端口

3. 语义化 Syslog 搜索 (LanceDB, Critical)：
   - 关键故障关键词：critical error alert failure interface down BGP reset flap
     memory OOM spanning-tree BPDU err-disable chassis hardware fault

4. 跨快照漂移检查 (SQL, Warning)，使用 raw_diffs：
   - 连续快照之间的 CPU 变化（标记增量 ≥5%）
   - 内存利用率变化（标记增量 ≥3%）
   - 接口链路协议 (line-protocol) 状态翻转
   - BGP 会话状态变化（Established 增加/移除）
   - OSPF 邻接状态变化（FULL 移除，LOADING/DOWN 增加）
   - 生成树 (Spanning-tree) 端口角色或根桥 (root bridge) 变化
   - Syslog 行数突增（>10 条新行）

5. 配置变更检测 (SQL, Warning)：
   - 运行配置 (Running-config) 的差异，增加+删除 > 0（总计 > 50 标记为高风险）

启用事件聚类 (run_incident_clustering: true)，快照分辨率: 1d，
单次任务最大发现数: 100。语言：中文。
```

**生成的配置文件 —— 包含 15 项检查：**

| 检查项 | 严重程度 | 检测内容 |
|---|---|---|
| **CPU_Anomaly** | Critical | CPU 相对于每个设备自身历史记录的统计学激增/下降 (Z-score) |
| **Memory_Anomaly** | Critical | 内存的统计学偏移；持续增长 = 内存泄漏信号 |
| **Interface_Down** | Critical | 当前处于 down 状态的物理接口（排除管理/环回接口） |
| **BGP_Not_Established** | Critical | 不处于 Established 状态的 BGP 邻居 |
| **OSPF_Not_Full** | Critical | 不处于 FULL 或 2WAY 状态的 OSPF 邻接 |
| **STP_Error_Disable** | Critical | 处于 err-disable 状态的交换机端口 |
| **Critical_Syslog** | Critical | 语义匹配的故障日志条目（通过 Syslog 进行向量搜索） |
| **CPU_Drift** | Warning | 连续快照之间 CPU 变化 ≥5% |
| **Memory_Drift** | Warning | 连续快照之间内存利用率变化 ≥3% |
| **Interface_State_Drift** | Warning | 跨快照的接口链路协议状态翻转 |
| **BGP_Drift** | Warning | 跨快照的 BGP 会话状态变化 |
| **OSPF_Drift** | Warning | OSPF 邻接状态变化（方向性：FULL → LOADING/DOWN） |
| **STP_Drift** | Warning | 生成树拓扑变化（端口角色/状态转换） |
| **Log_Spike** | Warning | 连续快照之间 Syslog 行数突增 >10 条新行 |
| **Config_Drift** | Warning | 运行配置变更；变更超过 50 行标记为高风险 |

### 示例：创建一个专注 BGP 的配置文件

```
设计一个名为 "bgp_health" 的审计配置文件，仅关注 BGP。
检查内容：
1. 当前不处于 Established 状态的 BGP 邻居（严重/Critical）
2. 在指定时间窗口内，通过 raw_diffs 检测到的 BGP 会话状态变化（严重/Critical）
3. BGP 前缀数量变化 —— 如果接收到的前缀数量较前一快照下降超过 20%，则发出标记（警告/Warning）
尽可能使用数据驱动的阈值。
语言：中文。
```

设计器会内省方案，从数据库中计算实际的 P90/P95 前缀分布，提出阈值建议，并等待你的确认后再保存。

---

## 审计 Agent 可以监控的内容

审计 Agent 可以检查**快照数据库中存储的任何数据**。自定义配置文件可以针对任何表、列或其组合。

### 覆盖类别

| 类别 | 示例 |
|---|---|
| **单设备异常检测** | `parsed_outputs` 中的任何数字指标 —— 延迟、队列深度、错误计数器、BGP 前缀计数 |
| **跨快照漂移 (Drift)** | 任何包含 `created_at` 列和 `raw_diffs` 中状态字段的表 |
| **设备配置漂移** | 任何 `show running-config` / `show configuration` 部分的差异 |
| **Syslog / 语义化日志搜索** | 通过 LanceDB 向量搜索匹配任何故障关键词模式 |
| **第三方 API 数据** | 由 `api_anomaly` 任务填充的任何表 —— Prometheus 指标、SNMP 陷阱聚合、NMS 提要 |
| **拓扑检查** | 针对 `topology_links` 的查询，检查预期链路数、缺失邻居、非对称路径 |

### 异常检测：自适应 Z-score（单设备基线）

对于数字指标，审计 Agent 使用**单设备 Z-score 异常检测**，而不是全局阈值。每个设备在时间窗口内的自身历史记录决定了什么是“正常”：

- 一台 CPU 永久处于 80% 的核心路由器是健康的 —— 它永远不会被标记。
- 一台从 20% 突增到 65% 的接入交换机会立即被标记。
- 连续快照之间持续向上的偏移会产生不断升高的 `z_score` —— 这是强烈的内存泄漏信号。

---

## 运行审计

### 命令行界面 (CLI)

```bash
# 推荐的简写形式
uv run python -m olav --agent audit --profile health_full_drift

# 非交互模式（用于 CI / cron）
uv run python -m olav --agent audit --profile health_full_drift --auto-approve

# 自然语言查询
echo "使用 health_full_drift 运行完整的健康审计，时间窗口 3 天" \
  | uv run python -m olav --agent audit --auto-approve
```

报告将作为 `.md`（人类可读）和 `.json`（原始发现）写入 `exports/audit_reports/`。

`--profile` 标志接受简写名称：`--profile health_full_drift` 会解析为 `.olav/workspace/audit/profiles/health_full_drift.md`。

### 通过配置 Agent (调度)

```bash
# 立即运行一次
echo "现在使用 profile health_full_drift 运行完整的健康审计" \
  | uv run python -m olav --agent config --auto-approve

# 调度每天 06:00 运行
echo "调度每天 06:00 使用 profile health_full_drift 运行网络健康审计，\
将日志记录到 .olav/logs/cron_audit.log" \
  | uv run python -m olav --agent config --auto-approve
```

配置 Agent 会编写一个如下所示的 cron 条目：
```cron
0 6 * * * cd /home/yhvh/Olav && uv run python -m olav --agent audit --profile health_full_drift --auto-approve >> .olav/logs/cron_audit.log 2>&1
```

---

## 使用运维剧本 (Ops Playbook)

每份报告的末尾都有一个**检查后剧本 (Post-Check Playbook)** —— 自动生成的 `olav -a ops` 命令，可直接复制到你的终端运行。

**优先级 1** —— 事件簇（已确认的拓扑根因）：
```bash
olav -a ops "事件簇 #INC-001 (2026-03-03 17:48, 4分钟): 故障链 SW1, SW2 → R1, R2, R3, R4。
使用 networkx 模拟移除根节点 [SW1, SW2]：识别所有受影响的下游设备和链路，
验证冗余路径是否存在，并输出恢复顺序。
事件类型：ospf_not_full×6, config_change×2"
```

**优先级 2** —— 设备级验证：
```bash
olav -a ops "R3 OSPF 邻居 1.1.1.1 不处于 FULL 状态：运行 SSH 
'show ip ospf neighbor detail 1.1.1.1' 检查 MTU/Hello/Dead 间隔"
```

每个命令都是自包含的。可以按任何顺序运行。

---

## 使用设计器更新或追加 Profile

设计器支持通过自然语言修改现有配置文件的两种工作流 —— 无需手动编辑 YAML。

### 模式 2：基于当前数据重新调整阈值

当警报灵敏度需要调整或有新数据出现时，请使用此模式。

```bash
uv run python -m olav --agent audit
> 基于过去 30 天的实际 CPU 和内存数据，重新调整 health_full_drift 中的异常阈值。
  在更改任何内容之前，向我展示 P90/P95 分布。
```

设计器将执行以下操作：
1. 读取现有配置文件以获取当前任务定义和阈值。
2. 为每个数值指标运行 `analyze_thresholds`，计算 P50/P90/P95/P99 分布。
3. 展示差异表：每个指标的当前阈值 vs 建议阈值。
4. **等待你的明确确认**（人工确认环节/HITL），然后才执行覆盖。
5. 使用新阈值保存更新后的配置文件。

适用场景：
- 现有阈值过于嘈杂（触发了过多的误报）。
- 网络状况发生变化；基线需要重新校准。
- 你希望使用数据驱动的阈值，而不是手动猜测。

**示例输出：**
```
health_full_drift 的阈值建议：

| 指标 | 当前警告 (Warning) | 建议警告 | 当前严重 (Critical) | 建议严重 |
|---|---|---|---|---|
| CPU_Anomaly | 2.5 | 2.1 | 3.5 | 3.2 |
| Memory_Anomaly | 2.5 | 2.8 | 3.5 | 3.7 |

是否继续更新？(yes/no)
```

### 模式 3：向现有配置文件追加新检查

使用此模式可以在不修改现有检查的情况下扩展配置文件。

```bash
uv run python -m olav --agent audit
> 在 health_full_drift 中添加一项新检查，监控 OSPF 外部 LSA 数量 ——
  如果任何设备的外部 LSA 数量在快照之间增加了 500 以上，则发出标记。
  尽可能使用数据驱动的阈值。
```

设计器将执行以下操作：
1. 读取现有配置文件以获取当前任务名称（防止重复）。
2. 内省数据库方案以确认表和列的可用性。
3. 针对真实数据试运行新查询。
4. （可选）调用 `analyze_thresholds` 来计算建议的警报阈值。
5. 将验证后的任务块追加到配置文件中 —— 现有任务保持不变。

适用场景：
- 添加你在排障过程中发现的特定设备指标。
- 将覆盖范围扩展到新表（例如新集成的 NMS 提要）。
- 为特定的设备角色或站点创建专门的检查。

**另一个示例：**
```bash
python -m olav --agent audit
> 在 health_full_drift 中添加一项基于关键词的 Syslog 检查，标记任何包含 
  "packet drop" 或 "discard" 的行。将任务命名为 PACKET_DROP_SPIKE。
  使用 lancedb 语义搜索。将严重程度设置为警告 (Warning)。
```

### 模式 1 (重用)：更改部分提示词以提高报告质量

如果你想改进 LLM 对现有检查的分析（不添加新任务，也不重新调整阈值），请让设计器修改提示词：

```bash
uv run python -m olav --agent audit
> 在 health_full_drift 配置文件中，更新 OSPF_Not_Full 部分的提示词，增加提到：
  LOADING 状态卡住超过 60 秒通常表示 MTU 不匹配。
  当两者都发生时，要求 LLM 将发现的结果与 Interface_State_Drift 进行关联。
```

设计器将执行以下操作：
1. 读取配置文件。
2. 找到指定的部分。
3. 仅更新 `section_prompt` 字段（提供给 LLM 的自然语言指导）。
4. 重新保存配置文件。

适用场景：
- 通过向 LLM 教授关于你环境的上下文来减少噪音。
- 关联相关检查（例如：“如果 OSPF 已断开且接口也已断开，很可能是拔掉了网线”）。
- 澄清什么是真正的问题，什么是预期行为。

---

## 解读报告

```
exports/audit_reports/health_full_drift_2026-03-04_20260304T060427Z.md
```

**执行摘要 (Executive Summary)**（顶部）—— 跨部分的关联分析、事件簇梗概、前 3 项待办事项、健康判定（✅ 健康 / ⚠️ 有风险 / 🔴 性能下降）。

**单项检查部分** —— 每个任务占据一个部分。没有发现异常的检查将打印 `✅ 未检测到异常`，不消耗 LLM 费用。有发现的任务将包含一个发现结果表和 LLM 分析。

**检查后剧本 (Post-Check Playbook)**（底部）—— 优先级 1 = 事件簇命令。优先级 2 = 单个设备发现结果。所有命令都是自包含的 `olav -a ops` 字符串。

---

## 技巧

- **从 `health_full_drift` 开始** —— 它涵盖了所有主要的故障模式。运行几次，看看会触发什么，然后让设计器调整阈值。
- **缩小时间窗口以实现更快运行** —— `3d` 对于大多数运营检查来说已经足够；`7d` 对于趋势和泄漏检测效果更好。
- **在生产环境中启用 `run_incident_clustering: true`** —— 它会将零散的发现结果转换为可操作的故障叙述，并识别拓扑根因。
- **漂移 (Drift) 任务至少需要 2 个快照** —— `BGP_Drift`, `OSPF_Drift`, `Config_Drift`, 和 `STP_Drift` 查询 `raw_diffs`，而这只有在第二次运行快照后才会有数据。
- **`section_prompt` 是提高报告质量的最大杠杆** —— 当要求设计器更新提示词时，请描述在你环境中哪些关联很重要，以及哪些差异可以将噪音与真正的问题区分开。
