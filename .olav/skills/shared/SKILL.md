---
skill_name: shared_tools
description: 共享的网络工具集
version: 1.0.0

tools:
  - name: nornir_execute
    module: tools.network
    function: nornir_execute
    description: 执行 Nornir 批量命令
    
  - name: list_devices
    module: tools.network
    function: list_devices
    description: 列出所有设备
    
  - name: get_device_platform
    module: tools.network
    function: get_device_platform
    description: 获取设备平台信息
    
  - name: get_nornir
    module: tools.network_executor
    function: get_nornir
    description: 获取 Nornir 实例
    
  - name: reset_nornir
    module: tools.network_executor
    function: reset_nornir
    description: 重置 Nornir 实例
    
  - name: get_executor
    module: tools.network_executor
    function: get_executor
    description: 获取命令执行器
    
  - name: format_and_export
    module: tools.data_export
    function: format_and_export
    description: 格式化并导出数据为 CSV/JSON/Markdown
    
  - name: generate_professional_inspection_report
    module: tools.report_formatter
    function: generate_professional_inspection_report
    description: 生成专业格式巡检报告
    
  - name: create_inspection_views
    module: tools.inspection_views
    function: create_inspection_views
    description: 创建数据库巡检视图
    
  - name: sync_all
    module: tools.sync_tools
    function: sync_all
    description: 同步所有设备数据
---

# Shared Tools Skill

共享的网络运维工具集，提供设备管理、命令执行、数据导出、报告生成等核心功能。

## 工具列表

### 网络执行
- `nornir_execute`: 批量执行网络命令
- `get_executor`: 获取命令执行器实例
- `get_nornir`: 获取 Nornir 实例
- `reset_nornir`: 重置 Nornir 实例

### 设备管理
- `list_devices`: 列出所有管理设备
- `get_device_platform`: 查询设备平台信息

### 数据处理与导出
- `format_and_export`: 格式化数据并导出为 CSV/JSON/Markdown 格式
- `sync_all`: 同步所有设备配置和状态

### 报告生成
- `generate_professional_inspection_report`: 生成专业格式巡检报告
- `create_inspection_views`: 创建数据库巡检视图

## 使用示例

### 在 Agent 中使用工具

```python
from olav.core.tool_registry import get_tool

# 获取工具
nornir_execute = get_tool("nornir_execute")
format_and_export = get_tool("format_and_export")

# 使用工具
if nornir_execute:
    result = nornir_execute(...)

if format_and_export:
    exported = format_and_export(...)
```

### 检查已注册工具

```python
from olav.core.tool_registry import list_tools, has_tool

# 列出所有工具
all_tools = list_tools()

# 检查特定工具
if has_tool("nornir_execute"):
    print("Tool is available")
```

## 架构说明

本 Skill 遵循 **Skill-Centric 架构原则**：

1. **配置驱动**: 工具配置在 SKILL.md YAML frontmatter 中
2. **动态加载**: Tool Registry 在运行时从配置中加载工具
3. **Agent-Tool 分离**: Agent 代码不直接导入工具，通过 registry 调用
4. **扩展性**: 新增工具只需修改此文件，无需改动 Python 代码

## 维护指南

添加新工具时：

1. 在 `tools/` 目录实现工具函数
2. 在本文件 YAML frontmatter 的 `tools` 列表中添加条目
3. 在适当的 Agent 中使用 `get_tool()` 获取工具

示例：

```yaml
tools:
  - name: my_new_tool
    module: tools.my_module
    function: my_function
    description: Tool description
```

然后在 Agent 中：

```python
my_tool = get_tool("my_new_tool")
if my_tool:
    result = my_tool(...)
```

---

**Version**: 1.0.0  
**Last Updated**: 2026-02-13  
**Arch**: Skill-Centric, Configuration-Driven
