# Skill-Centric 架构迁移 - 操作指南

**版本**: v1.0.0  
**创建日期**: 2026-02-12  
**状态**: 📋 Ready for implementation  
**所属**: 迁移计划 Phase 1-2

---

## 📋 总览

本指南提供了分步骤的代码修改清单，包含：
1. ✅ 必须创建的wrapper文件
2. 📝 代码修改位置和内容  
3. 🧪 验证步骤  
4. 🎯 快速检查清单

---

## ✅ Phase 1: 创建Wrapper文件

### 目录结构

```
.olav/skills/shared/tools/
├─ __init__.py ...................... 主入口 ✓ (已有)
├─ query_database.py ................ ✓ (已有)
├─ smart_sql_query.py ............... ✓ (已有)
├─ nornir_execute.py ................ ✓ (已有)
├─ list_devices.py .................. ✓ (已有)
├─ discover_data.py ................. ✓ (已有)
├─ inspect_schema.py ................ ✓ (已有)
├─ 【新增】data_export.py ............. (NEW)
├─ 【新增】report_formatter.py ........ (NEW)
├─ 【新增】inspection_views.py ........ (NEW)
├─ 【新增】sync_tools.py ............. (NEW)
├─ 【新增】network_executor.py ....... (NEW)
├─ 【新增】api_client.py ............. (NEW)
└─ 【新增】raw_importer.py ........... (NEW)
```

### 要创建的Wrapper文件 (7个)

#### 1️⃣ `.olav/skills/shared/tools/data_export.py`

```python
"""
Data Export Tool - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.data_export.format_and_export()

Location: .olav/skills/shared/tools/data_export.py
Purpose: Re-export data export functionality for Skill-Centric architecture
"""

from olav.tools.data_export import format_and_export  # noqa: F401

__all__ = ["format_and_export"]
```

#### 2️⃣ `.olav/skills/shared/tools/report_formatter.py`

```python
"""
Report Formatter Tool - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.report_formatter.generate_professional_inspection_report()
  - olav.tools.report_formatter.generate_network_operations_report()

Location: .olav/skills/shared/tools/report_formatter.py
Purpose: Re-export report formatting functionality for Skill-Centric architecture
"""

from olav.tools.report_formatter import (  # noqa: F401
    generate_professional_inspection_report,
    generate_network_operations_report,
)

__all__ = [
    "generate_professional_inspection_report",
    "generate_network_operations_report",
]
```

#### 3️⃣ `.olav/skills/shared/tools/inspection_views.py`

```python
"""
Inspection Views Tool - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.inspection_views.create_inspection_views()

Location: .olav/skills/shared/tools/inspection_views.py
Purpose: Re-export inspection views functionality for Skill-Centric architecture
"""

from olav.tools.inspection_views import create_inspection_views  # noqa: F401

__all__ = ["create_inspection_views"]
```

#### 4️⃣ `.olav/skills/shared/tools/sync_tools.py`

```python
"""
Sync Tools - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.sync_tools.sync_all()
  - olav.tools.sync_tools.sync_devices()
  - And other sync-related functions

Location: .olav/skills/shared/tools/sync_tools.py
Purpose: Re-export sync functionality for Skill-Centric architecture
"""

from olav.tools.sync_tools import *  # noqa: F401, F403

__all__ = [
    "sync_all",
    "sync_devices",
    "SyncResult",
    "SyncStatus",
]
```

#### 5️⃣ `.olav/skills/shared/tools/network_executor.py`

```python
"""
Network Executor Tool - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.network_executor.get_executor()
  - olav.tools.network_executor.get_nornir()
  - olav.tools.network_executor.reset_nornir()
  - olav.tools.network_executor.NetworkExecutor
  - olav.tools.network_executor.BatchExecutionRequest
  - olav.tools.network_executor.CommandExecutionResult

Location: .olav/skills/shared/tools/network_executor.py
Purpose: Re-export network execution functionality for Skill-Centric architecture
"""

from olav.tools.network_executor import (  # noqa: F401
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
```

#### 6️⃣ `.olav/skills/shared/tools/api_client.py`

```python
"""
API Client Tool - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.api_client.*

Location: .olav/skills/shared/tools/api_client.py
Purpose: Re-export API client functionality for Skill-Centric architecture
"""

from olav.tools.api_client import *  # noqa: F401, F403

__all__ = [
    # Import and export all public API
]
```

#### 7️⃣ `.olav/skills/shared/tools/raw_importer.py`

