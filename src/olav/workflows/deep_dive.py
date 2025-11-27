"""Deep Dive Workflow - Funnel Debugging with OSI Layer-Based Diagnosis.

This workflow implements **漏斗式排错 (Funnel Debugging)**:
1. Topology Analysis: Identify fault scope and affected devices
2. Layered Hypothesis: Generate hypotheses per OSI layer (L1-L4+)
3. Macro Scan (SuzieQ): Broad sweep to narrow down problem area
4. Micro Diagnosis (NETCONF/CLI): Deep dive only where issues found
5. Root Cause Summary: Correlate findings and generate report

Key Principles:
- Start broad (macro), then narrow (micro)
- Lower layers first (L1→L2→L3→L4+)
- SuzieQ for historical analysis, NETCONF for real-time details
- Stop drilling when root cause identified

Trigger scenarios:
- Neighbor issues: "R1 和 R2 之间 BGP 邻居问题"
- Connectivity: "为什么 A 无法访问 B"
- Protocol failures: "OSPF 邻居关系异常"
- Batch audits: "审计所有边界路由器"

Usage:
    uv run olav.py -e "R1 和 R2 BGP 邻居建立失败"
    uv run olav.py --expert "从 DataCenter-A 到 DataCenter-B 不通"
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import json
import logging
import re
from operator import add
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph

from olav.core.llm import LLMFactory
from olav.core.memory_writer import get_memory_writer
from olav.core.prompt_manager import prompt_manager
from olav.core.settings import settings
from olav.workflows.base import BaseWorkflow
from olav.workflows.registry import WorkflowRegistry

logger = logging.getLogger(__name__)


# ============================================
# Type Definitions for Funnel Debugging
# ============================================

class LayerHypothesis(TypedDict):
    """Hypothesis for a specific OSI layer."""
    layer: Literal["L1", "L2", "L3", "L4"]
    issue: str
    probability: Literal["high", "medium", "low"]
    checks: list[str]  # SuzieQ tables to check


class PhaseCheck(TypedDict):
    """A single check within a diagnosis phase."""
    tool: str  # suzieq_query, netconf_tool, cli_tool
    table: str | None  # For SuzieQ
    filters: dict[str, Any]
    purpose: str
    result: dict[str, Any] | None
    status: Literal["pending", "running", "completed", "failed"] | None


class DiagnosisPhase(TypedDict):
    """A phase in the funnel diagnosis process."""
    phase: int
    layer: Literal["L1", "L2", "L3", "L4"]
    name: str
    checks: list[PhaseCheck]
    deep_dive_trigger: str | None
    findings: list[str]
    status: Literal["pending", "running", "completed", "skipped"]


class TopologyAnalysis(TypedDict):
    """Result of topology analysis."""
    source_device: str | None
    destination_device: str | None
    path_hypothesis: list[str]
    affected_devices: list[str]
    device_roles: dict[str, str]
    scope: Literal["single_device", "local", "path", "domain"]
    confidence: Literal["high", "medium", "low"]


class DiagnosisPlan(TypedDict):
    """Complete diagnosis plan from funnel analysis."""
    summary: str
    affected_scope: list[str]
    hypotheses: list[LayerHypothesis]
    phases: list[DiagnosisPhase]
    current_phase: int
    root_cause_identified: bool
    root_cause: str | None


class TodoItem(TypedDict):
    """Individual task item in the Todo List.

    Extended (Phase 2) with evaluator related fields.
    These optional fields support objective post-execution validation.
    """

    id: int
    task: str
    status: Literal["pending", "in-progress", "completed", "failed"]
    result: str | None
    deps: list[int]  # IDs of prerequisite todos
    # Schema investigation results
    feasibility: Literal["feasible", "uncertain", "infeasible"] | None
    recommended_table: str | None
    schema_notes: str | None
    # External evaluator (Phase 2) - no hardcoded fields needed
    evaluation_passed: bool | None
    evaluation_score: float | None
    failure_reason: str | None


# ============================================
# Internationalization (i18n) Strings
# ============================================
from config.settings import AgentConfig

I18N: dict[str, dict[str, str]] = {
    # Execution Plan Section
    "plan_title": {
        "zh": "## 📋 诊断计划\n",
        "en": "## 📋 Diagnostic Plan\n",
        "ja": "## 📋 診断計画\n",
    },
    "ready_section": {
        "zh": "### ✅ 准备就绪 ({count} 项)\n",
        "en": "### ✅ Ready ({count} items)\n",
        "ja": "### ✅ 準備完了 ({count} 件)\n",
    },
    "uncertain_section": {
        "zh": "### ⚠️ 需要确认 ({count} 项)\n",
        "en": "### ⚠️ Needs Confirmation ({count} items)\n",
        "ja": "### ⚠️ 確認が必要 ({count} 件)\n",
    },
    "infeasible_section": {
        "zh": "### ❌ 暂不支持 ({count} 项)\n",
        "en": "### ❌ Not Supported ({count} items)\n",
        "ja": "### ❌ 未対応 ({count} 件)\n",
    },
    "plan_summary_partial": {
        "zh": "📊 **计划摘要**: {ready}/{total} 项任务准备就绪\n",
        "en": "📊 **Plan Summary**: {ready}/{total} tasks ready\n",
        "ja": "📊 **計画概要**: {ready}/{total} 件のタスクが準備完了\n",
    },
    "plan_summary_full": {
        "zh": "📊 **计划摘要**: 全部 {total} 项任务准备就绪\n",
        "en": "📊 **Plan Summary**: All {total} tasks ready\n",
        "ja": "📊 **計画概要**: 全 {total} 件のタスクが準備完了\n",
    },
    "plan_confirmation": {
        "zh": "部分任务需要确认或暂不支持，是否继续执行已就绪的任务？\n",
        "en": "Some tasks need confirmation or are not supported. Continue with ready tasks?\n",
        "ja": "一部のタスクは確認が必要か、未対応です。準備完了のタスクを続行しますか？\n",
    },
    "action_approve": {
        "zh": "Y / approve  →  开始执行",
        "en": "Y / approve  →  Start execution",
        "ja": "Y / approve  →  実行開始",
    },
    "action_abort": {
        "zh": "N / abort    →  取消计划",
        "en": "N / abort    →  Cancel plan",
        "ja": "N / abort    →  計画中止",
    },
    "action_modify": {
        "zh": "modify       →  修改任务",
        "en": "modify       →  Modify tasks",
        "ja": "modify       →  タスク修正",
    },
    "default_task": {
        "zh": "执行数据查询",
        "en": "Execute data query",
        "ja": "データクエリを実行",
    },
    # Task Execution Results
    "query_complete": {
        "zh": "✅ 查询完成: {table}（{count} 条记录）",
        "en": "✅ Query complete: {table} ({count} records)",
        "ja": "✅ クエリ完了: {table}（{count} 件）",
    },
    "records_header": {
        "zh": "共 {count} 条记录:",
        "en": "{count} records:",
        "ja": "全 {count} 件:",
    },
    "records_header_truncated": {
        "zh": "共 {total} 条记录，显示前 {showing} 条:",
        "en": "{total} records, showing first {showing}:",
        "ja": "全 {total} 件、最初の {showing} 件を表示:",
    },
    "no_diagnostic_fields": {
        "zh": "无可用的诊断字段",
        "en": "No diagnostic fields available",
        "ja": "診断フィールドがありません",
    },
    # State Values
    "state_established": {
        "zh": "✅ 已建立",
        "en": "✅ Established",
        "ja": "✅ 確立済み",
    },
    "state_not_established": {
        "zh": "❌ 未建立",
        "en": "❌ Not Established",
        "ja": "❌ 未確立",
    },
    "state_up": {
        "zh": "✅ UP",
        "en": "✅ UP",
        "ja": "✅ UP",
    },
    "state_down": {
        "zh": "❌ DOWN",
        "en": "❌ DOWN",
        "ja": "❌ DOWN",
    },
    "timestamp_not_established": {
        "zh": "未建立",
        "en": "Not established",
        "ja": "未確立",
    },
    # Field Labels
    "field_hostname": {"zh": "主机", "en": "Host", "ja": "ホスト"},
    "field_peer": {"zh": "邻居地址", "en": "Peer", "ja": "ピア"},
    "field_state": {"zh": "状态", "en": "State", "ja": "状態"},
    "field_ifname": {"zh": "接口名", "en": "Interface", "ja": "インターフェース"},
    "field_adminState": {"zh": "管理状态", "en": "Admin State", "ja": "管理状態"},
    "field_ipAddressList": {"zh": "IP地址", "en": "IP Address", "ja": "IPアドレス"},
    "field_asn": {"zh": "AS号", "en": "ASN", "ja": "AS番号"},
    "field_peerAsn": {"zh": "邻居AS号", "en": "Peer ASN", "ja": "ピアAS番号"},
    "field_prefix": {"zh": "路由前缀", "en": "Prefix", "ja": "プレフィックス"},
    "field_nexthopIp": {"zh": "下一跳", "en": "Next Hop", "ja": "ネクストホップ"},
    "field_protocol": {"zh": "协议", "en": "Protocol", "ja": "プロトコル"},
    "field_vrf": {"zh": "VRF", "en": "VRF", "ja": "VRF"},
    "field_sqvers": {"zh": "版本", "en": "Version", "ja": "バージョン"},
    "field_origPeer": {"zh": "原始邻居", "en": "Origin Peer", "ja": "元ピア"},
    "field_afi": {"zh": "地址族", "en": "AFI", "ja": "AFI"},
    "field_safi": {"zh": "子地址族", "en": "SAFI", "ja": "SAFI"},
    # Table Names
    "table_bgp": {"zh": "BGP 邻居表", "en": "BGP Neighbors", "ja": "BGPネイバー"},
    "table_interfaces": {"zh": "接口状态表", "en": "Interfaces", "ja": "インターフェース"},
    "table_routes": {"zh": "路由表", "en": "Routes", "ja": "ルート"},
    "table_device": {"zh": "设备信息表", "en": "Devices", "ja": "デバイス"},
    "table_lldp": {"zh": "LLDP 邻居表", "en": "LLDP Neighbors", "ja": "LLDPネイバー"},
    "table_ospfIf": {"zh": "OSPF 接口表", "en": "OSPF Interfaces", "ja": "OSPFインターフェース"},
    "table_ospfNbr": {"zh": "OSPF 邻居表", "en": "OSPF Neighbors", "ja": "OSPFネイバー"},
    "table_macs": {"zh": "MAC 地址表", "en": "MAC Table", "ja": "MACテーブル"},
    "table_arpnd": {"zh": "ARP/ND 表", "en": "ARP/ND Table", "ja": "ARP/NDテーブル"},
    "table_vlan": {"zh": "VLAN 表", "en": "VLANs", "ja": "VLAN"},
    "table_inventory": {"zh": "设备清单", "en": "Inventory", "ja": "インベントリ"},
    "table_devconfig": {"zh": "设备配置", "en": "Device Config", "ja": "デバイス設定"},
    # Record placeholder
    "record_placeholder": {"zh": "记录", "en": "Record", "ja": "レコード"},
    # Task completion messages
    "task_complete_msg": {
        "zh": "任务 {task_id} 完成: 从 {table} 获取了 {count} 条数据",
        "en": "Task {task_id} complete: Retrieved {count} records from {table}",
        "ja": "タスク {task_id} 完了: {table} から {count} 件取得",
    },
    "task_complete_simple": {
        "zh": "任务完成: 从 {table} 获取了 {count} 条数据",
        "en": "Task complete: Retrieved {count} records from {table}",
        "ja": "タスク完了: {table} から {count} 件取得",
    },
}


def tr(key: str, **kwargs: Any) -> str:
    """Get translated string for current language.
    
    Args:
        key: String key in I18N dictionary
        **kwargs: Format arguments for the string
        
    Returns:
        Translated and formatted string
    """
    lang = AgentConfig.LANGUAGE
    if key not in I18N:
        return key  # Fallback to key itself
    translations = I18N[key]
    text = translations.get(lang, translations.get("en", key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except KeyError:
            return text
    return text


class ExecutionPlan(TypedDict):
    """Execution plan generated from schema investigation."""

    feasible_tasks: list[int]  # Todo IDs that can be executed
    uncertain_tasks: list[int]  # Need user clarification
    infeasible_tasks: list[int]  # Cannot be executed (no schema support)
    recommendations: dict[int, str]  # Todo ID -> recommended approach
    user_approval_required: bool


class DeepDiveState(TypedDict):
    """State for Deep Dive Workflow with Funnel Debugging.

    Funnel Debugging Flow:
        1. topology_analysis: Identify affected devices and scope
        2. diagnosis_plan: OSI layer-based hypothesis and phases
        3. macro_scan: SuzieQ broad sweep per layer
        4. micro_diagnosis: NETCONF/CLI deep dive (if needed)
        5. root_cause_summary: Correlate findings

    Fields:
        messages: Conversation history
        topology: Result of topology analysis
        diagnosis_plan: Layered diagnosis phases
        todos: Legacy todo list (for backward compat)
        execution_plan: Schema investigation results
        current_phase: Current diagnosis phase (0-based)
        findings: Accumulated diagnostic findings
        completed_results: Mapping of check_id -> result
        recursion_depth: Current recursion level
        max_depth: Maximum recursion depth
        expert_mode: Whether expert mode is enabled
        user_approval: HITL approval status
    """

    messages: Annotated[list[BaseMessage], add]
    # Funnel Debugging state
    topology: TopologyAnalysis | None
    diagnosis_plan: DiagnosisPlan | None
    current_phase: int
    findings: list[str]
    # Legacy state (backward compat)
    todos: list[TodoItem]
    execution_plan: ExecutionPlan | None
    current_todo_id: int | None
    completed_results: dict[int, str]
    recursion_depth: int
    max_depth: int
    expert_mode: bool
    trigger_recursion: bool | None
    user_approval: str | None


@WorkflowRegistry.register(
    name="deep_dive",
    description="Deep Dive 漏斗式排错（拓扑分析 → 分层假设 → 宏观扫描 → 微观诊断）",
    examples=[
        "R1 和 R2 之间 BGP 邻居建立失败",
        "为什么 DataCenter-A 无法访问 DataCenter-B",
        "OSPF 邻居关系异常，需要排查",
        "审计所有边界路由器的 BGP 配置",
        "从 Core-R1 到 Edge-R3 路由不通",
        "接口 Gi0/0/1 频繁 flapping",
    ],
    triggers=[
        r"邻居.*问题",
        r"邻居.*失败",
        r"无法访问",
        r"不通",
        r"为什么",
        r"排查",
        r"诊断",
        r"审计",
        r"批量",
        r"从.*到",
        r"flapping",
        r"异常",
    ],
)
class DeepDiveWorkflow(BaseWorkflow):
    """Deep Dive Workflow implementing Funnel Debugging methodology.
    
    Flow:
        1. topology_analysis_node: Parse query, identify affected devices
        2. funnel_planning_node: Generate OSI layer-based diagnosis plan
        3. [HITL] User approves diagnosis plan
        4. macro_scan_node: Execute SuzieQ checks per layer
        5. evaluate_findings_node: Decide if micro diagnosis needed
        6. micro_diagnosis_node: NETCONF/CLI deep dive (if needed)
        7. root_cause_summary_node: Correlate and summarize
    """

    @property
    def name(self) -> str:
        return "deep_dive"

    @property
    def description(self) -> str:
        return "Deep Dive 漏斗式排错（拓扑分析 → 分层假设 → 宏观扫描 → 微观诊断）"

    @property
    def tools_required(self) -> list[str]:
        return [
            "suzieq_query",
            "suzieq_schema_search",
            "netconf_tool",
            "cli_tool",
            "search_openconfig_schema",
        ]

    async def validate_input(self, user_query: str) -> tuple[bool, str]:
        """Check if query requires Deep Dive workflow.

        Deep Dive triggers:
        - Neighbor issues ("邻居问题", "邻居失败", "peer down")
        - Connectivity ("无法访问", "不通", "unreachable")
        - Diagnostics ("为什么", "排查", "诊断")
        - Audit ("审计", "批量")
        - Path issues ("从...到", "between")
        """
        import re

        triggers = [
            # 审计类 (Audit)
            r"审计",
            r"audit",
            r"检查.*完整性",
            r"check.*integrity",
            r"配置.*完整",
            # 批量操作 (Batch)
            r"审计所有",
            r"批量",
            r"全部设备",
            r"所有设备",
            r"所有.*路由器",
            r"all.*router",
            r"多.*设备",
            r"multiple.*device",
            r"多台",
            r"\d+台",
            # 复杂诊断
            r"为什么",
            r"why",
            r"诊断.*问题",
            r"diagnose.*issue",
            r"排查.*故障",
            r"troubleshoot",
            r"根因",
            r"root.*cause",
            r"影响范围",
            r"impact.*scope",
            r"为什么.*无法访问",
            r"从.*到.*",
            r"跨",
            r"深入分析",
            r"详细排查",
            r"彻底检查",
            r"递归",
            # 特定协议深度分析
            r"MPLS.*配置",
            r"BGP.*安全",
            r"OSPF.*邻居",
            r"ISIS.*拓扑",
        ]

        for pattern in triggers:
            if re.search(pattern, user_query, re.IGNORECASE):
                return (True, f"Deep Dive trigger detected: '{pattern}'")

        return (False, "Query does not require Deep Dive workflow")

    def __init__(self) -> None:
        self.llm = LLMFactory.get_chat_model(json_mode=False)
        self.llm_json = LLMFactory.get_chat_model(json_mode=True)

        # OSI Layer to SuzieQ table mapping
        self.layer_tables: dict[str, list[str]] = {
            "L1": ["interfaces", "lldp"],  # Physical: interface state, neighbors
            "L2": ["macs", "vlan"],  # Data Link: MAC table, VLANs
            "L3": ["arpnd", "routes"],  # Network: ARP/ND, routing
            "L4": ["bgp", "ospfIf", "ospfNbr"],  # Transport+: BGP, OSPF
        }

    # ============================================
    # NEW: Funnel Debugging Nodes
    # ============================================

    async def topology_analysis_node(self, state: DeepDiveState) -> dict:
        """Analyze user query to identify affected devices and fault scope.
        
        This is the first step in funnel debugging:
        1. Extract device names from query
        2. Infer device roles (router, switch, firewall)
        3. Determine fault scope (single, local, path, domain)
        4. Query LLDP/topology if available
        
        Returns:
            Updated state with topology analysis
        """
        user_query = state["messages"][-1].content if state["messages"] else ""
        
        # Extract device names using regex
        device_pattern = r'\b([A-Z]{1,4}[-_]?[A-Z0-9]*[-_]?[A-Z0-9]*\d+)\b'
        devices_mentioned = list(set(re.findall(device_pattern, user_query, re.IGNORECASE)))
        
        # Also catch common patterns like "R1", "SW1", "Core-R1"
        simple_pattern = r'\b([RSF][A-Za-z]*[-_]?\d+)\b'
        simple_devices = list(set(re.findall(simple_pattern, user_query, re.IGNORECASE)))
        devices_mentioned = list(set(devices_mentioned + simple_devices))
        
        logger.info(f"Topology analysis: devices mentioned = {devices_mentioned}")
        
        # If we have devices, try to get more context from SuzieQ LLDP
        topology_context = ""
        if devices_mentioned:
            try:
                from olav.tools.suzieq_parquet_tool import suzieq_query
                # Query LLDP for physical neighbors
                lldp_result = await suzieq_query.ainvoke({
                    "table": "lldp",
                    "method": "get",
                    "hostname": devices_mentioned[0] if len(devices_mentioned) == 1 else None,
                })
                if lldp_result.get("data"):
                    neighbors = [
                        f"{r.get('hostname')} ↔ {r.get('peerHostname')}"
                        for r in lldp_result["data"][:10]
                        if r.get("hostname") and r.get("peerHostname")
                    ]
                    topology_context = f"LLDP邻居: {', '.join(neighbors)}"
            except Exception as e:
                logger.warning(f"LLDP query failed: {e}")
        
        # Use LLM to analyze topology
        prompt = prompt_manager.load_prompt(
            category="workflows/deep_dive",
            name="topology_analysis",
            user_query=user_query,
            devices_mentioned=", ".join(devices_mentioned) if devices_mentioned else "未明确指定",
        )
        
        response = await self.llm_json.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_query),
        ])
        
        try:
            analysis = json.loads(response.content)
            topology = TopologyAnalysis(
                source_device=analysis.get("topology_analysis", {}).get("source_device"),
                destination_device=analysis.get("topology_analysis", {}).get("destination_device"),
                path_hypothesis=analysis.get("topology_analysis", {}).get("path_hypothesis", []),
                affected_devices=analysis.get("topology_analysis", {}).get("affected_devices", devices_mentioned),
                device_roles=analysis.get("topology_analysis", {}).get("device_roles", {}),
                scope=analysis.get("topology_analysis", {}).get("scope", "local"),
                confidence=analysis.get("topology_analysis", {}).get("confidence", "medium"),
            )
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Topology analysis parse error: {e}")
            topology = TopologyAnalysis(
                source_device=devices_mentioned[0] if devices_mentioned else None,
                destination_device=devices_mentioned[1] if len(devices_mentioned) > 1 else None,
                path_hypothesis=devices_mentioned,
                affected_devices=devices_mentioned,
                device_roles={d: "router" for d in devices_mentioned},
                scope="local",
                confidence="low",
            )
        
        # Generate user-friendly message
        scope_desc = {
            "single_device": "单设备问题",
            "local": "本地链路/邻居问题",
            "path": "端到端路径问题",
            "domain": "区域/域问题",
        }
        
        msg = f"""## 🗺️ 拓扑分析

