# Admin Agent 代码组织指南

**目的**: 明确哪些脚本应该放在SKILL下，哪些放在src下
**原则**: 复用性、可维护性、清晰的职责分工
**日期**: 2026-02-12

---

## 核心规则

### 规则1: 通用 → `src/`，特定 → `SKILL/tools/`

```
通用工具 (被多个Agent/系统使用)
    ↓
    放在 src/olav/

Admin特定工具 (仅Admin Agent使用)
    ↓
    放在 .olav/skills/olav-admin/tools/
```

### 规则2: 框架代码 → `src/`，业务逻辑 → `SKILL/tools/`

```
框架/基础设施代码
    ↓
    放在 src/olav/core/, src/olav/admin/

业务逻辑/具体实现
    ↓
    放在 .olav/skills/olav-admin/tools/
```

---

## 详细分类矩阵

### 🔵 放在 `src/olav/admin/` (框架层)

**特征**: 
- 通用性强
- 被多个Agent可能使用
- 框架基础设施
- 与Agent框架紧密相关
- 可能被其他Skill复用

**具体代码**:

```python
# src/olav/admin/admin_agent.py
class AdminAgent:
    """Admin Agent主类"""
    async def handle_request(user_input: str)
    async def identify_intent(user_input: str)
    async def extract_parameters(user_input: str, intent: str)
    # 核心框架逻辑

# src/olav/admin/config_manager.py
class ConfigManager:
    """通用配置管理器"""
    def load_yaml(path: str) -> dict
    def save_yaml(path: str, data: dict)
    def validate_yaml(data: dict)
    # 可被其他模块使用

# src/olav/admin/base_tools.py
class AdminToolBase:
    """工具基类"""
    # 工具框架，被所有Admin工具继承

# src/olav/admin/exceptions.py
class AdminException
class ValidationError
class OperationError
# 异常定义
```

**为什么放在src?**
```
✅ ConfigManager可能被其他系统需要
✅ AdminToolBase是框架基础
✅ 异常定义是系统级别的
✅ Admin Agent是框架层而不是业务层
✅ 便于其他Skill或Agent复用这些基础设施
```

---

### 🟡 放在 `.olav/skills/olav-admin/tools/` (业务层)

**特征**:
- Admin Agent专用
- 具体的操作实现
- 业务逻辑
- 与network命令相关的脚本
- 不太可能被其他系统复用

**具体代码**:

```python
# .olav/skills/olav-admin/tools/device_management.py
async def add_device(name: str, ip: str, ...) -> str
async def delete_device(name: str) -> str
async def update_device(name: str, **params) -> str
async def list_devices() -> str
# 设备管理的具体实现

# .olav/skills/olav-admin/tools/cron_management.py
async def create_cron(name: str, schedule: str, ...) -> str
async def delete_cron(name: str) -> str
async def enable_cron(name: str) -> str
async def disable_cron(name: str) -> str
# 定时任务管理的具体实现

# .olav/skills/olav-admin/tools/knowledge_management.py
async def add_knowledge(topic: str, content: str) -> str
async def delete_knowledge(topic: str) -> str
async def search_knowledge(query: str) -> str
# 知识库管理的具体实现

# .olav/skills/olav-admin/tools/system_management.py
async def get_system_status() -> str
async def cleanup_logs(days: int) -> str
async def clear_cache() -> str
# 系统管理的具体实现
```

**为什么放在SKILL/tools?**
```
✅ 这些都是Admin Agent特定的业务逻辑
✅ 只在Admin Agent中被调用
✅ 与SKILL.md配置紧密相关
✅ 容易独立部署/更新
✅ 符合Skill的组织方式
```

---

### ✅ 已有代码应该怎么放

#### 现有的 `.olav/skills/olav-admin/tools/` 目录

```
✓ backup_config.py         放在 SKILL/tools (业务逻辑)
✓ restore_config.py        放在 SKILL/tools (业务逻辑)
✓ read_file.py             → 考虑移到 src/olav/admin/ (通用)
✓ write_file.py            → 考虑移到 src/olav/admin/ (通用)
✓ search_code.py           → 考虑移到 src/olav/admin/ (通用)
✓ list_files.py            → 考虑移到 src/olav/admin/ (通用)
✓ list_workspace_structure → → 考虑移到 src/olav/admin/ (通用)

总结:
  业务相关: backup_config, restore_config (保留在SKILL/tools)
  通用工具: read_file, write_file, search_code, list_files (移到src/olav)
```

---

## 推荐的最终结构

### `src/olav/admin/` (框架+通用工具)

