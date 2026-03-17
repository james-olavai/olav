# 配置 Agent (Config Agent)

配置 Agent 是 OLAV 的**系统管理和自动化调度中枢**。它管理 LLM API 凭证、设备库存、数据采集调度、快照生命周期、LLM 成本预算等所有运行时参数，并支持通过自然语言调度复杂的网络任务（如审计、同步、仿真）。

### 🎛️ Config Agent 是多维度的系统管理引擎

Config Agent 不是简单的配置读写工具，它在**多个管理维度**上运作：

| 维度 | 能力 | 例子 |
|------|------|------|
| **凭证管理** | 集中管理 LLM API、设备SSH凭证、第三方API密钥 | "更新GPT-4API密钥" |
| **库存同步** | 自动发现/导入设备，维护设备库存的单一真实来源 | "同步思科设备库存到CMDB" |
| **调度自动化** | 用自然语言描述复杂的cron任务，自动生成和部署 | "每天早上6点运行健康审计" |
| **参数调优** | 动态调整LLM模型、请求参数、成本预算 | "切换到Claude-3，设置成本预算$100/月" |
| **状态监控** | 追踪所有后台任务的执行状态、失败告警 | "昨晚的审计任务为什么失败了？" |
| **生命周期管理** | 管理快照保留策略、数据归档、清理过期数据 | "只保留最近30天的快照" |

这些维度结合起来，使 Config Agent 成为**自动化整个系统的控制中心**。

---

## 快速开始

### 使用 CLI

```bash
# 进入 OLAV 主目录
cd /home/yhvh/Olav

# 显示当前配置
olav config

# 通过自然语言修改配置
olav --agent config "更新 LLM 模型为 GPT-4"

# 调度一个周期任务
olav --agent config "每天 06:00 运行健康审计"
```

### 使用 Python API

```python
from olav.agents.config import ConfigAgent

agent = ConfigAgent()

# 查询配置
result = agent.run("What is the current LLM model?")
print(result)

# 调度任务
agent.run("Schedule daily health audit at 06:00 using health_full_drift profile")
```

---

## 配置 Agent 能做什么？

### 1️⃣ **凭证和 API 管理**

Config Agent 管理所有敏感信息的中央存储。

**命令例子：**
```bash
# LLM API 凭证
olav --agent config "Set OpenAI API key to sk-xxxxx"
olav --agent config "Switch to Claude 3 with Anthropic API"

# 设备访问凭证
olav --agent config "Add SSH credentials for lab_site routers"
olav --agent config "Rotate device passwords"

# 成本管理
olav --agent config "Set monthly LLM budget to $500"
olav --agent config "Alert me when LLM costs exceed $400"
```

**支持的集成：**
- OpenAI (GPT-4, GPT-3.5)
- Anthropic (Claude 3)
- 本地 Ollama
- SSH 密钥和密码存储
- 告警 Webhook (Slack, Email)

**性能：** ⚡ 凭证更新立刻生效 | 无需重启

---

### 2️⃣ **设备库存管理**

从外部系统（CMDB、Ansible 清单、NetBox）自动导入和同步设备。

**命令例子：**
```bash
# 自动发现和导入
olav --agent config "Import devices from NetBox, sync every 24 hours"
olav --agent config "Sync Cisco devices from Ansible inventory"

# 手动管理
olav --agent config "Add device R1 (10.0.1.1) with platform junos"
olav --agent config "Mark device SW1 as decommissioned"
olav --agent config "Update R1 management IP to 10.0.1.5"

# 验证
olav --agent config "List all devices by site and platform"
olav --agent config "Show devices with connectivity issues"
```

**库存来源：**
- YAML/CSV 直接导入
- NetBox API 同步
- Ansible inventory 集成
- Nornir 自动发现

**验证机制：** 自动 Ping 检查管理 IP 可达性 | 失败告警通知

---

### 3️⃣ **快照采集调度**

自动化网络数据采集，支持增量采集和完整采集。