**故障范围**: {scope_desc.get(topology['scope'], topology['scope'])}
**受影响设备**: {', '.join(topology['affected_devices']) or '待确定'}
**置信度**: {topology['confidence']}

{topology_context if topology_context else ''}

正在生成分层诊断计划..."""
        
        return {
            "topology": topology,
            "findings": [],
            "current_phase": 0,
            "messages": [AIMessage(content=msg)],
        }

    async def funnel_planning_node(self, state: DeepDiveState) -> dict:
        """Generate OSI layer-based diagnosis plan.
        
        Based on topology analysis, create a phased diagnosis plan:
        - Phase 1: L1 Physical (interfaces, LLDP)
        - Phase 2: L2 Data Link (MAC, VLAN) - if needed
        - Phase 3: L3 Network (ARP, routes)
        - Phase 4: L4+ Application (BGP, OSPF)
        
        Returns:
            Updated state with diagnosis_plan
        """
        user_query = state["messages"][-1].content if state["messages"] else ""
        topology = state.get("topology") or {}
        affected_devices = topology.get("affected_devices", [])
        
        # Build context for LLM
        topology_context = f"""
受影响设备: {', '.join(affected_devices)}
故障范围: {topology.get('scope', 'unknown')}
路径假设: {' → '.join(topology.get('path_hypothesis', []))}
"""
        
        # Use LLM to generate funnel diagnosis plan
        prompt = prompt_manager.load_prompt(
            category="workflows/deep_dive",
            name="funnel_diagnosis",
            user_query=user_query,
            topology_context=topology_context,
            affected_devices=", ".join(affected_devices),
        )
        
        response = await self.llm_json.ainvoke([
            SystemMessage(content=prompt),
            HumanMessage(content=user_query),
        ])
        
        try:
            plan_data = json.loads(response.content)
            
            # Convert to DiagnosisPlan
            phases: list[DiagnosisPhase] = []
            for p in plan_data.get("phases", []):
                checks: list[PhaseCheck] = []
                for c in p.get("checks", []):
                    checks.append(PhaseCheck(
                        tool=c.get("tool", "suzieq_query"),
                        table=c.get("table"),
                        filters=c.get("filters", {}),
                        purpose=c.get("purpose", ""),
                        result=None,
                        status="pending",
                    ))
                phases.append(DiagnosisPhase(
                    phase=p.get("phase", 0),
                    layer=p.get("layer", "L1"),
                    name=p.get("name", ""),
                    checks=checks,
                    deep_dive_trigger=p.get("deep_dive_trigger"),
                    findings=[],
                    status="pending",
                ))
            
            hypotheses: list[LayerHypothesis] = []
            for h in plan_data.get("diagnosis_plan", {}).get("hypothesis", []):
                hypotheses.append(LayerHypothesis(
                    layer=h.get("layer", "L4"),
                    issue=h.get("issue", ""),
                    probability=h.get("probability", "medium"),
                    checks=[],
                ))
            
            diagnosis_plan = DiagnosisPlan(
                summary=plan_data.get("diagnosis_plan", {}).get("summary", ""),
                affected_scope=plan_data.get("diagnosis_plan", {}).get("affected_scope", affected_devices),
                hypotheses=hypotheses,
                phases=phases,
                current_phase=0,
                root_cause_identified=False,
                root_cause=None,
            )
            
        except (json.JSONDecodeError, KeyError) as e:
            logger.warning(f"Funnel plan parse error: {e}, using default plan")
            # Create default L1→L4 plan
            diagnosis_plan = self._create_default_diagnosis_plan(affected_devices)
        
        # Format plan for user approval
        plan_msg = self._format_diagnosis_plan(diagnosis_plan)
        
        # Create execution_plan for HITL compatibility
        execution_plan: ExecutionPlan = {
            "feasible_tasks": list(range(1, len(diagnosis_plan["phases"]) + 1)),
            "uncertain_tasks": [],
            "infeasible_tasks": [],
            "recommendations": {},
            "user_approval_required": True,
        }
        
        return {
            "diagnosis_plan": diagnosis_plan,
            "execution_plan": execution_plan,
            "messages": [AIMessage(content=plan_msg)],
        }

    def _create_default_diagnosis_plan(self, affected_devices: list[str]) -> DiagnosisPlan:
        """Create default L1→L4 diagnosis plan."""
        hostname_filter = {"hostname": affected_devices} if affected_devices else {}
        
        phases = [
            DiagnosisPhase(
                phase=1,
                layer="L1",
                name="物理层检查",
                checks=[
                    PhaseCheck(tool="suzieq_query", table="interfaces", filters=hostname_filter,
                              purpose="检查接口状态", result=None, status="pending"),
                    PhaseCheck(tool="suzieq_query", table="lldp", filters=hostname_filter,
                              purpose="验证物理邻居", result=None, status="pending"),
                ],
                deep_dive_trigger="接口 down 或 LLDP 邻居缺失",
                findings=[],
                status="pending",
            ),
            DiagnosisPhase(
                phase=2,
                layer="L3",
                name="网络层检查",
                checks=[
                    PhaseCheck(tool="suzieq_query", table="arpnd", filters=hostname_filter,
                              purpose="检查 ARP/ND 表", result=None, status="pending"),
                    PhaseCheck(tool="suzieq_query", table="routes", filters=hostname_filter,
                              purpose="检查路由表", result=None, status="pending"),
                ],
                deep_dive_trigger="ARP 缺失或路由不存在",
                findings=[],
                status="pending",
            ),
            DiagnosisPhase(
                phase=3,
                layer="L4",
                name="协议层检查",
                checks=[
                    PhaseCheck(tool="suzieq_query", table="bgp", filters=hostname_filter,
                              purpose="检查 BGP 邻居状态", result=None, status="pending"),
                ],
                deep_dive_trigger="BGP state != Established",
                findings=[],
                status="pending",
            ),
        ]
        
        return DiagnosisPlan(
            summary="默认分层诊断计划: L1 物理层 → L3 网络层 → L4 协议层",
            affected_scope=affected_devices,
            hypotheses=[
                LayerHypothesis(layer="L4", issue="协议邻居未建立", probability="high", checks=[]),
                LayerHypothesis(layer="L1", issue="物理接口故障", probability="medium", checks=[]),
            ],
            phases=phases,
            current_phase=0,
            root_cause_identified=False,
            root_cause=None,
        )

    def _format_diagnosis_plan(self, plan: DiagnosisPlan) -> str:
        """Format diagnosis plan for user review."""
        lines = [
            "## 📋 漏斗式诊断计划\n",
            f"**概述**: {plan['summary']}\n",
            f"**受影响范围**: {', '.join(plan['affected_scope'])}\n",
        ]
        
        if plan["hypotheses"]:
            lines.append("\n### 🔍 初步假设\n")
            for h in plan["hypotheses"]:
                prob_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(h["probability"], "⚪")
                lines.append(f"- {prob_emoji} **{h['layer']}**: {h['issue']} (概率: {h['probability']})")
        
        lines.append("\n### 📊 诊断阶段\n")
        for phase in plan["phases"]:
            layer_emoji = {"L1": "🔌", "L2": "🔗", "L3": "🌐", "L4": "📡"}.get(phase["layer"], "📋")
            lines.append(f"\n**Phase {phase['phase']}: {layer_emoji} {phase['name']}** ({phase['layer']})")
            for check in phase["checks"]:
                lines.append(f"  - `{check['table']}`: {check['purpose']}")
            if phase["deep_dive_trigger"]:
                lines.append(f"  - ⚡ 深入条件: {phase['deep_dive_trigger']}")
        
        lines.append("\n---")
        lines.append(f"\n📊 **计划摘要**: {len(plan['phases'])} 个诊断阶段")
        lines.append("\n```")
        lines.append(f"  {tr('action_approve')}")
        lines.append(f"  {tr('action_abort')}")
        lines.append("```")
        
        return "\n".join(lines)

    async def macro_scan_node(self, state: DeepDiveState) -> dict:
        """Execute SuzieQ checks for current phase (Macro Scan).
        
        This node:
        1. Gets current phase from diagnosis_plan
        2. Executes all SuzieQ checks for that phase
        3. Collects findings (anomalies)
        4. Updates phase status
        
        Returns:
            Updated state with check results and findings
        """
        from langgraph.types import interrupt
        from config.settings import AgentConfig
        
        diagnosis_plan = state.get("diagnosis_plan")
        if not diagnosis_plan:
            return {"messages": [AIMessage(content="❌ 诊断计划缺失")]}
        
        user_approval = state.get("user_approval")
        
        # YOLO mode: auto-approve
        if AgentConfig.YOLO_MODE and user_approval is None:
            logger.info("[YOLO] Auto-approving diagnosis plan...")
            user_approval = "approved"
        
        # HITL: Check if approval needed
        execution_plan = state.get("execution_plan", {})
        if execution_plan.get("user_approval_required") and user_approval is None:
            approval_response = interrupt({
                "action": "approval_required",
                "execution_plan": execution_plan,
                "diagnosis_plan": diagnosis_plan,
                "message": "请审批诊断计划：Y=继续, N=终止",
            })
            
            if isinstance(approval_response, dict):
                if approval_response.get("approved"):
                    user_approval = "approved"
                    return {
                        "user_approval": user_approval,
                        "messages": [AIMessage(content="✅ 诊断计划已批准，开始宏观扫描...")],
                    }
                else:
                    return {
                        "user_approval": "aborted",
                        "messages": [AIMessage(content="⛔ 用户已中止诊断。")],
                    }
            else:
                return {
                    "user_approval": "approved",
                    "messages": [AIMessage(content="✅ 诊断计划已批准，开始宏观扫描...")],
                }
        
        # Execute current phase
        current_phase_idx = state.get("current_phase", 0)
        phases = diagnosis_plan.get("phases", [])
        
        if current_phase_idx >= len(phases):
            return {"messages": [AIMessage(content="所有诊断阶段已完成。")]}
        
        phase = phases[current_phase_idx]
        phase["status"] = "running"
        
        logger.info(f"Executing Phase {phase['phase']}: {phase['name']}")
        
        # Execute checks
        from olav.tools.suzieq_parquet_tool import suzieq_query
        
        phase_findings: list[str] = []
        check_results: list[str] = []
        
        for check in phase["checks"]:
            check["status"] = "running"
            try:
                result = await suzieq_query.ainvoke({
                    "table": check["table"],
                    "method": "get",
                    **check["filters"],
                })
                check["result"] = result
                check["status"] = "completed"
                
                # Analyze result for anomalies
                findings = self._analyze_check_result(check["table"], result, check["purpose"])
                phase_findings.extend(findings)
                
                # Format result summary
                count = result.get("count", len(result.get("data", [])))
                table_name = self._get_table_display_name(check["table"])
                check_results.append(f"✅ {table_name}: {count} 条记录")
                
                if findings:
                    for f in findings:
                        check_results.append(f"  ⚠️ {f}")
                        
            except Exception as e:
                check["status"] = "failed"
                check["result"] = {"error": str(e)}
                check_results.append(f"❌ {check['table']}: {e}")
        
        phase["findings"] = phase_findings
        phase["status"] = "completed"
        state["findings"].extend(phase_findings)
        
        # Format phase result
        layer_emoji = {"L1": "🔌", "L2": "🔗", "L3": "🌐", "L4": "📡"}.get(phase["layer"], "📋")
        msg = f"""## {layer_emoji} Phase {phase['phase']}: {phase['name']} 完成

