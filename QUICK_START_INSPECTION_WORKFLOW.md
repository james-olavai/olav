# 🚀 完整Inspection工作流 - 快速启动指南

**版本**: v1.0  
**状态**: ✅ 生产就绪 (Production Ready)  
**最后更新**: 2026-02-17

---

## 📚 一句话总结

> 用户通过Cron设置定时任务（例如每天凌晨2点），系统自动从所有设备收集数据、并行处理、LLM分析、生成专业报告，全程数据持久化到DuckDB

---

## ⚡ 5分钟快速启动

### 第1步: 审查配置

```bash
# 查看检查项 (SKILL.md - 已简化，无分层)
cat .olav/skills/network-inspection/SKILL.md | grep -A2 "inspection_items:"

# 查看阈值配置 (自动生成)
cat .olav/skills/network-inspection/config/thresholds.yaml | head -20
```

### 第2步: 注册定时任务

```bash
# 注册为每天凌晨2点执行
uv run python3 scripts/inspection_complete_workflow.py --schedule "0 2 * * *"

输出:
✅ Cron task registered successfully
   Command: cd /home/yhvh/Olav && uv run python3 scripts/inspection_complete_workflow.py --run-now
   Schedule: 0 2 * * *
   
Next executions:
  - 2026-02-18 02:00:00
  - 2026-02-19 02:00:00
  - 2026-02-20 02:00:00
```

### 第3步: 手动测试

```bash
# 立即执行一次完整工作流（测试）
uv run python3 scripts/inspection_complete_workflow.py --run-now

# 完整输出如下：
================================================================================
🎯 COMPLETE NETWORK INSPECTION WORKFLOW
================================================================================

📊 Step 1: Initialize Database Schema
✅ Database schema initialized

🎥 PHASE 1: Snapshot - Execute commands on all real devices
  ▶ R1... ✅
  ▶ R2... ✅
  ▶ SW1... ✅
✓ Snapshot phase completed: 3/3 successful

🔍 PHASE 2: Parse - Extract structured data from snapshots
✓ Parsed data records: [N]

⚙️  PHASE 3: MapReduce - Aggregate and process all device data
✓ MapReduce phase completed:
  - Healthy devices: [X]
  - Warning devices: [Y]
  - Critical devices: [Z]

🤖 PHASE 4: LLM Analysis - Analyzing anomalies...
💡 LLM Recommendations:
  1. ...
  2. ...

📄 PHASE 5: Report Generation
✅ Report generated: exports/reports/inspection_workflow_YYYYMMDD_HHMMSS.md

================================================================================
✅ WORKFLOW COMPLETED SUCCESSFULLY
================================================================================
```

### 第4步: 查看报告

```bash
# 查看最新生成的报告
cat exports/reports/inspection_workflow_$(date +%Y%m%d)_*.md

# 或查看所有报告
ls -lh exports/reports/inspection_workflow_*.md

# 查看数据库中的数据
uv run python3 -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')

print('📊 Devices Health Scores:')
result = conn.execute('''
    SELECT device_name, health_score, status
    FROM inspection_results
    ORDER BY execution_timestamp DESC
    LIMIT 10
''').fetchall()

for device, score, status in result:
    print(f'  {device}: {score:.0f}% ({status})')
"
```

---

## 📋 完整工作流说明

### 一、SKILL配置 (简化版)

**文件**: `.olav/skills/network-inspection/SKILL.md`

```yaml
inspection_items:
  - name: device_info             # 不再有分层 ✅
    description: 设备型号、版本
    importance: critical
  
  - name: cpu_utilization
    description: CPU利用率
    importance: critical
  
  # ... 10 more items (列表式，无分层)
```

**特点**:
- ❌ 无 L1/L2/L3 分层
- ✅ 简洁的检查项列表
- ✅ 用户只需定义"要检查什么"
- ✅ Agent自动推断命令

### 二、Cron系统 (自动执行)

**配置**:
```bash
# 用户一次性注册
uv run python3 scripts/inspection_complete_workflow.py --schedule "0 2 * * *"

# 系统自动在：~/.local/bin/crontab 中写入
# 0 2 * * * cd /home/yhvh/Olav && uv run python3 scripts/inspection_complete_workflow.py --run-now
```

