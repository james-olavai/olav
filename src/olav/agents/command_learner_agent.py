#!/usr/bin/env python3
"""
Command Learner Agent - v2.1.0

Autonomous TextFSM template learning and generation.

6-Step Workflow:
1. Execute command on device
2. Analyze output (LLM-powered field detection)
3. User approval (HITL)
4. Search NTC templates for references
5. Generate template (LLM + NTC references)
6. Save template (with auto-reload)
"""

import logging
from pathlib import Path

from langgraph.checkpoint.duckdb import DuckDBSaver
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langchain_openai import ChatOpenAI

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


class CommandLearnerAgent:
    """
    Command Learner Agent - Autonomous TextFSM template learning.
    
    Architecture:
    - 7 tools (execute_command, analyze_output, search_ntc_templates, 
                read_template_file, browse_ntc_directory, generate_template, save_template)
    - LangGraph workflow
    - DuckDB state persistence
    - NTC-templates integration
    """
    
    def __init__(self):
        """Initialize Command Learner Agent."""
        # Load tools
        self.tools = self._load_tools()
        
        # Lazy LLM initialization (created on first use to ensure .env loaded)
        self._llm = None
        self._llm_with_tools = None
        
        # Create workflow
        self.graph = self._build_graph()
        
        # Create checkpointer
        db_path = Path(".olav/databases/command_learner.duckdb")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.checkpointer = DuckDBSaver(str(db_path))
        
        # Compile workflow
        self.app = self.graph.compile(checkpointer=self.checkpointer)
        
        logger.info("Command Learner Agent initialized")
    
    @property
    def llm(self):
        """Lazy initialization of LLM (ensures .env loaded)."""
        if self._llm is None:
            self._llm = ChatOpenAI(
                model=settings.llm_model_name,
                temperature=0.1,
                timeout=120
            )
        return self._llm
    
    @property
    def llm_with_tools(self):
        """Lazy initialization of LLM with tools."""
        if self._llm_with_tools is None:
            self._llm_with_tools = self.llm.bind_tools(self.tools)
        return self._llm_with_tools
    
    def _load_tools(self) -> list:
        """Load command learner tools."""
        import sys
        
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
    
    def _build_graph(self) -> StateGraph:
        """Build LangGraph workflow."""
        # Create graph
        graph = StateGraph(MessagesState)
        
        # Add nodes
        graph.add_node("agent", self._agent_node)
        graph.add_node("tools", ToolNode(self.tools))
        
        # Add edges
        graph.add_edge(START, "agent")
        graph.add_conditional_edges(
            "agent",
            self._should_continue,
            {
                "continue": "tools",
                "end": END
            }
        )
        graph.add_edge("tools", "agent")
        
        return graph
    
    def _agent_node(self, state: MessagesState) -> MessagesState:
        """Agent reasoning node."""
        response = self.llm_with_tools.invoke(state["messages"])
        return {"messages": [response]}
    
    def _should_continue(self, state: MessagesState) -> str:
        """Determine if workflow should continue."""
        last_message = state["messages"][-1]
        
        # If LLM calls tools, continue
        if hasattr(last_message, "tool_calls") and last_message.tool_calls:
            return "continue"
        
        # Otherwise, end
        return "end"
    
    def _get_system_prompt(self) -> str:
        """Get system prompt for agent."""
        ntc_path = find_ntc_templates_path()
        
        return f"""
You are a TextFSM template learning assistant.

Your task: Learn new network commands and generate accurate TextFSM templates.

NTC-Templates Reference: {ntc_path}
(856 high-quality templates available for reference)

6-Step Workflow:
1. Execute command on device (use execute_command tool)
2. Analyze output and identify fields (use analyze_output tool)
3. Get user approval for fields (HITL - wait for user confirmation)
4. Search NTC templates for similar commands (use search_ntc_templates)
   - Returns metadata + paths only (saves tokens)
   - Use read_template_file to load full content of top 1-2 matches
5. Generate TextFSM template (use generate_template with NTC references)
   - Template must parse > 80% of output
   - All approved fields must be extracted
6. Save template and trigger reload (use save_template)

Quality standards:
- Parse coverage > 80%
- All approved fields must be extracted
- Template must be testable against actual output
- Follow TextFSM best practices from NTC references

Token Optimization:
- Step 4: search_ntc_templates returns metadata only
- Use browse_ntc_directory to explore templates first (optional)
- Use read_template_file to load full content of selected templates (1-2 only)
- This saves tokens vs loading all template content upfront

Your tools:
1. execute_command(device, command) - Run command on device
2. analyze_output(command, output, platform) - LLM field detection
3. search_ntc_templates(platform, command, fields) - Search NTC (metadata)
4. read_template_file(path) - Load full template content
5. browse_ntc_directory(platform?, limit?) - Browse NTC templates
6. generate_template(command, platform, fields, output, ntc_refs) - Generate template
7. save_template(template, filename, metadata) - Save + auto-reload

Remember:
- Ask user to approve fields before generating template
- Use NTC templates as high-quality references
- Test template against actual output
- Iterate up to 3 times if generation fails
"""
    
    def invoke(self, query: str, thread_id: str = "default") -> str:
        """Invoke agent synchronously."""
        # Add system prompt
        system_message = {"role": "system", "content": self._get_system_prompt()}
        user_message = {"role": "user", "content": query}
        
        # Invoke
        config = {"configurable": {"thread_id": thread_id}}
        result = self.app.invoke(
            {"messages": [system_message, user_message]},
            config=config
        )
        
        # Extract response
        if result and "messages" in result:
            last_message = result["messages"][-1]
            return last_message.content
        return "No response"
    
    async def ainvoke(self, query: str, thread_id: str = "default") -> str:
        """Invoke agent asynchronously."""
        # Add system prompt
        system_message = {"role": "system", "content": self._get_system_prompt()}
        user_message = {"role": "user", "content": query}
        
        # Invoke
        config = {"configurable": {"thread_id": thread_id}}
        result = await self.app.ainvoke(
            {"messages": [system_message, user_message]},
            config=config
        )
        
        # Extract response
        if result and "messages" in result:
            last_message = result["messages"][-1]
            return last_message.content
        return "No response"


# Create singleton instance
def create_command_learner_agent() -> CommandLearnerAgent:
    """Create Command Learner Agent instance."""
    return CommandLearnerAgent()


# Singleton instance
command_learner_agent = None


def get_command_learner_agent() -> CommandLearnerAgent:
    """Get or create Command Learner Agent singleton."""
    global command_learner_agent
    if command_learner_agent is None:
        command_learner_agent = create_command_learner_agent()
    return command_learner_agent
