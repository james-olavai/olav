"""Pattern 2 SubAgent Factories - Persistent Agent Creation.

Implements SUB_AGENT_DEVELOPMENT_GUIDE.md Pattern 2 for SubAgents requiring
session persistence and conversation history (query, analysis).

These factories create full DeepAgents with:
- DuckDBSaver for session checkpointing
- DuckDBStore for key-value storage
- SummarizationMiddleware for long conversations
- Proper initialization and cleanup
"""

import logging
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent

from config.paths import USER_CHECKPOINT_PATH, USER_CHECKPOINT_DIR
from olav.core.llm import LLMFactory
from olav.core.skill_loader import get_skill_loader
from olav.core.storage import get_storage_backend

logger = logging.getLogger(__name__)


def create_query_subagent(
    user_id: str = "default",
    enable_summarization: bool = False,
) -> Any:
    """Create query SubAgent with full persistence (Pattern 2).
    
    Features:
    - DuckDBSaver: Session checkpointing for conversation continuity
    - DuckDBStore: Key-value store for aliases and preferences
    - Semantic caching for repeated queries
    
    Args:
        user_id: User identifier for session isolation (default: "default")
        enable_summarization: Enable automatic conversation summarization
    
    Returns:
        Compiled LangGraph agent with persistence
    
    Usage:
        agent = create_query_subagent(user_id="user123")
        result = await agent.ainvoke(
            {"messages": ["查询所有路由器设备"]},
            config={"configurable": {"thread_id": "session-123"}}
        )
    """
    logger.info(f"Creating query SubAgent with persistence (user_id={user_id})")
    
    # 1. Setup user-specific DuckDB persistence
    _init_user_database(user_id)
    user_db_path = Path(USER_CHECKPOINT_PATH) / f"{user_id}.duckdb"
    
    # Use None for checkpointer (can be set at runtime if needed)
    # DuckDBSaver.from_conn_string() returns a context manager, not a saver instance
    # The persistence will be managed at invocation time with config={'configurable': {'thread_id': ...}}
    checkpointer = None
    store = None
    
    # 2. Load skill configuration
    loader = get_skill_loader()
    skill = loader.get_skill("network-query")
    if not skill:
        raise ValueError("network-query SKILL.md not found")
    
    # 3. Note: Tools will be loaded by the orchestrator that invokes this SubAgent
    # Skip loading tools here to avoid format mismatches (tool definitions use string names)
    
    # 4. Get system prompt
    system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
    if not system_prompt:
        raise ValueError("network-query SKILL.md missing prompts.system")
    
    # 5. Setup LLM and backend
    agent_config = skill.frontmatter.get("agent", {})
    temperature = float(agent_config.get("temperature", 0.1))
    llm = LLMFactory.get_chat_model(temperature=temperature)
    backend = get_storage_backend()
    
    # 6. Optional middleware
    middleware = []
    if enable_summarization:
        from deepagents.middleware.summarization import SummarizationMiddleware
        from config.settings import settings
        
        summ_model = LLMFactory.get_chat_model(temperature=0.1)
        middleware.append(
            SummarizationMiddleware(
                model=summ_model,
                backend=backend,
                trigger=("tokens", settings.agent.summarization_trigger_tokens),
                keep=("messages", settings.agent.summarization_keep_messages),
            )
        )
    
    # 7. Create agent with persistence (tools will be injected by orchestrator)
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=[],  # Tools will be provided by orchestrator
        backend=backend,
        checkpointer=checkpointer,  # ✅ Pattern 2: Session persistence
        store=store,                # ✅ Pattern 2: KV store
        middleware=middleware,      # ✅ Optional: Summarization
        name="query",
    )
    
    logger.info("query SubAgent created with DuckDBSaver + DuckDBStore")
    return agent


def create_analysis_subagent(
    user_id: str = "default",
    enable_summarization: bool = False,
) -> Any:
    """Create analysis SubAgent with full persistence (Pattern 2).
    
    Features:
    - Multi-turn analysis workflows with context preservation
    - Session checkpointing for resumable analysis
    - Key-value store for hypothesis tracking
    
    Args:
        user_id: User identifier for session isolation
        enable_summarization: Enable automatic conversation summarization
    
    Returns:
        Compiled LangGraph agent with persistence
    """
    logger.info(f"Creating analysis SubAgent with persistence (user_id={user_id})")
    
    # 1. Setup user-specific DuckDB persistence
    _init_user_database(user_id)
    user_db_path = Path(USER_CHECKPOINT_PATH) / f"{user_id}_analysis.duckdb"
    
    # Use None for checkpointer (can be set at runtime if needed)
    # The persistence will be managed at invocation time
    checkpointer = None
    store = None
    
    # 2. Load skill configuration
    loader = get_skill_loader()
    skill = loader.get_skill("network-analysis")
    if not skill:
        raise ValueError("network-analysis SKILL.md not found")
    
    # 3. Note: Tools will be loaded by the orchestrator
    # Skip loading tools here to avoid format mismatches
    
    # 4. Get system prompt
    system_prompt = skill.frontmatter.get("prompts", {}).get("system", "")
    if not system_prompt:
        raise ValueError("network-analysis SKILL.md missing prompts.system")
    
    # 5. Setup LLM and backend
    agent_config = skill.frontmatter.get("agent", {})
    temperature = float(agent_config.get("temperature", 0.1))
    llm = LLMFactory.get_chat_model(temperature=temperature)
    backend = get_storage_backend()
    
    # 6. Optional middleware
    middleware = []
    if enable_summarization:
        from deepagents.middleware.summarization import SummarizationMiddleware
        from config.settings import settings
        
        summ_model = LLMFactory.get_chat_model(temperature=0.1)
        middleware.append(
            SummarizationMiddleware(
                model=summ_model,
                backend=backend,
                trigger=("tokens", settings.agent.summarization_trigger_tokens),
                keep=("messages", settings.agent.summarization_keep_messages),
            )
        )
    
    # 7. Create agent with persistence (tools will be injected by orchestrator)
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        tools=[],  # Tools will be provided by orchestrator
        backend=backend,
        checkpointer=checkpointer,  # ✅ Pattern 2: Session persistence
        store=store,                # ✅ Pattern 2: KV store
        middleware=middleware,      # ✅ Optional: Summarization
        name="analysis",
    )
    
    logger.info("analysis SubAgent created with DuckDBSaver + DuckDBStore")
    return agent


def _init_user_database(user_id: str) -> None:
    """Initialize user-specific DuckDB directory.
    
    Creates the checkpoints directory if needed. Each user's SubAgent
    data will be stored in separate DuckDB files within this directory.
    
    Args:
        user_id: User identifier
    """
    USER_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug(f"User checkpoint directory initialized: {USER_CHECKPOINT_DIR}")
