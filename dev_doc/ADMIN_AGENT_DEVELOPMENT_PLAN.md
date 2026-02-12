# Admin Agent 开发计划

**基于现有代码库的实际开发方案**
**日期**: 2026-02-12 (v3.0 - 已清理冗余)
**目标**: 为Admin Agent实现必要的工具和命令

---

## 📚 文档导航

**开发前必读** (选择适合你的角色):

| 角色 | 读什么 | 为什么 |
|-----|--------|--------|
| **架构师** | ADMIN_AGENT_SIMPLIFIED_DESIGN.md (v3.0) | 了解整体设计和安全边界 |
| **开发者** | 本文件 (DEVELOPMENT_PLAN.md v3.0) | 知道具体怎么做 |
| **代码审查** | ADMIN_AGENT_CODE_ORGANIZATION.md | 检查代码是否放在正确的位置 |
| **项目经理** | ADMIN_AGENT_IMPLEMENTATION_CHECKLIST.md | 跟踪任务进度 |
| **清理优化** | CODE_CLEANUP_ANALYSIS.md | 理解代码清理和避免冗余 |

**快速查阅**:
```
系统如何工作? → ADMIN_AGENT_SIMPLIFIED_DESIGN.md
代码应该怎么放? → ADMIN_AGENT_CODE_ORGANIZATION.md
具体怎么开发? → 本文件 (ADMIN_AGENT_DEVELOPMENT_PLAN.md)
任务清单是什么? → ADMIN_AGENT_IMPLEMENTATION_CHECKLIST.md
发现有冗余代码? → CODE_CLEANUP_ANALYSIS.md
```

---

## 现有资源清单

### ✅ 已有的CLI命令 (15个)

```
/.devices       → 列出设备
/.skills        → 列出Skills
/.reload        → 重新加载
/.clear         → 清理缓存
/.teach         → 教学互动
/.history       → 历史记录
/.help          → 帮助信息
/.analyze       → 分析
/.search        → 搜索
/.query         → 查询
/.learn_cmd     → 学习命令
/.cache         → 缓存管理
/.lib           → 库管理
/.quit, /.exit  → 退出
```

### ✅ 已有的工具系统

```
基础设施:
  • src/olav/core/skill_system.py
    - SkillTool (工具定义类)
    - SkillConfig (Skill配置类)
  
  • src/olav/core/script_engine.py
    - create_script_tool() (创建工具)
    - load_skill() (加载Skill)
    - StructuredTool (结构化工具)
  
  • src/olav/agents/agent_enhancements.py
    - QueryAgentTool (Agent工具基类)
    - 工具执行框架

现有的Admin工具:
  • backup_config.py (备份配置)
  • restore_config.py (恢复配置)
  • read_file.py (读取文件)
  • write_file.py (写入文件)
  • search_code.py (搜索代码)
  • list_files.py (列出文件)
  • list_workspace_structure.py (列出工作空间结构)
```

### ⚠️ 需要改进的地方

```
✗ 没有专门的Cron管理相关的命令/工具
✗ 没有知识库搜索/管理的命令
✗ 系统状态查看不完整
✗ 没有统一的Admin Agent实现
✗ 没有YAML/JSON配置编辑的通用工具
```

---

## Admin Agent 操作需求分析

### 需要的操作列表

| 操作 | 分类 | 现有? | 复杂度 | 优先级 |
|-----|------|--------|--------|--------|
| **设备管理** | | | | |
| add_device | File Edit | ❌ | 极低 | P1 |
| delete_device | File Edit | ❌ | 极低 | P1 |
| update_device | File Edit | ❌ | 极低 | P1 |
| list_devices | File Edit/CLI | ✅ /.devices | 极低 | P1 |
| **定时任务** | | | | |
| create_cron | File Edit | ❌ | 极低 | P1 |
| delete_cron | File Edit | ❌ | 极低 | P1 |
| enable_cron | File Edit | ❌ | 极低 | P1 |
| disable_cron | File Edit | ❌ | 极低 | P1 |
| list_cron | CLI | ❌ | 低 | P2 |
| run_cron | CLI | ❌ | 中 | P2 |
| **知识库** | | | | |
| add_knowledge | File Edit | ❌ | 低 | P2 |
| delete_knowledge | File Edit | ❌ | 极低 | P2 |
| list_knowledge | File Edit | ❌ | 极低 | P2 |
| search_knowledge | CLI/Tool | ❌ | 中 | P2 |
| **系统配置** | | | | |
| show_config | File Edit | ❌ | 极低 | P1 |
| set_log_level | File Edit | ❌ | 极低 | P2 |
| set_cache_size | File Edit | ❌ | 极低 | P2 |
| **Skill管理** | | | | |
| reload_skill | Tool | ✅ /.reload | 低 | P1 |
| list_skills | CLI | ✅ /.skills | 低 | P1 |
| describe_skill | CLI | ❌ | 低 | P2 |
| **系统监控** | | | | |
| system_status | Tool | 部分 | 低 | P2 |
| cleanup_logs | Tool | ❌ | 中 | P2 |
| clear_cache | Tool | ✅ /.clear | 低 | P2 |
| task_history | File Read | ❌ | 低 | P3 |

