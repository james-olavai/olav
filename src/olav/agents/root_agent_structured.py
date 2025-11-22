"""Structured Root Agent using LangGraph StateGraph.

This version uses explicit state machine for funnel debugging workflow:
Intent Analysis → Macro Analysis → Self-Evaluation → Micro Diagnosis → Final Answer

Compared to ReAct (prompt-driven):
- ✅ Deterministic flow control (no reliance on LLM understanding trigger words)
- ✅ Self-evaluation loop (checks if sufficient data collected)
- ✅ Forced tool sequence (SuzieQ → Schema → NETCONF)
- ✅ Explicit routing logic (not hidden in prompt)
- ⚠️ Slightly more verbose code
- ⚠️ Less flexible for simple queries (overhead of state transitions)

Architecture:
    User Query → Intent Router
        ├── Simple Query Path: Direct SuzieQ → Answer
        └── Diagnostic Path: Macro → Evaluate → Micro → Answer
"""

import os
import sys
from typing import Literal, TypedDict, Annotated
from enum import Enum

# Windows ProactorEventLoop fix for psycopg async
if sys.platform == "win32":
    import asyncio
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langgraph.graph import StateGraph, END, add_messages
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from olav.core.llm import LLMFactory
from olav.core.prompt_manager import prompt_manager
from olav.core.settings import settings
from config.settings import AgentConfig

# Import all tools
from olav.tools.suzieq_parquet_tool import suzieq_query, suzieq_schema_search
from olav.tools.opensearch_tool import search_episodic_memory, search_openconfig_schema
from olav.tools.nornir_tool import cli_tool, netconf_tool
from olav.tools.netbox_tool import netbox_api_call, netbox_schema_search


class TaskType(str, Enum):
    """Task type classification."""
    SIMPLE_QUERY = "simple_query"  # 简单查询：只需 SuzieQ
    DIAGNOSTIC = "diagnostic"  # 诊断任务：需要完整漏斗流程
    CONFIG_CHANGE = "config_change"  # 配置变更：需要 HITL


class WorkflowStage(str, Enum):
    """Current workflow stage."""
    INTENT_ANALYSIS = "intent_analysis"  # 意图分析
    MACRO_ANALYSIS = "macro_analysis"  # 宏观分析（SuzieQ）
    SELF_EVALUATION = "self_evaluation"  # 自我评估（是否需要深入）
    MICRO_DIAGNOSIS = "micro_diagnosis"  # 微观诊断（NETCONF/CLI）
    CONFIG_PLANNING = "config_planning"  # 配置变更规划
    HITL_APPROVAL = "hitl_approval"  # 人工审批
    CONFIG_EXECUTION = "config_execution"  # 执行配置变更
    VALIDATION = "validation"  # 变更后验证
    FINAL_ANSWER = "final_answer"  # 生成最终答案


class StructuredState(TypedDict):
    """State for structured workflow."""
    messages: Annotated[list[BaseMessage], add_messages]
    task_type: TaskType | None  # 任务类型
    stage: WorkflowStage  # 当前阶段
    macro_data: dict | None  # 宏观分析数据（SuzieQ 结果）
    micro_data: dict | None  # 微观诊断数据（NETCONF 结果）
    evaluation_result: dict | None  # 自我评估结果
    needs_micro: bool  # 是否需要微观诊断
    config_plan: dict | None  # 配置变更计划（XPath/设备/参数）
    approval_status: str | None  # 审批状态（pending/approved/rejected）
    execution_result: dict | None  # 执行结果
    validation_result: dict | None  # 验证结果
    iteration_count: int  # 迭代计数


