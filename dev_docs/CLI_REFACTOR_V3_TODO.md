# CLI 重构方案 v3 - 直接命令

**Date**: 2026-02-15  
**Context**: 用户反馈 "不用 Adm，这个方案和 admin 差别不大"  
**Goal**: 更激进的简化 - 去掉 admin 前缀  
**Status**: ✅ **IMPLEMENTED** (2026-02-15 16:00)

---

## 🚀 Implementation Notes

### **Change Log** (2026-02-15 16:00)

**实施的10个新命令**:
1. ✅ `olav ls` (renamed from `list` to avoid Python builtin conflict)
2. ✅ `olav search`
3. ✅ `olav tree`
4. ✅ `olav backup`
5. ✅ `olav restore`
6. ✅ `olav skills`
7. ✅ `olav git`
8. ✅ `olav db-status`
9. ✅ `olav db-query`
10. ✅ `olav db-schema`

**Key Decisions**:
- `list` → `ls`: 避免与 Python 内置 `list` 类型冲突（在类型注解中会导致错误）
- 使用 `from __future__ import annotations`: 支持现代类型注解
- `admin` 命令: 更新文档字符串，强调AI任务优先，保留向后兼容

**测试结果**:
- ✅ `olav ls "*.md" --dir dev_docs` - 19 files found
- ✅ `olav skills` - 9 skills listed
- ✅ `olav db-status` - Database status displayed (39.26 MB, 8 tables)

---

## 🎯 核心理念

### 问题
- `olav admin list` (16 chars) 太长
- `olav adm list` (11 chars) 和 admin 差别不大

### 解决方案
**分离具体命令和自然语言任务**

```bash
# ✅ 具体操作：直接用命令名（无 admin 前缀）
olav list "*.py"                    # 9 chars (-7 chars, -44%)
olav search "pattern"               # 13 chars
olav backup                         # 11 chars

# ✅ 自然语言任务：用 admin 调用 Admin Agent
olav admin "fix bug in network-query"
olav admin "create monitoring skill"
olav admin "show documentation about skills"
```

**优势**:
- ✅ **最短**: 直接命令不需要前缀
- ✅ **清晰**: 具体操作 vs AI 任务分离
- ✅ **直觉**: 用户不需要想"这是不是 admin 命令"

---

## 📊 命令设计

### Category 1: 文件与代码（快捷命令）

```bash
# 取代 olav admin list/search/tree

olav ls [pattern]                   # 列出文件 (renamed from 'list')
olav search <pattern> [--type py]   # 搜索代码
olav tree [directory] [--depth 3]   # 目录树
```

**实现**: 独立 command

**Note**: `list` renamed to `ls` to avoid conflict with Python builtin `list` type

---

### Category 2: 数据库（快捷命令）

```bash
# 取代 olav admin db-*

olav db-status                      # 数据库状态
olav db-query <database> <query>    # 查询
olav db-schema <database> [table]   # Schema
```

**实现**: 独立 command 或 db 子命令

---

### Category 3: 备份（快捷命令）

```bash
# 取代 olav admin backup/restore

olav backup [--target path]         # 备份
olav restore <file>                 # 恢复
```

**实现**: 独立 command

---

### Category 4: 技能（快捷命令）

```bash
# 取代 olav admin skills/skill-info

olav skills [--detail]              # 列出技能
olav skill-info <name>              # 技能详情
```

**实现**: 独立 command

---

### Category 5: Git（快捷命令）

```bash
# 新增

olav git <args>                     # Git 快捷方式
# olav git status
# olav git log -10
```

**实现**: 独立 command，调用 subprocess

---

### Category 6: Admin Agent（自然语言任务）⭐

```bash
# 保留 olav admin 用于复杂 AI 任务

olav admin "fix the bug in network-query skill"
olav admin "create a monitoring skill that checks CPU"
olav admin "show me documentation about skill development"
olav admin "search for execute_sql usage"
```

**实现**: Admin Agent (LLM-powered)

---

## 🔄 命令对比

