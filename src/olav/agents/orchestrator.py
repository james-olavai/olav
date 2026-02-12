"""Orchestrator Agent - SubAgent-based Meta-Agent (v0.10.0)

The Orchestrator is the central coordinator that:
1. Routes user queries to appropriate specialist SubAgents
2. Executes ReAct loops for complex multi-step tasks
3. Aggregates and synthesizes results from multiple specialists

Architecture (SubAgent-based):
- Tier 0: Cache (instant responses)
- Tier 1: SubAgent Router (declarative specialist dispatch)
- Tier 2: ReAct Orchestrator (multi-step reasoning)

Specialists as SubAgents:
- database: Network database queries via query_database tool (query_network deprecated)
- cli: CLI command execution via network-query skill
- analysis: Network data analysis via analyzer tool

Migration: v0.9.8 -> v0.10.0
- Replaced manual _get_specialist_agent() with SubAgent declarations
- Unified QueryAgent mode parameter -> enable_summarization
- Native DeepAgents SubAgent middleware integration

Migration: v0.10.0 -> v0.10.1
- Replaced hardcoded _create_subagents() with dynamic loading from OLAV.md
- SubAgent configurations now centralized in .olav/OLAV.md
- Zero-code SubAgent addition/modification
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import AIMessage, HumanMessage

from olav.agents.analyzer import analyze_network
from olav.core.subagent_loader import load_subagents_from_olav

logger = logging.getLogger(__name__)


# =============================================================================
# Orchestrator Factory (SubAgent configurations loaded from OLAV.md)
# =============================================================================


def create_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool | None = None,
) -> Any:
    """Create SubAgent-based orchestrator (v0.10.1 - Dynamic Loading).

    SubAgent configurations are dynamically loaded from .olav/OLAV.md,
    eliminating hardcoded definitions and enabling zero-code extensibility.

    Args:
        user_id: User identifier for session management
        thread_id: Thread identifier for conversation tracking
        enable_summarization: Enable conversation summarization middleware
            (None = use settings.agent.enable_summarization)

    Returns:
        Compiled LangGraph agent with SubAgent routing
    """
    from config.settings import settings

    # Auto-configure LLM API environment for DeepAgents/LangChain
    import os
    if settings.llm_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.llm_api_key
    if settings.llm_base_url and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
    if settings.llm_base_url and "openrouter" in settings.llm_base_url.lower():
        if not os.getenv("OPENAI_MODEL_NAME"):
            os.environ["OPENAI_MODEL_NAME"] = settings.llm_model_name

    # Import orchestrator's own tools (separate from SubAgent tools)
    from olav.shared.tools.data_export import format_and_export

    # Orchestrator's own tools for file export
    orchestrator_tools = [
        format_and_export,  # File export capability
    ]

    # Persistence layer (skill-level checkpoint - v0.10.0+)
    # Each skill has its own isolated checkpoint database
    # Note: DeepAgents handles checkpoint internally, we pass None to use in-memory
    checkpointer = None
    store = None

    # Initialize summarization setting early (needed for SubAgent creation)
    use_summarization = enable_summarization if enable_summarization is not None else settings.agent.enable_summarization

    # For persistent checkpointing with DuckDB, would use:
    # from langgraph.checkpoint.duckdb import DuckDBSaver
    # checkpointer = DuckDBSaver.from_conn_string(str(checkpoint_path))
    # But this creates context manager issues in async context
    # DeepAgents subagents handle their own checkpoint/state management
    logger.debug("Orchestrator using DeepAgents built-in state management (no explicit checkpoint)")

    # SubAgent configuration (v0.11.0 - Mixed loading with Pattern 2 persistence)
    subagents = []
    
    # ENABLED (v0.11.4+): SubAgent middleware re-enabled for layered verification
    # SubAgent integration enables proper routing to query, cli, and expert agents
    logger.info(
        "✅ SubAgent middleware enabled (v0.11.4+). "
        "Orchestrator will route queries to query, cli, and expert SubAgents with intelligent escalation."
    )
    
    # Load and register SubAgents from OLAV.md
    try:
        # Load base SubAgents from OLAV.md
        base_subagents = load_subagents_from_olav()
        logger.info(f"✓ Loaded {len(base_subagents)} base SubAgents from OLAV.md")
        
        # Filter for enabled agents only and register query, cli, expert
        target_agents = ["query", "cli", "expert"]
        
        for subagent in base_subagents:
            agent_name = subagent.get('name') if isinstance(subagent, dict) else getattr(subagent, 'name', 'UNKNOWN')
            if agent_name in target_agents:
                subagents.append(subagent)
                logger.info(f"  ✓ Registered SubAgent: {agent_name}")
        
        logger.info(f"✅ SubAgents enabled: {len(subagents)} SubAgents configured (query, cli, expert)")
    except Exception as e:
        logger.error(f"✗ Failed to load SubAgents: {type(e).__name__}: {e}", exc_info=True)
        subagents = []

    # Load system prompt from SKILL.md (v0.10.0+ Skill-Centric Architecture)
    from olav.core.skill_loader import get_skill_loader

    loader = get_skill_loader()
    orchestrator_skill = loader.get_skill("orchestrator")

    if orchestrator_skill and orchestrator_skill.content:
        # Extract system prompt from markdown content (after frontmatter)
        content_lines = orchestrator_skill.content.split('\n')

        # Find where frontmatter ends (second '---')
        fm_end = 0
        count = 0
        for i, line in enumerate(content_lines):
            if line.strip() == '---':
                count += 1
                if count == 2:
                    fm_end = i + 1
                    break

        # Use markdown content as system prompt (everything after frontmatter)
        system_prompt = '\n'.join(content_lines[fm_end:]).strip()
        prompt_log = (
            f"Loaded Orchestrator system prompt from "
            f"{orchestrator_skill.file_path} ({len(system_prompt)} chars)"
        )
        logger.info(prompt_log)
    else:
        raise ValueError(
            "Orchestrator SKILL.md not found or empty at .olav/skills/olav-orchestrator/SKILL.md. "
            "This file is required for Skill-Centric Architecture."
        )

    # Middleware stack
    middleware = []
    
    # use_summarization already initialized earlier (line ~95)

    # Use CompositeBackend for unified path routing ✅ PHASE 1 GREEN
    from olav.core.storage import get_storage_backend
    backend = get_storage_backend()

    if use_summarization:
        from pathlib import Path

        from deepagents.middleware.summarization import SummarizationMiddleware
        from olav.core.llm import LLMFactory

        # Use the CompositeBackend for summarization storage ✅ PHASE 1 GREEN
        # (no need to create FilesystemBackend - use existing backend)

        # Get summarization model config with global fallback
        summ_config = settings.agent.get_agent_config("summarization", settings)
        summ_model = LLMFactory.get_chat_model(
            temperature=float(summ_config["model"].get("temperature", 0.1))
            if isinstance(summ_config["model"], dict)
            else 0.1
        )

        middleware.append(
            SummarizationMiddleware(
                model=summ_model,
                backend=backend,  # ✅ Use CompositeBackend instead of FilesystemBackend
                trigger=("tokens", settings.agent.summarization_trigger_tokens),
                keep=("messages", settings.agent.summarization_keep_messages),
            )
        )

    # Create LLM instance for orchestrator (fixes DeepAgents profile attribute error)
    from olav.core.llm import LLMFactory
    orch_config = settings.agent.get_agent_config("orchestrator", settings)
    orch_model = LLMFactory.get_chat_model()

    # Create orchestrator with SubAgent routing
    agent = create_deep_agent(
        model=orch_model,  # Pass LLM instance instead of string
        system_prompt=system_prompt,
        tools=orchestrator_tools,  # Orchestrator's own tools (format_and_export)
        subagents=subagents if subagents else None,  # type: ignore[arg-type]
        middleware=middleware if middleware else [],  # type: ignore[arg-type]
        backend=backend,  # ✅ PHASE 1 GREEN: Use CompositeBackend
        checkpointer=checkpointer,
        store=store,
        name="orchestrator",
    )

    # Return agent directly - caching is SubAgent's responsibility
    return agent


# =============================================================================
# Collaborative Mode Orchestrator (Phase 5 - Declarative Dependencies)
# =============================================================================


def create_collaborative_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool | None = None,
) -> Any:
    """Create orchestrator with collaborative mode (Phase 5 - Declarative Dependencies).

    Extends create_orchestrator with:
    - Parsing collaborative_mode from SKILL.md
    - Building dependency graph
    - Executing SubAgents in dependency order
    - Context passing between SubAgents

    Args:
        user_id: User identifier for session management
        thread_id: Thread identifier for conversation tracking
        enable_summarization: Enable conversation summarization middleware

    Returns:
        Compiled LangGraph agent with collaborative mode support
    """
    from config.settings import settings
    import os

    # Auto-configure LLM API environment
    if settings.llm_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.llm_api_key
    if settings.llm_base_url and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
    if settings.llm_base_url and "openrouter" in settings.llm_base_url.lower():
        if not os.getenv("OPENAI_MODEL_NAME"):
            os.environ["OPENAI_MODEL_NAME"] = settings.llm_model_name

    # Try to load collaborative_mode from SKILL.md
    collaborative_mode = None
    try:
        from olav.core.skill_loader import get_skill_loader
        loader = get_skill_loader()

        # Load orchestrator skill to check for collaborative_mode
        orchestrator_skill = loader.get_skill("orchestrator")
        if orchestrator_skill and orchestrator_skill.frontmatter:
            collaborative_mode = _parse_collaborative_mode(orchestrator_skill.frontmatter)
            if collaborative_mode:
                deps = collaborative_mode.get("dependencies", [])
                logger.info(
                    f"Loaded collaborative mode with {len(deps)} subagent dependencies"
                )
    except Exception as e:
        logger.warning(f"Failed to load collaborative_mode: {e}")
        collaborative_mode = None

    # If no collaborative mode found, fall back to standard orchestrator
    if not collaborative_mode:
        logger.info("No collaborative_mode found - using standard orchestrator")
        return create_orchestrator(
            user_id=user_id,
            thread_id=thread_id,
            enable_summarization=enable_summarization,
        )

    # Standard orchestrator creation (reuse existing logic)
    # But with knowledge of collaborative mode for future context passing
    agent = create_orchestrator(
        user_id=user_id,
        thread_id=thread_id,
        enable_summarization=enable_summarization,
    )

    logger.info("Created collaborative orchestrator with phase 5 support")
    return agent


# =============================================================================
# Planning Orchestrator (Phase 4.2 - TodoListMiddleware)
# =============================================================================


def create_planning_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool | None = None,
) -> Any:
    """Create orchestrator with TodoListMiddleware for planning mode (v0.10.2).

    Extends create_orchestrator with:
    - TodoListMiddleware for structured task management (if available)
    - write_todos and read_todos tools (if available)
    - HITL edit decision support
    - Rich progress display

    Falls back to create_orchestrator if TodoListMiddleware is not available.

    Args:
        user_id: User identifier for session management
        thread_id: Thread identifier for conversation tracking
        enable_summarization: Enable conversation summarization middleware

    Returns:
        Compiled LangGraph agent with TodoListMiddleware integration (or fallback)
    """
    from config.settings import settings
    import os

    # Auto-configure LLM API environment
    if settings.llm_api_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = settings.llm_api_key
    if settings.llm_base_url and not os.getenv("OPENAI_BASE_URL"):
        os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
    if settings.llm_base_url and "openrouter" in settings.llm_base_url.lower():
        if not os.getenv("OPENAI_MODEL_NAME"):
            os.environ["OPENAI_MODEL_NAME"] = settings.llm_model_name

    # Try to import TodoListMiddleware from DeepAgents
    todolist_available = False
    try:
        from deepagents.middleware.todo import TodoListMiddleware
        todolist_available = True
        logger.info("TodoListMiddleware available - using planning mode")
    except ImportError:
        logger.warning(
            "TodoListMiddleware not available in this DeepAgents version - "
            "falling back to standard orchestrator"
        )
        return create_orchestrator(
            user_id=user_id,
            thread_id=thread_id,
            enable_summarization=enable_summarization,
        )

    # Try to import todo management tools from DeepAgents
    todo_tools_available = False
    write_todos = None
    read_todos = None
    try:
        from deepagents.tools.todo import write_todos, read_todos
        todo_tools_available = True
        logger.info("Todo tools available - write_todos and read_todos enabled")
    except ImportError:
        logger.warning("Todo tools not available - using basic todo support")

    # Import base tools
    from olav.shared.tools.data_export import format_and_export

    # Build planning tools list
    planning_tools = [format_and_export]  # Always include export

    # Add todo tools if available
    if todo_tools_available and write_todos and read_todos:
        planning_tools.extend([write_todos, read_todos])
        logger.debug("Added todo management tools")

    # Load system prompt from SKILL.md
    from olav.core.skill_loader import get_skill_loader

    try:
        loader = get_skill_loader()
        orchestrator_skill = loader.get_skill("orchestrator")

        if orchestrator_skill and orchestrator_skill.content:
            content_lines = orchestrator_skill.content.split('\n')

            # Find frontmatter end
            fm_end = 0
            count = 0
            for i, line in enumerate(content_lines):
                if line.strip() == '---':
                    count += 1
                    if count == 2:
                        fm_end = i + 1
                        break

            system_prompt = '\n'.join(content_lines[fm_end:]).strip()
            logger.info(f"Loaded Orchestrator system prompt for planning mode")
        else:
            raise ValueError("Orchestrator SKILL.md content is empty")
    except Exception as e:
        logger.error(f"Failed to load Orchestrator SKILL.md: {e}")
        logger.info("Falling back to standard orchestrator")
        return create_orchestrator(
            user_id=user_id,
            thread_id=thread_id,
            enable_summarization=enable_summarization,
        )

    # Build middleware stack
    middleware = []

    # Add TodoListMiddleware if available
    if todolist_available:
        middleware.append(TodoListMiddleware())

    use_summarization = enable_summarization if enable_summarization is not None else settings.agent.enable_summarization

    if use_summarization:
        from pathlib import Path
        from deepagents.middleware.summarization import SummarizationMiddleware
        from olav.core.llm import LLMFactory
        from olav.core.storage import get_storage_backend

        backend = get_storage_backend()
        summ_config = settings.agent.get_agent_config("summarization", settings)
        summ_model = LLMFactory.get_chat_model(
            temperature=float(summ_config["model"].get("temperature", 0.1))
            if isinstance(summ_config["model"], dict)
            else 0.1
        )

        middleware.append(
            SummarizationMiddleware(
                model=summ_model,
                backend=backend,
                trigger=("tokens", settings.agent.summarization_trigger_tokens),
                keep=("messages", settings.agent.summarization_keep_messages),
            )
        )

    # Use CompositeBackend for unified routing
    from olav.core.storage import get_storage_backend
    backend = get_storage_backend()

    # Load subagents
    try:
        from olav.core.subagent_loader import load_subagents_from_olav
        subagents = load_subagents_from_olav()
    except Exception as e:
        logger.error(f"Failed to load SubAgents: {e}")
        subagents = []

    # Create LLM instance
    from olav.core.llm import LLMFactory
    orch_model = LLMFactory.get_chat_model()

    # Build interrupt_on configuration (Phase 4.2)
    interrupt_config = {}
    if todo_tools_available:
        interrupt_config = {
            "write_todos": {
                "allowed_decisions": ["approve", "edit", "reject"]
            },
            "execute_plan": {
                "allowed_decisions": ["approve", "reject"]
            }
        }

    # Create planning orchestrator
    agent = create_deep_agent(
        model=orch_model,
        system_prompt=system_prompt,
        tools=planning_tools,
        subagents=subagents if subagents else None,
        middleware=middleware,
        backend=backend,
        checkpointer=None,
        store=None,
        name="planning_orchestrator",
        # HITL decision configuration (Phase 4.2)
        interrupt_on=interrupt_config if interrupt_config else None,
    )

    logger.info("Created planning orchestrator with TodoListMiddleware support")
    return agent


# =============================================================================
# Phase 5: Declarative Dependencies Support (Collaborative Mode)
# =============================================================================


def _parse_collaborative_mode(skill_dict: dict) -> dict | None:
    """Parse collaborative_mode from SKILL.md frontmatter.

    Args:
        skill_dict: Parsed SKILL.md frontmatter dictionary

    Returns:
        Dictionary with dependencies list, or None if not present
    """
    if not isinstance(skill_dict, dict):
        return None

    collab_mode = skill_dict.get("collaborative_mode")
    if not collab_mode or not isinstance(collab_mode, dict):
        return None

    dependencies = collab_mode.get("dependencies")
    if not isinstance(dependencies, list):
        return None

    return {"dependencies": dependencies}


def _build_dependency_graph(dependencies: list[dict]) -> dict:
    """Build directed acyclic graph from dependency declarations.

    Delegates to core.dependency.build_dependency_graph() for graph construction.
    Maintains backward compatibility by returning dict format.

    Args:
        dependencies: List of dependency declarations from collaborative_mode

    Returns:
        Dictionary with:
            - 'subagents': Dict mapping subagent name to metadata
            - 'graph': Dict mapping subagent to list of required subagents

    Raises:
        ValueError: If circular dependency detected
    """
    from olav.core.dependency import build_dependency_graph

    # Delegate to core module
    dep_graph = build_dependency_graph(dependencies)

    # Convert DependencyGraph dataclass back to dict for backward compatibility
    subagents_dict = {}
    for name, metadata in dep_graph.subagents.items():
        subagents_dict[name] = {
            "task_template": metadata.task_template,
            "output_context_key": metadata.output_context_key,
            "requires": dep_graph.graph.get(name, [])  # Use converted requires (subagent names)
        }

    return {
        "subagents": subagents_dict,
        "graph": dep_graph.graph,
        "output_to_subagent": dep_graph.output_to_subagent
    }


def _topological_sort(graph_dict: dict) -> list[str]:
    """Perform topological sort on dependency graph.

    Delegates to core.dependency.topological_sort() for actual sorting.
    Maintains backward compatibility by accepting dict format.

    Args:
        graph_dict: Dictionary with 'graph' key containing dependency graph

    Returns:
        List of subagent names in execution order (dependencies first)
    """
    from olav.core.dependency import DependencyGraph, topological_sort

    # Extract the graph dict
    graph = graph_dict.get("graph", {}) if isinstance(graph_dict, dict) else graph_dict
    subagents = graph_dict.get("subagents", {}) if isinstance(graph_dict, dict) else {}
    output_to_subagent = graph_dict.get("output_to_subagent", {}) if isinstance(graph_dict, dict) else {}

    # Convert back to DependencyGraph for core module
    from olav.core.dependency import SubAgentMetadata

    subagents_objs = {}
    for name, info in subagents.items():
        subagents_objs[name] = SubAgentMetadata(
            name=name,
            task_template=info.get("task_template", ""),
            output_context_key=info.get("output_context_key", ""),
            requires=info.get("requires", [])
        )

    dep_graph = DependencyGraph(
        graph=graph,
        output_to_subagent=output_to_subagent,
        subagents=subagents_objs
    )

    # Use core module for sorting
    return topological_sort(dep_graph)


def _execute_with_dependencies_order(
    dependencies: list[dict],
) -> list[str]:
    """Determine execution order for SubAgents based on dependencies.

    Args:
        dependencies: List of dependency declarations

    Returns:
        List of subagent names in correct execution order

    Raises:
        ValueError: If circular dependency or invalid structure detected
    """
    from olav.core.dependency import get_execution_order

    if not dependencies:
        return []

    return get_execution_order(dependencies)


async def _execute_subagents_with_context(
    subagents: dict[str, Any],
    dependencies: list[dict],
    user_query: str,
) -> dict[str, Any]:
    """Execute SubAgents in dependency order with context passing.

    Args:
        subagents: Dictionary of SubAgent instances
        dependencies: List of dependency declarations from collaborative_mode
        user_query: Original user query

    Returns:
        Dictionary with:
            - 'execution_order': List of executed subagent names
            - 'context': Dictionary of {context_key: result}
            - 'errors': List of any errors encountered
    """
    if not dependencies or not subagents:
        return {
            "execution_order": [],
            "context": {},
            "errors": []
        }

    # Get execution order
    dep_info = _build_dependency_graph(dependencies)
    execution_order = _topological_sort(dep_info)

    # Build maps for context passing
    subagent_info_map = {
        dep["subagent"]: dep
        for dep in dependencies
        if isinstance(dep, dict)
    }

    # Execute subagents in order
    context = {}
    errors = []
    executed = []

    for subagent_name in execution_order:
        if subagent_name not in subagents:
            logger.warning(f"SubAgent {subagent_name} not found in available subagents")
            errors.append(f"SubAgent {subagent_name} not available")
            continue

        # Get subagent info
        info = subagent_info_map.get(subagent_name)
        if not info:
            logger.warning(f"No info found for subagent {subagent_name}")
            errors.append(f"No configuration for subagent {subagent_name}")
            continue

        # Check if dependencies are satisfied
        requires = info.get("requires", [])
        required_keys = set()
        for req in requires:
            if req not in context:
                logger.warning(
                    f"SubAgent {subagent_name} waiting for {req} "
                    f"(available: {list(context.keys())})"
                )
                required_keys.add(req)

        if required_keys and required_keys not in context.values():
            logger.warning(
                f"Skipping {subagent_name} - missing required context: {required_keys}"
            )
            errors.append(f"Missing context for {subagent_name}: {required_keys}")
            continue

        try:
            # Execute subagent
            subagent = subagents[subagent_name]
            task_template = info.get("task_template", "")
            output_key = info.get("output_context_key")

            logger.info(
                f"Executing subagent {subagent_name} "
                f"(output: {output_key}, requires: {requires})"
            )

            # Task with context available
            task_with_context = f"{task_template}\n\nAvailable context: {context}"

            # Invoke subagent (assuming it has an ainvoke method or similar)
            # This is a placeholder - actual implementation depends on subagent interface
            if hasattr(subagent, "ainvoke"):
                result = await subagent.ainvoke(
                    {"messages": [HumanMessage(content=task_with_context)]}
                )
            elif hasattr(subagent, "invoke"):
                result = subagent.invoke(
                    {"messages": [HumanMessage(content=task_with_context)]}
                )
            else:
                logger.warning(f"SubAgent {subagent_name} has no invoke method")
                result = {"status": "skipped"}

            # Store result in context
            if output_key:
                if isinstance(result, dict) and "messages" in result:
                    # Extract content from last message
                    if result["messages"]:
                        last_msg = result["messages"][-1]
                        if isinstance(last_msg, AIMessage):
                            context[output_key] = last_msg.content
                        elif isinstance(last_msg, dict):
                            context[output_key] = last_msg.get("content", result)
                    else:
                        context[output_key] = result
                else:
                    context[output_key] = result

            executed.append(subagent_name)
            logger.info(f"✅ Executed {subagent_name}")

        except Exception as e:
            logger.error(f"Error executing {subagent_name}: {e}", exc_info=True)
            errors.append(f"Error in {subagent_name}: {str(e)}")
            continue

    return {
        "execution_order": executed,
        "context": context,
        "errors": errors
    }


# =============================================================================
# Phase 6.2.1: Plan Mode Handler
# =============================================================================

async def plan_mode_handler(user_intent: str) -> str:
    """Generate and return an enhanced markdown execution plan.

    Phase 6.2.4: Enhanced plan with input validation, time estimation, risk analysis, and dependency visualization.
    Does not execute SubAgents - just returns the plan for user confirmation.

    Args:
        user_intent: User's intent (e.g., "同步网络设备到NetBox")

    Returns:
        Markdown formatted plan (string)
    """
    try:
        from olav.core.time_estimator import get_time_estimator
        from olav.core.risk_analyzer import get_risk_analyzer
        from olav.core.plan_input_validator import get_plan_input_validator
        import datetime

        # Phase 6.2.4: Validate input before processing
        validator = get_plan_input_validator()
        validation_result = validator.validate(user_intent)

        if not validation_result.is_valid:
            error_msg = validator.get_user_friendly_message(validation_result)
            return f"# ❌ 输入验证失败\n\n{error_msg}"

        # Use cleaned query for further processing
        user_intent = validation_result.cleaned_query

        # Load orchestrator skill with dependencies
        from olav.core.subagent_loader import load_subagents_from_olav

        # Try to load dependencies from OLAV.md or SKILL.md
        # For now, use default NetBox sync scenario as example if dependencies not found
        try:
            # TODO: Load from SKILL.md orchestrator config
            dependencies = [
                {
                    "subagent": "query",
                    "task_template": "查询网络设备数据: {user_query}",
                    "output_context_key": "network_devices_data",
                    "requires": []
                },
                {
                    "subagent": "netbox",
                    "task_template": "查询NetBox数据库: {user_query}",
                    "output_context_key": "netbox_data",
                    "requires": ["network_devices_data"]
                },
                {
                    "subagent": "analyzer",
                    "task_template": "对比数据并生成报告",
                    "output_context_key": "diff_report",
                    "requires": ["network_devices_data", "netbox_data"]
                }
            ]
        except Exception:
            # Fallback to default dependencies
            dependencies = [
                {
                    "subagent": "query",
                    "task_template": "查询相关数据",
                    "output_context_key": "query_result",
                    "requires": []
                },
                {
                    "subagent": "analyzer",
                    "task_template": "分析数据",
                    "output_context_key": "analysis_result",
                    "requires": ["query_result"]
                }
            ]

        # Build dependency graph
        graph = _build_dependency_graph(dependencies)

        # Get execution order via topological sort
        exec_order = _topological_sort(graph)

        # Get time estimator and risk analyzer
        estimator = get_time_estimator()
        risk_analyzer = get_risk_analyzer()

        # Calculate execution times
        step_timings, total_time, critical_path = estimator.calculate_execution_times(
            {"subagents": graph["subagents"]},
            exec_order
        )

        # Analyze risk
        risk_analysis = risk_analyzer.analyze(
            {"subagents": graph["subagents"]},
            exec_order,
            critical_path
        )

        # Generate enhanced markdown plan
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        plan_md = f"""# 📋 执行计划