```
src/olav/admin/
├── __init__.py
├── admin_agent.py          (核心Agent类: 200-300行)
│   ├── AdminAgent
│   ├── identify_intent()
│   ├── extract_parameters()
│   └── handle_request()
│
├── config_manager.py       (配置管理: 300-400行)
│   ├── ConfigManager (类)
│   ├── load_yaml()
│   ├── save_yaml()
│   └── validate_*()
│
├── base_tools.py           (工具基类: 100-150行)
│   ├── AdminToolBase (基类)
│   └── execute()
│
├── file_tools.py           (通用文件工具: 150-200行)
│   ├── read_file()         (从.olav/tools/read_file.py迁移)
│   ├── write_file()        (从.olav/tools/write_file.py迁移)
│   ├── list_files()
│   ├── search_code()
│   └── list_workspace()
│
├── exceptions.py           (异常定义: 50-100行)
│   ├── AdminException
│   ├── ValidationError
│   ├── OperationError
│   └── PathError
│
└── validators.py           (验证逻辑: 100-150行)
    ├── validate_device_params()
    ├── validate_cron_schedule()
    ├── validate_knowledge_content()
    └── validate_path()
```

**总代码量**: ~1000-1500行

---

### `.olav/skills/olav-admin/tools/` (业务实现)

```
.olav/skills/olav-admin/tools/
├── __init__.py
├── device_management.py    (设备管理: 150-200行)
│   ├── add_device()
│   ├── delete_device()
│   ├── update_device()
│   └── list_devices()
│
├── cron_management.py      (定时任务: 200-250行)
│   ├── create_cron()
│   ├── delete_cron()
│   ├── enable_cron()
│   ├── disable_cron()
│   └── list_cron_tasks()
│
├── knowledge_management.py (知识库: 150-200行)
│   ├── add_knowledge()
│   ├── delete_knowledge()
│   ├── search_knowledge()
│   └── list_knowledge()
│
├── system_management.py    (系统管理: 150-200行)
│   ├── get_system_status()
│   ├── cleanup_logs()
│   ├── clear_cache()
│   └── rebuild_index()
│
├── skill_management.py     (Skill管理: 100-150行)
│   ├── reload_skill()
│   ├── describe_skill()
│   └── list_skills()
│
├── backup_config.py        (保留)
└── restore_config.py       (保留)
```

**总代码量**: ~750-1100行

---

## 导入关系

### 清晰的依赖链

```
User Input
    ↓
CLI (src/olav/cli/commands.py)
    ↓
Admin Agent (src/olav/admin/admin_agent.py)  ← 框架层
    ↓
意图识别 + 参数提取
    ↓
业务工具函数 (.olav/skills/olav-admin/tools/*.py)  ← 业务层
    ↓
ConfigManager (src/olav/admin/config_manager.py)  ← 通用工具
    ↓
YAML/JSON文件
```

### 具体导入示例

```python
# .olav/skills/olav-admin/tools/device_management.py
from src.olav.admin.config_manager import ConfigManager
from src.olav.admin.validators import validate_device_params
from src.olav.admin.exceptions import ValidationError, OperationError

async def add_device(name: str, ip: str, username: str, **kwargs) -> str:
    # 1. 验证参数
    validate_device_params(name=name, ip=ip, username=username)
    
    # 2. 读取配置
    config_mgr = ConfigManager()
    config = config_mgr.load_yaml(".olav/config/hosts.yaml")
    
    # 3. 修改配置
    config[name] = {...}
    
    # 4. 保存配置
    config_mgr.save_yaml(".olav/config/hosts.yaml", config)
    
    return f"✓ 设备{name}已添加"
```

---

## 迁移计划

### Phase 1: 建立src/olav/admin/框架

```
步骤1: 创建目录结构
  mkdir -p src/olav/admin/
  touch src/olav/admin/__init__.py

步骤2: 编写核心文件
  • admin_agent.py (200-300行)
  • config_manager.py (300-400行)
  • base_tools.py (100-150行)
  • exceptions.py (50-100行)
  • validators.py (100-150行)

步骤3: 测试框架
  • 单元测试框架代码
  • 集成测试

工作量: 2-3天
```

### Phase 2: 迁移通用工具

```
步骤1: 创建file_tools.py
  • 复制read_file.py逻辑
  • 复制write_file.py逻辑
  • 复制list_files.py逻辑
  • 改进和统一接口

步骤2: 更新导入
  • .olav/skills/olav-admin/tools 导入新位置
  • 其他模块也可以导入

步骤3: 测试
  • 确保导入路径正确
  • 功能测试

工作量: 1天
```

### Phase 3: 编写业务工具

```
步骤1: 编写.olav/skills/olav-admin/tools/下的具体实现
  • device_management.py
  • cron_management.py
  • knowledge_management.py
  • system_management.py
  • skill_management.py

步骤2: 集成到AdminAgent
  • admin_agent.py导入这些工具
  • 测试intent → tool的映射

工作量: 3-4天
```

