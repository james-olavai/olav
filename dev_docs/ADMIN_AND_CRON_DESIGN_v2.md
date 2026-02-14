# Admin & Cron 机制设计更正

**日期**: 2026-02-14  
**版本**: v2.1 (python-crontab + Tool)

---

## 1. Admin Skill 保留理由

### 1.1 为什么不能废弃？

**olav-admin skill 的核心价值**:

```yaml
# 当前功能（.olav/skills/olav-admin/SKILL.md）
capabilities:
  - 配置备份和恢复 (backup_config, restore_config)
  - 读写 .olav/ 目录文件
  - 创建和修改 SKILL.md
  - 代码搜索和导航
  - 架构咨询（通过文档）
  
tools:
  - read_file, write_file
  - list_files, search_code
  - backup_config, restore_config
  - list_workspace_structure

references:
  - ARCHITECTURE.md
  - SUB_AGENT_DEVELOPMENT_GUIDE.md
  - SKILL_AUTHORING_GUIDE.md
  - 总计 176 KB, 6,509 行文档
```

**这些功能确实需要**：
1. ✅ **配置管理** - 用户需要备份/恢复配置
2. ✅ **Skill 定制** - 用户需要创建自定义 Skills
3. ✅ **架构查询** - 用户需要理解 OLAV 内部结构
4. ✅ **对话式管理** - 比 CLI 命令更友好（"帮我备份配置"）

### 1.2 简化策略（而非废弃）

#### 方案 A: 保留 Skill + 提供 CLI 快捷方式

```python
# src/olav/cli/admin.py

@click.group()
def admin():
    """OLAV system administration commands"""
    pass

@admin.command()
def backup():
    """Backup OLAV configuration
    
    Equivalent to: olav ask "backup my configuration"
    But faster: direct function call without LLM
    """
    from olav.lib.admin import backup_config
    
    print("🔄 Backing up OLAV configuration...")
    result = backup_config()
    
    if result["status"] == "success":
        print(f"✅ Backup created: {result['file']}")
        print(f"   Size: {result['size']}")
        print(f"   Files: {result['files_count']}")
    else:
        print(f"❌ Backup failed: {result['error']}")

@admin.command()
@click.argument('backup_file')
def restore(backup_file: str):
    """Restore OLAV configuration from backup
    
    Example: olav admin restore 2026-02-14_120000.tar.gz
    """
    from olav.lib.admin import restore_config
    
    print(f"🔄 Restoring from {backup_file}...")
    result = restore_config(backup_file)
    
    if result["status"] == "success":
        print(f"✅ Restored successfully")
        print(f"   Files restored: {result['files_count']}")
    else:
        print(f"❌ Restore failed: {result['error']}")

@admin.command()
def status():
    """Show OLAV system status"""
    from olav.lib.admin import get_system_status
    
    status = get_system_status()
    
    print("📊 OLAV System Status")
    print(f"   Version: {status['version']}")
    print(f"   Database: {status['database']['path']} ({status['database']['size']})")
    print(f"   Skills: {status['skills']['count']} loaded")
    print(f"   LLM: {status['llm']['provider']} - {status['llm']['model']}")
```

**使用体验**:
```bash
# 快速命令（不经过 LLM）
olav admin backup          # < 1 second
olav admin restore xxx.tar.gz
olav admin status

# 对话式管理（经过 LLM，更智能）
olav ask "备份我的配置"
olav ask "创建一个新的 netbox skill"
olav ask "为什么我的 OSPF 查询很慢？查看架构文档"
```

**优势**:
- ✅ CLI 命令快速、确定性（< 1s）
- ✅ 对话式管理智能、灵活（理解自然语言）
- ✅ 保留 admin skill 的文档查询能力

#### 方案 B: 纯 CLI 命令（不推荐）

```python
# 如果废弃 olav-admin skill，所有功能都变成 CLI 命令
# 问题：失去对话式管理能力

# ❌ 无法做到：
"帮我创建一个 skill 来查询 NetBox 的 IP 分配"
"为什么我的数据库查询很慢？查看优化文档"
"备份配置，但排除日志文件"
```

### 1.3 最终决策

✅ **保留 olav-admin skill** + 提供 CLI 快捷方式