### 检查结果
{chr(10).join(check_results)}

### 发现 ({len(phase_findings)} 项)
{chr(10).join(f'- {f}' for f in phase_findings) if phase_findings else '- 未发现异常'}
"""
        
        # Move to next phase
        new_phase_idx = current_phase_idx + 1
        
        return {
            "diagnosis_plan": diagnosis_plan,
            "current_phase": new_phase_idx,
            "findings": state["findings"],
            "user_approval": user_approval,
            "messages": [AIMessage(content=msg)],
        }

    def _analyze_check_result(self, table: str, result: dict, purpose: str) -> list[str]:
        """Analyze SuzieQ query result for anomalies."""
        findings = []
        data = result.get("data", [])
        
        if not data:
            findings.append(f"{table}: 无数据（可能采集问题或范围错误）")
            return findings
        
        # Table-specific anomaly detection
        if table == "interfaces":
            down_ifs = [r for r in data if r.get("state") == "down" and r.get("adminState") != "down"]
            if down_ifs:
                for iface in down_ifs[:5]:
                    findings.append(f"接口 {iface.get('hostname')}:{iface.get('ifname')} 状态异常 (adminUp, operDown)")
        
        elif table == "bgp":
            not_estd = [r for r in data if r.get("state") != "Established"]
            if not_estd:
                for peer in not_estd[:5]:
                    reason = peer.get("reason") or peer.get("notificnReason") or "未知"
                    findings.append(f"BGP {peer.get('hostname')} ↔ {peer.get('peer')}: {peer.get('state')} ({reason})")
        
        elif table == "ospfNbr" or table == "ospfIf":
            not_full = [r for r in data if r.get("state") not in ("full", "Full", "dr", "bdr")]
            if not_full:
                for nbr in not_full[:5]:
                    findings.append(f"OSPF {nbr.get('hostname')}:{nbr.get('ifname')} 邻居状态: {nbr.get('state')}")
        
        elif table == "lldp":
            # Check for missing expected neighbors (would need topology baseline)
            if len(data) == 0:
                findings.append("LLDP: 未发现邻居（物理连接可能断开）")
        
        elif table == "arpnd":
            # Check for incomplete ARP entries
            incomplete = [r for r in data if r.get("state") in ("incomplete", "INCOMPLETE")]
            if incomplete:
                for arp in incomplete[:5]:
                    findings.append(f"ARP {arp.get('hostname')}: {arp.get('ipAddress')} 状态不完整")
        
        return findings

    async def evaluate_findings_node(self, state: DeepDiveState) -> dict:
        """Evaluate findings and decide next step.
        
        Decision logic:
        1. If critical findings → trigger micro diagnosis
        2. If more phases → continue macro scan
        3. If all done → go to summary
        
        Returns:
            Updated state with next action decision
        """
        diagnosis_plan = state.get("diagnosis_plan")
        if not diagnosis_plan:
            return {"trigger_recursion": False}
        
        current_phase = state.get("current_phase", 0)
        phases = diagnosis_plan.get("phases", [])
        findings = state.get("findings", [])
        
        # Check if we have critical findings that need micro diagnosis
        critical_keywords = ["down", "异常", "失败", "NotEstd", "incomplete"]
        critical_findings = [f for f in findings if any(k in f for k in critical_keywords)]
        
        if critical_findings and current_phase < len(phases):
            # Found issues - may need micro diagnosis
            logger.info(f"Critical findings detected: {len(critical_findings)}")
        
        # Check if more phases to run
        if current_phase < len(phases):
            return {"trigger_recursion": True}  # Continue to next phase
        
        # All phases done
        return {"trigger_recursion": False}

    async def root_cause_summary_node(self, state: DeepDiveState) -> dict:
        """Generate root cause analysis summary.
        
        Correlates all findings across phases and generates:
        1. Root cause identification
        2. Evidence trail
        3. Recommended actions
        
        Returns:
            Final summary message
        """
        diagnosis_plan = state.get("diagnosis_plan") or {}
        topology = state.get("topology") or {}
        findings = state.get("findings", [])
        user_query = ""
        for msg in state.get("messages", []):
            if isinstance(msg, HumanMessage):
                user_query = msg.content
                break
        
        # Prepare summary context
        phases_summary = []
        for phase in diagnosis_plan.get("phases", []):
            phase_findings = phase.get("findings", [])
            phases_summary.append(f"**{phase['name']}** ({phase['layer']}): {len(phase_findings)} 项发现")
            for f in phase_findings[:3]:
                phases_summary.append(f"  - {f}")
        
        # Use LLM to generate root cause analysis
        prompt = f"""你是网络故障分析专家。根据漏斗式诊断的结果，生成根因分析报告。