**命令例子：**
```bash
# 基础调度
olav --agent config "Schedule daily snapshots at 06:00"
olav --agent config "Run hourly incremental snapshots for core routers only"

# 灵活调度
olav --agent config "Every Monday 22:00 run full snapshot, store results labeled 'weekly-baseline'"
olav --agent config "On the 1st of each month, retain only that snapshot for 90 days"

# 触发式采集
olav --agent config "When CPU exceeds 80% on any device, trigger immediate snapshot"
olav --agent config "On BGP flap events, capture logs and snapshot"

# 验证
olav --agent config "Show snapshot schedule and last execution status"
olav --agent config "What snapshots are stored, how much disk used?"
```

**采集模式：**
- **完整采集** - 所有设备、所有命令模板
- **增量采集** - 仅采集配置变更和故障相关设备
- **按需采集** - 立刻触发，用于故障排查

**存储策略：**
- 按日期分类存储
- 自动压缩和归档
- 生命周期管理（删除过期数据）
- 增量备份支持

---

### 4️⃣ **后台任务调度**

用自然语言描述复杂任务，自动生成 cron 条目和执行流程。

**命令例子：**
```bash
# 审计任务
olav --agent config "Every day 06:00 run comprehensive health audit with health_full_drift"
olav --agent config "Every Friday 20:00 run resilience assessment and email report to ops@company.com"

# 同步任务
olav --agent config "Sync device inventory from NetBox every 12 hours"
olav --agent config "Check configuration drift every 4 hours, alert on changes"

# 数据处理
olav --agent config "Archive snapshots older than 90 days, compress to gz format"
olav --agent config "Generate weekly network topology report, save to exports/"

# 组合任务
olav --agent config "At 23:59 every Sunday: run full health audit, then archive old snapshots, send summary email"
```

**任务执行：**
- 后台运行（cron）
- 日志记录到 `.olav/logs/cron_*.log`
- 失败自动重试
- 并行执行（最多 5 个并发任务）

**监控和告警：**
```bash
olav --agent config "Show all scheduled tasks and their execution history"
olav --agent config "Why did yesterday's audit task fail?"
olav --agent config "Alert me if any cron task fails"
```

---

### 5️⃣ **参数调优和优化**

动态调整系统参数、LLM 行为、数据库设置。

**命令例子：**
```bash
# LLM 配置
olav --agent config "Set LLM temperature to 0.3 for more deterministic responses"
olav --agent config "Increase max_tokens to 4000 for detailed analysis"
olav --agent config "Use GPT-4 Turbo for Ops Agent, keep GPT-3.5 for Quick Agent"

# 性能参数
olav --agent config "Disable caching for real-time queries"
olav --agent config "Set snapshot cache size to 10 GB"
olav --agent config "Increase database query timeout to 30 seconds"

# 审计参数
olav --agent config "Set anomaly detection Z-score threshold to 2.0 (more sensitive)"
olav --agent config "Enable incident clustering in all audit profiles"
olav --agent config "Max 50 findings per audit report"
```

**当前参数展示：**
```bash
olav config
# 显示所有当前设置
```

---

### 6️⃣ **系统健康检查和诊断**

主动监控和诊断系统各层面的健康状态，覆盖基础设施、数据库、网络、LLM服务、自动化任务等。

#### 检查范围

**🖥️ 系统资源检查：**
```bash
# CPU、内存、磁盘
olav --agent config "Full system health report"
olav --agent config "Check disk usage, alert if >80%"
olav --agent config "Show memory usage by agent"
olav --agent config "CPU load trends over last 7 days"
```

**🗄️ 数据库检查：**
```bash
# DuckDB / LanceDB 健康
olav --agent config "Database integrity check"
olav --agent config "Show database size and growth rate"
olav --agent config "Check slow queries and indexes"
olav --agent config "Snapshot table statistics"
olav --agent config "Verify data consistency between tables"
```

