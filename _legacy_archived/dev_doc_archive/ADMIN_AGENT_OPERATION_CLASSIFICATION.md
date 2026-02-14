# Admin Agent 操作细化分类

**目的**: 明确每个Admin操作的实现方式，避免过度设计
**原则**: KISS - 选择最简单可行的方案
**日期**: 2026-02-12

---

## 操作分类矩阵

根据**实现复杂度**和**用户需求**，操作分为4类：

```
┌─────────────────────────────────────────────────────┐
│ Admin能做的操作                                      │
├─────────────────────────────────────────────────────┤
│ Category 1: 直接编辑文件 (File Edit)                │
│ → 最简单，仅YAML/JSON修改                           │
│                                                      │
│ Category 2: 用Tool封装 (Tool Wrapper)               │
│ → 需要业务逻辑，但仅Admin使用                       │
│                                                      │
│ Category 3: 复用Olav命令 (Reuse CLI)                │
│ → 已有命令，Agent直接调用                           │
│                                                      │
│ Category 4: 新增Olav命令 (New CLI)                  │
│ → 用户和Agent都需要，值得做成命令                   │
└─────────────────────────────────────────────────────┘
```

---

## 详细分类

### 🟢 Category 1: 直接编辑文件 (最简单)

**原则**: 无需任何业务逻辑，纯粹YAML/JSON编辑

#### 1.1 设备管理

| 操作 | 方式 | 复杂度 | 原因 |
|------|------|--------|------|
| 添加设备 | 编辑`hosts.yaml` | 极低 | 就是添加YAML条目 |
| 删除设备 | 编辑`hosts.yaml` | 极低 | 删除YAML条目 |
| 修改IP | 编辑`hosts.yaml` | 极低 | 修改YAML值 |
| 修改用户名 | 编辑`hosts.yaml` | 极低 | 修改YAML值 |
| 列出设备 | 编辑`hosts.yaml` | 极低 | 读取YAML，格式化输出 |

**实现方式**:
```python
class AdminAgent:
    def add_device(self, name: str, ip: str, username: str, **kwargs):
        """直接编辑hosts.yaml"""
        config = load_yaml(".olav/config/hosts.yaml")
        config[name] = {
            "hostname": ip,
            "username": username,
            "password": f"${{{kwargs.get('password_var', f'PASSWORD_{name}')}}}",
            "platform": kwargs.get("platform", "cisco_ios"),
        }
        save_yaml(".olav/config/hosts.yaml", config)
        return f"✓ 设备{name}已添加"
```

#### 1.2 定时任务管理

| 操作 | 方式 | 复杂度 | 原因 |
|------|------|--------|------|
| 创建任务 | 编辑`schedules.yaml` | 极低 | 添加YAML条目 |
| 删除任务 | 编辑`schedules.yaml` | 极低 | 删除YAML条目 |
| 禁用任务 | 编辑`schedules.yaml` | 极低 | 修改`enabled`字段 |
| 启用任务 | 编辑`schedules.yaml` | 极低 | 修改`enabled`字段 |
| 列出任务 | 编辑`schedules.yaml` | 极低 | 读取YAML，格式化输出 |

#### 1.3 知识库管理

| 操作 | 方式 | 复杂度 | 原因 |
|------|------|--------|------|
| 添加知识 | 编辑`*.md` | 低 | 创建Markdown文件 |
| 删除知识 | 编辑`*.md` | 极低 | 删除文件 |
| 列出知识 | 编辑`*.md` | 极低 | 列举目录 |

#### 1.4 系统配置

| 操作 | 方式 | 复杂度 | 原因 |
|------|------|--------|------|
| 修改日志级别 | 编辑`settings.json` | 极低 | 修改YAML值 |
| 修改缓存大小 | 编辑`settings.json` | 极低 | 修改YAML值 |
| 查看配置 | 编辑`settings.json` | 极低 | 读取YAML |

---

### 🟡 Category 2: 用Tool封装 (需要业务逻辑)

**原则**: 需要一些业务逻辑，但仅Admin使用，不需要做成公开命令

#### 2.1 Skill管理

