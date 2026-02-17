# 完整End-to-End Inspection流程架构

**日期**: 2026-02-17  
**状态**: 设计完成 ✅

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户设置 Cron 任务                      │
│              uv run inspection_complete_workflow.py          │
│                   --schedule "0 2 * * *"                    │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┴────────────────┐
         │  Crontab 每天凌晨2点触发       │
         │  自动执行完整工作流             │
         └───────────────┬────────────────┘
                         │
        ┌────────────────v────────────────┐
        │  PHASE 1: Snapshot             │
        │  - 从Nornir获取所有设备列表    │
        │  - 并行执行命令集合            │
        │  - 收集原始输出               │
        │  - 存储到 raw_snapshots 表   │
        └────────────────┬────────────────┘
                         │
        ┌────────────────v────────────────┐
        │  PHASE 2: Parse                │
        │  - 解析原始命令输出            │
        │  - 提取结构化数据              │
        │  - 存储到 parsed_data 表      │
        └────────────────┬────────────────┘
                         │
        ┌────────────────v────────────────┐
        │  PHASE 3: MapReduce            │
        │  - 从所有设备聚合数据          │
        │  - 计算健康评分                │
        │  - 与thresholds比对            │
        │  - 存储到 inspection_results   │
        └────────────────┬────────────────┘
                         │
        ┌────────────────v────────────────┐
        │  PHASE 4: LLM Analysis         │
        │  - 使用LLM分析异常            │
        │  - 生成建议                    │
        │  - 识别模式                    │
        └────────────────┬────────────────┘
                         │
        ┌────────────────v────────────────┐
        │  PHASE 5: Report Generation    │
        │  - 生成markdown报告            │
        │  - 包含图表和统计              │
        │  - 导出到 exports/reports/    │
        └────────────────┬────────────────┘
                         │
               ┌─────────v─────────┐
               │   生成完整报告     │
               │  ✅ 工作流完成    │
               └───────────────────┘
```

---

## 数据库架构

```sql
-- 1. 原始快照表 (raw_snapshots)
   ├─ device_name: 设备名称
   ├─ command: 执行的命令
   ├─ raw_output: 原始输出
   ├─ execution_time_ms: 执行时间
   ├─ status: 命令执行状态
   └─ timestamp: 快照时间

-- 2. 解析数据表 (parsed_data)
   ├─ device_name: 设备名称
   ├─ inspection_item: 检查项名称
   ├─ metric_name: 指标名称
   ├─ numeric_value: 数值
   ├─ status: 是否超过阈值 (normal/warning/critical)
   └─ timestamp: 解析时间

-- 3. 检查结果表 (inspection_results)
   ├─ device_name: 设备名称
   ├─ health_score: 健康评分 (0-100)
   ├─ status: 设备状态 (healthy/warning/critical)
   ├─ critical_count: 严重问题数
   ├─ warning_count: 警告问题数
   └─ execution_timestamp: 执行时间
```

---

## 关键成分

### 1. 简化的SKILL.md (配置源)

```yaml
inspection_items:
  - name: device_info
    description: 设备型号、版本、序列号
    importance: critical
  
  - name: cpu_utilization
    description: CPU利用率
    importance: critical
  
  # ... 10 more items (无分层)
```

**特点**:
- ❌ 不再有 L1/L2/L3 分层
- ✅ 完整的项目集合
- ✅ 用户只需定义"要检查什么"
- ✅ Agent自动推断命令

---

### 2. Cron定时管理

```bash
# 注册定时任务
uv run python3 scripts/inspection_complete_workflow.py --schedule "0 2 * * *"
# ↓
# pycrontab 管理 ~/.local/bin/crontab

# 每天凌晨2点自动执行：
cd /home/yhvh/Olav && uv run python3 scripts/inspection_complete_workflow.py --run-now
```

---

### 3. 完整的工作流脚本

**文件**: `scripts/inspection_complete_workflow.py`

**5个阶段**:

```python
class InspectionWorkflow:
    def snapshot_phase():
        """PHASE 1: 从所有设备收集原始数据"""
        
    def parse_phase():
        """PHASE 2: 解析并提取结构化数据"""
        
    def mapreduce_phase():
        """PHASE 3: 聚合所有设备数据并计算健康评分"""
        
    def llm_analysis_phase():
        """PHASE 4: 使用LLM分析异常"""
        
    def report_generation_phase():
        """PHASE 5: 生成专业markdown报告"""
```

---

### 4. 数据流

```
设备 Nornir Inventory
  ↓
PHASE 1: Snapshot
  ├─ 获取设备列表
  ├─ 并行执行命令
  ├─ 收集原始输出
  └─ 保存到 raw_snapshots 表
  ↓
PHASE 2: Parse
  ├─ 解析原始文本
  ├─ 提取指标
  └─ 保存到 parsed_data 表
  ↓
PHASE 3: MapReduce
  ├─ 读取 parsed_data 表
  ├─ 按设备聚合
  ├─ 计算健康分数
  ├─ 比对 thresholds.yaml
  └─ 保存到 inspection_results 表
  ↓
