#!/usr/bin/env python3
"""
Admin Agent - v3.0 (DeepAgents)

Ultra-minimalist system administrator using DeepAgents framework.

Architecture: DeepAgents (simplified from LangGraph)
4 Tools: read_file, write_file, execute_shell, execute_olav

Philosophy: "代码即工具" - Use shell commands directly, don't create abstractions
"""

import logging
import sys
from pathlib import Path

from langchain_openai import ChatOpenAI
from deepagents import create_deep_agent
from config.settings import settings

logger = logging.getLogger(__name__)


def _load_admin_tools() -> list:
    """Load 4 Admin tools from olav-admin skill."""
    tools = []
    admin_tools_path = Path(".olav/skills/olav-admin/tools")

    if not admin_tools_path.exists():
        logger.error(f"Admin tools directory not found: {admin_tools_path}")
        return tools

    try:
        import importlib.util

        # Add tools directory to path
        sys.path.insert(0, str(admin_tools_path))

        # Load 4 tools
        tool_files = [
            ("read_file", "read_file"),
            ("write_file", "write_file"),
            ("command_executor", "execute_shell"),
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


def _get_system_prompt() -> str:
    """Load system prompt from skill configuration.
    
    Returns:
        System prompt content from .olav/skills/olav-admin/prompts/system.md
    """
    skill_path = Path(".olav/skills/olav-admin")
    system_prompt_path = skill_path / "prompts" / "system.md"
    
    if system_prompt_path.exists():
        try:
            return system_prompt_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to read system prompt from {system_prompt_path}: {e}")
    
    # Fallback for backward compatibility (should not reach here in normal operation)
    logger.warning("Using fallback system prompt - skill prompt file not found")
    return """You are the Admin Agent for OLAV system administration.
    
Use your 4 tools (read_file, write_file, execute_shell, execute_olav) to manage OLAV.
Refer to .olav/skills/olav-admin/prompts/system.md for full instructions.
"""


class AdminAgent:
    """Admin Agent using DeepAgents framework."""

    def __init__(
        self,
        model_name: str | None = None,
        temperature: float | None = None,
    ):
        """Initialize Admin Agent with DeepAgents.

        Args:
            model_name: LLM model to use (defaults to settings.llm_model_name)
            temperature: LLM temperature (defaults to 0.1 for Admin)
        """
        model_name = model_name or settings.llm_model_name
        temperature = temperature if temperature is not None else 0.1
        
        tools = _load_admin_tools()
        
        # Create LLM
        llm = ChatOpenAI(
            model=model_name,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=temperature,
            timeout=120
        )
        
        # Create DeepAgent graph
        self.graph = create_deep_agent(
            model=llm,
            tools=tools,
            system_prompt=_get_system_prompt()
        )
        
        logger.info(f"Admin Agent v3.0 (DeepAgents) initialized: model={model_name}")

    def invoke(self, message: str, thread_id: str = "default") -> str:
        """Invoke Admin Agent with a message.

        Args:
            message: User message/task
            thread_id: Thread ID for conversation state

        Returns:
            Agent's response as string
        """
        try:
            result = self.graph.invoke({"messages": [{"role": "user", "content": message}]})
            
            # Extract response
            if isinstance(result, dict) and "messages" in result:
                last_msg = result["messages"][-1]
                return last_msg.get("content") if isinstance(last_msg, dict) else str(last_msg)
            
            return str(result)
        except Exception as e:
            logger.error(f"Admin Agent invocation failed: {e}", exc_info=True)
            raise

    async def ainvoke(self, message: str, thread_id: str = "default") -> str:
        """Async invoke Admin Agent.

        Args:
            message: User message/task
            thread_id: Thread ID for conversation state

        Returns:
            Agent's response as string
        """
        try:
            result = await self.graph.ainvoke({"messages": [{"role": "user", "content": message}]})
            
            # Extract response
            if isinstance(result, dict) and "messages" in result:
                last_msg = result["messages"][-1]
                return last_msg.get("content") if isinstance(last_msg, dict) else str(last_msg)
            
            return str(result)
        except Exception as e:
            logger.error(f"Admin Agent async invocation failed: {e}", exc_info=True)
            raise


# Singleton instance
_admin_agent = None


def get_admin_agent() -> AdminAgent:
    """Get or create Admin Agent singleton."""
    global _admin_agent
    if _admin_agent is None:
        _admin_agent = AdminAgent()
    return _admin_agent