```
.olav/skills/
├── olav-admin/           # ✅ 保留
│   ├── SKILL.md          # 对话式管理 + 文档查询
│   ├── prompts/
│   └── tools/
```

**更新后的 Skills 清单**:
```
✅ network-query/          # 数据库查询
✅ network-cli/            # CLI 命令执行
✅ network-expert/         # 故障诊断专家
✅ network-inspection/     # 健康检查
✅ network-snapshot/       # 数据采集
✅ olav-admin/             # 系统管理（保留！）
✅ shared/                 # 共享资源

❌ olav-guard/             # Guard 机制已废弃
❌ olav-orchestrator/      # 单 Agent 架构不需要
❌ orchestrator/           # 重复目录
```

---

## 2. Cron 机制简化设计

### 2.1 为什么不需要 APScheduler？

**APScheduler 的问题**:
- ❌ **额外依赖** - 需要安装 Python 包
- ❌ **后台进程** - 需要 `olav scheduler` 一直运行
- ❌ **监控复杂** - 进程意外退出需要重启
- ❌ **资源占用** - Python 进程常驻内存
- ❌ **过度工程** - 对于简单的 daily inspection 来说

**系统 cron 的优势**:
- ✅ **系统级别** - Linux/macOS 内置，久经考验
- ✅ **零依赖** - 不需要额外安装
- ✅ **标准运维** - 所有运维人员都熟悉
- ✅ **监控方便** - `crontab -l` 查看，日志清晰
- ✅ **资源友好** - 只在执行时占用资源

### 2.2 简化后的架构

```
┌─────────────────────────────────────────────┐
│   System Cron (crond)                       │
│   0 6 * * * /path/to/daily_inspection.sh    │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Bash Script: daily_inspection.sh          │
│   - Pre-flight checks                       │
│   - Lock file (prevent concurrent)          │
│   - Timeout control                         │
│   - Logging + notification                  │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   OLAV CLI: uv run olav inspect             │
│   - Load workflow definition                │
│   - Create Agent with skill                 │
│   - Execute stages sequentially             │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Agent (TodoListMiddleware)                │
│   - Parse workflow stages                   │
│   - Execute tools (nornir, sql)             │
│   - Generate report                         │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Output                                    │
│   - exports/reports/snapshots/YYYYMMDD.md  │
│   - .olav/logs/inspection_YYYYMMDD.log     │
└─────────────────────────────────────────────┘
```

## 3. Cron 定时任务简化方案

### 3.1 为什么选择 python-crontab？

#### 对比方案

| 维度 | python-crontab | bash 脚本 | APScheduler |
|------|----------------|-----------|-------------|
| **编程式管理** | ✅ Python API | ❌ 手动编辑 | ✅ Python API |
| **与架构统一** | ✅ Tool 调用 | ❌ 外部脚本 | ⚠️ 常驻进程 |
| **Agent 可控** | ✅ LLM调用tool | ❌ 需执行命令 | ✅ 但复杂 |
| **依赖复杂度** | 低（1个包）| 零 | 中（多个包）|
| **资源占用** | 无（按需）| 无 | 常驻进程 |
| **适用场景** | **OLAV 最佳** | 运维脚本 | 复杂调度 |

#### OLAV 场景优势

使用 `python-crontab` + `inspection.py` tool：

1. **统一架构** - 定时任务作为 Tool，与其他功能一致
2. **Agent 可管理** - LLM可直接调用 `manage_inspection_schedule` tool
3. **编程式配置** - 无需手动编辑 crontab，通过代码管理
4. **保持简单** - 不引入常驻进程，仍使用系统 cron

**结论**：
- ✅ `python-crontab` - 编程式管理，与 OLAV 架构统一
- ❌ bash 脚本 - 无法被 Agent 直接调用
- ❌ APScheduler - 引入常驻进程，over-engineering

### 3.2 实现方案

#### 架构图

