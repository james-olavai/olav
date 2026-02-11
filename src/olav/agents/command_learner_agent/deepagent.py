"""
DeepAgents Plan Agent for TextFSM Generation

Handles ReAct loop for template generation with NTC references.
"""

import logging
from typing import Any
from .config import get_config
from .template_cache import get_template_cache

logger = logging.getLogger(__name__)


class CommandLearnerAgent:
    """
    DeepAgents Plan Agent for TextFSM generation.
    
    Handles:
    - Step 4: Fetch NTC References
    - Step 5: ReAct Generation Loop
    
    Uses DeepAgents for automated planning and iteration.
    """
    
    def __init__(
        self,
        max_iterations: int = None,
        success_threshold: float = None,
        llm_model: str = "gpt-4",
        llm_base_url: str = None,
        llm_api_key: str = None,
    ):
        """
        Initialize TextFSM generation agent.
        
        Args:
            max_iterations: Maximum ReAct iterations (uses config default if None)
            success_threshold: Min success rate to accept 0-1 (uses config default if None)
            llm_model: LLM model name
            llm_base_url: Optional LLM base URL override
            llm_api_key: Optional LLM API key override
        """
        config = get_config()
        self.max_iterations = max_iterations or config.max_iterations
        self.success_threshold = success_threshold or config.success_threshold
        self.llm_model = llm_model
        self.llm_base_url = llm_base_url
        self.llm_api_key = llm_api_key
        
        # Phase 4 TODO: Initialize DeepAgents components
        # - Create LLM instance (with base_url override if provided)
        # - Create Plan Agent with tools integration
        # - Setup ReAct loop framework
        # Not implemented in Phase 1-3. Currently uses mock ReAct implementation.
        
        logger.info(
            f"Initialized CommandLearnerAgent "
            f"(max_iterations={self.max_iterations}, "
            f"threshold={self.success_threshold})"
        )
    
    async def generate_with_ntc_references(
        self,
        raw_output: str,
        command_name: str,
        platform: str,
        approved_fields: list[str],
        ntc_references: list[str],
        sample_outputs: list[str] = None,
    ) -> dict[str, Any]:
        """
        Generate TextFSM template using ReAct loop.
        
        Coordinates:
        1. Generate initial template with NTC guidance
        2. Test template against samples
        3. If success_rate < threshold, analyze errors and retry
        4. Repeat up to max_iterations
        
        Args:
            raw_output: Raw command output
            command_name: Command name (e.g., "show bgp summary")
            platform: Platform (e.g., "cisco_ios")
            approved_fields: User-approved fields to extract
            ntc_references: NTC template content examples
            sample_outputs: Optional additional sample outputs for testing
            
        Returns:
            {
                "template": str,
                "metrics": {
                    "parse_success": float,
                    "value_coverage": float,
                    "regex_accuracy": float,
                    "state_completeness": float
                },
                "iterations": int,
                "final_success": bool,
                "history": [
                    {
                        "iteration": 1,
                        "template": str,
                        "success_rate": float,
                        "errors": [str]
                    },
                    ...
                ]
            }
        """
        logger.info(
            f"Starting ReAct generation for '{command_name}' ({platform}) "
            f"with {len(approved_fields)} approved fields"
        )
        
        config = get_config()
        
        # Tier 0: Template Cache (Phase 3+ optimization)
        # Check if we have a cached template for this command + platform
        if config.enable_template_cache:
            sample_output = (sample_outputs[0] if sample_outputs else raw_output)
            template_cache = get_template_cache(config.cache_db)
            cached = template_cache.get(
                command=command_name,
                platform=platform,
                sample_output=sample_output,
            )
            
            if cached and cached.success_rate >= self.success_threshold:
                logger.info(
                    f"✓ CACHE HIT ({platform}/{command_name}): "
                    f"success_rate={cached.success_rate:.2f} >= {self.success_threshold} "
                    f"(saved {config.generation_timeout}s) (MOCK)"
                )
                # Return cached result immediately (skip entire ReAct loop!)
                return {
                    "template": cached.template,
                    "metrics": {
                        "parse_success": config.mock_success_rate,
                        "value_coverage": config.mock_value_coverage,
                        "regex_accuracy": config.mock_regex_accuracy,
                        "state_completeness": config.mock_state_completeness,
                    },
                    "iterations": 0,  # No iterations needed
                    "final_success": True,
                    "history": [],
                    "cached": True,  # Indicate this came from cache
                    "cache_metadata": {
                        "created_at": cached.created_at.isoformat(),
                        "original_iterations": cached.iterations_used,
                    },
                }
        
        # Phase 4 TODO: Implement using DeepAgents
        # - Use Plan Agent to create generation strategy
        # - Submit to ReAct loop with tool functions
        # Currently implements mock ReAct workflow for testing.
        
        # 1. Prepare context
        generation_context = {
            "raw_output": raw_output,
            "command_name": command_name,
            "platform": platform,
            "approved_fields": approved_fields,
            "ntc_references": ntc_references,
            "sample_outputs": sample_outputs or [raw_output],
        }
        
        # 2. Create plan using DeepAgents
        # plan = await self._create_generation_plan(generation_context)
        
        # 3. Execute ReAct loop
        history = []
        current_iteration = 0
        best_template = None
        best_success_rate = 0.0
        
        config = get_config()
        for iteration in range(1, self.max_iterations + 1):
            current_iteration = iteration
            logger.info(f"ReAct iteration {iteration}/{self.max_iterations}")
            
            # Phase 4 TODO: Call real tool functions
            # - generate_template_tool if iteration == 1
            # - generate_template_tool with previous_errors if iteration > 1  
            # - test_template_tool to validate
            # Phase 1-3: Using mock implementation for testing workflow
            
            iteration_result = {
                "iteration": iteration,
                "template": r"""Value System_Load ([\d.]+)
Value CPU_Cores (\d+)
Value RAM_Total (\d+)
Value RAM_Used (\d+)
Value Disk_Size (\d+)
Value Disk_Used (\d+)
Value Running_Processes (\d+)
Value Network_Interfaces (\d+)
Value Active_Connections (\d+)
Value UDP_Sockets (\d+)

Start
  ^System Load: ${System_Load}
  ^CPU Cores: ${CPU_Cores}
  ^RAM Total: ${RAM_Total}
  ^RAM Used: ${RAM_Used}
  ^Disk Size: ${Disk_Size}
  ^Disk Used: ${Disk_Used}
  ^Running Processes: ${Running_Processes}
  ^Network Interfaces: ${Network_Interfaces}
  ^Active TCP Connections: ${Active_Connections}
  ^UDP Sockets: ${UDP_Sockets}""",
                "success_rate": config.mock_success_rate,
                "errors": []
            }
            history.append(iteration_result)
            
            # Track best attempt
            if iteration_result["success_rate"] > best_success_rate:
                best_success_rate = iteration_result["success_rate"]
                best_template = iteration_result["template"]
            
            # Stop if threshold reached
            if iteration_result["success_rate"] >= self.success_threshold:
                logger.info(f"Threshold reached (success_rate={best_success_rate:.2f})")
                break
        
        # Phase 3+ TODO: Cache successful templates
        # Only cache if success_rate is above threshold
        if config.enable_template_cache and best_success_rate >= self.success_threshold:
            template_cache = get_template_cache(config.cache_db)
            sample_output = sample_outputs[0] if sample_outputs else raw_output
            
            template_cache.set(
                command=command_name,
                platform=platform,
                template=best_template,
                success_rate=best_success_rate,
                sample_output=sample_output,
                iterations_used=current_iteration,
                metadata={
                    "approved_fields": approved_fields,
                    "ntc_references_count": len(ntc_references),
                    "field_count": len(approved_fields),
                },
            )
            logger.debug(
                f"Template cached: {command_name}@{platform} "
                f"(success_rate={best_success_rate:.2f}, iterations={current_iteration})"
            )
        
        # 4. Return results
        return {
            "template": best_template,
            "metrics": {
                "parse_success": best_success_rate,
                "value_coverage": config.mock_value_coverage,
                "regex_accuracy": config.mock_regex_accuracy,
                "state_completeness": config.mock_state_completeness,
            },
            "iterations": current_iteration,
            "final_success": best_success_rate >= self.success_threshold,
            "history": history,
            "cached": False,  # Indicate this was generated, not cached
        }
    
    async def _create_generation_plan(
        self,
        context: dict[str, Any]
    ) -> str:
        """
        Create a plan for template generation using DeepAgents.
        
        Args:
            context: Generation context
            
        Returns:
            Plan string
        """
        # Phase 4 TODO: Use Plan Agent to create strategy
        # Should return structured plan like:
        # "1. Analyze output using approved fields
        #  2. Review NTC references for patterns
        #  3. Generate combined template
        #  4. Test & iterate"
        # Phase 1-3: Returns phase indicator instead
        
        return "Phase 4: Plan Agent not yet implemented"
