# Phase 5B.2 执行计划：优化 Agent 工具加载

**日期**: 2026-02-17  
**目标**: 简化和优化 agent._load_tools() 方法  
**范围**: 改进代码结构，降低复杂性  
**目标代码行数削减**: 从 32 行 → 12 行 (减少 62%)

---

## 🎯 当前问题 (agent.py L93-130)

### 代码复杂性高
```python
# 当前: 使用 importlib.util.spec_from_file_location 动态加载
# - 需要检查 spec 是否存在
# - 需要创建 module_from_spec
# - 需要执行 exec_module
# - 需要逐个检查 hasattr

spec_db = importlib.util.spec_from_file_location("database", tools_path / "database.py")
if spec_db and spec_db.loader:
    database = importlib.util.module_from_spec(spec_db)
    spec_db.loader.exec_module(database)
    if hasattr(database, "execute_sql"):
        tools.append(database.execute_sql)
```

### 问题列表
1. ❌ 代码冗余 (重复模式 3 次)
2. ❌ 路径依赖复杂 (.olav/tools/ 位置依赖)
3. ❌ 错误处理不足 (只记录警告，未详细说明)
4. ❌ 可读性差 (32 行代码执行简单逻辑)

---

## ✅ 改进方案

### 方案 A: 直接导入 (推荐)

**思路**: 直接 import，而不是动态加载

```python
def _load_tools(self) -> list:
    """Load tools with enhanced error handling."""
    tools = []
    tools_path = self.olav_base_path / "tools"

    if not tools_path.exists():
        logger.warning(f"Tools directory not found: {tools_path}")
        return tools

    sys.path.insert(0, str(tools_path))
    
    # Define tool imports with name and module
    tool_specs = [
        ("execute_sql", "database"),
        ("execute_cli", "network"),
        ("list_devices_inventory", "network"),
        ("manage_inspection_schedule", "inspection"),
    ]
    
    for tool_name, module_name in tool_specs:
        try:
            module = __import__(module_name)
            if hasattr(module, tool_name):
                tools.append(getattr(module, tool_name))
                logger.debug(f"Loaded tool: {tool_name} from {module_name}")
            else:
                logger.warning(f"Tool {tool_name} not found in {module_name}")
        except ImportError as e:
            logger.warning(f"Failed to import {module_name}: {e}")
        except Exception as e:
            logger.warning(f"Error loading {tool_name} from {module_name}: {e}")
    
    logger.info(f"Loaded {len(tools)} tools from {tools_path}")
    return tools
```

**优点**:
- ✅ 代码行数: 从 32 → 20 行 (减少 37%)
- ✅ 更清晰的工具定义
- ✅ 更好的错误消息
- ✅ 易于添加新工具 (只需添加一行)

---

### 方案 B: 简化现有代码 (保守方案)

**思路**: 提取辅助函数，消除重复

```python
def _load_tool(self, tools_path: Path, module_name: str, *tool_names: str) -> list:
    """Helper to load tools from a module."""
    loaded_tools = []
    try:
        spec = importlib.util.spec_from_file_location(
            module_name, 
            tools_path / f"{module_name}.py"
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            for tool_name in tool_names:
                if hasattr(module, tool_name):
                    loaded_tools.append(getattr(module, tool_name))
                    logger.debug(f"Loaded {tool_name} from {module_name}")
    except Exception as e:
        logger.warning(f"Failed to load from {module_name}: {e}")
    
    return loaded_tools

def _load_tools(self) -> list:
    """Load tools from .olav/tools/."""
    tools = []
    tools_path = self.olav_base_path / "tools"

    if not tools_path.exists():
        logger.warning(f"Tools directory not found: {tools_path}")
        return tools

    sys.path.insert(0, str(tools_path))
    
    # Load each tool module
    tools.extend(self._load_tool(tools_path, "database", "execute_sql"))
    tools.extend(self._load_tool(tools_path, "network", "execute_cli", "list_devices_inventory"))
    tools.extend(self._load_tool(tools_path, "inspection", "manage_inspection_schedule"))
    
    logger.info(f"Loaded {len(tools)} tools from {tools_path}")
    return tools
```

**优点**:
- ✅ 代码行数: 从 32 → 25 行 (加上7行辅助函数 = 32行总，但更清晰)
- ✅ 消除了 if 嵌套
- ✅ 保留原有逻辑，易于测试
- ✅ 更容易维护

---

## 📊 对比分析

| 指标 | 当前 | 方案 A | 方案 B |
|-----|------|--------|--------|
| 代码行数 (_load_tools) | 32 | 20 | 15 |
| +辅助函数 | 0 | 0 | +7 |
| 代码复杂度 | 高 | 中 | 中 |
| 出错概率 | 高 | 低 | 中 |
| 可读性 | 低 | 高 | 中 |
| 易于扩展 | 低 | 高 | 中 |

---

## 🔧 实施计划 (采用方案 A)

### 步骤 1: 备份当前代码

```bash
cd /home/yhvh/Olav
git diff src/olav/agents/agent.py > /tmp/agent_original.patch
```

### 步骤 2: 更新 agent.py

替换 _load_tools() 方法 (L93-130 → L93-115)

### 步骤 3: 验证

```bash
# 验证语法
python3 -m py_compile src/olav/agents/agent.py

# 运行单元测试
uv run pytest tests/e2e/test_inspection_report_complete.py::TestT1ToolLoading -v --no-cov

# 运行 Agent 初始化测试
python3 -c "from src.olav.agents.agent import OLAVAgent; a = OLAVAgent(); print(f'Tools loaded: {len(a.tools)}')"
```

###步骤 4: 验证 E2E 测试

```bash
uv run pytest tests/e2e/test_inspection_report_complete.py --no-cov -q
```

---

## 📋 检查清单

- [ ] Git 工作目录干净
- [ ] 原始代码已备份
- [ ] 新代码已编写
- [ ] Python 语法检查通过
- [ ] 单元测试通过 (Tool Loading T-1)
- [ ] E2E 测试通过 (17/17)
- [ ] 代码行数确实减少了
- [ ] 构建成功 (如果有)

---

## 🎯 预期结果

**代码删减**:
- ✅ agent.py: 32 → 20 行 (减少 12 行, 37% 提升)

**性能改进**:
- ✅ 工具加载时间可能略微减少 (避免了多次文件操作)

**可维护性改进**:
- ✅ 代码清晰度提高
- ✅ 更易于添加新工具 (单行操作)
- ✅ 错误消息更清晰

**测试**:
- ✅ 所有测试通过 (17/17)
- ✅ 代码覆盖率不变

---

## 📝 后续工作

Phase 5B.3 之后，如果要进一步删除冗余代码：
1. 分析 shared/tools 中是否有重复的实现
2. 考虑是否需要统一 configuration loading
3. 检查是否能进一步合并工具

**当前目标**: 优化 agent.py，为未来的整合奠定基础

---

**状态**: 就绪  
**预计工作时间**: 15 分钟  
**风险**: 低 (工具加载逻辑未变，只是代码结构改进)
