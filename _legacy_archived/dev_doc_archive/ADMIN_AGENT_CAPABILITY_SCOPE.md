# Admin Agent 能力范围定义

**目的**: 明确Admin Agent应该管理OLAV系统的哪些方面
**日期**: 2026-02-12
**状态**: 需要评论

---

## OLAV系统架构回顾

```
┌─────────────────────────────────────────────────────────────┐
│ 用户层                                                        │
│ Natural Language Queries + System Management                 │
└──────┬──────────────────────────┬───────────────────────────┘
       │                          │
       ▼                          ▼
┌──────────────────────┐  ┌──────────────────────┐
│ Orchestrator Agent   │  │ Admin Agent          │
│ (业务查询)           │  │ (系统配置)           │
│                      │  │                      │
│ 任务:                │  │ 任务:                │
│ - 理解业务查询       │  │ - 理解管理请求      │
│ - 规划执行步骤       │  │ - 修改配置          │
│ - 调用技能完成任务   │  │ - 监控系统状态      │
│ - 返回数据           │  │ - 维护系统资源      │
└──────┬───────────────┘  └──────┬───────────────┘
       │                          │
       └──────────┬───────────────┘
                  ▼
        ┌─────────────────────┐
        │ Core Layer          │
        │ - DuckDB            │
        │ - Inventory         │
        │ - Knowledge Base    │
        │ - Templates         │
        │ - Cache             │
        │ - Cron/APScheduler  │
        └─────────────────────┘
```

---

## Admin Agent 能力范围 (Capability Matrix)

### 🎯 第一层: 必须有的功能 (Must-Have)

#### 1. **设备管理 (Device Inventory Management)**

**目标**: 帮用户维护设备清单

**包含的操作**:
- ✅ 添加设备 (add device)
- ✅ 删除设备 (remove device)
- ✅ 修改设备参数 (update device credentials, platform, etc.)
- ✅ 列出所有设备 (list devices)
- ✅ 查看单个设备详情 (show device details)

**编辑的文件**: `.olav/config/hosts.yaml`

**用户场景**:
```
User: 添加一个新的Cisco路由器R5，IP是192.168.1.5，用户名admin
Agent: ✓ 设备R5已添加

User: 把R1的IP改成10.0.0.1
Agent: ✓ 设备R1的IP已更新

User: 列出所有设备
Agent: 当前清单有6个设备:
  - R1 (10.0.0.1)
  - R2 (10.0.0.2)
  ...
```

---

#### 2. **定时任务管理 (Scheduled Task Management)**

**目标**: 帮用户设置和管理定期执行的任务

**包含的操作**:
- ✅ 创建定时任务 (create scheduled task)
- ✅ 删除定时任务 (delete scheduled task)
- ✅ 启用/禁用任务 (enable/disable task)
- ✅ 修改任务参数 (update task schedule/command)
- ✅ 列出所有任务 (list scheduled tasks)
- ✅ 查看任务执行历史 (show task history)

**编辑的文件**: `.olav/cron/schedules.yaml`

**用户场景**:
```
User: 每天下午3点导出所有设备的配置到CSV
Agent: ✓ 任务已创建
  - 名称: export_configs_daily
  - 时间: 每天下午3点 (15:00)
  - 下次执行: 今天下午3点

User: 列出所有定时任务
Agent: 当前有3个定时任务:
  1. export_configs_daily (每天15:00)
  2. backup_running_config_nightly (每晚20:00)
  3. check_device_health_hourly (每小时)

User: 禁用export_configs_daily任务
Agent: ✓ 任务已禁用
```

---

### 🎯 第二层: 应该有的功能 (Should-Have)

#### 3. **知识库管理 (Knowledge Base Management)**

**目标**: 帮用户积累和利用组织知识

**包含的操作**:
- ✅ 添加知识条目 (add knowledge)
- ✅ 删除知识条目 (delete knowledge)
- ✅ 更新知识条目 (update knowledge)
- ✅ 列出知识库 (list knowledge base)
- ✅ 搜索知识 (search knowledge)

