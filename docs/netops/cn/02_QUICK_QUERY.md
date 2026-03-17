# Quick Agent 用户指南

**Quick Agent** 是 OLAV 的默认快速查询入口。它专为日常的网络运维查询优化，支持 SQL 查询、CLI 命令执行、知识库搜索、图表导出等功能，采用极简设计以在 1 次迭代内给出答案。

### 🚀 Quick Agent 是快速响应查询引擎

不同于深度分析工具，Quick Agent 在**单层次、快速反馈**的维度上运作：

| 维度 | 能力 | 例子 |
|------|------|------|
| **实时执行** | 直接连接设备执行 show/config 命令，获取当前状态 | "Show interface brief on R2" |
| **历史查询** | 从快照数据库查询历史状态（不涉及复杂关联） | "List all BGP neighbors and their state" |
| **缓存加速** | 频繁查询在 1 秒内返回，避免重复计算 | 同样查询第二次立刻返回 |
| **多源融合** | 同时查询数据库、实时CLI、知识库，一个答案包含多个维度 | "R1的接口，当前+历史+故障案例" |
| **单次交互** | 最多1次迭代就给出答案，不需要反复对话 | 问一句话，直接返回结果 |

这些维度合在一起，使 Quick Agent 成为**快速反馈的日常查询工具**。

---

## 📌 快速开始

### 使用 TUI（文本界面）

```bash
# 进入 OLAV 主目录
cd /home/yhvh/Olav

# 启动 Quick Agent（默认）
olav "show all devices"

# 或显式指定 Quick Agent
olav --agent quick "show ip ospf neighbor"
```

### 使用 Python API

```python
from olav.agents.quick import QuickAgent

agent = QuickAgent()
result = agent.run("What is the IP of device R1?")
print(result)
```

---

## 🎯 Quick Agent 能做什么？

Quick Agent 支持以下四种查询模式：

### 1️⃣ **数据库查询（Query Mode）**
从历史快照中查询设备数据。

**例子：**
```
- "List all devices and their management IPs"
- "Show all core routers in the lab site"
- "What devices are inactive?"
- "Find all interfaces with error counts"
```

**支持的表：**
- `devices` — 设备清单（名称、IP、平台、角色、站点）
- `interfaces` — 接口 IPAM 映射
- `routes` — 路由表
- `bgp_neighbors` — BGP 邻接关系
- `ospf_neighbors` — OSPF 邻接关系
- `topology_links` — 资源拓扑（CDP/LLDP/BGP/OSPF）
- `v_routes_enriched` — 路由表（已解析下一跳设备名）
- `v_bgp_neighbors_enriched` — BGP 邻接表（已解析邻接点设备名）

**性能：** ⚡ 缓存命中 < 1 秒 | 首次查询 < 5 秒

---

### 2️⃣ **实时 CLI 执行（CLI Mode）**
实时连接到设备并执行 show/config 命令。

**例子：**
```
- "Show interface brief on R2"
- "Display BGP summary on R1 and R4"
- "Check OSPF process status"
- "Get running-config | include router bgp"
```

**工作流程：**
1. 系统自动根据设备平台（Cisco、Juniper 等）选择合适的命令
2. 验证命令是否在黑名单中（不允许执行）
3. 连接到设备执行命令
4. 返回原始或解析后的输出

**支持的平台：** Cisco IOS(XE/XR)、Juniper Junos、Arista EOS 等（由 Nornir 定义）

**性能：** 🕐 一般在 5 秒内（取决于设备响应时间）

---

### 3️⃣ **故障分析（Analysis Mode）**
快速诊断网络异常。

**例子：**
```
- "Are all BGP peers up?"
- "Find interface down events in the last 7 days"
- "Which device has the most packet loss?"
- "Check if any routes are blackholed"
- "Find OSPF flap incidents"
```

**分析流程：**
1. **定义范围** — 确定要分析的设备/协议
2. **基线查询** — 从历史快照获取基线指标
3. **当前状态** — 对比当前实时数据
4. **异常检测** — 识别偏离阈值的项
5. **验证** — 用 CLI 命令确认
6. **建议** — 给出调整或改进建议

---

### 4️⃣ **知识库搜索 + Web 搜索**
查询命令用法和外部信息。

**例子：**
```
- "How do I clear a BGP peer?"
- "What does OSPF cost mean?"
- "Show commands for BGP on Cisco"
- "Search external docs for MPLS configuration"
```