---

## 分阶段开发计划

### 🟢 Phase 1: Core Foundation (第1周) - 3天

#### 目标
实现Admin Agent的最小可行产品（MVP），包括所有Category 1操作（YAML文件编辑）

#### 新增组件

##### 1.1 基础工具库
```
src/olav/admin/
├── __init__.py
├── config_manager.py      ← 新增：YAML编辑工具
│   ├── load_yaml()
│   ├── save_yaml()
│   ├── add_device()
│   ├── delete_device()
│   ├── update_device()
│   └── ...
├── admin_agent.py         ← 新增：Admin Agent主类
│   ├── identify_intent()
│   ├── extract_parameters()
│   ├── handle_request()
│   └── ...
└── admin_tools.py         ← 新增：Admin工具集
    ├── FileEditTool
    ├── YAMLEditTool
    └── ...
```

##### 1.2 文件编辑工具 (重用现有的write_file等)
```
✓ 使用现有的: write_file.py, read_file.py, list_files.py
→ 但创建更高级的wrapper:
  • ConfigEditTool (编辑配置文件)
  • YAMLEditTool (编辑YAML)
  • MarkdownEditTool (编辑Markdown)
```

##### 1.3 Admin Agent实现
```python
src/olav/admin/admin_agent.py

class AdminAgent:
    async def handle_request(user_input):
        # 1. 意图识别
        intent = identify_intent(user_input)
        
        # 2. 参数提取
        params = extract_parameters(user_input, intent)
        
        # 3. 执行操作
        if intent == "add_device":
            return await self.add_device(**params)
        elif intent == "list_devices":
            return await self.list_devices(**params)
        # ... 其他操作
```

#### 工作分解

| 任务 | 工具类 | 文件 | 工作量 | 依赖 |
|-----|--------|------|-----------|------|
| YAML编辑工具 | ConfigManager | config_manager.py | 1-2天 | 无 |
| Admin Agent主类 | AdminAgent | admin_agent.py | 1天 | ConfigManager |
| 集成到CLI | - | cli_main.py修改 | 0.5天 | AdminAgent |
| **小计** | | | **2.5天** | |

#### 第1周可实现的操作 (Category 1全部)

```
✅ add_device (添加设备)
✅ delete_device (删除设备)
✅ update_device (更新设备)
✅ list_devices (列出设备)
✅ create_cron (创建定时任务)
✅ delete_cron (删除定时任务)
✅ enable_cron (启用任务)
✅ disable_cron (禁用任务)
✅ add_knowledge (添加知识)
✅ delete_knowledge (删除知识)
✅ show_config (查看配置)
```

#### 文件结构变化

```
src/olav/
└── admin/                    ← 新增
    ├── __init__.py
    ├── admin_agent.py        (200-300行)
    ├── config_manager.py      (300-400行)
    └── admin_tools.py        (100-200行)

.olav/skills/olav-admin/
└── (保持不变，后续可迁移到src/olav/admin/)
```

---

### 🟡 Phase 2: Enhanced Tools (第2周) - 5天

#### 目标
实现Category 2的工具（需要业务逻辑）和Category 4的P1命令

#### 新增工具 (Category 2)

##### 2.1 Skill管理工具
```
src/olav/admin/skill_tools.py ← 新增

class SkillReloadTool:
    """重新加载Skill"""
    async def execute(skill_name: str) -> str:
        # 1. 验证Skill存在
        # 2. 调用重新加载
        # 3. 验证加载成功

class SkillDescribeTool:
    """获取Skill详情"""
    async def execute(skill_name: str) -> str:
        # 读取SKILL.md
        # 提取元数据
        # 返回格式化结果
```

