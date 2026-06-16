# OLAV 插件体系设计方案

更新日期: 2026-03-15
状态: 方案设计，未实施
范围: 插件目录结构、加载机制、AgentMiddleware 接口、Callback 接口、闭源企业插件隔离、现有功能迁移路径

## 1. 目标

建立一个在 `src/olav/plugins/` 下统一管理所有自定义插件的机制，使以下三类需求能在同一框架内实现：

1. **开源内置插件**：随 OLAV 一起分发，已知、可见、可贡献（如 LanceDB 记忆、审计 Callback）
2. **闭源企业插件**：独立打包，安装后自动激活，不在开源仓库中（如脱敏导出、Guard Model）
3. **用户自定义插件**：用户可在本地 `src/olav/plugins/` 下添加，也可以打成独立包注册

## 2. 技术基础

### 2.1 两条接入通道

deepagents 和 LangChain 共同提供了两条接入通道，覆盖不同场景：

#### 通道 A：`AgentMiddleware`（来自 `langchain.agents.middleware`）

位于模型调用链内部，可以修改请求、检查响应、包裹模型调用。

`create_deep_agent` 的 `middleware: Sequence[AgentMiddleware]` 参数，用户自定义 middleware 被追加到内置栈之后。

**内置栈顺序（只读）：**

```
TodoList → Memory → Skills → Filesystem → SubAgent
→ Summarization → AnthropicPromptCaching → PatchToolCalls
→ [plugins/middleware/*.py ...]
→ HumanInTheLoop（如果 interrupt_on 启用）
```

**`AgentMiddleware` 的 hook 点：**

| 方法 | 触发时机 | 能否修改/中断 |
|---|---|---|
| `before_agent` | 每次 agent 开始前 | 可修改 state |
| `before_model` | 每次调用模型前 | 可修改 ModelRequest |
| `wrap_model_call` | 包裹整个模型调用 | 可拦截、并发旁路、修改流 |
| `after_model` | 模型返回后 | 可检查 ModelResponse，可抛出 |
| `after_agent` | agent 完成后 | 可后处理 |

每个 hook 均有对应的 `async` 版本（前缀 `a`）。

#### 通道 B：`AsyncCallbackHandler`（来自 `langchain_core.callbacks`）

旁路观测，零侵入，不能修改执行链，但能捕获所有生命周期事件。注入方式：在 `astream_events(config={"callbacks": [handler]})` 时传入。

**可捕获的所有事件：**

```
on_chat_model_start / on_llm_new_token / on_llm_end / on_llm_error
on_tool_start / on_tool_end / on_tool_error
on_chain_start / on_chain_end / on_chain_error
on_custom_event
on_agent_action / on_agent_finish
on_retriever_start / on_retriever_end
```

### 2.2 现有 middleware 注册的问题

当前 `OLAVAgent.__init__` 里 `create_deep_agent` 调用没有传入 `middleware` 参数。`AutoRecallMiddleware` / `AutoCaptureMiddleware` 是自定义类，不是 `AgentMiddleware` 子类，通过 `invoke()` 方法手动调用，与 deepagents 的 middleware 体系完全脱节。

这是后续迁移的起点。

## 3. 目录结构

```
src/olav/plugins/
├── __init__.py                # 插件加载器（扫描 + entry points）
├── base.py                    # 插件基类定义（OLAVPlugin）
├── registry.py                # 插件注册表（单例）
│
├── middleware/                # AgentMiddleware 插件（修改执行链）
│   ├── __init__.py
│   ├── memory_recall.py       # LanceDB 自动召回（从 core/memory/middleware.py 迁移）
│   ├── memory_capture.py      # LanceDB 自动捕获（从 core/memory/middleware.py 迁移）
│   └── [enterprise/guard.py] # 企业版 Guard Model（闭源，不在此目录）
│
└── callbacks/                 # AsyncCallbackHandler 插件（旁路观测）
    ├── __init__.py
    └── audit.py               # 审计 Callback（写 audit.duckdb）
```

**说明：**

- `plugins/middleware/` 和 `plugins/callbacks/` 只存放开源内置插件
- 闭源企业插件通过 Python entry points 机制自动发现，不在此目录中
- 用户自定义插件既可以放在此目录，也可以打成独立包通过 entry points 注册

## 4. 插件接口定义

### 4.1 OLAVPlugin 基类

所有插件继承同一个基类，统一元数据格式：

