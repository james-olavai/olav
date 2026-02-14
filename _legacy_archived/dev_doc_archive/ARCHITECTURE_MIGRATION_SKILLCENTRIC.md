# Skill-Centric 架构迁移计划 v1.0.0

**状态**: 📋 规划中  
**目标**: 完全Skill-Centric架构 - 所有工具和工作流围绕.olav/skills组织  
**创建**: 2026-02-12  
**优先级**: P2 (架构优化)

---

## 📊 问题诊断

### 当前混乱的架构

```
src/olav/
├─ agents/           ← Agent与工具耦合！❌
│  ├─ orchestrator.py (导入 src/olav/tools/data_export)
│  ├─ guard.py (导入 src/olav/tools/network_executor)
│  ├─ inspector.py (导入 src/olav/tools/report_formatter)
│  └─ intent_agent.py (导入 src/olav/tools/network_executor)
├─ tools/            ← 工具在src/olav下 ❌
│  ├─ network_executor.py
│  ├─ data_export.py
│  ├─ report_formatter.py
│  ├─ sync_tools.py
│  └─ ...
└─ ...

.olav/shared/tools/  ← 部分wrapper已创建 ✓
├─ query_database.py
├─ nornir_execute.py
├─ smart_sql_query.py
└─ ...

.olav/skills/
├─ network-query/tools/ (指向.olav/shared/tools)
├─ network-cli/tools/
├─ olav-admin/tools/ (专用工具 ✓)
└─ ...
```

### 📌 问题清单

| # | 问题 | 影响 | 优先级 |
|---|------|------|--------|
| 1 | Agent直接导入 src/olav/tools/ | Skill无法独立使用 | P1 |
| 2 | src/olav/tools 在src下，不在.olav下 | 看不出是Skill一部分 | P2 |
| 3 | 共享工具wrapper在.olav/shared，不在skills | Skill-Centric不完全 | P2 |
| 4 | src/olav/tools 文件冗长复杂 | 难以维护和扩展 | P3 |

---

## ✅ 解决方案

### 最终目标架构

```
【核心原则】Skill-Centric
- 所有工具围绕skills组织
- Agent不依赖src/olav/tools（只依赖.olav/skills/shared/tools）
- 每个skill自管理工具（在skill/tools下）

【目录结构】

src/olav/
├─ agents/           ← 纯Agent逻辑（无工具导入）✅
│  ├─ orchestrator.py
│  ├─ guard.py
│  └─ ...
├─ core/             ← 框架核心
├─ cli/              ← CLI界面
├─ cron/             ← 任务调度
├─ lib/              ← 库函数（data_gateway等）
└─ NOT: tools/       ← 删除！❌

.olav/
└─ skills/           ← 所有Skill及工具在这里 ✅
   ├─ shared/
   │  └─ tools/      ← 共享工具（包装+ forward）
   │     ├─ __init__.py
   │     ├─ query_database.py (包装→src/olav/lib/data_gateway)
   │     ├─ nornir_execute.py (包装→src/olav/tools/network_executor)
   │     ├─ data_export.py (包装→src/olav/tools/data_export)
   │     ├─ report_formatter.py (包装→src/olav/tools/report_formatter)
   │     ├─ network_executor.py (包装→src/olav/tools/network_executor)
   │     └─ sync_tools.py (包装→src/olav/tools/sync_tools)
   ├─ network-query/
   │  ├─ SKILL.md
   │  └─ tools/
   │     ├─ smart_sql_query.py (包装→.olav/shared/tools/query_database)
   │     └─ discover_data.py (包装→.olav/shared/tools/discover_data)
   ├─ network-cli/
   │  ├─ SKILL.md
   │  └─ tools/
   │     ├─ nornir_execute.py (包装→.olav/shared/tools/nornir_execute)
   │     └─ list_devices.py (包装→.olav/shared/tools/list_devices)
   ├─ olav-admin/
   │  ├─ SKILL.md
   │  └─ tools/
   │     ├─ backup_config.py (专用 ✅)
   │     ├─ restore_config.py (专用 ✅)
   │     ├─ list_files.py (专用 ✅)
   │     └─ ...
   └─ ...
```

### 导入链变更

