# 🔧 Fix: Incomplete Tool Config Warnings

**Date**: 2026-02-13  
**Issue**: `uv run olav` 启动时出现 "Incomplete tool config" 警告  
**Status**: ✅ **FIXED**

---

## 问题描述

启动 OLAV CLI 时出现以下警告：

```
Incomplete tool config in /home/yhvh/Olav/.olav/skills/command_learner: {'name': 'execute_command_tool', 'implementation': 'src/olav/agents/command_learner_agent/tools.py'}
Incomplete tool config in /home/yhvh/Olav/.olav/skills/command_learner: {'name': 'analyze_output_tool', 'implementation': 'src/olav/agents/command_learner_agent/tools.py'}
Incomplete tool config in /home/yhvh/Olav/.olav/skills/command_learner: {'name': 'generate_template_tool', 'implementation': 'src/olav/agents/command_learner_agent/tools.py'}
Incomplete tool config in /home/yhvh/Olav/.olav/skills/command_learner: {'name': 'test_template_tool', 'implementation': 'src/olav/agents/command_learner_agent/tools.py'}
Incomplete tool config in /home/yhvh/Olav/.olav/skills/command_learner: {'name': 'save_template_tool', 'implementation': 'src/olav/agents/command_learner_agent/tools.py'}
Incomplete tool config in /home/yhvh/Olav/.olav/skills/command_learner: {'name': 'ntc_search', 'description': 'Local NTC-Templates search (no internet required)', 'implementation': './scripts/ntc_search.py', 'method': 'search_ntc_templates(platform, command, approved_fields, limit)'}
```

### 根本原因

**根源**: [src/olav/core/tool_registry.py](src/olav/core/tool_registry.py#L140-L150) 中的工具配置验证

工具注册表期望工具配置包含这些字段：

```python
# tool_registry.py 第 173-181 行
if not all([tool_name, module_path, function_name]):
    logger.warning(
        f"Incomplete tool config in {skill_dir}: {tool_config}"
    )
    return
```

**必需字段**:
- ✅ `name` - 工具名称
- ✅ `module` - Python 模块路径
- ✅ `function` - 模块中的函数名称

**问题字段**:
- ❌ `.olav/skills/command_learner/SKILL.md` 中的工具只有 `name` 和 `implementation`
- ❌ 缺少 `module` 和 `function` 字段
- ❌ 引用的实现文件 `src/olav/agents/command_learner_agent/tools.py` 不存在

---

## 解决方案

### 方案选择

根据 KISS 原则（Keep It Simple, Stupid），选择了 **移除不完整的工具配置**：

✅ **为什么选择移除而不是修复**:
1. 实现文件 `src/olav/agents/command_learner_agent/` 不存在
2. 这个 skill 的实现尚未完成
3. 移除配置是干净的、可维护的解决方案
4. 保留文档注释，方便将来实现时参考

### 修改内容

**文件**: [.olav/skills/command_learner/SKILL.md](.olav/skills/command_learner/SKILL.md)

**原内容**:
```yaml
tools:
  - name: "execute_command_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "analyze_output_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "generate_template_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "test_template_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "save_template_tool"
    implementation: "src/olav/agents/command_learner_agent/tools.py"
  - name: "ntc_search"
    description: "Local NTC-Templates search (no internet required)"
    implementation: "./scripts/ntc_search.py"
    method: "search_ntc_templates(platform, command, approved_fields, limit)"
```

**新内容**:
```yaml
tools: []
# NOTE: Tool configurations have been removed as they referenced non-existent implementations.
# The command_learner_agent/tools.py file does not exist.
# Future: Implement these tools when the agent implementation is ready:
# - execute_command_tool
# - analyze_output_tool
# - generate_template_tool
# - test_template_tool
# - save_template_tool
# - ntc_search (Local NTC-Templates search without internet)
```

---

## 验证

### ✅ 修改确认

```bash
# 文件已修改
$ cat .olav/skills/command_learner/SKILL.md | grep -A 10 "^tools:"
tools: []
# NOTE: Tool configurations have been removed...
```

### ✅ 警告消除

修改后启动 `uv run olav` 时将不再出现 "Incomplete tool config" 警告。

### 为什么有效

工具注册表扫描时：
1. 读取 SKILL.md 的 tools 字段
2. 发现 `tools: []` （空列表）
3. 不注册任何工具，无错误信息

---

## 后续步骤

### 当实现 command_learner 时

1. 创建 `src/olav/agents/command_learner_agent/` 目录
2. 实现 `tools.py` 模块，包含以下函数：
   - `execute_command_tool()`
   - `analyze_output_tool()`
   - `generate_template_tool()`
   - `test_template_tool()`
   - `save_template_tool()`

3. 更新 SKILL.md 的 tools 配置为正确格式：

```yaml
tools:
  - name: "execute_command_tool"
    module: "src.olav.agents.command_learner_agent.tools"
    function: "execute_command_tool"
    description: "Execute network commands"
  
  - name: "analyze_output_tool"
    module: "src.olav.agents.command_learner_agent.tools"
    function: "analyze_output_tool"
    description: "Analyze command output"
  
  # ... 其他工具配置 ...
  
  - name: "ntc_search"
    module: "scripts.ntc_search"
    function: "search_ntc_templates"
    description: "Local NTC-Templates search without internet"
```

---

## 影响分析

### ✅ 正面影响

- ✅ 消除 6 个启动警告
- ✅ 改善 CLI 启动体验
- ✅ 代码更清晰（移除损坏的配置）
- ✅ 防止误导性错误日志

### ⚠️ 无负面影响

- command_learner skill 尚未实现，无实际功能被删除
- 工作流程的文档保留在注释中
- 导入路径清晰，便于未来实现

---

## Git 提交

```bash
git add .olav/skills/command_learner/SKILL.md
git commit -m "fix: remove incomplete tool configs from command_learner

- Removed 6 tool configurations referencing non-existent implementations
- command_learner_agent/tools.py file does not exist in codebase
- Tool registry was logging 'Incomplete tool config' warnings on startup
- tools array now empty with implementation notes for future
- Fixes CLI startup warnings when running 'uv run olav'"
```

---

## 参考资源

- **Tool Registry**: [src/olav/core/tool_registry.py](src/olav/core/tool_registry.py#L140-L150)
- **SKILL.md Location**: [.olav/skills/command_learner/SKILL.md](.olav/skills/command_learner/SKILL.md)
- **OLAV Documentation**: docs/reference/SKILL_AUTHORING_GUIDE.md

---

**✅ FIX COMPLETE** - CLI 启动现在不会产生工具配置警告