| 操作 | 工具 | 原因 | 实现 |
|------|------|------|------|
| 重新加载Skill | Tool: `ReloadSkillTool` | 需要关联skill注册表 | 调用skills.reload() |
| 列出Skill | Tool: `ListSkillsTool` | 需要遍历并格式化 | 读取.olav/skills目录 |
| 查看Skill详情 | Tool: `DescribeSkillTool` | 需要解析SKILL.md | 读取SKILL.md并提取 |

**为什么做Tool?**
```
不直接编辑文件的原因:
❌ 不能直接修改文件
❌ 需要调用系统函数重新加载
❌ 需要验证Skill是否存在
❌ 需要完整的错误处理
```

**实现示例**:
```python
class ReloadSkillTool(Tool):
    """重新加载Skill"""
    
    async def execute(self, skill_name: str) -> str:
        """重新加载指定skill"""
        try:
            # 验证skill存在
            skill_path = Path(f".olav/skills/{skill_name}")
            if not skill_path.exists():
                return f"❌ Skill不存在: {skill_name}"
            
            # 调用重新加载函数
            result = await reload_skill(skill_name)
            
            return f"✓ Skill已重新加载: {skill_name}"
        except Exception as e:
            return f"❌ 重新加载失败: {str(e)}"
```

#### 2.2 系统监控和诊断

| 操作 | 工具 | 原因 | 实现 |
|------|------|------|------|
| 查看系统状态 | Tool: `SystemStatusTool` | 需要聚合多个数据源 | 读取日志+统计 |
| 查看任务历史 | Tool: `TaskHistoryTool` | 需要解析历史文件 | 读取history目录 |
| 清理日志 | Tool: `CleanupLogsTool` | 需要找出旧文件+删除 | 文件操作+时间判断 |
| 清理缓存 | Tool: `ClearCacheTool` | 需要删除cache目录 | 目录操作 |

**为什么做Tool?**
```
不直接编辑文件的原因:
❌ 不能简单地编辑文件
❌ 需要复杂的逻辑判断（如"旧于一个月"）
❌ 需要多步骤的文件操作
❌ 需要完整的错误恢复
```

**实现示例**:
```python
class CleanupLogsTool(Tool):
    """清理旧日志"""
    
    async def execute(self, days_old: int = 30) -> str:
        """清理超过days_old天的日志"""
        import glob
        from datetime import datetime, timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days_old)
        logs_dir = Path("logs")
        deleted_count = 0
        freed_space = 0
        
        for log_file in logs_dir.glob("*.log"):
            mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
            if mtime < cutoff_date:
                freed_space += log_file.stat().st_size
                log_file.unlink()
                deleted_count += 1
        
        return f"✓ 已清理日志\n- 删除文件: {deleted_count}个\n- 释放空间: {freed_space/(1024**2):.1f}MB"
```

---

### 🔵 Category 3: 复用Olav命令 (已有功能)

**原则**: 系统已经有命令，Agent直接调用，无需新增

#### 3.1 可以直接调用的Olav命令

| 操作 | Olav命令 | Admin实现 | 说明 |
|------|---------|---------|------|
| 设备连接测试 | `olav /devices` | 直接调用 | 已有一键测试 |
| Skill重新加载* | (规划中) | 等待实现 | 需要先做成命令 |

**实现方式**:
```python
class AdminAgent:
    async def reload_skill(self, skill_name: str):
        """通过Tool重新加载Skill"""
        tool = ReloadSkillTool()
        return await tool.execute(skill_name)
```

---

### 🟠 Category 4: 新增Olav命令 (高价值)

**原则**: 对用户和Agent都有价值，值得做成公开命令

#### 4.1 应该新增的命令

| Command | 功能 | 用户场景 | Admin用途 | 优先级 |
|---------|------|--------|---------|--------|
| `olav cron list` | 列出定时任务 | 用户想看所有任务 | Admin需要展示任务 | P1 |
| `olav cron run` | 立即执行任务 | 用户想手动触发任务 | Admin需要测试任务 | P1 |
| `olav skill reload` | 重新加载Skill | 用户想重新加载 | Admin在修改后需要 | P1 |
| `olav skill list` | 列出所有Skill | 用户想看Skill | Admin需要列表 | P1 |
| `olav system status` | 显示系统状态 | 用户想了解系统 | Admin打诊断 | P2 |
| `olav system clean` | 清理日志/缓存 | 用户想释放空间 | Admin维护 | P2 |
| `olav knowledge search` | 搜索知识库 | 用户想搜索知识 | Admin需要搜索 | P2 |