```python
"""
Raw Data Importer Tool - Wrapper for Skill-based invocation

Wraps:
  - olav.tools.raw_importer.*

Location: .olav/skills/shared/tools/raw_importer.py
Purpose: Re-export raw data import functionality for Skill-Centric architecture
"""

from olav.tools.raw_importer import *  # noqa: F401, F403

__all__ = [
    # Import and export all public API
]
```

### 验证Wrapper创建 ✓

```bash
# 检查所有wrapper文件已创建
ls -1 .olav/skills/shared/tools/*.py

# 应该显示：
# __init__.py
# api_client.py (NEW)
# data_export.py (NEW)
# discover_data.py
# inspect_schema.py
# inspection_views.py (NEW)
# list_devices.py
# network_executor.py (NEW)
# nornir_execute.py
# query_database.py
# raw_importer.py (NEW)
# report_formatter.py (NEW)
# smart_sql_query.py
# sync_tools.py (NEW)

# 检查__init__.py导出 (应该包含所有工具)
cat .olav/skills/shared/tools/__init__.py
```

---

## 📝 Phase 2: 修改Agent导入

### 文件修改清单 (13个文件)

#### 【File 1】`src/olav/agents/orchestrator.py`

**修改行数**: 4处

```python
# 【修改1】Line ~83
# BEFORE:
from olav.tools.data_export import format_and_export

# AFTER:
from olav.shared.tools.data_export import format_and_export


# 【修改2】Line ~375
# BEFORE:
from olav.tools.data_export import format_and_export

# AFTER:
from olav.shared.tools.data_export import format_and_export


# 【修改3】Line ~1173
# BEFORE:
from olav.tools.data_export import format_and_export

# AFTER:
from olav.shared.tools.data_export import format_and_export


# 【修改4】Line ~1443
# BEFORE:
from olav.tools.network_executor import get_executor

# AFTER:
from olav.shared.tools.network_executor import get_executor
```

**验证**:
```bash
grep -n "from olav.tools" src/olav/agents/orchestrator.py
# 应该无输出（没有找到）
grep -n "from olav.shared.tools" src/olav/agents/orchestrator.py
# 应该显示修改后的行
```

---

#### 【File 2】`src/olav/agents/guard.py`

**修改行数**: 1处

```python
# 【修改】Line ~861
# BEFORE:
from olav.tools.network_executor import get_executor, BatchExecutionRequest

# AFTER:
from olav.shared.tools.network_executor import get_executor, BatchExecutionRequest
```

**验证**:
```bash
grep -n "from olav.tools\|from olav.shared.tools" src/olav/agents/guard.py | grep network_executor
```

---

#### 【File 3】`src/olav/agents/inspector.py`

**修改行数**: 2处

```python
# 【修改1】Line ~142
# BEFORE:
from olav.tools.report_formatter import generate_professional_inspection_report

# AFTER:
from olav.shared.tools.report_formatter import generate_professional_inspection_report


# 【修改2】Line ~176
# BEFORE:
from olav.tools.inspection_views import create_inspection_views

# AFTER:
from olav.shared.tools.inspection_views import create_inspection_views
```

**验证**:
```bash
grep -n "from olav.tools\|from olav.shared.tools" src/olav/agents/inspector.py | grep -E "report_formatter|inspection_views"
```

---

#### 【File 4】`src/olav/agents/intent_agent.py`

**修改行数**: 1处

```python
# 【修改】Line ~164
# BEFORE:
from olav.tools.network_executor import get_executor

# AFTER:
from olav.shared.tools.network_executor import get_executor
```

---

#### 【File 5】`src/olav/agents/analyzer.py`

**修改行数**: 待确认 (至少1处)

```bash
# 首先查找当前导入
grep -n "from olav.tools" src/olav/agents/analyzer.py

# 示例（根据结果修改）:
# BEFORE:
from olav.tools.network import nornir_execute

# AFTER:
from olav.shared.tools.network_executor import nornir_execute
```

---

#### 【File 6】`src/olav/cli/cli_main.py`

**修改行数**: 3+ 处

```bash
# 首先查找所有import
grep -n "from olav.tools" src/olav/cli/cli_main.py

# 示例修改:
# BEFORE:
from olav.tools.network import something
from olav.tools.sync_tools import sync_all

# AFTER:
from olav.shared.tools.network_executor import something
from olav.shared.tools.sync_tools import sync_all
```

---

#### 【File 7】`src/olav/cli/commands.py`

**修改行数**: 待确认

```bash
# 首先查找当前导入
grep -n "from olav.tools" src/olav/cli/commands.py

# 根据结果修改相应导入
```

---

#### 【File 8】`src/olav/__init__.py`