**🌐 网络连接检查：**
```bash
# 设备可达性、API连接
olav --agent config "Network connectivity report"
olav --agent config "Which devices are unreachable (haven't been reached in 7 days)"
olav --agent config "Verify LLM API endpoints are reachable"
olav --agent config "Check database host connectivity"
olav --agent config "DNS resolution vs actual device IPs"
```

**🔑 API 和凭证检查：**
```bash
# LLM API、设备SSH、第三方API
olav --agent config "Verify all API credentials are valid"
olav --agent config "Test OpenAI API key, check rate limits"
olav --agent config "Validate SSH credentials for all devices"
olav --agent config "Test NetBox API connectivity"
olav --agent config "Show API key expiration dates"
```

**⚙️ 后台任务检查：**
```bash
# Cron任务、快照采集、同步任务状态
olav --agent config "Show all scheduled tasks and their status"
olav --agent config "List failed tasks in the last 24 hours"
olav --agent config "Any tasks stuck or not responding?"
olav --agent config "Snapshot collection success rate"
olav --agent config "Show tasks that take longest to complete"
```

**💰 成本和配额检查：**
```bash
# LLM成本、API额度、存储配额
olav --agent config "LLM API costs and spending trends"
olav --agent config "Which agent consumes most LLM tokens?"
olav --agent config "API rate limit status and usage"
olav --agent config "Storage usage vs available quota"
olav --agent config "Cost projection for this month"
```

**📊 日志和告警检查：**
```bash
# 错误、警告、异常事件
olav --agent config "Show recent errors and warnings"
olav --agent config "Critical alerts in the last 24 hours"
olav --agent config "Any permission or authentication errors?"
olav --agent config "Syslog analysis - common error patterns"
olav --agent config "Trends: are errors increasing?"
```

#### 生成的健康报告

执行系统健康检查后，Config Agent 生成包含以下部分的报告：

| 报告部分 | 内容 | 告警条件 |
|---------|------|---------|
| **资源摘要** | CPU、内存、磁盘使用百分比 | 磁盘>85% / 内存持续>80% |
| **数据库健康** | 表大小、增长率、慢查询 | 表损坏 / 查询超时 |
| **设备可达性** | 有多少设备无法访问、何时失联 | 核心设备无法访问 |
| **API可用性** | LLM、NetBox、SNMP等所有API状态 | API超时 / 认证失败 |
| **任务执行** | 过去24小时成功率、失败原因 | 成功率<95% / 关键任务失败 |
| **成本趋势** | 当月支出、环比、预测 | 支出超过预算 |
| **告警摘要** | 错误频率、严重程度分布 | Critical告警数>5 |
| **优化建议** | 基于历史数据的改进方向 | 列举Top 5建议 |

#### 自动化健康检查告警

Config Agent 支持自动化健康检查并设置告警规则：

```bash
# 每小时运行一次轻量级检查
olav --agent config "Schedule hourly system health check (light mode)"

# 每天详细检查，发送报告
olav --agent config "Every day 07:00 run full health check, email report to ops@company.com"

# 关键指标变化时立刻告警
olav --agent config "Alert immediately if:
  - Disk usage >90%
  - Database query latency >5 second
  - Any core device unreachable
  - LLM API rate limited"

# 查看告警规则
olav --agent config "Show all active health check alerts"
```

#### 诊断命令（Deep Dive）

调试和分析时的深度诊断命令：

```bash
# 追踪某个设备的问题
olav --agent config "Diagnostic: Device R1 unreachable - trace connectivity, check logs, device status"

# 分析性能问题
olav --agent config "Performance diagnosis: Database queries slow - show slow query log, index stats, table size"

# 追踪任务失败
olav --agent config "Task diagnostic: Why did 2026-03-06 audit fail? Show logs, resource usage, error details"

# API问题诊断
olav --agent config "API diagnostic: OpenAI rate limited - show request history, quota, reset time"

# 存储问题诊断
olav --agent config "Storage diagnostic: Disk almost full - show snapshot sizes, find largest tables, recommend cleanup"
```

---

## 配置 Agent 的工作流

