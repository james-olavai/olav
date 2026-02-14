# Admin Agent 简化设计 (v3.0 - 综合规范版)

**原则**: KISS - 直接编辑文件，不做CLI中间层
**更新日期**: 2026-02-12
**状态**: 规范版 (包含所有设计决策、安全分析、权限清单)

---

## 核心理念

```
用户自然语言输入
    ↓
Agent意图识别 (简单)
    ↓
直接编辑配置文件 (YAML/JSON)
    ↓
完成
```

**不需要**:
- ❌ 复杂的CLI命令集  
- ❌ Tool层的包装和抽象
- ❌ 参数解析和验证层
- ❌ 权限管理（Dev环境）

**只需要**:
- ✅ 简单的意图识别 (LLM)
- ✅ 直接的文件读写
- ✅ YAML/JSON编辑
- ✅ 可视化的日志和审计

---

## Admin Agent vs Orchestrator Agent 职责分工

### Admin Agent = 系统配置管理员（有安全边界）

```
✅ 安全操作 (DO - SAFE):
  • 设备管理 (add/delete/update device)
  • 定时任务 (create/delete/modify cron task)
  • 知识库管理 (add/delete/search knowledge)
  • 系统配置 (modify system settings)
  • 系统监控 (view status/logs/metrics, 仅读)
  • 日志清理 (cleanup old logs)
  • 缓存清理 (clear cache)
  • Skill重新加载 (reload skill - 不修改代码)

⚠️ 条件操作 (DO - WITH CONFIRMATION):
  • 执行预定脚本 (run predefined scripts in .olav/scripts/)
  • 需要用户确认

❌ 禁止操作 (DON'T - FORBIDDEN):
  • 数据库修改 (modify main.duckdb - core data)
  • 备份删除 (delete backup files - disaster recovery asset)
  • Skill代码修改 (modify skill code - should use git)
  • 任意Shell执行 (execute arbitrary commands - security risk)
  • 敏感信息修改 (modify passwords/api keys)
  • 业务查询 → Orchestrator做
```

### Orchestrator Agent = 业务查询执行者

```
✅ 职责 (DO):
  • 理解业务查询 ("有多少台设备?")
  • 规划执行步骤
  • 调用skills获取数据
  • 返回查询结果

❌ 不管 (DON'T):
  • 系统配置管理 → Admin做
  • 设备清单维护
  • 定时任务管理
  • 知识库管理
```

### 交互流程

```
User: "添加设备R1" 
    ↓
Admin Agent: 编辑hosts.yaml ✓
    ↓
User: "R1的BGP邻居有哪些?"
    ↓
Orchestrator Agent: 查询数据库 ✓
```

---

## Admin Agent 职责范围

### 1. 设备管理 (Device Management)

**用户说**: "添加设备R1，IP是10.0.0.1，用户名是admin"

**Agent做什么**:
```
1. 识别意图: add_device
2. 提取参数: 
   - name: R1
   - ip: 10.0.0.1
   - username: admin
3. 编辑 .olav/config/hosts.yaml:
   
   R1:
     hostname: 10.0.0.1
     username: admin
     password: ${PASSWORD_R1}  # 从环境变量
     platform: cisco_ios       # 可选，默认
     
4. 返回: "✓ 设备R1已添加到inventory"
```

**支持的操作**:
- 添加设备 (add_device)
- 删除设备 (delete_device)  
- 修改设备参数 (update_device)
- 列出所有设备 (list_devices)

**文件**: `.olav/config/hosts.yaml`

---

### 2. 定时任务管理 (Cron Tasks)

**用户说**: "每晚8点备份所有设备的running config"

**Agent做什么**:
```
1. 识别意图: create_cron_task
2. 提取参数:
   - name: backup_running_config_nightly
   - schedule: "0 20 * * *"  # 每晚8点
   - command: "export running-config"
   - devices: all
   
3. 编辑 .olav/cron/schedules.yaml:
   
   backup_running_config_nightly:
     schedule: "0 20 * * *"
     command: "export running-config"
     devices: all
     enabled: true
     description: "Backup all devices running config nightly"
     created_at: "2026-02-12T12:30:00Z"
     
4. APScheduler会自动加载这个任务
5. 返回: ✓ 定时任务已创建
```

**支持的操作**:
- 创建任务 (create_cron)
- 删除任务 (delete_cron)
- 启用/禁用任务 (enable/disable_cron)
- 立即运行任务 (run_cron_now)
- 列出所有任务 (list_cron_tasks)

**文件**: `.olav/cron/schedules.yaml`

---

### 3. Skill管理

