"""
Fast Path Integration for QueryAgentV2

This file contains the updated ainvoke method with Fast Path support.
To apply this, replace the ainvoke method in query_agent_v2.py with the content below.
"""

async def ainvoke(self, inputs: dict[str, Any]) -> dict[str, Any]:
    """Async invoke for CLI compatibility with Fast Path integration.

    Processes messages and returns a state dictionary including 'result'.
    
    Phase 4 Fast Path Integration:
    1. Extract user query
    2. Check intent_cache for high-confidence cached plans (>0.95)
    3. If hit, execute directly (Fast Path, 3-5s)
    4. Otherwise, proceed with normal ReAct loop (Orchestrator)
    """
    import time
    start_time = time.time()

    # Extract user query
    messages = inputs.get("messages", [])
    user_query = ""
    
    if messages:
        if isinstance(messages[-1], dict):
            user_query = messages[-1].get("content", "")
        else:
            user_query = str(messages[-1].content)

    # Phase 4.1: Check intent cache (Fast Path)
    if user_query and self.mode == "standard":
        logger.info(f"Checking intent cache for query: {user_query[:50]}...")
        
        try:
            # Try to use Fast Path for cached high-confidence plans
            result = await self.intent_agent.process_query(user_query)
            
            # If IntentAgent returned a result (not Orchestrator fallback), use it
            if not result.startswith("Orchestrator mode"):
                logger.info("Fast Path: Using cached execution plan")
                elapsed = time.time() - start_time
                
                return {
                    "messages": [{"type": "ai", "content": result}],
                    "result": result,
                    "error": None,
                    "performance": {
                        "total_seconds": round(elapsed, 2),
                        "mode": f"{self.mode} (fast-path)",
                        "cache_hit": True
                    }
                }
        except Exception as e:
            logger.warning(f"Fast Path failed, falling back to Orchestrator: {e}")

    # ========== ORIGINAL ReAct LOGIC (Fallback) ==========
    # DeepAgents expects 'messages' in input
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
                    "mode": self.mode,
                    "cache_hit": False
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

            # Find successful tool call (database tools)
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc["name"]
                    # Cache core database tools
                    if name in ["query_database", "get_device_health", "find_ip_location", "get_network_summary", "search_ip_across_network", "inspect_schema"]:
                        tool_name = name
                        params = tc["args"]

                if not last_msg_content:
                    last_msg_content = str(all_messages[-1].content)

    # Performance Optimization: Cache successful SQL interaction
    # Also cache "Not Found" results (Negative Caching) for Tier 0
    if (successful_sql or tool_name or "not found" in last_msg_content.lower()) and last_user_msg:
        if "Error" not in last_msg_content:
            await self._save_to_semantic_cache(last_user_msg, successful_sql=successful_sql, tool_name=tool_name, params=params)

    # Check for "Not Found" patterns explicitly
    has_not_found = "not found" in last_msg_content.lower()

    if has_not_found:
        # Special caching for "Not Found" responses to avoid repeated failures
        await self._save_to_semantic_cache(
            last_user_msg,
            successful_sql="not_found",  # Marker for "not found" responses
            tool_name="negative_cache",
            params=None
        )

    return {
        "messages": all_messages,
        "result": last_msg_content,
        "sql_query": successful_sql if not has_not_found else None,
        "error": None if not has_not_found else "Information not found",
        "performance": {
            "total_seconds": round(time.time() - start_time, 2),
            "mode": self.mode,
            "cache_hit": False
        }
    }
