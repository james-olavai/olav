# 🔍 工具注册架构分析 - 当前实现 vs DeepAgents 原生

**Date**: 2026-02-13  
**Question**: 工具注册是否使用 DeepAgents 原生的动态注册？  
**Answer**: ❌ **否** - 当前使用的是自定义的 `ToolRegistry`，而不是 DeepAgents 原生机制

---

## 📊 架构对比

### 当前实现 (Custom ToolRegistry)

```
SKILL.md (工具配置)
    ↓
ToolRegistry._load_all_tools()
    ├─ 扫描 .olav/skills/*/SKILL.md
    ├─ 解析 tools 配置
    ├─ 动态导入模块 (.py 文件)
    └─ 缓存工具函数
    ↓
get_tool(tool_name) [全局函数]
    ↓
create_orchestrator()
    ├─ tools=orchestrator_tools  [手动传入]
    ↓
create_deep_agent(tools=...)  [DeepAgents]
```

### DeepAgents 原生机制 (未使用)

```
create_deep_agent(tools=[...])
    ├─ 接受工具列表
    ├─ 原生支持 LangChain Tool 包装
    └─ 内部管理工具注册
```

---

## 🏗️ 当前实现细节

### 代码位置

**ToolRegistry 类**: `src/olav/core/tool_registry.py` (250 行)

### 工具流程

```python
# 1. 初始化 (单例)
from olav.core.tool_registry import get_tool

# 2. 动态加载
get_tool("nornir_execute")  # ← 从缓存返回或加载

# 3. 传递给 DeepAgents
agent = create_deep_agent(
    model=llm_model,
    tools=orchestrator_tools,      # ← 手动收集的工具列表
    subagents=subagents,
    ...
)
```

### 工具验证机制

```python
# src/olav/core/tool_registry.py 行 140-150
if not all([tool_name, module_path, function_name]):
    logger.warning(f"Incomplete tool config in {skill_dir}: {tool_config}")
    return
```

**必需字段** (SKILL.md):
```yaml
tools:
  - name: "my_tool"
    module: "fully.qualified.path"     # ← 必需
    function: "my_function"             # ← 必需
    description: "Tool description"
```

---

## ✅ 为什么不使用 DeepAgents 原生注册

### 1️⃣ DeepAgents 的工具声明方式

DeepAgents 接受的工具必须符合 LangChain 的 Tool 接口：

```python
from langchain.tools import tool

@tool
def my_function(param: str) -> str:
    """Tool description"""
    return result

# 或者
from langchain.tools import Tool

tool = Tool(
    name="my_tool",
    func=my_function,
    description="Tool description"
)

# 传给 DeepAgents
agent = create_deep_agent(
    tools=[tool],
    ...
)
```

### 2️⃣ 当前架构的优势

| 特性 | 当前 ToolRegistry | DeepAgents 原生 |
|------|-------------------|-----------------|
| **配置驱动** | ✅ SKILL.md 定义 | ❌ 代码定义 |
| **零侵入** | ✅ 不修改工具代码 | ❌ 需要 @tool 装饰 |
| **KISS** | ✅ 简洁清晰 | ⚠️ 需要额外包装 |
| **Skill-Centric** | ✅ 配置是中心 | ❌ 代码是中心 |
| **动态加载** | ✅ 运行时加载 | ✅ 支持 |
| **缓存** | ✅ 单例管理 | ⚠️ 需要手动 |

### 3️⃣ 关键设计权衡

**选择自定义 ToolRegistry 的原因**:

1. ✅ **配置就是代码** - SKILL.md 是唯一真实来源
2. ✅ **避免侵入式修饰符** - 不需要在每个工具上加 @tool
3. ✅ **灵活性** - 支持多种模块和函数来源
4. ✅ **单例管理** - 全局统一的工具缓存
5. ✅ **Skill-Centric 架构** - 符合 OLAV 设计原则

---

## 🔄 工具注册流程详解

### Phase 1: 初始化

```python
# src/olav/__init__.py - 延迟导入
def __getattr__(name: str):
    if name == "list_devices":
        return list_devices
    else:
        from olav.core.tool_registry import get_tool
        tool = get_tool("nornir_execute")
        if tool:
            return tool
```

### Phase 2: 扫描 SKILL.md

```python
# src/olav/core/tool_registry.py - _load_all_tools()

def _load_all_tools(self) -> None:
    """扫描所有 skill 目录，加载工具配置"""
    for skill_dir in Path(SKILLS_DIR).iterdir():
        skill_md = skill_dir / "SKILL.md"
        self._load_skill_tools(skill_dir, skill_md)
```

### Phase 3: 解析工具配置

```yaml
# .olav/skills/network-cli/SKILL.md
tools:
  - name: "nornir_execute"
    module: "src.olav.tools.nornir_executor"
    function: "execute_command"
    description: "Execute commands on network devices"
```

### Phase 4: 动态导入

