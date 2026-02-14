# Skill-Centric 架构：技术深度文档

**版本**: v1.0.0  
**作者**: AI Architecture Team  
**日期**: 2026-02-12  
**概览**: Skill-Centric架构的设计原理、rationale，以及为什么需要wrapper层

---

## 📚 架构概览

### 核心原则

```
【Skill-Centric Architecture】核心规则：

1. 所有功能皆为Skill
   ✅ 每个功能都有SKILL.md描述其参数、工具、LLM角色
   ✅ Skill就是系统的最小功能单位

2. 工具围绕Skill组织
   ✅ 工具要么在 .olav/skills/shared/ (
   ✅ 要么在 .olav/skills/{skill}/tools/ (skill-specific)
   ❌ 绝对不在 src/olav/tools (代码库内)

3. Agent不直接使用工具
   ✅ Agent不知道工具的具体实现
   ✅ 工具由Skill声明和提供
   ❌ Agent不导入src/olav/tools

4. 所有导入通过wrapper
   ✅ Agent → 导入 olav.shared.tools.* (wrapper)
   ✅ Wrapper → 导入 src/olav/tools.* (实现)
   ✅ src/olav/tools 变成"私有库"，不对外暴露
```

### 为什么需要Wrapper？

| 原因 | 问题 | 解决 |
|------|------|------|
| **架构清晰** | Agent直接耦合src/olav/tools，不知道这是Skill一部分 | Wrapper使工具看起来来自.olav/skills |
| **Skill独立** | 无法单独打包/使用Skill，因为依赖src/olav在项目根 | Wrapper让Skill看起来自给自足 |
| **维护简单** | src/olav/tools 903行代码在src根，和agent混在一起 | Wrapper使实现和接口分离 |
| **扩展容易** | 如果要修改某个工具在system-admin中独占使用 | Wrapper在.olav/skills/中，易于创建skill-specific版本 |
| **DuckDB兼容** | 未来可能要把工具也纳入DuckDB（作为存储层） | Wrapper层便于这种架构演进 |

---

## 🔄 导入链设计

### Before (混乱的架构)

```
Agent Code:
├─ orchestrator.py
│  ├─ import from olav.tools.data_export ❌ 直接耦合
│  ├─ import from olav.tools.network_executor ❌
│  └─ import from olav.tools.report_formatter ❌
├─ guard.py
│  └─ import from olav.tools.network_executor ❌
└─ ...

CLI Code:
├─ cli_main.py
│  ├─ import from olav.tools.network ❌
│  └─ import from olav.tools.sync_tools ❌
└─ ...

Implementation (src/olav/tools):
├─ network_executor.py ........... 900+ lines，复杂
├─ data_export.py ............... 800+ lines
├─ report_formatter.py .......... 900+ lines
├─ sync_tools.py ............... 700+ lines
├─ inspection_views.py ......... many lines
└─ ...

问题：
- Agent看不出这些工具属于哪个Skill
- 工具位置在src，给人感觉不是Skill的一部分
- 需要修改工具时，在src下修改，但职责不清
```

### After (Skill-Centric 架构)

```
Agent Code (src/olav/agents/):
├─ orchestrator.py
│  ├─ import from olav.shared.tools.data_export ✅ 通过wrapper
│  ├─ import from olav.shared.tools.network_executor ✅
│  └─ import from olav.shared.tools.report_formatter ✅
├─ guard.py
│  └─ import from olav.shared.tools.network_executor ✅
└─ ...

Skill-Centric Tools Layer (.olav/skills/shared/tools/):
├─ __init__.py
├─ data_export.py ........................ Wrapper + re-export
├─ network_executor.py .................. Wrapper + re-export
├─ report_formatter.py .................. Wrapper + re-export
├─ sync_tools.py ........................ Wrapper + re-export
├─ inspection_views.py .................. Wrapper + re-export
└─ [other wrappers]

Implementation Layer (src/olav/tools/):
├─ network_executor.py ........... 实际实现（不直接导入）
├─ data_export.py ............... 实际实现（通过wrapper导入）
├─ report_formatter.py .......... 实际实现
├─ sync_tools.py ............... 实际实现
└─ ...

优势：
✅ Agent知道工具来自 olav.shared.tools 
✅ 工具看起来是shared Skill的一部分
✅ 实现和接口分离，易于修改和扩展
✅ 支持sky-specific工具覆盖（在skill/tools下创建版本）
```

---

## 🎯 各个Wrapper的设计

### Wrapper 1: `data_export.py`

**目的**: 数据导出功能 (CSV, JSON, etc)

**原实现位置**: `src/olav/tools/data_export.py` (900+ lines)

**主要函数**:
- `format_and_export(results, format='csv', filepath='exports/')` - 导出查询结果