### 流程图

1. **解析请求** → 理解用户的自然语言意图
2. **检查权限** → 验证用户是否可以修改该配置
3. **验证更改** → 测试新配置的有效性（如验证 API 密钥）
4. **人工确认** (HITL) → 对敏感操作要求确认（如删除数据）
5. **执行更新** → 写入磁盘和内存配置
6. **应用更改** → 重新加载相关服务（如无需重启）

### 人工确认（HITL）场景

某些操作需要 explicit 确认：
```bash
olav --agent config "Delete all snapshots older than 90 days"
# 输出：确认提示，要求输入 yes
# 执行删除前再次验证
```

---

## 配置文件位置

| 文件 | 用途 | 权限 |
|------|------|------|
| `.olav/config/api.json` | LLM API 配置、成本预算 | 管理员 |
| `.olav/config/paths.json` | 数据路径配置 | 只读 |
| `.olav/config/logging.yaml` | 日志级别和输出 | 管理员 |
| `~/.olav/personal_config.json` | 用户个人配置（本地覆盖） | 用户 |

### 配置优先级

1. **用户本地** `~/.olav/personal_config.json` （最高优先级）
2. **项目配置** `.olav/config/api.json`
3. **默认值** `src/olav/core/defaults.py`

---

## 常用命令参考

```bash
# 显示配置
olav config
olav --agent config "Show current LLM model and API provider"

# LLM 和 API
olav --agent config "Set LLM model to gpt-4-turbo"
olav --agent config "Add new Anthropic API key"

# 设备管理
olav --agent config "Sync devices from NetBox"
olav --agent config "Add device R1 (10.0.1.1)"
olav --agent config "List all devices by site"

# 调度
olav --agent config "Every day 06:00 run health audit"
olav --agent config "Show all scheduled tasks"

# 快照管理
olav --agent config "Schedule daily snapshots at 06:00"
olav --agent config "Archive snapshots older than 60 days"

# 监控
olav --agent config "System health status"
olav --agent config "LLM costs this month"
olav --agent config "Show failed tasks"
```

---

## 权限和安全

### 用户角色

| 角色 | 权限 | 例子 |
|-----|------|------|
| **查看者** (Viewer) | 只能读配置 | `olav config` |
| **运维** (Operator) | 可调度任务、查看日志 | 调度审计、查看快照 |
| **管理员** (Admin) | 可修改敏感配置 | 更改 API 密钥、更新库存 |

### 敏感操作审核日志

所有配置更改都被记录到 `.olav/logs/config_audit.log`：
```
2026-03-06 12:34:56 | user: alice | action: update_api_key | target: openai | status: success
2026-03-06 12:35:10 | user: bob | action: delete_snapshots | count: 100 | status: confirmed
```

---

## 故障排查

### 问题：调度任务没有执行

**诊断：**
```bash
# 查看任务状态
olav --agent config "Show scheduled tasks and execution history"

# 检查日志
tail -f .olav/logs/cron_*.log
```

**常见原因：**
- Cron 守护程序未运行 → `ps aux | grep cron`
- 磁盘空间不足 → `df -h`
- 权限问题 → 检查 `.olav/` 目录权限

### 问题：配置更改不生效

**诊断：**
```bash
# 强制重新加载配置
olav --agent config "Reload all configurations"

# 验证新设置
olav config
```

### 问题：设备库存导入失败

**诊断：**
```bash
# 检查库存文件格式
olav --agent config "Validate inventory file"

# 测试连接
olav --agent config "Test connectivity to all devices"
```

---

## 技巧

- **先测试再应用** — 对敏感配置，总是先在测试环境尝试
- **定期备份** — 定期备份 `.olav/config/` 目录
- **使用个人配置** — 不同用户使用 `~/.olav/personal_config.json` 覆盖全局设置
- **监控成本** — 定期检查 LLM 成本，及时调整预算或模型选择
- **自动告警** — 设置任务失败告警，及时发现问题

---

**最后更新：2026年3月6日**