```
【迁移前】❌ 直接导入src/olav/tools
from olav.tools.data_export import format_and_export
from olav.tools.network_executor import get_executor

【迁移后】✅ 通过.olav/skills/shared/tools
from olav.shared.tools.data_export import format_and_export
from olav.shared.tools.network_executor import get_executor

包装器内部：
  .olav/skills/shared/tools/data_export.py:
  └─ from olav.tools.data_export import format_and_export (re-export)
```

---

## 📋 迁移步骤

### Phase 1: 创建完整的shared/tools包装器

**目标**: `.olav/skills/shared/tools/` 包含所有共享工具的包装器

**文件清单** (需要创建的wrapper):

```
.olav/skills/shared/tools/
├─ __init__.py (新建)
├─ data_export.py (新建) → 包装 src/olav/tools/data_export
├─ report_formatter.py (新建) → 包装 src/olav/tools/report_formatter
├─ inspection_views.py (新建) → 包装 src/olav/tools/inspection_views
├─ sync_tools.py (新建) → 包装 src/olav/tools/sync_tools
├─ network_executor.py (新建) → 包装 src/olav/tools/network_executor
├─ api_client.py (新建) → 包装 src/olav/tools/api_client
├─ raw_importer.py (新建) → 包装 src/olav/tools/raw_importer
├─ query_database.py (已有)
├─ smart_sql_query.py (已有)
├─ nornir_execute.py (已有)
├─ list_devices.py (已有)
├─ discover_data.py (已有)
└─ inspect_schema.py (已有)
```

**Wrapper模板**:

```python
#!/usr/bin/env python3
"""
[Tool Name] - Wrapper for Skill-based invocation

Wraps the actual implementation from src/olav/tools/[module].py
Location: .olav/skills/shared/tools/[name].py
"""

# Forward all exports from the actual implementation
from olav.tools.[module_name] import *  # noqa: F401, F403

__all__ = [
    # List all exported functions/classes
    "function_name1",
    "function_name2",
    "ClassName1",
]
```

**需要创建的wrapper文件**:

1. **data_export.py**
   ```python
   from olav.tools.data_export import *  # noqa: F401, F403
   __all__ = ["format_and_export"]
   ```

2. **report_formatter.py**
   ```python
   from olav.tools.report_formatter import *  # noqa: F401, F403
   __all__ = [
       "generate_professional_inspection_report",
       "generate_network_operations_report",
   ]
   ```

3. **inspection_views.py**
   ```python
   from olav.tools.inspection_views import *  # noqa: F401, F403
   __all__ = ["create_inspection_views"]
   ```

4. **sync_tools.py**
   ```python
   from olav.tools.sync_tools import *  # noqa: F401, F403
   __all__ = ["sync_all", "sync_devices"]
   ```

5. **network_executor.py**
   ```python
   from olav.tools.network_executor import *  # noqa: F401, F403
   __all__ = [
       "get_executor",
       "get_nornir",
       "reset_nornir",
       "NetworkExecutor",
       "BatchExecutionRequest",
       "CommandExecutionResult",
   ]
   ```

6. **api_client.py**
   ```python
   from olav.tools.api_client import *  # noqa: F401, F403
   ```

7. **raw_importer.py**
   ```python
   from olav.tools.raw_importer import *  # noqa: F401, F403
   ```

### Phase 2: 修改所有Agent导入

**文件需要修改的Agent** (共13个Python文件):

| 文件 | 当前导入 | 新导入 | 修改行数 |
|------|---------|--------|---------|
| src/olav/agents/orchestrator.py | from olav.tools.data_export | from olav.shared.tools.data_export | 3处 |
| | from olav.tools.network_executor | from olav.shared.tools.network_executor | 1处 |
| src/olav/agents/guard.py | from olav.tools.network_executor | from olav.shared.tools.network_executor | 1处 |
| src/olav/agents/inspector.py | from olav.tools.report_formatter | from olav.shared.tools.report_formatter | 1处 |
| | from olav.tools.inspection_views | from olav.shared.tools.inspection_views | 1处 |
| src/olav/agents/intent_agent.py | from olav.tools.network_executor | from olav.shared.tools.network_executor | 1处 |
| src/olav/agents/analyzer.py | from olav.tools.network | from olav.shared.tools.network_executor | 1处 |
| src/olav/cli/cli_main.py | from olav.tools.network | from olav.shared.tools.network_executor | 多处 |
| | from olav.tools.sync_tools | from olav.shared.tools.sync_tools | 2处 |
| src/olav/cli/commands.py | from olav.tools/... | from olav.shared.tools/... | 待查 |
| src/olav/__init__.py | from olav.tools.network | from olav.shared.tools.network_executor | 1处 |
| scripts/init.py | from olav.tools.network_executor | from olav.shared.tools.network_executor | 2处 |

