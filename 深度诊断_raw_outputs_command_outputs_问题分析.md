# 🔍 深度诊断报告：raw_outputs、命令数量、command_outputs、parsed_data

**日期**: 2026-02-13  
**诊断内容**: 用户的4个关键问题

---

## Q1: raw_outputs应被移除，需要移除对应的代码

### 当前状态

**raw_outputs的使用现状**:

| 位置 | 类型 | 状态 | 说明 |
|-----|------|------|------|
| `src/olav/core/database.py` | 表定义 | ❌ 仍定义但未使用 | 代码存在但被注释 |
| `.olav/skills/shared/tools/raw_importer.py` | 导入函数 | ❌ 被禁用 | 代码第48行注释 |
| `src/olav/cli/cli_main.py` | 查询语句 | ⚠️ 仍在使用 | 3处从raw_outputs查询 |
| `.olav/skills/*/REFERENCE.md` | 文档示例 | ⚠️ 已过时 | 示例仍引用raw_outputs |
| `.olav/skills/*/system_prompt.md` | LLM提示 | ⚠️ 已过时 | 指导LLM查询raw_outputs |

### 问题：代码不一致

**raw_importer.py第48行** (已禁用):
```python
# v0.10.1: Raw files kept in filesystem only, not imported to DB
# raw_count = _import_raw_outputs(conn, sync_dir, snapshot_date)
raw_count = 0  # Files are stored locally, not in database
```

**但CLI中仍在查询raw_outputs** (cli_main.py):

```python
# 第755行 - database命令
output_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]

# 第994行 - init命令  
raw_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]
```

**结果**: 运行`olav init`时会崩溃
```
⚠️ Catalog Error: Table with name raw_outputs does not exist!
```

### 需要移除的代码位置

| 文件 | 行号 | 代码 | 优先级 |
|-----|------|------|--------|
| `src/olav/core/database.py` | 540-570 | CREATE TABLE raw_outputs | 🟡 低 |
| `src/olav/cli/cli_main.py` | 700-703 | DROP TABLE raw_outputs | 🔴 高 |
| `src/olav/cli/cli_main.py` | 753-756 | SELECT raw_outputs | 🔴 **高** |
| `src/olav/cli/cli_main.py` | 993-995 | SELECT raw_outputs | 🔴 **高** |
| `.olav/skills/shared/tools/raw_importer.py` | 48 | 注释的导入函数 | 🟡 低 |
| `.olav/skills/*/REFERENCE.md` | 多处 | 文档示例 | 🟡 低 |
| `.olav/skills/*/system_prompt.md` | 多处 | LLM提示 | 🟡 低 |

---

## Q2: 30个命令是不是NTC templates中的全部命令？

### 答案：❌ 不是

**NTC Templates中的实际数量**:

```
📊 NTC Templates for Cisco IOS:
   Total commands: 130
   Used in sync_all(): 30 (23%)
```

### 命令来源分析

**30个命令的来源**:

```python
# File: .olav/skills/shared/tools/sync_tools.py:579-593

fallback_commands = [
    "show version",
    "show running-config",
    "show cdp neighbors detail",
    "show ip interface brief",
    "show ip route",
    "show ip ospf neighbor",
    "show ip bgp summary",
    "show interfaces status",
    "show vlan brief",
    "show processes cpu",
    "show memory statistics",
    "show logging",
    "show arp",
    "show mac address-table",
    "show ntp status",
    # ... 15 more (30 total)
]
```

**这些30个命令是**:
- ✅ 硬编码的后备命令集
- ✅ 从NTC templates中选出的最常用命令
- ❌ 不是全部 (130个可用)

### 命令配置流程

```
优先级1: --whitelist文件 (如果存在)
         ↓
优先级2: NTC templates + command_mode设置
         • mode = 'all': 使用所有130个命令
         • mode = 'whitelist': 使用白名单
         ↓
后备方案: 30个硬编码命令 (如果以上都不可用)
         ↓
实际命令集: 通常是30个或130个
```

### 为什么不是130个？

**init_test_output.log显示**:
```
Using all available NTC templates (130 commands)
Pre-flight: Checking connectivity for 6 devices...
```

**解释**: 代码打印了"130个"，但实际执行时很多命令尝试失败，只收集了12/30

---

## Q3: command_outputs是什么

### 定义和用途

**表结构** (database.py 第545-561):

```sql
CREATE TABLE IF NOT EXISTS command_outputs (
    id INTEGER PRIMARY KEY,
    snapshot_date DATE NOT NULL,
    device_name VARCHAR NOT NULL,
    platform VARCHAR DEFAULT 'cisco_ios',
    command VARCHAR NOT NULL,
    raw_output TEXT,              -- ← 原始CLI输出
    parsed_data JSON,             -- ← 解析的JSON数据
    row_count INTEGER DEFAULT 0,
    parse_success BOOLEAN DEFAULT FALSE,
    collected_at TIMESTAMP,
    UNIQUE(snapshot_date, device_name, command)
)
```

### 功能

| 字段 | 说明 | 例子 |
|-----|------|------|
| **raw_output** | 未处理的CLI输出 | "Interface Ethernet0/0 is up, line protocol is up" |
| **parsed_data** | TextFSM解析后的JSON | `{"interface": "Eth0/0", "status": "up"}` |
| **parse_success** | 是否成功解析 | true/false |
| **row_count** | 解析后的行数 | 5 (表示解析出5条记录) |

### 数据流

```
原始CLI输出
  ↓
TextFSM解析
  ↓
command_outputs
  ├─ raw_output: 原始文本
  ├─ parsed_data: JSON
  └─ parse_success: true/false
  ↓
SQL查询或L1-L4视图
  ↓
用户查询结果
```

### 使用场景