**使用者**:
- `orchestrator.py` (Line 83, 375, 1173) - 3处调用

**Wrapper设计**:
```python
from olav.tools.data_export import format_and_export

# 为什么不创建新实现？
# - 现有实现已成熟（900+ lines已测试）
# - wrapper只是转发，没有逻辑变化
# - 将来如需修改，直接在src/olav/tools/修改，wrapper自动继承

__all__ = ["format_and_export"]
```

**未来可能的修改**:
```python
# 如果某个skill需要特殊导出格式：
# .olav/skills/network-admin/tools/data_export.py
# 可以覆盖这个shared wrapper的版本
```

---

### Wrapper 2: `network_executor.py`

**目的**: 网络设备执行框架 (Nornir wrap)

**原实现位置**: `src/olav/tools/network_executor.py` (900+ lines)

**主要类和函数**:
- `class NetworkExecutor` - 主执行器
- `function get_executor()` - 获取执行器实例
- `function get_nornir()` - 获取Nornir实例
- `class BatchExecutionRequest` - 批量执行请求
- `class CommandExecutionResult` - 执行结果

**使用者** (多处):
- `orchestrator.py` (Line 1443)
- `guard.py` (Line 861)
- `intent_agent.py` (Line 164)
- `analyzer.py` (推断)
- `cli_main.py` (多处)

**Wrapper设计**:
```python
from olav.tools.network_executor import (
    BatchExecutionRequest,
    CommandExecutionResult,
    NetworkExecutor,
    get_executor,
    get_nornir,
    reset_nornir,
)

__all__ = [
    "get_executor",
    "get_nornir", 
    "reset_nornir",
    "NetworkExecutor",
    "BatchExecutionRequest",
    "CommandExecutionResult",
]

# 为什么不改造成Skill工具？
# - 复杂度高（900+ lines），涉及Nornir全套
# - 依赖多（inventory, groups, hosts等）
# - 不是每个Skill都需要，但shared ones需要
# - 现在wrapper方案允许未来gradual迁移
```

**扩展点**:
```python
# 如果某个Skill需要定制化执行器：
# 可在 skill/tools/network_executor.py 实现定制版本
# 该skill的Agent导入此版本而非shared版本
```

---

### Wrapper 3: `report_formatter.py`

**目的**: 生成专业报告（巡检报告、运维报告）

**原实现位置**: `src/olav/tools/report_formatter.py` (904 lines)

**主要函数**:
- `generate_professional_inspection_report()` - 巡检报告
- `generate_network_operations_report()` - 运维报告
- 其他report生成函数

**使用者**:
- `inspector.py` (Line 142)

**Wrapper设计**:
```python
from olav.tools.report_formatter import (
    generate_professional_inspection_report,
    generate_network_operations_report,
)

__all__ = [
    "generate_professional_inspection_report",
    "generate_network_operations_report",
]
```

**为什么独立成wrapper**:
- 虽然当前只有inspector.py用，但未来其他Skill（如admin）也可能需要

**设计考虑**:
```python
# 可能的改进方向：
# 1. Skill-specific报告格式
#    .olav/skills/network-admin/tools/report_formatter.py
# 2. 报告模板库
#    .olav/skills/shared/tools/report_templates/
# 3. 报告缓存
#    src/olav/lib/report_cache.py
```

---

### Wrapper 4: `inspection_views.py`

**目的**: 巡检视图（结构化输出）

**原实现位置**: `src/olav/tools/inspection_views.py`

**主要函数**:
- `create_inspection_views()` - 创建视图结构

**使用者**:
- `inspector.py` (Line 176)

**Wrapper设计**:
```python
from olav.tools.inspection_views import create_inspection_views

__all__ = ["create_inspection_views"]
```

---

### Wrapper 5: `sync_tools.py`

**目的**: 设备数据同步（与外部系统）

**原实现位置**: `src/olav/tools/sync_tools.py` (722 lines)

**主要函数**:
- `sync_all()` - 同步所有数据
- `sync_devices()` - 同步设备
- `SyncResult`, `SyncStatus` - 结果和状态类

**使用者**:
- `cli_main.py` (2处)

**Wrapper设计**:
```python
from olav.tools.sync_tools import *  # noqa: F401, F403

__all__ = ["sync_all", "sync_devices", "SyncResult", "SyncStatus"]
```

**注意**:
- CLI直接调用sync，不通过Agent
- 但仍要通过wrapper保持一致性

---

### Wrapper 6: `api_client.py`

**目的**: 与外部API通信

**原实现位置**: `src/olav/tools/api_client.py`

**使用者**: 暂时unknown，但为完整性添加