**用户说**: "重新加载command-learner skill"

**Agent做什么**:
```
1. 识别意图: reload_skill
2. 提取参数: skill_name = "command-learner"
3. 调用核心函数: reload_skill("command-learner")
4. 返回: ✓ Skill已重新加载
```

**支持的操作**:
- 重新加载Skill (reload_skill)
- 列出所有Skill (list_skills)
- 获取Skill详情 (describe_skill)

**说明**: Skill管理不需要编辑文件，直接调用核心函数

---

### 4. 知识库管理 (Knowledge Base)

**用户说**: "添加一个关于BGP的知识"

**Agent做什么**:
```
1. 识别意图: add_knowledge
2. 提取参数:
   - topic: "BGP Configuration"
   - content: "..."
   
3. 编辑 .olav/knowledge/bgp_config.md:
   
   # BGP Configuration
   
   ...content...
   
   ---
   Created: 2026-02-12T12:30:00Z
   Tags: bgp, routing, protocol
   
4. 自动向量化并添加到知识库索引
5. 返回: ✓ 知识已添加
```

**文件**: `.olav/knowledge/*.md`

---

## Admin Agent 实现框架

```python
class AdminAgent:
    """简化的管理Agent - 直接编辑文件"""
    
    async def handle_request(self, user_input: str):
        """处理用户请求"""
        
        # Step 1: 意图识别 (简单的提示词)
        intent = await self.identify_intent(user_input)
        
        # Step 2: 参数提取
        params = await self.extract_parameters(user_input, intent)
        
        # Step 3: 执行相应操作
        if intent == "add_device":
            return await self.add_device(**params)
        elif intent == "create_cron":
            return await self.create_cron_task(**params)
        elif intent == "reload_skill":
            return await self.reload_skill(**params)
        elif intent == "add_knowledge":
            return await self.add_knowledge(**params)
        else:
            return "❌ 无法识别请求"
    
    async def add_device(self, name: str, ip: str, username: str, **kwargs):
        """直接编辑hosts.yaml"""
        
        # 读取现有配置
        config = load_yaml(".olav/config/hosts.yaml")
        
        # 添加新设备
        config[name] = {
            "hostname": ip,
            "username": username,
            "password": f"${{PASSWORD_{name}}}",  # 从env读取
            "platform": kwargs.get("platform", "cisco_ios"),
        }
        
        # 保存回文件
        save_yaml(".olav/config/hosts.yaml", config)
        
        return f"✓ 设备{name}已添加"
    
    async def create_cron_task(self, name: str, schedule: str, command: str, **kwargs):
        """直接编辑cron/schedules.yaml"""
        
        config = load_yaml(".olav/cron/schedules.yaml")
        
        config[name] = {
            "schedule": schedule,
            "command": command,
            "devices": kwargs.get("devices", "all"),
            "enabled": True,
            "description": kwargs.get("description", ""),
            "created_at": datetime.now().isoformat(),
        }
        
        save_yaml(".olav/cron/schedules.yaml", config)
        
        # APScheduler会自动加载
        return f"✓ 定时任务{name}已创建"
```

---

## 文件结构

```
.olav/
├── config/
│   ├── hosts.yaml           # 设备清单 (Agent编辑)
│   └── settings.json        # 系统设置
│
├── cron/
│   ├── schedules.yaml       # 定时任务定义 (Agent编辑)
│   ├── logs/                # 执行日志
│   │   └── backup_running_config_nightly.log
│   └── history/             # 历史记录
│       └── 2026-02-12/
│
├── knowledge/               # 知识库 (Agent编辑)
│   ├── bgp_*.md
│   ├── ospf_*.md
│   └── index.json           # 向量索引
│
└── skills/olav-admin/
    └── SKILL.md             # Admin Agent定义
```

---

## 示例对话

### 示例1: 添加设备

```
User: /admin 添加设备R2，IP是10.0.0.2，用户名是admin

Agent Step 1 (意图识别):
→ Intent: add_device
→ 参数: name=R2, ip=10.0.0.2, username=admin

Agent Step 2 (编辑文件):
→ 修改 .olav/config/hosts.yaml:
  - 读取现有配置
  - 添加R2条目
  - 保存回文件

Agent Step 3 (确认):
✓ 设备R2已添加到inventory
✓ 地址: 10.0.0.2
✓ 用户名: admin
✓ 密码: 从环境变量 PASSWORD_R2 读取
```

### 示例2: 创建定时任务