```python
# 场景1: 获取指定设备的特定命令输出
SELECT device_name, parsed_data 
FROM command_outputs 
WHERE command = 'show ip route' AND device_name = 'R1'

# 场景2: 查看解析失败的命令
SELECT command, raw_output 
FROM command_outputs 
WHERE parse_success = FALSE

# 场景3: 提取解析的数据
SELECT 
    device_name,
    json_extract(parsed_data, '$.interfaces[0].name') as interface,
    json_extract(parsed_data, '$.interfaces[0].status') as status
FROM command_outputs
WHERE command = 'show interfaces'
```

---

## Q4: parsed_data是不是解析的JSON，设计是直接把JSON放入DuckDB，是不是JSON解析功能出现了问题？

### 答案：已出现问题

### 问题诊断

**当前状态**:

```
✅ 设计正确: parsed_data确实是JSON
✅ 表结构正确: command_outputs有parsed_data JSON列
❌ 实现有问题: JSON解析功能存在两个bug
```

### Bug 1: raw_importer.py中的列名不匹配

**raw_importer.py第73-91行**:

```python
conn.execute(
    """
    INSERT INTO command_outputs
    (snapshot_date, device_name, command, output, source_file, parser_used)
    VALUES (?, ?, ?, ?, ?, ?)
    """,
    [
        snapshot_date,
        device_name,
        command,
        json.dumps(output_data),
        str(json_file.relative_to(...)),
        "textfsm",
    ],
)
```

**问题**:
- 代码插入列: `output, source_file, parser_used`
- 表中实际列: `raw_output, parsed_data, parse_success`

**结果**: 

```
❌ Column 'output' does not exist
❌ Column 'source_file' does not exist
❌ Column 'parser_used' does not exist
```

### Bug 2: 设计与实现的差异

**设计说明** (raw_importer.py第7):

```
Raw CLI Output → raw_outputs table (JSONB) → L1-L4 SQL Views
```

**但实际实现**:

```
Raw CLI Output → command_outputs table (JSON) ← 表名错了
                  ├─ raw_output (TEXT) ← 应该存储原始文本
                  ├─ parsed_data (JSON) ← 应该存储解析结果
                  └─ parse_success (BOOLEAN) ← 应该表示是否成功
```

**问题**: 代码中的列名与表的实际列名完全不匹配

### Bug 3: raw_outputs vs command_outputs混淆

**现状汇总**:

| 实体 | 设计 | 当前实现 | 状态 |
|-----|------|---------|------|
| **raw_outputs表** | 存储原始CLI | 已移除 (v0.10.1) | ❌ 不存在 |
| **command_outputs表** | 存储解析数据 | 存在但导入失败 | ⚠️ 有问题 |
| **parsed_data列** | JSON格式 | 定义存在但无数据 | ⚠️ 空的 |

### JSON解析功能诊断

**可能的根本原因**:

```
v0.9.3设计: 使用raw_outputs表存储JSONB
  ↓
v0.10.1变更: 改为command_outputs表 + JSON列
  ↓
迁移不完整: 
  - raw_importer.py未更新 (仍用旧列名)
  - CLI仍查询旧表名 (raw_outputs)
  - 文档未同步
  ↓
结果: JSON数据无法正确导入和查询 ❌
```

---

## 🎯 总结表

| 问题 | 现状 | 严重性 | 原因 |
|-----|------|--------|------|
| **raw_outputs表** | 定义存在但不应使用 | 🔴 高 | v0.10.1应移除但代码遗留 |
| **30个命令** | 是硬编码后备，不是全部 | 🟡 低 | 设计正确，文档可改进 |
| **command_outputs表** | 设计正确但实现有bug | 🔴 **高** | 列名不匹配，导入失败 |
| **parsed_data JSON** | 设计正确但无法导入 | 🔴 **高** | raw_importer.py代码过时 |

---

## 🔧 需要立即修复的

### 优先级1：修复raw_outputs引用 (高优先级)

**文件**: `src/olav/cli/cli_main.py`

```python
# 第753-756行：删除
# ❌ 这会导致崩溃因为raw_outputs表不存在
try:
    output_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]
except:
    pass

# 第993-995行：删除  
# ❌ 这会导致init命令失败
raw_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]
```

### 优先级2：修复raw_importer.py (高优先级)

**文件**: `.olav/skills/shared/tools/raw_importer.py`

```python
# 第73-91行：更正列名
# ❌ 当前代码
INSERT INTO command_outputs
(snapshot_date, device_name, command, output, source_file, parser_used)

# ✅ 应该是
INSERT INTO command_outputs
(snapshot_date, device_name, command, raw_output, parsed_data, parse_success)
```

### 优先级3：更新文档和Prompt (中优先级)

**文件**: `.olav/skills/*/REFERENCE.md`, `.olav/skills/*/system_prompt.md`

```
❌ 当前: 引用raw_outputs表和JSONB字段
✅ 应该: 引用command_outputs表和JSON字段
```

### 优先级4：移除raw_outputs表定义 (低优先级)

**文件**: `src/olav/core/database.py`

```python
# 第540-575行: 删除整个CREATE TABLE raw_outputs块
```

---

## 📊 代码健康度评分

| 方面 | 分数 | 原因 |
|-----|------|------|
| **架构设计** | 8/10 | 从raw_outputs到command_outputs是好主意 |
| **实现完整性** | 3/10 | 多个地方的变更没同步 |
| **文档准确性** | 2/10 | 所有文档仍引用旧表名 |
| **代码可维护性** | 4/10 | 有太多遗留的废弃代码 |
| **测试覆盖率** | 2/10 | JSON导入和查询没被测试 |

---

**总体结论**: 这是一次不完整的重构。设计很好，但迁移工作有很多遗漏。需要系统地进行代码清理和测试。