**修改规则**:

```python
# BEFORE
from olav.tools.data_export import format_and_export
from olav.tools.network_executor import get_executor, BatchExecutionRequest
from olav.tools.report_formatter import generate_professional_inspection_report

# AFTER
from olav.shared.tools.data_export import format_and_export
from olav.shared.tools.network_executor import get_executor, BatchExecutionRequest
from olav.shared.tools.report_formatter import generate_professional_inspection_report
```

**全部修改列表（代码变更）**:

1. **src/olav/agents/orchestrator.py**
   - Line 83: `from olav.tools.data_export` → `from olav.shared.tools.data_export`
   - Line 375: `from olav.tools.data_export` → `from olav.shared.tools.data_export`
   - Line 1173: `from olav.tools.data_export` → `from olav.shared.tools.data_export`
   - Line 1443: `from olav.tools.network_executor` → `from olav.shared.tools.network_executor`

2. **src/olav/agents/guard.py**
   - Line 861: `from olav.tools.network_executor` → `from olav.shared.tools.network_executor`

3. **src/olav/agents/inspector.py**
   - Line 142: `from olav.tools.report_formatter` → `from olav.shared.tools.report_formatter`
   - Line 176: `from olav.tools.inspection_views` → `from olav.shared.tools.inspection_views`

4. **src/olav/agents/intent_agent.py**
   - Line 164: `from olav.tools.network_executor` → `from olav.shared.tools.network_executor`

5. **src/olav/agents/analyzer.py**
   - Need to verify exact import line

6. **src/olav/cli/cli_main.py**
   - `from olav.tools.network` → `from olav.shared.tools.network_executor`
   - `from olav.tools.sync_tools` → `from olav.shared.tools.sync_tools` (2 lines)

7. **src/olav/cli/commands.py**
   - Need to verify exact imports

8. **src/olav/__init__.py**
   - `from olav.tools.network` → `from olav.shared.tools.network_executor`

9. **scripts/init.py**
   - Line 353: `from olav.tools.network_executor` → `from olav.shared.tools.network_executor`
   - Line (其他): 待查

### Phase 3: 清理src/olav/tools（长期）

**不立即删除** - 保留src/olav/tools/作为实现，wrapper指向它

**最终状态**:
- src/olav/tools/ 变成"实现库" - 不直接被导入（agent通过wrapper导入）
- .olav/skills/shared/tools/ 作为official API
- 未来可考虑把src/olav/tools/的代码迁入.olav/skills/shared/ 

---

## 🔄 src/olav/tools中的内部导入

这些文件之间有互相导入，需要处理：

### 内部导入图谱

```
network_executor.py
├─ 被导入: network_parser.py, network.py, sync_tools.py
├─ 导入: (无olav.tools导入)
└─ 无需修改

network_parser.py
├─ 被导入: network_executor.py
├─ 导入: network_executor (olav.tools.network_executor)
└─ 无需修改 (保持src内部导入)

network.py
├─ 被导入: __init__.py
├─ 导入: network_executor, network_parser
└─ 无需修改 (保持src内部导入)

sync_tools.py
├─ 被导入: cli_main.py (需改为shared/tools)
├─ 导入: network_executor (olav.tools.network_executor)
└─ 无需修改 (保持src内部导入)

report_formatter.py
├─ 被导入: inspector.py, sync_tools.py (需改为shared/tools)
├─ 导入: (检查是否有内部导入)
└─ 无需修改 (保持src内部导入)
```

### 规则

✅ **src/olav/tools内部** - 继续使用 `from olav.tools.XXX`
❌ **src/olav外部导入** - 改为 `from olav.shared.tools.XXX`