```
┌─────────────────────────────────────────────┐
│   用户输入（三种方式）                       │
├─────────────────────────────────────────────┤
│ 1. 对话式: "设置每天6点执行检查"            │
│ 2. CLI: olav admin schedule ...             │
│ 3. Tool stdin: echo '{...}' | python3 ...   │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   Tool: manage_inspection_schedule          │
│   Location: .olav/tools/inspection.py       │
├─────────────────────────────────────────────┤
│   Actions:                                  │
│   - schedule: 创建/更新定时任务             │
│   - unschedule: 删除定时任务                │
│   - list: 列出所有定时任务                  │
│   - run: 立即执行检查                       │
│   - status: 查看执行历史                    │
│   - logs: 查看日志内容                      │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   python-crontab Library                    │
│   - CronTab(user=True)                      │
│   - job.setall(schedule)                    │
│   - cron.write()                            │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│   System Crontab                            │
│   OLAV-daily-inspection: 0 6 * * *          │
│   Command: cd ... && uv run olav inspect... │
└─────────────────────────────────────────────┘
```

#### Tool 实现（已创建）

```python
# .olav/tools/inspection.py（已创建）
from crontab import CronTab
from langchain_core.tools import tool

@tool
def manage_inspection_schedule(
    action: str,
    workflow: str = "daily-inspection",
    schedule: str | None = None,
    enabled: bool = True,
    days: int = 7
) -> dict:
    """Manage network inspection schedules.
    
    Actions:
        - schedule: Create/update inspection schedule
        - unschedule: Remove inspection schedule
        - list: List all scheduled inspections
        - run: Execute inspection immediately
        - status: Get inspection status and history
        - logs: View recent inspection logs
    """
    cron = CronTab(user=True)
    
    if action == "schedule":
        job = cron.new(
            command=f"cd {PROJECT_ROOT} && uv run olav inspect {workflow}",
            comment=f"OLAV-{workflow}"
        )
        job.setall(schedule)
        job.enable(enabled)
        cron.write()
        
        return {
            "status": "success",
            "message": f"Scheduled {workflow} at {schedule}",
            "next_run": str(job.schedule(date_from=datetime.now()).get_next())
        }
    
    # ... 其他actions实现
```

### 3.3 使用方式

#### 方式 1: 通过 Agent（对话式）

```bash
# 用户输入自然语言
uv run olav ask "设置每天早上6点执行网络检查"

# Agent 内部调用
→ manage_inspection_schedule(
    action="schedule",
    workflow="daily-inspection",
    schedule="0 6 * * *"
  )

# 返回结果
✅ Scheduled daily-inspection at 0 6 * * *
   Next run: 2026-02-15 06:00:00
```

#### 方式 2: 通过 CLI（快捷命令）

```bash
# 设置定时任务
olav admin schedule daily-inspection "0 6 * * *"

# 立即执行
olav admin inspect run

# 查看状态
olav admin inspect status

# 查看日志
olav admin inspect logs --days 7

# 列出所有任务
olav admin inspect list
```

#### 方式 3: 直接调用 Tool（调试）

```bash
# 设置定时任务
echo '{"action":"schedule","schedule":"0 6 * * *"}' | python3 .olav/tools/inspection.py

# 列出任务
echo '{"action":"list"}' | python3 .olav/tools/inspection.py

# 立即执行
echo '{"action":"run"}' | python3 .olav/tools/inspection.py

# 查看状态
echo '{"action":"status","days":7}' | python3 .olav/tools/inspection.py
```

### 3.4 优势总结

#### vs Bash 脚本

| 特性 | python-crontab Tool | Bash 脚本 |
|------|-------------------|-----------|
| Agent 可调用 | ✅ 直接调用 | ❌ 需 subprocess |
| 编程式管理 | ✅ API | ❌ 文本编辑 |
| 状态查询 | ✅ 内置 | ❌ 需解析输出 |
| 错误处理 | ✅ 结构化 | ❌ 退出码 |
| 与架构统一 | ✅ Tool 模式 | ❌ 外部脚本 |

#### vs APScheduler

| 特性 | python-crontab | APScheduler |
|------|----------------|-------------|
| 运行模式 | 按需调用 | 常驻进程 |
| 资源占用 | 零 | 持续占用 |
| 依赖数量 | 1 个包 | 多个包 |
| 监控复杂度 | crontab -l | 需自定义 |
| 适合场景 | 固定时间 | 动态调度 |

**OLAV 场景结论**: python-crontab 是最优方案
- ✅ 编程式管理
- ✅ Agent 可控
- ✅ 架构统一
- ✅ 保持简单
- ✅ 零运行开销

## 4. 实施清单

### 4.1 依赖安装

- [ ] 更新 `pyproject.toml`：
  ```toml
  [project.dependencies]
  python-crontab = "^3.0.0"
  ```