| 功能 | v1 (admin) | v3 (direct) | 节省 | 场景 |
|------|-----------|------------|------|------|
| 列出文件 | `olav admin list` | `olav list` | -6 chars (-40%) | 快捷 |
| 搜索代码 | `olav admin search` | `olav search` | -6 chars | 快捷 |
| 备份 | `olav admin backup` | `olav backup` | -6 chars | 快捷 |
| 目录树 | `olav admin tree` | `olav tree` | -6 chars | 快捷 |
| DB 状态 | `olav admin db-status` | `olav db-status` | -6 chars | 快捷 |
| AI 任务 | `olav admin "fix bug"` | `olav admin "fix bug"` | 0 | Admin Agent |

---

## 🏗️ 架构设计

### CLI 命令层级

```
olav
├── ask <query>                     # LLM query (Main Agent)
├── admin <natural-language>        # Admin Agent (AI)
├── devices                         # List devices
├── interactive                     # Interactive mode
│
├── list [pattern]                  # File operations ⭐ NEW
├── search <pattern>                # Code search ⭐ NEW
├── tree [dir]                      # Directory tree ⭐ NEW
│
├── backup [--target]               # Backup ⭐ NEW
├── restore <file>                  # Restore ⭐ NEW
│
├── skills [--detail]               # Skill management ⭐ NEW
├── skill-info <name>               # Skill info ⭐ NEW
│
├── db-status                       # Database ⭐ NEW
├── db-query <db> <query>           # DB query ⭐ NEW
├── db-schema <db> [table]          # DB schema ⭐ NEW
│
├── git <args>                      # Git shortcut ⭐ NEW
└── --help / --version              # System
```

**设计原则**:
- ✅ 扁平化：具体操作在顶层（无 admin 前缀）
- ✅ 区分：`admin` 专门用于自然语言 AI 任务
- ✅ 清晰：用户看命令名就知道功能

---

## 💻 实现方案

### Step 1: 新增独立命令

```python
# src/olav/cli/agent_v2.py

@app.command()
def list(
    pattern: str = typer.Argument("*", help="File pattern (e.g., '*.py')"),
):
    """List files matching pattern.
    
    Examples:
        olav list "*.py"
        olav list ".olav/skills/*/SKILL.md"
    """
    result = subprocess.run(
        ["find", ".", "-name", pattern, "-type", "f"],
        capture_output=True, text=True
    )
    console.print(result.stdout)


@app.command()
def search(
    pattern: str = typer.Argument(..., help="Search pattern"),
    type: str = typer.Option("*", "--type", help="File type (py, md, all)"),
):
    """Search for pattern in codebase.
    
    Examples:
        olav search "execute_sql"
        olav search "execute_sql" --type py
    """
    file_pattern = f"*.{type}" if type != "all" else "*"
    result = subprocess.run(
        ["grep", "-r", pattern, ".", f"--include={file_pattern}"],
        capture_output=True, text=True
    )
    console.print(result.stdout)


@app.command()
def tree(
    directory: str = typer.Argument(".", help="Directory to show"),
    depth: int = typer.Option(3, "--depth", help="Max depth"),
):
    """Show directory tree.
    
    Examples:
        olav tree
        olav tree .olav/skills --depth 2
    """
    result = subprocess.run(
        ["tree", "-L", str(depth), directory],
        capture_output=True, text=True
    )
    console.print(result.stdout)


@app.command()
def backup(
    target: str = typer.Option(None, "--target", help="Target path"),
):
    """Backup OLAV data.
    
    Examples:
        olav backup
        olav backup --target ~/backups/
    """
    from datetime import datetime
    if not target:
        target = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    
    result = subprocess.run(
        ["tar", "-czf", target, ".olav/"],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        console.print(f"[green]✓[/green] Backup created: {target}")
    else:
        console.print(f"[red]✗[/red] Backup failed: {result.stderr}")


@app.command()
def restore(
    file: str = typer.Argument(..., help="Backup file path"),
):
    """Restore from backup.
    
    Examples:
        olav restore backup_20260215_153000.tar.gz
    """
    result = subprocess.run(
        ["tar", "-xzf", file, "-C", "."],
        capture_output=True, text=True
    )
    if result.returncode == 0:
        console.print(f"[green]✓[/green] Restored from: {file}")
    else:
        console.print(f"[red]✗[/red] Restore failed: {result.stderr}")


@app.command()
def skills(
    detail: bool = typer.Option(False, "--detail", help="Show details"),
):
    """List available skills.
    
    Examples:
        olav skills
        olav skills --detail
    """
    from pathlib import Path
    skills_path = Path(".olav/skills")
    
    if not skills_path.exists():
        console.print("[yellow]No skills found[/yellow]")
        return
    
    skills = []
    for skill_dir in skills_path.iterdir():
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            skills.append(skill_dir.name)
    
    if detail:
        for skill in skills:
            tool_count = len(list((skills_path / skill / "tools").glob("*.py")))
            console.print(f"  {skill} ({tool_count} tools)")
    else:
        console.print("\n".join(skills))


@app.command()
def git(
    args: list[str] = typer.Argument(..., help="Git arguments"),
):
    """Git command shortcut.
    
    Examples:
        olav git status
        olav git log -10
        olav git diff
    """
    result = subprocess.run(
        ["git"] + args,
        capture_output=True, text=True
    )
    console.print(result.stdout)
    if result.stderr:
        console.print(result.stderr, style="yellow")
```