## 原始问题
{user_query}

## 拓扑分析
- 受影响设备: {', '.join(topology.get('affected_devices', []))}
- 故障范围: {topology.get('scope', 'unknown')}

## 诊断发现
{chr(10).join(phases_summary)}

## 所有发现
{chr(10).join(f'- {f}' for f in findings) if findings else '- 未发现明显异常'}

请生成根因分析报告，包括:
1. **根因识别**: 最可能的故障原因
2. **证据链**: 支持该结论的关键发现
3. **建议操作**: 修复步骤或进一步排查方向

使用 Markdown 格式输出。"""
        
        response = await self.llm.ainvoke([
            SystemMessage(content=prompt),
        ])
        
        # Save to episodic memory if enabled
        if settings.enable_deep_dive_memory and findings:
            try:
                memory_writer = get_memory_writer()
                await memory_writer.memory.store_episodic_memory(
                    intent=user_query,
                    xpath=f"funnel_diagnosis:{len(findings)} findings",
                    success=len([f for f in findings if "down" in f or "异常" in f]) == 0,
                    context={
                        "tool_used": "deep_dive_funnel",
                        "phases_completed": len(diagnosis_plan.get("phases", [])),
                        "findings_count": len(findings),
                        "affected_devices": topology.get("affected_devices", []),
                    },
                )
            except Exception as e:
                logger.warning(f"Failed to save to episodic memory: {e}")
        
        return {
            "messages": [AIMessage(content=response.content)],
        }

    async def should_continue_funnel(
        self, state: DeepDiveState
    ) -> Literal["macro_scan", "root_cause_summary"]:
        """Decide whether to continue scanning or summarize."""
        if state.get("trigger_recursion"):
            return "macro_scan"
        return "root_cause_summary"

    # ============================================
    # LEGACY: Task Planning Nodes (backward compat)
    # ============================================

    async def task_planning_node(self, state: DeepDiveState) -> dict:
        """Generate Todo List from user query using LLM.

        Args:
            state: Current workflow state

        Returns:
            Updated state with generated todos
        """
        user_query = state["messages"][-1].content if state["messages"] else ""

        # Load task planning prompt
        prompt = prompt_manager.load_prompt(
            category="workflows/deep_dive",
            name="task_planning",
            user_query=user_query,
            recursion_depth=state.get("recursion_depth", 0),
            max_depth=state.get("max_depth", 3),
        )

        # LLM generates structured Todo List
        messages = [SystemMessage(content=prompt), HumanMessage(content=user_query)]
        response = await self.llm_json.ainvoke(messages)

        # Parse JSON response to TodoItem list

        try:
            todo_data = json.loads(response.content)
            todos = [
                TodoItem(
                    id=item["id"],
                    task=item["task"],
                    status="pending",
                    result=None,
                    deps=item.get("deps", []),
                )
                for item in todo_data.get("todos", [])
            ]
        except (json.JSONDecodeError, KeyError):
            # Fallback: Create single todo from query
            todos = [TodoItem(id=1, task=user_query, status="pending", result=None, deps=[])]

        return {
            "todos": todos,
            "execution_plan": None,
            "completed_results": {},
            "recursion_depth": state.get("recursion_depth", 0),
            "max_depth": state.get("max_depth", 3),
            "trigger_recursion": False,
        }

    async def schema_investigation_node(self, state: DeepDiveState) -> dict:
        """Investigate schema feasibility for all planned tasks.

        This node:
        1. Calls suzieq_schema_search for each task to discover available tables
        2. Validates keyword mapping against schema results
        3. Categorizes tasks as feasible/uncertain/infeasible
        4. Generates execution plan with recommendations

        Returns:
            Updated state with execution_plan for user approval
        """
        from olav.tools.suzieq_parquet_tool import suzieq_schema_search

        todos = state["todos"]
        feasible_tasks = []
        uncertain_tasks = []
        infeasible_tasks = []
        recommendations = {}

        for todo in todos:
            task_text = todo["task"]
            task_id = todo["id"]

            # Step 1: Keyword-based mapping (heuristic)
            heuristic_mapping = self._map_task_to_table(task_text)

            # Step 2: Schema search (ground truth)
            try:
                schema_result = await suzieq_schema_search.ainvoke({"query": task_text})
                available_tables = schema_result.get("tables", [])

                if not available_tables:
                    # No schema match at all
                    todo["feasibility"] = "infeasible"
                    todo["schema_notes"] = (
                        "系统中没有找到相关的数据表，可能需要直接连接设备查询"
                    )
                    infeasible_tasks.append(task_id)
                    recommendations[task_id] = (
                        "建议通过 NETCONF 直接查询设备，或检查数据采集是否正常"
                    )

                elif heuristic_mapping:
                    # Validate heuristic against schema
                    heuristic_table = heuristic_mapping[0]
                    if heuristic_table in available_tables:
                        # Perfect match
                        todo["feasibility"] = "feasible"
                        todo["recommended_table"] = heuristic_table
                        # Get human-readable field names
                        fields = schema_result.get(heuristic_table, {}).get('fields', [])[:5]
                        field_desc = self._humanize_fields(fields)
                        todo["schema_notes"] = (
                            f"将从 {heuristic_table} 表查询，包含 {field_desc} 等字段"
                        )
                        feasible_tasks.append(task_id)
                        recommendations[task_id] = (
                            f"执行查询: {heuristic_table} 表"
                        )
                    else:
                        # Heuristic mismatch - use first schema suggestion
                        suggested_table = available_tables[0]
                        todo["feasibility"] = "uncertain"
                        todo["recommended_table"] = suggested_table
                        todo["schema_notes"] = (
                            f"任务描述指向 {heuristic_table}，但系统建议使用 {suggested_table} 表"
                        )
                        uncertain_tasks.append(task_id)
                        recommendations[task_id] = (
                            f"请确认：使用 {suggested_table} 还是 {heuristic_table}？"
                        )

                else:
                    # No heuristic mapping, but schema has suggestions
                    suggested_table = available_tables[0]
                    todo["feasibility"] = "uncertain"
                    todo["recommended_table"] = suggested_table
                    tables_desc = "、".join(available_tables[:3])
                    todo["schema_notes"] = (
                        f"无法自动识别数据源，可能的表: {tables_desc}"
                    )
                    uncertain_tasks.append(task_id)
                    recommendations[task_id] = (
                        f"建议使用 {suggested_table} 表，或指定其他数据源"
                    )

            except Exception as e:
                # Schema search failed
                todo["feasibility"] = "uncertain"
                todo["schema_notes"] = f"查询数据源时出错: {e!s}"
                uncertain_tasks.append(task_id)
                recommendations[task_id] = "请重试或手动指定数据源"

        # Generate execution plan
        # HITL: DeepDive always requires user approval before execution
        # This is a safety measure to prevent unintended operations
        execution_plan: ExecutionPlan = {
            "feasible_tasks": feasible_tasks,
            "uncertain_tasks": uncertain_tasks,
            "infeasible_tasks": infeasible_tasks,
            "recommendations": recommendations,
            "user_approval_required": True,  # Always require approval for DeepDive
        }

        # Generate plan summary message
        plan_summary = self._format_execution_plan(todos, execution_plan)

        return {
            "todos": todos,
            "execution_plan": execution_plan,
            "messages": [AIMessage(content=plan_summary)],
        }

    def _format_execution_plan(self, todos: list[TodoItem], plan: ExecutionPlan) -> str:
        """Format execution plan for user review with human-friendly descriptions."""
        lines = [tr("plan_title")]

        if plan["feasible_tasks"]:
            lines.append(tr("ready_section", count=len(plan['feasible_tasks'])))
            for task_id in plan["feasible_tasks"]:
                todo = next(td for td in todos if td["id"] == task_id)
                # Clean up task description for readability
                task_desc = self._humanize_task(todo['task'])
                lines.append(f"**{task_id}.** {task_desc}")
                lines.append(f"   ↳ {todo['schema_notes']}\n")

        if plan["uncertain_tasks"]:
            lines.append(tr("uncertain_section", count=len(plan['uncertain_tasks'])))
            for task_id in plan["uncertain_tasks"]:
                todo = next(td for td in todos if td["id"] == task_id)
                task_desc = self._humanize_task(todo['task'])
                lines.append(f"**{task_id}.** {task_desc}")
                lines.append(f"   ↳ {todo['schema_notes']}")
                lines.append(f"   💡 {plan['recommendations'][task_id]}\n")

        if plan["infeasible_tasks"]:
            lines.append(tr("infeasible_section", count=len(plan['infeasible_tasks'])))
            for task_id in plan["infeasible_tasks"]:
                todo = next(td for td in todos if td["id"] == task_id)
                task_desc = self._humanize_task(todo['task'])
                lines.append(f"**{task_id}.** {task_desc}")
                lines.append(f"   ↳ {todo['schema_notes']}")
                lines.append(f"   💡 {plan['recommendations'][task_id]}\n")

        # Approval prompt
        lines.append("\n---")
        total = len(plan["feasible_tasks"]) + len(plan["uncertain_tasks"]) + len(plan["infeasible_tasks"])
        ready = len(plan["feasible_tasks"])
        
        if plan.get("uncertain_tasks") or plan.get("infeasible_tasks"):
            lines.append(f"\n{tr('plan_summary_partial', ready=ready, total=total)}")
            lines.append(tr("plan_confirmation"))
        else:
            lines.append(f"\n{tr('plan_summary_full', total=total)}")
        
        lines.append("```")
        lines.append(f"  {tr('action_approve')}")
        lines.append(f"  {tr('action_abort')}")
        lines.append(f"  {tr('action_modify')}")
        lines.append("```")

        return "\n".join(lines)
    
    def _humanize_task(self, task: str) -> str:
        """Convert machine-style task description to human-readable format."""
        # Remove suzieq_query prefix patterns
        import re
        
        # Language-specific device config query replacement
        device_config_label = {
            "zh": "设备配置查询: ",
            "en": "Device config query: ",
            "ja": "デバイス設定クエリ: ",
        }.get(AgentConfig.LANGUAGE, "Device config query: ")
        
        task = re.sub(r"suzieq_query\s*:?\s*", "", task, flags=re.IGNORECASE)
        task = re.sub(r"table\s*=\s*\w+\s*", "", task)
        task = re.sub(r"hostname\s*=\s*\[?['\"]?\w+['\"]?\]?\s*", "", task)
        task = re.sub(r"netconf_tool\s*:?\s*", device_config_label, task, flags=re.IGNORECASE)
        
        # Clean up extra whitespace
        task = re.sub(r"\s+", " ", task).strip()
        
        # Remove leading commas or punctuation
        task = re.sub(r"^[,\s]+", "", task)
        
        return task if task else tr("default_task")
    
    def _humanize_fields(self, fields: list[str]) -> str:
        """Convert field names to human-readable descriptions."""
        readable = []
        for f in fields[:4]:  # Limit to 4 fields
            # Try to get translated field label
            label = tr(f"field_{f}")
            # If not found (returns the key itself), use original field name
            readable.append(label if label != f"field_{f}" else f)
        
        # Use language-appropriate separator
        separator = {"zh": "、", "en": ", ", "ja": "、"}.get(AgentConfig.LANGUAGE, ", ")
        return separator.join(readable)
    
    def _get_table_display_name(self, table: str) -> str:
        """Get human-readable display name for a table."""
        # Try to get translated table name
        label = tr(f"table_{table.lower()}")
        # If not found (returns the key itself), use original table name
        return label if label != f"table_{table.lower()}" else table

    async def execute_todo_node(self, state: DeepDiveState) -> dict:
        """Execute next eligible todo with real tool invocation where possible.

        This node first checks if HITL approval is needed:
        - If execution_plan.user_approval_required and not yet approved, interrupt()
        - User can approve, modify, or abort
        - After approval, execute feasible tasks

        Priority:
        1. Heuristic keyword mapping (device, interface, routes, bgp, etc.)
        2. Schema existence check via suzieq_schema_search
        3. Distinguish SCHEMA_NOT_FOUND vs NO_DATA_FOUND vs OK
        4. Fallback to LLM-driven execution prompt if mapping fails or table unsupported
        """
        import asyncio  # Local import to avoid global side-effects
        from langgraph.types import interrupt
        from config.settings import AgentConfig

        todos = state["todos"]
        completed_results = state.get("completed_results", {})
        execution_plan = state.get("execution_plan", {})
        user_approval = state.get("user_approval")

        # YOLO mode: auto-approve without user interaction
        if AgentConfig.YOLO_MODE and user_approval is None:
            print("[YOLO] Auto-approving execution plan...")
            user_approval = "approved"

        # HITL: Check if approval is needed before first execution
        if execution_plan and execution_plan.get("user_approval_required") and user_approval is None:
            # Interrupt for user approval
            approval_response = interrupt({
                "action": "approval_required",
                "execution_plan": execution_plan,
                "todos": todos,
                "message": "请审批执行计划：approve=继续, abort=终止, 或输入修改请求",
            })

            # Process approval response (returned by Command(resume=...))
            if isinstance(approval_response, dict):
                if approval_response.get("approved"):
                    user_approval = approval_response.get("user_approval", "approved")
                    if approval_response.get("modified_plan"):
                        execution_plan = approval_response["modified_plan"]
                        # Return immediately to update state with new plan
                        return {
                            "user_approval": user_approval,
                            "execution_plan": execution_plan,
                        }
                    # CRITICAL: Return immediately after approval to persist state
                    # Then next loop iteration will have user_approval set
                    return {
                        "user_approval": user_approval,
                        "messages": [AIMessage(content="✅ 用户已批准执行计划，开始执行任务...")],
                    }
                else:
                    # User aborted
                    return {
                        "messages": [AIMessage(content="⛔ 用户已中止执行计划。")],
                        "user_approval": "aborted",
                    }
            else:
                # Simple resume value (just approval) - also return immediately
                return {
                    "user_approval": "approved",
                    "messages": [AIMessage(content="✅ 用户已批准执行计划，开始执行任务...")],
                }

        # ------------------------------------------------------------------
        # Parallel batch execution (Phase 3.2)
        # Strategy: Identify all ready & dependency-satisfied todos without deps.
        # Run up to parallel_batch_size concurrently. Falls back to serial path
        # when <=1 independent ready todo.
        # ------------------------------------------------------------------
        parallel_batch_size = state.get("parallel_batch_size", 5)

        ready: list[TodoItem] = []
        for todo in todos:
            if todo["status"] == "pending":
                deps_ok = all(
                    any(t["id"] == dep_id and t["status"] in {"completed", "failed"} for t in todos)
                    for dep_id in todo["deps"]
                )
                if deps_ok:
                    ready.append(todo)

        independent = [t for t in ready if not t["deps"]]

        if len(independent) > 1:
            batch = independent[:parallel_batch_size]
            # Mark batch in-progress
            for t in batch:
                t["status"] = "in-progress"

            async def _execute_single(todo: TodoItem) -> tuple[TodoItem, list[BaseMessage]]:
                task_text = todo["task"].strip()
                mapping = self._map_task_to_table(task_text)
                tool_result: dict | None = None
                messages: list[BaseMessage] = []
                if mapping:
                    table, method, extra_filters = mapping
                    tool_input = {"table": table, "method": method, **extra_filters}
                    try:
                        from olav.tools.suzieq_parquet_tool import (  # type: ignore
                            suzieq_query,
                            suzieq_schema_search,
                        )

                        schema = await suzieq_schema_search.ainvoke({"query": table})
                        available_tables = schema.get("tables", [])
                        if table in available_tables:
                            tool_result = await suzieq_query.ainvoke(tool_input)
                        else:
                            tool_result = {
                                "status": "SCHEMA_NOT_FOUND",
                                "table": table,
                                "message": f"Table '{table}' not present in discovered schema tables.",
                                "available_tables": available_tables,
                            }
                    except Exception as e:
                        tool_result = {
                            "status": "TOOL_ERROR",
                            "error": str(e),
                            "table": table,
                            "method": method,
                            "input": tool_input,
                        }

                if tool_result:
                    classified = self._classify_tool_result(tool_result)
                    # Failure statuses propagate directly
                    if classified["status"] in {
                        "SCHEMA_NOT_FOUND",
                        "NO_DATA_FOUND",
                        "DATA_NOT_RELEVANT",
                        "TOOL_ERROR",
                    }:
                        todo["status"] = "failed"
                        todo["result"] = (
                            f"⚠️ 批量任务失败: {classified['status']} table={classified['table']}"
                        )
                        completed_results[todo["id"]] = todo["result"]
                        return todo, [AIMessage(content=todo["result"])]

                    # 使用智能字段提取，避免截断关键诊断数据
                    data = tool_result.get("data", [])
                    tbl = classified.get("table", "unknown")
                    if isinstance(data, list) and data:
                        diagnostic_summary = self._extract_diagnostic_fields(data, tbl, max_records=10)
                    else:
                        diagnostic_summary = str(tool_result)[:400]
                    
                    # Human-friendly task completion message
                    table_name_cn = self._get_table_display_name(tbl)
                    todo["status"] = "completed"
                    todo["result"] = (
                        f"{tr('query_complete', table=table_name_cn, count=classified['count'])}\n{diagnostic_summary}"
                    )
                    messages.append(
                        AIMessage(
                            content=tr("task_complete_msg", task_id=todo['id'], table=table_name_cn, count=classified['count'])
                        )
                    )
                else:
                    # Fallback LLM path
                    prompt = prompt_manager.load_prompt(
                        category="workflows/deep_dive",
                        name="execute_todo",
                        task=task_text,
                        available_tools="suzieq_query, netconf_tool, search_openconfig_schema",
                    )
                    llm_resp = await self.llm.ainvoke(
                        [
                            SystemMessage(content=prompt),
                            HumanMessage(content=f"Execute task: {task_text}"),
                        ]
                    )
                    todo["status"] = "completed"
                    todo["result"] = llm_resp.content
                    messages.append(
                        AIMessage(content=f"Parallel task {todo['id']} completed via LLM fallback")
                    )

                completed_results[todo["id"]] = todo["result"]
                return todo, messages

            results = await asyncio.gather(
                *[_execute_single(t) for t in batch], return_exceptions=True
            )
            aggregated_messages: list[BaseMessage] = []
            for res in results:
                if isinstance(res, Exception):  # Defensive: unexpected batch error
                    aggregated_messages.append(AIMessage(content=f"批量执行出现未捕获异常: {res}"))
                else:
                    _todo, msgs = res
                    aggregated_messages.extend(msgs)

            # Decide next step message
            aggregated_messages.append(AIMessage(content=f"并行批次完成: {len(batch)} 个任务."))
            return {
                "todos": todos,
                "current_todo_id": batch[-1]["id"],
                "completed_results": completed_results,
                "messages": aggregated_messages,
                "user_approval": user_approval,  # Persist approval across iterations
            }

        # ------------------------------------------------------------------
        # Serial execution fallback (original logic) when 0 or 1 independent
        # ------------------------------------------------------------------
        next_todo: TodoItem | None = None
        for todo in todos:
            if todo["status"] == "pending":
                deps_ok = all(
                    any(t["id"] == dep_id and t["status"] in {"completed", "failed"} for t in todos)
                    for dep_id in todo["deps"]
                )
                if deps_ok or not todo["deps"]:
                    next_todo = todo
                    break

        if not next_todo:
            return {
                "messages": [AIMessage(content="All pending tasks processed.")],
                "user_approval": user_approval,
            }

        # Mark in-progress
        next_todo["status"] = "in-progress"
        task_text = next_todo["task"].strip()
        tool_result: dict | None = None
        mapping = self._map_task_to_table(task_text)
        tool_messages: list[BaseMessage] = []

        if mapping:
            table, method, extra_filters = mapping
            tool_input = {"table": table, "method": method, **extra_filters}
            try:
                # Local import to avoid global dependency issues
                from olav.tools.suzieq_parquet_tool import (  # type: ignore
                    suzieq_query,
                    suzieq_schema_search,
                )

                # Discover available tables; suzieq_schema_search returns {"tables": [...], "bgp": {...}, ...}
                schema = await suzieq_schema_search.ainvoke({"query": table})
                available_tables = schema.get("tables", [])

                if table in available_tables:
                    tool_result = await suzieq_query.ainvoke(tool_input)

                    # 方案2: 字段语义验证 - 检查返回字段是否与任务相关
                    if (
                        tool_result
                        and "columns" in tool_result
                        and tool_result.get("status") != "NO_DATA_FOUND"
                    ):
                        is_relevant = self._validate_field_relevance(
                            task_text=task_text,
                            returned_columns=tool_result["columns"],
                            queried_table=table,
                        )
                        if not is_relevant:
                            # Data returned but not relevant to task
                            tool_result = {
                                "status": "DATA_NOT_RELEVANT",
                                "table": table,
                                "returned_columns": tool_result["columns"],
                                "message": f"表 '{table}' 返回了数据，但字段与任务需求不匹配。",
                                "hint": f"任务关键词: {self._extract_task_keywords(task_text)}，返回字段: {tool_result['columns'][:5]}",
                                "suggestion": "可能需要使用 NETCONF 查询或重新规划任务。",
                            }
                else:
                    tool_result = {
                        "status": "SCHEMA_NOT_FOUND",
                        "table": table,
                        "message": f"Table '{table}' not present in discovered schema tables.",
                        "hint": "Use suzieq_schema_search with a broader query or verify poller collection.",
                        "available_tables": available_tables,
                    }
            except Exception as e:
                tool_result = {
                    "status": "TOOL_ERROR",
                    "error": str(e),
                    "table": table,
                    "method": method,
                    "input": tool_input,
                }

        if tool_result:
            classified = self._classify_tool_result(tool_result)
            summary = (
                f"TOOL_CALL table={classified['table']} status={classified['status']} "
                f"count={classified['count']}"
            )

            # CRITICAL: 防止 LLM 幻觉 - 在遇到错误状态时直接返回失败，不继续处理
            if classified["status"] in {
                "SCHEMA_NOT_FOUND",
                "NO_DATA_FOUND",
                "DATA_NOT_RELEVANT",
                "TOOL_ERROR",
            }:
                error_msg = (
                    f"⚠️ 任务执行失败: {classified['status']}\n"
                    f"表: {classified['table']}\n"
                    f"原因: {tool_result.get('message') or tool_result.get('error', '未知错误')}\n"
                    f"提示: {tool_result.get('hint', 'N/A')}\n"
                )

                # DATA_NOT_RELEVANT 需要额外说明
                if classified["status"] == "DATA_NOT_RELEVANT":
                    error_msg += (
                        f"\n⚠️ **数据语义不匹配**: 查询的表返回了数据，但字段与任务需求不相关。\n"
                        f"建议: {tool_result.get('suggestion', '重新规划任务或使用 NETCONF 直接查询')}\n"
                    )

                error_msg += (
                    "\n⛔ **严格禁止编造数据** - 无相关数据即报告失败，不推测或生成虚假结果。"
                )

                next_todo["status"] = "failed"
                next_todo["result"] = error_msg
                completed_results[next_todo["id"]] = error_msg

                return {
                    "todos": todos,
                    "current_todo_id": next_todo["id"],
                    "completed_results": completed_results,
                    "messages": [AIMessage(content=error_msg)],
                    "user_approval": user_approval,
                }

            # 成功状态：使用智能字段提取，避免截断关键诊断数据（如 state, reason 等）
            data = tool_result.get("data", [])
            table = classified.get("table", "unknown")
            table_name_cn = self._get_table_display_name(table)
            if isinstance(data, list) and data:
                diagnostic_summary = self._extract_diagnostic_fields(data, table)
            else:
                diagnostic_summary = str(tool_result)[:800]  # Fallback for non-list data
            result_text = f"{tr('query_complete', table=table_name_cn, count=classified['count'])}\n\n{diagnostic_summary}"
            tool_messages.append(
                AIMessage(
                    content=tr("task_complete_simple", table=table_name_cn, count=classified['count'])
                )
            )
        else:
            # Fallback to LLM execution strategy
            prompt = prompt_manager.load_prompt(
                category="workflows/deep_dive",
                name="execute_todo",
                task=task_text,
                available_tools="suzieq_query, netconf_tool, search_openconfig_schema",
            )
            messages = [
                SystemMessage(content=prompt),
                HumanMessage(content=f"Execute task: {task_text}"),
            ]
            llm_resp = await self.llm.ainvoke(messages)
            result_text = llm_resp.content

        # Complete todo (only if not already marked failed above)
        if next_todo["status"] != "failed":
            next_todo["status"] = "completed"
        next_todo["result"] = result_text

        # ------------------------------------------------------------------
        # Phase 2: External Evaluator integration (Schema-Aware dynamic)
        # ------------------------------------------------------------------
        try:
            if next_todo["status"] == "completed" and tool_result:
                from olav.evaluators.config_compliance import ConfigComplianceEvaluator

                evaluator = ConfigComplianceEvaluator()
                eval_result = await evaluator.evaluate(next_todo, tool_result)

                next_todo["evaluation_passed"] = eval_result.passed
                next_todo["evaluation_score"] = eval_result.score

                if not eval_result.passed:
                    next_todo["failure_reason"] = eval_result.feedback
                    # Reclassify status to failed and append evaluator feedback
                    next_todo["status"] = "failed"
                    appended = f"\n🔍 评估未通过: {eval_result.feedback}"
                    next_todo["result"] = (next_todo["result"] or "") + appended
        except Exception as eval_err:
            # Non-fatal – store failure_reason for visibility
            next_todo["evaluation_passed"] = False
            next_todo["evaluation_score"] = 0.0
            next_todo["failure_reason"] = f"Evaluator error: {eval_err}"

        completed_results[next_todo["id"]] = next_todo["result"]

        completion = AIMessage(content=f"Completed task {next_todo['id']}: {result_text[:600]}")
        return {
            "todos": todos,
            "current_todo_id": next_todo["id"],
            "completed_results": completed_results,
            "messages": [*tool_messages, completion],
            "user_approval": user_approval,
        }

    def _map_task_to_table(self, task: str) -> tuple[str, str, dict] | None:
        """Map natural language task to (table, method, filters) using ordered specificity.

        Order matters: more specific/general inventory tasks first, then protocol.
        Returns None if no mapping found (will trigger schema investigation).
        
        Method selection:
        - 'get': For detailed data queries (default for troubleshooting)
        - 'summarize': Only for explicit aggregation requests (统计, 汇总, 概览)
        """
        lower = task.lower()
        
        # Determine method based on task intent
        # Use 'summarize' only for explicit aggregation requests
        needs_summary = any(k in lower for k in ["统计", "汇总", "概览", "总数", "count", "summary", "overview"])
        method = "summarize" if needs_summary else "get"

        candidates: list[tuple[list[str], str]] = [
            # Inventory / device list
            (["设备列表", "所有设备", "审计设备", "device", "设备"], "device"),
            # Interfaces
            (["接口", "端口", "interface", "物理", "rx", "tx", "链路"], "interfaces"),
            # Routing / prefixes
            (["路由", "前缀", "routes", "lpm"], "routes"),
            # OSPF
            (["ospf"], "ospfIf"),
            # LLDP
            (["lldp"], "lldp"),
            # MAC
            (["mac", "二层"], "macs"),
            # BGP (put later to avoid greedy matching of '边界')
            (["bgp", "peer", "邻居", "边界", "ebgp", "ibgp"], "bgp"),
        ]
        for keywords, table in candidates:
            if any(k in lower for k in keywords):
                import re

                hosts = re.findall(r"\b([A-Za-z]{1,4}\d{1,2})\b", task)
                filters: dict[str, Any] = {}
                if hosts:
                    filters["hostname"] = hosts[0]
                return table, method, filters
        return None

    def _extract_diagnostic_fields(
        self, data: list[dict[str, Any]], table: str, max_records: int = 20
    ) -> str:
        """Extract key diagnostic fields from query results to prevent truncation of critical data.

        Instead of blindly truncating the full data dict (which loses important fields like 'state'),
        this method extracts only the most important fields for each table type.

        Args:
            data: List of records from suzieq_query
            table: Table name to determine which fields to extract
            max_records: Maximum number of records to include

        Returns:
            Formatted string with key diagnostic information
        """
        if not data:
            return "无数据记录"

        # Define key fields per table type (most important for diagnostics first)
        table_key_fields: dict[str, list[str]] = {
            "bgp": ["hostname", "peer", "state", "asn", "peerAsn", "afi", "safi", 
                    "reason", "notificnReason", "estdTime", "pfxRx", "pfxTx", "vrf"],
            "ospfIf": ["hostname", "ifname", "state", "area", "networkType", "cost", "passive"],
            "ospfNbr": ["hostname", "ifname", "nbrHostname", "state", "area", "nbrPriority"],
            "interfaces": ["hostname", "ifname", "state", "adminState", "speed", "mtu", "ipAddressList"],
            "routes": ["hostname", "vrf", "prefix", "nexthopIp", "protocol", "preference", "metric"],
            "device": ["hostname", "model", "version", "vendor", "uptime", "serialNumber"],
            "lldp": ["hostname", "ifname", "peerHostname", "peerIfname", "capability"],
            "macs": ["hostname", "vlan", "macaddr", "interface", "moveCount"],
        }
        
        # Human-readable field labels
        field_labels = {
            "hostname": "主机",
            "peer": "邻居",
            "state": "状态",
            "asn": "本地AS",
            "peerAsn": "邻居AS",
            "afi": "地址族",
            "safi": "子族",
            "reason": "原因",
            "notificnReason": "通知原因",
            "estdTime": "建立时间",
            "pfxRx": "收到前缀",
            "pfxTx": "发送前缀",
            "vrf": "VRF",
            "ifname": "接口",
            "adminState": "管理状态",
            "speed": "速率",
            "mtu": "MTU",
            "ipAddressList": "IP",
            "prefix": "前缀",
            "nexthopIp": "下一跳",
            "protocol": "协议",
            "preference": "优先级",
            "metric": "度量值",
            "model": "型号",
            "version": "版本",
            "vendor": "厂商",
            "uptime": "运行时间",
            "area": "区域",
            "cost": "开销",
            "peerHostname": "邻居主机",
            "peerIfname": "邻居接口",
        }

        # Get fields for this table, or use common fallback fields
        fields = table_key_fields.get(table.lower(), ["hostname", "state", "status"])

        # Build formatted output with better readability
        lines = []
        for i, record in enumerate(data[:max_records]):
            if not isinstance(record, dict):
                continue
            
            # Extract available key fields from this record
            field_values = []
            for field in fields:
                if field not in record:
                    continue
                value = record[field]
                # Skip empty/null values (handle numpy arrays specially)
                try:
                    import numpy as np
                    if isinstance(value, np.ndarray):
                        if value.size == 0:
                            continue
                        value = value.tolist()  # Convert to list for display
                    elif value in (None, "", [], {}):
                        continue
                except (ImportError, ValueError, TypeError):
                    if value in (None, "", [], {}):
                        continue
                
                # Format timestamp as readable date
                if field == "estdTime" and isinstance(value, (int, float)):
                    if value > 1e12:
                        from datetime import datetime
                        try:
                            value = datetime.fromtimestamp(value / 1000).strftime("%m-%d %H:%M")
                        except Exception:
                            pass
                    elif value == 0:
                        value = tr("timestamp_not_established")
                
                # Format state values with i18n
                if field == "state":
                    state_map = {
                        "Established": tr("state_established"),
                        "NotEstd": tr("state_not_established"), 
                        "up": tr("state_up"),
                        "down": tr("state_down"),
                    }
                    value = state_map.get(str(value), value)
                
                # Use translated label
                label = tr(f"field_{field}")
                if label == f"field_{field}":
                    # No translation found, use field_labels fallback or raw field name
                    label = field_labels.get(field, field)
                field_values.append(f"{label}: {value}")
            
            if field_values:
                # Format as bullet point with hostname highlighted
                hostname = record.get("hostname", f"{tr('record_placeholder')}{i+1}")
                host_label = tr("field_hostname")
                other_fields = [f for f in field_values if not f.startswith(f"{host_label}:")]
                lines.append(f"  • **{hostname}** → " + " | ".join(other_fields))

        if not lines:
            return tr("no_diagnostic_fields")

        # Add header with record count
        showing = min(len(data), max_records)
        if len(data) > max_records:
            header = tr("records_header_truncated", total=len(data), showing=showing)
        else:
            header = tr("records_header", count=len(data))
        return header + "\n" + "\n".join(lines)

    def _classify_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """Normalize tool result into status/count/table for summary lines."""
        status = "OK"
        table = result.get("table", "unknown")
        count = result.get("count")
        if count is None and isinstance(result.get("data"), list):
            count = len(result.get("data", []))

        # Priority 1: Explicit DATA_NOT_RELEVANT status (field validation failed)
        if result.get("status") == "DATA_NOT_RELEVANT":
            status = "DATA_NOT_RELEVANT"
        # Priority 2: Explicit error field (tool execution failed)
        elif "error" in result:
            error_msg = str(result["error"])
            # Check if error indicates unknown table (schema validation)
            if "Unknown table" in error_msg or "available_tables" in result:
                status = "SCHEMA_NOT_FOUND"
            else:
                status = "TOOL_ERROR"
        # Priority 3: Explicit schema not found status (from our validation)
        elif result.get("status") == "SCHEMA_NOT_FOUND":
            status = "SCHEMA_NOT_FOUND"
        # Priority 4: NO_DATA_FOUND sentinel in first data record
        elif isinstance(result.get("data"), list) and result["data"]:
            first = result["data"][0]
            if isinstance(first, dict) and first.get("status") == "NO_DATA_FOUND":
                status = "NO_DATA_FOUND"
        # Priority 5: Empty data list
        elif isinstance(result.get("data"), list) and len(result.get("data", [])) == 0:
            status = "NO_DATA_FOUND"

        return {"status": status, "table": table, "count": count if count is not None else 0}

    def _validate_field_relevance(
        self, task_text: str, returned_columns: list[str], queried_table: str
    ) -> bool:
        """Validate if returned columns are semantically relevant to task (方案2).

        Args:
            task_text: Original task description
            returned_columns: Field names returned from query
            queried_table: Table that was queried

        Returns:
            True if fields appear relevant, False otherwise
        """
        # Strategy: Be lenient - if the table matches the task intent, accept the data
        # The real validation should be in the final summary, not here
        
        # 1. If table name matches any task keyword, data is relevant
        task_keywords = self._extract_task_keywords(task_text)
        if queried_table.lower() in task_keywords:
            return True
        
        # 2. Mapping of tables to their core field groups
        table_core_fields = {
            "bgp": ["peer", "neighbor", "state", "afi", "safi", "asn", "pfx"],
            "ospf": ["area", "neighbor", "state", "cost", "dr"],
            "interfaces": ["ifname", "state", "admin", "speed", "mtu", "ip"],
            "routes": ["prefix", "nexthop", "protocol", "metric", "vrf"],
            "device": ["hostname", "model", "version", "vendor"],
            "lldp": ["neighbor", "port", "chassis"],
            "macs": ["mac", "vlan", "port", "interface"],
        }
        
        # 3. Check if returned columns contain any core fields for the queried table
        core_fields = table_core_fields.get(queried_table.lower(), [])
        columns_str = " ".join(returned_columns).lower()
        
        if any(field in columns_str for field in core_fields):
            return True

        # 4. Special case: device/interfaces are generic inventory, acceptable for most tasks
        if queried_table in {"device", "interfaces"}:
            return True
            
        # 5. If returned columns contain common network fields, accept
        common_network_fields = ["hostname", "namespace", "timestamp", "state", "status"]
        if any(field in columns_str for field in common_network_fields):
            return True

        # No semantic match - but only reject if we have very specific mismatches
        # e.g., asking for "mpls" but getting "mac" table
        return len(task_keywords) == 0  # If no keywords extracted, accept anything

    def _extract_task_keywords(self, task_text: str) -> list[str]:
        """Extract technical keywords from task description."""
        lower = task_text.lower()
        # Common network protocol/feature keywords
        keywords = [
            "mpls",
            "ldp",
            "rsvp",
            "bgp",
            "ospf",
            "eigrp",
            "isis",
            "vlan",
            "vxlan",
            "evpn",
            "interface",
            "route",
            "prefix",
            "neighbor",
            "peer",
            "session",
            "tunnel",
            "policy",
            "qos",
            "acl",
            "nat",
            "firewall",
            "vpn",
        ]
        return [kw for kw in keywords if kw in lower]

    async def should_continue(
        self, state: DeepDiveState
    ) -> Literal["execute_todo", "recursive_check"]:
        """Decide whether to continue executing todos or move to recursive check.

        Args:
            state: Current workflow state

        Returns:
            Next node to execute
        """
        todos = state["todos"]
        pending_count = sum(1 for t in todos if t["status"] == "pending")

        if pending_count > 0:
            return "execute_todo"
        return "recursive_check"

    async def recursive_check_node(self, state: DeepDiveState) -> dict:
        """Check if recursive deep dive is needed.

        Phase 3.4 Enhancement: Handles multiple failures in parallel, not just the first one.
        Creates focused sub-tasks for each failed todo (up to max_failures_per_recursion).

        Args:
            state: Current workflow state

        Returns:
            Updated state with potential new sub-todos for all failures
        """
        recursion_depth = state.get("recursion_depth", 0)
        max_depth = state.get("max_depth", 3)
        max_failures_per_recursion = (
            3  # Limit parallel failure investigation to avoid prompt explosion
        )

        # Depth guard
        if recursion_depth >= max_depth:
            return {
                "messages": [
                    AIMessage(
                        content=f"Max recursion depth ({max_depth}) reached. Moving to summary."
                    )
                ],
                "trigger_recursion": False,
            }

        todos = state.get("todos", [])
        failed_todos = [t for t in todos if t.get("status") == "failed"]

        if not failed_todos:
            return {
                "messages": [AIMessage(content="No deeper analysis needed.")],
                "trigger_recursion": False,
            }

        # PHASE 3.4: Handle multiple failures (not just first one)
        # Limit to top N failures to avoid overwhelming prompt/planning
        failures_to_analyze = failed_todos[:max_failures_per_recursion]

        # Build recursive prompt for ALL selected failures
        failure_summaries = []
        for failed in failures_to_analyze:
            parent_task_id = failed["id"]
            parent_task_text = failed["task"]
            parent_result = (failed.get("result") or "")[
                :400
            ]  # Truncate per failure to fit multiple
            parent_reason = failed.get("failure_reason", "Unknown")

            failure_summaries.append(
                f"  • 失败任务 {parent_task_id}: {parent_task_text}\n"
                f"    失败原因: {parent_reason}\n"
                f"    输出摘要: {parent_result}\n"
            )

        recursive_prompt = (
            f"递归深入分析: 检测到 {len(failures_to_analyze)} 个失败任务，需要生成更细粒度的子任务。\n\n"
            "失败任务列表:\n" + "\n".join(failure_summaries) + "\n\n"
            "请遵循要求: \n"
            f"1) 为每个失败任务生成 1-2 个更具体的子任务（总共 {len(failures_to_analyze) * 2} 个左右）。\n"
            "2) 子任务需更具体，例如聚焦某协议实例、邻居、接口或字段。\n"
            "3) 避免与父任务完全重复。\n"
            '4) 使用 JSON 输出: {\n  "todos": [ {"id": <int>, "task": <str>, "deps": [] } ]\n}。\n'
            "5) ID 从现有最大 ID + 1 开始递增。\n"
            "6) 在 task 文本中包含父任务引用: '(parent:<id>)'，例如 '检查 R1 BGP 配置 (parent:3)'。\n"
            "7) 如果某失败任务无法进一步细化，生成一个验证性任务，例如 '验证采集是否缺失 (parent:<id>)'。\n"
        )

        return {
            "messages": [HumanMessage(content=recursive_prompt)],
            "recursion_depth": recursion_depth + 1,
            "trigger_recursion": True,
        }

    async def should_recurse(
        self, state: DeepDiveState
    ) -> Literal["final_summary", "task_planning"]:
        """Decide whether to recurse or finalize.

        Args:
            state: Current workflow state

        Returns:
            Next node to execute
        """
        if state.get("trigger_recursion"):
            return "task_planning"
        return "final_summary"

    async def final_summary_node(self, state: DeepDiveState) -> dict:
        """Generate final summary report from all completed todos.

        Args:
            state: Current workflow state

        Returns:
            Updated state with final summary message
        """
        import logging

        logger = logging.getLogger(__name__)

        todos = state["todos"]
        completed_results = state.get("completed_results", {})
        messages = state.get("messages", [])

        # Extract original user query from first HumanMessage
        user_query = ""
        for msg in messages:
            if isinstance(msg, HumanMessage):
                user_query = msg.content
                break

        # Load summary prompt
        prompt = prompt_manager.load_prompt(
            category="workflows/deep_dive",
            name="final_summary",
            todos=str(todos),
            results=str(completed_results),
        )

        llm_messages = [SystemMessage(content=prompt)]
        response = await self.llm.ainvoke(llm_messages)
        final_report = response.content

        # Count successful/failed tasks for evaluation
        successful_tasks = sum(1 for t in todos if t.get("status") == "completed")
        failed_tasks = sum(1 for t in todos if t.get("status") == "failed")
        total_tasks = len(todos)

        # Save troubleshooting report to episodic memory (Agentic RAG)
        # Only save if Deep Dive memory is enabled in settings
        if settings.enable_deep_dive_memory and successful_tasks > 0 and user_query:
            try:
                memory_writer = get_memory_writer()
                await memory_writer.memory.store_episodic_memory(
                    intent=user_query,
                    xpath=f"deep_dive:{successful_tasks}/{total_tasks} tasks",
                    success=failed_tasks == 0,  # Fully successful if no failures
                    context={
                        "tool_used": "deep_dive_workflow",
                        "device_type": "multi-device",
                        "strategy_used": "deep_dive",
                        "execution_time_ms": 0,  # Not tracked at workflow level
                        "parameters": {
                            "todos_count": total_tasks,
                            "successful": successful_tasks,
                            "failed": failed_tasks,
                        },
                        "result_summary": final_report[:500],  # Truncate for storage
                        "full_report_available": len(final_report) > 500,
                    },
                )
                logger.info(
                    f"✓ Saved Deep Dive report to episodic memory: {user_query[:50]}..."
                )
            except Exception as e:
                # Don't fail workflow on memory save error
                logger.warning(f"Failed to save Deep Dive report to memory: {e}")
        elif not settings.enable_deep_dive_memory:
            logger.debug("Deep Dive memory disabled, skipping report save")

        return {
            "messages": [AIMessage(content=final_report)],
        }

    def build_graph(self, checkpointer: AsyncPostgresSaver) -> StateGraph:
        """Build Deep Dive Workflow graph with Funnel Debugging methodology.

        NEW Flow (Funnel Debugging):
        1. topology_analysis → Identify affected devices and scope
        2. funnel_planning → Generate OSI layer-based diagnosis plan
        3. [INTERRUPT] → Wait for user approval
        4. macro_scan → Execute SuzieQ checks per layer (loop)
        5. evaluate_findings → Decide if more scanning needed
        6. root_cause_summary → Generate final report

        Args:
            checkpointer: PostgreSQL checkpointer for state persistence

        Returns:
            Compiled StateGraph with HITL interrupts
        """
        workflow = StateGraph(DeepDiveState)

        # Add Funnel Debugging nodes
        workflow.add_node("topology_analysis", self.topology_analysis_node)
        workflow.add_node("funnel_planning", self.funnel_planning_node)
        workflow.add_node("macro_scan", self.macro_scan_node)
        workflow.add_node("evaluate_findings", self.evaluate_findings_node)
        workflow.add_node("root_cause_summary", self.root_cause_summary_node)

        # Define edges for Funnel Debugging flow
        workflow.set_entry_point("topology_analysis")
        workflow.add_edge("topology_analysis", "funnel_planning")
        workflow.add_edge("funnel_planning", "macro_scan")
        workflow.add_edge("macro_scan", "evaluate_findings")
        
        workflow.add_conditional_edges(
            "evaluate_findings",
            self.should_continue_funnel,
            {
                "macro_scan": "macro_scan",  # Continue to next phase
                "root_cause_summary": "root_cause_summary",  # All phases done
            },
        )
        
        workflow.add_edge("root_cause_summary", END)

        # Compile with checkpointer
        # HITL is handled by interrupt() in macro_scan_node
        return workflow.compile(
            checkpointer=checkpointer,
        )

    def build_legacy_graph(self, checkpointer: AsyncPostgresSaver) -> StateGraph:
        """Build legacy Deep Dive graph (task planning style).
        
        Use this for backward compatibility with existing audit workflows.

        Flow:
        1. task_planning → Generate todos
        2. schema_investigation → Validate feasibility
        3. execute_todo → Execute tasks
        4. recursive_check → Deeper analysis if needed
        5. final_summary → Generate report
        """
        workflow = StateGraph(DeepDiveState)

        # Add nodes
        workflow.add_node("task_planning", self.task_planning_node)
        workflow.add_node("schema_investigation", self.schema_investigation_node)
        workflow.add_node("execute_todo", self.execute_todo_node)
        workflow.add_node("recursive_check", self.recursive_check_node)
        workflow.add_node("final_summary", self.final_summary_node)

        # Define edges
        workflow.set_entry_point("task_planning")
        workflow.add_edge("task_planning", "schema_investigation")
        workflow.add_edge("schema_investigation", "execute_todo")

        workflow.add_conditional_edges(
            "execute_todo",
            self.should_continue,
            {
                "execute_todo": "execute_todo",
                "recursive_check": "recursive_check",
            },
        )
        workflow.add_conditional_edges(
            "recursive_check",
            self.should_recurse,
            {
                "task_planning": "task_planning",
                "final_summary": "final_summary",
            },
        )
        workflow.add_edge("final_summary", END)

        return workflow.compile(
            checkpointer=checkpointer,
        )