async def intent_analysis_node(state: StructuredState) -> StructuredState:
    """Node 1: Analyze user intent and classify task type.
    
    Uses LLM to determine if this is:
    - Simple query (只需状态查询)
    - Diagnostic task (需要根因分析)
    - Config change (需要修改配置)
    """
    llm = LLMFactory.get_chat_model()
    
    # 获取最后一条用户消息
    last_message = state["messages"][-1].content
    
    # Intent classification prompt
    classification_prompt = f"""分析用户请求，分类任务类型：

用户请求: {last_message}

任务分类标准：
1. SIMPLE_QUERY: 仅查询状态/概览，无需深入分析
   - 关键词: "查询"、"显示"、"列出"、"状态"、"统计"
   - 示例: "查询 R1 的接口状态"、"显示 BGP 邻居数量"
   
2. DIAGNOSTIC: 需要分析根因、排查问题
   - 关键词: "为什么"、"原因"、"诊断"、"排查"、"没有建立"、"down"、"失败"
   - 示例: "为什么 R1 的 BGP 没有建立"、"诊断 R2 的接口 down 原因"
   
3. CONFIG_CHANGE: 需要修改配置
   - 关键词: "修改"、"配置"、"设置"、"添加"、"删除"
   - 示例: "修改 R1 的 BGP AS 号"、"添加新的 VLAN"

仅返回一个单词: SIMPLE_QUERY 或 DIAGNOSTIC 或 CONFIG_CHANGE
"""
    
    response = await llm.ainvoke([SystemMessage(content=classification_prompt)])
    task_type_str = response.content.strip().upper()
    
    # 解析任务类型
    try:
        task_type = TaskType(task_type_str.lower())
    except ValueError:
        # 默认为诊断任务（保守策略）
        task_type = TaskType.DIAGNOSTIC
    
    return {
        **state,
        "task_type": task_type,
        "stage": WorkflowStage.INTENT_ANALYSIS,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def macro_analysis_node(state: StructuredState) -> StructuredState:
    """Node 2: Perform macro-level analysis using SuzieQ.
    
    Always executed for DIAGNOSTIC and SIMPLE_QUERY tasks.
    """
    llm = LLMFactory.get_chat_model()
    
    # Bind SuzieQ tools
    llm_with_tools = llm.bind_tools([suzieq_query, suzieq_schema_search])
    
    macro_prompt = f"""使用 SuzieQ 工具进行宏观分析。

用户请求: {state['messages'][-1].content}
任务类型: {state['task_type'].value}

步骤：
1. 如果不确定表名/字段，先用 suzieq_schema_search 查询
2. 使用 suzieq_query 获取历史数据（summarize/get 方法）
3. 分析结果，识别异常模式

返回分析结果。
"""
    
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=macro_prompt),
        *state["messages"]
    ])
    
    # TODO: 实际调用工具（需要实现 tool calling loop）
    # 这里简化为直接返回 LLM 响应
    
    return {
        **state,
        "macro_data": {"analysis": response.content},
        "stage": WorkflowStage.MACRO_ANALYSIS,
        "messages": state["messages"] + [AIMessage(content=response.content)],
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def self_evaluation_node(state: StructuredState) -> StructuredState:
    """Node 3: Self-evaluate if macro analysis is sufficient.
    
    For DIAGNOSTIC tasks, checks if we have enough data to answer.
    If not, sets needs_micro=True to trigger NETCONF/CLI diagnosis.
    """
    if state["task_type"] == TaskType.SIMPLE_QUERY:
        # Simple queries don't need micro diagnosis
        return {
            **state,
            "needs_micro": False,
            "stage": WorkflowStage.SELF_EVALUATION,
        }
    
    llm = LLMFactory.get_chat_model()
    
    eval_prompt = f"""评估当前宏观分析数据是否足以回答用户问题。

用户请求: {state['messages'][0].content}
宏观分析结果: {state['macro_data']}

评估标准：
- 如果用户询问"为什么"/"原因"，仅历史数据不足，需要实时配置验证
- 如果发现异常状态（NotEstd/down），需要获取实时配置确认根因
- 如果只是统计/概览，历史数据已足够

返回 JSON:
{{
    "sufficient": true/false,
    "reason": "评估原因",
    "missing_data": ["需要补充的数据类型"]
}}
"""
    
    response = await llm.ainvoke([SystemMessage(content=eval_prompt)])
    
    # TODO: 解析 JSON 响应
    # 简化版：检查用户问题是否包含触发词
    user_query = state['messages'][0].content.lower()
    trigger_words = ["为什么", "原因", "诊断", "排查", "why", "cause"]
    needs_micro = any(word in user_query for word in trigger_words)
    
    return {
        **state,
        "needs_micro": needs_micro,
        "evaluation_result": {"response": response.content},
        "stage": WorkflowStage.SELF_EVALUATION,
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def micro_diagnosis_node(state: StructuredState) -> StructuredState:
    """Node 4: Perform micro-level diagnosis using NETCONF/CLI.
    
    Only executed if self_evaluation determines needs_micro=True.
    """
    llm = LLMFactory.get_chat_model()
    
    # Bind NETCONF/CLI tools
    llm_with_tools = llm.bind_tools([
        search_openconfig_schema,
        netconf_tool,
        cli_tool
    ])
    
    micro_prompt = f"""基于宏观分析结果，执行微观诊断。

宏观分析: {state['macro_data']}
用户请求: {state['messages'][0].content}

步骤：
1. 使用 search_openconfig_schema 确认 XPath
2. 使用 netconf_tool 获取实时配置（优先）
3. 如果 NETCONF 失败，降级到 cli_tool
4. 对比历史数据 vs 实时配置，定位根因

返回诊断结果。
"""
    
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=micro_prompt),
        *state["messages"]
    ])
    
    return {
        **state,
        "micro_data": {"diagnosis": response.content},
        "stage": WorkflowStage.MICRO_DIAGNOSIS,
        "messages": state["messages"] + [AIMessage(content=response.content)],
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def config_planning_node(state: StructuredState) -> StructuredState:
    """Node 5: Plan configuration changes (for CONFIG_CHANGE tasks).
    
    Steps:
    1. Query current config via NETCONF/CLI
    2. Search OpenConfig schema for XPath
    3. Search episodic memory for similar successful changes
    4. Generate detailed change plan with rollback strategy
    """
    llm = LLMFactory.get_chat_model()
    
    # Bind config-related tools
    llm_with_tools = llm.bind_tools([
        search_episodic_memory,
        search_openconfig_schema,
        netconf_tool,
        cli_tool,
    ])
    
    planning_prompt = f"""为配置变更任务生成详细执行计划。

用户请求: {state['messages'][0].content}

步骤：
1. search_episodic_memory(query="类似变更") → 查询历史成功路径
2. search_openconfig_schema(query="相关 XPath") → 确认配置路径
3. netconf_tool(operation="get-config") → 获取当前配置
4. 生成变更计划，包含：
   - 目标设备列表
   - 配置 XPath 和新值
   - 预期影响范围
   - 回滚策略（NETCONF commit 自动回滚 / CLI 手动回滚命令）
   - 风险评估

返回 JSON 格式计划：
{{
    "devices": ["R1", "R2"],
    "changes": [
        {{"xpath": "/openconfig-bgp:bgp/global/config/as", "old_value": "65000", "new_value": "65001"}},
    ],
    "impact": "可能导致 BGP 会话重启",
    "rollback_strategy": "NETCONF commit with confirmed timeout 300s",
    "risk_level": "MEDIUM"
}}
"""
    
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=planning_prompt),
        *state["messages"]
    ])
    
    # TODO: Parse JSON plan from response
    config_plan = {"plan": response.content}
    
    return {
        **state,
        "config_plan": config_plan,
        "stage": WorkflowStage.CONFIG_PLANNING,
        "messages": state["messages"] + [AIMessage(content=response.content)],
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def hitl_approval_node(state: StructuredState) -> StructuredState:
    """Node 6: Human-in-the-loop approval (for CONFIG_CHANGE tasks).
    
    This is an interrupt point - LangGraph will pause here and wait for
    human approval before proceeding to config_execution_node.
    
    Note: Actual HITL UI is handled by LangGraph's interrupt mechanism.
    This node just records the approval status from state update.
    """
    # When execution resumes after interrupt, approval_status should be set by user
    approval_status = state.get("approval_status", "pending")
    
    return {
        **state,
        "stage": WorkflowStage.HITL_APPROVAL,
        "approval_status": approval_status,
    }


async def config_execution_node(state: StructuredState) -> StructuredState:
    """Node 7: Execute configuration changes (only if approved).
    
    Executes the change plan via NETCONF/CLI with rollback protection.
    """
    if state.get("approval_status") != "approved":
        return {
            **state,
            "execution_result": {"status": "rejected", "message": "User rejected the change"},
            "stage": WorkflowStage.CONFIG_EXECUTION,
        }
    
    llm = LLMFactory.get_chat_model()
    llm_with_tools = llm.bind_tools([netconf_tool, cli_tool])
    
    execution_prompt = f"""执行已批准的配置变更计划。

变更计划: {state['config_plan']}

步骤：
1. 优先使用 netconf_tool(operation="edit-config") with confirmed commit
2. 如果 NETCONF 失败，降级到 cli_tool（警告用户无自动回滚）
3. 记录每个设备的执行结果
4. 如果任何设备失败，立即停止并回滚

返回执行结果 JSON：
{{
    "status": "success/partial/failed",
    "devices_succeeded": ["R1"],
    "devices_failed": [],
    "errors": [],
    "rollback_triggered": false
}}
"""
    
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=execution_prompt),
        *state["messages"]
    ])
    
    execution_result = {"result": response.content}
    
    return {
        **state,
        "execution_result": execution_result,
        "stage": WorkflowStage.CONFIG_EXECUTION,
        "messages": state["messages"] + [AIMessage(content=response.content)],
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def validation_node(state: StructuredState) -> StructuredState:
    """Node 8: Validate configuration changes (post-execution).
    
    Verifies that changes took effect and system is stable.
    """
    llm = LLMFactory.get_chat_model()
    llm_with_tools = llm.bind_tools([suzieq_query, netconf_tool, cli_tool])
    
    validation_prompt = f"""验证配置变更是否成功生效。

变更计划: {state['config_plan']}
执行结果: {state['execution_result']}

步骤：
1. 使用 netconf_tool(operation="get-config") 确认新配置已应用
2. 使用 suzieq_query 检查相关状态（如 BGP 邻居是否重新建立）
3. 检查是否有异常告警或状态变化

返回验证结果 JSON：
{{
    "config_applied": true/false,
    "state_healthy": true/false,
    "issues_detected": [],
    "recommendation": "变更成功"或"建议回滚"
}}
"""
    
    response = await llm_with_tools.ainvoke([
        SystemMessage(content=validation_prompt),
        *state["messages"]
    ])
    
    validation_result = {"result": response.content}
    
    return {
        **state,
        "validation_result": validation_result,
        "stage": WorkflowStage.VALIDATION,
        "messages": state["messages"] + [AIMessage(content=response.content)],
        "iteration_count": state.get("iteration_count", 0) + 1,
    }


async def final_answer_node(state: StructuredState) -> StructuredState:
    """Node 5: Generate final answer combining all analysis."""
    llm = LLMFactory.get_chat_model()
    
    final_prompt = f"""综合所有分析，给出最终答案。

用户请求: {state['messages'][0].content}
任务类型: {state['task_type'].value}
宏观分析: {state.get('macro_data')}
微观诊断: {state.get('micro_data')}

要求：
- 直接回答用户问题
- 如果是诊断任务，给出明确根因
- 如果需要配置变更，说明会触发 HITL 审批
- 使用清晰的结构化输出（表格/列表）
"""
    
    response = await llm.ainvoke([SystemMessage(content=final_prompt)])
    
    return {
        **state,
        "stage": WorkflowStage.FINAL_ANSWER,
        "messages": state["messages"] + [AIMessage(content=response.content)],
    }


def route_after_intent(state: StructuredState) -> Literal["macro_analysis", "config_planning"]:
    """Router: After intent analysis, route based on task type.
    
    - CONFIG_CHANGE: Go directly to config planning (skip macro analysis)
    - SIMPLE_QUERY / DIAGNOSTIC: Go through macro analysis first
    """
    if state.get("task_type") == TaskType.CONFIG_CHANGE:
        return "config_planning"
    return "macro_analysis"


def route_after_evaluation(state: StructuredState) -> Literal["micro_diagnosis", "final_answer"]:
    """Router: After evaluation, decide if micro diagnosis needed."""
    if state.get("needs_micro", False):
        return "micro_diagnosis"
    return "final_answer"


def route_after_approval(state: StructuredState) -> Literal["config_execution", "final_answer"]:
    """Router: After HITL approval, decide whether to execute or abort.
    
    If approved: proceed to execution
    If rejected: skip to final answer with rejection message
    """
    if state.get("approval_status") == "approved":
        return "config_execution"
    return "final_answer"


async def create_root_agent_structured():
    """Create structured root agent with explicit workflow.
    
    Returns:
        Tuple of (agent_executor, checkpointer_manager)
    
    Workflow (Two Paths):
    
    Path 1: Query/Diagnostic
        User Query
        ↓
        Intent Analysis (classify task type)
        ↓
        Macro Analysis (SuzieQ historical data)
        ↓
        Self Evaluation (sufficient data?)
        ├── Yes → Final Answer
        └── No → Micro Diagnosis (NETCONF/CLI) → Final Answer
    
    Path 2: Config Change
        User Query
        ↓
        Intent Analysis (classify task type)
        ↓
        Config Planning (generate change plan + rollback strategy)
        ↓
        HITL Approval (human review)
        ├── Approved → Config Execution → Validation → Final Answer
        └── Rejected → Final Answer (abort)
    """
    # Get shared PostgreSQL checkpointer
    checkpointer_manager = AsyncPostgresSaver.from_conn_string(settings.postgres_uri)
    checkpointer = await checkpointer_manager.__aenter__()
    await checkpointer.setup()
    
    # Build StateGraph
    workflow = StateGraph(StructuredState)
    
    # Add nodes
    workflow.add_node("intent_analysis", intent_analysis_node)
    workflow.add_node("macro_analysis", macro_analysis_node)
    workflow.add_node("self_evaluation", self_evaluation_node)
    workflow.add_node("micro_diagnosis", micro_diagnosis_node)
    workflow.add_node("config_planning", config_planning_node)
    workflow.add_node("hitl_approval", hitl_approval_node)
    workflow.add_node("config_execution", config_execution_node)
    workflow.add_node("validation", validation_node)
    workflow.add_node("final_answer", final_answer_node)
    
    # Add edges - Query/Diagnostic path
    workflow.set_entry_point("intent_analysis")
    workflow.add_conditional_edges(
        "intent_analysis",
        route_after_intent,
        {
            "macro_analysis": "macro_analysis",
            "config_planning": "config_planning",
        }
    )
    workflow.add_edge("macro_analysis", "self_evaluation")
    workflow.add_conditional_edges(
        "self_evaluation",
        route_after_evaluation,
        {
            "micro_diagnosis": "micro_diagnosis",
            "final_answer": "final_answer",
        }
    )
    workflow.add_edge("micro_diagnosis", "final_answer")
    
    # Add edges - Config Change path
    workflow.add_edge("config_planning", "hitl_approval")
    workflow.add_conditional_edges(
        "hitl_approval",
        route_after_approval,
        {
            "config_execution": "config_execution",
            "final_answer": "final_answer",
        }
    )
    workflow.add_edge("config_execution", "validation")
    workflow.add_edge("validation", "final_answer")
    
    workflow.add_edge("final_answer", END)
    
    # Compile graph with interrupt on HITL approval node
    app = workflow.compile(
        checkpointer=checkpointer,
        interrupt_before=["hitl_approval"],  # Pause before approval for human review
    )
    
    return app, checkpointer_manager


__all__ = ["create_root_agent_structured", "StructuredState", "TaskType", "WorkflowStage"]
