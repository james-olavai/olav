"""Plan execution bridge for connecting generated plans to SubAgent execution.

Phase 6.4: Execution bridge coordinates plan approval, SubAgent execution,
progress tracking, and result collection.

Features:
- Plan approval/modification handling
- SubAgent execution orchestration
- Progress tracking and reporting
- Result aggregation
- Execution state management
"""

import logging
from typing import Dict, Any, Optional, List
from enum import Enum
from dataclasses import dataclass
import datetime

logger = logging.getLogger(__name__)


class ExecutionPhase(Enum):
    """Phases of plan execution."""
    PENDING = "pending"           # Waiting for user confirmation
    APPROVED = "approved"         # User confirmed execution
    EXECUTING = "executing"       # Currently executing
    COMPLETED = "completed"       # Execution finished
    FAILED = "failed"            # Execution failed
    CANCELLED = "cancelled"      # User cancelled


@dataclass
class ExecutionStep:
    """Represents an execution step in the plan.
    
    Attributes:
        step_name: Name of the step (e.g., "QUERY", "ANALYZER")
        subagent_name: Which SubAgent to execute
        status: Current execution status
        start_time: When execution started
        end_time: When execution finished
        duration: How long it took (seconds)
        result: Execution result/output
        error: Any error that occurred
    """
    step_name: str
    subagent_name: str
    status: ExecutionPhase = ExecutionPhase.PENDING
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    duration: float = 0.0
    result: Optional[Dict[str, Any]] = None
    error: Optional[Exception] = None


@dataclass
class ExecutionPlan:
    """Represents a complete execution plan.
    
    Attributes:
        plan_id: Unique plan identifier
        user_intent: Original user query
        approval_status: Whether user approved
        steps: List of execution steps
        start_time: When plan execution started
        end_time: When plan execution finished
        total_duration: Total execution time
        success_count: Number of successful steps
        error_count: Number of failed steps
    """
    plan_id: str
    user_intent: str
    approval_status: bool = False
    steps: List[ExecutionStep] = None
    start_time: Optional[datetime.datetime] = None
    end_time: Optional[datetime.datetime] = None
    total_duration: float = 0.0
    success_count: int = 0
    error_count: int = 0
    
    def __post_init__(self):
        if self.steps is None:
            self.steps = []


