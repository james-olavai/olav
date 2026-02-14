# Admin Agent 实现检查清单

**用途**: 开发时跟踪任务完成情况，确保不遗漏需求
**日期**: 2026-02-12
**更新**: 每个Phase完成后更新状态

---

## Phase 1: Core Foundation (预计3天)

### 目标
```
✅ ConfigManager 类实现 (YAML读写)
✅ AdminAgent 核心类实现 (意图识别+参数提取)
✅ 集成到CLI (/admin 命令)
✅ 设备管理功能完全可用
```

### 代码实现清单

#### 1.1 创建framework目录结构
- [ ] `mkdir -p src/olav/admin`
- [ ] `touch src/olav/admin/__init__.py`
- [ ] 验证导入: `from src.olav.admin import AdminAgent`

#### 1.2 实现 ConfigManager (300-400行)
**文件**: `src/olav/admin/config_manager.py`

```
核心功能:
  [ ] load_yaml(path) - 读取任何YAML文件
      [ ] 处理不存在的文件错误
      [ ] 返回字典或None
      
  [ ] save_yaml(path, data) - 保存YAML文件
      [ ] 创建不存在的目录
      [ ] 保留YAML格式
      [ ] 记录操作日志
      
  [ ] validate_yaml(data, schema) - 验证YAML结构
      [ ] 检查必填字段
      [ ] 检查字段类型
      [ ] 返回验证错误列表
      
  [ ] merge_yaml(base, updates) - 合并两个YAML
      [ ] 深度合并 (不覆盖未指定的字段)
      [ ] 返回合并结果
```

**测试**:
- [ ] 读取现有的 .olav/config/hosts.yaml
- [ ] 修改并保存回文件
- [ ] 验证文件内容正确

#### 1.3 实现 AdminAgent (200-300行)
**文件**: `src/olav/admin/admin_agent.py`

```
核心方法:
  [ ] handle_request(user_input: str) -> str
      [ ] 调用 identify_intent()
      [ ] 调用 extract_parameters()
      [ ] 路由到对应的处理器
      [ ] 返回操作结果
      
  [ ] identify_intent(user_input: str) -> str
      [ ] 使用LLM识别意图
      [ ] 支持的意图: add_device, delete_device, update_device, list_devices
      [ ] 无法识别时返回 "unknown"
      
  [ ] extract_parameters(user_input: str, intent: str) -> dict
      [ ] 使用LLM提取参数
      [ ] 针对不同意图提取不同参数
      [ ] add_device: name, ip, username, [platform]
      [ ] 缺少必填参数时向用户提示
      
  [ ] 路由处理器:
      [ ] route_add_device(**params)
      [ ] route_delete_device(**params)
      [ ] route_update_device(**params)
      [ ] route_list_devices(**params)
```

**安全检查**:
```
三层安全检查 (必须实现):

第1层 - 意图分类:
  [ ] 检查意图是否在允许列表中
  [ ] 禁止意图直接返回 "❌ 禁止操作"
  
第2层 - 文件路径检查:
  [ ] 只允许修改 .olav/config/ 下的YAML
  [ ] 禁止修改 src/, .olav/db/, 备份文件
  
第3层 - 内容检查:
  [ ] 不能添加非法的IP地址
  [ ] 不能添加为空的设备名
```

**错误处理**:
- [ ] 使用try/except捕获异常
- [ ] 返回用户友好的错误信息
- [ ] 记录异常到logs/admin_errors.log

#### 1.4 实现异常类 (50-100行)
**文件**: `src/olav/admin/exceptions.py`

```
[ ] AdminException - 基类
[ ] ValidationError - 参数验证错误
[ ] OperationError - 操作执行错误
[ ] PathError - 文件路径错误
[ ] PermissionError - 权限检查失败
```

#### 1.5 实现验证器 (100-150行)
**文件**: `src/olav/admin/validators.py`

```
[ ] validate_device_name(name: str)
    [ ] 不能为空
    [ ] 不能包含非法字符
    
[ ] validate_device_ip(ip: str)
    [ ] 格式检查 (xxx.xxx.xxx.xxx)
    [ ] 不能是保留IP
    
[ ] validate_username(username: str)
    [ ] 不能为空
    [ ] 长度检查 (1-32字符)
    
[ ] validate_file_path(path: str, allowed_dirs: list)
    [ ] 路径必须在allowed_dirs中
    [ ] 不能有../路径遍历
```

#### 1.6 迁移文件工具 (150-200行)
**文件**: `src/olav/admin/file_tools.py` (从.olav/skills/olav-admin/tools迁移)

