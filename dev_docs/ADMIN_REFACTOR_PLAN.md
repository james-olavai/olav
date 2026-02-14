# Admin Agent Refactor Plan

**Date**: 2026-02-15  
**Context**: v2.1 Ultra-Minimalist Admin Agent (4 tools)  
**Purpose**: 标注冗余代码 + 设计实用 OLAV 命令

---

## 🗑️ Part 1: 待删除的冗余代码

### 🔴 高优先级删除（立即）

这些是 v2.1 中被 `execute_command` 替代的专门工具：

#### 1. `.olav/skills/olav-admin/tools/list_files.py` ❌ 删除
```python
# 位置: .olav/skills/olav-admin/tools/list_files.py
# 行数: ~100 lines
# 原因: 被 execute_command("find ...") 替代
# 替代方案:
#   Before: list_files(".olav/skills", pattern="*.py")
#   After:  execute_command("find .olav/skills -name '*.py' -type f")
```

**删除命令**:
```bash
rm .olav/skills/olav-admin/tools/list_files.py
```

---

#### 2. `.olav/skills/olav-admin/tools/search_code.py` ❌ 删除
```python
# 位置: .olav/skills/olav-admin/tools/search_code.py
# 行数: ~90 lines
# 原因: 被 execute_command("grep ...") 替代
# 替代方案:
#   Before: search_code("execute_sql", file_type="*.py")
#   After:  execute_command("grep -r 'execute_sql' .olav/ --include='*.py'")
```

**删除命令**:
```bash
rm .olav/skills/olav-admin/tools/search_code.py
```

---

#### 3. `.olav/skills/olav-admin/tools/list_workspace_structure.py` ❌ 删除
```python
# 位置: .olav/skills/olav-admin/tools/list_workspace_structure.py
# 原因: 被 execute_command("tree ...") 或 execute_command("find ...") 替代
# 替代方案:
#   Before: list_workspace_structure()
#   After:  execute_command("find . -type d -maxdepth 3")
#           execute_command("tree -L 3 -d")
```

**删除命令**:
```bash
rm .olav/skills/olav-admin/tools/list_workspace_structure.py
```

---

#### 4. `.olav/skills/olav-admin/tools/backup_config.py` ❌ 删除
```python
# 位置: .olav/skills/olav-admin/tools/backup_config.py
# 原因: 被 execute_command("tar ...") 替代
# 替代方案:
#   Before: backup_config()
#   After:  execute_command("tar -czf backup_$(date +%Y%m%d_%H%M%S).tar.gz .olav/")
```

**删除命令**:
```bash
rm .olav/skills/olav-admin/tools/backup_config.py
```

---

#### 5. `.olav/skills/olav-admin/tools/restore_config.py` ❌ 删除
```python
# 位置: .olav/skills/olav-admin/tools/restore_config.py
# 原因: 被 execute_command("tar -xzf ...") 替代
# 替代方案:
#   Before: restore_config(backup_path)
#   After:  execute_command("tar -xzf backup.tar.gz -C .olav/")
```

**删除命令**:
```bash
rm .olav/skills/olav-admin/tools/restore_config.py
```

---

### 🟡 中优先级重构（可选）

#### 6. `src/olav/cli/admin.py` 🔄 重构
```python
# 位置: src/olav/cli/admin.py
# 行数: 250 lines
# 状态: 部分保留，部分重构

# ✅ 保留（基础信息命令）:
#   - async def status()         # 系统状态
#   - async def db_info()        # 数据库信息

# 🔄 重构（改用 execute_command）:
#   - async def backup()         # 改用 tar 命令
#   - async def restore()        # 改用 tar 命令
#   - async def skill_list()     # 改用 find 命令
#   - async def cron_list()      # 改用 crontab -l

# ❌ 删除（未实现的占位符）:
#   - async def skill_reload()   # Not Implemented
#   - async def schema_sync()    # Not Implemented
#   - async def cron_add()       # Not Implemented
```

**重构策略**: 见下方 Part 2 新命令设计

---

### 📊 删除统计

| 文件 | 行数 | 状态 | 原因 |
|------|------|------|------|
| list_files.py | ~100 | ❌ 删除 | execute_command("find") |
| search_code.py | ~90 | ❌ 删除 | execute_command("grep") |
| list_workspace_structure.py | ~80 | ❌ 删除 | execute_command("tree/find") |
| backup_config.py | ~60 | ❌ 删除 | execute_command("tar") |
| restore_config.py | ~60 | ❌ 删除 | execute_command("tar") |
| **总计** | **~390 lines** | **❌** | **Ultra-minimalist philosophy** |