```python
# src/olav/core/tool_registry.py - _register_tool()

module = importlib.import_module(module_path)
tool_func = getattr(module, function_name)
self._tools[tool_name] = tool_func  # 缓存
```

### Phase 5: 使用工具

```python
# 在任何地方
from olav.core.tool_registry import get_tool

nornir_tool = get_tool("nornir_execute")
result = nornir_tool(command="show version", device="core-01")
```

---

## 🎯 当前设计遵循的原则

### 1. KISS 原则 (Keep It Simple, Stupid)

```
简单方案 ✅:
├─ SKILL.md 定义工具
├─ ToolRegistry 加载
└─ get_tool() 获取

复杂方案 ❌:
├─ @tool 装饰器不一致
├─ Tool() 包装类繁琐
├─ LangChain 类型转换
└─ 额外的中间层
```

### 2. 配置驱动设计

```python
# 配置是中心节点
SKILL.md (单一事实来源)
    ↑      ↓
  读取   加载
    ↑      ↓
ToolRegistry ← 唯一的工具管理器
    ↑
获取工具
```

### 3. Skill-Centric 架构

```
每个 Skill
├─ SKILL.md (配置)
│   └─ tools: [...] ← 工具配置
├─ 实现文件 (./tools.py)
│   └─ def my_function(): ...
└─ 提示词 (./prompts.md)
```

### 4. 零代码侵入

```python
# 工具实现不需要修改
def execute_command(device: str, command: str) -> dict:
    """Execute command on network device."""
    # 无需 @tool 装饰
    # 无需 Tool() 包装
    # 无需 LangChain 导入
    return {"result": ...}

# 配置在 SKILL.md 中完成
```

---

## 📈 架构演进路线

### v0.11.1 (当前)

```
✅ ToolRegistry 单例
✅ SKILL.md 驱动完全
✅ 动态工具加载
✅ 工具缓存
```

### v0.12.0 (可选增强)

如果需要更好的 DeepAgents 集成，可以：

```python
# 选项 A: Tool 适配层 (LangChain 兼容)
from langchain.tools import Tool

def wrap_tool_for_langgraph(tool_func):
    """包装 OLAV 工具为 LangChain 工具"""
    return Tool(
        name=tool_func.__name__,
        func=tool_func,
        description=tool_func.__doc__ or "No description"
    )

# 选项 B: 原生 DeepAgents 工具
# (需要修改所有工具实现 - 不推荐)
```

---

## 🏆 是否应该改为 DeepAgents 原生?

### 💼 对比决策表

| 因素 | 改为原生 | 保持自定义 |
|------|---------|-----------|
| 代码侵入 | 🔴 高 | 🟢 低 |
| 配置复杂性 | 🔴 高 | 🟢 低 |
| KISS 原则 | 🔴 违反 | 🟢 遵循 |
| DeepAgents 耦合 | 🔴 紧耦合 | 🟢 松耦合 |
| Skill-Centric | 🔴 破坏 | 🟢 保留 |
| 迁移成本 | 🔴 高 | ✅ 无需迁移 |

### 💡 建议

**保持当前的自定义 ToolRegistry** ✅

理由：
1. ✅ 符合 SKIP 原则 - 更简洁
2. ✅ 保持 Skill-Centric 架构
3. ✅ 工具实现无需修改
4. ✅ 配置与代码分离
5. ✅ DeepAgents 解耦

---

## 📋 关键代码位置

### 工具系统

| 模块 | 文件 | 行数 | 职责 |
|------|------|------|------|
| **ToolRegistry** | `src/olav/core/tool_registry.py` | 250 | 工具注册中心 |
| **Skill Loader** | `src/olav/core/skill_loader.py` | ~200 | SKILL.md 解析 |
| **使用示例** | `src/olav/cli/cli_main.py` | 多处 | get_tool() 调用 |
| **Orchestrator** | `src/olav/agents/router.py` | 170-190 | 工具集成 |

### SKILL.md 工具配置

```
.olav/skills/
├─ network-cli/SKILL.md
│   └─ tools:
│       - name, module, function
├─ network-query/SKILL.md
│   └─ tools: [...]
└─ other-skills/SKILL.md
    └─ tools: [...]
```

---

## ✨ 总结

### 当前架构

```
✅ 使用自定义的 ToolRegistry (不是 DeepAgents 原生)
✅ 配置驱动 (SKILL.md 中心)
✅ 零代码侵入 (工具不需要装饰器)
✅ 符合 KISS 原则
✅ 松耦合于 DeepAgents
```

### 设计优势

```
1. 配置是唯一真实来源 (SKILL.md)
2. 工具实现保持简洁 (无装饰器)
3. Skill-Centric 架构保留
4. 易于测试和维护
5. 支持热重载
```

### 推荐结论

```
🟢 保持当前架构
   不应该迁移到 DeepAgents 原生注册
   因为当前解决方案更简洁、更符合 OLAV 设计原则
```

---

**更新**: 2026-02-13  
**结论**: 当前的自定义 ToolRegistry 是更好的选择 ✅

