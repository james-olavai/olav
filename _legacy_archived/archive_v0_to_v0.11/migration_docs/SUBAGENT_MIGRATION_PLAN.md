# 🚀 SubAgent 架构完整迁移方案

**版本**: v0.10.0  
**创建日期**: 2026-02-02  
**目标**: 迁移到 DeepAgents SubAgent 声明式架构

---

## 📋 迁移目标

### 1. 架构目标
- ✅ 统一使用 `create_deep_agent` + SubAgent 声明式配置
- ✅ 移除手动 if-elif 专家路由逻辑
- ✅ 清理所有 AgentMemory 遗留引用
- ✅ Standard/Analysis 模式统一使用 checkpointer

### 2. 代码清理目标
- ✅ 移除 `_get_specialist_agent()` 手动路由
- ✅ 移除 AgentMemory 导入和使用
- ✅ user_aliases 完全迁移到 DuckDBStore
- ✅ 删除自定义 session_history 表逻辑

### 3. 测试目标
- ✅ 真实 CLI E2E 测试（echo + pipe）
- ✅ SubAgent 路由测试
- ✅ 跨会话状态恢复测试
- ✅ 别名学习和查询测试

---

## 🏗️ 新架构设计

### Orchestrator SubAgent 模式

```python
# 新架构：声明式 SubAgent
orchestrator = create_deep_agent(
    model="gpt-4o",
    system_prompt="You are the main orchestrator...",
    subagents=[
        SubAgent(
            name="database",
            tools=[query_network],
            description="Execute SQL queries on network database",
        ),
        SubAgent(
            name="cli",
            skill_name="network-query",
            description="Execute CLI commands on network devices",
        ),
        SubAgent(
            name="analysis",
            tools=[analyze_network],
            description="Deep analysis of network topology and issues",
        ),
        # 未来扩展
        SubAgent(
            name="snmp",
            skill_name="snmp-query",
            description="SNMP polling and monitoring",
        ),
        SubAgent(
            name="netbox",
            skill_name="netbox-sync",
            description="NetBox DCIM synchronization",
        ),
    ],
    checkpointer=checkpointer,
    store=store,
    backend=backend,
)
```

### QueryAgentV2 统一模式

```python
# 统一 Standard 和 Analysis 模式
class QueryAgentV2:
    def __init__(
        self,
        skill_name: str = "network-query",
        enable_summarization: bool = False,  # 替代 mode 参数
    ):
        middleware = [self.skills_middleware]
        
        if enable_summarization:
            middleware.append(
                SummarizationMiddleware(
                    model="gemini-flash",
                    backend=backend,
                    trigger=("tokens", 50000),
                    keep=("messages", 10),
                )
            )
        
        self.agent = create_deep_agent(
            model=model_name,
            tools=self.tools,
            system_prompt=self.system_prompt,
            middleware=middleware,
            checkpointer=self.checkpointer,
            store=self.store,
            backend=backend,
        )
```

---

## 📂 文件修改清单

### Phase A: 移除 AgentMemory 遗留 (阻塞)

| 文件 | 操作 | 优先级 |
|------|------|--------|
| `src/olav/cli/cli_main.py` | 移除 AgentMemory 导入和使用 | 🔴 P0 |
| `src/olav/cli/commands.py` | 移除 AgentMemory 导入 | 🔴 P0 |
| `src/olav/agents/query_agent_v2.py` | Standard 模式添加 checkpointer | 🔴 P0 |

### Phase B: user_aliases 迁移 (数据一致性)

| 文件 | 操作 | 优先级 |
|------|------|--------|
| `src/olav/lib/data_gateway.py` | 迁移 learn_user_alias 到 DuckDBStore | 🟡 P1 |
| `src/olav/lib/data_gateway.py` | 迁移 get_user_alias 到 DuckDBStore | 🟡 P1 |
| `src/olav/lib/data_gateway.py` | 删除 user_aliases 表创建 | 🟡 P1 |

### Phase C: SubAgent 架构迁移 (重构)

| 文件 | 操作 | 优先级 |
|------|------|--------|
| `src/olav/agents/orchestrator.py` | 重写为 SubAgent 声明式 | 🟢 P2 |
| `src/olav/agents/query_agent_v2.py` | 统一 mode 参数为 enable_summarization | 🟢 P2 |
| `src/olav/cli/cli_main.py` | 更新 agent 创建调用 | 🟢 P2 |