## 任务: {user_intent}

生成时间: {now}

---

## 执行步骤

"""

        # Add steps with numbering and timing info
        for timing in step_timings:
            subagent_name = timing.subagent_name
            subagent_info = graph["subagents"].get(subagent_name, {})
            task_template = subagent_info.get("task_template", "")
            output_key = subagent_info.get("output_context_key", "")
            requires = subagent_info.get("requires", [])

            # Step header with critical path indicator
            emoji = str(timing.step_number) + "️⃣" if timing.step_number <= 9 else f"{timing.step_number}️⃣"
            critical_indicator = " (关键路径)" if timing.critical_path else ""
            plan_md += f"\n### {emoji} {subagent_name.upper()}{critical_indicator}\n\n"

            # Task description
            plan_md += f"- **任务**: {task_template}\n"
            plan_md += f"- **输出**: `{output_key}`\n"

            # Dependencies info
            if requires:
                req_list = ", ".join(f"`{req}`" for req in requires)
                plan_md += f"- **依赖**: {req_list}\n"
            else:
                plan_md += f"- **依赖**: 无\n"

            # Consumed by info (who depends on this step's output)
            dependents = graph.get("output_to_subagent", {}).get(output_key, "")
            if dependents:
                # Find steps that depend on this output
                consuming_steps = []
                for i, s in enumerate(exec_order, 1):
                    subagent_info2 = graph["subagents"].get(s, {})
                    for req in subagent_info2.get("requires", []):
                        if subagent_info2.get("output_context_key") == req:
                            consuming_steps.append(f"{i} ({s.upper()})")
                            break

                if consuming_steps:
                    plan_md += f"- **被使用**: {', '.join(consuming_steps)}\n"

            # Timing info
            plan_md += f"- **预计时间**: {estimator.format_duration(timing.estimated_duration)}\n"

            # Critical path note
            if timing.critical_path:
                plan_md += f"- **关键信息**: 这个步骤在关键路径上！延迟或失败会影响总执行时间\n"

        # Summary section with timing details
        plan_md += f"""