```
[ ] 创建file_tools.py
[ ] 复制read_file()逻辑
[ ] 复制write_file()逻辑
[ ] 复制list_files()逻辑
[ ] 复制search_code()逻辑
[ ] 更新.olav/skills/olav-admin/SKILL.md
    [ ] 删除这些工具的声明
    [ ] 保留backup_config, restore_config
```

### 设备管理功能清单

#### 操作1: 添加设备 (add_device)
**命令示例**: `用户: /admin 添加设备R1，IP是10.0.0.1，用户名是admin`

```
完成条件:
  [ ] 识别意图为 add_device
  [ ] 提取参数: name=R1, ip=10.0.0.1, username=admin
  [ ] 验证参数
      [ ] R1 不能重复
      [ ] 10.0.0.1 格式正确
      [ ] admin 不为空
  [ ] 编辑 .olav/config/hosts.yaml
      [ ] 添加新条目
      [ ] 保持YAML格式
  [ ] 日志记录
      [ ] 记录到 logs/admin_audit.log
      [ ] 包含: 操作人, 时间, 操作内容, 结果
  [ ] 返回成功信息
      [ ] ✓ 设备R1已添加到inventory
      [ ] 显示添加的参数
```

**测试验证**:
- [ ] hosts.yaml 确实添加了新条目
- [ ] 日志记录正确
- [ ] 重复的设备名被拒绝
- [ ] 无效的IP被拒绝

#### 操作2: 删除设备 (delete_device)
**命令示例**: `用户: /admin 删除设备R1`

```
完成条件:
  [ ] 识别意图为 delete_device
  [ ] 提取参数: name=R1
  [ ] 验证参数
      [ ] R1 存在于inventory中
  [ ] 编辑 .olav/config/hosts.yaml
      [ ] 删除对应条目
  [ ] 日志记录 (audit trail)
  [ ] 返回成功信息
      [ ] ✓ 设备R1已删除
```

**测试验证**:
- [ ] hosts.yaml 确实删除了条目
- [ ] 不存在的设备名被拒绝
- [ ] 日志记录完整

#### 操作3: 修改设备 (update_device)
**命令示例**: `用户: /admin 修改设备R1的IP为10.0.0.2`

```
完成条件:
  [ ] 识别意图为 update_device
  [ ] 提取参数: name=R1, ip=10.0.0.2
  [ ] 验证参数
      [ ] R1 存在
      [ ] 新IP有效
  [ ] 编辑 .olav/config/hosts.yaml
      [ ] 更新指定字段
      [ ] 保留其他字段
  [ ] 日志记录 (before/after)
  [ ] 返回成功信息
```

**测试验证**:
- [ ] hosts.yaml 确实修改了参数
- [ ] 其他字段未被改动
- [ ] 日志显示before/after

#### 操作4: 列表设备 (list_devices)
**命令示例**: `用户: /admin 显示所有设备`

```
完成条件:
  [ ] 识别意图为 list_devices
  [ ] 读取 .olav/config/hosts.yaml
  [ ] 格式化输出
      [ ] 表格形式展示
      [ ] 列: 名称, IP, 用户名, 平台
  [ ] 返回格式化结果
      [ ] 总数统计
      [ ] 逐个显示设备
```

**测试验证**:
- [ ] 显示所有设备
- [ ] 格式清晰可读
- [ ] 统计数字正确

### CLI集成清单

#### 1.7 实现 /admin 命令
**文件**: `src/olav/cli/commands.py` (修改)

```
[ ] 添加 /admin 命令注册
[ ] 命令处理器:
    async def cmd_admin(user_input: str) -> str:
        agent = AdminAgent()
        result = await agent.handle_request(user_input)
        return result
        
[ ] 帮助文本
    [ ] 显示Admin Agent支持的操作列表
    [ ] 显示示例命令
```

**测试**:
- [ ] `uv run olav /admin 添加设备R1，IP是10.0.0.1，用户名是admin`
- [ ] 返回成功信息
- [ ] hosts.yaml 被正确修改

### 测试清单 - Phase 1

#### 单元测试
- [ ] `tests/unit/admin/test_config_manager.py`
  - [ ] test_load_yaml_success
  - [ ] test_load_yaml_not_found
  - [ ] test_save_yaml_success
  - [ ] test_save_yaml_creates_directory
  - [ ] test_validate_yaml_success
  - [ ] test_validate_yaml_missing_field
  
