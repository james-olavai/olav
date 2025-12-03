"""Query Agent - Read-only information retrieval.

This agent handles information retrieval queries:
- Device status queries
- Configuration lookups
- Inventory queries
- Documentation searches

Tools (3 only - LangChain best practice):
- suzieq_query: Cached telemetry data (L2)
- netbox_query: SSOT inventory queries (L3)
- document_search: Knowledge base RAG (L1)

NO write operations, NO HITL required.
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
from olav.tools.document_tool import search_documents
from olav.tools.netbox_tool import netbox_api_call
from olav.tools.suzieq_parquet_tool import suzieq_query

from .base import BaseAgent


class QueryAgentState(BaseModel):
    """State for Query Agent."""

    messages: list[Any] = Field(default_factory=list)
    query_result: dict | None = None
    iteration_count: int = 0


class QueryAgent(BaseAgent):
    """Query Agent for read-only information retrieval.

    Follows LangChain best practice: 3 tools per agent.

    Tool Stack (Funnel Priority):
    1. suzieq_query (L2): Fast cached telemetry
    2. netbox_api_call (L3): SSOT inventory
    3. search_documents (L1): Knowledge base fallback
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None = None):
        """Initialize Query Agent.

        Args:
            checkpointer: LangGraph checkpointer for state persistence
        """
        self.checkpointer = checkpointer
        self.tools = [
            suzieq_query,
            netbox_api_call,
            search_documents,
        ]
        self._graph = None

    @property
    def name(self) -> str:
        return "query_agent"

    @property
    def description(self) -> str:
        return "信息查询代理 - 只读操作，无需审批"

    @property
    def tools_count(self) -> int:
        return len(self.tools)

    def build_graph(self) -> StateGraph:
        """Build Query Agent graph."""

        tools_node = ToolNode(self.tools)

        async def query_node(state: dict) -> dict:
            """Main query processing node."""
            llm = LLMFactory.get_chat_model()
            llm_with_tools = llm.bind_tools(self.tools)

            # Load system prompt
            try:
                system_prompt = prompt_manager.load_prompt(
                    "agents/query_agent", "system"
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
            }

        async def answer_node(state: dict) -> dict:
            """Generate final answer from query results."""
            llm = LLMFactory.get_chat_model()

            messages = state.get("messages", [])
            user_query = messages[0].content if messages else ""

            # Extract tool results
            tool_results = []
            for msg in messages:
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    if "output" in msg.content or "data" in msg.content:
                        tool_results.append(msg.content)

            answer_prompt = f"""根据查询结果回答用户问题。

用户问题: {user_query}

查询结果:
{chr(10).join(tool_results[-3:])}  # Last 3 results

要求：
- 直接回答问题，不要重复工具调用
- 使用表格或列表格式化输出
- 如果没有找到数据，诚实说明
"""

            response = await llm.ainvoke([SystemMessage(content=answer_prompt)])

            return {
                "messages": messages + [AIMessage(content=response.content)],
                "query_result": {"answer": response.content},
            }

        # Build graph
        workflow = StateGraph(dict)

        workflow.add_node("query", query_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("answer", answer_node)

        workflow.set_entry_point("query")

        # Query loop: query -> tools -> query OR answer
        workflow.add_conditional_edges(
            "query",
            tools_condition,
            {"tools": "tools", "__end__": "answer"},
        )
        workflow.add_edge("tools", "query")
        workflow.add_edge("answer", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def run(self, query: str, thread_id: str | None = None) -> dict:
        """Run query agent with user query.

        Args:
            query: User's query string
            thread_id: Optional thread ID for conversation continuity

        Returns:
            dict with messages and query_result
        """
        if self._graph is None:
            self._graph = self.build_graph()

        config = {"configurable": {"thread_id": thread_id or "default"}}
        initial_state = {
            "messages": [HumanMessage(content=query)],
            "iteration_count": 0,
        }

        result = await self._graph.ainvoke(initial_state, config=config)
        return result

    def _get_fallback_prompt(self) -> str:
        """Fallback system prompt if config not found."""
        return """你是一个网络信息查询专家。你的任务是回答用户的只读查询请求。

## 可用工具

### 1. suzieq_query (优先使用)
查询缓存的网络遥测数据。速度快，数据可能有几分钟延迟。
- 接口状态、BGP 邻居、OSPF 邻居、路由表等
- 支持的表: interfaces, bgp, ospf, routes, macs, arpnd, device 等

### 2. netbox_api_call
查询 NetBox SSOT 数据。设备清单、IP 地址、站点、机架等。
- GET /dcim/devices/ - 设备列表
- GET /ipam/ip-addresses/ - IP 地址
- GET /dcim/interfaces/ - 接口配置

### 3. search_documents
搜索知识库文档。配置指南、故障排除手册、RFC 等。
- 当其他工具无法回答时使用
- 适合"如何配置"、"最佳实践"类问题

## 工作流程

1. 分析用户问题，确定需要什么数据
2. 优先使用 suzieq_query 获取实时状态
3. 如果需要清单信息，使用 netbox_api_call
4. 如果需要配置指南，使用 search_documents
5. 综合结果回答用户问题

## 重要规则

- 只使用只读操作，不要修改任何配置
- 如果数据不可用，诚实回答"未找到相关数据"
- 使用表格或列表格式化输出
"""


__all__ = ["QueryAgent", "QueryAgentState"]
