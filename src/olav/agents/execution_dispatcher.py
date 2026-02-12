"""Execution Dispatcher: Route-specific execution handlers.

Responsibilities:
1. CLI route execution (real-time device commands)
2. SIMPLE route execution (database queries)
3. EXPERT route execution (complex analysis)
4. MULTI_AGENT route execution (cross-system comparison)
5. Query parsing: device and command extraction
6. Command inference based on query intent

Design Principles:
✅ Direct execution for high-confidence routes (CLI, SIMPLE)
✅ Fallback to Orchestrator for complex routes (EXPERT, MULTI_AGENT)
✅ Smart batch processing for multi-command scenarios
✅ Device/command extraction with Chinese support
"""

import hashlib
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ExecutionDispatcher:
    """Route-specific execution handler.
    
    Manages direct execution for high-confidence routes
    and fallback for complex scenarios.
    """
    
    def route_and_execute(
        self,
        query: str,
        decision: dict[str, Any],
        confidence_threshold: float = 0.75,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Route and execute query based on Guard decision.
        
        High-confidence routes bypass Orchestrator for efficiency.
        Low-confidence (<0.75) falls back to Orchestrator planning.
        
        Architecture:
            CLI → NetworkExecutor (direct)
            SIMPLE → query_database tool (direct)
            EXPERT → Orchestrator (currently no standalone Expert)
            UNKNOWN → Orchestrator (fallback)
        
        Args:
            query: User's natural language query
            decision: Guard routing decision
            confidence_threshold: Min confidence to skip Orchestrator (default 0.75)
            user_id: User ID for feature flags
        
        Returns:
            Dict with status, final_answer, error_message
        """
        route_code = decision.get("route_code")
        confidence = decision.get("confidence", 0.0)
        
        logger.info(f"🛡️ Guard routing: {route_code} (confidence: {confidence:.2f})")
        logger.debug(f"   Use TextFSM: {decision.get('use_textfsm')}")
        logger.debug(f"   Cache bypass: {decision.get('cache_bypass')}")
        logger.debug(f"   Reasoning: {decision.get('reasoning')}")
        
        # Check confidence threshold for Orchestrator fallback
        if confidence < confidence_threshold:
            logger.warning(f"⚠️ Low confidence ({confidence:.2f}), falling back to Orchestrator")
            return self._delegate_to_orchestrator(query, user_id)
        
        # Route-specific execution
        try:
            if route_code == "REJECT":
                return {
                    "status": "rejected",
                    "final_answer": f"❌ **Query Rejected**\n\n{decision.get('reasoning')}",
                    "error_message": decision.get("reasoning", "Query rejected"),
                }
            
            elif route_code == "CLI":
                return self._execute_cli_route(query, decision)
            
            elif route_code == "SIMPLE":
                return self._execute_simple_route(query, decision)
            
            elif route_code == "EXPERT":
                # Expert currently requires Orchestrator (complex analysis)
                logger.info("🔄 EXPERT route, delegating to Orchestrator")
                return self._delegate_to_orchestrator(query, user_id)
            
            elif route_code == "MULTI_AGENT":
                return self._execute_multi_agent_route(query, decision)
            
            else:  # UNKNOWN
                logger.info("🔄 UNKNOWN route, falling back to Orchestrator")
                return self._delegate_to_orchestrator(query, user_id)
        
        except Exception as e:
            logger.error(f"❌ Routing execution failed: {e}")
            import traceback
            tb = traceback.format_exc()
            return {
                "status": "error",
                "final_answer": f"Error during query execution:\n{str(e)}",
                "error_message": str(e),
                "traceback": tb,
            }
    
    def _execute_cli_route(
        self,
        query: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute CLI route with Guard decision parameters.
        
        Phase 3.2: Direct CLI execution using NetworkExecutor.
        Scenario 5: Supports batch multi-command processing.
        
        Args:
            query: User's natural language query
            decision: Guard routing decision (contains use_textfsm, cache_bypass)
        
        Returns:
            Execution result with device outputs
        """
        logger.info("🔥 Executing CLI route (direct)")
        
        try:
            from olav.shared.tools.network_executor import BatchExecutionRequest, get_executor
            
            # Extract devices and commands from query
            devices = self._extract_devices(query)
            commands = self._extract_commands(query)
            
            if not devices:
                # Default to common devices if no specific device mentioned
                devices = ["R1"]
                logger.debug(f"   No devices specified, using default: {devices}")
            
            if not commands:
                # Infer command from query intent
                commands = self._infer_commands(query)
                logger.debug(f"   No commands specified, inferred: {commands}")
            
            # Scenario 5: Detect batch processing request
            # Triggers: 
            # - Multiple commands (len(commands) > 1)
            # - Query contains "batch", "批量", "file", "分别存储", "save to files"
            # - Multiple devices + multiple commands
            batch_keywords = ["batch", "批量", "file", "文件", "分别", "separately", "save to"]
            needs_batch = (
                len(commands) > 1 
                or any(kw in query.lower() for kw in batch_keywords)
                or (len(devices) > 1 and len(commands) > 1)
            )
            
            executor = get_executor()
            
            # Scenario 5: Batch execution path
            if needs_batch:
                logger.info(f"📦 Batch processing: {len(devices)} devices × {len(commands)} commands")
                
                try:
                    # Create batch request with Pydantic validation
                    batch_request = BatchExecutionRequest(
                        devices=devices,
                        commands=commands,
                        organize_by_device=True,
                        use_textfsm=decision.get("use_textfsm", False),
                        cache_bypass=decision.get("cache_bypass", False),
                    )
                    
                    # Execute batch
                    batch_result = executor.execute_batch(batch_request)
                    
                    # Format batch output
                    output_lines = [
                        f"# Batch Execution Results",
                        f"",
                        f"**Batch ID**: `{batch_result.batch_id}`",
                        f"**Devices**: {len(batch_result.devices)} ({', '.join(batch_result.devices)})",
                        f"**Commands**: {len(batch_result.commands)}",
                        f"**Success Rate**: {batch_result.success_rate:.1f}% ({batch_result.successful_executions}/{batch_result.total_executions})",
                        f"**Duration**: {batch_result.total_duration_ms}ms",
                        f"**Output Directory**: `{batch_result.output_dir}`",
                        f"",
                        f"## Files Created",
                        f"",
                    ]
                    
                    # Group by device
                    for device in batch_result.devices:
                        device_results = [r for r in batch_result.results if r.device == device]
                        output_lines.append(f"### Device: {device}")
                        for result in device_results:
                            status = "✅" if result.success else "❌"
                            file_path = result.file_path.relative_to(batch_result.output_dir) if result.file_path else "N/A"
                            output_lines.append(
                                f"- {status} [{result.command_index:02d}] `{result.command}` → `{file_path}`"
                            )
                        output_lines.append("")
                    
                    if batch_result.metadata_file:
                        output_lines.append(f"**Metadata**: `{batch_result.metadata_file}`")
                    
                    final_answer = "\n".join(output_lines)
                    
                    logger.info(f"✅ Batch execution completed: {batch_result.summary}")
                    
                    return {
                        "status": "complete",
                        "final_answer": final_answer,
                        "error_message": "",
                        "batch_id": batch_result.batch_id,
                        "output_dir": str(batch_result.output_dir),
                        "results_count": batch_result.total_executions,
                        "success_count": batch_result.successful_executions,
                        "success_rate": batch_result.success_rate,
                    }
                
                except Exception as e:
                    logger.error(f"❌ Batch execution failed: {e}")
                    # Fallback to sequential execution
                    logger.info("⚠️ Falling back to sequential execution")
                    needs_batch = False
            
            # Standard execution path (single or simple multi-command)
            if not needs_batch:
                all_results = []
                
                for command in commands:
                    logger.debug(f"   Executing: {command} on {len(devices)} device(s)")
                    
                    batch_results = executor.execute_command(
                        devices=devices,
                        command=command,
                        use_textfsm=decision.get("use_textfsm", False),
                        cache_bypass=decision.get("cache_bypass", False),
                    )
                    all_results.extend(batch_results)
                
                # Format output
                output_lines = []
                success_count = 0
                textfsm_reasoning = decision.get("textfsm_reasoning", "")
                
                for result in all_results:
                    if result.success:
                        success_count += 1
                        output_lines.append(f"## Device: {result.device}")
                        output_lines.append(f"**Command**: `{result.command}`")
                        
                        if result.structured:
                            output_lines.append(f"**Format**: Structured (TextFSM)")
                            if textfsm_reasoning:
                                output_lines.append(f"_Reason_: {textfsm_reasoning}")
                        else:
                            output_lines.append(f"**Format**: Raw text")
                        
                        output_lines.append(f"\n```\n{result.output}\n```\n")
                    else:
                        output_lines.append(f"## Device: {result.device} ❌")
                        output_lines.append(f"**Error**: {result.error}\n")
                
                final_answer = "\n".join(output_lines)
                
                logger.info(f"✅ CLI execution completed: {success_count}/{len(all_results)} successful")
                
                return {
                    "status": "complete",
                    "final_answer": final_answer,
                    "error_message": "",
                    "results_count": len(all_results),
                    "success_count": success_count,
                }
        
        except Exception as e:
            logger.error(f"❌ CLI route execution failed: {e}")
            import traceback
            return {
                "status": "error",
                "final_answer": f"CLI execution error: {str(e)}",
                "error_message": str(e),
                "traceback": traceback.format_exc(),
            }
    
    def _execute_simple_route(
        self,
        query: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute SIMPLE route (direct database query).
        
        Phase 3.3: Direct database query using query_database tool.
        
        Args:
            query: User's natural language query
            decision: Guard routing decision
        
        Returns:
            Query result from database
        """
        logger.info("📊 Executing SIMPLE route (direct database query)")
        
        try:
            # Use Orchestrator's query agent logic (it already handles SIMPLE queries well)
            from olav.agents.orchestrator import orchestrate_query_sync
            return orchestrate_query_sync(query)
        
        except Exception as e:
            logger.error(f"❌ SIMPLE route execution failed: {e}")
            return {
                "status": "error",
                "final_answer": f"Database query error: {str(e)}",
                "error_message": str(e),
            }
    
    def _execute_expert_route(
        self,
        query: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute EXPERT route (complex analysis).
        
        Currently delegates to Orchestrator as Expert Agent requires
        multi-tool coordination and LLM-based analysis.
        
        Args:
            query: User's natural language query
            decision: Guard routing decision
        
        Returns:
            Expert analysis result
        """
        logger.info("🧠 Executing EXPERT route (delegating to Orchestrator)")
        
        try:
            from olav.agents.orchestrator import orchestrate_query_sync
            return orchestrate_query_sync(query)
        
        except Exception as e:
            logger.error(f"❌ EXPERT route execution failed: {e}")
            return {
                "status": "error",
                "final_answer": f"Expert analysis error: {str(e)}",
                "error_message": str(e),
            }
    
    def _execute_multi_agent_route(
        self,
        query: str,
        decision: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute MULTI_AGENT route (cross-system comparison).
        
        Currently delegates to Orchestrator for multi-source coordination.
        
        Args:
            query: User's natural language query
            decision: Guard routing decision
        
        Returns:
            Multi-agent coordination result
        """
        logger.info("🔄 Executing MULTI_AGENT route (delegating to Orchestrator)")
        
        try:
            from olav.agents.orchestrator import orchestrate_query_sync
            return orchestrate_query_sync(query)
        
        except Exception as e:
            logger.error(f"❌ MULTI_AGENT route execution failed: {e}")
            return {
                "status": "error",
                "final_answer": f"Multi-agent coordination error: {str(e)}",
                "error_message": str(e),
            }
    
    def _delegate_to_orchestrator(
        self,
        query: str,
        user_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Delegate to Orchestrator for handling.
        
        Used for low-confidence decisions or complex scenarios.
        """
        try:
            from olav.agents.orchestrator import orchestrate_query_sync
            return orchestrate_query_sync(query, user_id=user_id)
        except Exception as e:
            logger.error(f"❌ Orchestrator delegation failed: {e}")
            return {
                "status": "error",
                "final_answer": f"Orchestrator error: {str(e)}",
                "error_message": str(e),
            }
    
    # ═══════════════════════════════════════════════════════════════
    # Helper Methods: Query Parsing
    # ═══════════════════════════════════════════════════════════════
    
    def _extract_devices(self, query: str) -> list[str]:
        """Extract device names from query.
        
        Simple extraction based on common device naming patterns.
        
        Args:
            query: User query
        
        Returns:
            List of device names (empty if no devices found)
        """
        devices = []
        query_upper = query.upper()
        
        # Pattern 1: Explicit device names (R1, R2, SW1, etc.)
        device_pattern = r'\b(R\d+|SW\d+|ROUTER\d+|SWITCH\d+)\b'
        matches = re.findall(device_pattern, query_upper)
        devices.extend(matches)
        
        # Pattern 2: "所有设备" / "all devices"
        if re.search(r'所有设备|all\s+devices?', query, re.IGNORECASE):
            # Return empty to signal "all devices" (caller handles default)
            return []
        
        # Pattern 3: Device groups
        if re.search(r'路由器|routers?', query, re.IGNORECASE):
            devices.extend(["R1", "R2", "R3", "R4"])
        
        if re.search(r'交换机|switches?', query, re.IGNORECASE):
            devices.extend(["SW1", "SW2"])
        
        # Remove duplicates and return
        return list(set(devices)) if devices else []
    
    def _extract_commands(self, query: str) -> list[str]:
        """Extract CLI commands from query.
        
        Scenario 5: Enhanced to support multiple commands.
        Supports:
        - Explicit show commands
        - Quoted commands
        - Comma-separated command lists
        - Chinese comma separator (、,，)
        
        Args:
            query: User query
        
        Returns:
            List of CLI commands (empty if no commands found)
        """
        commands = []
        
        # Pattern 1: Quoted commands (highest priority - most explicit)
        quoted_pattern = r'["\']([^"\']+)["\']'
        quoted_matches = re.findall(quoted_pattern, query)
        for match in quoted_matches:
            if match.lower().startswith('show'):
                commands.append(match.strip())
        
        # Pattern 2: Comma-separated command list
        # Support: , (comma), 、 (Chinese enumeration), ， (Chinese comma)
        if ',' in query or '、' in query or '，' in query:
            # Split by various comma types
            parts = re.split(r'[,、，]', query)
            for part in parts:
                # Extract show commands - stop at delimiters/keywords
                part_commands = re.findall(r'(show\s+[\w]+(?:\s+[\w]+)*?)(?:\s+(?:并|and|or|,|、|on|in|at|保存|save|file|to)|\s*$)', part, re.IGNORECASE)
                commands.extend([c.strip() for c in part_commands if c.strip()])
        
        # Pattern 3: Explicit show commands (non-quoted, with proper boundaries)
        # Stop at common delimiters: "并" "保存" "to" "on" "and" etc.
        show_pattern = r'show\s+[\w]+(?:\s+[\w]+)*?(?=\s+(?:并|保存|save|file|to|on|and|or|,|、|，|\Z)|\Z)'
        matches = re.findall(show_pattern, query, re.IGNORECASE)
        commands.extend([m.strip() for m in matches if m.strip()])
        
        # Remove duplicates while preserving order
        seen = set()
        unique_commands = []
        for cmd in commands:
            cmd_lower = cmd.lower()
            if cmd_lower not in seen:
                seen.add(cmd_lower)
                unique_commands.append(cmd)
        
        return unique_commands if unique_commands else []
    
    def _infer_commands(self, query: str) -> list[str]:
        """Infer CLI commands from query intent.
        
        When no explicit command is found, infer based on keywords.
        
        Args:
            query: User query
        
        Returns:
            List of inferred commands
        """
        query_lower = query.lower()
        
        # Interface-related queries
        if any(kw in query_lower for kw in ['接口', 'interface', 'port']):
            if any(kw in query_lower for kw in ['简要', 'brief', 'summary']):
                return ["show ip interface brief"]
            else:
                return ["show interfaces"]
        
        # Version queries
        if any(kw in query_lower for kw in ['版本', 'version', '软件']):
            return ["show version"]
        
        # OSPF queries
        if 'ospf' in query_lower:
            if any(kw in query_lower for kw in ['邻居', 'neighbor']):
                return ["show ip ospf neighbor"]
            else:
                return ["show ip ospf"]
        
        # BGP queries
        if 'bgp' in query_lower:
            if any(kw in query_lower for kw in ['汇总', 'summary']):
                return ["show ip bgp summary"]
            else:
                return ["show ip bgp"]
        
        # CPU/Memory queries
        if any(kw in query_lower for kw in ['cpu', '处理器']):
            return ["show processes cpu"]
        
        if any(kw in query_lower for kw in ['memory', '内存']):
            return ["show memory statistics"]
        
        # Default: show version
        return ["show version"]