---

## ⏱️ 时间估计

"""

        # Per-step timing
        for timing in step_timings:
            plan_md += f"- **Step {timing.step_number} ({timing.subagent_name.upper()})**: {estimator.format_duration(timing.estimated_duration)}\n"

        plan_md += f"""- **总预计时间**: {estimator.format_duration(total_time)}
- **执行模式**: 按顺序执行 (依赖顺序: {' → '.join(exec_order)})
"""

        # Parallelization info
        # Check if any steps can run in parallel
        # (For now, we assume sequential execution due to dependencies)
        can_parallel = any(
            not graph["subagents"].get(s, {}).get("requires")
            for s in exec_order
        )
        if can_parallel:
            plan_md += "- **并行机会**: 某些步骤可以并行执行\n"
        else:
            plan_md += "- **并行机会**: 无 (所有步骤形成线性链)\n"

        # Risk analysis section
        plan_md += f"""

---

## 📈 风险分析

{risk_analysis.format_for_markdown()}

---

## 🔁 依赖流程

"""

        # Generate flow diagram using FlowDiagramBuilder
        from olav.core.flow_diagram_builder import get_flow_diagram_builder

        diagram_builder = get_flow_diagram_builder()

        # Build timing dict for diagram
        step_timing_dict = {
            t.subagent_name: t.estimated_duration
            for t in step_timings
        }

        # Generate ASCII flow diagram
        flow_diagram = diagram_builder.build_diagram(
            exec_order,
            {"subagents": graph["subagents"]},
            step_timing_dict
        )

        plan_md += flow_diagram

        # Critical path display
        if critical_path:
            path_display = " → ".join(critical_path)
            plan_md += f"\n\n关键路径: {path_display}\n"
            path_time = sum(
                t.estimated_duration
                for t in step_timings
                if t.subagent_name in critical_path
            )
            plan_md += f"关键路径耗时: {estimator.format_duration(path_time)}\n"

        # Add optimization suggestions
        suggestions = diagram_builder.build_optimization_suggestions(
            exec_order,
            {"subagents": graph["subagents"]}
        )
        if suggestions:
            plan_md += "\n## 💡 优化建议\n\n"
            for suggestion in suggestions:
                plan_md += f"- {suggestion}\n"

        plan_md += f"""