**删除命令（一键清理）**:
```bash
cd /home/yhvh/Olav
rm .olav/skills/olav-admin/tools/list_files.py
rm .olav/skills/olav-admin/tools/search_code.py
rm .olav/skills/olav-admin/tools/list_workspace_structure.py
rm .olav/skills/olav-admin/tools/backup_config.py
rm .olav/skills/olav-admin/tools/restore_config.py

# 验证
ls .olav/skills/olav-admin/tools/
# 应该只剩: read_file.py, write_file.py
```

---

## ✨ Part 2: 新增实用 OLAV 命令

### 设计原则

1. **双用途**: 用户 CLI + Admin Agent 都能调用
2. **Shell 命令封装**: 内部调用 `subprocess` 执行 shell 命令
3. **快速响应**: 大部分命令 <100ms（无 LLM 调用）
4. **安全**: 参数验证 + 路径检查

---

### 命令设计（12 个实用命令）

#### 📁 Category 1: 文件与代码（替代旧工具）

##### 1. `olav admin list <pattern>` ⭐
```bash
# 用途: 列出文件（替代 list_files 工具）
# 示例:
olav admin list "*.py"                    # 列出所有 Python 文件
olav admin list ".olav/skills/*/SKILL.md" # 列出所有技能定义
olav admin list ".olav/tools/*.py"        # 列出所有工具

# 实现: execute_command("find . -name '<pattern>' -type f")
```

##### 2. `olav admin search <pattern> [--type py|md|all]` ⭐
```bash
# 用途: 搜索代码（替代 search_code 工具）
# 示例:
olav admin search "execute_sql"           # 搜索所有文件
olav admin search "execute_sql" --type py # 只搜索 Python 文件
olav admin search "class Agent" --type py # 搜索类定义

# 实现: execute_command("grep -r '<pattern>' . --include='*.<type>'")
```

##### 3. `olav admin tree [directory] [--depth 3]`
```bash
# 用途: 显示目录树
# 示例:
olav admin tree                           # 显示全部目录树
olav admin tree .olav/skills --depth 2    # 显示技能目录（2层）
olav admin tree src/olav --depth 3        # 显示源码结构

# 实现: execute_command("tree -L <depth> <directory>")
#       或 execute_command("find <dir> -maxdepth <depth> -type d")
```

---

#### 🗄️ Category 2: 数据库管理

##### 4. `olav admin db-status`
```bash
# 用途: 数据库状态（现有，保留）
# 示例:
olav admin db-status

# 输出:
# {
#   "main.duckdb": {"size_mb": 5.2, "tables": 8},
#   "agent.duckdb": {"size_mb": 1.1, "tables": 2}
# }
```

##### 5. `olav admin db-query <database> <query>`
```bash
# 用途: 快速查询数据库
# 示例:
olav admin db-query main "SELECT COUNT(*) FROM devices"
olav admin db-query main "SELECT * FROM devices LIMIT 5"

# 实现: 连接 DuckDB 执行查询
```

##### 6. `olav admin db-schema <database> [table]`
```bash
# 用途: 查看数据库 schema
# 示例:
olav admin db-schema main                 # 列出所有表
olav admin db-schema main devices         # 显示 devices 表结构

# 实现: execute_command("duckdb main.duckdb 'DESCRIBE <table>'")
```

---

#### 💾 Category 3: 备份与恢复（改进版）

##### 7. `olav admin backup [--target path]` ⭐
```bash
# 用途: 备份系统（改用 tar 命令）
# 示例:
olav admin backup                         # 自动命名: backup_20260215_153000.tar.gz
olav admin backup --target ~/backups/     # 备份到指定目录

# 实现: execute_command("tar -czf backup_$(date +%Y%m%d_%H%M%S).tar.gz .olav/")
```

##### 8. `olav admin restore <backup-file>`
```bash
# 用途: 从备份恢复
# 示例:
olav admin restore backup_20260215_153000.tar.gz
olav admin restore ~/backups/latest.tar.gz

# 实现: execute_command("tar -xzf <backup-file> -C .")
```

---

#### 🎯 Category 4: 技能管理（改进版）