### Phase D: 测试补充 (验证)

| 文件 | 操作 | 优先级 |
|------|------|--------|
| `tests/test_cli_real_e2e.py` | 创建真实 CLI E2E 测试 | 🟢 P2 |
| `tests/test_subagent_routing.py` | 创建 SubAgent 路由测试 | 🟢 P2 |
| `tests/test_aliases_store.py` | 创建别名 Store 测试 | 🟢 P2 |

---

## 🔧 详细实施步骤

### Phase A: 修复阻塞问题 (立即)

#### A1. 移除 cli_main.py AgentMemory

```python
# 删除导入
- from olav.cli.memory import AgentMemory

# 删除实例化
- memory = AgentMemory(max_messages=100)

# 删除类型注解
- memory: "AgentMemory | None" = None

# 删除参数传递
- def _interactive_loop(..., memory: AgentMemory | None = None):
+ def _interactive_loop(...):
```

#### A2. 移除 commands.py AgentMemory

```python
# 删除导入
- from olav.cli.memory import AgentMemory

# 删除实例化
- memory = AgentMemory()
```

#### A3. 修复 Standard 模式

```python
# query_agent_v2.py
else:  # Standard mode
-   # 使用简单 Chain
-   prompt = ChatPromptTemplate.from_messages([...])
-   model_with_tools = model.bind_tools(fast_tools)
-   self.agent = prompt | model_with_tools

+   # 使用 create_deep_agent（保持快速执行）
+   self.agent = create_deep_agent(
+       model=model_name,
+       tools=fast_tools,
+       system_prompt=self.system_prompt + "\nIMPORTANT: Generate SQL immediately.",
+       middleware=[self.skills_middleware],
+       checkpointer=self.checkpointer,
+       store=self.store,
+       backend=backend,
+   )
```

#### A4-A5. 验证

```bash
# 验证启动
uv run olav --help

# 验证交互
echo "show all devices" | uv run olav

# 验证会话持久化
uv run olav
> show all devices
> exit
uv run olav
> # 历史应该保留
```

---

### Phase B: user_aliases 迁移

#### B1-B2. 迁移 data_gateway.py

```python
# 移除自定义表创建
- CREATE TABLE IF NOT EXISTS user_aliases (...)

# 修改 learn_user_alias
def learn_user_alias(self, alias: str, canonical: str, type_: str = "device") -> None:
-   self.conn.execute(
-       "INSERT INTO user_aliases (alias, canonical, type) VALUES (?, ?, ?)",
-       (alias.upper(), canonical.upper(), type_),
-   )
+   # 使用 DuckDBStore
+   from langgraph.store.duckdb import DuckDBStore
+   store = DuckDBStore(self.conn)
+   namespace = ("network-query", "aliases")
+   
+   # 存储别名映射
+   store.put(namespace, alias.upper(), {"canonical": canonical.upper(), "type": type_})

# 修改 get_user_alias
def get_user_alias(self, alias: str) -> str | None:
-   result = self.conn.execute(
-       "SELECT canonical FROM user_aliases WHERE alias = ?", (alias.upper(),)
-   ).fetchone()
-   return result[0] if result else None
+   # 使用 DuckDBStore
+   from langgraph.store.duckdb import DuckDBStore
+   store = DuckDBStore(self.conn)
+   namespace = ("network-query", "aliases")
+   
+   item = store.get(namespace, alias.upper())
+   return item.value.get("canonical") if item else None
```

#### B3. 删除自定义表代码

```python
# 移除 user_aliases 表创建逻辑
- CREATE TABLE IF NOT EXISTS user_aliases (...)
```

---

### Phase C: SubAgent 架构迁移

#### C1. 重写 orchestrator.py

