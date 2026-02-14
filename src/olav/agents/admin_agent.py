#!/usr/bin/env python3
"""
Admin Agent - Ultra-minimalist system administrator for OLAV.

Architecture:
- 4 Tools: read_file, write_file, execute_command, execute_olav
- Developer Reference as system prompt
- LangGraph-based workflow
- DuckDB state persistence

Philosophy: "代码即工具" - Use shell commands directly, don't create abstractions
"""

import logging
from pathlib import Path

from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode

from config.settings import settings
from olav.core.llm import LLMFactory

logger = logging.getLogger(__name__)


class AdminAgent:
    """Admin Agent - Ultra-minimalist system administrator."""

    def __init__(
        self,
        model_name: str | None = None,
        temperature: float | None = None,
        olav_base_path: str = ".olav",
        enable_checkpointer: bool = True
    ):
        """Initialize Admin Agent.

        Args:
            model_name: LLM model to use (defaults to settings.llm_model_name)
            temperature: LLM temperature 0.0-1.0 (defaults to 0.1 for Admin)
            olav_base_path: Path to .olav directory
            enable_checkpointer: Enable state persistence (default: True)
        """
        self.model_name = model_name or settings.llm_model_name
        self.temperature = temperature if temperature is not None else 0.1  # Low temp for Admin
        self.olav_base_path = Path(olav_base_path)

        # Initialize LLM
        self.llm = LLMFactory.get_chat_model(temperature=self.temperature)

        logger.info(
            f"Admin Agent initialized: model={self.model_name}, temperature={self.temperature}"
        )

        # Initialize checkpointer
        self.checkpointer = None
        if enable_checkpointer:
            db_path = self.olav_base_path / "databases" / "admin_agent.duckdb"
            db_path.parent.mkdir(parents=True, exist_ok=True)

            try:
                import duckdb
                conn = duckdb.connect(str(db_path))
                self.checkpointer = DuckDBSaver(conn=conn)
                logger.info(f"Admin Agent checkpointer enabled: {db_path}")
            except Exception as e:
                logger.warning(f"Failed to initialize checkpointer: {e}")
                self.checkpointer = None

        # Load tools
        self.tools = self._load_admin_tools()

        # Build graph
        self.graph = self._build_graph()

    def _load_admin_tools(self) -> list:
        """Load 4 Admin tools from olav-admin skill."""
        tools = []
        admin_tools_path = self.olav_base_path / "skills" / "olav-admin" / "tools"

        if not admin_tools_path.exists():
            logger.error(f"Admin tools directory not found: {admin_tools_path}")
            return tools

        try:
            import importlib.util
            import sys

            # Add tools directory to path
            sys.path.insert(0, str(admin_tools_path))

            # Load 4 tools
            tool_files = [
                ("read_file", "read_file"),
                ("write_file", "write_file"),
                ("command_executor", "execute_command"),
                ("olav_executor", "execute_olav"),
            ]

            for file_name, tool_name in tool_files:
                try:
                    spec = importlib.util.spec_from_file_location(
                        file_name, admin_tools_path / f"{file_name}.py"
                    )
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        
                        if hasattr(module, tool_name):
                            tools.append(getattr(module, tool_name))
                            logger.info(f"Loaded admin tool: {tool_name}")
                except Exception as e:
                    logger.warning(f"Failed to load {file_name}: {e}")

            logger.info(f"Admin Agent loaded {len(tools)}/4 tools")
            
            if len(tools) < 4:
                logger.warning("Not all 4 admin tools were loaded!")

        except Exception as e:
            logger.error(f"Failed to load admin tools: {e}")

        return tools

    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow for Admin Agent."""
        # Create workflow
        workflow = StateGraph(MessagesState)

        # Create LLM with tools
        llm_with_tools = self.llm.bind_tools(self.tools)

        # Define agent node
        def call_model(state: MessagesState):
            messages = state["messages"]
            
            # Add system message with Developer Reference
            system_message = self._get_system_prompt()
            
            # Call LLM
            response = llm_with_tools.invoke([system_message] + messages)
            return {"messages": [response]}

        # Define conditional edge: continue or end?
        def should_continue(state: MessagesState):
            messages = state["messages"]
            last_message = messages[-1]
            
            # If LLM makes a tool call, continue to tools
            if last_message.tool_calls:
                return "tools"
            # Otherwise, end
            return END

        # Add nodes
        workflow.add_node("agent", call_model)
        workflow.add_node("tools", ToolNode(self.tools))

        # Add edges
        workflow.set_entry_point("agent")
        workflow.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
        workflow.add_edge("tools", "agent")

        # Compile
        graph = workflow.compile(checkpointer=self.checkpointer)
        
        return graph

    def _get_system_prompt(self) -> dict:
        """Get system prompt with Developer Reference."""
        prompt = """You are the Admin Agent - an ultra-minimalist system administrator for OLAV.