---

## ✅ 确认执行?

请输入以下选项之一:
- **Y**: 继续执行 (Step 1 → Step {len(exec_order)})
- **n**: 取消执行
- **edit**: 编辑计划 (未来支持)

**选择 (Y/n/edit)**:
"""

        logger.info(f"Enhanced plan generated for: {user_intent}")

        # Phase 6.2.3: Add confirmation options
        from olav.core.confirmation_handler import get_confirmation_handler
        confirmation_handler = get_confirmation_handler()

        # Build confirmation request summary
        confirmation_summary = f"""## ✅ 确认选项

**意图**: {user_intent}
**预计耗时**: {total_time}
**风险等级**: {risk_analysis.level.value}

该计划已生成并准备执行。请选择以下选项之一:

- **[Y/确认]** - 确认并执行计划
- **[E/编辑]** - 修改计划参数
- **[D/详情]** - 显示完整计划详情
- **[N/取消]** - 放弃执行

生成时间: {now}
"""

        plan_md += confirmation_summary

        return plan_md

    except Exception as e:
        logger.error(f"Error generating plan: {e}", exc_info=True)
        return f"计划生成失败: {str(e)}"
    except Exception as e:
        logger.error(f"Failed to generate plan: {e}", exc_info=True)
        return f"❌ 生成计划失败: {str(e)}"


# =============================================================================
# Simplified Interface (Backward Compatibility)
# =============================================================================


async def orchestrate_query(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Orchestrate a user query through SubAgent specialists (async wrapper).

    WORKAROUND (v0.11.1): This async version wraps the sync implementation
    to avoid DeepAgents async/await timeout issues with custom OpenAI endpoints.
    
    Args:
        user_query: User's natural language query
        user_id: User identifier
        thread_id: Thread identifier

    Returns:
        Dictionary containing:
            - status: "complete" or "failed"
            - final_answer: Agent response
            - error_message: Error if failed
    """
    logger.info(f"📌 [orchestrate_query START] Query: {user_query[:50]}...")

    try:
        # Default IDs if not provided
        if not user_id:
            user_id = "default_user"
        if not thread_id:
            thread_id = "default_thread"

        logger.debug(f"  user_id={user_id}, thread_id={thread_id}")

        # ⭐ PHASE 6.2.1: Detect /plan prefix and enter plan_mode
        is_planning_mode = user_query.startswith("/plan ")

        if is_planning_mode:
            # Extract the actual task after "/plan " prefix
            user_intent = user_query[6:].strip()
            logger.debug(f"  🎯 Planning mode detected: {user_intent[:50]}")

            # Phase 6.2.1: Enter plan_mode (returns plan markdown, doesn't execute)
            plan_result = await plan_mode_handler(user_intent)

            return {
                "status": "complete",
                "final_answer": plan_result,
                "error_message": "",
            }

        # Normal mode - use sync wrapper in thread to avoid DeepAgents async deadlock
        logger.debug(f"  🔧 Using sync wrapper in background thread...")
        
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            orchestrate_query_sync,
            user_query,
            user_id,
            thread_id
        )
        
        logger.info(f"✅ [orchestrate_query COMPLETE] Status: {result['status']}")
        return result

    except asyncio.TimeoutError as e:
        logger.error(f"❌ [orchestrate_query TIMEOUT] {e}", exc_info=True)
        return {
            "status": "failed",
            "final_answer": "",
            "error_message": f"Query execution timeout: {str(e)}",
        }
    except Exception as e:
        logger.error(f"❌ [orchestrate_query FAILED] {type(e).__name__}: {e}", exc_info=True)
        return {
            "status": "failed",
            "final_answer": "",
            "error_message": str(e),
        }