**为什么要做成命令?**
```
新增命令的理由:
✅ 用户也可能需要这个功能
✅ 多个Agent/自动化可能会用
✅ 便于测试和调试
✅ 清晰的输出格式
✅ 可被脚本调用

vs 仅为Admin做Tool:
❌ 无法让用户直接使用
❌ 难以集成到其他自动化中
❌ 重复实现相同逻辑
```

**实现建议**:
```bash
# 新增命令的实现流程

1. 定义命令入口 (src/olav/cli/commands.py)
   @register_command("cron")
   def cron_command(args):
       if args.action == "list":
           return list_cron_tasks()
       elif args.action == "run":
           return run_cron_task(args.name)

2. Admin通过Tool调用
   class RunCronToolOruginally定义命令
   async def execute(self, task_name: str):
       return await run_cron_task(task_name)

3. 用户也可以直接用
   $ olav cron list
   $ olav cron run backup_configs
```

---

## 最终操作清单

### ✅ Category 1: 直接编辑文件 (立即实施，无难度)

```
Device Management:
  ✅ add_device         → 编辑 .olav/config/hosts.yaml
  ✅ delete_device      → 编辑 .olav/config/hosts.yaml
  ✅ update_device      → 编辑 .olav/config/hosts.yaml
  ✅ list_devices       → 读取 .olav/config/hosts.yaml

Cron Task Management:
  ✅ create_cron        → 编辑 .olav/cron/schedules.yaml
  ✅ delete_cron        → 编辑 .olav/cron/schedules.yaml
  ✅ enable_cron        → 编辑 .olav/cron/schedules.yaml (enabled=true)
  ✅ disable_cron       → 编辑 .olav/cron/schedules.yaml (enabled=false)
  ✅ list_cron_tasks    → 读取 .olav/cron/schedules.yaml

Knowledge Management:
  ✅ add_knowledge      → 创建 .olav/knowledge/*.md
  ✅ delete_knowledge   → 删除 .olav/knowledge/*.md
  ✅ list_knowledge     → 列出 .olav/knowledge/

System Configuration:
  ✅ set_log_level      → 编辑 .olav/settings.json
  ✅ set_cache_size     → 编辑 .olav/settings.json
  ✅ show_config        → 读取 .olav/settings.json
```

### 🛠️ Category 2: 需要Tool封装 (需要1-2天开发)

```
Skill Management:
  🛠️ reload_skill       → Tool + 调用skills.reload()
  🛠️ list_skills        → Tool + 遍历.olav/skills/
  🛠️ describe_skill     → Tool + 解析SKILL.md

System Monitoring:
  🛠️ system_status      → Tool + 聚合多个数据源
  🛠️ task_history       → Tool + 读取history目录
  🛠️ cleanup_logs       → Tool + 文件系统操作
  🛠️ clear_cache        → Tool + 目录操作
```

### 📋 Category 3: 复用现有Olav命令 (无需开发)

```
Device:
  📋 test_connection    → 调用 /devices 命令
```

### ➕ Category 4: 新增Olav命令 (需要2-3天开发，高价值)

```
Priority P1 (用户和Admin都需要):
  ➕ olav cron list             → 新命令 + Admin Tool调用
  ➕ olav cron run              → 新命令 + Admin Tool调用
  ➕ olav skill reload          → 新命令 + Admin Tool调用
  ➕ olav skill list            → 新命令 + Admin Tool调用

Priority P2 (主要给Admin用，但用户也可能需要):
  ➕ olav system status         → 新命令 + Admin Tool调用
  ➕ olav system clean          → 新命令 + Admin Tool调用
  ➕ olav knowledge search      → 新命令 + Admin Tool调用
```

---

## 实现路线图 (KISS原则)

### Phase 1: 最小可行产品 (1周)