**Wrapper设计**:
```python
from olav.tools.api_client import *  # noqa: F401, F403

__all__ = [
    # List public API
]
```

---

### Wrapper 7: `raw_importer.py`

**目的**: 导入原始数据

**原实现位置**: `src/olav/tools/raw_importer.py`

**使用者**: CLI和Admin skill

**Wrapper设计**:
```python
from olav.tools.raw_importer import *  # noqa: F401, F403

__all__ = [
    # List public API
]
```

---

## 🔗 依赖关系图

### src/olav/tools内部的导入链

```
【重要】src/olav/tools内部的导入需要继续使用olav.tools前缀
       这些是实现细节，不通过wrapper

network_executor.py (900+ lines，核心)
  ├─ No imports from olav.tools (self-contained)
  └─ Imports: nornir, asyncio, typing, pydantic

network_parser.py
  ├─ import from olav.tools.network_executor ✅ (src内部，保持)
  ├─ Imports: json, re, typing
  └─ Exports: TextFSMParser, JuniperConfigParser, etc.

network.py (汇总/导出模块)
  ├─ import from olav.tools.network_executor ✅ (src内部，保持)
  ├─ import from olav.tools.network_parser ✅ (src内部，保持)
  └─ Exports: nornir_execute, ConfigurationAnalyzer, etc.

sync_tools.py (722 lines)
  ├─ import from olav.tools.network_executor ✅ (src内部，保持)
  ├─ import from olav.tools.report_formatter ✅ (src内部，保持)
  └─ Exports: sync_all, sync_devices, SyncResult, etc.

report_formatter.py (904 lines)
  ├─ No direct imports from olav.tools (uses data structures)
  └─ Exports: generate_professional_inspection_report, etc.

data_export.py (900+ lines)
  ├─ No imports from olav.tools (uses data structures)
  └─ Exports: format_and_export, etc.

规则：
✅ src/olav/tools/* 之间导入 → 继续使用 from olav.tools.XXX
❌ src/olav外部导入 → 改为 from olav.shared.tools.XXX
```

### src/olav/tools → .olav/shared/tools 转发

```
请求流：

src/olav/agents/orchestrator.py
  └─ from olav.shared.tools.data_export import format_and_export
     └─ .olav/skills/shared/tools/data_export.py (wrapper)
        └─ from olav.tools.data_export import format_and_export
           └─ src/olav/tools/data_export.py (实现)


src/olav/agents/guard.py
  └─ from olav.shared.tools.network_executor import get_executor
     └─ .olav/skills/shared/tools/network_executor.py (wrapper)
        └─ from olav.tools.network_executor import get_executor
           └─ src/olav/tools/network_executor.py (实现)

这样的好处：
1. Agent只知道olav.shared.tools (Skill-Centric)
2. Wrapper location在.olav/，表明这是Skill的一部分
3. 实现在src/olav/，可以独立维护
```

---

## 📊 迁移前后的代码结构

### Before (混乱)

```python
# src/olav/agents/orchestrator.py - Line 83
from olav.tools.data_export import format_and_export  # ❌ 什么意思？
# 看不出这是Skill工具

# src/olav/cli/cli_main.py
from olav.tools.sync_tools import sync_all  # ❌ 这个工具属于哪个Skill？
from olav.tools.network import something  # ❌ network是什么？

# .olav/skills/*/SKILL.md
# tools:
#   - nornir_execute
#   - discover_data
# 
# 但Agent导入的都是src/olav/tools中的东西，不清楚关系

# src/olav/tools/network_executor.py - 900行
# 位置混乱，不清楚这属于哪个Skill
```

### After (清晰)

```python
# src/olav/agents/orchestrator.py - Line 83
from olav.shared.tools.data_export import format_and_export  # ✅ 
# 清楚：来自.olav/skills（Skill-Centric）

# src/olav/cli/cli_main.py
from olav.shared.tools.sync_tools import sync_all  # ✅
from olav.shared.tools.network_executor import get_executor  # ✅

# 导入链一目了然：
# olav.shared.tools → .olav/skills/shared/tools/ → 原实现库

# SKILL.md 对应关系清晰：
# .olav/skills/shared/SKILL.md
#   tools:
#     - data_export (from olav.shared.tools.data_export)
#     - network_executor (from olav.shared.tools.network_executor)

# src/olav/tools/ 变成私有库，通过wrapper导出
```

---

## 🛠️ 技术实现细节

### Wrapper的最小实现

```python
"""最小wrapper - 只做re-export"""

# 选项1：显式导入（推荐，清晰）
from olav.tools.data_export import format_and_export

__all__ = ["format_and_export"]


# 选项2：通配符导入（简单但隐式）
from olav.tools.data_export import *  # noqa: F401, F403

__all__ = [
    "format_and_export",
    # 明确列明所有导出
]
```