**Your Role**:
- Maintain and extend OLAV through file operations and shell commands
- Create skills, fix bugs, backup data, search code
- Use 4 simple tools: read_file, write_file, execute_command, execute_olav

**Philosophy: "代码即工具" (Code as Tool)**:
- Don't create Python wrappers for everything
- Use direct shell commands: find, grep, git, tar, python3
- Example: Instead of list_files(), use execute_command("find dir -name '*.py'")

**Your 4 Tools**:

1. **read_file(path)** - Read any file
   - No restrictions (read-only operation)
   - Examples: read_file("dev_docs/DEVELOPER_REFERENCE.md")

2. **write_file(path, content, backup=True)** - Write file
   - HITL approval required for .py files and src/
   - Auto-approved for .md, .json, .olav/
   - Examples: write_file(".olav/skills/monitoring/SKILL.md", content)

3. **execute_command(command, timeout=60, cwd=None)** ⭐ - Execute ANY shell command
   - HITL approval for: git commit/push, rm, mv
   - This replaces 5 specialized tools!
   - Examples:
     * List files: execute_command("find .olav/skills -name '*.py'")
     * Search: execute_command("grep -r 'execute_sql' .olav/")
     * Git: execute_command("git status")
     * Backup: execute_command("tar -czf backup.tar.gz .olav/")
     * Python: execute_command("python3 script.py")

4. **execute_olav(command, timeout=60)** - Test OLAV features
   - Convenience wrapper for "uv run olav <command>"
   - Examples: execute_olav("ask 'how many devices?'")

**Workflow Examples**:

User: "List all Python files in .olav/skills"
→ execute_command("find .olav/skills -name '*.py' -type f")

User: "Search for 'execute_sql' usage"
→ execute_command("grep -r 'execute_sql' .olav/ --include='*.py'")

User: "Create a monitoring skill"
→ read_file(".olav/skills/network-query/SKILL.md")  # Learn structure
→ write_file(".olav/skills/monitoring/SKILL.md", skill_content)
→ write_file(".olav/skills/monitoring/tools/check_health.py", tool_code)
→ execute_olav("ask 'test monitoring skill'")

User: "Backup OLAV data"
→ execute_command("tar -czf backup_$(date +%Y%m%d_%H%M%S).tar.gz .olav/")

User: "What's in the database?"
→ execute_olav("db-status")
→ execute_olav("db-query 'SELECT * FROM devices LIMIT 5'")

**Key Principles**:
- Use shell commands directly (find, grep, git, tar)
- Read developer docs to learn OLAV structure
- Test changes with execute_olav() before committing
- Request HITL approval for destructive operations
- Keep changes focused and tested

**References**:
- Read dev_docs/DEVELOPER_REFERENCE.md for OLAV architecture
- Check existing skills in .olav/skills/ for examples
- Use execute_command for flexibility, not specialized wrappers
"""
        return {"role": "system", "content": prompt}

    def invoke(self, message: str, thread_id: str = "default") -> str:
        """Invoke Admin Agent with a message.

        Args:
            message: User message/task
            thread_id: Thread ID for conversation state (default: "default")

        Returns:
            Agent's response as string
        """
        try:
            # Prepare config with thread_id
            config = {"configurable": {"thread_id": thread_id}} if self.checkpointer else {}

            # Invoke graph
            result = self.graph.invoke(
                {"messages": [{"role": "user", "content": message}]},
                config=config
            )

            # Extract response
            if result and "messages" in result:
                last_message = result["messages"][-1]
                if hasattr(last_message, "content"):
                    return last_message.content
                elif isinstance(last_message, dict):
                    return last_message.get("content", str(last_message))
                return str(last_message)

            return "No response from Admin Agent"

        except Exception as e:
            logger.error(f"Admin Agent invocation failed: {e}", exc_info=True)
            return f"Error: {e}"

    async def ainvoke(self, message: str, thread_id: str = "default") -> str:
        """Async invoke Admin Agent.

        Args:
            message: User message/task
            thread_id: Thread ID for conversation state

        Returns:
            Agent's response as string
        """
        try:
            config = {"configurable": {"thread_id": thread_id}} if self.checkpointer else {}

            result = await self.graph.ainvoke(
                {"messages": [{"role": "user", "content": message}]},
                config=config
            )

            if result and "messages" in result:
                last_message = result["messages"][-1]
                if hasattr(last_message, "content"):
                    return last_message.content
                elif isinstance(last_message, dict):
                    return last_message.get("content", str(last_message))
                return str(last_message)

            return "No response from Admin Agent"

        except Exception as e:
            logger.error(f"Admin Agent async invocation failed: {e}", exc_info=True)
            return f"Error: {e}"
