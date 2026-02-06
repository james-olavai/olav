"""OLAV Agents Package - Unified Core.

This package contains the core agents of the v0.10.0 architecture:
1. QueryAgent: The query engine with dynamic tool registration (Skill-Centric).
2. Analyzer: The complex diagnosis expert (Data Fusion).
3. Orchestrator: The ReAct-based Meta-Agent for multi-specialist coordination.
4. TextfsmAgent: The automation engineer (Template Generation).
"""

from olav.agents.analyzer import analyze_network
from olav.agents.orchestrator import (
    orchestrate_query,
    create_planning_orchestrator,
    create_collaborative_orchestrator,
)
from olav.agents.query_agent import QueryAgent
from olav.agents.textfsm_agent import create_textfsm_agent_graph

__all__ = [
    "analyze_network",
    "orchestrate_query",
    "create_planning_orchestrator",
    "create_collaborative_orchestrator",
    "QueryAgent",
    "create_textfsm_agent_graph",
]
from olav.agents.tool_loader import (
    get_tool_whitelist,
    load_tools_for_agent,
    validate_tool_access,
)

# Script Engine imports for Skill-as-a-Tool capability
try:
    from olav.core.script_engine import (
        ScriptExecutor,  # noqa: F401
        ScriptLoader,  # noqa: F401
        ScriptMetadata,  # noqa: F401
        create_script_tool,  # noqa: F401
        get_script_tools,  # noqa: F401
        load_script_tool,  # noqa: F401
        parse_skill_file,  # noqa: F401
    )

    _script_engine_available = True
except ImportError:
    _script_engine_available = False

__all__ = [
    # Core Agents
    "QueryAgent",
    "analyze_network",
    "create_coder_graph",
    "OrchestratorState",
    "create_orchestrator_graph",
    "orchestrate_query",
    "create_planning_orchestrator",
    # Tool Loader
    "load_tools_for_agent",
    "get_tool_whitelist",
    "validate_tool_access",
]

# Script Engine exports (if available)
if _script_engine_available:
    __all__.extend(
        [
            "ScriptExecutor",
            "ScriptLoader",
            "ScriptMetadata",
            "create_script_tool",
            "get_script_tools",
            "load_script_tool",
            "parse_skill_file",
        ]
    )
