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

import logging
import json
from typing import Any
from pathlib import Path

from langchain_core.messages import BaseMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, END
from langgraph.checkpoint.duckdb import DuckDBSaver

logger = logging.getLogger(__name__)


class OLAVAgent:
    """OLAV unified Agent powered by DeepAgents framework."""

    def __init__(
        self,
        model_name: str = "gpt-4-turbo-preview",
        temperature: float = 0.1,
        olav_base_path: str = ".olav"
    ):
        """Initialize OLAV Agent.

        Args:
            model_name: LLM model to use
            temperature: LLM temperature (0.0-1.0)
            olav_base_path: Path to .olav directory
        """
        self.model_name = model_name
        self.temperature = temperature
        self.olav_base_path = Path(olav_base_path)

        # Initialize LLM
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature
        )

        # Initialize checkpointer for state persistence
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
        """Load tools from .olav/tools/."""
        tools = []
        tools_path = self.olav_base_path / "tools"

        if not tools_path.exists():
            logger.warning(f"Tools directory not found: {tools_path}")
            return tools

        try:
            # Dynamically import tool functions
            import sys
            sys.path.insert(0, str(tools_path.parent))

            # Import tools
            from .tools import database, network, inspection

            tools.extend([
                database.execute_sql,
                network.execute_cli,
                network.list_devices_inventory,
                inspection.inspect_devices,  # if available
            ])

            logger.info(f"Loaded {len(tools)} tools")
        except Exception as e:
            logger.warning(f"Failed to load tools: {e}")

        return tools

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
                            with open(skill_file, "r", encoding="utf-8") as f:
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

        # Main agent node
        def agent_node(state: MessagesState) -> MessagesState:
            """Agent decision-making node."""
            messages = state["messages"]

            # Prepare system prompt
            system_prompt = self._build_system_prompt()

            # Call LLM with tools bound
            response = self.llm.bind_tools(self.tools).invoke(
                [{"role": "system", "content": system_prompt}] + messages
            )

            return {"messages": messages + [response]}

        # Tool execution node
        async def tool_node(state: MessagesState) -> MessagesState:
            """Execute tool calls from agent."""
            messages = state["messages"]
            last_message = messages[-1]

            # Process tool calls if present
            if hasattr(last_message, "tool_calls") and last_message.tool_calls:
                tool_results = []
                for tool_call in last_message.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]

                    # Find and execute tool
                    result = None
                    for tool in self.tools:
                        if tool.name == tool_name:
                            result = tool.invoke(tool_args)
                            break

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": tool_call["id"],
                        "content": json.dumps(result)
                    })

                return {"messages": messages + tool_results}

            return {"messages": messages}

        # Add nodes to graph
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", tool_node)

        # Conditional routing
        def should_continue(state: MessagesState) -> str:
            last_message = state["messages"][-1]
            if hasattr(last_message, "tool_calls"):
                return "tools"
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
        """Build system prompt with context about available tools and skills."""
        tool_descriptions = "\n".join([
            f"- {tool.name}: {tool.description or 'Tool'}"
            for tool in self.tools
        ])

        skill_context = ""
        if self.skills:
            skill_names = ", ".join(self.skills.keys())
            skill_context = f"\n\nAvailable Skills: {skill_names}\n"
            skill_context += "Refer to applicable skills for domain-specific instructions."

        prompt = f"""You are OLAV (Open network Learning and Analytics Vector), 
an intelligent network operations assistant powered by advanced AI.

Available Tools:
{tool_descriptions}

{skill_context}

Guidelines:
1. For SQL queries, use execute_sql tool with natural language query first
2. For CLI commands, use execute_cli tool with device name and command
3. For inventory queries, use list_devices_inventory tool
4. Combine multiple tools when needed for comprehensive analysis
5. Always explain your reasoning before executing tools
6. If data is insufficient, ask clarifying questions

Respond in a clear, structured format."""

        return prompt

    async def invoke(self, query: str, thread_id: str | None = None) -> dict:
        """Invoke the agent with a query.

        Args:
            query: User natural language query
            thread_id: Optional thread ID for conversation continuity

        Returns:
            Agent response
        """
        try:
            # Prepare input
            input_data = {"messages": [{"role": "user", "content": query}]}

            # Configure runtime
            config = None
            if thread_id and self.checkpointer:
                config = {"configurable": {"thread_id": thread_id}}

            # Execute graph
            result = self.graph.invoke(input_data, config=config)

            # Extract final response
            messages = result.get("messages", [])
            if messages:
                last_message = messages[-1]
                return {
                    "status": "success",
                    "response": last_message.content if hasattr(last_message, "content") else str(last_message),
                    "thread_id": thread_id
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