**支持：**
- 本地知识库语义搜索（LanceDB）
- 网络搜索（DuckDuckGo）
- 命令查询（搜索所有已知命令）

---

## 🚀 使用场景与示例

### 场景 1：查询设备库存
```bash
$ olav "List all devices in the lab"

# Quick Agent 的回答：
| Name  | Hostname | Platform     | Role           | Site |
|-------|----------|--------------|----------------|------|
| R1    | router1  | cisco_ios    | core           | lab  |
| R2    | router2  | cisco_ios    | edge           | lab  |
| SW1   | switch1  | juniper_evo  | aggregation    | lab  |
```

### 场景 2：检查 BGP 邻接状态
```bash
$ olav "Are all BGP peers up?"

# 回答包含：
- UP 邻接个数和列表
- DOWN 邻接个数（如果有）
- 最后快照时间
- 建议下一步 (如果需要实时确认，使用 `--agent ops`)
```

### 场景 3：实时执行命令
```bash
$ olav "Show interface brief on R1"

# Quick Agent 通过 Nornir 执行 cli 命令：
- Cisco: "show interface brief"
- Juniper: "show interfaces brief"

# 返回设备实际输出
```

### 场景 4：对比配置变化
```bash
$ olav "Find config changes between 2026-03-01 and 2026-03-05 on R1"

# 回答：
- 删除的行数
- 新增的行数
- 具体差异（如路由策略更改）
```

---

## ⚙️ 配置与自定义

### 命令黑名单
某些危险命令不允许执行（写入、删除等）。查看黑名单：

```bash
cat .olav/config/blacklisted_commands.yaml
```

### 修改超时时间
编辑 `api.json`：

```json
{
  "agents": {
    "quick": {
      "cli_timeout_seconds": 30,
      "max_iterations": 1
    }
  }
}
```

### 日志与调试
启用详细日志：

```bash
# 查看 Quick Agent 的执行日志
tail -f .olav/logs/users/$(whoami).log
```

---

## 📊 数据来源与新鲜度

Quick Agent 查询的数据来自两个源：

| 数据源 | 更新频率 | 适用查询 |
|--------|---------|---------|
| **DuckDB 快照** | 定期采集（默认 8 小时一次） | 历史数据、库存、拓扑 |
| **实时 CLI（Nornir）** | 按需执行 | 当前设备状态、实时指标 |

**检查快照新鲜度：**
```bash
$ olav "When was the last snapshot?"

# 回答会告诉你最后采集时间
# 如果超过 24 小时，Quick Agent 会提醒你
```

---

## 🛑 能力边界与限制

### ✅ Quick Agent 能做的

| 功能 | 说明 |
|------|------|
| **SQL 查询** | ✅ 简单 SELECT、JOIN、聚合 |
| **单设备 CLI** | ✅ 单个 show 命令 |
| **命令搜索** | ✅ 按平台和关键词搜索 |
| **数据导出** | ✅ CSV/JSON/Markdown |
| **知识搜索** | ✅ 命令用法、配置示例 |
| **快速诊断** | ✅ 简单故障定位（1-2 步）|

### ❌ Quick Agent 不能做的

| 功能 | 限制原因 | 解决办法 |
|------|---------|---------|
| **深度根本原因分析** | 需要多步假设验证 | 使用 `--agent ops` |
| **跨时间序列分析** | 需要复杂的历史对比 | 使用 `--agent ops` |
| **网络仿真与变更规划** | 需要配置验证和影响分析 | 使用 `--agent ops` |
| **大规模配置推送** | 不支持批量配置下发 | 使用 Nornir 脚本或 `--agent sync` |
| **多步自动修复** | 需要人工审批 | 使用 `--agent ops` 提建议 |
| **复杂流量分析** | 需要 NetFlow 数据或 SNMP | 集成外部工具 |

### ⏱️ 性能指标

| 查询类型 | 典型耗时 | 最大推荐规模 |
|---------|---------|------------|
| SQL 查询（缓存命中） | < 1 秒 | 100K+ 行 |
| SQL 查询（首次查询） | < 5 秒 | 100K+ 行 |
| CLI 单命令 | < 5 秒 | 1 个设备 |
| CLI 多设备并行 | < 5 秒 | 10 个设备 |
| 知识库搜索 | < 1 秒 | 不限 |
| 数据导出 | < 1 秒 | 1M+ 行 |

---

## 🔄 何时升级到 Ops Agent？