---

## 决策矩阵

### 对于任何新代码，问自己：

| 问题 | 答案是"是" | 答案是"否" |
|-----|----------|----------|
| 通用吗？(多个系统可能用) | → `src/olav/` | → `.olav/skills/` |
| 框架相关吗？(基础设施) | → `src/olav/` | → `.olav/skills/` |
| Admin特定吗？ | → `.olav/skills/` | → `src/olav/` |
| 业务逻辑吗？ | → `.olav/skills/` | → `src/olav/` |
| 可能被重用吗？ | → `src/olav/` | → `.olav/skills/` |

**规则**: 如果2个及以上的"是"指向同一个答案，就放那里

---

## 具体例子

### 例1: 验证YAML内容

```
问: 这应该放在哪里?
答: ConfigManager.validate_yaml()

理由:
  ✓ 通用工具 (ConfigManager)
  ✓ 框架基础设施
  ✓ 多个系统可能用到
  
位置: src/olav/admin/config_manager.py
```

### 例2: 添加设备到hosts.yaml

```
问: 这应该放在哪里?
答: 业务工具函数 add_device()

理由:
  ✓ 业务逻辑 (具体的设备管理)
  ✓ Admin特定
  ✗ 不通用
  
位置: .olav/skills/olav-admin/tools/device_management.py
```

### 例3: 清理日志

```
问: 这应该放在哪里?
答: 业务工具函数 cleanup_logs()

理由:
  ✓ 业务逻辑 (具体的操作)
  ✓ Admin特定
  ✗ 不通用
  
位置: .olav/skills/olav-admin/tools/system_management.py

但是: 如果其他Skill也需要清理日志，就应该提炼到:
src/olav/admin/system_tools.py → CleanupLogTool()
```

### 例4: 参数验证

```
问: 这应该放在哪里?
答: 框架级验证器

理由:
  ✓ 框架基础设施
  ✓ 被多个工具使用
  ✓ 业务无关
  
位置: src/olav/admin/validators.py

validate_device_params()  → AdminAgent可能需要
validate_cron_schedule()  → AdminAgent可能需要
validate_file_path()      → 多个工具可能需要
```

---

## 总结表格

| 代码类型 | 放置位置 | 示例 | 原因 |
|---------|---------|------|------|
| **Agent核心** | `src/olav/admin/` | AdminAgent class | 框架基础 |
| **配置管理** | `src/olav/admin/` | ConfigManager | 通用工具 |
| **参数验证** | `src/olav/admin/` | validators.py | 框架基础 |
| **异常定义** | `src/olav/admin/` | exceptions.py | 系统级别 |
| **通用文件操作** | `src/olav/admin/` | file_tools.py | 可复用 |
| **设备管理** | `.olav/skills/olav-admin/tools/` | device_management.py | 业务逻辑 |
| **任务管理** | `.olav/skills/olav-admin/tools/` | cron_management.py | 业务逻辑 |
| **知识库管理** | `.olav/skills/olav-admin/tools/` | knowledge_management.py | 业务逻辑 |
| **系统操作** | `.olav/skills/olav-admin/tools/` | system_management.py | 业务逻辑 |
| **Skill操作** | `.olav/skills/olav-admin/tools/` | skill_management.py | 业务逻辑 |

---

## 最佳实践

### ✅ 好的做法

```
1. 框架代码优先放在src/olav/
   原因: 便于复用和维护
   
2. 业务代码优先放在SKILL/tools/
   原因: 与SKILL紧耦合
   
3. 通用工具及时提炼到src/olav/
   原因: 避免代码重复
   
4. 清晰的导入关系
   src/olav -> .olav/skills/(单向)
   不反向导入
```

### ❌ 应避免

```
✗ 将所有代码都放在SKILL/tools/
  问题: 无法复用，框架臃肿

✗ 将业务逻辑放在src/olav/
  问题: 框架层混入业务
  
✗ 多向循环导入
  问题: 维护困难，难以测试
  
✗ 在src/olav/中创建太多子模块
  问题: 结构混乱
```

---

**核心建议**:

从这个矩阵来看，推荐的结构是：

```
src/olav/admin/        ← 框架/通用工具 (1000-1500行)
  admin_agent.py
  config_manager.py
  file_tools.py
  validators.py
  exceptions.py
  base_tools.py

.olav/skills/olav-admin/tools/  ← 业务实现 (750-1100行)
  device_management.py
  cron_management.py
  knowledge_management.py
  system_management.py
  skill_management.py
```

这样做的好处：
- 清晰的分层
- 易于复用
- 易于维护
- 易于测试
- 易于扩展