- [ ] 执行：`uv sync`

### 4.2 Tool 创建

- [x] 创建 `.olav/tools/inspection.py`
  - [x] `manage_inspection_schedule` tool
  - [x] Actions: schedule, unschedule, list, run, status, logs
  - [x] 使用 `python-crontab` 管理系统 cron
  - [x] 支持 stdin JSON 和 LangChain tool 两种模式
  - [x] Lock file 防止并发
  - [x] 超时控制（30分钟）
  - [x] 日志记录到 `.olav/logs/`
- [ ] 注册到 `.olav/AGENTS.md`（Agent 配置）
- [ ] 创建 `.olav/tools/README.md`（Tool 使用文档）

### 4.3 Admin Skill 保留

- [ ] 保留 `.olav/skills/olav-admin/` 完整目录
- [ ] 确保 176KB 参考文档可访问
- [ ] 测试 backup/restore 功能
- [ ] 测试 skill 创建功能
- [ ] 添加 `manage_inspection_schedule` 到 admin 可用工具

### 4.4 Admin CLI 快捷命令

- [ ] 实现 `src/olav/cli/admin.py`
- [ ] 添加命令：
  - `olav admin backup` - 快速备份
  - `olav admin restore <timestamp>` - 快速恢复
  - `olav admin status` - 系统状态
  - `olav admin skills` - 技能列表
  - `olav admin schedule <workflow> <cron>` - 设置定时任务
  - `olav admin inspect run` - 立即执行检查
  - `olav admin inspect status` - 检查状态
  - `olav admin inspect list` - 列出所有定时任务
  - `olav admin inspect logs` - 查看日志
- [ ] 所有命令封装为对 tool 的直接调用
- [ ] 测试所有命令 < 1 秒执行

### 4.5 测试验证

#### Tool 独立测试

```bash
# 设置定时任务
echo '{"action":"schedule","schedule":"0 6 * * *"}' | python3 .olav/tools/inspection.py

# 列出任务
echo '{"action":"list"}' | python3 .olav/tools/inspection.py

# 立即执行
echo '{"action":"run"}' | python3 .olav/tools/inspection.py

# 查看状态
echo '{"action":"status","days":7}' | python3 .olav/tools/inspection.py

# 验证 crontab
crontab -l | grep OLAV
```

#### Agent 调用测试

```bash
# 对话式管理
uv run olav ask "设置每天早上6点执行网络检查"
uv run olav ask "立即执行网络检查"
uv run olav ask "查看定时任务状态"
uv run olav ask "列出所有定时任务"
```

#### CLI 命令测试

```bash
# 快捷命令
olav admin schedule daily-inspection "0 6 * * *"
olav admin inspect run
olav admin inspect status
olav admin inspect list
olav admin inspect logs --days 7
```

#### E2E 测试

- [ ] 创建 `tests/e2e/test_inspection_tool.py`
- [ ] 测试场景：
  - Schedule创建成功
  - List返回正确任务
  - Run执行成功并生成报告
  - Status返回历史记录
  - Logs返回日志内容
  - Unschedule删除任务

### 4.6 文档更新

- [x] 更新 `ADMIN_AND_CRON_DESIGN_v2.md`（本文档）
- [ ] 更新 `DEEPAGENTS_SIMPLIFICATION_PLAN.md`
  - [ ] 修改工具列表： 6 → 4 tools（加入 inspection.py）
  - [ ] 更新 Cron 机制： bash脚本 → python-crontab tool
- [ ] 更新 `OLAV_DIRECTORY_REFACTOR_ANALYSIS.md`
  - [ ] 工具重构计划： 包含 inspection.py
- [ ] 创建 `.olav/tools/README.md`

### 4.7 部署流程

```bash
# 1. 安装依赖
uv sync

# 2. 测试 tool
echo '{"action":"list"}' | python3 .olav/tools/inspection.py

# 3. 设置定时任务
olav admin schedule daily-inspection "0 6 * * *"

# 4. 验证安装
crontab -l | grep OLAV

# 5. 测试手动执行
olav admin inspect run

# 6. 查看日志
tail -f .olav/logs/cron.log
```

### 4.8 验收标准

