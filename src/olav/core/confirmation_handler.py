"""User confirmation flow for plan execution.

Phase 6.2.3: Confirmation flow allows users to review and approve plans before execution.

Features:
- Interactive confirmation prompt
- Plan review options (show full plan, edit parameters, cancel)
- Confirmation timeout handling
- Execution decision logging
"""

import logging
from typing import Dict, Optional, Any
from enum import Enum
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ConfirmationAction(Enum):
    """User's confirmation action choices."""
    CONFIRMED = "confirmed"      # Proceed with execution
    MODIFIED = "modified"        # Request plan modification
    CANCELLED = "cancelled"      # Cancel execution
    TIMEOUT = "timeout"          # No response within timeout
    SHOW_DETAILS = "show_details"  # Show full plan details
    SHOW_TIMING = "show_timing"    # Show timing breakdown


@dataclass
class ConfirmationRequest:
    """Confirmation request from plan handler.
    
    Attributes:
        plan_markdown: Full markdown plan to confirm
        plan_summary: Short summary for display
        execution_time: Estimated execution time
        risk_level: Risk level assessment
        intent: User's original query intent
    """
    plan_markdown: str
    plan_summary: str
    execution_time: str
    risk_level: str
    intent: str


@dataclass
class ConfirmationResponse:
    """User's response to confirmation request.
    
    Attributes:
        action: ConfirmationAction chosen by user
        timestamp: When confirmation was made
        modifications: Any requested modifications (if action=MODIFIED)
        user_notes: Optional user notes
    """
    action: ConfirmationAction
    timestamp: str
    modifications: Optional[Dict[str, Any]] = None
    user_notes: str = ""


class ConfirmationHandler:
    """Handles user confirmation workflow.
    
    Presents plan for user confirmation and handles:
    - Interactive prompts
    - Plan review options
    - Timeout management
    - Action logging
    """
    
    def __init__(self, timeout_seconds: int = 300):
        """Initialize confirmation handler.
        
        Args:
            timeout_seconds: How long to wait for user response (default 5 min)
        """
        self.timeout_seconds = timeout_seconds
        self.last_confirmation: Optional[ConfirmationResponse] = None
    
    def format_confirmation_prompt(self, request: ConfirmationRequest) -> str:
        """Format confirmation prompt for display.
        
        Args:
            request: ConfirmationRequest with plan details
        
        Returns:
            Formatted markdown prompt string
        """
        prompt = f"""# ✅ 确认方案

## 执行摘要

**意图**: {request.intent}
**预计耗时**: {request.execution_time}
**风险等级**: {request.risk_level}

---

## 方案预览

{request.plan_summary}

---

## 确认选项

请从以下选项中选择:

1. **[Y] 确认** - 按计划执行
2. **[E] 编辑** - 修改计划参数
3. **[D] 详情** - 显示完整计划
4. **[T] 时效** - 显示时间分解
5. **[N] 取消** - 放弃执行

**输入** (Y/E/D/T/N):
"""
        return prompt
    
    def validate_response(self, user_input: str) -> ConfirmationAction:
        """Validate and parse user's response.
        
        Args:
            user_input: User's input string
        
        Returns:
            ConfirmationAction based on input
        """
        if not user_input:
            return ConfirmationAction.TIMEOUT
        
        response = user_input.strip().upper()
        
        action_map = {
            "Y": ConfirmationAction.CONFIRMED,
            "YES": ConfirmationAction.CONFIRMED,
            "确认": ConfirmationAction.CONFIRMED,
            "E": ConfirmationAction.MODIFIED,
            "EDIT": ConfirmationAction.MODIFIED,
            "编辑": ConfirmationAction.MODIFIED,
            "D": ConfirmationAction.SHOW_DETAILS,
            "DETAIL": ConfirmationAction.SHOW_DETAILS,
            "详情": ConfirmationAction.SHOW_DETAILS,
            "T": ConfirmationAction.SHOW_TIMING,
            "TIME": ConfirmationAction.SHOW_TIMING,
            "时效": ConfirmationAction.SHOW_TIMING,
            "N": ConfirmationAction.CANCELLED,
            "NO": ConfirmationAction.CANCELLED,
            "取消": ConfirmationAction.CANCELLED,
            "CANCEL": ConfirmationAction.CANCELLED,
        }
        
        return action_map.get(response, ConfirmationAction.TIMEOUT)
    
    def should_show_full_plan(
        self, action: ConfirmationAction, full_plan: str
    ) -> str:
        """Return full plan if user requested details.
        
        Args:
            action: User's confirmation action
            full_plan: Complete plan markdown
        
        Returns:
            Full plan or empty string
        """
        if action == ConfirmationAction.SHOW_DETAILS:
            return f"""# 📋 完整方案

{full_plan}

---

请再次确认是否执行 (Y/E/N):
"""
        return ""
    
    def extract_timing_breakdown(self, plan_markdown: str) -> str:
        """Extract timing breakdown from plan markdown.
        
        Args:
            plan_markdown: Full plan markdown
        
        Returns:
            Formatted timing breakdown
        """
        # Parse markdown to extract timing info
        timing_section = "## ⏱️ 执行时间分解\n\n"
        
        # Extract step timings
        lines = plan_markdown.split("\n")
        for line in lines:
            if "(" in line and "s)" in line:
                timing_section += f"- {line.strip()}\n"
        
        # Extract critical path if present
        if "关键路径" in plan_markdown:
            for line in lines:
                if "关键路径" in line:
                    timing_section += f"\n{line}\n"
        
        timing_section += "\n请再次确认是否执行 (Y/E/N):"
        return timing_section
    
    def log_confirmation(
        self, request: ConfirmationRequest, response: ConfirmationResponse
    ) -> None:
        """Log confirmation event for audit trail.
        
        Args:
            request: Original confirmation request
            response: User's response
        """
        logger.info(
            f"Plan confirmation: action={response.action.value}, "
            f"intent={request.intent}, "
            f"timestamp={response.timestamp}"
        )
        if response.modified:
            logger.debug(f"Requested modifications: {response.modifications}")
        
        self.last_confirmation = response
    
    def create_confirmation_response(
        self,
        action: ConfirmationAction,
        modifications: Optional[Dict[str, Any]] = None,
        notes: str = ""
    ) -> ConfirmationResponse:
        """Create confirmation response object.
        
        Args:
            action: User's confirmed action
            modifications: Any requested parameter modifications
            notes: Optional user notes
        
        Returns:
            ConfirmationResponse object
        """
        import datetime
        
        return ConfirmationResponse(
            action=action,
            timestamp=datetime.datetime.now().isoformat(),
            modifications=modifications,
            user_notes=notes
        )


# Global singleton instance
_confirmation_handler_instance: Optional[ConfirmationHandler] = None


def get_confirmation_handler() -> ConfirmationHandler:
    """Get or create singleton confirmation handler instance.
    
    Returns:
        Shared ConfirmationHandler instance
    """
    global _confirmation_handler_instance
    if _confirmation_handler_instance is None:
        _confirmation_handler_instance = ConfirmationHandler()
    return _confirmation_handler_instance