##### 9. `olav admin skills [--detail]` ⭐
```bash
# 用途: 列出技能（改用 find 命令）
# 示例:
olav admin skills                         # 列出技能名称
olav admin skills --detail                # 显示详细信息（工具数量等）

# 实现: execute_command("find .olav/skills -name 'SKILL.md' -type f")
```

##### 10. `olav admin skill-info <skill-name>`
```bash
# 用途: 显示技能详细信息
# 示例:
olav admin skill-info network-query

# 输出:
# {
#   "name": "network-query",
#   "tools": ["query_database", "execute_nornir"],
#   "description": "Query network device data"
# }

# 实现: 读取并解析 .olav/skills/network-query/SKILL.md
```

---

#### 🔧 Category 5: 高级管理（Admin Agent 专用）

##### 11. `olav admin exec <command>` ⭐⭐⭐
```bash
# 用途: 执行任意命令（Admin Agent 专用）
# 安全: HITL approval for dangerous commands
# 示例:
olav admin exec "find .olav/skills -name '*.py' | wc -l"
olav admin exec "grep -r 'DuckDB' src/"
olav admin exec "git status"

# 实现: execute_command(<command>) with safety checks
```

##### 12. `olav admin git <args>`
```bash
# 用途: Git 操作快捷方式
# 示例:
olav admin git status
olav admin git log -10
olav admin git diff

# 实现: execute_command("git <args>")
```

---

### 命令对比表（新 vs 旧）

| 功能 | v1 实现（冗余工具） | v2 实现（OLAV 命令） | 谁可以用？ |
|------|-------------------|---------------------|---------|
| 列出文件 | `list_files()` (100 lines) | `olav admin list "*.py"` | User + Admin Agent |
| 搜索代码 | `search_code()` (90 lines) | `olav admin search "pattern"` | User + Admin Agent |
| 备份系统 | `backup_config()` (60 lines) | `olav admin backup` | User + Admin Agent |
| 恢复系统 | `restore_config()` (60 lines) | `olav admin restore file` | User + Admin Agent |
| 目录结构 | `list_workspace_structure()` (80 lines) | `olav admin tree` | User + Admin Agent |
| Git 操作 | ❌ 无 | `olav admin git status` | User + Admin Agent |
| 任意命令 | ❌ 无 | `olav admin exec "..."` | **Admin Agent 专用** |
| DB 查询 | ❌ 无 | `olav admin db-query main "SELECT ..."` | User + Admin Agent |

**优势**:
- ✅ 用户可以直接在 CLI 使用（不需要写 Python 代码）
- ✅ Admin Agent 可以调用（通过 `execute_olav("admin ...")` 工具）
- ✅ 无需维护 390 行 Python wrapper 代码
- ✅ 更灵活（shell 命令组合无限可能）

---

## 🔄 Part 3: Admin Agent 工具更新

### v2.1 工具定义（4 tools）

```python
# .olav/skills/olav-admin/tools/

tools = [
    read_file,         # 保留: 读文件
    write_file,        # 保留: 写文件
    execute_command,   # 新增: 执行任意 shell 命令
    execute_olav,      # 新增: 执行 OLAV 命令（包括 admin 命令）
]
```

### execute_olav 工具示例

```python
@tool
def execute_olav(command: str) -> dict:
    """Execute OLAV command (including admin commands).
    
    Examples:
        execute_olav("ask 'What is 2+2?'")
        execute_olav("admin list '*.py'")
        execute_olav("admin search 'execute_sql'")
        execute_olav("admin backup")
        execute_olav("devices")
    """
    import subprocess
    result = subprocess.run(
        ["uv", "run", "olav"] + shlex.split(command),
        capture_output=True,
        text=True,
        timeout=60
    )
    return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
```

### Admin Agent 使用新命令的示例

```python
# Before (v1): 使用专门工具
result1 = list_files(".olav/skills", pattern="*.py")
result2 = search_code("execute_sql", file_type="*.py")
result3 = backup_config()

# After (v2): 使用 execute_olav 调用 admin 命令
result1 = execute_olav("admin list '.olav/skills/*.py'")
result2 = execute_olav("admin search 'execute_sql' --type py")
result3 = execute_olav("admin backup")

# 或者直接用 execute_command
result1 = execute_command("find .olav/skills -name '*.py' -type f")
result2 = execute_command("grep -r 'execute_sql' .olav/ --include='*.py'")
result3 = execute_command("tar -czf backup.tar.gz .olav/")
```

