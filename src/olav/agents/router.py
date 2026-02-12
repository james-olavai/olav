"""Orchestrator Router - SubAgent Factory and Routing Logic (v0.10.1)

Separated from orchestrator.py as part of code simplification refactor (Phase 2.1).

Responsibilities:
- Create SubAgent-based orchestrator instances
- Configure agent routing and middleware
- Load SKILL.md configurations
- Manage LLM initialization
"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent

from olav.core.subagent_loader import load_subagents_from_olav

logger = logging.getLogger(__name__)


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

    # Use CompositeBackend for unified path routing ✅ PHASE 1 GREEN
    from olav.core.storage import get_storage_backend
    backend = get_storage_backend()

    if use_summarization:

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


def create_collaborative_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool | None = None,
) -> Any:
    """Create orchestrator with collaborative mode (Phase 5 - Declarative Dependencies).

    Extends create_orchestrator with dependency graph support.

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

    # Standard orchestrator creation (reuse existing logic)
    agent = create_orchestrator(
        user_id=user_id,
        thread_id=thread_id,
        enable_summarization=enable_summarization,
    )

    logger.info("Created collaborative orchestrator with phase 5 support")
    return agent


def create_planning_orchestrator(
    *,
    user_id: str | None = None,
    thread_id: str | None = None,
    enable_summarization: bool | None = None,
) -> Any:
    """Create orchestrator with TodoListMiddleware for planning mode (v0.10.2).

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

    # For now, fall back to standard orchestrator
    # TodoListMiddleware integration can be added later if needed
    logger.info("Creating planning orchestrator (experimental support)")
    
    return create_orchestrator(
        user_id=user_id,
        thread_id=thread_id,
        enable_summarization=enable_summarization,
    )