---

## 📝 代码审计

### 待检查的文件

这些文件可能有额外的导入需要修改：

```
src/olav/cli/commands.py - 检查是否有 from olav.tools
scripts/init.py - 多处可能的导入
src/olav/tools/raw_importer.py - 检查导入链
```

### 输出命令（用于审计）

```bash
# 查找所有旧导入
grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools"

# 确认wrapper创建完毕
ls -la .olav/skills/shared/tools/*.py

# 验证迁移完成（无输出 = 完成）
grep -rn "from olav.tools" src/olav --include="*.py" | grep -vE "src/olav/tools|\.olav/skills"
```

---

## 🚀 执行计划

### Phase 1: 创建Wrapper (1-2天)

```bash
# 1. 在.olav/skills/shared/tools/创建wrapper
#    使用上面提供的模板

# 2. 创建__init__.py导出所有包装器
touch .olav/skills/shared/tools/__init__.py
```

### Phase 2: 修改Agent (1天)

```bash
# 1. 修改13个Python文件的导入
#    使用replace_string_in_file tool

# 2. 运行测试验证
uv run pytest tests/e2e/ -v

# 3. 手工测试
uv run olav ask "test query"
```

### Phase 3: 验证和清理 (1天) [可后期]

```bash
# 1. 运行全套测试
uv run pytest -v

# 2. 审计仍使用olav.tools的代码
grep -rn "from olav.tools" src/ --include="*.py" | grep -v "src/olav/tools"

# 3. 如无输出，迁移完成 ✅
```

---

## ✓ 验证清单

### 迁移前检查

- [ ] 所有wrapper已创建在 `.olav/skills/shared/tools/`
- [ ] 每个wrapper都有正确的 `__all__` 导出

### 迁移中检查

- [ ] 13个Agent文件的导入已修改
- [ ] 没有修改 `src/olav/tools/` 内部的导入
- [ ] 所有测试通过

### 迁移后检查

- [ ] `grep "from olav.tools" src/olav` 仅返回 `src/olav/tools/` 内的导入
- [ ] E2E测试通过
- [ ] `uv run olav ask` 功能正常
- [ ] SKILL.md中的工具声明正常工作

---

## 📊 影响范围

| 文件 | 修改行数 | 难度 | 测试点 |
|------|--------|------|--------|
| orchestrator.py | 4 | ⭐ | 路由、导出、CLI执行 |
| guard.py | 1 | ⭐ | Guard路由、CLI执行 |
| inspector.py | 2 | ⭐ | 检查报告生成 |
| intent_agent.py | 1 | ⭐ | 意图识别 |
| analyzer.py | 1 | ⭐ | 分析功能 |
| cli_main.py | 3 | ⭐⭐ | CLI全功能 |
| __init__.py | 1 | ⭐ | 模块导入 |
| **共计** | **~13** | 低 | E2E测试 |

---

## 🧹 要清理的文代码

### 当前src/olav/tools/中的问题代码

#### 1. **冗余导入** (要保留)
```python
# src/olav/tools/__init__.py 可能有冗余导入
# 作用：允许 from olav.tools import XXX
# 保留：短期内保留（支持旧代码），长期删除
```

#### 2. **混合职责** (待优化)
```python
# src/olav/tools/network.py
# 问题：汇总模块，重新导出多个类
# 待做：整理导出清单
```

#### 3. **CLI依赖** (待处理)
```python
# src/olav/tools/sync_tools.py
# 问题：直接在CLI中导入，不通过wrapper
# 待做：改为导入 olav.shared.tools.sync_tools
```

---

## 📚 参考资源

- [ARCHITECTURE.md](../docs/reference/ARCHITECTURE.md) - 系统架构
- [SKILL_AUTHORING_GUIDE.md](../docs/reference/SKILL_AUTHORING_GUIDE.md) - Skill编写
- [SUB_AGENT_DEVELOPMENT_GUIDE.md](.olav/skills/olav-admin/reference/SUB_AGENT_DEVELOPMENT_GUIDE.md) - SubAgent指南

---

**文档版本**: v1.0.0  
**最后更新**: 2026-02-12  
**维护者**: AI Team  
**状态**: 📋 Ready for implementation
