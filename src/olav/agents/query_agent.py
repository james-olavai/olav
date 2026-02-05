"""
Query Agent - ReAct Powered by DeepAgents with Native LangGraph Components

Uses:
- DuckDBSaver: LangGraph native checkpointer for session state
- DuckDBStore: LangGraph native KV store for aliases
- SummarizationMiddleware: Native conversation summarization
"""

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.store.duckdb import DuckDBStore

from config.paths import USER_CHECKPOINT_PATH
from config.settings import settings
from olav.agents.intent_agent import IntentAgent
from olav.core.query_cache import get_query_cache
from olav.core.skill_adapter import SkillAdapter
from olav.core.skill_loader import get_skill_loader
from olav.lib.data_gateway import get_gateway

logger = logging.getLogger(__name__)


class QueryAgent:
    """Query Agent using DeepAgents ReAct architecture.

    DEPRECATED: This standalone agent is being migrated to orchestrator's query SubAgent.
    Use orchestrator.create_orchestrator() with the 'query' SubAgent instead.

    Migration timeline:
    - v0.10.0: query SubAgent available in orchestrator (current)
    - v0.11.0: QueryAgent will show deprecation warnings
    - v0.12.0: QueryAgent will be removed

    See: docs/ARCHITECTURE_COMPARISON.md for migration guide
    """

    def __init__(
        self,
        enable_summarization: bool = False,
        skill_name: str = "network-query",
        mode: str | None = None,  # Deprecated, kept for backward compatibility
    ) -> None:
        """Initialize QueryAgent.

        DEPRECATED: Use orchestrator.create_orchestrator() instead.

        Args:
            enable_summarization: Enable conversation summarization middleware
                - False: Standard mode (zero-shot, fast, direct SQL)
                - True: Analysis mode (ReAct loop, summarization, multi-step)
            skill_name: Name of the skill to load (e.g., "network-query", "bgp-expert")
            mode: [DEPRECATED] Legacy "standard"|"analysis" parameter.
                  Use enable_summarization instead.
        """
        import warnings

        warnings.warn(
            "QueryAgent is deprecated and will be removed in v0.12.0. "
            "Use orchestrator.create_orchestrator() with query SubAgent instead. "
            "See docs/ARCHITECTURE_COMPARISON.md for migration guide.",
            DeprecationWarning,
            stacklevel=2,
        )

        # Set environment variables from settings for LangChain/DeepAgents
        import os

        if settings.llm_api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = settings.llm_api_key
        if settings.llm_base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = settings.llm_base_url
        # For OpenRouter models with x-ai/ prefix, use a generic model name
        # and let OpenRouter's base_url handle routing
        if settings.llm_base_url and "openrouter" in settings.llm_base_url.lower():
            if not os.getenv("OPENAI_MODEL_NAME"):
                # Use the actual model name from settings - OpenRouter will handle it
                os.environ["OPENAI_MODEL_NAME"] = settings.llm_model_name

        # Backward compatibility: convert old mode parameter
        if mode is not None:
            logger.warning(
                f"Parameter 'mode={mode}' is deprecated. "
                f"Use 'enable_summarization=True/False' instead."
            )
            enable_summarization = mode == "analysis"

        self.enable_summarization = enable_summarization
        self.skill_loader = get_skill_loader()
        self.skill = self.skill_loader.get_skill(skill_name)

        if not self.skill:
            raise ValueError(f"Skill '{skill_name}' not found")

        # Initialize IntentAgent for Fast Path
        self.intent_agent = IntentAgent()

        # Initialize DataGateway
        self.gw = get_gateway()

        # Initialize user-specific checkpoint and store (LangGraph native)
        self._init_user_database()

        # Cache known devices for fast lookup
        self._known_devices = self._load_known_devices()

        # 1. Load tools dynamically from Skill metadata (Agent-Agnostic)
        self.tools = SkillAdapter.load_tools_from_skill(self.skill)

        # 2. Setup backend for DeepAgents
        project_root = Path.cwd()
        self.backend = FilesystemBackend(root_dir=str(project_root))

        # 3. Load external prompts
        prompts = self.skill.frontmatter.get("prompts", {})
        system_prompt_path = prompts.get("system", ".olav/prompts/react_system.txt")
        base_system_prompt = self._load_prompt_content(system_prompt_path)

        # 4. Inject dynamic metadata (Phase 4.3 Optimization)
        self.system_prompt = self._inject_metadata(base_system_prompt)

        # 5. Create the agent
        self._create_agent()

        # 6. Initialize query result cache
        self.query_cache = get_query_cache()

    def _init_user_database(self) -> None:
        """Initialize user-specific persistent checkpointer and store using DuckDB."""
        # from_conn_string returns a context manager - enter it manually
        self.checkpointer = DuckDBSaver.from_conn_string(str(USER_CHECKPOINT_PATH)).__enter__()
        self.store = DuckDBStore.from_conn_string(str(USER_CHECKPOINT_PATH)).__enter__()
        logger.debug(f"User checkpoint (DuckDB) initialized: {USER_CHECKPOINT_PATH}")

    def _load_known_devices(self) -> set[str]:
        """Load known device names from database for fast validation."""
        try:
            # Query olav.duckdb/raw_outputs instead of non-existent v_system view
            devices = self.gw.query_main("SELECT DISTINCT device FROM raw_outputs")
            return {str(d["device"]).upper() for d in devices}
        except Exception as e:
            logger.debug(f"No device data loaded (database may not be initialized): {e}")
            # Return empty set if database not initialized - this is normal on first run
            return set()

    def _create_agent(self) -> None:
        """Create the DeepAgent with native components."""
        # 5. Create the DeepAgent with native components
        model_name = settings.llm_model_name  # Use string directly

        # Infer model provider from model name if not explicitly set
        model_provider = settings.llm_model_provider or None
        if not model_provider and "/" in model_name:
            # Extract provider from format like "x-ai/grok-4.1-fast"
            provider_prefix = model_name.split("/")[0]
            # When using OpenRouter (base_url set), always use openai provider
            if settings.llm_base_url and "openrouter" in settings.llm_base_url.lower():
                model_provider = "openai"  # OpenRouter uses OpenAI-compatible API
            elif provider_prefix == "x-ai":
                model_provider = "xai"

        # Check if API key is available and try fallback if needed
        model_name, model_provider = self._check_model_availability(model_name, model_provider)

        # For create_deep_agent, prepend provider if using OpenRouter
        # This helps LangChain's init_chat_model infer the provider
        if model_provider and "/" not in model_name:
            model_for_agent = f"{model_provider}:{model_name}"
        elif model_provider == "openai" and "/" in model_name:
            # For OpenRouter with x-ai/ prefix, use openai: prefix
            model_for_agent = f"openai:{model_name}"
        else:
            model_for_agent = model_name

        # Create agent WITH tools for SQL + CLI fallback capability
        # Tools are loaded from skill metadata (query_database, inspect_schema, smart_query, get_cached_sql)
        if self.enable_summarization:
            # Tier 2: Full ReAct Loop with summarization middleware
            # Note: checkpoint support requires async-compatible saver
            self.agent = create_deep_agent(
                model=model_for_agent,
                system_prompt=self.system_prompt,
                tools=self.tools,  # CRITICAL: Pass tools so LLM can invoke smart_query for CLI fallback
            )
        else:
            # Tier 1: Standard (Fast-Path, no summarization)
            # LLM must invoke tools (query_database → smart_query) to get data
            self.agent = create_deep_agent(
                model=model_for_agent,
                system_prompt=self.system_prompt,
                tools=self.tools,  # CRITICAL: Pass tools so LLM can invoke smart_query for CLI fallback
            )

    def _check_model_availability(
        self, model_name: str, model_provider: str | None
    ) -> tuple[str, str | None]:
        """Check if the requested model is available, fallback to alternatives if needed.

        Returns:
            Tuple of (model_name, model_provider) that should be used

        Raises:
            ValueError: If no available model found
        """
        import os

        from config.settings import settings

        # Define fallback chain: xai -> openai -> google
        fallback_chain = [
            ("xai", "x-ai/grok-4.1-fast", "XAI_API_KEY"),
            ("openai", "gpt-4o-mini", "OPENAI_API_KEY"),
            ("google", "gemini-2.0-flash-exp", "GOOGLE_API_KEY"),
        ]

        # Try requested model first
        # Check both environment variables and settings.llm_api_key
        # Special case: if base_url contains "openrouter", always use openai provider
        if (
            settings.llm_base_url
            and "openrouter" in settings.llm_base_url.lower()
            and settings.llm_api_key
        ):
            logger.info(f"✅ Using OpenRouter with OpenAI-compatible API: {model_name}")
            return model_name, "openai"

        if model_provider == "xai" and (
            os.getenv("XAI_API_KEY") or (settings.llm_provider == "openai" and settings.llm_api_key)
        ):
            return model_name, model_provider
        elif model_provider == "openai" and (os.getenv("OPENAI_API_KEY") or settings.llm_api_key):
            return model_name, model_provider
        elif model_provider == "google" and os.getenv("GOOGLE_API_KEY"):
            return model_name, model_provider
        elif model_provider == "anthropic" and os.getenv("ANTHROPIC_API_KEY"):
            return model_name, model_provider

        # Try fallback chain
        logger.warning(
            f"⚠️  {model_provider or 'Requested'} model not available, trying fallback..."
        )

        for provider, fallback_model, env_key in fallback_chain:
            # Check both environment and settings
            has_key = os.getenv(env_key) or (provider == "openai" and settings.llm_api_key)
            if has_key:
                logger.info(f"✅ Using fallback: {provider}/{fallback_model}")
                return fallback_model, provider

        # No API key found at all
        raise ValueError(
            "❌ No LLM API key found in environment or settings.\n"
            "Please set one of:\n"
            "  export XAI_API_KEY='your-xai-key'        (recommended)\n"
            "  export OPENAI_API_KEY='your-openai-key'  (fallback)\n"
            "  export GOOGLE_API_KEY='your-google-key'  (fallback)\n"
            "Or configure in .olav/settings.json:\n"
            '  {"llm_api_key": "sk-or-v1-...", "llm_base_url": "https://openrouter.ai/api/v1"}'
        )

    def _inject_metadata(self, prompt: str) -> str:
        """Inject current snapshot date and available views into prompt."""
        try:
            # 1. Get snapshot info
            meta = self.gw.query_snapshots(
                "SELECT snapshot_date, device_count FROM commands.snapshot_metadata ORDER BY snapshot_date DESC LIMIT 1"
            )
            date_str = str(meta[0]["snapshot_date"]) if meta else "Unknown"
            devices = meta[0]["device_count"] if meta else 0

            # 2. Get available views
            views = self.gw.query_snapshots(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'VIEW'"
            )
            view_list = ", ".join([v["table_name"] for v in views])

            context = "\n\n### Current Environment Context\n"
            context += f"- **Latest Snapshot**: {date_str} ({devices} devices)\n"
            context += f"- **Available Views**: {view_list}\n"
            context += "Use these views for SQL queries. If a view is missing, you may use 'inspect_schema' but prioritize these.\n"

            return prompt + context
        except Exception:
            return prompt

    def _load_prompt_content(self, prompt_value: str) -> str:
        """Load prompt content from file path or return direct string"""
        # If it contains newlines or is very long, it's definitely content, not a path
        if "\n" in prompt_value or len(prompt_value) > 200:
            return prompt_value

        # If it looks like a path, try reading it
        if prompt_value.strip().startswith(".") or "/" in prompt_value:
            try:
                full_path = Path("/home/yhvh/Olav") / prompt_value
                if full_path.exists():
                    return full_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.debug(f"Failed to read file: {e}")

        # Otherwise treat as direct content
        return prompt_value

    def _process_aliases(
        self,
        query: str,
        learn_callback: "Callable[[str], str | None] | None" = None,
        max_prompts: int = 3,
    ) -> str:
        """Process aliases in user query with device existence validation.

        Extracts potential device names/aliases from the query and replaces them
        with canonical forms. Skips known devices to avoid unnecessary learning prompts.

        Args:
            query: User's original query string
            learn_callback: Optional callback for interactive learning.
            max_prompts: Maximum learning prompts per query

        Returns:
            Query with aliases replaced by canonical names
        """
        import re

        processed = query
        skill_name = self.skill.name if hasattr(self.skill, "name") else "network-query"

        # Extract potential entities: Chinese phrases or device names like R1, SW1, etc.
        entities = re.findall(r"[\u4e00-\u9fa5]+|[A-Z]+\d*", query)

        # Pattern for standard device names (skip learning for these)
        _device_pattern = re.compile(r"^(R|SW|S|FW|WLC|AP)\d+$", re.IGNORECASE)

        learning_count = 0

        for entity in set(entities):  # Deduplicate
            if not entity or len(entity) < 2:
                continue

            # Skip standard device name patterns (R1-R99, SW1-SW99, etc.)
            if _device_pattern.match(entity):
                logger.debug(f"Skipping standard device name pattern: {entity}")
                continue

            # Skip if it's a known device in database
            if entity.upper() in self._known_devices:
                logger.debug(f"Skipping known device: {entity}")
                continue

            # Check DuckDBStore for user alias
            try:
                result = self.store.get((skill_name, "aliases"), entity)
                if result:
                    canonical = result.value.get("canonical")
                    if canonical:
                        processed = processed.replace(entity, canonical)
                        logger.debug(f"Alias resolved from store: {entity} -> {canonical}")
                        continue
            except Exception as e:
                logger.debug(f"Store lookup failed: {e}")

            # Unknown entity - trigger learning if callback provided
            if learn_callback and learning_count < max_prompts:
                logger.info(
                    f"Unknown entity '{entity}' (prompt {learning_count + 1}/{max_prompts})"
                )

                try:
                    user_response = learn_callback(entity)
                    learning_count += 1

                    if user_response and user_response.strip():
                        canonical = user_response.strip()

                        # Save to DuckDBStore
                        self.store.put(
                            (skill_name, "aliases"),
                            entity,
                            {"canonical": canonical, "type": "device"},
                        )

                        # Replace in query
                        processed = processed.replace(entity, canonical)
                        logger.info(f"Learned new alias: {entity} -> {canonical}")
                    else:
                        logger.debug(f"User declined to teach alias for '{entity}'")
                except Exception as e:
                    logger.warning(f"Interactive learning failed for '{entity}': {e}")

        return processed

        return processed

    async def ainvoke(
        self,
        inputs: dict[str, Any],
        config: dict[str, Any] | None = None,
        learn_callback: "Callable[[str], str | None] | None" = None,
    ) -> dict[str, Any]:
        """Async invoke for CLI compatibility with optional learning callback.

        Processes messages and returns a state dictionary including 'result'.

        Args:
            inputs: Message dictionary with 'messages' key
            config: Optional LangGraph config (e.g., for thread_id)
            learn_callback: Optional callback for interactive alias learning
        """
        import time

        start_time = time.time()

        # DeepAgents expects 'messages' in the input
        messages = inputs.get("messages", [])
        last_user_msg = ""
        if messages and isinstance(messages[-1], dict):
            last_user_msg = messages[-1].get("content", "")
        elif messages:
            last_user_msg = str(messages[-1].content)

        # Phase 4 Day 5: Prepare cache context (used throughout)
        skill_name = self.skill.name if hasattr(self.skill, "name") else "network-query"
        cache_context = {
            "skill": skill_name,
            "mode": "analysis" if self.enable_summarization else "standard",
        }

        # Check query cache BEFORE expensive operations
        if last_user_msg:
            cached_result = self.query_cache.get(last_user_msg, context=cache_context)
            if cached_result:
                elapsed = time.time() - start_time
                logger.info(f"✅ Cache HIT: {last_user_msg[:50]}... ({elapsed * 1000:.2f}ms)")
                # Return cached result with updated performance metadata
                return {
                    **cached_result,
                    "performance": {
                        **cached_result.get("performance", {}),
                        "cache_hit": True,
                        "total_seconds": round(elapsed, 2),
                    },
                }

            logger.info(f"❌ Cache MISS: {last_user_msg[:50]}... (will store after execution)")

        # Phase 1: Process aliases - replace user aliases with canonical names
        logger.debug(f"Processing aliases for query: {last_user_msg}")
        original_query = last_user_msg  # Save for caching (user's original input)
        last_user_msg = self._process_aliases(last_user_msg, learn_callback=learn_callback)
        if last_user_msg != original_query:
            logger.info(f"Alias processed: {original_query} -> {last_user_msg}")
            # Update the messages with processed query
            if messages and isinstance(messages[-1], dict):
                messages[-1]["content"] = last_user_msg
            elif messages and hasattr(messages[-1], "content"):
                # For LangChain messages, create new message with processed content
                from langchain_core.messages import HumanMessage

                messages = messages[:-1] + [HumanMessage(content=last_user_msg)]

        # Store original query for caching (user's intent, not processed form)
        cache_query = original_query

        logger.debug(f"Alias processing completed in {time.time() - start_time:.2f}s")

        try:
            # Execute ReAct loop
            logger.debug(
                f"Starting agent execution in {'analysis' if self.enable_summarization else 'standard'} mode"
            )

            # Prepare agent invocation config with thread_id for checkpointer
            import uuid

            agent_config = config or {}
            if "configurable" not in agent_config:
                agent_config["configurable"] = {"thread_id": str(uuid.uuid4())}
            elif "thread_id" not in agent_config.get("configurable", {}):
                agent_config["configurable"]["thread_id"] = str(uuid.uuid4())

            if self.enable_summarization:
                # Analysis Mode: Full ReAct Loop
                final_state = await self.agent.ainvoke({"messages": messages}, config=agent_config)
            else:
                # Standard Mode returns specific AIMessage, not state dict
                # We need to wrap it to look like final_state for compatibility
                response = await self.agent.ainvoke({"messages": messages}, config=agent_config)

                # Handle different response types from DeepAgents
                if isinstance(response, dict):
                    # Response is already a state dict
                    final_state = response
                    # Extract last message for compatibility
                    all_messages = final_state.get("messages", [])
                    if all_messages:
                        last_msg = all_messages[-1]
                        msg = last_msg if hasattr(last_msg, "content") else None
                    else:
                        msg = None
                else:
                    # Response is AIMessage or list of messages
                    msg = response[-1] if isinstance(response, list) else response

                if msg and hasattr(msg, "content"):
                    result_content = str(msg.content)
                else:
                    # Fallback: use full response
                    result_content = str(response)
                    msg = None

                successful_sql = None
                tool_name = None
                params = None

                # Optimization: Execute tool call locally if present (Single-Step ReAct)
                if msg and hasattr(msg, "tool_calls") and msg.tool_calls:
                    try:
                        tc = msg.tool_calls[0]
                        tool_name = tc["name"]
                        tool_args = tc["args"]

                        # Find tool definition in skill
                        tool_def = next(
                            (
                                t
                                for t in self.skill.frontmatter.get("tools", [])
                                if t["name"] == tool_name
                            ),
                            None,
                        )

                        if tool_def:
                            # Get skill directory for relative path resolution
                            from pathlib import Path

                            skill_file = Path(self.skill.file_path)
                            skill_dir = skill_file.parent if skill_file.is_file() else skill_file

                            executor = SkillAdapter._create_executor(tool_def["script"], skill_dir)
                            # Run synchronously since tools are scripts
                            execution_result = executor(**tool_args)

                            # Normalize output
                            result_content = execution_result.get("data")
                            if result_content is None:
                                result_content = execution_result.get("results")

                            if result_content is None:
                                result_content = str(execution_result)

                            # Handle empty lists explicitly - use Chinese for test compatibility
                            if isinstance(result_content, list) and not result_content:
                                result_content = "没有发现匹配的数据 (No matching results found)"

                            successful_sql = (
                                tool_args.get("query") if tool_name == "query_database" else None
                            )
                            tool_name = tool_name
                            params = tool_args
                    except Exception as e:
                        result_content = f"Error executing tool {tool_name}: {e}"

                # Standard Mode Caching & Return
                # Phase 4 Day 5: Cache any successful query result (not limited to SQL tools)
                if cache_query and result_content:
                    # Only cache if not an execution error
                    if (
                        "Error" not in str(result_content)
                        or "not found" in str(result_content).lower()
                    ):
                        # Store in query cache for future fast retrieval
                        # Convert AIMessage to serializable format
                        serializable_msg = {
                            "role": "assistant",
                            "content": str(msg.content) if hasattr(msg, "content") else str(msg),
                        }
                        result_to_cache = {
                            "messages": [serializable_msg],
                            "result": str(result_content),
                            "sql_query": successful_sql or "",
                            "error": None,
                        }
                        mode_str = "analysis" if self.enable_summarization else "standard"
                        try:
                            self.query_cache.set(
                                cache_query,  # Use original user query
                                result_to_cache,
                                context=cache_context,
                                metadata={"mode": mode_str, "tool": tool_name or "unknown"},
                            )
                            logger.info(f"✅ Stored in cache: {cache_query[:50]}...")
                        except Exception as cache_err:
                            logger.warning(f"Cache store failed: {cache_err}")

                elapsed = time.time() - start_time
                mode_str = "analysis" if self.enable_summarization else "standard"
                return {
                    "messages": [msg],
                    "result": str(result_content),
                    "sql_query": successful_sql or "",
                    "error": None,
                    "performance": {
                        "total_seconds": round(elapsed, 2),
                        "mode": mode_str,
                        "cache_hit": False,
                    },
                }

            # Extract final answer and find successful SQL for caching
            all_messages = final_state.get("messages", [])
            last_msg_content = ""
            successful_sql = None
            tool_name = None
            params = None

            if all_messages:
                for msg in reversed(all_messages):
                    if not last_msg_content and hasattr(msg, "type") and msg.type == "ai":
                        last_msg_content = str(msg.content)

                    # Find the successful tool call (database tools)
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            name = tc["name"]
                            # Cache core database tools
                            if name in [
                                "query_database",
                                "get_device_health",
                                "find_ip_location",
                                "get_network_summary",
                                "search_ip_across_network",
                                "inspect_schema",
                            ]:
                                tool_name = name
                                params = tc["args"]
                                if name == "query_database":
                                    successful_sql = params.get("sql")

                if not last_msg_content:
                    last_msg_content = str(all_messages[-1].content)

            # Performance Optimization: Cache successful query results
            # Phase 4 Day 5: Cache any successful result (not limited to SQL tools)
            if cache_query and last_msg_content:
                # Cache if no error, or if it's a "not found" result (negative caching)
                if "Error" not in last_msg_content or "not found" in last_msg_content.lower():
                    # Convert LangChain messages to serializable format
                    serializable_messages = []
                    for m in all_messages:
                        if hasattr(m, "type"):
                            serializable_messages.append(
                                {
                                    "role": "assistant" if m.type == "ai" else m.type,
                                    "content": str(m.content),
                                }
                            )
                        else:
                            serializable_messages.append({"role": "unknown", "content": str(m)})

                    # Store in query cache
                    result_to_cache = {
                        "messages": serializable_messages,
                        "result": last_msg_content,
                        "sql_query": successful_sql or "",
                        "error": None,
                    }
                    mode_str = "analysis" if self.enable_summarization else "standard"
                    try:
                        self.query_cache.set(
                            cache_query,  # Use original user query
                            result_to_cache,
                            context=cache_context,
                            metadata={"mode": mode_str, "tool": tool_name or "unknown"},
                        )
                        logger.info(f"✅ Stored in cache: {cache_query[:50]}...")
                    except Exception as cache_err:
                        logger.warning(f"Cache store failed: {cache_err}")

            # DeepAgents typical result extraction
            elapsed = time.time() - start_time
            mode_str = "analysis" if self.enable_summarization else "standard"
            return {
                "messages": all_messages,
                "result": last_msg_content,
                "sql_query": successful_sql or "",
                "error": None,
                "performance": {
                    "total_seconds": round(elapsed, 2),
                    "mode": mode_str,
                    "cache_hit": False,
                },
            }
        except Exception as e:
            elapsed = time.time() - start_time
            mode_str = "analysis" if self.enable_summarization else "standard"
            return {
                "messages": messages,
                "result": None,
                "error": str(e),
                "performance": {"total_seconds": round(elapsed, 2), "mode": mode_str},
            }

    async def query(self, user_query: str) -> dict[str, Any]:
        """Query interface for CLI compatibility"""
        result = await self.ainvoke({"messages": [{"role": "user", "content": user_query}]})
        if result.get("error"):
            return {"status": "error", "error": result["error"]}
        return {"status": "success", "output": result.get("result", "")}

    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Synchronous version of ainvoke.

        NOTE: This method should not be called from async context.
        Use ainvoke() directly instead.
        """
        import asyncio

        try:
            # Check if we're already in an async context
            asyncio.get_running_loop()
            # If we get here, we're in async context - cannot use asyncio.run()
            raise RuntimeError(
                "invoke() cannot be called from async context. Use ainvoke() directly."
            )
        except RuntimeError as e:
            if "asyncio.run()" in str(e) or "already" in str(e).lower():
                raise e
            # No running loop, safe to proceed with asyncio.run()
            pass

        return asyncio.run(self.ainvoke(inputs))

    async def synthesis(self, user_query: str, data: Any) -> str:
        """Synthesize raw data into a friendly natural language response (Phase 4 Bypass)."""
        try:
            # Load synthesis prompt from skill
            prompts = self.skill.frontmatter.get("prompts", {})
            synthesis_template = prompts.get(
                "synthesis", "Analyze results for: {user_query}\nData: {data_snippet}"
            )

            import json

            from langchain_google_genai import ChatGoogleGenerativeAI

            data_snippet = json.dumps(data, indent=2, default=str)[:6000]

            prompt = synthesis_template.format(user_query=user_query, data_snippet=data_snippet)

            # Use native LangChain model directly
            model = ChatGoogleGenerativeAI(model=settings.llm_model_name)
            response = await model.ainvoke(prompt)
            return str(response.content)
        except Exception as e:
            return f"Synthesis failed: {e}\n\nRaw Data:\n{data}"
