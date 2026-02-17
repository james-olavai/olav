#!/usr/bin/env python3
"""
Command Learner Agent - v3.0 (DeepAgents)

Autonomous TextFSM template learning using DeepAgents framework.

6-Step Workflow:
1. Execute command on device
2. Analyze output (LLM-powered field detection)
3. User approval (HITL)
4. Search NTC templates for references
5. Generate template (LLM + NTC references)
6. Save template (with auto-reload)

Architecture: DeepAgents (simplified from LangGraph)
"""

import logging
import sys
from pathlib import Path

from deepagents import create_deep_agent
from config.settings import settings

logger = logging.getLogger(__name__)


def find_ntc_templates_path() -> str:
    """Locate ntc-templates installation directory."""
    try:
        import ntc_templates
        ntc_path = Path(ntc_templates.__file__).parent / "templates"
        return str(ntc_path)
    except ImportError:
        return "ntc-templates not installed"


def _load_tools() -> list:
    """Load command learner tools."""
    # Add tools path
    tools_path = Path(".olav/skills/command_learner/tools")
    if str(tools_path) not in sys.path:
        sys.path.insert(0, str(tools_path))
    
    # Import tools
    from execute_command import execute_command
    from analyze_output import analyze_output
    from ntc_search import search_ntc_templates
    from template_reader import read_template_file
    from ntc_browser import browse_ntc_directory
    from template_generator import generate_template
    from template_saver import save_template
    
    return [
        execute_command,
        analyze_output,
        search_ntc_templates,
        read_template_file,
        browse_ntc_directory,
        generate_template,
        save_template,
    ]


def _get_system_prompt() -> str:
    """Load system prompt from skill configuration.
    
    Returns:
        System prompt content from .olav/skills/command_learner/prompts/system.md
        with NTC templates path injected.
    """
    skill_path = Path(".olav/skills/command_learner")
    system_prompt_path = skill_path / "prompts" / "system.md"
    
    if system_prompt_path.exists():
        try:
            prompt = system_prompt_path.read_text(encoding="utf-8")
            
            # Inject NTC templates path dynamically
            ntc_path = find_ntc_templates_path()
            prompt = prompt.replace("Local pip package `ntc-templates`", 
                                  f"Local pip package `ntc-templates` ({ntc_path})")
            
            return prompt
        except Exception as e:
            logger.warning(f"Failed to read system prompt from {system_prompt_path}: {e}")
    
    # Fallback for backward compatibility
    logger.warning("Using fallback system prompt - skill prompt file not found")
    ntc_path = find_ntc_templates_path()
    return f"""You are a TextFSM template learning assistant.

Your task: Learn new network commands and generate accurate TextFSM templates.
NTC-Templates Reference: {ntc_path}

Refer to .olav/skills/command_learner/prompts/system.md for full workflow instructions.
"""


class CommandLearnerAgent:
    """Command Learner Agent using DeepAgents framework."""
    
    def __init__(self):
        """Initialize Command Learner Agent with DeepAgents."""
        from langchain_openai import ChatOpenAI
        
        tools = _load_tools()
        
        # Create LLM
        llm = ChatOpenAI(
            model=settings.llm_model_name,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.1,  # Low temperature for precision
            timeout=120
        )
        
        # Create DeepAgent graph
        self.graph = create_deep_agent(
            model=llm,
            tools=tools,
            system_prompt=_get_system_prompt()
        )
        
        logger.info("Command Learner Agent v3.0 (DeepAgents) initialized")
    
    def invoke(self, query: str, thread_id: str = "default") -> str:
        """Invoke agent synchronously."""
        try:
            result = self.graph.invoke({"messages": [{"role": "user", "content": query}]})
            
            # Extract response
            if isinstance(result, dict) and "messages" in result:
                last_msg = result["messages"][-1]
                return last_msg.get("content") if isinstance(last_msg, dict) else str(last_msg)
            
            return str(result)
        except Exception as e:
            logger.error(f"Agent invocation failed: {e}")
            raise
    
    async def ainvoke(self, query: str, thread_id: str = "default") -> str:
        """Invoke agent asynchronously."""
        try:
            result = await self.graph.ainvoke({"messages": [{"role": "user", "content": query}]})
            
            # Extract response
            if isinstance(result, dict) and "messages" in result:
                last_msg = result["messages"][-1]
                return last_msg.get("content") if isinstance(last_msg, dict) else str(last_msg)
            
            return str(result)
        except Exception as e:
            logger.error(f"Async agent invocation failed: {e}")
            raise


# Singleton instance
_command_learner_agent = None


def get_command_learner_agent() -> CommandLearnerAgent:
    """Get or create Command Learner Agent singleton."""
    global _command_learner_agent
    if _command_learner_agent is None:
        _command_learner_agent = CommandLearnerAgent()
    return _command_learner_agent