```python
# src/olav/plugins/base.py
from abc import ABC
from dataclasses import dataclass, field


@dataclass
class OLAVPlugin(ABC):
    """所有 OLAV 插件的基类。"""

    name: str                   # 插件名，唯一标识，用于日志和配置覆盖
    version: str = "1.0.0"
    description: str = ""
    enabled: bool = True        # 可通过 api.json 的 plugins.disabled 列表关闭
    tags: list[str] = field(default_factory=list)  # e.g. ["enterprise", "audit"]
```

### 4.2 MiddlewarePlugin

继承 `OLAVPlugin` + `AgentMiddleware`：

```python
# src/olav/plugins/base.py（续）
from langchain.agents.middleware.types import AgentMiddleware


class OLAVMiddlewarePlugin(OLAVPlugin, AgentMiddleware):
    """
    既是 OLAV 插件（有 name/version/enabled），
    又是 AgentMiddleware（可传入 create_deep_agent(middleware=[...])）。

    实现任意 hook 即可，未实现的 hook 使用基类默认（no-op）。
    """
    pass
```

示例——LanceDB 记忆召回插件迁移后的形态：

```python
# src/olav/plugins/middleware/memory_recall.py
from olav.plugins.base import OLAVMiddlewarePlugin


class MemoryRecallPlugin(OLAVMiddlewarePlugin):
    name = "memory_recall"
    description = "在每次模型调用前注入 LanceDB 历史记忆"
    tags = ["memory", "builtin"]

    def __init__(self, store):
        self._store = store

    def before_model(self, state, runtime):
        # 查询 LanceDB，注入 <relevant-memories> 到 ModelRequest
        ...

    async def abefore_model(self, state, runtime):
        ...
```

### 4.3 CallbackPlugin

继承 `OLAVPlugin` + `AsyncCallbackHandler`：

```python
# src/olav/plugins/base.py（续）
from langchain_core.callbacks import AsyncCallbackHandler


class OLAVCallbackPlugin(OLAVPlugin, AsyncCallbackHandler):
    """
    既是 OLAV 插件，又是 LangChain AsyncCallbackHandler。
    直接注入到 astream_events 的 callbacks 列表。
    """
    pass
```

示例——审计 Callback 插件：

```python
# src/olav/plugins/callbacks/audit.py
from olav.plugins.base import OLAVCallbackPlugin


class AuditCallbackPlugin(OLAVCallbackPlugin):
    name = "audit"
    description = "将所有 LangChain 事件写入 audit.duckdb"
    tags = ["audit", "builtin"]

    async def on_tool_start(self, serialized, input_str, **kwargs): ...
    async def on_tool_end(self, output, **kwargs): ...
    async def on_llm_new_token(self, token, **kwargs): ...
    async def on_llm_end(self, response, **kwargs): ...
```

## 5. 插件加载器

### 5.1 加载来源优先级

```
1. src/olav/plugins/middleware/*.py     （内置 middleware 插件）
2. src/olav/plugins/callbacks/*.py      （内置 callback 插件）
3. Python entry points: olav.middleware （外部包注册的 middleware 插件）
4. Python entry points: olav.callbacks  （外部包注册的 callback 插件）
```

加载顺序：内置插件先于外部插件，外部插件按包安装顺序。

### 5.2 加载器实现思路

```python
# src/olav/plugins/__init__.py
from importlib.metadata import entry_points
from importlib import import_module
from pathlib import Path
from olav.plugins.registry import PluginRegistry

def load_builtin_plugins(registry: PluginRegistry) -> None:
    """扫描 plugins/middleware/ 和 plugins/callbacks/ 目录，自动注册。"""
    base = Path(__file__).parent
    for subdir in ("middleware", "callbacks"):
        for path in (base / subdir).glob("*.py"):
            if path.stem.startswith("_"):
                continue
            module = import_module(f"olav.plugins.{subdir}.{path.stem}")
            for obj in vars(module).values():
                if isinstance(obj, type) and issubclass(obj, OLAVPlugin) and obj is not OLAVPlugin:
                    registry.register(obj())

def load_external_plugins(registry: PluginRegistry) -> None:
    """通过 entry points 加载外部（企业/用户）插件。"""
    for group in ("olav.middleware", "olav.callbacks"):
        for ep in entry_points(group=group):
            plugin_cls = ep.load()
            registry.register(plugin_cls())
```

### 5.3 禁用机制

`api.json` 支持通过插件名禁用特定插件：

```json
{
  "plugins": {
    "disabled": ["memory_capture", "audit"]
  }
}
```

加载器在 `PluginRegistry.register()` 时检查此列表，被禁用的插件不加入运行时栈。