##### 2.2 系统监控工具
```
src/olav/admin/system_tools.py ← 新增

class SystemStatusTool:
    """获取系统状态"""
    - 设备数量
    - 定时任务数量
    - 知识库条目数
    - 缓存使用情况

class CleanupLogsTool:
    """清理旧日志"""
    - 删除超X天的日志
    - 计算释放空间

class TaskHistoryTool:
    """获取定时任务执行历史"""
    - 读取history目录
    - 解析日志
    - 返回执行统计
```

#### 新增CLI命令 (Category 4 P1)

##### 2.3 新的Slash命令

```
src/olav/cli/commands.py ← 扩展

@register_command("cron")
async def cmd_cron(args: str) -> str:
    # /cron list
    # /cron run <task_name>
    # /cron describe <task_name>

@register_command("skill_reload")
async def cmd_skill_reload(args: str) -> str:
    # /skill_reload <skill_name>
    
@register_command("system")
async def cmd_system(args: str) -> str:
    # /system status
    # /system clean
```

#### 工作分解

| 任务 | 工具类 | 文件 | 工作量 | 依赖 |
|------|--------|------|---------|------|
| Skill工具 | SkillTools | skill_tools.py | 1-2天 | 无 |
| 系统工具 | SystemTools | system_tools.py | 1-2天 | 无 |
| Cron命令 | - | commands.py修改 | 1天 | Cron工具 |
| Skill命令 | - | commands.py修改 | 0.5天 | Skill工具 |
| System命令 | - | commands.py修改 | 0.5天 | System工具 |
| Admin Agent集成 | - | admin_agent.py修改 | 1天 | 所有工具 |
| **小计** | | | **5天** | |

#### 第2周可实现的操作

```
Category 2 Tools:
  ✅ reload_skill
  ✅ describe_skill
  ✅ system_status
  ✅ cleanup_logs
  ✅ task_history

Category 4 P1 Commands:
  ✅ /cron list
  ✅ /cron run <task_name>
  ✅ /skill_reload <skill_name>
  ✅ /system status
  ✅ /system clean
```

#### 文件变化

```
src/olav/admin/
├── skill_tools.py         ← 新增 (200-300行)
├── system_tools.py        ← 新增 (300-400行)
└── admin_agent.py         (修改，新增工具调用)

src/olav/cli/
└── commands.py            (扩展，新增命令)
```

---

### 🔵 Phase 3: Knowledge & Advanced (第3周) - 4-5天

#### 目标
实现知识库管理和Category 4 P2命令

#### 新增工具 (Category 2 + Category 4)

##### 3.1 知识库工具
```
src/olav/admin/knowledge_tools.py ← 新增

class KnowledgeSearchTool:
    """搜索知识库"""
    - 读取knowledge目录
    - 解析Markdown元数据
    - 向量化搜索  (可选)
    - 返回匹配结果

class KnowledgeIndexTool:
    """重新索引知识库"""
    - 扫描所有*.md文件
    - 提取标签和元数据
    - 更新index.json
```

##### 3.2 Cron高级功能
```
src/olav/cli/commands.py

@register_command("cron")  ← 扩展
async def cmd_cron(args: str) -> str:
    # /cron list          ✅ (已有)
    # /cron run <task>    ✅ (已有)
    # /cron history <task> ← 新增
    # /cron describe <task>← 新增
    # /cron enable <task> ← 新增 (调用Admin Agent)
    # /cron disable <task>← 新增 (调用Admin Agent)
```

##### 3.3 高级命令
```
@register_command("knowledge")
async def cmd_knowledge(args: str) -> str:
    # /knowledge search <query>
    # /knowledge list
    # /knowledge describe <topic>

@register_command("admin")
async def cmd_admin(args: str) -> str:
    # /admin status
    # /admin backup
    # /admin restore
```

#### 工作分解

| 任务 | 工具类 | 文件 | 工作量 | 依赖 |
|------|--------|------|---------|------|
| 知识库工具 | KnowledgeTools | knowledge_tools.py | 1-2天 | 无 |
| 知识库命令 | - | commands.py修改 | 1天 | 知识库工具 |
| Cron高级功能 | - | cron_tools.py修改 | 1天 | 无 |
| Admin高级命令 | - | commands.py修改 | 0.5天 | 无 |
| Admin Agent增强 | - | admin_agent.py修改 | 1day | 所有工具 |
| **小计** | | | **4-5天** | |

#### 第3周可实现的操作