```python
# 删除 _get_specialist_agent() 方法
- def _get_specialist_agent(expert_name: str) -> Any:
-     if expert_name == "database":
-         return QueryAgentV2(tools=[query_network], model="gpt-4o")
-     elif expert_name == "cli":
-         return QueryAgentV2(skill_name="network-query", mode="standard")
-     ...

# 使用 SubAgent 声明式
from deepagents.middleware.subagents import SubAgentMiddleware, SubAgent

async def create_orchestrator(
    checkpointer: DuckDBSaver,
    store: DuckDBStore,
    backend: FilesystemBackend,
) -> Any:
    """Create orchestrator with SubAgent architecture."""
    
    subagents = [
        SubAgent(
            name="database",
            tools=[query_network],
            description="Execute SQL queries on network database snapshots",
        ),
        SubAgent(
            name="cli",
            skill_name="network-query",
            description="Execute CLI commands on live network devices",
        ),
        SubAgent(
            name="analysis",
            tools=[analyze_network],
            description="Deep analysis of network topology, routing, and issues",
        ),
    ]
    
    orchestrator = create_deep_agent(
        model="gpt-4o",
        system_prompt=load_orchestrator_prompt(),
        subagents=subagents,
        checkpointer=checkpointer,
        store=store,
        backend=backend,
    )
    
    return orchestrator
```

#### C2. 统一 QueryAgentV2 模式

```python
class QueryAgentV2:
    def __init__(
        self,
        skill_name: str = "network-query",
        enable_summarization: bool = False,  # 替代 mode 参数
    ):
        # 统一使用 create_deep_agent
        middleware = [self.skills_middleware]
        
        if enable_summarization:
            middleware.append(
                SummarizationMiddleware(
                    model="gemini-flash",
                    backend=backend,
                    trigger=("tokens", 50000),
                    keep=("messages", 10),
                )
            )
        
        # 统一创建逻辑
        self.agent = create_deep_agent(
            model=model_name,
            tools=self.tools,
            system_prompt=self.system_prompt,
            middleware=middleware,
            checkpointer=self.checkpointer,
            store=self.store,
            backend=backend,
        )
```

#### C3. 更新 cli_main.py 调用

```python
# 更新 agent 创建调用
- agent = QueryAgentV2(mode="standard", skill_name=skill_name)
+ agent = QueryAgentV2(skill_name=skill_name, enable_summarization=False)

- agent = QueryAgentV2(mode="analysis")
+ agent = QueryAgentV2(enable_summarization=True)
```

---

### Phase D: 测试补充

#### D1. 真实 CLI E2E 测试

```python
# tests/test_cli_real_e2e.py
import subprocess
import pytest

def test_cli_help():
    """Test CLI help command."""
    result = subprocess.run(
        ["uv", "run", "olav", "--help"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "OLAV" in result.stdout

def test_cli_query_pipe():
    """Test CLI query via pipe."""
    result = subprocess.run(
        ["uv", "run", "olav"],
        input="show all devices\n",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0
    assert "device" in result.stdout.lower()

def test_cli_query_echo():
    """Test CLI query via echo."""
    result = subprocess.run(
        'echo "show device count" | uv run olav',
        shell=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0

def test_cli_session_persistence():
    """Test session state persistence across invocations."""
    # First query
    result1 = subprocess.run(
        ["uv", "run", "olav", "query", "show device R1"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result1.returncode == 0
    
    # Second query should have context
    result2 = subprocess.run(
        ["uv", "run", "olav", "query", "show its interfaces"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result2.returncode == 0
```

#### D2. SubAgent 路由测试

```python
# tests/test_subagent_routing.py
import pytest
from olav.agents.orchestrator import create_orchestrator

@pytest.mark.asyncio
async def test_subagent_routing_database():
    """Test routing to database subagent."""
    orchestrator = await create_orchestrator(checkpointer, store, backend)
    
    result = await orchestrator.ainvoke(
        {"messages": [("user", "show all devices in database")]}
    )
    
    assert "device" in str(result).lower()

@pytest.mark.asyncio
async def test_subagent_routing_cli():
    """Test routing to CLI subagent."""
    orchestrator = await create_orchestrator(checkpointer, store, backend)
    
    result = await orchestrator.ainvoke(
        {"messages": [("user", "execute show version on R1")]}
    )
    
    assert "cli" in str(result).lower() or "version" in str(result).lower()

@pytest.mark.asyncio
async def test_subagent_routing_analysis():
    """Test routing to analysis subagent."""
    orchestrator = await create_orchestrator(checkpointer, store, backend)
    
    result = await orchestrator.ainvoke(
        {"messages": [("user", "analyze network topology")]}
    )
    
    assert "analysis" in str(result).lower() or "topology" in str(result).lower()
```