## 6. 与 OLAVAgent 的集成点

加载器在 `OLAVAgent.__init__` 中调用一次，结果注入到两个位置：

### 6.1 middleware 插件 → `create_deep_agent`

```python
# src/olav/agents/agent.py（改造后示意）
from olav.plugins import load_builtin_plugins, load_external_plugins
from olav.plugins.registry import PluginRegistry

registry = PluginRegistry()
load_builtin_plugins(registry)
load_external_plugins(registry)

self.graph = create_deep_agent(
    model=self.llm,
    tools=orchestrator_tools,
    system_prompt=...,
    middleware=registry.get_middleware_plugins(),  # ← 注入
    checkpointer=self.checkpointer,
    store=self.store,
    subagents=subagents,
)
```

### 6.2 callback 插件 → `astream_events`

在 `invoke()` / `astream_events()` 调用点注入：

```python
# CLI 和 API 的 astream_events 调用（改造后示意）
callbacks = registry.get_callback_plugins()

async for event in self.graph.astream_events(
    input_data,
    config={
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,          # ← 注入
    },
    version="v2",
):
    ...
```

## 7. 闭源企业插件打包方案

企业插件打成独立包 `olav-enterprise`，通过 Python entry points 声明插件类，安装后即自动激活。

### 7.1 `olav-enterprise/pyproject.toml`

```toml
[project]
name = "olav-enterprise"
version = "1.0.0"
dependencies = ["olav"]

[project.entry-points."olav.middleware"]
guard_model     = "olav_enterprise.guard:GuardModelPlugin"
log_redaction   = "olav_enterprise.redaction:NetworkRedactionPlugin"

[project.entry-points."olav.callbacks"]
audit_export    = "olav_enterprise.audit_export:EnterpriseAuditExportPlugin"
semantic_dedup  = "olav_enterprise.dedup:SemanticDedupPlugin"
```

### 7.2 企业插件实现示例

Guard Model 插件（中断危险串流）：

```python
# olav_enterprise/guard.py
from olav.plugins.base import OLAVMiddlewarePlugin


class GuardModelPlugin(OLAVMiddlewarePlugin):
    name = "guard_model"
    description = "旁路 Guard Model，检测危险行为，触发时中断执行"
    tags = ["enterprise", "security"]

    async def awrap_model_call(self, request, handler):
        # 1. 并发启动 guard 模型，检查 request 内容的危险性
        # 2. 调用原始模型，流式检查输出
        # 3. 如果 guard 触发 → raise 中断
        ...
```

### 7.3 用户安装体验

```bash
pip install olav-enterprise
# 重启 OLAV，企业插件自动激活，无需修改 OLAV 源码
```

### 7.4 未安装时的行为

框架在 `load_external_plugins()` 中使用 `entry_points()` 扫描，如果没有注册任何 `olav.middleware` 或 `olav.callbacks` 的 entry point，函数静默返回空列表。不产生任何报错，功能缺失但框架不受影响。

## 8. 现有功能的迁移路径

### 8.1 LanceDB 记忆功能

当前实现：`src/olav/core/memory/middleware.py` 中的 `AutoRecallMiddleware` / `AutoCaptureMiddleware`，不是 `AgentMiddleware` 子类，通过 `OLAVAgent.invoke()` 手动调用。

迁移目标：改为 `OLAVMiddlewarePlugin` 子类，注册为内置插件，通过 `create_deep_agent(middleware=[...])` 注入。

迁移步骤：

1. 在 `src/olav/plugins/middleware/memory_recall.py` 新建 `MemoryRecallPlugin`，继承 `OLAVMiddlewarePlugin`
2. 将 `AutoRecallMiddleware.enrich()` 逻辑迁入 `before_model()` / `abefore_model()`
3. 在 `src/olav/plugins/middleware/memory_capture.py` 新建 `MemoryCapturePlugin`
4. 将 `AutoCaptureMiddleware.process()` 逻辑迁入 `after_agent()` / `aafter_agent()`
5. `OLAVAgent` 不再手动持有 `_auto_recall` / `_auto_capture`，由插件加载器统一管理
6. `src/olav/core/memory/middleware.py` 原文件保留，逐步废弃

**注意**：`MemoryRecallPlugin` 和 `MemoryCapturePlugin` 初始化时需要 `store` 引用，插件加载器需要支持带依赖注入的插件构造。可通过 `PluginRegistry.register(MemoryRecallPlugin(store=self.store))` 在 `OLAVAgent.__init__` 中手动注册，外部包插件无法感知 `store`，仍使用 entry points 自动加载。