```
Week 1: File-Only Admin
├─ 实现Category 1所有操作（直接编辑文件）
│  └ 工作量: 3-4天 (各操作类似，重复度高)
├─ 测试Category 1的操作
│  └ 工作量: 1天
└─ 集成到Admin Agent
   └ 工作量: 1-2天
```

### Phase 2: 增强能力 (1-2周)

```
Week 2-3: Add Tools & Commands
├─ 实现Category 2 Tools (Skill管理、系统监控)
│  └ 工作量: 3-4天
├─ 新增Category 4 P1命令 (cron, skill)
│  └ 工作量: 2-3天
└─ 集成到Admin Agent和CLI
   └ 工作量: 1-2天
```

### Phase 3: 完整功能 (1周)

```
Week 4: Complete Implementation
├─ 新增Category 4 P2命令 (system, knowledge)
│  └ 工作量: 2-3天
├─ 完整测试所有操作
│  └ 工作量: 2-3天
└─ 文档编写
   └ 工作量: 1天
```

---

## KISS原则应用

### ❌ 不做的事

```
❌ 不创建复杂的Tool框架
   理由: 直接编辑文件就够了

❌ 不创建数据库访问层
   理由: 只编辑YAML，不访问DB

❌ 不创建权限管理系统
   理由: Dev环境不需要，可信环境

❌ 不创建UI/Web界面
   理由: CLI就够了

❌ 不创建复杂的API层
   理由: 直接函数调用就够了
```

### ✅ 只做必要的事

```
✅ YAML编辑函数 (load_yaml, save_yaml)
   → 可复用，代码少

✅ 简单的Tool包装 (仅在必要时)
   → 只封装需要业务逻辑的操作

✅ Olav命令 (仅在用户也需要时)
   → 一箭双雕，提供给用户和Admin

✅ 意图识别 (简单的LLM提示词)
   → 无需复杂的NLU框架
```

---

## 代码示例：Admin Agent实现结构

```python
class AdminAgent:
    """简化的Admin Agent实现"""
    
    # Category 1: 直接编辑YAML
    async def add_device(self, name, ip, username, **kwargs):
        config = load_yaml(".olav/config/hosts.yaml")
        config[name] = {...}
        save_yaml(".olav/config/hosts.yaml", config)
        return f"✓ 设备{name}已添加"
    
    async def create_cron(self, name, schedule, command, **kwargs):
        config = load_yaml(".olav/cron/schedules.yaml")
        config[name] = {...}
        save_yaml(".olav/cron/schedules.yaml", config)
        return f"✓ 任务{name}已创建"
    
    # Category 2: 调用Tool
    async def reload_skill(self, skill_name):
        tool = ReloadSkillTool()
        return await tool.execute(skill_name)
    
    async def system_status(self):
        tool = SystemStatusTool()
        return await tool.execute()
    
    # Category 4: 调用Olav命令
    async def cron_list(self):
        # 复用 olav cron list 命令
        return await run_command("olav cron list")
    
    # 主入口
    async def handle_request(self, user_input: str):
        intent = await self.identify_intent(user_input)
        
        # 路由到相应的操作
        if intent == "add_device":
            return await self.add_device(**params)
        elif intent == "reload_skill":
            return await self.reload_skill(**params)
        elif intent == "cron_list":
            return await self.cron_list(**params)
        # ... 其他路由
```

---

## 总结表格

| 操作类别 | 工作量 | 实现难度 | 开始时间 | 用户价值 |
|---------|--------|---------|---------|----------|
| **Category 1** (文件编辑) | 3天 | 极低 | Week 1 | 高 |
| **Category 2** (Tool) | 3-4天 | 低 | Week 2 | 中 |
| **Category 4 P1** (新命令) | 2-3天 | 中 | Week 2 | 高 |
| **Category 4 P2** (新命令) | 2-3天 | 中 | Week 3 | 中 |

**总工作量**: 约2-3周，包括测试和文档

---

**KISS设计原则验证**:

✅ **简单性**: 大部分操作就是YAML编辑，无复杂业务逻辑

✅ **必要性**: 每个操作都有明确的用途，无冗余功能

✅ **可维护性**: 代码结构清晰，容易扩展

✅ **可测试性**: 每个操作都可独立测试

✅ **可学习性**: 新开发者易于理解和修改

这确实是KISS的设计。
