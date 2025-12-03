"""Config Agent - Configuration changes with HITL approval.

This agent handles configuration operations:
- Device configuration changes
- NetBox resource management
- All write operations

Tools (3 only - LangChain best practice):
- netconf_edit: NETCONF edit-config (HITL required)
- cli_config: CLI configuration commands (HITL required)
- netbox_api_call: NetBox POST/PUT/DELETE (HITL required)

ALL operations require Human-in-the-Loop approval.
"""

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition
from pydantic import BaseModel, Field

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager
from olav.tools.netbox_tool import netbox_api_call
from olav.tools.nornir_tool import cli_config, netconf_edit

from .base import BaseAgent


class ConfigOperation(BaseModel):
    """Structured output for configuration operations."""

    operation_type: str = Field(description="Type of operation: netconf/cli/netbox")
    target: str = Field(description="Target device or resource")
    changes: list[str] = Field(description="List of configuration changes")
    hitl_status: str = Field(
        default="pending",
        description="HITL approval status: pending/approved/rejected",
    )
    result: str | None = Field(default=None, description="Execution result after approval")


class ConfigAgentState(BaseModel):
    """State for Config Agent."""

    messages: list[Any] = Field(default_factory=list)
    config_operations: list[ConfigOperation] = Field(default_factory=list)
    iteration_count: int = 0
    hitl_pending: bool = False


class ConfigAgent(BaseAgent):
    """Config Agent for configuration changes with HITL approval.

    Follows LangChain best practice: 3 tools per agent.

    Tool Stack (All HITL Required):
    1. netconf_edit: NETCONF edit-config for OpenConfig devices
    2. cli_config: CLI configuration for legacy devices
    3. netbox_api_call: NetBox resource management (POST/PUT/DELETE)

    ALL operations trigger Human-in-the-Loop approval before execution.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None = None):
        """Initialize Config Agent.

        Args:
            checkpointer: LangGraph checkpointer for state persistence
        """
        self.checkpointer = checkpointer
        self.tools = [
            netconf_edit,
            cli_config,
            netbox_api_call,
        ]
        self._graph = None

    @property
    def name(self) -> str:
        return "config_agent"

    @property
    def description(self) -> str:
        return "配置代理 - 配置变更操作，需要人工审批"

    @property
    def tools_count(self) -> int:
        return len(self.tools)

    def build_graph(self) -> StateGraph:
        """Build Config Agent graph with HITL checkpoints."""

        tools_node = ToolNode(self.tools)

        async def prepare_config_node(state: dict) -> dict:
            """Prepare configuration payload and request approval."""
            llm = LLMFactory.get_chat_model()
            llm_with_tools = llm.bind_tools(self.tools)

            # Load system prompt
            try:
                system_prompt = prompt_manager.load_prompt(
                    "agents/config_agent", "system"
                )
            except Exception:
                system_prompt = self._get_fallback_prompt()

            messages = state.get("messages", [])
            response = await llm_with_tools.ainvoke(
                [SystemMessage(content=system_prompt), *messages]
            )

            return {
                "messages": messages + [response],
                "iteration_count": state.get("iteration_count", 0) + 1,
                "hitl_pending": True,
            }

        async def execute_config_node(state: dict) -> dict:
            """Execute configuration after HITL approval."""
            messages = state.get("messages", [])
            
            # The actual execution happens in the tools node
            # This node handles post-execution summary
            
            summary_prompt = """总结配置变更执行结果。