---

### Step 2: 重构 admin 命令

```python
@app.command()
def admin(
    task: str = typer.Argument(..., help="Natural language task for Admin Agent"),
):
    """Execute Admin Agent task (AI-powered).
    
    Use this for complex, natural language tasks that require AI reasoning.
    For simple operations, use direct commands (list, search, backup, etc.)
    
    Examples:
        olav admin "fix the bug in network-query skill"
        olav admin "create a monitoring skill that checks CPU"
        olav admin "show documentation about skill development"
    """
    # Call Admin Agent with LLM
    _check_llm_key()
    console.print(f"[cyan]Admin Agent:[/cyan] Processing task...")
    
    # TODO: Implement Admin Agent invocation
    # admin_agent = create_admin_agent()
    # result = admin_agent.invoke(task)
    
    console.print("[yellow]Admin Agent not yet implemented in v2.1[/yellow]")
```

---

## 📋 实施 TODO

### Phase 1: 核心快捷命令 (1 hour)

- [x] ~~分析最佳 CLI 结构~~
- [ ] 实现 `list` 命令
- [ ] 实现 `search` 命令
- [ ] 实现 `tree` 命令
- [ ] 实现 `backup` 命令
- [ ] 实现 `restore` 命令
- [ ] 测试所有文件操作命令

### Phase 2: 数据库和技能命令 (30 min)

- [ ] 实现 `skills` 命令
- [ ] 实现 `skill-info` 命令
- [ ] 实现 `db-status` 命令
- [ ] 实现 `db-query` 命令（可选）
- [ ] 测试数据库和技能命令

### Phase 3: Git 快捷方式 (15 min)

- [ ] 实现 `git` 命令
- [ ] 测试 git 操作

### Phase 4: 重构 admin 命令 (15 min)

- [ ] 更新 `admin` 命令文档
- [ ] 标注为 Admin Agent (AI) 专用
- [ ] 测试自然语言任务

### Phase 5: 文档更新 (30 min)

- [ ] 更新 ADMIN_AGENT_SPEC.md
- [ ] 更新 ADMIN_REFACTOR_PLAN.md
- [ ] 创建用户快速参考
- [ ] Git commit all changes

---

## 🎯 预期效果

### 命令长度对比

| 命令 | v1 (admin) | v3 (direct) | 节省 |
|------|-----------|------------|------|
| 列出文件 | 16 chars | 10 chars | **-37%** |
| 搜索 | 18 chars | 12 chars | **-33%** |
| 备份 | 17 chars | 11 chars | **-35%** |
| 平均 | ~17 chars | ~11 chars | **-35%** ⭐ |

### 用户体验对比

```bash
# Before (v1)
olav admin list "*.py"              # 需要记住 "admin" 前缀
olav admin search "pattern"         # 需要记住 "admin" 前缀
olav admin backup                   # 需要记住 "admin" 前缀

# After (v3)
olav list "*.py"                    # 直接，直觉
olav search "pattern"               # 直接，直觉
olav backup                         # 直接，直觉

# Natural language tasks (保留 admin)
olav admin "fix bug in network-query"   # 清晰表明是 AI 任务
```

---

## ✨ 总结

### 核心改进
1. **去掉 admin 前缀** - 具体操作命令直接可用
2. **保留 admin** - 专门用于自然语言 AI 任务
3. **35% 更短** - 平均减少 6 个字符

### 设计哲学
```
具体操作 = 直接命令（无前缀）
AI 任务 = olav admin <自然语言>
```

**清晰、简短、符合直觉** ⭐