**执行**:
```
每天凌晨2:00 UTC+8
  ↓
Cron自动触发
  ↓
执行5阶段工作流
  ↓
报告自动生成: exports/reports/
```

### 三、5阶段工作流

```
┌─ PHASE 1: Snapshot
│  ├─ 从Nornir inventory获取设备列表
│  ├─ 并行执行命令（基于SKILL.md中的检查项）
│  ├─ 收集原始输出
│  └─ 保存到 raw_snapshots 表
│
├─ PHASE 2: Parse
│  ├─ 读取 raw_snapshots 表
│  ├─ 解析命令输出
│  ├─ 提取结构化指标
│  └─ 保存到 parsed_data 表
│
├─ PHASE 3: MapReduce
│  ├─ 读取所有设备的 parsed_data
│  ├─ 并行计算健康评分
│  ├─ 与 thresholds.yaml 比对
│  └─ 保存结果到 inspection_results 表
│
├─ PHASE 4: LLM Analysis
│  ├─ 读取 inspection_results 表
│  ├─ 识别异常模式
│  ├─ 调用LLM生成分析
│  └─ 返回可操作的建议
│
└─ PHASE 5: Report Generation
   ├─ 汇总所有信息
   ├─ 生成Markdown报告
   ├─ 包含图表、统计、建议
   └─ 导出到 exports/reports/
```

### 四、数据库架构

```
.olav/db/main.duckdb (DuckDB数据库)
│
├─ raw_snapshots (原始数据)
│  ├─ device_name: 设备名
│  ├─ command: 执行的命令
│  ├─ raw_output: 原始输出
│  ├─ execution_time_ms: 执行时间
│  └─ status: 执行状态
│
├─ parsed_data (解析数据)
│  ├─ device_name: 设备名
│  ├─ inspection_item: 检查项
│  ├─ metric_name: 指标名
│  ├─ numeric_value: 数值
│  └─ status: 是否超过阈值
│
└─ inspection_results (最终结果)
   ├─ device_name: 设备名
   ├─ health_score: 健康评分 (0-100)
   ├─ status: 设备状态 (healthy/warning/critical)
   ├─ critical_count: 严重问题数
   ├─ warning_count: 警告问题数
   └─ execution_timestamp: 执行时间
```

---

## 🔧 常见操作

### 操作1: 查看已注册的任务

```bash
uv run python3 scripts/inspection_complete_workflow.py --list-tasks

输出:
📋 Scheduled Inspection Tasks:
────────────────────────────────────────────────────────
Task: OLAV daily inspection workflow
  Schedule: 0 2 * * *
  Command: cd /home/yhvh/Olav && uv run python3 scripts/inspection_complete_workflow.py --run-now
```

### 操作2: 修改检查项

```bash
# 编辑SKILL.md添加新项
vi .olav/skills/network-inspection/SKILL.md

# 添加:
# - name: stp_status
#   description: STP拓扑状态
#   importance: warning

# 下次运行时会自动包含新项
```

### 操作3: 修改阈值

```bash
# 编辑阈值配置
vi .olav/skills/network-inspection/config/thresholds.yaml

# 例如改变CPU警告阈值
# cpu_utilization:
#   warning: 60  # 改为60%
#   critical: 85 # 改为85%

# 下次运行时会自动应用
```

### 操作4: 手动运行（不等待Cron）

```bash
# 立即执行
uv run python3 scripts/inspection_complete_workflow.py --run-now

# 执行约10秒钟，生成报告
```

### 操作5: 查询历史数据

```bash
# 查看最近10次执行的结果
uv run python3 -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')

# 查看原始快照
print('Latest Snapshots:')
result = conn.execute('''
    SELECT device_name, command, status, execution_time_ms
    FROM raw_snapshots
    ORDER BY timestamp DESC
    LIMIT 10
''').fetchall()
for row in result:
    print(f'  Device: {row[0]}, Cmd: {row[1]}, Time: {row[3]}ms')

# 查看设备健康评分
print('\nDevice Health Scores:')
result = conn.execute('''
    SELECT device_name, health_score, status, critical_count, warning_count
    FROM inspection_results
    ORDER BY execution_timestamp DESC
    LIMIT 10
''').fetchall()
for device, score, status, crit, warn in result:
    print(f'  {device}: {score:.0f}% ({status}) - {crit} critical, {warn} warnings')
"
```