### 8.2 GuardrailInjector

当前实现：`src/olav/core/memory/guardrails.py`，同样手动持有在 `OLAVAgent`。

迁移目标：迁入 `src/olav/plugins/middleware/guardrails.py`，基于 `before_model()` 实现。

### 8.3 审计 Callback

当前实现：无（`audit_logger.py` 仅记录命令行文本）。

新建目标：`src/olav/plugins/callbacks/audit.py`，实现 `AuditCallbackPlugin`，写入 `audit.duckdb`。与 `log_rector.md` 中的 `AuditEventRecorder` 方案对应。

## 9. 插件注册表（PluginRegistry）

```python
# src/olav/plugins/registry.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain_core.callbacks import AsyncCallbackHandler
    from olav.plugins.base import OLAVPlugin, OLAVMiddlewarePlugin, OLAVCallbackPlugin


class PluginRegistry:
    """运行时插件注册表（单例，每个 OLAVAgent 实例持有一份）。"""

    def __init__(self, disabled: list[str] | None = None):
        self._middleware: list[OLAVMiddlewarePlugin] = []
        self._callbacks: list[OLAVCallbackPlugin] = []
        self._disabled = set(disabled or [])

    def register(self, plugin: OLAVPlugin) -> None:
        if plugin.name in self._disabled:
            return
        if isinstance(plugin, OLAVMiddlewarePlugin):
            self._middleware.append(plugin)
        elif isinstance(plugin, OLAVCallbackPlugin):
            self._callbacks.append(plugin)

    def get_middleware_plugins(self) -> list[AgentMiddleware]:
        return list(self._middleware)

    def get_callback_plugins(self) -> list[AsyncCallbackHandler]:
        return list(self._callbacks)
```

## 10. api.json 配置扩展

在 `api.json` 中增加插件配置节：

```json
{
  "plugins": {
    "disabled": [],
    "memory_recall": {
      "top_k": 5,
      "min_score": 0.3
    },
    "guard_model": {
      "model": "claude-haiku-4-5",
      "threshold": 0.85
    }
  }
}
```

`PluginRegistry` 在注册时将对应配置传递给插件构造器，保持零硬编码。

## 11. 分阶段实施

### Phase 1：建立框架骨架

1. 新建 `src/olav/plugins/` 目录及 `__init__.py`、`base.py`、`registry.py`
2. 插件加载器仅实现内置插件扫描（暂不接 entry points）
3. `OLAVAgent` 接入 `registry.get_middleware_plugins()` 和 `get_callback_plugins()`，暂时两个列表均为空，验证不影响现有功能

### Phase 2：迁移现有功能

1. 将 `AutoRecallMiddleware` / `AutoCaptureMiddleware` 迁移为 `MemoryRecallPlugin` / `MemoryCapturePlugin`
2. 将 `GuardrailInjector` 迁移为 `GuardrailsPlugin`
3. 删除 `OLAVAgent` 中手动持有的 `_auto_recall` / `_auto_capture` / `_guardrail_injector`

### Phase 3：新增审计 Callback

1. 新建 `src/olav/plugins/callbacks/audit.py`（对应 log_rector.md Phase 1-2）
2. 实现 `on_tool_start` / `on_tool_end` / `on_llm_new_token` / `on_llm_end` 写 `audit.duckdb`

### Phase 4：接入外部 entry points

1. `load_external_plugins()` 实现
2. 测试 `olav-enterprise` 包通过 entry points 注册插件的完整流程

## 12. 当前已知约束

1. `AgentMiddleware` 的 `middleware` 参数是追加在内置栈之后、`HumanInTheLoop` 之前。无法插入内置栈内部（如在 `FilesystemMiddleware` 和 `SubAgentMiddleware` 之间）。Guard Model 如果要在 HITL 之前触发，位置是合适的。

2. `before_model` 和 `after_model` 能修改请求和检查响应，但无法直接修改流式输出的中间 token。流式拦截必须通过 `wrap_model_call` 实现。

3. LanceDB 记忆插件依赖 `store` 对象，需要在 `OLAVAgent.__init__` 中手动注册，无法通过 entry points 自动完成。这是 di（依赖注入）和 entry points 自动发现之间的固有张力，设计上接受这一限制。

4. 在 `astream_events` 里注入 callbacks 只对该次调用生效；若 CLI 执行循环通过 `deepagents_cli.execution.execute_task` 调用图，需确认 callback 的注入位置，可能需要在 `execute_task` 的 config 参数处传入。