```
User: /admin 每天凌晨1点导出所有interface信息到CSV

Agent Step 1 (意图识别):
→ Intent: create_cron_task
→ 参数:
  - schedule: "0 1 * * *"
  - command: "export interface info to csv"
  - devices: all
  - name: export_interface_info_daily

Agent Step 2 (编辑文件):
→ 修改 .olav/cron/schedules.yaml:
  export_interface_info_daily:
    schedule: "0 1 * * *"
    command: "export interface info to csv"
    devices: all
    enabled: true

Agent Step 3 (确认):
✓ 定时任务已创建
✓ 下次执行: 明天凌晨1点00分
✓ Cron表达式: 0 1 * * *
```

### 示例3: 添加知识

```
User: /admin 添加关于BGP邻居故障排查的知识

Agent Step 1 (意图识别):
→ Intent: add_knowledge
→ 参数: topic=BGP邻居故障排查

Agent Step 2 (与用户交互):
Agent: 请提供关于BGP邻居故障排查的详细信息

User: 
常见原因有：
1. MTU不匹配
2. AS号配置错误
3. 路由器ID冲突
...

Agent Step 3 (编辑文件):
→ 创建 .olav/knowledge/bgp_neighbor_troubleshooting.md
→ 添加用户提供的内容
→ 自动向量化并索引

Agent Step 4 (确认):
✓ 知识已添加: bgp_neighbor_troubleshooting
✓ 已向量化并索引
```

---

## 核心优势

| 方面 | 优势 |
|-----|------|
| **简洁性** | 直接编辑YAML，无需复杂的Tool包装 |
| **职责清晰** | Admin管配置，Orchestrator管查询，边界明确 |
| **安全性** | 有明确的权限边界，禁止危险操作 |
| **可理解** | 配置文件人类可读，易于审查 |
| **可版本控制** | 配置文件可以Git提交，有完整历史 |
| **可审计** | 文件修改有清晰的日志 |
| **可恢复** | 危险操作被禁止，安全操作都可回滚 |
| **灵活性** | 用户也可以手动编辑配置 |
| **无学习曲线** | 无需学习复杂的API或命令 |

---

## 实现优先级 (Phase)

| Phase | 功能 | 工作量 | 时间 |
|-------|------|--------|------|
| P1 | Device管理 (add/delete/update) | 中 | 2天 |
| P2 | Cron任务管理 | 中 | 2天 |
| P3 | Knowledge管理 | 小 | 1天 |
| P4 | Skill管理 | 小 | 1天 |

---

## 设计决策

**Q0: Admin Agent的核心职责是什么？**

A: 管理OLAV系统本身，而不是网络业务。职责范围：
- ✅ 系统配置 (hosts.yaml, schedules.yaml, settings.json)
- ✅ 知识管理 (knowledge base add/delete/search)
- ✅ 监控维护 (status, logs, cleanup)
- ❌ 业务查询 (由Orchestrator负责)
- ❌ 网络设备配置 (由用户或具体skill负责)

**Q1: 为什么Agent可以直接编辑文件？**

A: Dev环境中，Agent是可信的执行环境。用户已经通过自然语言认可了操作。生产环境可以添加审批流程。

**Q2: 密码/敏感信息如何处理？**

A: 
- 不保存在YAML中
- 使用环境变量: `PASSWORD_R1`, `PASSWORD_R2` 等
- 或使用密钥管理系统（未来）

**Q3: 如何防止Agent误操作？**

A: 
- 提示词明确指导，降低理解错误率
- 关键操作可要求确认（未来增强）
- Git版本控制，可随时回滚

**Q4: YAML格式修改后APScheduler如何重新加载？**

A: 
- APScheduler定期扫描schedules.yaml (每分钟)
- 或Agent修改后主动调用reload()函数
- 或通过inotify监听文件变化（Linux）

**Q5: Admin Agent和Orchestrator Agent如何协作？**

A: 严格分工：
```
User Question
    ↓
包含"add device"或"create task"? 
    → YES: Admin Agent (编辑配置)
    → NO: Orchestrator Agent (执行查询)
```

**Q6: 为什么Agent不能修改Skill代码？**

A: Skill修改本质上是代码修改
```
❌ 不应该:
  Agent修改 → 可能引入bug → 无法回滚 → 难以追踪
  User: "支持HP设备吧"
  Agent: 修改network-cli/tools/cli_executor.py → 系统崩溃

✅ 正确流程:
  1. 用户: "需要支持HP设备"
  2. Agent: "需要修改skill代码，请提交PR或联系开发"
  3. 开发者: 修改code → 测试 → git commit → Agent reload
  4. Agent: 重新加载Skill (仅加载SKILL.md配置)
```

**Q7: 为什么不能执行任意Shell命令？**

