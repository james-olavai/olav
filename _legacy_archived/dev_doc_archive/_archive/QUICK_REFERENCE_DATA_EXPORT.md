# 🚀 数据导出功能 - 快速参考

## 一句话总结
**LLM自动理解"保存"意图，智能导出到 `exports/` 目录，零硬编码。**

---

## 🎯 核心概念

```
用户意图 → LLM理解 → 调用工具 → 自动导出
```

- **统一目录**: `exports/`
- **智能检测**: 自动推断格式
- **LLM驱动**: 无硬编码关键词

---

## 📝 使用方法

### 导出数据（自动调用）

```bash
# Markdown报告
olav "诊断R1的OSPF问题，保存报告"
→ exports/R1_ospf_diagnosis.md

# CSV表格
olav "查询所有VLAN，导出CSV"
→ exports/vlans.csv

# JSON数据
olav "查询设备信息，保存为JSON"
→ exports/devices_inventory.json

# 文本输出
olav "在R1执行show tech，保存到文件"
→ exports/R1_tech_support.txt
```

### 不导出（仅显示）

```bash
# 无"保存/导出"意图 → 直接显示
olav "列出所有设备"
→ 屏幕显示结果
```

---

## 🛠️ 工具接口

```python
from olav.tools.data_export import format_and_export

# 自动检测（推荐）
format_and_export(data)  
# → exports/export_20260205_143022.{md|json|txt}

# 指定文件名
format_and_export(data, filename="my_report")
# → exports/my_report.{自动检测格式}

# 明确指定格式
format_and_export(data, filename="vlans", format="csv")
# → exports/vlans.csv
```

---

## 📊 支持格式

| 格式 | 扩展名 | 用途 | 检测规则 |
|------|--------|------|---------|
| Markdown | `.md` | 诊断报告、文档 | 以 `#` 开头 |
| JSON | `.json` | 结构化数据 | dict/list 或 `{`/`[` |
| CSV | `.csv` | 表格数据 | 明确指定 |
| Text | `.txt` | CLI输出、日志 | 默认 |
| YAML | `.yaml` | 配置文件 | 明确指定 |

---

## ✅ 测试验证

```bash
# 基础功能测试
uv run python src/olav/tools/data_export.py

# E2E测试
uv run python tests/e2e/test_data_export_e2e.py

# pytest测试
uv run pytest tests/e2e/test_data_export_e2e.py -v

# 查看演示
uv run python examples/data_export_demo.py
```

---

## 📁 文件结构

```
exports/                          # 统一输出目录
├── ospf_diagnosis_*.md           # Markdown报告
├── vlans_export_*.csv            # CSV表格
├── devices_inventory_*.json      # JSON数据
└── R1_tech_support_*.txt         # 文本输出

src/olav/tools/
└── data_export.py                # 核心工具 (240行)

tests/e2e/
└── test_data_export_e2e.py       # E2E测试 (330行)

docs/
├── 14_data_export_design.md      # 设计文档
└── 15_data_export_implementation_summary.md  # 实施总结
```

---

## 🔑 关键特性

```python
✅ 自动格式检测     # 从内容推断，无需指定
✅ LLM智能理解     # "保存"/"导出" → 自动调用
✅ 统一输出目录     # 所有文件 → exports/
✅ 自动文件命名     # 带时间戳
✅ 零硬编码        # 无关键词映射
✅ 权限控制        # 只有Orchestrator能写文件
✅ 多格式支持      # md/json/csv/txt/yaml
```

---

## 💡 设计原则

| 原则 | 实践 |
|------|------|
| **简单 > 复杂** | 单一工具，单一目录 |
| **智能 > 硬编码** | LLM理解，自动检测 |
| **配置 > 代码** | 从内容推断，而非规则 |
| **用户 > 系统** | 手动整理知识库 |

---

## 🚦 工作流程

```
用户查询："诊断OSPF问题并保存报告"
    ↓
Orchestrator理解意图
    ↓
1. 调用Expert Agent → 生成诊断内容
    ↓
2. 检测到"保存"意图
    ↓
3. 调用format_and_export(content, filename="ospf_diagnosis")
    ↓
4. 自动检测格式 → "md"（因为以#开头）
    ↓
5. 写入文件 → exports/ospf_diagnosis.md
    ↓
6. 返回: "✅ 报告已保存到 exports/ospf_diagnosis.md"
```

---

## 🎓 最佳实践

### ✅ 应该

```bash
# 明确导出意图
olav "查询VLAN并保存"
olav "诊断问题，生成报告"

# 指定格式（可选）
olav "导出CSV格式"
olav "保存为JSON"

# 手动整理知识库
cp exports/ospf_diagnosis.md .olav/knowledge/cases/
```

### ❌ 避免

```bash
# 不需要指定路径（自动到exports/）
# ❌ olav "保存到/tmp/report.md"

# 不需要硬编码格式（自动检测）
# ❌ 在代码中写 if "CSV" in query

# 不需要在SubAgent中写文件
# ❌ 在Expert工具中直接write_file()
```

---

## 📞 快速支持

### 问题排查

| 问题 | 解决方案 |
|------|---------|
| 未生成文件 | 检查查询是否包含"保存/导出"关键词 |
| 格式错误 | 明确指定 `format="csv"` 参数 |
| 文件名重复 | 使用时间戳自动命名 |
| 找不到文件 | 检查 `exports/` 目录 |

### 常见查询模式

```bash
# 模式1：动词 + 保存/导出
"查询XXX并保存"
"分析XXX，导出结果"

# 模式2：保存/导出 + 格式
"保存为CSV"
"导出JSON格式"

# 模式3：生成 + 报告
"生成诊断报告"
"创建分析文档"
```

---

## 🎯 记住这些

1. **统一目录**: 所有导出 → `exports/`
2. **LLM智能**: 自动理解"保存"意图
3. **自动检测**: 格式从内容推断
4. **零硬编码**: 无关键词映射
5. **手动整理**: 用户决定加入知识库

---

**快速开始**: `olav "查询所有设备，导出CSV"` 🚀