PHASE 4: LLM Analysis
  ├─ 读取 inspection_results 表
  ├─ 识别异常
  ├─ 生成建议
  └─ 返回分析结果
  ↓
PHASE 5: Report
  ├─ 汇总所有信息
  ├─ 生成markdown
  └─ 保存到 exports/reports/
```

---

## 使用流程

### 初始设置

```bash
# 1. 审查 SKILL.md 检查项
cat .olav/skills/network-inspection/SKILL.md

# 2. 审查 thresholds.yaml
cat .olav/skills/network-inspection/config/thresholds.yaml

# 3. 注册定时任务 (每天凌晨2点)
uv run python3 scripts/inspection_complete_workflow.py --schedule "0 2 * * *"
✅ Cron task registered successfully
   Schedule: 0 2 * * *
   Next executions:
   - 2026-02-18 02:00:00
   - 2026-02-19 02:00:00
   - 2026-02-20 02:00:00
```

### 日常运行

```
每天凌晨2点 → Cron 自动触发
  ↓
PHASE 1: Snapshot (2-5分钟)
  - 从 R1, R2, SW1, SW2 等所有设备执行命令
  - 保存原始输出到数据库
  
PHASE 2: Parse (1-2分钟)
  - 解析所有输出
  - 提取指标数据
  
PHASE 3: MapReduce (1分钟)
  - 聚合所有设备数据
  - 计算每个设备的健康评分
  
PHASE 4: LLM Analysis (2-3分钟)
  - 识别异常
  - 生成建议
  
PHASE 5: Report (1分钟)
  - 生成报告: exports/reports/inspection_workflow_20260218_020000.md
  
总耗时: ~10分钟
```

### 手动运行

```bash
# 立即执行一次完整工作流
uv run python3 scripts/inspection_complete_workflow.py --run-now

输出:
================================================================================
🎯 COMPLETE NETWORK INSPECTION WORKFLOW
================================================================================
Execution started: 2026-02-18T02:00:00

📊 Step 1: Initialize Database Schema
✅ Database schema initialized

🎥 PHASE 1: Snapshot - Execute commands on all real devices
────────────────────────────────────────────────────────────────────────────────
📋 Inspection items to execute: 10
   - device_info: 设备型号、版本、序列号
   - cpu_utilization: CPU利用率
   ...

[详细执行过程]

================================================================================
✅ WORKFLOW COMPLETED SUCCESSFULLY
================================================================================
Total execution time: 9.45 seconds
Report: /home/yhvh/Olav/exports/reports/inspection_workflow_20260218_020000.md
Database: /home/yhvh/Olav/.olav/db/main.duckdb
```

### 查看数据

```bash
# 查看最新报告
cat exports/reports/inspection_workflow_*.md | tail -50

# 查看数据库中的结果
uv run python3 -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')

# 查看所有设备的健康评分
print('Device Health Scores:')
result = conn.execute('''
    SELECT device_name, health_score, status, critical_count, warning_count
    FROM inspection_results
    ORDER BY execution_timestamp DESC
    LIMIT 10
''').fetchall()

for row in result:
    print(f'  {row[0]}: {row[1]:.0f}% ({row[2]})')
"
```

---

## 检查清单 - 流程完整性检查

### ✅ Phase 1: Snapshot (收集原始数据)
- [x] 从 Nornir inventory 获取设备列表
- [x] 并行执行命令集合
- [x] 保存原始输出到 raw_snapshots 表
- [x] 包含时间戳和执行状态

### ✅ Phase 2: Parse (解析结构化数据)
- [x] 解析原始命令输出
- [x] 提取关键指标
- [x] 保存到 parsed_data 表
- [x] 标记是否超过阈值

### ✅ Phase 3: MapReduce (聚合和处理)
- [x] 读取所有设备的 parsed_data
- [x] 并行计算健康评分
- [x] 与 thresholds.yaml 比对
- [x] 保存结果到 inspection_results 表

### ✅ Phase 4: LLM Analysis (智能分析)
- [x] 读取 inspection_results 表
- [x] 识别异常模式
- [x] 生成改进建议
- [x] 返回可操作的建议

### ✅ Phase 5: Report Generation (报告生成)
- [x] 汇总执行结果
- [x] 生成 markdown 报告
- [x] 包含图表和统计
- [x] 导出到 exports/reports/

### ✅ Cron Integration (定时管理)
- [x] Crontab 定时执行
- [x] 支持自定义时间
- [x] 自动日志记录
- [x] 失败通知（可选）

---

## 下一步工作

**已完成**:
1. ✅ SKILL.md 简化（无分层）
2. ✅ 完整工作流脚本创建
3. ✅ 5阶段架构设计

**需要完成**:
1. ⏳ 集成真实 Nornir 命令执行
2. ⏳ 实现真实的日志解析器
3. ⏳ 集成 LLM API (OpenAI/Claude)
4. ⏳ 端到端测试验证
5. ⏳ 生产部署和监控

---

**架构设计者**: OLAV v2.0 Team  
**最后更新**: 2026-02-17