#### D3. 别名 Store 测试

```python
# tests/test_aliases_store.py
import pytest
from olav.lib.data_gateway import get_gateway

def test_alias_learn_and_query():
    """Test alias learning and querying with DuckDBStore."""
    gw = get_gateway()
    
    # Learn alias
    gw.learn_user_alias("r1-core", "R1-CORE-SW01", "device")
    
    # Query alias
    canonical = gw.get_user_alias("r1-core")
    assert canonical == "R1-CORE-SW01"

def test_alias_case_insensitive():
    """Test alias case insensitivity."""
    gw = get_gateway()
    
    gw.learn_user_alias("R2-Access", "R2-ACCESS-SW01", "device")
    
    assert gw.get_user_alias("r2-access") == "R2-ACCESS-SW01"
    assert gw.get_user_alias("R2-ACCESS") == "R2-ACCESS-SW01"

def test_alias_not_found():
    """Test alias not found."""
    gw = get_gateway()
    
    result = gw.get_user_alias("nonexistent-device")
    assert result is None
```

---

## 🧪 验收标准

### 功能验收

| 测试场景 | 命令 | 预期结果 |
|---------|------|---------|
| CLI 帮助 | `uv run olav --help` | 显示帮助信息 |
| Echo 查询 | `echo "show devices" \| uv run olav` | 返回设备列表 |
| 交互模式 | `uv run olav` → 输入查询 | 正常响应 |
| 会话持久化 | 两次查询引用上下文 | 上下文保留 |
| 别名学习 | 触发 R3 学习流程 | 别名保存到 Store |
| 别名查询 | 使用学习的别名 | 正确解析 |
| SubAgent 路由 | 不同类型查询 | 路由到正确 SubAgent |

### 代码质量验收

```bash
# 代码检查
uv run ruff check src/ --fix
uv run ruff format src/
uv run pyright src/

# 单元测试
uv run pytest tests/ -v

# E2E 测试
uv run pytest tests/test_cli_real_e2e.py -v
uv run pytest tests/test_subagent_routing.py -v
uv run pytest tests/test_aliases_store.py -v

# 完整验收测试
uv run pytest tests/00_e2e_acceptance_test.py -v
```

---

## 📊 迁移收益分析

### 代码简化

| 指标 | 迁移前 | 迁移后 | 改善 |
|------|--------|--------|------|
| orchestrator.py 行数 | ~463 行 | ~200 行 | -57% |
| agent 创建模式 | 3 种 | 1 种 | 统一 |
| 手动路由逻辑 | 50+ 行 | 0 行 | 消除 |
| 自定义表 | 2 个 | 0 个 | 消除 |

### 可维护性

| 维度 | 迁移前 | 迁移后 |
|------|--------|--------|
| 添加新 Agent | 修改 if-elif + 复制逻辑 | 添加 1 行 SubAgent |
| 修改路由规则 | 修改 Python 代码 | 修改配置 |
| 测试隔离 | Mock 整个 Orchestrator | 单独测试 SubAgent |
| 调试难度 | 高（手动路由） | 低（声明式） |

### 扩展性

```python
# 未来扩展只需添加：
SubAgent(name="snmp", skill_name="snmp-query"),      # SNMP 监控
SubAgent(name="netbox", skill_name="netbox-sync"),   # NetBox 同步
SubAgent(name="syslog", skill_name="syslog-query"),  # Syslog 分析
```

---

## 🎯 总结

### 迁移完成标志

- ✅ 所有 AgentMemory 引用移除
- ✅ Standard/Analysis 模式统一使用 create_deep_agent
- ✅ user_aliases 完全迁移到 DuckDBStore
- ✅ Orchestrator 使用 SubAgent 声明式架构
- ✅ 真实 CLI E2E 测试通过
- ✅ 所有单元测试通过
- ✅ 代码质量检查通过

### 版本标记

**v0.10.0**: SubAgent 架构完整迁移版本

---

**文档版本**: 1.0  
**最后更新**: 2026-02-02