**编辑的文件**: `.olav/knowledge/*.md` + `index.json`

**用户场景**:
```
User: 添加一个关于BGP配置最佳实践的知识
Agent: 我来帮你添加这个知识。请提供详细内容...

User: [提供详细内容]
Agent: ✓ 知识已添加
  - 标题: BGP Configuration Best Practices
  - 文件: bgp_config_best_practices.md
  - 已索引，可供检索
```

---

#### 4. **系统配置管理 (System Configuration)**

**目标**: 帮用户管理OLAV系统本身的配置

**包含的操作**:
- ✅ 查看系统设置 (show system settings)
- ✅ 修改系统参数 (update system parameters)
  - 日志级别 (log level)
  - 缓存大小 (cache size)
  - 模板目录 (template directory)
  - 超时时间 (timeout values)

**编辑的文件**: `.olav/settings.json`, `.env`

**用户场景**:
```
User: 显示系统配置
Agent: 当前系统配置:
  - Log Level: INFO
  - Cache Size: 1GB
  - Template Dir: .olav/templates
  - Query Timeout: 30s

User: 把日志级别改成DEBUG
Agent: ✓ 日志级别已改为DEBUG
```

---

### 🎯 第三层: 可以有的功能 (Nice-to-Have)

#### 5. **系统监控 (System Monitoring)**

**目标**: 帮用户了解系统运行状态

**包含的操作**:
- ✅ 查看系统状态 (system status)
- ✅ 查看最近任务执行结果 (recent task results)
- ✅ 查看系统日志 (system logs)
- ✅ 查看性能指标 (performance metrics)

**读取的文件**: `logs/`, `.olav/cron/history/`, 不编辑

**用户场景**:
```
User: 系统状态怎么样
Agent: 系统状态正常
  - 设备数: 6
  - 定时任务: 3个（3个运行中）
  - 知识库: 12条
  - 最近执行: export_configs_daily (成功，2分钟前)
  - 缓存使用: 256MB / 1GB
```

---

#### 6. **系统维护 (System Maintenance)**

**目标**: 帮用户维护系统健康

**包含的操作**:
- ✅ 清理缓存 (clear cache)
- ✅ 清理日志 (clean logs)
- ✅ 重新加载Skills (reload skills)
- ✅ 整理知识库索引 (rebuild knowledge index)
- ✅ 导出系统配置 (export configuration)
- ✅ 恢复系统配置 (restore configuration)

**范围**: 限制在`.olav/`目录内

**用户场景**:
```
User: 清理一个月前的日志
Agent: ✓ 已清理日志
  - 删除的文件: 45个
  - 释放空间: 120MB

User: 重新加载所有skills
Agent: ✓ 所有skills已重新加载
  - 加载成功: 8个
  - 警告: command_learner (需要检查配置)

User: 导出系统配置用于备份
Agent: ✓ 配置已导出
  - 文件: backup_config_2026-02-12.tar.gz
  - 大小: 5MB
```

---

### ❌ 第四层: 不应该做的事情 (Out of Scope)

#### ❌ Agent不应该:

1. **执行具体的业务查询** 
   - 错: "查询所有BGP邻居的状态"
   - 理由: 这是Orchestrator Agent的工作

2. **修改网络设备配置**
   - 错: "在R1上配置OSPF"
   - 理由: 这是危险操作，应通过明确的命令执行

3. **访问DuckDB数据库**
   - 错: "从设备表中删除某个设备"
   - 理由: 数据库操作应该被限制和审计

4. **安装/卸载依赖包**
   - 错: "安装textfsm库"
   - 理由: 环境管理应该通过包管理器

5. **修改任意代码或脚本**
   - 错: "更新skill脚本"
   - 理由: 代码应通过版本控制系统管理

6. **执行任意shell命令**
   - 错: "执行'rm -rf /'"
   - 理由: 安全隐患

---

## 能力范围矩阵

