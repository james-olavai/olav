# 数据导出与格式化设计方案

## 一、设计原则

### 核心思想：LLM智能 + 配置驱动 + 零硬编码

```
用户意图 → LLM理解 → 调用工具 → 统一输出
```

**关键特性**：
- ❌ 无硬编码关键词检测
- ❌ 无格式映射逻辑
- ❌ 无路径选择逻辑
- ✅ LLM自动理解并调用工具
- ✅ 自动格式检测
- ✅ 统一输出目录

## 二、架构设计

### 1. 单一工具：format_and_export

```python
def format_and_export(
    data: Any,
    filename: str | None = None,
    format: str | None = None
) -> dict:
    """
    极简文件导出工具 - 统一输出到 exports/
    
    特性：
    - 自动格式检测（从内容特征）
    - 自动文件名生成（带时间戳）
    - 支持多种格式（md/json/txt/csv/yaml）
    """
```

### 2. 权限控制：只给Orchestrator

```
Orchestrator（唯一写入点）
├── format_and_export ✅
│
SubAgents（无写入权限）
├── Query SubAgent    → 返回数据
├── Expert SubAgent   → 返回报告内容
└── CLI SubAgent      → 返回命令输出
```

### 3. 工作流程

```
用户："查询VLAN并保存为CSV"
    ↓
LLM理解：需要查询 + 导出
    ↓
1. 调用 query SubAgent → 返回数据
2. 调用 format_and_export(data, format="csv")
    ↓
输出：exports/vlans_20260205_143022.csv
```

## 三、目录结构

### 统一输出目录

```
exports/                      # 所有导出都在这里
├── vlans_20260205_143022.csv
├── ospf_diagnosis_20260205_143155.md
├── R1_tech_support_20260205_143301.txt
├── devices_inventory_20260205_143445.json
└── network_topology_20260205_143520.yaml
```

**优势**：
- ✅ 简单明了：单一目录
- ✅ 用户自主：手动整理到知识库
- ✅ 易于清理：定期清理exports/
- ✅ 无需分类：不需要复杂子目录

## 四、格式支持

### 自动格式检测规则

| 数据特征 | 检测格式 | 用途 |
|---------|---------|------|
| 以 `#` 开头或包含 `##` | `md` | 诊断报告、文档 |
| 以 `{` 或 `[` 开头 | `json` | 结构化数据、API |
| dict/list 类型 | `json` | Python对象 |
| 其他字符串 | `txt` | CLI输出、日志 |
| 用户明确指定 | 用户指定 | 覆盖自动检测 |

### 支持的格式

- **Markdown (md)**: 诊断报告、分析文档
- **JSON (json)**: 结构化数据、API响应
- **Text (txt)**: CLI输出、show tech、日志
- **CSV (csv)**: 表格数据、数据库查询结果
- **YAML (yaml)**: 配置文件、拓扑数据

## 五、实现细节

### 工具实现（~80行）

```python
# src/olav/tools/data_export.py

from pathlib import Path
from typing import Any
from datetime import datetime
import json

def format_and_export(
    data: Any,
    filename: str | None = None,
    format: str | None = None
) -> dict:
    """极简文件导出工具"""
    
    # 1. 统一输出目录
    output_dir = Path("exports")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 2. 自动检测格式
    if not format:
        format = _detect_format(data)
    
    # 3. 自动生成文件名
    if not filename:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"export_{timestamp}"
    
    # 4. 写入文件
    filepath = output_dir / f"{filename}.{format}"
    _write_file(filepath, data, format)
    
    # 5. 返回结果
    return {
        "path": str(filepath),
        "size": filepath.stat().st_size
    }
```

### Orchestrator集成

```python
# system_prompt添加：

"""
File Export Tool:
- format_and_export(data, filename, format) - Save results to exports/

Usage guidelines:
1. Call ONLY when user asks to save/export (保存/导出/存储)
2. Auto-detect format from content or use user's preference
3. All files go to exports/ directory

Examples:
- "诊断并保存报告" → format_and_export(result, format="md")
- "导出CSV" → format_and_export(data, format="csv")
- "保存配置" → format_and_export(config, format="txt")
"""
```

