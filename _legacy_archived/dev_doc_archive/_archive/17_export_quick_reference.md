# OLAV 文件导出功能 - 快速参考

## ✅ 设计已完整实现

| 需求 | 实现状态 | 位置 | 说明 |
|------|--------|------|------|
| 多种文件格式 (md/csv/txt/json/yaml) | ✅ 完成 | `src/olav/tools/data_export.py` | 5种格式全支持 |
| DeepAgents原生功能集成 | ✅ 完成 | `src/olav/agents/orchestrator.py` | `create_deep_agent(subagents=...)` |
| 用户查询→自动导出 | ✅ 完成 | Orchestrator SKILL.md | 关键词识别+自动调用 |
| SubAgent数据→exports目录 | ✅ 完成 | `config/paths.py` (REPORTS_DIR) | 统一输出位置 |

---

## 📌 核心组件速查表

### 1. 导出工具
```python
from olav.tools.data_export import format_and_export

# 调用方式
format_and_export(
    data=content,           # 任意数据(str/dict/list)
    filename="vlans",       # 文件名(可选,自动时间戳)
    format="csv"            # 格式(可选,自动检测)
)

# 返回值
{
    "path": "exports/reports/vlans.csv",
    "size": 512,
    "format": "csv"
}
```

### 2. Orchestrator中的工具配置
```python
# 仅Orchestrator有format_and_export权限
orchestrator_tools = [format_and_export]

# SubAgent通过Orchestrator间接调用
agent = create_deep_agent(
    tools=orchestrator_tools,
    subagents=subagent_list,  # ← DeepAgents原生支持
)
```

### 3. 自动格式检测规则
| 数据特征 | 检测格式 | 示例 |
|---------|--------|------|
| 以 `#` 开头或含 `##` | md | `# 诊断报告\n##问题` |
| 以 `{` 或 `[` 开头 | json | `{"devices": [...]}` |
| dict / list Python对象 | json | `{"k": "v"}` |
| 普通字符串 | txt | CLI输出、配置等 |
| 特定CSV格式 | csv | 表格数据 |

---

## 🎯 使用场景速查

### CSV导出
```
用户: "查询所有VLAN，导出为CSV"
↓
Orchestrator → Query SubAgent → 获取数据
↓
format_and_export(data, format="csv", filename="vlans")
↓
✅ exports/reports/vlans.csv
```

### TXT导出
```
用户: "在R2上运行show run，保存为TXT"
↓
Orchestrator → CLI SubAgent → 执行命令
↓
format_and_export(output, filename="R2_config")
↓
✅ exports/reports/R2_config.txt
```

### Markdown自动检测
```
用户: "诊断OSPF问题"
↓
Orchestrator → Expert SubAgent → 生成Markdown报告
↓
format_and_export(markdown_content, filename="ospf_diagnosis")
↓
自动检测格式 → md
✅ exports/reports/ospf_diagnosis.md
```

---

## 🔧 关键文件位置速查

| 功能 | 文件 | 行数 | 说明 |
|------|------|------|------|
| **核心导出** | `src/olav/tools/data_export.py` | 298 | format_and_export工具 |
| **Orchestrator** | `src/olav/agents/orchestrator.py` | 445 | 中央协调+工具调用 |
| **Skill定义** | `.olav/skills/orchestrator/SKILL.md` | 337 | 导出指南+例子 |
| **配置路径** | `config/paths.py` | - | REPORTS_DIR定义 |
| **演示代码** | `examples/data_export_demo.py` | 77 | 完整使用示例 |
| **E2E测试** | `tests/e2e/test_real_scenarios.py` | - | 文件导出验证测试 |

---

## ✅ 测试状态

### 单元测试
```
✅ 格式检测: 9/9 通过
✅ 导出功能: 10/10 通过
✅ 集成测试: 2/2 通过
━━━━━━━━━━━━━━━━━━━━
✅ 总计: 23/23 通过
```

### E2E测试
```
✅ test_csv_export_path_validation_real - PASSED
   验证CSV文件生成在exports/reports/
   
✅ 所有21个E2E场景 - PASSED
```

---

## 🌊 数据流总结

```
┌────────┐ 用户查询
└────┬───┘
     │ 包含"导出"/"保存"关键词
     ▼
┌──────────────┐
│ Orchestrator  │ 路由选择SubAgent
└────┬─────────┘
     │
     ▼
┌────────────────────────────┐
│ Query/CLI/Analysis/Expert  │ 获取数据
│ SubAgent执行               │ (content only)
└────┬───────────────────────┘
     │ 返回原始内容
     │
     ▼
┌──────────────────────────┐
│ format_and_export()      │ Orchestrator调用
│ • 检测格式               │
│ • 生成文件名             │
│ • 写入exports/reports/   │
└────┬─────────────────────┘
     │
     ▼
  ✅ 用户获得文件路径
```

---

## 📋 快速问答

**Q: 导出是自动的吗?**
A: 用户说"保存"/"导出"时自动调用。不说的话不导出。

**Q: 在哪个目录导出?**
A: 统一在 `exports/reports/` (由REPORTS_DIR配置)

**Q: 支持哪些格式?**
A: md, csv, txt, json, yaml (自动检测+可手动指定)

**Q: 谁可以导出文件?**
A: 仅Orchestrator (权限管理，SubAgent只返回数据)

**Q: 文件名怎么生成?**
A: 用户指定 OR 自动时间戳 `export_YYYYmmdd_HHMMSS`

**Q: 用了什么DeepAgents功能?**
A: `create_deep_agent(subagents=...)` 原生SubAgent支持

**Q: 有没有硬编码?**
A: 零硬编码。格式检测完全基于内容特征。

---

## 🚀 一句话总结

**Orchestrator通过DeepAgents的SubAgent机制，自动从数据内容推断格式，将SubAgent返回的数据导出到exports/reports/目录，零硬编码，完全由LLM理解用户意图。**

---

## 📞 需要修改?

常见改进方向:
- 自动导出启发式 (当前: 需明确说"导出")
- 导出格式推荐 (当前: 自动检测)
- 邮件/Slack通知 (当前: 仅文件)
- 批量导出支持 (当前: 单个)

联系修改: `src/olav/tools/data_export.py` 或 Orchestrator SKILL.md