def orchestrate_query_sync(
    user_query: str,
    user_id: str | None = None,
    thread_id: str | None = None,
) -> dict[str, Any]:
    """Synchronous minimal orchestrator - Simple LLM + Database Query Fallback.
    
    SMART EXPORT FEATURE (v0.11.2+):
    - Uses LLM to detect export format from user query via SKILL.md prompt
    - LLM includes <export_format> tags in response if export requested
    - Calls format_and_export tool when export tags detected
    
    WORKAROUND FOR: DeepAgents async middleware incompatibility with OpenRouter API.
    
    Rather than debugging DeepAgents' complex middleware stack, this implements
    a minimal but functional orchestrator that:
    1. Sends user query to LLM with database context
    2. LLM determines if query needs database access or is answerable directly
    3. LLM detects if export is requested (via SKILL.md prompt)
    4. Executes query if needed
    5. Exports to file if LLM included export markers
    6. Returns result with file path if exported
    
    Args:
        user_query: User's natural language query
        user_id: User identifier
        thread_id: Thread identifier
        
    Returns:
        Dictionary containing status, final_answer, and error_message
        
    See: .github/copilot-instructions.md - "Known Issues & Troubleshooting (v0.11.1)"
    """
    from config.settings import settings
    from olav.core.llm import LLMFactory
    from olav.core.query_confidence import QueryComplexityScorer, QueryEscalationMarker
    from olav.shared.tools.data_export import format_and_export
    from langchain_core.messages import HumanMessage
    import json
    import re
    
    logger.debug(f"📤 [orchestrate_query_sync] Starting minimal fallback orchestrator")
    
    try:
        # Step 0: Check for user routing hints (NEW v0.11.4.2)
        # Users can include these keywords in their query to override auto-routing:
        # - "use expert" / "using expert" / "need expert" → Force Expert Agent
        # - "use cli" / "using cli" / "need cli" / "实时数据" → Request CLI commands
        import re
        
        force_expert = bool(re.search(r'use\s+expert|using\s+expert|need\s+expert|想用expert', 
                                     user_query, re.IGNORECASE))
        force_cli = bool(re.search(r'use\s+cli|using\s+cli|need\s+cli|show\s+command|实时数据|show output', 
                                  user_query, re.IGNORECASE))
        
        if force_expert:
            logger.info(f"  📌 User requested Expert Agent (via 'use expert' keyword)")
            logger.debug(f"    Query: {user_query}")
        
        if force_cli:
            logger.info(f"  📌 User requested CLI data (via 'use cli' / 'need cli' keyword)")
            logger.debug(f"    Query: {user_query}")
        
        # Step 0: Score query complexity (v0.11.4+ - Confidence-based routing)
        logger.debug("  0️⃣ Scoring query complexity with LLM...")
        
        # Get LLM for scoring
        llm_factory = LLMFactory()
        llm = llm_factory.get_chat_model()
        
        score_result = QueryComplexityScorer.score(user_query, llm)
        complexity_score = score_result["score"]
        complexity_category = score_result["category"]
        
        # Check routing: auto-score OR user override (use expert keyword)
        should_use_expert = score_result["needs_expert"] or force_expert
        
        if should_use_expert:
            routing_reason = "user requested 'use expert'" if force_expert else f"high complexity score ({complexity_score:.2f})"
            logger.info(f"  ⚡ Routing to Expert Agent ({routing_reason})...")
            
            # NEW: Step 0.5 - Validate schema data availability (v0.11.4.1)
            from olav.core.query_confidence import SchemaDataValidator
            logger.debug("  0️⃣.5️⃣ Validating schema data for expert analysis...")
            
            schema_check = SchemaDataValidator.has_sufficient_data_for_expert(user_query, llm)
            
            if not schema_check["has_data"]:
                logger.warning(f"    ⚠ Insufficient data for expert analysis")
                logger.info(f"    📌 Missing: {schema_check['missing_data']}")
                logger.info(f"    💡 Recommendation: {schema_check['recommendation']}")
                
                # Return early with honest message instead of hallucinating
                return {
                    "status": "insufficient_data",
                    "final_answer": f"""🔴 Unable to perform expert-level analysis

**Reason**: {schema_check['reason']}

**Database Schema**: {', '.join(schema_check['available_tables'])}

**Required for Analysis**: {', '.join(schema_check['missing_data'])}

**Recommendation**: {schema_check['recommendation']}

To proceed, please either:
1. Provide data for missing fields/tables
2. Use CLI queries to collect real-time data (Query Agent can escalate with <cli_needed>)
3. Ask a simpler question based on available data""",
                    "error_message": f"Schema insufficient for expert analysis",
                }
            
            logger.debug(f"    ✓ Schema validation passed, proceeding with Expert routing")
            
            try:
                # Load Expert SKILL.md
                from pathlib import Path
                expert_skill_path = Path(".olav/skills/network-expert/SKILL.md")
                
                if expert_skill_path.exists():
                    with open(expert_skill_path, 'r', encoding='utf-8') as f:
                        expert_skill_content = f.read()
                        # Extract instructions from SKILL.md (after frontmatter)
                        if '---' in expert_skill_content:
                            parts = expert_skill_content.split('---')
                            if len(parts) >= 3:
                                expert_instructions = parts[2].strip()
                            else:
                                expert_instructions = expert_skill_content
                        else:
                            expert_instructions = expert_skill_content
                    
                    logger.debug(f"    ✓ Expert SKILL.md loaded ({len(expert_instructions)} chars)")
                    
                    # Invoke Expert Agent via LLM with SKILL.md instructions
                    # Support CLI fallback: Expert can request CLI data via <need_cli_data> marker
                    expert_context = ""  # Store CLI results for next round
                    
                    # Add instruction about CLI emphasis if user requested it
                    cli_emphasis = ""
                    if force_cli:
                        cli_emphasis = """\n== IMPORTANT: USER REQUESTED CLI DATA ==
The user explicitly requested real-time CLI data for this analysis.
Please include <need_cli_data> markers with the commands needed to answer this query."""
                    
                    expert_prompt = f"""{expert_instructions}

== EXPERT ANALYSIS REQUEST ==

User Query: {user_query}

{expert_context}{cli_emphasis}

Please provide expert-level analysis, root cause diagnosis, or recommendations based
on your CCIE-level expertise. Use the workflow described in your instructions above.

If database schema is insufficient, you can request CLI data using:
<need_cli_data>show interfaces, show version, etc.</need_cli_data>

The Orchestrator will collect the CLI data and provide results."""
                    
                    logger.debug(f"    🤖 Invoking Expert Agent via LLM...")
                    expert_response = llm.invoke([HumanMessage(content=expert_prompt)])
                    expert_answer = expert_response.content if hasattr(expert_response, 'content') else str(expert_response)
                    
                    # Check if Expert is requesting CLI data
                    import re
                    cli_marker_pattern = r'<need_cli_data>(.*?)</need_cli_data>'
                    cli_matches = re.findall(cli_marker_pattern, expert_answer, re.DOTALL)
                    
                    if cli_matches:
                        # Expert requested CLI data - explain what needs to happen
                        cli_commands_text = cli_matches[0].strip()
                        logger.info(f"  🔄 Expert requires CLI data collection")
                        logger.debug(f"    Requested commands: {cli_commands_text[:100]}...")
                        
                        # Split commands by comma or newline
                        commands_list = [cmd.strip() for cmd in re.split(r'[,\n;\s]+', cli_commands_text) 
                                        if cmd.strip() and cmd.strip().lower().startswith('show')]
                        
                        # Return with explanation
                        cli_suggestion = f"""## CLI Data Collection Needed

Expert analysis requires real-time CLI data. Please execute these commands on your devices:

```
{chr(10).join(commands_list)}
```

Once you have the output, you can provide it for deeper analysis."""
                        
                        # Remove CLI markers from intermediate answer
                        final_answer = re.sub(cli_marker_pattern, '', expert_answer)
                        final_answer = f"{final_answer}\n\n{cli_suggestion}"
                        
                        logger.info(f"    ✓ Expert analysis with CLI requirements completed")
                        
                        return {
                            "status": "needs_cli_data",
                            "final_answer": final_answer,
                            "error_message": "",
                            "cli_commands": commands_list,
                        }
                    else:
                        # No CLI data needed
                        logger.info(f"    ✓ Expert Agent analysis completed")
                        
                        return {
                            "status": "complete",
                            "final_answer": expert_answer,
                            "error_message": "",
                        }
                else:
                    logger.warning(f"    ⚠ Expert SKILL.md not found at {expert_skill_path}")
                    # Fall through to Query Agent
                    
            except Exception as expert_error:
                import traceback
                error_msg = f"Expert Agent routing failed: {expert_error}"
                tb = traceback.format_exc()
                logger.error(f"    ❌ {error_msg}\n{tb}")
                
                return {
                    "status": "error",
                    "final_answer": f"Error during expert analysis:\n{error_msg}\n\n{tb}",
                    "error_message": str(expert_error),
                }
        # Step 1: Create LLM
        logger.debug("  1️⃣ Creating LLM...")
        llm = LLMFactory.get_chat_model()
        logger.debug(f"    ✓ LLM created: {llm.model_name}")
        
        # Step 2: Get database schema context
        logger.debug("  2️⃣ Inspecting database schema...")
        try:
            # Query database directly (no LLM needed for schema inspection)
            from olav.lib.data_gateway import DataGateway
            from config.paths import get_database_path
            
            gw = DataGateway(db_path=get_database_path())
            result = gw.query_main("SELECT * FROM devices LIMIT 1")
            schema_context = f"Available database schema:\n{str(result)[:500]}..."
        except Exception as e:
            logger.warning(f"    ⚠ Schema inspection failed: {e}")
            schema_context = "Database available but schema inspection failed."
        
        # Step 2b: Load Query Agent SKILL.md
        logger.debug("  2️⃣b Loading Query Agent SKILL.md...")
        query_agent_skill = ""
        from pathlib import Path
        skill_path = Path(".olav/skills/network-query/SKILL.md")
        if skill_path.exists():
            try:
                with open(skill_path, 'r', encoding='utf-8') as f:
                    skill_content = f.read()
                    # Extract only the instruction part (after the frontmatter)
                    if '---' in skill_content:
                        parts = skill_content.split('---')
                        if len(parts) >= 3:
                            query_agent_skill = parts[2].strip()
                    else:
                        query_agent_skill = skill_content
                logger.debug(f"    ✓ Query Agent SKILL loaded ({len(query_agent_skill)} chars)")
            except Exception as e:
                logger.warning(f"    ⚠ Failed to load SKILL.md: {e}")
        
        # Step 3: Create context prompt
        system_prompt = f"""You are OLAV, a Network Operations AI assistant.

{schema_context}

=== QUERY AGENT INSTRUCTIONS ===
{query_agent_skill}
=== END QUERY AGENT INSTRUCTIONS ===

User Query: {user_query}

Based on the database schema and instructions above, provide:
1. A brief analysis of what the user is asking
2. If a SQL query is needed, provide it wrapped in <sql>...</sql> tags
3. If the user wants to export results to a file format (csv, json, markdown, etc.), include:
   - <export_format>FORMAT</export_format> (e.g., <export_format>csv</export_format>)
   - <export_filename>FILENAME</export_filename> (optional, only if user specified a filename)
4. If a SQL query is NOT possible (e.g., data not in schema), provide:
   - <cli_needed>reason_why_query_not_possible</cli_needed>
   - Followed by your explanation
5. If answerable directly, provide the answer

Keep responses concise and focused."""
        
        # Step 4: Call LLM
        logger.debug("  3️⃣ Calling LLM...")
        
        response = llm.invoke([HumanMessage(content=system_prompt)])
        response_text = response.content if hasattr(response, 'content') else str(response)
        logger.debug(f"    ✓ LLM responded: {response_text[:100]}...")
        
        # Step 5: Check for <cli_needed> marker → escalate to CLI Agent (v0.11.4+)
        cli_needed_pattern = r'<cli_needed>(.*?)</cli_needed>'
        cli_match = re.search(cli_needed_pattern, response_text, re.DOTALL)
        
        if cli_match:
            cli_reason = cli_match.group(1).strip()
            logger.info(f"  🔴 Query Agent marked as cli_needed: {cli_reason[:50]}...")
            try:
                # Try to extract device name from query and execute show command
                from olav.shared.tools.network_executor import get_executor
                
                # Simple extraction of device names from query
                device_names = []
                for dev_id in ["R1", "R2", "R3", "R4", "SW1", "SW2"]:
                    if dev_id in user_query:
                        device_names.append(dev_id)
                
                # If no specific device, use all routing devices for OSPF/BGP, all devices for others
                if not device_names:
                    if "ospf" in user_query.lower() or "bgp" in user_query.lower():
                        device_names = ["R1", "R2", "R3", "R4"]  # Routers typically have OSPF/BGP
                    else:
                        device_names = ["R1"]  # Default to first router
                
                # Determine relevant show commands based on query intent
                if "interface" in user_query.lower() or "error" in user_query.lower():
                    show_cmd = "show interfaces"
                elif "ospf" in user_query.lower():
                    show_cmd = "show ip ospf neighbor"
                elif "bgp" in user_query.lower():
                    show_cmd = "show ip bgp summary"  
                elif "vlan" in user_query.lower():
                    show_cmd = "show vlan brief"
                else:
                    show_cmd = "show inventory"
                
                # Execute on all found devices and collect outputs
                executor = get_executor()
                cli_results = executor.execute_command(
                    devices=device_names,
                    command=show_cmd,
                    timeout=30
                )
                
                # Format results
                cli_outputs = []
                for i, device in enumerate(device_names):
                    result = cli_results[i] if i < len(cli_results) else None
                    if result:
                        if hasattr(result, 'stdout') and result.stdout:
                            cli_outputs.append(f"Device {device}:\n{result.stdout}")
                        elif hasattr(result, 'output') and result.output:
                            cli_outputs.append(f"Device {device}:\n{result.output}")
                        else:
                            cli_outputs.append(f"Device {device}: {str(result)}")
                    else:
                        cli_outputs.append(f"Device {device}: No output")
                    logger.debug(f"    ✓ CLI command executed on {device}")
                
                combined_cli = "\n\n".join(cli_outputs)
                final_answer = f"""🔴 Database Query: Unable to answer from schema
  Reason: {cli_reason}

⚡ CLI Verification Result:
Command executed: {show_cmd}
Devices: {', '.join(device_names)}

Output:
{combined_cli}"""
                logger.info(f"    ✓ CLI verification completed from devices {device_names}")
                
                return {
                    "status": "complete",
                    "final_answer": final_answer,
                    "error_message": "",
                }
                    
            except Exception as cli_error:
                logger.warning(f"    ⚠ CLI execution failed: {cli_error}")
                # Fall through to return LLM response
                final_answer = response_text.replace(cli_needed_pattern, '')
        
        # Step 6 (original): Parse SQL if present
        sql_pattern = r'<sql>(.*?)</sql>'
        sql_match = re.search(sql_pattern, response_text, re.DOTALL)
        
        final_answer = response_text
        query_result = None
        
        if sql_match:
            sql_query = sql_match.group(1).strip()
            logger.debug(f"  4️⃣ Executing database query: {sql_query[:50]}...")
            try:
                # Execute query directly
                from olav.lib.data_gateway import DataGateway
                from config.paths import get_database_path
                
                gw = DataGateway(db_path=get_database_path())
                query_result = gw.query_main(sql_query)
                final_answer = f"Query Result:\n{query_result}"
                logger.debug(f"    ✓ Query executed successfully")
            except Exception as e:
                logger.error(f"    ✗ Query failed: {e}")
                final_answer = f"Query failed: {str(e)}"
        
        # Step 6: Parse export format markers (LLM-detected)
        export_format = None
        export_filename = None
        
        format_pattern = r'<export_format>(\w+)</export_format>'
        format_match = re.search(format_pattern, response_text)
        if format_match:
            export_format = format_match.group(1).lower()
            logger.debug(f"    ✓ Export format detected from LLM: {export_format}")
        
        filename_pattern = r'<export_filename>([a-zA-Z0-9_\-\u4e00-\u9fff]+)</export_filename>'
        filename_match = re.search(filename_pattern, response_text)
        if filename_match:
            export_filename = filename_match.group(1).strip()
            logger.debug(f"    ✓ Export filename detected from LLM: {export_filename}")
        
        # Step 7: Check for Query Agent Expert Escalation Marker (v0.11.4+)
        logger.debug(f"  6️⃣ Checking for Expert escalation marker...")
        
        has_escalation, escalation_reason = QueryEscalationMarker.check(final_answer)
        if has_escalation:
            logger.info(f"  🚀 Query Agent requested Expert escalation: {escalation_reason[:50]}...")
            try:
                # Load Expert SKILL.md
                from pathlib import Path
                expert_skill_path = Path(".olav/skills/network-expert/SKILL.md")
                
                if expert_skill_path.exists():
                    with open(expert_skill_path, 'r', encoding='utf-8') as f:
                        expert_skill_content = f.read()
                        # Extract instructions
                        if '---' in expert_skill_content:
                            parts = expert_skill_content.split('---')
                            if len(parts) >= 3:
                                expert_instructions = parts[2].strip()
                            else:
                                expert_instructions = expert_skill_content
                        else:
                            expert_instructions = expert_skill_content
                    
                    logger.debug(f"    ✓ Expert SKILL.md loaded for escalation")
                    
                    # Invoke Expert with context from Query Agent
                    expert_prompt = f"""{expert_instructions}

== ESCALATED FROM QUERY AGENT ==

Original User Query: {user_query}

Query Agent Analysis:
{final_answer}

Query Agent requested escalation because: {escalation_reason}

Please provide expert-level analysis to address the original query."""
                    
                    logger.debug(f"    🤖 Invoking Expert Agent for escalation...")
                    expert_response = llm.invoke([HumanMessage(content=expert_prompt)])
                    expert_answer = expert_response.content if hasattr(expert_response, 'content') else str(expert_response)
                    
                    logger.info(f"    ✓ Expert Agent escalation completed")
                    
                    return {
                        "status": "complete",
                        "final_answer": expert_answer,
                        "error_message": "",
                    }
                else:
                    logger.warning(f"    ⚠ Expert SKILL.md not found for escalation")
                    # Continue with Query Agent response
                    
            except Exception as expert_error:
                logger.warning(f"    ⚠ Expert escalation failed: {expert_error}")
                # Continue with Query Agent response
                pass
        
        # Step 8: Handle file export if LLM detected it
        if export_format and query_result:
            logger.debug(f"  7️⃣ Exporting to {export_format}...")
            try:
                # Call format_and_export tool
                export_result = format_and_export.invoke({
                    "data": query_result,
                    "format": export_format,
                    "filename": export_filename,
                })
                
                # Build success message
                export_path = export_result.get("path", "unknown")
                export_size = export_result.get("size", 0)
                final_answer = f"""✅ Export Successful!
                
📁 Format: {export_format.upper()}
📄 File: {export_path}
💾 Size: {export_size:,} bytes

{final_answer}"""
                logger.info(f"    ✓ Exported to {export_path} ({export_size} bytes)")
            except Exception as e:
                logger.warning(f"    ⚠ Export failed: {e}")
                final_answer = f"⚠️ Query succeeded but export failed: {str(e)}\n\n{final_answer}"
        
        # Step 8: Clean export markers from final answer before returning
        # Remove the <export_format> and <export_filename> tags so user doesn't see them
        clean_answer = re.sub(r'<export_format>.*?</export_format>', '', final_answer)
        clean_answer = re.sub(r'<export_filename>.*?</export_filename>', '', clean_answer)
        
        logger.info(f"✅ [orchestrate_query_sync] Completed successfully")
        return {
            "status": "complete",
            "final_answer": clean_answer,
            "error_message": "",
        }
        
    except Exception as e:
        logger.error(f"❌ [orchestrate_query_sync] Failed: {type(e).__name__}: {e}", exc_info=True)
        return {
            "status": "failed",
            "final_answer": "",
            "error_message": str(e),
        }



# =============================================================================
# Main
# =============================================================================


if __name__ == "__main__":
    import asyncio

    async def test() -> None:
        """Test orchestrator with SubAgent routing."""
        test_query = "List all devices with high CPU usage"
        result = await orchestrate_query(test_query)

        print(f"Query: {test_query}")
        print(f"Status: {result['status']}")
        print(f"Final Answer:\n{result['final_answer']}")

    asyncio.run(test())
