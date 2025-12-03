"""Diagnose Agent - Problem analysis and root cause identification.

This agent handles diagnostic queries:
- Root cause analysis
- Failure investigation
- Event correlation
- Performance troubleshooting

Tools (4 only - LangChain best practice):
- suzieq_schema_search: Discover available tables/fields (L2 Meta)
- openconfig_schema_search: Find YANG paths (L1 Meta)
- netconf_get: Real-time device state (L4 Read-only)
- syslog_search: Event log analysis (L3)

Read-only operations, NO HITL required.
May recommend handoff to Config Agent if fix is needed.
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
from olav.tools.nornir_tool import netconf_get
from olav.tools.opensearch_tool import search_openconfig_schema
from olav.tools.suzieq_parquet_tool import suzieq_schema_search
from olav.tools.syslog_tool import syslog_search

from .base import BaseAgent


class DiagnoseResult(BaseModel):
    """Structured output for diagnosis results."""

    root_cause: str = Field(description="Identified root cause of the issue")
    evidence: list[str] = Field(default_factory=list, description="Supporting evidence")
    affected_devices: list[str] = Field(default_factory=list, description="Devices affected")
    needs_config_change: bool = Field(
        default=False, description="Whether a configuration fix is needed"
    )
    suggested_fix: str | None = Field(
        default=None, description="Suggested configuration change if applicable"
    )
    confidence: float = Field(default=0.8, ge=0.0, le=1.0, description="Diagnosis confidence")


class DiagnoseAgentState(BaseModel):
    """State for Diagnose Agent."""

    messages: list[Any] = Field(default_factory=list)
    diagnosis_result: DiagnoseResult | None = None
    iteration_count: int = 0


class DiagnoseAgent(BaseAgent):
    """Diagnose Agent for problem analysis and root cause identification.

    Follows LangChain best practice: 4 tools per agent.

    Tool Stack (Diagnostic Flow):
    1. suzieq_schema_search: Discover what data is available
    2. syslog_search: Find trigger events and timeline
    3. search_openconfig_schema: Get YANG paths for device queries
    4. netconf_get: Read real-time device state (read-only)

    May signal handoff to Config Agent if fix is needed.
    """

    def __init__(self, checkpointer: BaseCheckpointSaver | None = None):
        """Initialize Diagnose Agent.

        Args:
            checkpointer: LangGraph checkpointer for state persistence
        """
        self.checkpointer = checkpointer
        self.tools = [
            suzieq_schema_search,
            search_openconfig_schema,
            netconf_get,
            syslog_search,
        ]
        self._graph = None

    @property
    def name(self) -> str:
        return "diagnose_agent"

    @property
    def description(self) -> str:
        return "诊断代理 - 问题分析与根因定位，只读操作"

    @property
    def tools_count(self) -> int:
        return len(self.tools)

    def build_graph(self) -> StateGraph:
        """Build Diagnose Agent graph."""

        tools_node = ToolNode(self.tools)

        async def diagnose_node(state: dict) -> dict:
            """Main diagnosis processing node."""
            llm = LLMFactory.get_chat_model()
            llm_with_tools = llm.bind_tools(self.tools)

            # Load system prompt
            try:
                system_prompt = prompt_manager.load_prompt(
                    "agents/diagnose_agent", "system"
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

        async def conclusion_node(state: dict) -> dict:
            """Generate diagnosis conclusion with structured output."""
            llm = LLMFactory.get_chat_model()

            messages = state.get("messages", [])
            user_query = messages[0].content if messages else ""

            # Extract investigation results
            investigation_log = []
            for msg in messages:
                if hasattr(msg, "content") and msg.content:
                    investigation_log.append(str(msg.content)[:500])

            conclusion_prompt = f"""根据调查结果，生成诊断结论。

用户问题: {user_query}

调查记录:
{chr(10).join(investigation_log[-5:])}

请生成结构化的诊断结论，包括：
1. **根因 (Root Cause)**: 问题的根本原因
2. **证据 (Evidence)**: 支持诊断的关键证据
3. **影响范围 (Affected Devices)**: 受影响的设备列表
4. **是否需要配置修复 (Needs Config Change)**: 是/否
5. **建议修复方案 (Suggested Fix)**: 如果需要修复，给出具体配置建议
6. **置信度 (Confidence)**: 0.0-1.0

如果问题需要配置修复，明确说明 "需要转交给配置代理处理"。
"""

            response = await llm.ainvoke([SystemMessage(content=conclusion_prompt)])

            # Parse response to determine if handoff is needed
            content = response.content.lower()
            needs_handoff = any(kw in content for kw in [
                "需要修复", "需要配置", "建议修改", "需要转交",
                "config change", "fix needed", "handoff"
            ])

            diagnosis_result = DiagnoseResult(
                root_cause=response.content[:200],  # Simplified extraction
                evidence=[],
                affected_devices=[],
                needs_config_change=needs_handoff,
                suggested_fix=None,
                confidence=0.8,
            )

            return {
                "messages": messages + [AIMessage(content=response.content)],
                "diagnosis_result": diagnosis_result,
            }

        # Build graph
        workflow = StateGraph(dict)

        workflow.add_node("diagnose", diagnose_node)
        workflow.add_node("tools", tools_node)
        workflow.add_node("conclusion", conclusion_node)

        workflow.set_entry_point("diagnose")

        # Diagnosis loop: diagnose -> tools -> diagnose OR conclusion
        workflow.add_conditional_edges(
            "diagnose",
            tools_condition,
            {"tools": "tools", "__end__": "conclusion"},
        )
        workflow.add_edge("tools", "diagnose")
        workflow.add_edge("conclusion", END)

        return workflow.compile(checkpointer=self.checkpointer)

    async def run(self, query: str, thread_id: str | None = None) -> dict:
        """Run diagnose agent with user query.

        Args:
            query: User's diagnostic query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            dict with messages and diagnosis_result
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
        return """你是一个网络故障诊断专家。你的任务是分析问题原因并定位根因。

## 可用工具

### 1. suzieq_schema_search
发现 SuzieQ 中可用的数据表和字段。
- 在查询具体数据前，先了解有哪些表可用
- 返回表名、字段列表、字段类型

### 2. search_openconfig_schema
查找 OpenConfig YANG 模型中的 XPath 路径。
- 用于确定 NETCONF 查询的正确路径
- 搜索关键词如 "BGP neighbor", "interface state"

### 3. syslog_search
搜索设备日志事件。
- 查找问题发生的时间线
- 关联事件：DOWN, ERROR, CONFIG_CHANGE
- 可按设备、时间范围、严重级别过滤

### 4. netconf_get
通过 NETCONF 读取设备实时状态（只读）。
- 需要先用 search_openconfig_schema 确定 XPath
- 只用于读取，不会修改配置

## 诊断流程

1. **理解问题**: 分析用户描述的症状
2. **搜索日志**: 用 syslog_search 查找相关事件
3. **建立时间线**: 确定问题发生的顺序
4. **验证状态**: 用 netconf_get 检查当前设备状态
5. **确定根因**: 综合分析，确定问题根因
6. **评估修复**: 判断是否需要配置修复

## 输出要求

- 给出明确的根因分析
- 列出支持诊断的证据
- 如果需要配置修复，说明需要转交给配置代理
- 提供置信度评估

## 重要规则

- 只使用只读操作，不修改任何配置
- 基于证据诊断，不要猜测
- 如果证据不足，诚实说明无法确定根因
"""


__all__ = ["DiagnoseAgent", "DiagnoseAgentState", "DiagnoseResult"]