| 功能 | 优先级 | 能力 | 方式 | 约束 |
|-----|--------|------|------|------|
| **设备管理** | P1 | 添加/删除/修改/图表 | 编辑hosts.yaml | 仅YAML文件 |
| **定时任务** | P1 | 创建/删除/启用/禁用/查历史 | 编辑schedules.yaml | 仅YAML文件 |
| **知识库** | P2 | 添加/删除/搜索 | 编辑*.md文件 | 限制在knowledge/ |
| **系统配置** | P2 | 查看/修改参数 | 编辑settings.json | 仅系统参数 |
| **系统监控** | P3 | 查看状态/日志/指标 | 读取日志 | 仅读取 |
| **系统维护** | P3 | 清理/导出/重载 | 直接操作 | 限制在.olav/ |

---

## Admin Agent 与 Orchestrator Agent 的分工

```
┌─────────────────────────────────────────────────────────────┐
│ 用户请求                                                      │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴───────────┐
        │ 属于什么领域？          │
        └────────────┬───────────┘
                     │
       ┌─────────────┴──────────────┐
       │                            │
       ▼                            ▼
   系统管理                      业务查询
   (System Management)           (Business Query)
       │                            │
       ▼                            ▼
   Admin Agent              Orchestrator Agent
   
   - 设备管理                   - 理解业务需求
   - 任务管理                   - 规划执行步骤
   - 知识库管理                 - 调用skills
   - 系统配置                   - 执行查询
   - 系统监控                   - 返回结果
   - 系统维护
```

---

## 设计原则

### 1. **权责清晰**
- Admin Agent: 配置和管理
- Orchestrator Agent: 业务查询和执行
- 不重叠，不遗漏

### 2. **安全第一**
- 只编辑`.olav/`中的配置文件
- 不执行shell命令
- 不修改代码
- 不访问敏感的系统资源

### 3. **可审计性**
- 所有操作都有日志
- 文件修改可被版本控制
- 用户可以看到Agent做了什么

### 4. **用户友好**
- 支持自然语言
- 清晰的确认信息
- 易于撤销（git rollback）

---

## 用户场景演例

### 场景1: 新用户一键部署

```
User: 我有3台Cisco设备需要管理，帮我添加到OLAV

Admin Agent Step 1: 收集信息
Agent: 请提供这3台设备的信息:
  设备1: 名称? IP? 用户名?
  
User: R1, 10.0.0.1, admin
User: R2, 10.0.0.2, admin  
User: R3, 10.0.0.3, admin

Admin Agent Step 2: 批量添加
✓ 设备R1已添加
✓ 设备R2已添加
✓ 设备R3已添加

Orchestrator Agent Step 3: 验证连接
✓ R1: 连接成功
✓ R2: 连接成功
✓ R3: 连接成功

User: 现在我可以查询这些设备了吗？
Orchestrator: 可以，试试看: "R1和R2的BGP邻居是什么?"
```

---

### 场景2: 配置自动化任务

```
User: 我需要每周一上午9点导出所有网络配置

Admin Agent: 理解了，我来帮你创建这个任务

Agent: 检查参数...
  - 频率: 每周一
  - 时间: 上午9点
  - 命令: export running-config from all devices
  - 导出格式: csv/json/md?

User: CSV格式，存储到exports/weekly/

Agent: 参数确认无误，创建任务...
✓ 任务已创建: weekly_config_export
✓ 下次执行: 本周一上午9点
✓ 历史记录: 可随时查看

(一周后)
Orchestrator Agent: 任务已自动执行
  ✓ 导出成功
  ✓ 文件: exports/weekly/configs_2026-02-17.csv
```

---

## 下一步动作

1. ❓ **确认**: 以上能力范围定义是否正确？
2. ❓ **补充**: 是否还有其他功能应该添加或移除？
3. ❓ **优先级**: P1/P2/P3的顺序对吗？
4. ⏳ **实现**: 确认后开始P1功能实现

---

**最关键的问题**: Admin Agent的边界是什么？它和Orchestrator Agent如何分工？
