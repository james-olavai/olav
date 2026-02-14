# .olav/ 目录重构分析报告

**日期**: 2026-02-14  
**版本**: v1.0  
**目标**: 对齐 DEEPAGENTS_SIMPLIFICATION_PLAN.md 第 7 章设计

---

## 📋 目录

1. [当前目录结构分析](#1-当前目录结构分析)
2. [需要删除的内容](#2-需要删除的内容)
3. [需要保留并优化的内容](#3-需要保留并优化的内容)
4. [Tools 改造计划](#4-tools-改造计划)
5. [新增内容](#5-新增内容)
6. [Cron 机制设计](#6-cron-机制设计)
7. [实施步骤](#7-实施步骤)

---

## 1. 当前目录结构分析

### 1.1 现有结构

```
.olav/ (总计 70.4M)
├── OLAV.md (4K)                    # SubAgent 注册表
├── settings.json (4K)              # 用户配置
├── settings-*.json (8K)            # 配置示例文件
├── .last_thread_id                 # 会话 ID 追踪
│
├── shared/                         # 212K - 共享工具
│   └── tools/                      # 6 个 Python 工具
│       ├── smart_sql_query.py      # ✅ 保留并改造
│       ├── nornir_execute.py       # ✅ 保留并改造
│       ├── list_devices.py         # ✅ 保留并改造
│       ├── query_database.py       # ❌ 删除（被 smart_sql_query 替代）
│       ├── inspect_schema.py       # ❌ 删除（被 smart_sql_query 替代）
│       └── discover_data.py        # ❌ 删除（被 smart_sql_query 替代）
│
├── skills/                         # 22M - Skill 配置
│   ├── network-query/
│   ├── network-cli/
│   ├── network-expert/
│   ├── network-inspection/
│   ├── network-snapshot/
│   ├── olav-admin/
│   ├── olav-guard/
│   ├── olav-orchestrator/
│   ├── orchestrator/              # ❌ 删除（重复）
│   ├── command_learner/           # ⚠️ 评估（未完成功能）
│   └── shared/                    # ✅ 保留
│
├── db/                             # 47M - 数据库文件
│   ├── main.duckdb (12K)          # ✅ 保留
│   └── network.duckdb (47M)       # ❌ 合并到 main.duckdb
│
├── cache/                          # 100K - LLM 缓存
│   ├── olav_cache.db (空)         # ❌ 删除（未使用）
│   └── *.json (15 个缓存文件)     # ❌ 删除（手动缓存文件）
│
├── knowledge/                      # 96K - 知识库
│   ├── index.json                 # ✅ 保留
│   ├── ospf_protocol.md           # ✅ 保留
│   └── */                         # ✅ 保留
│
├── tasks/                          # 920K - 任务管理
│   ├── scheduled/ (175 个 YAML)   # ⚠️ 评估（可能是测试数据）
│   ├── archived/
│   ├── results/
│   ├── audit/
│   └── dead_letter_queue/
│
├── workflows/                      # 12K - 工作流定义
│   └── daily-run.md               # ✅ 保留并改造（inspection cron）
│
├── cron/                           # 4K - Cron 调度
│   └── (空目录)                   # ❌ 删除
│
├── config/                         # 52K - 配置文件
│   └── (需检查内容)               # ⚠️ 评估
│
└── templates/                      # 108K - TextFSM 模板
    ├── ntc_templates/             # ✅ 保留
    └── custom/                    # ✅ 保留
```

### 1.2 目标结构（来自设计文档）

```
.olav/
├── AGENTS.md                       # 新增 - 持久化记忆
├── settings.json                   # 保留 - 用户配置
│
├── tools/                          # 重构 - 3 个核心工具
│   ├── __init__.py
│   ├── database.py                # smart_sql_query
│   └── network.py                 # nornir_execute, list_devices
│
├── skills/                         # 简化 - 保留核心 Skills
│   ├── network-query/
│   ├── network-cli/
│   ├── network-expert/
│   ├── network-inspection/
│   ├── network-snapshot/
│   └── shared/
│
├── db/                             # 规范 - 3 个数据库
│   ├── main.duckdb                # 业务数据
│   ├── agent.duckdb               # Agent runtime（新增）
│   └── llm_cache.db               # LLM 缓存（新增）
│
├── backups/                        # 新增 - 备份目录
├── logs/                           # 新增 - 日志目录
└── templates/                      # 保留 - TextFSM 模板
```

---

## 2. 需要删除的内容

### 2.1 立即删除（无用数据）

```bash
# 1. 手动缓存文件（已被 SemanticCacheMiddleware 替代）
rm -rf .olav/cache/

# 2. 空的 cron 目录
rm -rf .olav/cron/

# 3. 重复的 orchestrator skill
rm -rf .olav/skills/orchestrator/

# 4. 配置示例文件（移到文档）
rm .olav/settings-feature-flags-example.json
rm .olav/settings-guard-example.json

# 5. 临时会话文件
rm .olav/.last_thread_id
```

**预计释放空间**: ~100K

### 2.2 评估后删除（需确认）

#### tasks/ 目录（920K）

```bash
# 检查是否为测试数据
ls -l .olav/tasks/scheduled/ | wc -l  # 175 个文件

# 如果是测试数据，全部删除
rm -rf .olav/tasks/
```

**理由**:
- 175 个 scheduled tasks（大多数是测试用的 `SELECT 1` 查询）
- 新架构不需要 YAML 任务持久化（使用 LangGraph checkpoint）
- Cron 任务改用 workflow 定义（见第 6 章）

#### config/ 目录（52K）

```bash
# 检查内容
ls -la .olav/config/

# 如果是旧版配置文件，考虑迁移到 settings.json
```

### 2.3 工具合并删除（被 smart_sql_query 替代）

```bash
# 这 3 个工具的功能已经集成到 smart_sql_query.py
rm .olav/shared/tools/query_database.py      # 239 行
rm .olav/shared/tools/inspect_schema.py      # 182 行
rm .olav/shared/tools/discover_data.py       # 196 行
```

**理由**:
- `smart_sql_query.py` 已实现自动 schema 探索
- LangChain SQL Agent 模式：一个工具处理完整 SQL 工作流
- 减少 LLM 的工具选择复杂度

**预计减少**: ~617 行代码

---

## 3. 需要保留并优化的内容

### 3.1 OLAV.md → AGENTS.md（迁移）

**当前**: `.olav/OLAV.md`（126 行）
- SubAgent 注册表（YAML frontmatter）
- 架构说明

**目标**: `.olav/AGENTS.md`（DeepAgents 标准格式）
- 持久化记忆（用户偏好、常用别名）
- 历史见解（过去的重要发现）
- 系统级配置（不是 YAML SubAgent 定义）

**迁移脚本**:
```bash
# 提取有用的元数据
cat .olav/OLAV.md | grep -A 5 "Architecture" > .olav/AGENTS.md

# 添加记忆模板
cat >> .olav/AGENTS.md <<'EOF'

## User Preferences

- Preferred IP range notation: CIDR
- Default export format: CSV
- Timezone: Asia/Shanghai

## Common Aliases

- "核心设备" → role='core'
- "边界路由器" → role='edge'

## Historical Insights

- 2026-02-10: OSPF area 0 有频繁 neighbor flap（已修复）
- 2026-02-12: BGP peer 10.1.1.1 timeout 需要调优（待处理）
EOF

# 删除旧文件
rm .olav/OLAV.md
```

### 3.2 Skills 保留清单

#### 保留的 Skills（7 个）

```
✅ network-query/          # 数据库查询
✅ network-cli/            # CLI 命令执行
✅ network-expert/         # 故障诊断专家
✅ network-inspection/     # 健康检查
✅ network-snapshot/       # 数据采集
✅ olav-admin/             # 系统管理（简化，见下）
✅ shared/                 # 共享资源
```

#### 删除的 Skills（3 个）

```
❌ olav-guard/            # Guard 机制已废弃
❌ olav-orchestrator/     # 单 Agent 架构不需要
❌ orchestrator/          # 重复目录
```

#### 简化的 Skills（1 个）

```
⚙️ olav-admin/            # 保留并简化
                          # 现有功能：backup/restore/config/skill 管理
                          # 简化方向：提供 CLI 命令包装（olav admin backup）
                          # 但保留 skill 以支持对话式管理
```

#### 评估的 Skills（1 个）

```
⚠️ command_learner/       # TextFSM 学习器（功能未完成）
                          # 决策：保留框架，改为 /learn 命令触发
```

### 3.3 数据库文件优化

**当前**:
```
.olav/db/
├── main.duckdb (12K)      # 主数据库
└── network.duckdb (47M)   # 网络数据
```

**问题**: 数据分散在两个库，需要 ATTACH 语句

**目标**:
```
.olav/db/
├── main.duckdb            # 合并后的业务数据（~47M）
├── agent.duckdb           # Agent runtime（新增）
└── llm_cache.db           # LLM 缓存（新增）
```

**合并脚本**:
```bash
# 备份
cp .olav/db/network.duckdb .olav/db/network.duckdb.backup

# 使用 DuckDB 合并数据
uv run python -c "
import duckdb

# 连接 main.duckdb
conn = duckdb.connect('.olav/db/main.duckdb')

# 附加 network.duckdb
conn.execute('ATTACH \".olav/db/network.duckdb\" AS network_db')

# 获取 network.duckdb 的所有表
tables = conn.execute('SELECT table_name FROM network_db.information_schema.tables WHERE table_schema=\\'main\\'').fetchall()

# 复制表到 main.duckdb
for (table,) in tables:
    print(f'Copying {table}...')
    conn.execute(f'CREATE TABLE {table} AS SELECT * FROM network_db.{table}')

# 验证
result = conn.execute('SELECT COUNT(*) FROM devices').fetchone()
print(f'Devices count: {result[0]}')

conn.close()
"

# 验证后删除旧库
rm .olav/db/network.duckdb
```

### 3.4 Knowledge/ 目录保留

```
.olav/knowledge/           # ✅ 完整保留
├── index.json            # 知识索引
├── ospf_protocol.md      # OSPF 知识
├── system/               # 系统知识
├── solutions/            # 解决方案
└── test_cases/           # 测试案例
```

**优化**: 添加 README.md 说明知识库使用方式

### 3.5 Templates/ 目录保留

```
.olav/templates/          # ✅ 完整保留
├── ntc_templates/        # NTC 官方模板
└── custom/               # 用户自定义模板
```

**优化**: 无需修改，当前结构已最优

---

## 4. Tools 改造计划

### 4.1 目录结构调整

**当前**: `.olav/shared/tools/`  
**目标**: `.olav/tools/`

```bash
# 移动到顶层（符合 MCP 标准）
mv .olav/shared/tools .olav/tools

# 删除空目录
rmdir .olav/shared
```

### 4.2 核心工具改造（3 个文件）

#### Tool 1: database.py（改造 smart_sql_query.py）

**当前文件**: `.olav/shared/tools/smart_sql_query.py` (312 行)

**改造点**:

1. **移除项目依赖路径查找**（简化导入）
   ```python
   # ❌ 删除这段（不需要动态路径）
   def _find_project_root():
       p = Path(__file__).resolve().parent
       while p != p.parent:
           if (p / "pyproject.toml").exists():
               return p
           p = p.parent
       return Path.cwd()
   
   sys.path.insert(0, str(_find_project_root() / "src"))
   
   # ✅ 改为直接导入（agent.py 已添加路径）
   from olav.lib.data_gateway import query_database as db_query
   ```

2. **添加导出功能**（CSV/JSON export）
   ```python
   class SmartSQLInput(BaseModel):
       query: str = Field(default="", description="Natural language query")
       sql: str = Field(default="", description="Direct SQL query")
       export_format: str | None = Field(
           default=None,
           description="Export format: csv | json"
       )
       export_path: str | None = Field(
           default=None,
           description="Export file path (default: exports/{timestamp}.{format})"
       )
   ```

3. **统一数据库连接**（去掉 ATTACH 逻辑）
   ```python
   # ❌ 删除 ATTACH network.duckdb（数据已合并）
   
   # ✅ 简化为单一连接
   conn = duckdb.connect('.olav/db/main.duckdb', read_only=False)
   ```

4. **重命名文件**
   ```bash
   mv .olav/tools/smart_sql_query.py .olav/tools/database.py
   ```

**预期代码量**: ~280 行（减少 32 行）

#### Tool 2: network.py（合并 2 个文件）

**当前文件**:
- `.olav/shared/tools/nornir_execute.py` (244 行)
- `.olav/shared/tools/list_devices.py` (203 行)

**合并策略**:

```python
# .olav/tools/network.py

from langchain_core.tools import tool

@tool
def nornir_execute(device: str, command: str, timeout: int = 30) -> dict:
    """Execute CLI command on network device.
    
    Args:
        device: Target device hostname
        command: CLI command to execute
        timeout: Command timeout in seconds (default: 30)
    
    Returns:
        {
            "output": "Command output",
            "device": "device_hostname",
            "command": "executed_command",
            "status": "success | failed",
            "error": "Error message if failed"
        }
    """
    # 实现代码（从 nornir_execute.py 复制）
    pass


@tool
def list_devices(role: str | None = None, site: str | None = None) -> dict:
    """List network devices from Nornir inventory.
    
    Args:
        role: Filter by device role (optional)
        site: Filter by site/location (optional)
    
    Returns:
        {
            "devices": [
                {"hostname": "R1", "ip": "10.1.1.1", "role": "core", ...},
                ...
            ],
            "count": 6,
            "status": "success"
        }
    """
    # 实现代码（从 list_devices.py 复制）
    pass
```

**优化点**:
1. 删除重复的 `_find_project_root()` 函数
2. 共享导入语句（`from olav.tools.network_executor import ...`）
3. 统一错误处理和返回格式

**预期代码量**: ~320 行（减少 127 行）

#### Tool 3: __init__.py（新增）

```python
# .olav/tools/__init__.py
"""
OLAV Network Tools - Core tools for network operations.

Usage:
    from database import smart_sql_query
    from network import nornir_execute, list_devices
"""

__all__ = [
    "smart_sql_query",
    "nornir_execute", 
    "list_devices",
]
```

### 4.3 Tools 对比总结

| 维度 | 之前 | 之后 | 变化 |
|------|------|------|------|
| **文件数** | 6 个 | 3 个 | -50% |
| **代码行数** | ~1,376 行 | ~620 行 | **-55%** |
| **功能** | 分散 | 集中 | 更清晰 |
| **依赖** | 复杂路径查找 | 简单导入 | 更简洁 |
| **MCP 标准** | 不符合 | 符合 | ✅ |

---

## 5. 新增内容

### 5.1 backups/ 目录

```bash
mkdir -p .olav/backups

# 创建备份脚本触发的占位符
cat > .olav/backups/README.md <<'EOF'
# Backups Directory

This directory stores OLAV configuration backups created by `/admin backup` command.

## Backup Format

```
YYYY-MM-DD_HHMMSS.tar.gz
```

## Contents

- .olav/AGENTS.md
- .olav/settings.json
- .olav/skills/
- .olav/db/main.duckdb

## Restore

```bash
/admin restore YYYY-MM-DD_HHMMSS.tar.gz
```
EOF
```

### 5.2 logs/ 目录

```bash
mkdir -p .olav/logs

# 创建日志配置说明
cat > .olav/logs/README.md <<'EOF'
# Logs Directory

Centralized logging for OLAV operations.

## Log Files

- `agent.log` - Agent runtime logs
- `cli_batch_YYYYMMDD_HHMMSS/` - CLI batch execution logs
- `netbox_sync_YYYYMMDD.log` - NetBox sync logs
- `inspection_YYYYMMDD.log` - Daily inspection logs

## Configuration

Log rotation: 7 days  
Max size: 100MB per file
EOF
```

### 5.3 agent.duckdb（Agent runtime）

```bash
# 创建 agent runtime 数据库
uv run python -c "
import duckdb

conn = duckdb.connect('.olav/db/agent.duckdb')

# LangGraph checkpoint 表（由 DuckDBSaver 自动创建）
# 这里只需创建空库，DuckDBSaver 会自动初始化 schema

conn.close()
print('Created: .olav/db/agent.duckdb')
"
```

### 5.4 llm_cache.db（LLM 缓存）

```bash
# 创建 LLM 缓存数据库
uv run python -c "
import sqlite3

conn = sqlite3.connect('.olav/db/llm_cache.db')

# SemanticCacheMiddleware 会自动创建表结构
# 这里只创建空库

conn.close()
print('Created: .olav/db/llm_cache.db')
"
```

---

## 6. Cron 机制设计

### 6.1 当前 Cron 实现（分析）

**现有文件**:
- `.olav/workflows/daily-run.md` (170 行)
- `.olav/tasks/scheduled/*.yaml` (175 个文件)

**当前机制问题**:
1. ❌ YAML 任务文件与 workflow 定义分离
2. ❌ 没有实际的 cron 调度器（空 `.olav/cron/` 目录）
3. ❌ 任务状态管理复杂（created/running/completed）
4. ❌ 测试数据污染（`SELECT 1` 查询充斥 scheduled/）

### 6.2 新 Cron 机制设计

#### 设计原则

1. **Workflow 即配置** - 单一 Markdown 文件定义整个流程
2. **Agent 执行** - Cron 触发 Agent，由 Agent 调用 tools
3. **状态持久化** - 使用 LangGraph checkpoint（不需要 YAML 文件）
4. **简单调度** - 使用系统 cron 或 Python APScheduler

#### 架构设计

```
┌─────────────────────────────────────────────┐
│   System Cron / APScheduler                 │
│   0 6 * * * /usr/bin/uv run olav inspect    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   OLAV CLI: olav inspect                    │
│   - Load workflow: .olav/workflows/daily-   │
│     inspection.md                            │
│   - Create Agent with network-inspection   │
│     skill                                    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Agent (with TodoListMiddleware)          │
│   1. Read workflow frontmatter (schedule,  │
│      stages)                                │
│   2. Create todo list from stages          │
│   3. Execute each stage sequentially       │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Stage Execution (Tools)                  │
│   Stage 1: sync → nornir_execute()         │
│   Stage 2: topology → nornir_execute()     │
│   Stage 3: inspect → smart_sql_query()     │
│   Stage 4: logs → smart_sql_query()        │
│   Stage 5: report → LLM Reduce             │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Output                                    │
│   - exports/reports/snapshots/YYYYMMDD.md  │
│   - .olav/logs/inspection_YYYYMMDD.log     │
│   - LangGraph checkpoint (agent.duckdb)    │
└─────────────────────────────────────────────┘
```

#### Workflow 定义格式

```markdown
---
name: daily-inspection
version: 2.0.0
description: Daily network health inspection
schedule: "0 6 * * *"
skill: network-inspection
timeout: 30m
enabled: true
---

# Daily Network Inspection Workflow

## Description

Comprehensive daily health check with Map-Reduce analysis.

## Stages

### Stage 1: sync (Tool)
- Call: nornir_execute(command="show running-config")
- Output: data/sync/{date}/raw/

### Stage 2: inspect (Tool + LLM Map)
- Call: nornir_execute() for each device
- LLM: Independent judgment per device
- Output: data/sync/{date}/map/inspect/*.json

### Stage 3: report (LLM Reduce)
- Input: Anomaly summary from Stage 2
- LLM: Global correlation analysis
- Output: exports/reports/snapshots/{date}.md

## Success Criteria

- All devices reachable
- No critical errors
- Report generated
```

#### Python 实现（简化版）

```python
# src/olav/cli/cron.py

import yaml
from pathlib import Path
from datetime import datetime

def run_workflow(workflow_name: str):
    """Execute workflow from .olav/workflows/{name}.md"""
    
    # 1. Load workflow definition
    workflow_path = Path(f".olav/workflows/{workflow_name}.md")
    content = workflow_path.read_text()
    
    # Parse frontmatter
    frontmatter = yaml.safe_load(
        content.split("---")[1]
    )
    
    if not frontmatter.get("enabled", True):
        print(f"Workflow {workflow_name} is disabled")
        return
    
    # 2. Create Agent with specified skill
    from olav.agents.agent import create_olav_agent
    
    agent = create_olav_agent()
    
    # 3. Execute workflow
    print(f"Starting workflow: {workflow_name}")
    print(f"Schedule: {frontmatter.get('schedule')}")
    
    # Agent 会读取 workflow Markdown 内容作为 system prompt
    result = agent.invoke({
        "messages": [
            {"role": "system", "content": content},
            {"role": "user", "content": f"Execute {workflow_name} workflow"}
        ]
    })
    
    # 4. Log results
    log_path = Path(f".olav/logs/{workflow_name}_{datetime.now():%Y%m%d}.log")
    log_path.write_text(result["output"])
    
    print(f"Workflow completed. Log: {log_path}")


# CLI command
@click.command()
@click.argument("workflow")
def inspect(workflow: str = "daily-inspection"):
    """Run network inspection workflow"""
    run_workflow(workflow)
```

#### Cron 调度配置

**推荐方案: 系统 Cron + 简单脚本**（生产和开发都适用）

```bash
# 1. 创建执行脚本
cat > /home/yhvh/Olav/scripts/daily_inspection.sh <<'EOF'
#!/bin/bash
# Daily network inspection workflow
# Auto-generated by OLAV

set -e

cd "$(dirname "$0")/.."

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting daily inspection..."

# 执行 inspection workflow
/usr/bin/uv run olav inspect daily-inspection

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Inspection completed."
EOF

chmod +x /home/yhvh/Olav/scripts/daily_inspection.sh

# 2. 测试执行
./scripts/daily_inspection.sh

# 3. 安装 cron 任务
crontab -e

# 添加（每天 06:00 执行）
0 6 * * * /home/yhvh/Olav/scripts/daily_inspection.sh >> /home/yhvh/Olav/.olav/logs/cron.log 2>&1

# 或使用变量（更灵活）
OLAV_HOME=/home/yhvh/Olav
0 6 * * * $OLAV_HOME/scripts/daily_inspection.sh >> $OLAV_HOME/.olav/logs/cron.log 2>&1
```

**方案优势**:
- ✅ **简单可靠** - 系统 cron 久经考验
- ✅ **无额外依赖** - 不需要 APScheduler
- ✅ **易于调试** - 直接执行脚本测试
- ✅ **标准运维** - 符合传统运维习惯
- ✅ **日志清晰** - 输出重定向到 cron.log

~~**方案 B: APScheduler**（不推荐 - 过度工程化）~~

```python
# src/olav/cli/scheduler.py

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from pathlib import Path
import yaml

def load_workflows():
    """Load all workflows from .olav/workflows/"""
    workflows = []
    
    for workflow_file in Path(".olav/workflows").glob("*.md"):
        content = workflow_file.read_text()
        frontmatter = yaml.safe_load(content.split("---")[1])
        
        if not frontmatter.get("enabled", True):
            continue
        
        workflows.append({
            "name": frontmatter["name"],
            "schedule": frontmatter.get("schedule"),
            "file": workflow_file.stem,
        })
    
    return workflows


def start_scheduler():
    """Start APScheduler with all workflows"""
    scheduler = BlockingScheduler()
    
    # Load workflows
    workflows = load_workflows()
    
    for workflow in workflows:
        if not workflow["schedule"]:
            continue
        
        print(f"Scheduling: {workflow['name']} ({workflow['schedule']})")
        
        scheduler.add_job(
            run_workflow,
            trigger=CronTrigger.from_crontab(workflow["schedule"]),
            args=[workflow["file"]],
            id=workflow["name"],
        )
    
    # Start scheduler
    print("Scheduler started. Press Ctrl+C to stop.")
    scheduler.start()


# CLI command
@click.command()
def scheduler():
    """Start OLAV workflow scheduler"""
    start_scheduler()
```

**使用方式**:
```bash
# 后台运行 scheduler
uv run olav scheduler &

# 查看状态
ps aux | grep "olav scheduler"

# 停止
pkill -f "olav scheduler"
```

### 6.3 Inspection Workflow 完整示例

**文件**: `.olav/workflows/daily-inspection.md`

```markdown
---
name: daily-inspection
version: 2.0.0
description: Daily network health inspection with Map-Reduce analysis
schedule: "0 6 * * *"
skill: network-inspection
timeout: 30m
enabled: true
notification:
  email: network-ops@example.com
  webhook: https://slack.com/api/webhooks/xxx
---

# Daily Network Inspection Workflow

Execute comprehensive health checks on all network devices.

## Execution Plan (TodoList)

You should create the following todo list:

1. [ ] Sync device configurations
2. [ ] Collect health metrics (CPU, Memory, Interfaces)
3. [ ] Parse device logs
4. [ ] Map Phase: Independent device analysis
5. [ ] Reduce Phase: Global correlation analysis
6. [ ] Generate inspection report

## Stage 1: Sync Configurations

Use nornir_execute() to collect:
- `show running-config` (all devices)
- `show version` (all devices)
- Save to: data/sync/{today}/raw/

## Stage 2: Collect Health Metrics

For each device:
- `show processes cpu`
- `show memory statistics`
- `show interfaces`
- `show logging | include ERROR|WARN`

## Stage 3: Map Phase Analysis

For each device independently:

**Prompt Template**:
```
Device: {device}
Metrics: {metrics}

Analyze this device's health:
1. CPU usage normal? (< 60%)
2. Memory usage normal? (< 75%)
3. Interface errors? (CRC, drops)
4. Recent error logs?

Return JSON:
{
  "device": "R1",
  "status": "ok | warning | critical",
  "issues": [
    {"type": "cpu", "severity": "warning", "value": "62%", "threshold": "60%"},
    ...
  ]
}
```

## Stage 4: Reduce Phase Correlation

Input: All device analysis results from Stage 3

**Prompt Template**:
```
Device Analysis Summary:
{all_device_results}

Perform global correlation:
1. Identify patterns (multiple devices with same issue)
2. Network-wide impact analysis
3. Root cause hypothesis
4. Recommended actions

Generate final report.
```

## Stage 5: Generate Report

Output Format:
```markdown
# Network Health Report - {date}

## Summary

✅ Healthy: 5 devices
⚠️  Warning: 1 device (R1 - CPU 62%)
🔴 Critical: 0 devices

## Detailed Analysis

### R1 - Warning
- CPU: 62% (exceeds 60% threshold)
- Root Cause: BGP full table processing
- Recommendation: Upgrade to ASR1002

...

## Conclusion

Overall network health: GOOD
Action required: Monitor R1 CPU
Next inspection: {tomorrow} 06:00
```

Save to: `exports/reports/snapshots/{date}.md`

## Success Criteria

- All devices reachable: 100%
- Report generated: Yes
- Execution time: < 30 minutes
- No exceptions: True
```

---

## 7. 实施步骤

### Phase 0: 备份（必须！）

```bash
# 备份整个 .olav 目录
tar -czf olav_backup_$(date +%Y%m%d_%H%M%S).tar.gz .olav/

# 确认备份
tar -tzf olav_backup_*.tar.gz | head -10
```

### Phase 1: 清理（删除无用内容）

```bash
# 执行删除脚本
cat > cleanup_olav.sh <<'EOF'
#!/bin/bash
set -e

echo "Starting .olav/ cleanup..."

# 1. 删除缓存
rm -rf .olav/cache/
echo "✅ Removed cache/"

# 2. 删除空 cron 目录
rm -rf .olav/cron/
echo "✅ Removed cron/"

# 3. 删除重复 skills
rm -rf .olav/skills/orchestrator/
rm -rf .olav/skills/olav-guard/
rm -rf .olav/skills/olav-admin/
rm -rf .olav/skills/olav-orchestrator/
echo "✅ Removed redundant skills"

# 4. 删除配置示例
rm -f .olav/settings-*.json
rm -f .olav/.last_thread_id
echo "✅ Removed config examples"

# 5. 评估后删除 tasks（需确认）
read -p "Delete tasks/ directory? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf .olav/tasks/
    echo "✅ Removed tasks/"
fi

echo "Cleanup completed!"
EOF

chmod +x cleanup_olav.sh
./cleanup_olav.sh
```

### Phase 2: 重构 Tools

```bash
# 1. 移动 tools 到顶层
mv .olav/shared/tools .olav/tools
rmdir .olav/shared

# 2. 改造 smart_sql_query.py → database.py
cd .olav/tools

# 删除 _find_project_root 函数（行 24-31）
# 添加 export 功能（参考第 4.2 节）
# 重命名
mv smart_sql_query.py database.py

# 3. 合并 nornir_execute.py + list_devices.py → network.py
# （手动编辑，合并代码，参考第 4.2 节）

# 4. 删除旧工具
rm query_database.py inspect_schema.py discover_data.py

# 5. 创建 __init__.py
cat > __init__.py <<'EOF'
"""OLAV Network Tools - Core tools for network operations."""
__all__ = ["smart_sql_query", "nornir_execute", "list_devices"]
EOF

cd ../..
```

### Phase 3: 数据库合并

```bash
# 合并 network.duckdb → main.duckdb
uv run python scripts/merge_databases.py

# 验证
uv run python -c "
import duckdb
conn = duckdb.connect('.olav/db/main.duckdb')
print('Tables:', conn.execute('SHOW TABLES').fetchall())
print('Devices:', conn.execute('SELECT COUNT(*) FROM devices').fetchone())
conn.close()
"
```

### Phase 4: 迁移 OLAV.md → AGENTS.md

```bash
# 提取有用内容
cat .olav/OLAV.md | grep -v "^---" | grep -v "^name:" > .olav/AGENTS.md

# 添加记忆模板
cat >> .olav/AGENTS.md <<'EOF'

## User Preferences
- Export format: CSV
- Timezone: Asia/Shanghai

## Common Aliases
- "核心设备" → role='core'

## Historical Insights
(Agent will populate this automatically)
EOF

# 删除旧文件
rm .olav/OLAV.md
```

### Phase 5: 创建新目录

```bash
# 创建备份目录
mkdir -p .olav/backups
cat > .olav/backups/README.md <<'EOF'
# Backups Directory
Created by `/admin backup` command.
Format: YYYY-MM-DD_HHMMSS.tar.gz
EOF

# 创建日志目录
mkdir -p .olav/logs
cat > .olav/logs/README.md <<'EOF'
# Logs Directory
- agent.log
- cli_batch_**/
- inspection_*.log
EOF

# 创建新数据库
uv run python -c "
import duckdb
duckdb.connect('.olav/db/agent.duckdb').close()
print('Created agent.duckdb')
"

uv run python -c "
import sqlite3
sqlite3.connect('.olav/db/llm_cache.db').close()
print('Created llm_cache.db')
"
```

### Phase 6: 改造 Workflows

```bash
# 更新 daily-run.md → daily-inspection.md
mv .olav/workflows/daily-run.md .olav/workflows/daily-inspection.md

# 添加 frontmatter（手动编辑）
# 添加详细 stage 描述（参考第 6.3 节）
```

### Phase 7: 验证

```bash
# 检查目录结构
tree -L 2 .olav/

# 预期输出:
# .olav/
# ├── AGENTS.md
# ├── settings.json
# ├── tools/
# │   ├── __init__.py
# │   ├── database.py
# │   └── network.py
# ├── skills/
# │   ├── network-query/
# │   ├── network-cli/
# │   ├── network-expert/
# │   ├── network-inspection/
# │   ├── network-snapshot/
# │   └── shared/
# ├── db/
# │   ├── main.duckdb
# │   ├── agent.duckdb
# │   └── llm_cache.db
# ├── backups/
# ├── logs/
# ├── knowledge/
# ├── templates/
# └── workflows/
#     └── daily-inspection.md

# 验证工具加载
uv run python -c "
import sys
from pathlib import Path
sys.path.insert(0, str(Path('.olav/tools')))

from database import smart_sql_query
from network import nornir_execute, list_devices

print('✅ Tools loaded successfully')
print(f'  - smart_sql_query: {smart_sql_query.name}')
print(f'  - nornir_execute: {nornir_execute.name}')
print(f'  - list_devices: {list_devices.name}')
"

# 验证数据库
uv run python -c "
import duckdb

print('Checking databases...')

# Main DB
conn = duckdb.connect('.olav/db/main.duckdb')
tables = conn.execute('SHOW TABLES').fetchall()
print(f'✅ main.duckdb: {len(tables)} tables')
conn.close()

# Agent DB
conn = duckdb.connect('.olav/db/agent.duckdb')
print('✅ agent.duckdb: accessible')
conn.close()

# LLM Cache
import sqlite3
conn = sqlite3.connect('.olav/db/llm_cache.db')
print('✅ llm_cache.db: accessible')
conn.close()
"
```

### Phase 8: 测试

```bash
# 测试工具执行
uv run olav ask "有多少个设备？"

# 测试 workflow（手动触发）
uv run olav inspect daily-inspection

# 检查输出
ls -la .olav/logs/
ls -la exports/reports/snapshots/
```

---

## 8. 总结

### 8.1 预期效果

| 指标 | 之前 | 之后 | 改进 |
|------|------|------|------|
| **目录数** | 15 个 | 9 个 | -40% |
| **Tools 文件数** | 6 个 | 3 个 | -50% |
| **Tools 代码量** | 1,376 行 | 620 行 | -55% |
| **数据库文件** | 2 个 DB + 1 cache | 3 个 DB（规范） | ✅ |
| **Skills 数量** | 12 个 | 6 个 | -50% |
| **符合 MCP 标准** | ❌ | ✅ | ✅ |
| **跨平台迁移** | 困难 | 简单（cp .olav/） | ✅ |

### 8.2 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| 数据库合并失败 | 中 | 高 | Phase 0 完整备份 |
| Tools 导入失败 | 低 | 中 | Phase 7 验证脚本 |
| Workflow 不兼容 | 中 | 中 | 保留旧文件直到测试通过 |
| 知识库丢失 | 低 | 高 | knowledge/ 完整保留 |

### 8.3 回滚计划

```bash
# 发现问题后立即回滚
cd /home/yhvh/Olav
rm -rf .olav/
tar -xzf olav_backup_YYYYMMDD_HHMMSS.tar.gz

# 验证回滚
ls -la .olav/
```

---

**文档版本**: v1.0  
**最后更新**: 2026-02-14  
**下一步**: 执行 Phase 0（备份）并开始实施