```
Category 2:
  ✅ search_knowledge
  ✅ index_knowledge

Category 4 P2:
  ✅ /knowledge search <query>
  ✅ /knowledge list
  ✅ /cron history <task>
  ✅ /admin status
  ✅ /admin backup/restore
```

---

## 总体实现时间线

```
Week 1 (3天)       → Phase 1: Core Admin Agent MVP
  Days 1-3: YAML编辑工具 + Admin Agent主类 + 集成

Week 2 (5天)       → Phase 2: Tools + Commands
  Days 4-5: Skill/System工具开发
  Days 6-8: CLI命令扩展 + 集成

Week 3 (4-5天)     → Phase 3: Knowledge + Advanced
  Days 9-10: 知识库工具 + 搜索
  Days 11-12: 高级命令 + 优化

额外 (1-2天)       → Testing & Documentation
  天数: 根据需要调整
```

**总时间**: 2.5 - 3.5 周（包括测试和文档）

---

## 代码结构最终样子

```
src/olav/
├── admin/                      ← Admin Agent模块
│   ├── __init__.py
│   ├── admin_agent.py          (核心Agent: 200-300行)
│   ├── config_manager.py       (配置管理: 300-400行)
│   ├── admin_tools.py          (基础工具: 100-200行)
│   ├── skill_tools.py          (Skill工具: 200-300行)
│   ├── system_tools.py         (系统工具: 300-400行)
│   └── knowledge_tools.py      (知识库工具: 200-300行)
│
└── cli/
    ├── commands.py             (修改: +300-500行，新增命令)
    └── ...

.olav/
├── config/
│   ├── hosts.yaml              (Agent编辑)
│   └── system_settings.json    (Agent编辑)
├── cron/
│   └── schedules.yaml          (Agent编辑)
└── knowledge/
    └── *.md                    (Agent编辑)
```

---

## 实现建议和注意事项

### ✅ 推荐做法

```
1. 重用现有工具
   • read_file.py, write_file.py等
   • 创建高级wrapper而不是重新实现

2. 遵循现有的工具系统设计
   • SkillTool的定义方式
   • Tool的执行方式
   • 参数验证方式

3. 保持简单
   • YAML编辑用简单的dict操作
   • 不需要复杂的数据结构
   • 配置文件是单一真实来源

4. 安全第一
   • 三层安全检查
   • 路径白名单
   • 操作日志记录
```

### ❌ 应避免的做法

```
✗ 不要重新实现read/write文件的逻辑
✗ 不要创建新的数据库层
✗ 不要使用ORM或复杂的映射
✗ 不要创建权限认证系统 (Dev环境)
✗ 不要过度设计工具框架
```

### 🔒 安全考虑

```
Phase 1: 文件路径白名单
  • 允许修改: .olav/config/*, .olav/cron/*, .olav/knowledge/*
  • 禁止访问: .olav/db/*, backup/*.tar, src/, etc.

Phase 2: 操作验证
  • 验证Skill存在性
  • 验证Cron任务语法
  • 验证参数有效性

Phase 3: 日志记录
  • 记录所有Agent操作
  • 可审计的修改日志
  • Git集成备份
```

---

## 优先级调整

### 基础必须有 (P1 - Week 1-2)
```
✅ 设备管理 (YAML编辑)
✅ Skill重新加载 (已有命令)
✅ 列出设备/Skills (已有命令)
```

### 高价值功能 (P2 - Week 2-3)
```
✅ 定时任务管理
✅ 系统状态查看
✅ 知识库基础功能
✅ 新的CLI命令
```

### 可以延后 (P3)
```
○ 任务历史查看 (可用日志代替)
○ 知识库向量搜索 (基础搜索够用)
○ 高级诊断工具 (未来功能)
```

---

## 成功标准

### Phase 1完成标志：
- [ ] Admin Agent能添加/删除/修改设备
- [ ] Admin Agent能创建/删除定时任务
- [ ] 操作能持久化到YAML文件
- [ ] 基本的意图识别可用

### Phase 2完成标志：
- [ ] Skill重新加载工作正常
- [ ] 新的CLI命令可用
- [ ] 系统状态查看完整
- [ ] 日志清理功能正常

### Phase 3完成标志：
- [ ] 知识库管理完整
- [ ] 所有Admin操作可用
- [ ] 用户文档完善
- [ ] E2E测试通过

---

**核心思想**: 充分利用现有基础设施，采用增量开发，快速迭代。从最简单的YAML编辑开始，逐步增加复杂功能。