Quick Agent 会在以下情况自动建议升级：

```
⚠️ Quick analysis failed or is too complex. For deep troubleshooting and 
automated expert analysis, please try again with: olav --agent ops
```

或者，如果你的查询属于以下类型，**直接使用 Ops Agent**：

```bash
# 深度故障排查
olav --agent ops "Why is BGP down on R1? Check historical logs and suggest fix"

# 变更规划和验证
olav --agent ops "Plan a core switch upgrade from SW1 to SW2"

# 性能分析
olav --agent ops "Analyze BGP convergence time over the last week"
```

---

## 💡 使用技巧

### 1. 使用明确的列标签
**好：**
```
"Show device name, IP address, and platform for all devices"
```

**差：**
```
"Show me the devices"  # 系统不知道你想要哪些字段
```

### 2. 指定时间范围（适用于历史查询）
**好：**
```
"Show interface errors in the last 7 days"
```

**差：**
```
"Show interface errors"  # 使用最近快照，可能过时
```

### 3. 使用设备角色或站点过滤
```
"Show all core routers in site 'lab'"
# 比逐个查询 R1, R2, R3... 更快
```

### 4. 导出结果进行本地分析
```bash
$ olav "Show BGP routes with low local-pref" > bgp_routes.csv

# 然后在 Excel 或其他工具中分析
```

### 5. 组合查询
```bash
# 第一步：查询故障点
olav "Which interfaces have packet loss?"

# 第二步：检查该接口的拓扑
olav "Show topology links connected to interface Ge-0/0/0 on SW1"

# 第三步：审查相端设备的日志（如需要）
olav "Show last error on R1 interface Ge-0/0/1"
```

---

## 🆘 常见问题 FAQ

### Q: 我的查询返回 "No data" 怎么办？

**A:** 可能原因：
1. 该设备/接口在快照中没有数据 → 用 `show devices` 验证
2. 快照太旧 → 检查 `When was the last snapshot?`
3. SQL 语法错误 → 查看日志或重新表述

```bash
# 查看可用的表和列
olav "Show schema of devices table"

# 重新采集快照
olav --agent sync "collect_snapshot"
```

### Q: CLI 命令执行超时？

**A:** 
1. 检查设备是否在线：`olav "Show device R1 status"`
2. 增加超时时间（编辑 `api.json`）
3. 用简化的命令重试（避免大的 config dump）

### Q: 如何检查哪些命令被黑名单阻止？

**A:**
```bash
# 查看黑名单
cat .olav/config/blacklisted_commands.yaml

# 查询某设备允许的命令
olav "Show all commands allowed on Cisco devices"
```

### Q: 快照采集多久一次？能手动触发吗？

**A:**
```bash
# 查看当前采集计划
olav "Show snapshot schedule"

# 手动采集一次
olav --agent sync "collect_snapshot --force"

# 查看采集历史
.olav/logs/snapshot_*.log
```

### Q: 支持管理员帐户吗？

**A:**
Quick Agent 仅读取快照和执行 show 命令。不支持配置更改。如需变更，请：
```bash
# 规划变更（分析影响）
olav --agent ops "Plan config change: ..."

# 执行变更（手动或通过 Nornir）
cd /path/to/nornir/tasks && nornir_cli ...
```

---

## 📞 获取帮助

### 在线资源
- 📖 完整文档：`docs/README.MD`
- 🔧 配置参考：`docs/01_CONFIGURATION.MD`
- 📊 数据库架构：`.olav/workspace/quick/references/SCHEMA_REFERENCE.md`

### 问题排查
1. 查看日志：`.olav/logs/users/<username>.log`
2. 测试 SQL：`.olav/sql_debug.md`
3. 升级到 Ops Agent：`olav --agent ops "<complex_query>"`

### 反馈和建议
```bash
# 报告问题
echo "Problem: ..." > .olav/feedback.txt

# 查看版本和系统信息
olav --version
olav --system-info
```

---

## 📝 更新日志

**v1.1.0**（当前）
- ✅ 新增 4 大查询模式（Query/CLI/Analysis/Search）
- ✅ 支持拓扑感知故障排查
- ✅ 添加日志查询能力（Parquet 支持）
- ✅ 数据导出到 CSV/JSON/Markdown

**v1.0.0**
- ✅ 基础 SQL 查询
- ✅ CLI 命令执行
- ✅ 知识库搜索

---

**最后更新：2026年3月6日**