- [ ] `tests/unit/admin/test_admin_agent.py`
  - [ ] test_identify_intent_add_device
  - [ ] test_extract_parameters_add_device
  - [ ] test_handle_request_add_device
  
- [ ] `tests/unit/admin/test_validators.py`
  - [ ] test_validate_device_name
  - [ ] test_validate_device_ip
  - [ ] test_validate_username

#### 集成测试
- [ ] `tests/integration/test_admin_agent_device_management.py`
  ```python
  async def test_add_device_workflow():
      """完整的添加设备工作流"""
      result = await admin_agent.handle_request("添加设备R1，IP是10.0.0.1")
      assert "设备R1已添加" in result
      assert hosts_yaml_contains("R1")
  ```

- [ ] `tests/integration/test_admin_agent_cli.py`
  ```python
  async def test_admin_command_via_cli():
      """通过CLI调用/admin命令"""
      result = await handle_cli_command("/admin 添加设备R1...")
      assert "成功" in result
  ```

#### 手工测试
- [ ] 启动OLAV: `uv run olav`
- [ ] 执行命令: `/admin 添加设备R1，IP是10.0.0.1，用户名是admin`
- [ ] 验证结果:
  - [ ] 返回成功信息
  - [ ] .olav/config/hosts.yaml 有新条目
  - [ ] logs/admin_audit.log 有记录
  
- [ ] 执行更多命令:
  - [ ] `/admin 显示所有设备`
  - [ ] `/admin 修改设备R1的IP为10.0.0.2`
  - [ ] `/admin 删除设备R1`

### 代码质量检查 - Phase 1

- [ ] 代码规范
  - [ ] 使用pylint检查: `uv run pylint src/olav/admin/`
  - [ ] 使用black格式化: `uv run black src/olav/admin/`
  - [ ] 使用mypy类型检查: `uv run mypy src/olav/admin/`

- [ ] 文档完整性
  - [ ] 每个类都有docstring
  - [ ] 每个方法都有docstring
  - [ ] docstring说明参数和返回值类型
  - [ ] 异常情况有说明

- [ ] 错误处理
  - [ ] 没有裸露的except
  - [ ] 所有异常都被转换为AdminException
  - [ ] 错误信息对用户友好

- [ ] 日志记录
  - [ ] 关键操作都有日志
  - [ ] 日志包含时间戳、操作者、内容
  - [ ] logs/admin_audit.log 存在且可读

- [ ] 代码审查
  - [ ] 没有代码重复
  - [ ] 没有未使用的import
  - [ ] 没有注释掉的代码
  - [ ] 没有硬编码的路径或值 (使用config.paths)

### Phase 1 验收标准

**必须全部满足才能进入Phase 2**:

```
功能完成:
  ✅ ConfigManager 类完全实现
  ✅ AdminAgent 核心类完全实现
  ✅ 四个设备操作都可以工作
  ✅ /admin 命令集成到CLI

质量标准:
  ✅ 所有单元测试通过 (100% pass rate)
  ✅所有集成测试通过
  ✅ 手工测试验证设备管理流程
  ✅ 代码规范检查通过 (pylint, black, mypy)
  ✅ 代码审查通过
  ✅ 三层安全检查实现完整

文档:
  ✅ docstruings 完整
  ✅ admin_audit.log 记录正确
  ✅ dev_doc/ 中的设计文档与实现一致
  
性能:
  ✅ 添加设备 < 1秒
  ✅ 删除设备 < 1秒
  ✅ 修改设备 < 1秒
  ✅ 列出设备 < 1秒 (即使有1000个设备)
```

---

## Phase 2: Cron & System (预计5天)

### 目标
```
✅ Cron任务管理 (create/delete/enable/disable/list)
✅ 系统监控命令 (/cron list, /cron run, /system status)
✅ 日志清理、缓存清理功能
✅ Skill管理命令 (/skill reload, /skill list)
```

### 代码实现清单

#### 2.1 实现 CronManager
- [ ] create_cron(name, schedule, command, ...)
- [ ] delete_cron(name)
- [ ] enable_cron(name)
- [ ] disable_cron(name)
- [ ] list_cron_tasks()

#### 2.2 实现 SystemManager
- [ ] get_system_status() -> dict
- [ ] cleanup_logs(days: int)
- [ ] clear_cache()
- [ ] rebuild_index()

#### 2.3 实现 SkillManager
- [ ] reload_skill(skill_name)
- [ ] list_skills()
- [ ] describe_skill(skill_name)

