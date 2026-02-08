"""
TextFSM Interactive Workflow Orchestrator

Coordinates all 6 steps of the interactive template generation workflow.
"""

import logging
import time
from datetime import datetime
from typing import Any

from .config import get_config
from .field_analysis_cache import get_field_analysis_cache, FieldAnalysisResult
from .models import (
    AnalysisResult,
    ApprovalResult,
    GenerationResult,
    GenerationMetrics,
    TemplateMetadata,
    FieldDefinition,
)
from .tools import (
    execute_command_tool,
    analyze_fields_tool,
    get_ntc_references_tool,
    test_template_tool,
    save_template_tool,
)
from .deepagent import TextFSMInteractiveAgent

logger = logging.getLogger(__name__)


class TextFSMWorkflowOrchestrator:
    """
    Orchestrates the complete 6-step TextFSM generation workflow.
    
    Steps:
    1. Execute Command → raw output
    2. Analyze Fields → field suggestions (LLM)
    3. User Approval → validated fields + user modifications
    4. Fetch NTC References → relevant templates
    5. ReAct Generation → template generation loop (DeepAgents)
    6. Save Template → save to disk with metadata
    """
    
    def __init__(
        self,
        user_approval_callback=None,
        max_iterations: int = None,
        success_threshold: float = None,
        skill_config: dict[str, Any] = None,
    ):
        """
        Initialize orchestrator with optional SKILL.md configuration.
        
        Args:
            user_approval_callback: Async callback for user approval (Step 3)
                Should accept AnalysisResult and return ApprovalResult
            max_iterations: Max iterations for generation loop (overrides config)
            success_threshold: Min success rate to accept (overrides config)
            skill_config: Optional SKILL.md config dict for initialization
        """
        self.user_approval_callback = user_approval_callback
        
        # Load configuration (may come from SKILL.md)
        config = get_config()
        if skill_config:
            # If SKILL.md provided, could reload config from it
            # Currently we rely on environment variables
            logger.debug(f"Orchestrator initialized with skill_config")
        
        # Use provided values or fall back to config
        self.max_iterations = max_iterations or config.max_iterations
        self.success_threshold = success_threshold or config.success_threshold
        self.config = config
        
        # Initialize generation agent with config
        self.generation_agent = TextFSMInteractiveAgent(
            max_iterations=self.max_iterations,
            success_threshold=self.success_threshold
        )
        
        # Initialize field analysis cache (Tier 1 optimization)
        self.field_analysis_cache = get_field_analysis_cache(config.cache_db)
        
        logger.info(
            f"Initialized TextFSMWorkflowOrchestrator "
            f"(cache_enabled={config.enable_field_analysis_cache}, "
            f"max_iterations={self.max_iterations})"
        )
    
    async def run_workflow(
        self,
        host: str,
        command: str,
        platform: str,
        sample_outputs: list[str] = None,
    ) -> dict[str, Any]:
        """
        Run the complete 6-step workflow.
        
        Args:
            host: Target host (e.g., "R1.cisco_ios")
            command: Command (e.g., "show bgp summary")
            platform: Platform (e.g., "cisco_ios")
            sample_outputs: Optional additional sample outputs
            
        Returns:
            {
                "success": bool,
                "template": str,
                "metadata": TemplateMetadata (dict),
                "generation_result": GenerationResult (dict),
                "error": str (if failed),
                "workflow_path": list[str] - step names executed
            }
        """
        workflow_path = []
        
        try:
            # ================================================================
            # Step 1: Execute Command
            # ================================================================
            logger.info("=" * 70)
            logger.info("Step 1: Execute Command")
            logger.info("=" * 70)
            
            workflow_path.append("execute_command")
            
            exec_result = await execute_command_tool(
                host=host,
                command=command,
                timeout=30
            )
            
            if not exec_result["success"]:
                return {
                    "success": False,
                    "error": f"Command execution failed: {exec_result.get('error')}",
                    "workflow_path": workflow_path,
                }
            
            raw_output = exec_result["output"]
            logger.info(f"✓ Command executed in {exec_result['execution_time']:.2f}s")
            logger.info(f"  Output length: {len(raw_output)} chars")
            
            # ================================================================
            # Step 2: Analyze Fields
            # ================================================================
            logger.info("=" * 70)
            logger.info("Step 2: Analyze Required Fields (LLM)")
            logger.info("=" * 70)
            
            workflow_path.append("analyze_fields")
            
            # ================================================================
            # Tier 1 Cache: Field Analysis Cache Check
            # ================================================================
            analysis_result = None
            analysis_time_ms = 0
            cache_hit = False
            
            if self.config.enable_field_analysis_cache:
                logger.debug(f"Checking field analysis cache for output pattern...")
                cached_analysis = self.field_analysis_cache.get(
                    output=raw_output,
                    command=command,
                    platform=platform
                )
                
                if cached_analysis and cached_analysis.fields:
                    logger.info(f"✓ Cache hit! Reusing field analysis (saved {cached_analysis.analysis_time_ms}ms)")
                    analysis_result = {
                        "fields": [
                            {
                                "name": f.name,
                                "type": f.type,
                                "mandatory": f.mandatory,
                                "description": f.description
                            }
                            for f in cached_analysis.fields
                        ],
                        "relationships": cached_analysis.metadata.get("relationships", {}),
                        "strategy": cached_analysis.metadata.get("strategy", "row-based"),
                        "confidence": cached_analysis.metadata.get("confidence", 0.95)
                    }
                    analysis_time_ms = cached_analysis.analysis_time_ms
                    cache_hit = True
            
            # Call LLM if cache miss
            if analysis_result is None:
                if cache_hit is False:
                    logger.debug(f"Cache miss or cache disabled. Calling LLM for field analysis...")
                
                start_time = time.time()
                
                analysis_result = await analyze_fields_tool(
                    raw_output=raw_output,
                    command_name=command,
                    platform=platform
                )
                
                analysis_time_ms = int((time.time() - start_time) * 1000)
                
                # ================================================================
                # Save to Tier 1 Cache (Field Analysis)
                # ================================================================
                if self.config.enable_field_analysis_cache and analysis_result["fields"]:
                    from .field_analysis_cache import FieldSummary
                    
                    fields_to_cache = [
                        FieldSummary(
                            name=f["name"],
                            type=f["type"],
                            mandatory=f["mandatory"],
                            description=f.get("description")
                        )
                        for f in analysis_result["fields"]
                    ]
                    
                    cache_metadata = {
                        "relationships": analysis_result.get("relationships", {}),
                        "strategy": analysis_result["strategy"],
                        "confidence": analysis_result["confidence"]
                    }
                    
                    self.field_analysis_cache.set(
                        output=raw_output,
                        command=command,
                        platform=platform,
                        fields=fields_to_cache,
                        analysis_time_ms=analysis_time_ms,
                        metadata=cache_metadata,
                        llm_model=self.config.llm_model_name
                    )
                    
                    logger.info(f"✓ Cached field analysis (took {analysis_time_ms}ms)")
            
            analysis = AnalysisResult(
                command_name=command,
                platform=platform,
                raw_output=raw_output,
                detected_fields=[
                    FieldDefinition(
                        name=f["name"],
                        type=f["type"],
                        mandatory=f["mandatory"],
                        description=f.get("description")
                    )
                    for f in analysis_result["fields"]
                ],
                field_relationships=analysis_result.get("relationships", {}),
                extraction_strategy=analysis_result["strategy"],
                confidence=analysis_result["confidence"]
            )
            
            logger.info(f"✓ Detected {len(analysis.detected_fields)} fields")
            logger.info(f"  Strategy: {analysis.extraction_strategy}")
            logger.info(f"  Confidence: {analysis.confidence:.2%}")
            
            for field in analysis.detected_fields:
                logger.info(f"    - {field.name} ({field.type})", extra={
                    "mandatory": field.mandatory
                })
            
            # ================================================================
            # Step 3: User Approval
            # ================================================================
            logger.info("=" * 70)
            logger.info("Step 3: User Approval/Modification")
            logger.info("=" * 70)
            
            workflow_path.append("user_approval")
            
            if self.user_approval_callback:
                approval = await self.user_approval_callback(analysis)
            else:
                # Default: auto-approve all detected fields
                logger.info("⊘ No approval callback - auto-approving all fields")
                approval = ApprovalResult(
                    analysis_result=analysis,
                    approved_fields=analysis.detected_fields,
                    rejected_fields=[],
                    approval_timestamp=datetime.now(),
                )
            
            logger.info(f"✓ User approved {len(approval.approved_fields)} fields")
            if approval.rejected_fields:
                for rejection in approval.rejected_fields:
                    logger.info(f"  Rejected: {rejection}")
            
            if approval.additional_requirements:
                logger.info(f"  User notes: {approval.additional_requirements}")
            
            approved_field_names = [f.name for f in approval.approved_fields]
            
            # ================================================================
            # Step 4: Fetch NTC References
            # ================================================================
            logger.info("=" * 70)
            logger.info("Step 4: Fetch NTC References")
            logger.info("=" * 70)
            
            workflow_path.append("fetch_ntc_references")
            
            ntc_result = await get_ntc_references_tool(
                platform=platform,
                command=command,
                approved_fields=approved_field_names,
                limit=2
            )
            
            ntc_references = [ref["content"] for ref in ntc_result["references"]]
            
            logger.info(f"✓ Retrieved {len(ntc_references)} NTC references")
            for ref in ntc_result["references"]:
                logger.info(f"  - {ref['template_name']} (relevance={ref['relevance_score']:.2%})")
            
            # ================================================================
            # Step 5: ReAct Generation Loop
            # ================================================================
            logger.info("=" * 70)
            logger.info("Step 5: Generate Template (ReAct Loop)")
            logger.info("=" * 70)
            
            workflow_path.append("generate_template")
            
            generation_result = await self.generation_agent.generate_with_ntc_references(
                raw_output=raw_output,
                command_name=command,
                platform=platform,
                approved_fields=approved_field_names,
                ntc_references=ntc_references,
                sample_outputs=sample_outputs or [raw_output],
            )
            
            logger.info(f"✓ Generation completed in {generation_result['iterations']} iterations")
            logger.info(f"  Final success rate: {generation_result['metrics']['parse_success']:.2%}")
            logger.info(f"  Value coverage: {generation_result['metrics']['value_coverage']:.2%}")
            logger.info(f"  Regex accuracy: {generation_result['metrics']['regex_accuracy']:.2%}")
            logger.info(f"  State completeness: {generation_result['metrics']['state_completeness']:.2%}")
            
            if not generation_result["final_success"]:
                logger.warning(
                    f"Generation below threshold "
                    f"({generation_result['metrics']['parse_success']:.2%} < {self.success_threshold:.2%})"
                )
                return {
                    "success": False,
                    "error": f"Generation failed to reach threshold ({generation_result['metrics']['parse_success']:.2%})",
                    "workflow_path": workflow_path,
                }
            
            template_content = generation_result["template"]
            generation_metrics = GenerationMetrics(
                parse_success_rate=generation_result["metrics"]["parse_success"],
                value_coverage=generation_result["metrics"]["value_coverage"],
                regex_accuracy=generation_result["metrics"]["regex_accuracy"],
                state_completeness=generation_result["metrics"]["state_completeness"],
            )
            
            # ================================================================
            # Step 6: Save Template
            # ================================================================
            logger.info("=" * 70)
            logger.info("Step 6: Save Template")
            logger.info("=" * 70)
            
            workflow_path.append("save_template")
            
            # Create metadata
            filename = f"{platform}_{command.replace(' ', '_')}.textfsm"
            file_path = f"~/.olav/templates/custom/{filename}"
            
            metadata = TemplateMetadata(
                command_name=command,
                platform=platform,
                filename=filename,
                file_path=file_path,
                generated_by="textfsm_interactive_agent_v1",
                generation_method="guided",
                success_rate=generation_metrics.parse_success_rate,
                user_approved_fields=approved_field_names,
                iterations_count=generation_result["iterations"],
                generation_time_seconds=0.0,  # Phase 4 TODO: track workflow duration
            )
            
            save_result = await save_template_tool(
                template=template_content,
                command_name=command,
                platform=platform,
                metadata=metadata.to_dict()
            )
            
            if not save_result["success"]:
                return {
                    "success": False,
                    "error": f"Save failed: {save_result.get('error')}",
                    "workflow_path": workflow_path,
                }
            
            logger.info(f"✓ Template saved to {save_result['file_path']}")
            
            # ================================================================
            # Success
            # ================================================================
            logger.info("=" * 70)
            logger.info("✓ Workflow completed successfully")
            logger.info("=" * 70)
            
            return {
                "success": True,
                "template": template_content,
                "metadata": metadata.to_dict(),
                "generation_result": {
                    "iterations": generation_result["iterations"],
                    "metrics": {
                        "parse_success": generation_metrics.parse_success_rate,
                        "value_coverage": generation_metrics.value_coverage,
                        "regex_accuracy": generation_metrics.regex_accuracy,
                        "state_completeness": generation_metrics.state_completeness,
                    },
                    "history": generation_result["history"],
                },
                "workflow_path": workflow_path,
            }
        
        except Exception as e:
            logger.exception(f"Workflow failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "workflow_path": workflow_path,
            }