**修改行数**: 1处

```python
# BEFORE:
from olav.tools.network import ...

# AFTER:
from olav.shared.tools.network_executor import ...
```

---

#### 【File 9-13】其他可能的文件

```bash
# 查找所有剩余的 from olav.tools 导入
grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools/"

# 对每一个结果进行修改（改为 from olav.shared.tools）
```

---

## 🧪 验证步骤

### Step 1: 检查导入migrate完成

```bash
# 命令：查找所有非src/olav/tools下的olav.tools导入
grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools/"

# 预期输出：
# (空白 = 完成)
```

### Step 2: 检查导入正确性

```bash
# 检查wrapper是否都正确导出
python3 -c "from olav.shared.tools import *; print('✅ Imports successful')"

# 检查各个工具可用性
python3 << 'EOF'
from olav.shared.tools.data_export import format_and_export
from olav.shared.tools.network_executor import get_executor
from olav.shared.tools.report_formatter import generate_professional_inspection_report
from olav.shared.tools.inspection_views import create_inspection_views
from olav.shared.tools.sync_tools import sync_all
print("✅ All wrapped tools imported successfully")
EOF
```

### Step 3: 运行E2E测试

```bash
# 运行所有E2E测试
uv run pytest tests/e2e/test_real_scenarios.py -v

# 如果有特定的skipped tests，运行它们
uv run pytest tests/e2e/ -k "test_" -v

# 期望：所有测试通过 ✅
```

### Step 4: 手动测试CLI

```bash
# 基础查询测试
uv run olav ask "有多少个设备?"

# 导出测试 (验证data_export wrapper工作)
uv run olav ask "export devices to csv"

# CLI执行测试 (验证network_executor wrapper工作)
uv run olav ask "show me device config for 10.0.0.1"

# 报告生成测试 (验证report_formatter wrapper工作)
uv run olav ask "generate network report"
```

---

## 🎯 快速检查清单

### Pre-Migration 检查

- [ ] 当前所有E2E测试通过: `uv run pytest tests/e2e/ -v`
- [ ] 当前CLI功能正常: `uv run olav ask "test query"`
- [ ] Git是干净的: `git status` (没有uncommitted changes)
- [ ] 备份代码: `git commit -m "Pre-migration backup"`

### Wrapper创建检查

- [ ] 7个wrapper文件已创建
- [ ] 每个wrapper都能被导入
- [ ] `from olav.shared.tools import *` 成功
- [ ] 没有circular import错误

### 代码修改检查

- [ ] orchestrator.py: 4处修改完成 ✅
- [ ] guard.py: 1处修改完成 ✅
- [ ] inspector.py: 2处修改完成 ✅
- [ ] intent_agent.py: 1处修改完成 ✅
- [ ] analyzer.py: 修改完成 ✅
- [ ] cli/cli_main.py: 修改完成 ✅
- [ ] cli/commands.py: 修改完成 ✅
- [ ] __init__.py: 修改完成 ✅
- [ ] `grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools"` 无输出

### 测试检查

- [ ] E2E测试全部通过: ✅
- [ ] CLI查询功能正常: ✅
- [ ] CLI导出功能正常: ✅
- [ ] 报告生成功能正常: ✅
- [ ] Guard路由功能正常: ✅
- [ ] Inspector检查功能正常: ✅

### 最终检查

- [ ] 代码提交: `git commit -m "refactor: migrate all imports to olav.shared.tools wrapper layer"`
- [ ] 推送: `git push`
- [ ] CI/CD 通过: ✅

---

## 🚀 执行时间估计

| 任务 | 时长 | 难度 |
|------|------|------|
| 创建7个wrapper文件 | 10分钟 | ⭐ |
| 修改13个Python文件 | 30分钟 | ⭐ |
| 验证导入 | 10分钟 | ⭐ |
| 运行E2E测试 | 5分钟 | ⭐ |
| 手动测试 | 15分钟 | ⭐ |
| **总计** | **~70分钟** | 低 |

---

## 📚 参考

- [ARCHITECTURE_MIGRATION_SKILLCENTRIC.md](./ARCHITECTURE_MIGRATION_SKILLCENTRIC.md) - 架构设计
- [SKILL_AUTHORING_GUIDE.md](../docs/reference/SKILL_AUTHORING_GUIDE.md) - Skill编写指南
- [TESTING_QUICK_REFERENCE.md](../docs/reference/TESTING_QUICK_REFERENCE.md) - 测试指南

---

**版本**: v1.0.0  
**状态**: 📋 Ready  
**最后更新**: 2026-02-12