- [ ] ✅ `python-crontab` 依赖安装成功
- [ ] ✅ `inspection.py` tool 可独立运行
- [ ] ✅ Agent 可通过自然语言调用
- [ ] ✅ CLI 命令全部实现且 < 1秒
- [ ] ✅ Crontab 正确创建任务
- [ ] ✅ 定时任务按时执行
- [ ] ✅ 日志正确记录到 `.olav/logs/`
- [ ] ✅ 报告正确生成到 `exports/reports/snapshots/`
- [ ] ✅ Admin skill 保留且功能正常
- [ ] ✅ E2E 测试全部通过
- [ ] ✅ 文档全部更新完毕
0 1 * * * find $OLAV_HOME/.olav/logs -name "inspection_*.log" -mtime +7 -delete

EOF

echo "✅ Cron jobs installed"
echo "📋 To view: crontab -l"
echo "📝 To edit: crontab -e"
```

### 2.5 监控和维护

#### 查看 Cron 执行状态

```bash
# 查看最近执行日志
tail -50 .olav/logs/cron.log

# 查看今天的 inspection 日志
cat .olav/logs/inspection_$(date +%Y%m%d).log

# 查看今天的报告
cat exports/reports/snapshots/$(date +%Y%m%d).md
```

#### 调试 Cron 问题

```bash
# 1. 检查 crontab 配置
crontab -l

# 2. 手动执行测试
./scripts/daily_inspection.sh

# 3. 检查系统 cron 日志
# Ubuntu/Debian
sudo tail -f /var/log/syslog | grep CRON

# CentOS/RHEL
sudo tail -f /var/log/cron

# 4. 检查脚本权限
ls -la scripts/daily_inspection.sh  # 应该是 -rwxr-xr-x
```

#### 清理旧日志

```bash
# 手动清理 7 天前的日志
find .olav/logs -name "inspection_*.log" -mtime +7 -delete

# 或添加到 cron（已包含在模板中）
0 1 * * * find $OLAV_HOME/.olav/logs -name "inspection_*.log" -mtime +7 -delete
```

---

## 3. 对比总结

### 3.1 Admin 管理方式对比

| 方式 | 速度 | 灵活性 | 智能性 | 推荐场景 |
|------|------|--------|--------|----------|
| **CLI 命令** | 快（< 1s） | 低 | 低 | 日常备份、状态查询 |
| **对话式（Skill）** | 慢（3-5s） | 高 | 高 | Skill 创建、架构查询 |

**最佳实践**: 两者结合
```bash
# 快速操作用 CLI
olav admin backup
olav admin status

# 复杂操作用对话
olav ask "创建一个查询 NetBox IP 的 skill"
olav ask "为什么我的 BGP 查询慢？查看优化建议"
```

### 3.2 Cron 调度方式对比

| 方式 | 复杂度 | 依赖 | 监控 | 资源 | 推荐 |
|------|--------|------|------|------|------|
| **系统 Cron** | 低 | 0 | 简单 | 低 | ✅ 强烈推荐 |
| **APScheduler** | 高 | 1 包 | 复杂 | 中 | ❌ 过度工程 |
| **Celery** | 高 | 2+ 包 | 复杂 | 高 | ❌ 绝对过度 |

**推荐**: 系统 Cron + Bash 脚本
- 简单、可靠、零依赖
- 符合运维标准
- 调试方便

---

## 4. 实施清单

### Phase 1: Admin CLI 实现

- [ ] 实现 `src/olav/lib/admin.py`（backup/restore/status）
- [ ] 实现 `src/olav/cli/admin.py`（CLI 命令）
- [ ] 保留 `olav-admin` skill（对话式管理）
- [ ] 测试两种方式互通性

### Phase 2: Cron 脚本部署

- [x] 创建 `scripts/daily_inspection.sh` ✅
- [ ] 测试手动执行
- [ ] 安装 cron 任务（`crontab -e`）
- [ ] 配置 Webhook 通知（可选）
- [ ] 验证日志输出

### Phase 3: 监控和维护

- [ ] 设置日志清理 cron
- [ ] 文档化故障排查流程
- [ ] 配置告警机制（失败时发送邮件/Slack）

---

**版本**: v2.0  
**最后更新**: 2026-02-14  
**核心变更**:
1. ✅ Admin skill 保留（不是废弃）
2. ✅ Cron 机制简化（系统 cron + bash 脚本）