## 六、使用场景

### 场景1：诊断报告导出

```
用户："诊断R1的OSPF问题，保存报告"

流程：
1. Expert SubAgent → 生成诊断内容
2. LLM检测到"保存" → 调用format_and_export
3. 输出：exports/R1_ospf_diagnosis.md

LLM响应：
"诊断完成！报告已保存到 exports/R1_ospf_diagnosis.md"
```

### 场景2：数据库查询导出CSV

```
用户："查询所有VLAN信息，导出表格"

流程：
1. Query SubAgent → 查询数据库
2. LLM检测到"导出表格" → format="csv"
3. 输出：exports/vlans_export.csv

LLM响应：
"已导出6条VLAN记录到 exports/vlans_export.csv"
```

### 场景3：CLI输出保存

```
用户："在R1上执行show tech-support，保存到文件"

流程：
1. CLI SubAgent → 执行命令
2. LLM检测到"保存" → format="txt"
3. 输出：exports/R1_tech_support.txt

LLM响应：
"技术支持信息已保存到 exports/R1_tech_support.txt (45KB)"
```

### 场景4：不导出（仅显示）

```
用户："诊断R1的OSPF问题"

流程：
1. Expert SubAgent → 生成诊断内容
2. LLM未检测到导出意图 → 不调用format_and_export
3. 直接返回诊断内容

LLM响应：
"# 诊断报告\n\n## 问题：R1 OSPF邻居down..."
```

## 七、测试用例

### E2E测试矩阵

| Agent | 查询 | 预期格式 | 文件名 |
|-------|------|---------|--------|
| Query | "查询所有Cisco设备，导出CSV" | csv | devices_export |
| Query | "列出VLAN信息，保存为JSON" | json | vlans_data |
| Expert | "诊断OSPF问题并保存报告" | md | ospf_diagnosis |
| Expert | "分析网络健康度，导出报告" | md | health_report |
| CLI | "show tech保存到文件" | txt | tech_support |
| CLI | "导出R1的配置" | txt | R1_config |

## 八、关键优势

### 1. 零硬编码

```python
# ❌ 旧方案
if "保存" in query or "导出" in query:
    if "表格" in query:
        format = "csv"
    elif "报告" in query:
        format = "md"

# ✅ 新方案
# LLM自动理解并调用工具
# 无需任何if判断
```

### 2. 极简工具

- 单一工具：`format_and_export`
- 代码量：~80行
- 依赖：标准库（json, pathlib, datetime）

### 3. 高度灵活

```python
# LLM可以创造性使用

# 场景1：批量导出
for device in devices:
    format_and_export(device, filename=device.hostname)

# 场景2：条件导出
if len(data) > 100:
    format_and_export(data, format="csv")
else:
    # 直接返回，不导出
```

### 4. 用户友好

- 所有文件在 `exports/` - 一目了然
- 自动生成文件名 - 无需纠结命名
- 支持多种格式 - 满足不同需求
- 手动整理到知识库 - 用户自主控制

## 九、未来扩展

### 可能的增强（按需添加）

1. **压缩支持**: 导出大文件时自动压缩
2. **批量导出**: 一次性导出多个文件
3. **模板系统**: 自定义报告模板
4. **云同步**: 自动上传到云存储
5. **版本控制**: 自动Git提交

但遵循原则：**只在真正需要时才添加**

## 十、总结

### 设计哲学

```
简单 > 复杂
智能 > 硬编码
配置 > 代码
用户 > 系统
```

### 实施清单

- [ ] 创建 `src/olav/tools/data_export.py` (~80行)
- [ ] 更新 Orchestrator system_prompt (添加工具说明)
- [ ] 创建 E2E 测试 (每个agent 2-3个场景)
- [ ] 测试 LLM 理解能力（保存/导出/不导出）
- [ ] 文档更新（README用户指南）

### 成功标准

✅ LLM能理解"保存"/"导出"意图  
✅ 自动检测格式准确率 >90%  
✅ 所有文件正确写入 exports/  
✅ 无硬编码，无格式映射  
✅ 代码量 <100行  

---

**版本**: v1.0  
**日期**: 2026-02-05  
**状态**: 设计完成，待实施