---

## 📊 工作流执行示例

### 场景: 完整执行一次

```bash
$ uv run python3 scripts/inspection_complete_workflow.py --run-now

================================================================================
🎯 COMPLETE NETWORK INSPECTION WORKFLOW
================================================================================
Execution started: 2026-02-17T15:21:44.706295

📊 Step 1: Initialize Database Schema
────────────────────────────────────────────────────────────────────────────────
✅ Database schema initialized

🎥 PHASE 1: Snapshot - Execute commands on all real devices
────────────────────────────────────────────────────────────────────────────────
📋 Inspection items to execute: 5
   - device_info: 设备型号、版本序列号
   - cpu_utilization: CPU利用率
   - memory_utilization: 内存利用率
   - interface_status: 接口状态和协议
   - ospf_neighbors: OSPF邻居状态

📝 Taking snapshots from 3 devices...
  ▶ R1... ✅
  ▶ R2... ✅
  ▶ SW1... ✅

✓ Snapshot phase completed:
  - Successful: 3/3
  - Total commands executed: 15

🔍 PHASE 2: Parse - Extract structured data from snapshots
────────────────────────────────────────────────────────────────────────────────
📊 Raw snapshots in database: 3
✓ Parsed data records: 3

⚙️  PHASE 3: MapReduce - Aggregate and process all device data
────────────────────────────────────────────────────────────────────────────────
📋 Processing 3 devices...
  ✓ R1: 95% - healthy
  ✓ R2: 92% - healthy
  ✓ SW1: 88% - warning

✓ MapReduce phase completed:
  - Healthy devices: 2
  - Warning devices: 1
  - Critical devices: 0

🤖 PHASE 4: LLM Analysis - Analyzing anomalies and generating recommendations
────────────────────────────────────────────────────────────────────────────────

📋 Analysis Input:
Network Inspection Results Summary:
- Total Devices: 3
- Healthy: 2
- Warning: 1
- Critical: 0
...

💡 LLM Recommendations:
  1. Monitor CPU utilization trends on critical devices
  2. Review interface error rates on SW1 - consider updating firmware
  3. Verify OSPF neighbor relationships across core network
  4. Schedule maintenance for SW1 (warning status)

📄 PHASE 5: Report Generation - Creating professional markdown report
────────────────────────────────────────────────────────────────────────────────
✅ Report generated: exports/reports/inspection_workflow_20260217_152145.md

================================================================================
✅ WORKFLOW COMPLETED SUCCESSFULLY
================================================================================
Total execution time: 9.45 seconds
Report: /home/yhvh/Olav/exports/reports/inspection_workflow_20260217_152145.md
Database: /home/yhvh/Olav/.olav/db/main.duckdb
```

---

## ✅ 完整性检查清单

### 流程
- [x] Cron定时管理
- [x] Snapshot收集
- [x] 数据入库
- [x] MapReduce处理
- [x] LLM分析
- [x] 报告生成

### 数据管理
- [x] 三层表结构 (raw/parsed/aggregated)
- [x] 完整的执行历史
- [x] 时间戳审计
- [x] 可查询API

### 用户体验
- [x] 简化的SKILL配置
- [x] 一命令注册Cron
- [x] 自动化执行
- [x] 专业报告输出

---

## 🎓 架构文档

详细说明请参考:
- [PHASE9_COMPLETE_WORKFLOW_ARCHITECTURE.md](PHASE9_COMPLETE_WORKFLOW_ARCHITECTURE.md) - 完整架构设计
- [PHASE9_COMPLETE_WORKFLOW_VERIFICATION.md](PHASE9_COMPLETE_WORKFLOW_VERIFICATION.md) - 验证清单

---

**立即开始**:
```bash
uv run python3 scripts/inspection_complete_workflow.py --schedule "0 2 * * *"
```

**系统已就绪！** 🚀