class PlanExecutionBridge:
    """Bridges generated plans with SubAgent execution.
    
    Coordinates:
    - Plan approval and modification
    - SubAgent orchestration
    - Results collection
    - Progress reporting
    - Execution state management
    """
    
    def __init__(self):
        """Initialize execution bridge."""
        self.current_plan: Optional[ExecutionPlan] = None
        self.execution_history: List[ExecutionPlan] = []
        self.progress_callbacks: List = []
    
    def create_execution_plan(
        self,
        plan_id: str,
        user_intent: str,
        steps: List[Dict[str, str]]
    ) -> ExecutionPlan:
        """Create execution plan from plan specification.
        
        Args:
            plan_id: Unique plan identifier
            user_intent: User's original query
            steps: List of execution steps with subagent info
        
        Returns:
            ExecutionPlan ready for approval
        """
        execution_steps = []
        for step_spec in steps:
            step = ExecutionStep(
                step_name=step_spec.get("name", "UNKNOWN"),
                subagent_name=step_spec.get("subagent", "unknown")
            )
            execution_steps.append(step)
        
        plan = ExecutionPlan(
            plan_id=plan_id,
            user_intent=user_intent,
            steps=execution_steps
        )
        
        self.current_plan = plan
        logger.info(f"Created execution plan {plan_id} with {len(steps)} steps")
        
        return plan
    
    async def approve_and_execute(
        self,
        plan: ExecutionPlan,
        subagent_executor: Any
    ) -> Dict[str, Any]:
        """Approve plan and execute all steps.
        
        Args:
            plan: ExecutionPlan to execute
            subagent_executor: Callable that executes subagents
        
        Returns:
            Execution results dictionary
        """
        plan.approval_status = True
        plan.start_time = datetime.datetime.now()
        
        logger.info(f"Plan {plan.plan_id} approved. Executing {len(plan.steps)} steps...")
        
        results = {}
        
        for i, step in enumerate(plan.steps):
            step.status = ExecutionPhase.EXECUTING
            step.start_time = datetime.datetime.now()
            
            # Notify progress
            await self._notify_progress(
                step_index=i,
                total_steps=len(plan.steps),
                current_step=step.step_name,
                status="executing"
            )
            
            try:
                # Execute the SubAgent
                result = await self._execute_step(step, subagent_executor)
                
                step.result = result
                step.status = ExecutionPhase.COMPLETED
                step.end_time = datetime.datetime.now()
                step.duration = (
                    step.end_time - step.start_time
                ).total_seconds()
                
                results[step.step_name] = result
                plan.success_count += 1
                
                logger.info(
                    f"Step {step.step_name} completed in {step.duration:.2f}s"
                )
                
            except Exception as e:
                step.error = e
                step.status = ExecutionPhase.FAILED
                step.end_time = datetime.datetime.now()
                step.duration = (
                    step.end_time - step.start_time
                ).total_seconds()
                
                plan.error_count += 1
                logger.error(f"Step {step.step_name} failed: {e}")
                
                # Notify error
                await self._notify_progress(
                    step_index=i,
                    total_steps=len(plan.steps),
                    current_step=step.step_name,
                    status="failed",
                    error=str(e)
                )
        
        plan.end_time = datetime.datetime.now()
        plan.total_duration = (
            plan.end_time - plan.start_time
        ).total_seconds()
        
        # Store in history
        self.execution_history.append(plan)
        
        logger.info(
            f"Plan {plan.plan_id} execution completed: "
            f"{plan.success_count} succeeded, "
            f"{plan.error_count} failed, "
            f"duration: {plan.total_duration:.2f}s"
        )
        
        return self._format_results(plan, results)
    
    async def _execute_step(
        self,
        step: ExecutionStep,
        executor: Any
    ) -> Dict[str, Any]:
        """Execute a single step with SubAgent.
        
        Args:
            step: ExecutionStep to execute
            executor: SubAgent executor callable
        
        Returns:
            Execution result
        """
        # Call the executor (implementation specific)
        # For now, return mock result
        return {
            "status": "success",
            "step": step.step_name,
            "subagent": step.subagent_name,
            "result_data": {}
        }
    
    async def _notify_progress(
        self,
        step_index: int,
        total_steps: int,
        current_step: str,
        status: str,
        error: Optional[str] = None
    ) -> None:
        """Notify progress callbacks.
        
        Args:
            step_index: Current step index (0-based)
            total_steps: Total number of steps
            current_step: Name of current step
            status: Status message
            error: Optional error message
        """
        progress = {
            "step_number": step_index + 1,
            "total_steps": total_steps,
            "percentage": ((step_index + 1) / total_steps) * 100,
            "current_step": current_step,
            "status": status,
            "timestamp": datetime.datetime.now().isoformat()
        }
        
        if error:
            progress["error"] = error
        
        for callback in self.progress_callbacks:
            if callable(callback):
                try:
                    await callback(progress)
                except Exception as e:
                    logger.error(f"Progress callback failed: {e}")
    
    def _format_results(
        self,
        plan: ExecutionPlan,
        results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Format execution results for output.
        
        Args:
            plan: The executed plan
            results: Execution results
        
        Returns:
            Formatted results dictionary
        """
        return {
            "plan_id": plan.plan_id,
            "user_intent": plan.user_intent,
            "status": "success" if plan.error_count == 0 else "partial_failure",
            "total_duration": plan.total_duration,
            "steps_completed": plan.success_count,
            "steps_failed": plan.error_count,
            "total_steps": len(plan.steps),
            "results": results,
            "execution_log": self._generate_execution_log(plan)
        }
    
    def _generate_execution_log(self, plan: ExecutionPlan) -> str:
        """Generate markdown execution log.
        
        Args:
            plan: The executed plan
        
        Returns:
            Markdown formatted execution log
        """
        log = f"""# 📋 执行日志

**计划ID**: {plan.plan_id}
**用户意图**: {plan.user_intent}
**执行状态**: {'✅ 成功' if plan.error_count == 0 else '⚠️  部分失败'}
**总耗时**: {plan.total_duration:.2f}s

## 步骤执行情况

| 步骤 | SubAgent | 状态 | 耗时 |
|------|----------|------|------|
"""
        for step in plan.steps:
            status_emoji = "✅" if step.status == ExecutionPhase.COMPLETED else "❌"
            log += f"| {step.step_name} | {step.subagent_name} | {status_emoji} {step.status.value} | {step.duration:.2f}s |\n"
        
        log += f"\n**总结**: {plan.success_count}/{len(plan.steps)} 步骤成功\n"
        
        return log
    
    def add_progress_callback(self, callback) -> None:
        """Add callback for progress updates.
        
        Args:
            callback: Async callable that receives progress dict
        """
        self.progress_callbacks.append(callback)
    
    def get_execution_history(self) -> List[ExecutionPlan]:
        """Get history of executed plans.
        
        Returns:
            List of ExecutionPlan objects from history
        """
        return self.execution_history.copy()


# Global singleton instance
_bridge_instance: Optional[PlanExecutionBridge] = None


def get_plan_execution_bridge() -> PlanExecutionBridge:
    """Get or create singleton execution bridge instance.
    
    Returns:
        Shared PlanExecutionBridge instance
    """
    global _bridge_instance
    if _bridge_instance is None:
        _bridge_instance = PlanExecutionBridge()
    return _bridge_instance