---

## 📋 Part 4: 实施步骤

### Phase 1: 删除冗余代码（立即）

```bash
# 1. 删除 5 个旧工具
rm .olav/skills/olav-admin/tools/list_files.py
rm .olav/skills/olav-admin/tools/search_code.py
rm .olav/skills/olav-admin/tools/list_workspace_structure.py
rm .olav/skills/olav-admin/tools/backup_config.py
rm .olav/skills/olav-admin/tools/restore_config.py

# 2. Git commit
git add .olav/skills/olav-admin/tools/
git commit -m "refactor: remove 5 redundant admin tools (replaced by execute_command)

🗑️ Removed (390 lines)
- list_files.py → execute_command('find ...')
- search_code.py → execute_command('grep ...')
- list_workspace_structure.py → execute_command('tree/find')
- backup_config.py → execute_command('tar ...')
- restore_config.py → execute_command('tar ...')

🎯 Philosophy
- '代码即工具' - Use shell commands directly
- 95% code reduction
- More flexible with shell command combinations"
```

### Phase 2: 实现新 admin 命令（渐进）

```bash
# 1. 重构 src/olav/cli/admin.py
#    - 添加: list, search, tree, exec, git 命令
#    - 保留: status, db-info
#    - 改进: backup, restore (使用 subprocess + shell 命令)

# 2. 更新 CLI 路由（src/olav/cli/agent_v2.py）

# 3. 测试所有命令
uv run olav admin list "*.py"
uv run olav admin search "execute_sql"
uv run olav admin backup

# 4. Git commit
git commit -m "feat: add 12 practical admin commands"
```

### Phase 3: 更新文档（同步）

```bash
# 1. 更新 ADMIN_AGENT_SPEC.md
#    - CLI Interface section: 添加 12 个新命令示例

# 2. 更新 DEVELOPER_REFERENCE.md
#    - Admin Commands section: 添加命令参考

# 3. Git commit
git commit -m "docs: update admin commands documentation"
```

---

## 🎯 预期结果

### 代码变化

| 指标 | Before | After | 变化 |
|------|--------|-------|------|
| Admin 工具数量 | 8 个 | 4 个 | -50% |
| 工具代码行数 | ~1,200 | ~200 | -83% |
| 冗余代码（.olav/） | 390 行 | 0 行 | **-100%** ⭐ |
| OLAV admin 命令数 | 8 个 | 20 个 | +150% |
| 可用性 | Admin Agent 专用 | User + Admin Agent | **双用途** ⭐ |

### 用户体验提升

**Before (v1)**:
```bash
# 用户想列出所有 Python 文件
# ❌ 无法直接做，需要写 Python 代码或手动 find
find .olav/skills -name "*.py"
```

**After (v2)**:
```bash
# 用户可以直接用 OLAV 命令
# ✅ 简单直观
olav admin list "*.py"
olav admin search "execute_sql"
olav admin backup
```

### Admin Agent 工作流提升

**Before (v1)**:
```python
# Admin Agent 需要调用 8 个专门工具
result = list_files(".olav/skills", pattern="*.py")
# 功能受限于预定义工具
```

**After (v2)**:
```python
# Admin Agent 可以用任意 shell 命令
result = execute_command("find .olav/skills -name '*.py' | wc -l")
result = execute_olav("admin list '*.py'")
# 功能无限（任何 shell 命令组合）
```

---

## 📌 总结

### 核心洞察（用户的提问）

> "虽然减少了工具，是不是需要添加一些 OLAV 命令，让用户和 Admin 都能调用？"

**答案**: ✅ **是的！** 这是关键设计改进：

1. **旧设计缺陷**: Admin Agent 有 8 个工具，但普通用户无法用
2. **新设计优势**: 
   - OLAV admin 命令 = 双用途（User CLI + Admin Agent 工具）
   - `execute_olav("admin list '*.py'")` = Admin Agent 调用
   - `olav admin list "*.py"` = 用户直接调用
   - 一套实现，两种用途 ⭐

### 待删除的冗余代码（用户的第二个问题）

✅ **已标注**: 5 个文件，390 行代码

```bash
# 立即删除命令
rm .olav/skills/olav-admin/tools/{list_files,search_code,list_workspace_structure,backup_config,restore_config}.py
```

---

**版本**: v2.1.0  
**日期**: 2026-02-15  
**状态**: 📋 方案完成，等待实施
