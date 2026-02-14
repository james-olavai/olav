# Tools 位置设计决策

**问题**：Tools 应该放在 `.olav/tools/` 还是 `src/olav/tools/`？

**决策**：✅ `.olav/tools/`（用户数据层）

---

## 设计理由

### 1. 跨平台迁移能力

**场景**：用户想把 OLAV 应用到新的网络环境

```bash
# 用户只需复制一个目录
cp -r project_A/.olav project_B/

# 获得完整配置：
✅ Skills（业务知识）
✅ Tools（执行逻辑）
✅ AGENTS.md（持久化记忆）
✅ database files（业务数据）
✅ settings.json（用户偏好）
```

如果 tools 在 `src/`，用户需要：
- 复制 `.olav/`
- 修改 `src/olav/tools/`
- 可能需要修改依赖
- 重新部署整个应用

### 2. 符合 MCP（Model Context Protocol）标准

Claude Code 和 MCP 推荐架构：

```
workspace/
├── .claude/          # 或 .olav/
│   ├── tools/       # ✅ User-defined tools
│   └── config/
└── src/             # Application code
```

参考：
- [MCP Documentation](https://modelcontextprotocol.io/)
- [Claude Code Tools](https://docs.anthropic.com/en/docs/build-with-claude/tool-use)

### 3. 业务逻辑与框架代码分离

```
.olav/                    # 用户数据层（可迁移）
├── tools/               # ← 业务执行逻辑
├── skills/              # ← 业务知识
├── AGENTS.md           # ← 用户记忆
└── db/                 # ← 业务数据

src/olav/                 # 框架代码层（版本控制）
├── agents/              # ← Agent 创建逻辑
├── cli/                 # ← CLI 接口
├── api/                 # ← REST API
└── core/                # ← 核心基础设施
```

**优势**：
- Git 管理：`.olav/` 可以是独立仓库或 gitignore
- 更新隔离：框架升级不影响用户业务逻辑
- 多租户：不同项目共享 src/ 代码，独立 .olav/ 配置

### 4. 动态加载机制（简单实现）

```python
# src/olav/agents/agent.py
import sys
from pathlib import Path

def create_olav_agent():
    """创建 OLAV Agent，动态加载 .olav/tools/"""
    
    # 将 .olav/tools 添加到 Python path
    tools_path = Path.cwd() / ".olav" / "tools"
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))
    
    # 动态导入 tools
    from database import smart_sql_query
    from network import nornir_execute, list_devices
    
    # 创建 Agent
    from deepagents import create_deep_agent
    
    agent = create_deep_agent(
        tools=[smart_sql_query, nornir_execute, list_devices],
        # ... 其他配置
    )
    
    return agent
```

**无需特殊 loader**：标准 Python import 机制即可

### 5. 热插拔能力

用户可以直接编辑 `.olav/tools/database.py`：

```python
# .olav/tools/database.py

@tool
def smart_sql_query(query: str) -> dict:
    """用户可以直接修改这个文件
    
    例如：
    - 添加自定义 SQL 优化
    - 集成自己的数据库
    - 添加审计日志
    """
    # 用户修改不需要重新部署 src/
    pass
```

**重启即生效**，无需：
- 修改源代码
- 重新构建
- Git commit

### 6. 与现有架构一致

OLAV v0.11.5 当前结构：

```
.olav/
├── tools/             # ← 已经在这里
│   ├── nornir_executor.py
│   ├── device_query.py
│   └── ...
```

**保持现有设计**，避免破坏性变更

---

## 实施细节

### 工具发现机制

```python
# src/olav/agents/agent.py

def load_tools_from_olav_directory():
    """从 .olav/tools/ 动态加载所有 tools"""
    tools_path = Path.cwd() / ".olav" / "tools"
    
    # 方案 A：标准 Python import（推荐）
    sys.path.insert(0, str(tools_path))
    
    # 方案 B：使用 importlib（更灵活）
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "database", tools_path / "database.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    return [module.smart_sql_query, ...]
```

### 错误处理

```python
def create_olav_agent():
    tools_path = Path.cwd() / ".olav" / "tools"
    
    if not tools_path.exists():
        raise FileNotFoundError(
            f"Tools directory not found: {tools_path}\n"
            f"Run: uv run olav init"
        )
    
    try:
        from database import smart_sql_query
    except ImportError as e:
        raise ImportError(
            f"Failed to load tools from {tools_path}\n"
            f"Error: {e}\n"
            f"Hint: Check .olav/tools/database.py exists"
        )
    
    # ... 创建 agent
```

### 测试支持

```python
# tests/conftest.py

@pytest.fixture
def mock_tools_directory(tmp_path):
    """为测试创建临时 .olav/tools/"""
    tools_dir = tmp_path / ".olav" / "tools"
    tools_dir.mkdir(parents=True)
    
    # 创建测试 tools
    (tools_dir / "__init__.py").write_text("")
    (tools_dir / "database.py").write_text("""
from langchain_core.tools import tool

@tool
def smart_sql_query(query: str) -> dict:
    return {"test": "data"}
""")
    
    # 修改当前工作目录
    import os
    old_cwd = os.getcwd()
    os.chdir(tmp_path)
    
    yield tools_dir
    
    os.chdir(old_cwd)
```

---

## 与其他架构对比

### 对比 A：Tools 在 src/olav/tools/

```
优点：
- 标准 Python 包结构
- 更容易做类型检查
- 不需要动态 path 修改

缺点：
❌ 用户修改需要 Git commit
❌ 框架更新可能覆盖用户修改
❌ 无法独立迁移业务逻辑
❌ 不符合 MCP 标准
```

### 对比 B：Tools 在独立包（PyPI）

```
优点：
- 标准发布流程
- 版本管理清晰

缺点：
❌ 过度工程化（OLAV 是单用户工具）
❌ 用户修改需要发布包
❌ 部署复杂度增加
```

---

## 最终决策

✅ **Tools 放在 `.olav/tools/`**

**关键原因**：
1. 用户体验：复制 `.olav/` 即可完整迁移
2. 行业标准：符合 MCP 规范
3. 架构清晰：业务层与框架层分离
4. 实施简单：标准 Python import
5. 现有一致：保持 v0.11.5 设计

**Trade-off 接受**：
- 需要动态加载（但实现简单）
- IDE 可能无法自动补全（可通过 stub 文件解决）

---

**版本**: v1.0
**日期**: 2026-02-14
**状态**: ✅ 已采纳