A: 太危险，且无法追踪
```
❌ 不应该:
  User: "修复数据库连接"
  Agent: 执行 rm -rf /some/path
  结果: 删错了，无法回滚

✅ 条件允许:
  - 预定义脚本: .olav/scripts/repair_cache.py (代码审核过)
  - 需要用户确认
  - 脚本被版本控制
  - 有完整执行日志
```

**Q8: 为什么数据库和备份不能修改？**

A: 这是系统的核心资产
```
资产等级:
  🔴 核心数据库 (main.duckdb) - 任何修改都是灾难
  🔴 备份文件 (backup_*.tar) - 灾难恢复的最后保障
  🟡 配置文件 (hosts.yaml) - 可以恢复，Git追踪
  🟢 日志 (logs/) - 可以重新生成
  🟢 缓存 (cache/) - 可以重建
  
限制:
  ❌ Agent无法修改: 数据库, 备份
  ✅ Agent可以修改: 配置文件, 知识库
  ✅ Agent可以清理: 日志, 缓存
```

---

## 下一步

1. ✅ 完成设计文档 (v3.0 - 已包含所有设计决策)
2. ⏳ 参考 dev_doc/ADMIN_AGENT_DEVELOPMENT_PLAN.md 执行Phase 1-3开发
3. ⏳ 参考 dev_doc/ADMIN_AGENT_CODE_ORGANIZATION.md 了解代码组织
4. ⏳ 参考 dev_doc/CODE_CLEANUP_ANALYSIS.md 理解代码清理计划

**文档导航**:
- 本文件: 核心设计规范 (参考此文件了解设计理念和安全边界)
- CODE_ORGANIZATION.md: 代码应该怎么放 (参考此文件了解文件结构)
- DEVELOPMENT_PLAN.md: 怎么开发 (参考此文件了解实现步骤)
- CODE_CLEANUP_ANALYSIS.md: 代码清理 (参考此文件了解如何避免冗余)

---

## 安全检查框架

Admin Agent执行操作前必须通过三层安全检查：

```python
# Pseudo Code
def handle_request(user_input):
    # 第1层: 意图识别 + 安全分类
    intent = llm_identify_intent(user_input)
    
    # 检查是禁止操作吗？
    if intent in FORBIDDEN_INTENTS:
        return "❌ 禁止操作"
    
    # 是否需要用户确认？
    if intent in CONDITIONAL_INTENTS:
        return "确认执行? (y/n)"
    
    # 第2层: 文件路径检查（仅针对文件操作）
    if is_file_operation(intent):
        target_path = extract_file_path(intent)
        if not is_allowed_path(target_path):
            return "❌ 禁止操作该文件"
    
    # 第3层: 内容安全检查（仅针对脚本执行）
    if is_script_execution(intent):
        script_path = extract_script_path(intent)
        if not is_allowed_script(script_path):
            return "❌ 禁止执行该脚本"
        if contains_dangerous_keywords(script_content):
            return "❌ 脚本包含危险命令"
    
    # 通过所有检查，执行操作
    return execute_operation(intent)
```

## 权限范围清单

### 🟢 允许修改

```
✅ .olav/config/hosts.yaml        (设备清单)
✅ .olav/config/settings.json     (系统设置)
✅ .olav/cron/schedules.yaml      (定时任务)
✅ .olav/knowledge/*.md           (知识库)
✅ .olav/cache/                   (缓存 - 可清理)
✅ logs/                           (日志 - 可清理)
```

### 🔴 严格禁止

```
❌ .olav/db/main.duckdb          (核心数据库)
❌ backup_*.tar                   (备份文件 - 灾难恢复)
❌ .olav/skills/*/                (Skill代码 - 使用Git)
❌ src/                            (Framework代码)
❌ config/settings.py             (系统框架配置)
```

### ⚠️ 条件执行

```
⚠️ .olav/scripts/*.py            (需要用户确认)
⚠️ Shell命令                      (禁止 - 使用脚本)
⚠️ Environment变量修改            (限制特定变量)
```

---

**设计哲学**: 

Admin Agent不是"超级AI"，而是**有明确权限边界的配置编辑助手**。它的强大之处在于：
- ✅ 理解简单但明确的用户意图
- ✅ 直接修改YAML/JSON配置文件（安全的操作）
- ✅ 禁止所有危险操作（数据库、备份、代码、任意Shell）
- ✅ 让OLAV核心系统处理复杂逻辑
- ✅ 保持职责明确、易于维护、可完全追踪

这样比起"万能的Agent"更简洁、更安全、更易维护。同时通过三层安全检查确保不会误操作核心资产。