#### 2.4 添加新CLI命令
- [ ] `/cron list` - 列出所有定时任务
- [ ] `/cron run <name>` - 立即运行一个任务
- [ ] `/system status` - 显示系统状态
- [ ] `/system cleanup` - 清理日志和缓存
- [ ] `/skill reload <name>` - 重新加载Skill

### Phase 2验收标准
```
所有Cron/System/Skill操作都可以通过自然语言执行
所有新命令都集成到CLI
所有新功能通过单元测试和集成测试
```

---

## Phase 3: Knowledge & Advanced (预计4-5天)

### 目标
```
✅ 知识库管理 (add/delete/search)
✅ 高级查询功能
✅ 完整的audit trail和版本控制
✅ 性能优化和边界情况处理
```

### 代码实现清单

#### 3.1 实现 KnowledgeManager
- [ ] add_knowledge(topic, content, tags)
- [ ] delete_knowledge(topic)
- [ ] search_knowledge(query)
- [ ] list_knowledge()
- [ ] update_knowledge(topic, content)

#### 3.2 高级功能
- [ ] Git集成用于版本控制
- [ ] 完整的audit trail
- [ ] 性能优化 (缓存、索引)

### Phase 3 验收标准
```
所有知识库操作都可以工作
性能满足要求
完整的audit trail记录
```

---

## 总体完成标准

### 代码指标
```
代码量:
  [ ] src/olav/admin/ 总计 ~1500-2000行
  [ ] .olav/skills/olav-admin/tools/ 总计 ~750-1100行
  
代码覆盖率:
  [ ] Unit tests >= 80%
  [ ] Integration tests >= 70%

代码质量:
  [ ] pylint score >= 8.0
  [ ] No critical issues
  [ ] All docstrings present
```

### 功能指标
```
功能完成度:
  Phase 1: 100% ✅
  Phase 2: 100% ✅
  Phase 3: 100% ✅
  
操作覆盖率:
  [ ] 所有Category 1操作都支持
  [ ] 所有Category 2操作都支持
  
安全性:
  [ ] 三层安全检查在所有操作中实现
  [ ] 没有权限逃逸
  [ ] 没有注入攻击漏洞
```

### 文档指标
```
文档完整性:
  [ ] 所有public API都有docstring
  [ ] 所有参数都有类型注解
  [ ] 所有异常都有说明
  [ ] README有使用示例

设计文档一致性:
  [ ] 代码与dev_doc/ADMIN_AGENT_SIMPLIFIED_DESIGN.md一致
  [ ] 代码与dev_doc/ADMIN_AGENT_CODE_ORGANIZATION.md一致
  [ ] 代码与dev_doc/ADMIN_AGENT_DEVELOPMENT_PLAN.md一致
```

### 性能指标
```
操作延迟:
  [ ] add_device < 500ms
  [ ] delete_device < 500ms
  [ ] list_devices < 1s (for 1000 devices)
  [ ] LLM调用缓存命中率 > 80%
  
错误处理:
  [ ] 没有未捕获的异常
  [ ] 所有错误都有友好的消息
  [ ] 没有部分成功的操作 (全或无)
```

---

## 如何使用此清单

### 开发者视角
```
1. 开启Phase 1
2. 逐项完成任务
3. 每完成一个任务，标记 ✅
4. 遇到问题，参考dev_doc/CODE_CLEANUP_ANALYSIS.md查询规范
5. Phase 1完成后，进行"验收"检查
6. 所有验收项通过后，进入Phase 2
```

### Code Review视角
```
1. 检查 Phase 1 的所有 ✅ 项
2. 运行单元测试: uv run pytest tests/unit/admin/
3. 运行集成测试: uv run pytest tests/integration/admin/
4. 检查代码质量: uv run pylint src/olav/admin/
5. 审查每个方法的docstring
6. 验证安全检查是否实现
7. 签字批准 -> 可以进入Phase 2
```

### 项目经理视角
```
Progress Tracking:
  Phase 1: ___/45 tasks completed (__%)
  Phase 2: ___/25 tasks completed (__%)
  Phase 3: ___/20 tasks completed (__%)
  
Quality Gates (Phase完成后检查):
  Phase 1 Acceptance: [ ] Pass
  Phase 2 Acceptance: [ ] Pass
  Phase 3 Acceptance: [ ] Pass
  
Timeline:
  Phase 1: Expected Day 1-3
  Phase 2: Expected Day 4-8
  Phase 3: Expected Day 9-13
```

---

**最后更新**: 2026-02-12
**单项总数**: 约90项
**预计完成**: 2-3周
