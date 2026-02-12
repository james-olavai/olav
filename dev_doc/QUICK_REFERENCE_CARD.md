# Skill-Centric 迁移 - 快速参考卡

**打印并贴在桌边** 📌 | **或作为IDE书签** 🔖

---

## 🎯 一句话总结

```
【迁移目标】
Agent 导入从 "from olav.tools.*" 改为 "from olav.shared.tools.*"
（符合Skill-Centric架构，工具变成.olav/skills的一部分）
```

---

## 📋 完成清单 (优先级顺序)

```
【TODAY - 必做】
☐ 创建7个wrapper文件 (30 min)
  └─ .olav/skills/shared/tools/{data_export, network_executor, 
                               report_formatter, inspection_views, 
                               sync_tools, api_client, raw_importer}.py

☐ 修改13个文件的导入 (45 min)
  └─ grep -rn "from olav.tools" src/olav | 每一个改成 from olav.shared.tools

☐ 验证 (30 min)
  └─ grep -rn "from olav.tools" src/olav | grep -v src/olav/tools  (应无结果✅)
  └─ uv run pytest tests/e2e/ -v (应全部通过✅)

【END OF DAY】
✅ git push
```

---

## 🔀 导入改动规则

| 位置 | 当前 | 改为 | 保持 |
|-------|------|------|------|
| **src/olav/agents/** | `from olav.tools` | `from olav.shared.tools` | ❌ 全改 |
| **src/olav/cli/** | `from olav.tools` | `from olav.shared.tools` | ❌ 全改 |
| **src/olav/__init__.py** | `from olav.tools` | `from olav.shared.tools` | ❌ 改 |
| **src/olav/tools/** | `from olav.tools` | `from olav.tools` | ✅ 保持 |
| **.olav/skills/*/tools/** | 如有导入 | `from olav.shared.tools` | ❌ 全改 |

---

## 📝 Wrapper 模板 (复制粘贴)

```python
"""
[工具名] - Skill-based wrapper

Wraps: olav.tools.[module_name]
Location: .olav/skills/shared/tools/[name].py
"""

from olav.tools.[module_name] import (
    function_or_class_1,
    function_or_class_2,
)

__all__ = [
    "function_or_class_1",
    "function_or_class_2",
]
```

---

## 🔍 需要修改的 13 个文件

```
【6个Agent文件】
□ src/olav/agents/orchestrator.py      ← 4处 修改data_export, network_executor
□ src/olav/agents/guard.py              ← 1处 修改network_executor  
□ src/olav/agents/inspector.py          ← 2处 修改report_formatter, inspection_views
□ src/olav/agents/intent_agent.py       ← 1处 修改network_executor
□ src/olav/agents/analyzer.py           ← 1处 修改network_executor
□ scripts/init.py (if exists)           ← 2处 修改network_executor

【2个CLI文件】
□ src/olav/cli/cli_main.py              ← 3+处 修改network, sync_tools
□ src/olav/cli/commands.py              ← N处 (待查)

【1个核心文件】
□ src/olav/__init__.py                  ← 1处 修改network导入

【其他可能的文件】
□ src/olav/tools/raw_importer.py        ← 检查是否有internal导入需要修改
```

---

## ⚡ 命令速查表

```bash
# 【查看】所有需要修改的导入
grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools"

# 【检查】迁移是否完成（应该无输出）
grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools" | grep -v "olav.shared"

# 【测试】导入
uv run python3 -c "from olav.shared.tools import *; print('✅')"

# 【验证】E2E测试
uv run pytest tests/e2e/test_real_scenarios.py -v

# 【手动】测试功能
uv run olav ask "有多少个设备?"
```

---

## 🧪 测试要点

```
【导入检查】✅
  ✓ 所有wrapper能正常导入
  ✓ 没有circular import
  ✓ 所有导出的函数/类可用

【功能检查】✅
  ✓ uv run olav ask "query"
  ✓ uv run olav ask "export to csv"
  ✓ CLI加密和执行工作
  ✓ 报告生成工作
  ✓ Guard路由工作

【代码检查】✅
  ✓ src/olav/tools内部导入保持不变（仍用olav.tools）
  ✓ 外部只用olav.shared.tools
  ✓ 没有新增的unused imports
```

---

## 🚨 常见错误及修复

```
【错误1】ImportError: cannot import name 'XXX' from 'olav.shared.tools'
├─ 原因：wrapper没有导出这个名字
├─ 修复：检查wrapper的__all__是否包含它
└─ 验证：grep "__all__" .olav/skills/shared/tools/[name].py

【错误2】ModuleNotFoundError: No module named 'olav.shared.tools'
├─ 原因：.olav/skills/shared/tools/__init__.py不存在或有问题
├─ 修复：检查该目录结构，确保__init__.py存在
└─ 验证：ls .olav/skills/shared/tools/__init__.py

【错误3】from olav.tools 其他包导入不存在
├─ 原因：忘记创建某个wrapper
├─ 修复：创建缺失的wrapper文件
└─ 验证：ls .olav/skills/shared/tools/{name}.py

【错误4】Circular import
├─ 原因：wrapper导入了自己或有循环依赖
├─ 修复：确保wrapper只做转发，不添加逻辑
└─ 验证：python3 -c "from olav.shared.tools.XXX import YYY"

【错误5】测试失败
├─ 原因：某个修改遗漏或导入错误
├─ 修复：一个一个文件检查，确认所有from olav.tools改成了from olav.shared.tools
└─ 验证：运行单个E2E测试定位问题
```

---

## 📞 需要帮助？

| 问题 | 文档 |
|------|------|
| 为什么要做这个改动？ | ARCHITECTURE_MIGRATION_SKILLCENTRIC.md |
| 我应该修改哪些文件？ | MIGRATION_EXECUTION_CHECKLIST.md |
| 具体怎样改代码？ | MIGRATION_EXECUTION_CHECKLIST.md (代码部分) |
| wrapper怎样设计的？ | WRAPPER_DESIGN_TECHNICAL_DEEPDIVE.md |
| 有问题怎么办？ | 00_MIGRATION_GUIDE_NAVIGATION.md (FAQ) |

---

## ⏱️ 时间估计

```
【按经验】
Wrapper创建:     ████░░░░░░░░░░░░░░░░ ~10-15 min
导入修改:        ████████░░░░░░░░░░░░ ~30-45 min  
验证&测试:       ██░░░░░░░░░░░░░░░░░░ ~15-20 min
-----------------------------------------------
总计:            ~60-80 min (1-1.5小时)

【快速版 (跳过理解)】
                 ~45-60 min

【完整版 (包括阅读和理解)】
                 ~2.5-3小时
```

---

## 📍 相关文件位置

```
.olav/
├── skills/
│   ├── shared/
│   │   ├── tools/
│   │   │   ├── data_export.py............... (NEW)
│   │   │   ├── network_executor.py......... (NEW)
│   │   │   ├── report_formatter.py......... (NEW)
│   │   │   ├── inspection_views.py......... (NEW)
│   │   │   ├── sync_tools.py.............. (NEW)
│   │   │   ├── api_client.py.............. (NEW)
│   │   │   ├── raw_importer.py............ (NEW)
│   │   │   └── __init__.py................ (已有)
│   ├── olav-guard/
│   ├── olav-orchestrator/
│   └── ...

src/olav/
├── agents/
│   ├── orchestrator.py..................... (修改4处)
│   ├── guard.py............................ (修改1处)
│   ├── inspector.py........................ (修改2处)
│   ├── intent_agent.py..................... (修改1处)
│   └── ...
├── cli/
│   ├── cli_main.py......................... (修改3+处)
│   └── ...
├── tools/
│   ├── network_executor.py................. (NO CHANGE)
│   ├── data_export.py...................... (NO CHANGE)
│   └── ...
└── ...
```

---

## 🎯 迁移前最后确认

在开始前，运行这个：

```bash
# 1. 备份当前代码
git status  # 确保git干净
git commit -m "pre-migration-backup" || echo "Already committed"

# 2. 确认当前状态正常
uv run pytest tests/e2e/test_real_scenarios.py -q
# 期望：passed

# 3. 记录当前导入状态
grep -rn "from olav.tools" src/olav --include="*.py" | wc -l
# 期望：会有N个结果（这些都需要改）

# 好的，现在可以开始迁移了！👇
```

---

## 🏁 迁移完成后最后确认

```bash
# 【验证导入已更改】
grep -rn "from olav.tools" src/olav --include="*.py" | grep -v "src/olav/tools"
# 期望：无输出 ✅

# 【验证wrapper可用】
uv run python3 -c "
from olav.shared.tools.data_export import format_and_export
from olav.shared.tools.network_executor import get_executor
from olav.shared.tools.report_formatter import generate_professional_inspection_report
from olav.shared.tools.inspection_views import create_inspection_views
print('✅ All wrappers importable')
"

# 【运行全套测试】
uv run pytest tests/e2e/test_real_scenarios.py -v
# 期望：✅ All tests passed

# 【提交代码】
git add -A
git commit -m "refactor: migrate all imports to olav.shared.tools wrapper layer"
git push

# 🎉 迁移完成！
```

---

## 📱 按步骤的Checklist

```
□ Day 1 - Setup
  └─ □ 读完所有文档 (30 min)
  └─ □ 确认了解全貌
  
□ Day 2 - Implementation  
  └─ □ 创建7个wrapper文件 (30 min)
      □ data_export.py
      □ network_executor.py
      □ report_formatter.py
      □ inspection_views.py
      □ sync_tools.py
      □ api_client.py
      □ raw_importer.py
  
  └─ □ 修改13个Python文件 (45 min)
      □ orchestrator.py (4处)
      □ guard.py (1处)
      □ inspector.py (2处)
      □ intent_agent.py (1处)
      □ analyzer.py (1处)
      □ cli_main.py (3处)
      □ commands.py (待查)
      □ __init__.py (1处)
      □ 其他文件 (如需要)
  
  └─ □ 验证 (30 min)
      □ 导入检查成功
      □ E2E测试通过
      □ 手动功能测试通过

□ Day 3 - Finalize
  └─ □ Code Review
  └─ □ git push
  └─ □ CI/CD通过
  
✅ 迁移完成！
```

---

**版本**: v1.0.0 | **日期**: 2026-02-12 | **打印并贴在桌边** 📌
