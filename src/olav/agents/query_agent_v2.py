"""
Query Agent V2 - ReAct Powered by DeepAgents

This module provides the QueryAgentV2 class which uses the DeepAgents framework
to implement a self-healing, caching, and introspection-capable network query agent.
"""

from pathlib import Path
from typing import Any

from deepagents import create_deep_agent
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SkillsMiddleware

from olav.agents.intent_agent import IntentAgent
from olav.core.llm import LLMFactory
from olav.core.skill_adapter import SkillAdapter
from olav.core.skill_loader import get_skill_loader


class QueryAgentV2:
    """Query Agent using DeepAgents ReAct architecture"""

    def __init__(self, mode: str = "standard", skill_name: str = "network-query") -> None:
        """Initialize QueryAgentV2.
        
        Args:
            mode: "standard" (Zero-shot, Fast) or "analysis" (ReAct, Slow).
            skill_name: Name of the skill to load (e.g., "network-query", "bgp-expert").
        """
        self.mode = mode
        self.skill_loader = get_skill_loader()
        self.skill = self.skill_loader.get_skill(skill_name)

        # Phase 4: Initialize IntentAgent for Fast Path
        self.intent_agent = IntentAgent()

        # 1. Load tools dynamically from Skill metadata (Agent-Agnostic)
        self.tools = SkillAdapter.load_tools_from_skill(self.skill)

        # 2. Setup Skills Middleware (Native AgentSkills support)
        project_root = Path.cwd()
        backend = FilesystemBackend(root_dir=str(project_root))
        
        # Sources are relative to backend root
        self.skills_middleware = SkillsMiddleware(
            backend=backend,
            sources=[".olav/skills/"]
        )

        # 3. Load external prompts
        prompts = self.skill.frontmatter.get("prompts", {})
        system_prompt_path = prompts.get("system", ".olav/prompts/react_system.txt")
        base_system_prompt = self._load_prompt_content(system_prompt_path)

        # 4. Inject dynamic metadata (Phase 4.3 Optimization)
        self.system_prompt = self._inject_metadata(base_system_prompt)

        # 5. Create the DeepAgent (LangGraph Compiled Graph)
        model = LLMFactory.get_chat_model()
        
        if self.mode == "analysis":
            # Tier 2: Full ReAct Loop (Federated specialist)
            self.agent = create_deep_agent(
                model=model,
                tools=self.tools,
                system_prompt=self.system_prompt,
                middleware=[self.skills_middleware]
            )
        else:
            # Tier 1: Standard (Zero-Shot Pipeline)
            # Use raw LLM with bound tools, completely bypassing DeepAgents graph
            from langchain_core.prompts import ChatPromptTemplate
            
            # Filter out caching tools to force direct SQL generation (Single-Step)
            # Since Standard Mode doesn't iterate, checking cache (Step 1) results in premature stop.
            fast_tools = [t for t in self.tools if t.name != "get_cached_sql"]
            
            # Create a simple chain: Prompt -> LLM.bind_tools -> Result
            prompt = ChatPromptTemplate.from_messages([
                ("system", self.system_prompt + "\nIMPORTANT: You are a fast execution agent. Do not iterate. Generate the SQL or Tool call immediately. Do NOT use get_cached_sql."),
                ("user", "{messages}")
            ])
            
            # Bind tools to model
            model_with_tools = model.bind_tools(fast_tools)
            self.agent = prompt | model_with_tools

    def _inject_metadata(self, prompt: str) -> str:
        """Inject current snapshot date and available views into prompt."""
        try:
            from olav.core.unified_database import UnifiedDatabase
            
            with UnifiedDatabase() as db:
                # 1. Get snapshot info
                meta = db.query("SELECT snapshot_date, device_count FROM commands.snapshot_metadata ORDER BY snapshot_date DESC LIMIT 1")
                date_str = str(meta[0][0]) if meta else "Unknown"
                devices = meta[0][1] if meta else 0

                # 2. Get available views
                views = db.query("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main' AND table_type = 'VIEW'")
                view_list = ", ".join([v[0] for v in views])

            context = f"\n\n### Current Environment Context\n"
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
            except Exception:
                pass

        # Otherwise treat as direct content
        return prompt_value

    async def _save_to_semantic_cache(
        self, 
        user_query: str, 
        successful_sql: str | None = None,
        tool_name: str | None = None,
        params: dict[str, Any] | None = None
    ) -> None:
        """Save a successful query interaction to semantic cache."""
        try:
            from olav.core.embeddings import get_embedder
            from olav.core.unified_database import UnifiedDatabase
            
            embedder = get_embedder()
            embedding = embedder.embed_query(user_query)
            
            action = {
                "expert": "database",
                "tool": tool_name if tool_name else ("query_database" if successful_sql else None),
                "params": params if params else ({"sql": successful_sql} if successful_sql else {}),
                "sql": successful_sql,
                "intent": "database"
            }
            
            with UnifiedDatabase() as db:
                db.save_semantic_cache(user_query, embedding, action)
        except Exception:
            pass

    async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Async invoke for CLI compatibility.

        Processes messages and returns a state dictionary including 'result'.
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

        try:
            # Execute ReAct loop
            if self.mode == "analysis":
                 final_state = await self.agent.ainvoke({"messages": messages})
            else:
                 # Standard Mode returns specific AIMessage, not state dict
                 # We need to wrap it to look like final_state for compatibility
                 response = await self.agent.ainvoke({"messages": messages})
                 # If response is a list, take the last one (rare in simple chain)
                 msg = response[-1] if isinstance(response, list) else response
                 
                 result_content = str(msg.content)
                 successful_sql = None
                 tool_name = None
                 params = None
                 
                 # Optimization: Execute tool call locally if present (Single-Step ReAct)
                 if hasattr(msg, "tool_calls") and msg.tool_calls:
                     try:
                         tc = msg.tool_calls[0]
                         tool_name = tc["name"]
                         tool_args = tc["args"]
                         
                         # Find tool definition in skill
                         tool_def = next((t for t in self.skill.frontmatter.get("tools", []) if t["name"] == tool_name), None)
                         
                          
                         if tool_def:
                             executor = SkillAdapter._create_executor(tool_def["script"])
                             # Run synchronously since tools are scripts
                             execution_result = executor(**tool_args)
                             
                             # Normalize output
                             result_content = execution_result.get("data")
                             if result_content is None:
                                 result_content = execution_result.get("results")
                             
                             if result_content is None:
                                 result_content = str(execution_result)
                             
                             # Handle empty lists explicitly
                             if isinstance(result_content, list) and not result_content:
                                 result_content = "No results found."

                             successful_sql = tool_args.get("query") if tool_name == "query_database" else None
                             tool_name = tool_name
                             params = tool_args
                     except Exception as e:
                         result_content = f"Error executing tool {tool_name}: {e}"

                 # Standard Mode Caching & Return
                 # We return immediately to avoid ReAct message extraction logic overwriting our result
                 if (successful_sql or tool_name) and last_user_msg:
                     # Only cache if not an execution error (unless it's a "Not Found" result)
                     if "Error" not in str(result_content) or "not found" in str(result_content).lower():
                          await self._save_to_semantic_cache(last_user_msg, successful_sql=successful_sql, tool_name=tool_name, params=params)

                 elapsed = time.time() - start_time
                 return {
                     "messages": [msg],
                     "result": str(result_content),
                     "sql_query": successful_sql or "",
                     "error": None,
                     "performance": {
                         "total_seconds": round(elapsed, 2),
                         "mode": self.mode
                     }
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
                            if name in ["query_database", "get_device_health", "find_ip_location", "get_network_summary", "search_ip_across_network", "inspect_schema"]:
                                tool_name = name
                                params = tc["args"]
                                if name == "query_database":
                                    successful_sql = params.get("sql")

                if not last_msg_content:
                    last_msg_content = str(all_messages[-1].content)

            # Performance Optimization: Cache successful SQL interaction
            # Also cache "Not Found" results (Negative Caching) for Tier 0
            if (successful_sql or tool_name or "not found" in last_msg_content.lower()) and last_user_msg:
                if "Error" not in last_msg_content or "not found" in last_msg_content.lower():
                     await self._save_to_semantic_cache(last_user_msg, successful_sql=successful_sql, tool_name=tool_name, params=params)

            # DeepAgents typical result extraction
            elapsed = time.time() - start_time
            return {
                "messages": all_messages,
                "result": last_msg_content,
                "sql_query": successful_sql or "",
                "error": None,
                "performance": {
                    "total_seconds": round(elapsed, 2),
                    "mode": self.mode
                }
            }
        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "messages": messages,
                "result": None,
                "error": str(e),
                "performance": {
                    "total_seconds": round(elapsed, 2),
                    "mode": self.mode
                }
            }

    async def query(self, user_query: str) -> dict[str, Any]:
        """Query interface for CLI compatibility"""
        result = await self.ainvoke({"messages": [{"role": "user", "content": user_query}]})
        if result.get("error"):
            return {"status": "error", "error": result["error"]}
        return {"status": "success", "output": result.get("result", "")}

    def invoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
        """Synchronous version of ainvoke"""
        import asyncio

        return asyncio.run(self.ainvoke(inputs))

    async def synthesis(self, user_query: str, data: Any) -> str:
        """Synthesize raw data into a friendly natural language response (Phase 4 Bypass)."""
        try:
            # Load synthesis prompt from skill
            prompts = self.skill.frontmatter.get("prompts", {})
            synthesis_template = prompts.get("synthesis", "Analyze results for: {user_query}\nData: {data_snippet}")
            
            import json
            data_snippet = json.dumps(data, indent=2, default=str)[:6000]
            
            prompt = synthesis_template.format(
                user_query=user_query,
                data_snippet=data_snippet
            )
            
            model = LLMFactory.get_chat_model()
            response = await model.ainvoke(prompt)
            return str(response.content)
        except Exception as e:
            return f"Synthesis failed: {e}\n\nRaw Data:\n{data}"