包括：
1. 执行的操作类型
2. 目标设备/资源
3. 变更内容
4. 执行结果（成功/失败）
5. 如果失败，说明原因和建议
"""
            llm = LLMFactory.get_chat_model()
            response = await llm.ainvoke(
                [SystemMessage(content=summary_prompt), *messages[-5:]]
            )

            return {
                "messages": messages + [AIMessage(content=response.content)],
                "hitl_pending": False,
            }

        # Build graph
        workflow = StateGraph(dict)

        workflow.add_node("prepare_config", prepare_config_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("execute_config", execute_config_node)

        workflow.set_entry_point("prepare_config")

        # Config flow: prepare -> tools -> execute
        workflow.add_conditional_edges(
            "prepare_config",
            tools_condition,
            {"tools": "tools", "__end__": "execute_config"},
        )
        workflow.add_edge("tools", "prepare_config")
        workflow.add_edge("execute_config", END)

        return workflow.compile(
            checkpointer=self.checkpointer,
            interrupt_before=["tools"],  # HITL interrupt before tool execution
        )

    async def run(
        self,
        query: str,
        thread_id: str | None = None,
        context: dict | None = None,
    ) -> dict:
        """Run config agent with user query or handoff context.

        Args:
            query: User's configuration request or handoff task
            thread_id: Optional thread ID for conversation continuity
            context: Optional context from Diagnose Agent handoff

        Returns:
            dict with messages and config_operations
        """
        if self._graph is None:
            self._graph = self.build_graph()

        config = {"configurable": {"thread_id": thread_id or "default"}}

        # Build initial message with context if provided
        if context:
            full_query = f"""配置任务: {query}

诊断上下文:
- 根因: {context.get('root_cause', 'N/A')}
- 受影响设备: {context.get('affected_devices', [])}
- 建议修复: {context.get('suggested_fix', 'N/A')}

请根据诊断结果执行配置修复。
"""
        else:
            full_query = query

        initial_state = {
            "messages": [HumanMessage(content=full_query)],
            "iteration_count": 0,
            "hitl_pending": False,
        }

        result = await self._graph.ainvoke(initial_state, config=config)
        return result

    def _get_fallback_prompt(self) -> str:
        """Fallback system prompt if config not found."""
        return """你是一个网络配置专家。你的任务是执行配置变更操作。

## 重要警告

**所有配置操作都需要人工审批 (HITL)！**

在执行任何工具调用之前，系统会自动暂停并等待人工批准。
请确保你的配置命令是正确的，因为错误的配置可能导致网络中断。

## 可用工具

### 1. netconf_edit
通过 NETCONF edit-config 修改设备配置。
- 用于支持 OpenConfig 的设备 (如 R1)
- 需要提供 XML 格式的配置 payload
- **需要 HITL 审批**

**示例:**
```python
netconf_edit(
    device="R1",
    payload='''
    <interfaces xmlns="http://openconfig.net/yang/interfaces">
      <interface>
        <name>Loopback0</name>
        <config>
          <name>Loopback0</name>
          <description>Management</description>
        </config>
      </interface>
    </interfaces>
    '''
)
```

### 2. cli_config
通过 CLI 执行配置命令。
- 用于不支持 OpenConfig 的设备 (如 R3)
- 提供配置命令列表
- **需要 HITL 审批**

**示例:**
```python
cli_config(
    device="R3",
    config_commands=[
        "interface Loopback10",
        "description Test Interface",
        "ip address 10.10.10.10 255.255.255.255"
    ]
)
```

### 3. netbox_api_call
通过 NetBox API 管理资源。
- POST: 创建新资源
- PUT/PATCH: 更新现有资源
- DELETE: 删除资源
- **POST/PUT/PATCH/DELETE 需要 HITL 审批**

**示例:**
```python
netbox_api_call(
    method="POST",
    endpoint="/dcim/devices/",
    body={
        "name": "SW01",
        "device_type": 1,
        "device_role": 1,
        "site": 1
    }
)
```

## 工作流程

1. **分析请求**: 理解需要执行的配置变更
2. **选择工具**: 
   - OpenConfig 设备 → netconf_edit
   - CLI-only 设备 → cli_config
   - NetBox 资源 → netbox_api_call
3. **准备 payload**: 生成正确的配置命令或 XML
4. **调用工具**: 系统会在执行前暂停等待审批
5. **报告结果**: 执行后报告成功或失败

## 设备能力

- **R1**: 支持 OpenConfig/NETCONF，优先使用 netconf_edit
- **R3**: 仅支持 CLI，使用 cli_config
- **其他**: 根据设备类型选择合适的工具

## 重要规则

1. **始终等待 HITL 审批** - 不要假设配置会自动执行
2. **验证 payload** - 确保语法正确
3. **最小变更原则** - 只修改必要的配置
4. **记录变更** - 说明为什么需要这个配置变更
5. **回滚计划** - 如果可能，提供回滚命令
"""


__all__ = ["ConfigAgent", "ConfigAgentState", "ConfigOperation"]
