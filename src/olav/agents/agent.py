#!/usr/bin/env python3
"""
OLAV Deep Agent - Single unified agent with DeepAgents framework.

Architecture:
- 1 Agent + 3 Tools (database, network, inspection)
- Dynamic Skill loading based on user query
- DuckDB-based state persistence
- LLM decision-making for tool selection

This replaces: 5 SubAgents + 1,077 lines of routing logic
"""

import json
import logging
from pathlib import Path

from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.graph import END, MessagesState, StateGraph

from config.settings import settings
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class OLAVAgent:
    """OLAV unified Agent powered by DeepAgents framework."""

    def __init__(
        self,
        model_name: str | None = None,
        temperature: float | None = None,
        olav_base_path: str = ".olav",
        enable_checkpointer: bool = True
    ):
        """Initialize OLAV Agent.

        Args:
            model_name: LLM model to use (defaults to settings.llm_model_name)
            temperature: LLM temperature 0.0-1.0 (defaults to settings.llm_temperature)
            olav_base_path: Path to .olav directory
            enable_checkpointer: Enable state persistence with DuckDB (default: True)
        """
        # Use settings if not provided
        self.model_name = model_name or settings.llm_model_name
        self.temperature = temperature if temperature is not None else settings.llm_temperature
        self.olav_base_path = Path(olav_base_path)

        # Initialize LLM using LLMFactory for third-party API support (OpenRouter, Groq, etc.)
        # This respects .env configuration: LLM_PROVIDER, LLM_BASE_URL, LLM_API_KEY, etc.
        self.llm = LLMFactory.get_chat_model(temperature=self.temperature)

        logger.info(
            f"OLAV Agent initialized with: "
            f"provider={settings.llm_provider}, "
            f"model={self.model_name}, "
            f"temperature={self.temperature}"
        )
        if settings.llm_base_url:
            logger.info(f"Using custom LLM endpoint: {settings.llm_base_url}")

        # Initialize checkpointer for state persistence
        self.checkpointer = None
        if enable_checkpointer:
            db_path = self.olav_base_path / "databases" / "agent.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                import duckdb
                conn = duckdb.connect(str(db_path))
                self.checkpointer = DuckDBSaver(conn=conn)
            except Exception as e:
                logger.warning(f"Failed to initialize DuckDBSaver: {e}. Using memory persistence.")
                self.checkpointer = None

        # Load tools and skills
        self.tools = self._load_tools()
        self.skills = self._load_skills()

        # Build graph
        self.graph = self._build_graph()

    def _load_tools(self) -> list:
        """Load tools from .olav/tools/ with improved clarity and error handling.
        
        Tools are loaded dynamically from individual modules (database, network, inspection).
        Each tool must be decorated with @tool from langchain_core.tools.
        
        Returns:
            List of available LangChain tools
        """
        tools = []
        tools_path = self.olav_base_path / "tools"

        if not tools_path.exists():
            logger.warning(f"Tools directory not found: {tools_path}")
            return tools

        import sys
        sys.path.insert(0, str(tools_path))

        # Define tools with module and function names for clarity
        # Format: (tool_name, module_name)
        tool_specs = [
            ("execute_sql", "database"),
            ("execute_cli", "network"),
            ("list_devices_inventory", "network"),
            ("manage_inspection_schedule", "inspection"),
        ]

        for tool_name, module_name in tool_specs:
            try:
                # Direct import is simpler and clearer than dynamic spec loading
                module = __import__(module_name)
                if hasattr(module, tool_name):
                    tool = getattr(module, tool_name)
                    tools.append(tool)
                    logger.debug(f"✓ Loaded tool: {tool_name} from {module_name}")
                else:
                    logger.warning(f"✗ Tool '{tool_name}' not found in module '{module_name}'")
            except ImportError as e:
                logger.warning(f"✗ Failed to import module '{module_name}': {e}")
            except Exception as e:
                logger.error(f"✗ Error loading tool '{tool_name}': {e}")

        logger.info(f"✓ Loaded {len(tools)} tools from {tools_path}")
        return tools

    def _get_system_prompt(self) -> str:
        """Load system prompt from shared skill configuration.
        
        Returns:
            System prompt text from .olav/skills/shared/prompts/system.md,
            or a minimal fallback if file doesn't exist.
        """
        shared_prompt_path = self.olav_base_path / "skills" / "shared" / "prompts" / "system.md"
        
        if shared_prompt_path.exists():
            try:
                return shared_prompt_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Failed to read shared prompt: {e}")
        
        # Minimal fallback - only for edge cases
        return """You are OLAV, an intelligent network operations assistant.
Use available tools to help with network queries and operations."""

    def _load_skills(self) -> dict:
        """Load and parse skills from .olav/skills/."""
        skills = {}
        skills_path = self.olav_base_path / "skills"

        if not skills_path.exists():
            logger.warning(f"Skills directory not found: {skills_path}")
            return skills

        try:
            import frontmatter

            for skill_dir in skills_path.iterdir():
                if skill_dir.is_dir():
                    skill_file = skill_dir / "SKILL.md"
                    if skill_file.exists():
                        try:
                            with open(skill_file, encoding="utf-8") as f:
                                post = frontmatter.load(f)
                                skills[skill_dir.name] = {
                                    "frontmatter": post.metadata,
                                    "content": post.content,
                                    "path": str(skill_dir)
                                }
                        except Exception as e:
                            logger.warning(f"Failed to parse skill {skill_dir.name}: {e}")

            logger.info(f"Loaded {len(skills)} skills")
        except ImportError:
            logger.warning("python-frontmatter not installed. Skipping skill parsing.")

        return skills

    def _build_graph(self) -> StateGraph:
        """Build agent execution graph using LangGraph."""
        workflow = StateGraph(MessagesState)

        # Main agent node (async for graph.ainvoke compatibility)
        async def agent_node(state: MessagesState) -> MessagesState:
            """Agent decision-making node."""
            logger.info(f"[agent_node] Entered with {len(state['messages'])} messages")
            messages = state["messages"]

            # Prepare system prompt
            system_prompt = self._build_system_prompt()
            logger.info(f"[agent_node] System prompt length: {len(system_prompt)} chars")

            # Call LLM with tools bound (use ainvoke for async)
            logger.info(f"[agent_node] Calling LLM with {len(self.tools)} tools bound...")
            response = await self.llm.bind_tools(self.tools).ainvoke(
                [{"role": "system", "content": system_prompt}] + messages
            )
            logger.info(f"[agent_node] LLM response received: {type(response)}")

            return {"messages": messages + [response]}

        # Tool execution node (synchronous - must match graph.invoke usage)
        def tool_node(state: MessagesState) -> MessagesState:
            """Execute tool calls from agent."""
            logger.info(f"[tool_node] Entered with {len(state['messages'])} messages")
            messages = state["messages"]
            last_message = messages[-1]
            logger.info(f"[tool_node] Last message type: {type(last_message)}")

            # Process tool calls if present
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                logger.info(f"[tool_node] Processing {len(last_message.tool_calls)} tool calls")
                tool_results = []
                for i, tool_call in enumerate(last_message.tool_calls):
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_call_id = tool_call["id"]
                    logger.info(f"[tool_node] Tool {i+1}: {tool_name} with args: {tool_args}")

                    # Find and execute tool (handles both plain functions and Tool objects)
                    result = None
                    for tool in self.tools:
                        # Check if tool is a plain function or Tool object
                        func_name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
                        if func_name == tool_name:
                            logger.info(f"[tool_node] Executing tool: {tool_name}")
                            try:
                                # Execute tool (handle both Tool.invoke() and direct function call)
                                if hasattr(tool, "invoke"):
                                    result = tool.invoke(tool_args)
                                else:
                                    result = tool(**tool_args)
                                logger.info(f"[tool_node] Tool {tool_name} result: {str(result)[:200]}")
                            except Exception as e:
                                logger.error(f"[tool_node] Tool {tool_name} failed: {e}")
                                result = f"Error executing {tool_name}: {e}"
                            break

                    if result is None:
                        logger.warning(f"[tool_node] Tool {tool_name} not found!")
                        result = f"Tool '{tool_name}' not found"

                    # Use ToolMessage for proper LangChain message format
                    from langchain_core.messages import ToolMessage
                    tool_results.append(ToolMessage(
                        content=json.dumps(result) if not isinstance(result, str) else result,
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    ))

                logger.info(f"[tool_node] Returning {len(tool_results)} tool results")
                return {"messages": messages + tool_results}
            else:
                logger.info(f"[tool_node] No tool calls in last message")

            return {"messages": messages}

        # Add nodes to graph
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)

        # Conditional routing
        def should_continue(state: MessagesState) -> str:
            last_message = state["messages"][-1]
            # Check if tool_calls exist AND are non-empty
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                logger.info(f"[should_continue] Routing to tools ({len(last_message.tool_calls)} calls)")
                return "tools"
            logger.info(f"[should_continue] Ending (no tool calls)")
            return END

        workflow.add_edge("tools", "agent")
        workflow.add_conditional_edges(
            "agent",
            should_continue,
        )

        # Set entry point
        workflow.set_entry_point("agent")

        # Compile with checkpointer if available
        if self.checkpointer:
            return workflow.compile(checkpointer=self.checkpointer)
        else:
            return workflow.compile()

    def _build_system_prompt(self) -> str:
        """Build system prompt with context about available tools and skills.
        
        Loads base prompt from shared skill and injects dynamic tool/skill context.
        """
        # Get base prompt from shared skill
        base_prompt = self._get_system_prompt()
        
        # Add dynamic tool context
        tool_descriptions = "\n".join([
            f"- **{tool.name}**: {tool.description or 'Tool'}"
            for tool in self.tools
        ])
        
        # Add skill context if available
        skill_names = ", ".join(self.skills.keys()) if self.skills else "None"
        
        # Inject dynamic context
        context_section = f"""
## Runtime Context

**Available Tools**:
{tool_descriptions}

**Loaded Skills**: {skill_names}
"""
        
        return base_prompt + context_section

    async def invoke(self, query: str, thread_id: str | None = None) -> dict:
        """Invoke the agent with a query.

        Args:
            query: User natural language query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            Agent response
        """
        try:
            logger.info(f"[invoke] Starting with query: {query[:100]}")
            # Prepare input
            input_data = {"messages": [{"role": "user", "content": query}]}
            logger.info(f"[invoke] Input data prepared")

            # Configure runtime - always provide config if checkpointer exists
            config = None
            if self.checkpointer:
                config = {
                    "configurable": {
                        "thread_id": thread_id or f"default-{id(input_data)}"
                    }
                }
                logger.info(f"[invoke] Using checkpointer with thread_id: {config['configurable']['thread_id']} ")
            else:
                logger.info(f"[invoke] Checkpointer disabled, using memory only")

            # Execute graph
            logger.info(f"[invoke] Calling graph.ainvoke()...")
            result = await self.graph.ainvoke(input_data, config=config)
            logger.info(f"[invoke] Graph execution completed successfully")

            # Extract final response
            messages = result.get("messages", [])
            logger.info(f"[invoke] Received {len(messages)} messages from graph")
            if messages:
                last_message = messages[-1]
                return {
                    "status": "success",
                    "response": last_message.content if hasattr(last_message, "content") else str(last_message),
                    "thread_id": thread_id or "default"
                }

            return {"status": "error", "message": "No response generated"}

        except Exception as e:
            logger.error(f"Agent invocation failed: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    async def stream(self, query: str, thread_id: str | None = None):
        """Stream agent response for real-time feedback.

        Args:
            query: User natural language query
            thread_id: Optional thread ID for conversation continuity

        Yields:
            Streaming events
        """
        try:
            input_data = {"messages": [{"role": "user", "content": query}]}
            config = None
            if thread_id and self.checkpointer:
                config = {"configurable": {"thread_id": thread_id}}

            for event in self.graph.stream(input_data, config=config):
                yield event

        except Exception as e:
            logger.error(f"Agent stream failed: {e}", exc_info=True)
            yield {"error": str(e)}


# Factory function for creating agent instances
def create_olav_agent(**kwargs) -> OLAVAgent:
    """Create an OLAV Agent instance.

    Args:
        **kwargs: Configuration parameters (model_name, temperature, olav_base_path)

    Returns:
        OLAVAgent instance
    """
    return OLAVAgent(**kwargs)


if __name__ == "__main__":
    import asyncio

    async def main():
        agent = create_olav_agent()
        result = await agent.invoke("How many devices do we have?")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    asyncio.run(main())