### 为什么wrapper不添加额外逻辑？

```python
# ❌ 错误：wrapper添加装饰器
from olav.tools.data_export import format_and_export as _format_and_export

@timing_decorator
def format_and_export(*args, **kwargs):
    return _format_and_export(*args, **kwargs)

# 问题：
# 1. 增加复杂度
# 2. 如果src/olav/tools更新，wrapper也要跟着改
# 3. 打破wrapper的核心目的（仅仅是导入转发）


# ✅ 正确：wrapper仅仅转发
from olav.tools.data_export import format_and_export

# 如果需要装饰：
# 1. 在src/olav/tools中直接添加
# 2. 或在Agent中使用装饰器
# 3. 或在.olav/skills/{skill}/tools中创建skill-specific版本
```

---

## 🎯 设计决策：为什么选择这个方案？

### 方案对比

| 方案 | 优点 | 缺点 | 选择 |
|------|------|------|------|
| **A: 直接导入**<br/>`from olav.tools.*` | 简单，无overhead | 架构不清晰，不Skill-Centric | ❌ |
| **B: 轻量wrapper**<br/>(当前选择) | 清晰，maintainable，支持future扩展 | 多一层文件 | ✅ |
| **C: 重实现**<br/>复制到.olav/skills/ | 完全独立 | 代码重复，难维护 | ❌ |
| **D: 强行迁移**<br/>移动到.olav/ | 一步到位 | 大风险，容易引入bug | ❌ |

**选择理由**:
- wrapper方案是 **渐进式迁移** 的最佳平衡
- 允许现有代码继续工作（src/olav/tools）
- 允许未来优化（wrapper → 实现迁移）
- 降低风险（仅改导入路径，不改逻辑）
- 支持skill-specific定制（创建override版本）

---

## 🔮 未来演进路径

### Phase N+1: 实现层优化

```
当前状态:
src/olav/tools/ (900+ line files)
  └─ wrapper layer (.olav/skills/shared/tools/)
    └─ Agent导入

改进方向:
1. 可以逐步把.olav/skills/shared/tools中的代码
   变成真实实现而非wrapper

2. 或者创建skill-specific版本覆盖shared版本
   .olav/skills/network-admin/tools/data_export.py
   └─ 自定义导出格式

3. 最终目标：src/olav/tools完全变成library/vendor
   所有Skill都通过wrapper导入
```

### 未来可能的改动：功能拆分

```python
# 如果network_executor.py变得太复杂（900+ lines）
# 可以拆分成：

.olav/skills/shared/tools/
├─ network_executor.py (主体：转发get_executor等)
├─ network_executor_async.py (async变体)
├─ network_executor_batch.py (批量执行特化版本)
└─ network_executor_cache.py (缓存版本)

每个Skill可以选择合适的版本:
.olav/skills/network-admin/tools/
  └─ __init__.py:
     from olav.shared.tools.network_executor_batch import *
```

---

## 📋 技术检查清单

### Wrapper创建时检查

- [ ] 文件位置正确：`.olav/skills/shared/tools/{name}.py`
- [ ] 能导入原始实现：`from olav.tools.{module} import ...`
- [ ] `__all__` 列表完整且正确
- [ ] 没有添加额外逻辑（仅转发）
- [ ] 文件头注释说明了包装目的

### Agent导入修改时检查

- [ ] 所有导入改为：`from olav.shared.tools.*`
- [ ] 函数/类名没有改变
- [ ] 导入块保持在文件顶部
- [ ] 没有改动实现逻辑（仅改导入）

### 验证步骤

```python
# 方法1：Import检查
python3 -c "from olav.shared.tools.data_export import format_and_export; print('OK')"

# 方法2：功能检查
python3 -c "
from olav.shared.tools.network_executor import get_executor
executor = get_executor()
print(f'Got executor: {type(executor).__name__}')
"

# 方法3：完整导入检查
python3 << 'EOF'
import importlib
modules = [
    'olav.shared.tools.data_export',
    'olav.shared.tools.network_executor',
    'olav.shared.tools.report_formatter',
    'olav.shared.tools.inspection_views',
    'olav.shared.tools.sync_tools',
]
for mod in modules:
    m = importlib.import_module(mod)
    print(f'✅ {mod}')
EOF
```

---

## 🎓 学习资源

- [ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md) - 系统架构 overview
- [SKILL_AUTHORING_GUIDE.md](../docs/reference/SKILL_AUTHORING_GUIDE.md) - 如何定义Skill
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](../docs/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - Agent开发

---

**文档版本**: v1.0.0  
**更新日期**: 2026-02-12  
**维护**: AI Architecture Team  
**可用性**: Open (用于reference和审审)
