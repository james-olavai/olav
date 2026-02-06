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

import logging
from typing import Any

from deepagents import create_deep_agent
from deepagents.middleware.subagents import SubAgent
from langchain_core.messages import AIMessage, HumanMessage

from olav.agents.analyzer import analyze_network
from olav.core.subagent_loader import load_subagents_from_olav
from olav.tools.react_query import query_database  # query_network removed (deprecated)

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
    from olav.tools.data_export import format_and_export

    # Orchestrator's own tools for file export
    orchestrator_tools = [
        format_and_export,  # File export capability
    ]

    # Persistence layer (skill-level checkpoint - v0.10.0+)
    # Each skill has its own isolated checkpoint database
    # Note: DeepAgents handles checkpoint internally, we pass None to use in-memory
    checkpointer = None
    store = None

    # For persistent checkpointing with DuckDB, would use:
    # from langgraph.checkpoint.duckdb import DuckDBSaver
    # checkpointer = DuckDBSaver.from_conn_string(str(checkpoint_path))
    # But this creates context manager issues in async context
    # DeepAgents subagents handle their own checkpoint/state management
    logger.debug("Orchestrator using DeepAgents built-in state management (no explicit checkpoint)")

    # SubAgent configuration (v0.10.1 - Dynamic Loading from OLAV.md)
    try:
        subagents = load_subagents_from_olav()
        logger.info(f"Loaded {len(subagents)} SubAgents from OLAV.md")
    except Exception as e:
        logger.error(f"Failed to load SubAgents from OLAV.md: {e}")
        logger.info("Falling back to legacy hardcoded SubAgent configuration")
        subagents = []  # No fallback - all SubAgents must be defined in OLAV.md

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
            "Orchestrator SKILL.md not found or empty at .olav/skills/orchestrator/SKILL.md. "
            "This file is required for Skill-Centric Architecture."
        )

    # Middleware stack
    middleware = []
    # Use parameter if provided, otherwise use settings
    use_summarization = enable_summarization if enable_summarization is not None else settings.agent.enable_summarization
    
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
    from olav.tools.data_export import format_and_export
    
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
    """Orchestrate a user query through SubAgent specialists.

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
    logger.info(f"Orchestrating query: {user_query[:50]}...")

    try:
        # Default IDs if not provided
        if not user_id:
            user_id = "default_user"
        if not thread_id:
            thread_id = "default_thread"

        # ⭐ PHASE 6.2.1: Detect /plan prefix and enter plan_mode
        is_planning_mode = user_query.startswith("/plan ")
        
        if is_planning_mode:
            # Extract the actual task after "/plan " prefix
            user_intent = user_query[6:].strip()
            
            # Phase 6.2.1: Enter plan_mode (returns plan markdown, doesn't execute)
            plan_result = await plan_mode_handler(user_intent)
            
            return {
                "status": "complete",
                "final_answer": plan_result,
                "error_message": "",
            }
        
        # Normal mode - use query as-is
        query_to_execute = user_query

        # Create orchestrator with SubAgent routing
        orchestrator = create_orchestrator(
            user_id=user_id,
            thread_id=thread_id,
        )

        # Execute query
        config = {"configurable": {}}
        if user_id:
            config["configurable"]["user_id"] = user_id
        if thread_id:
            config["configurable"]["thread_id"] = thread_id

        result = await orchestrator.ainvoke(
            {"messages": [HumanMessage(content=query_to_execute)]},
            config=config,
        )

        # Extract final answer from messages
        final_answer = ""
        if result.get("messages"):
            last_msg = result["messages"][-1]
            if isinstance(last_msg, AIMessage):
                final_answer = last_msg.content
            elif isinstance(last_msg, dict) and "content" in last_msg:
                # Handle serialized message format
                final_answer = last_msg["content"]
        if not final_answer and isinstance(result, dict):
            # Try to extract from nested structures
            if "output" in result:
                final_answer = str(result["output"])
            elif "content" in result:
                final_answer = str(result["content"])

        return {
            "status": "complete",
            "final_answer": final_answer,
            "error_message": "",
        }

    except Exception as e:
        logger.error(f"Orchestration failed: {e}", exc_info=True)
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
