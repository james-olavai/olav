"""Error recovery and resilience for plan execution.

Phase 6.3: Error recovery provides graceful failure handling, automatic recovery,
and user-friendly error messages for plan execution failures.

Features:
- Centralized error handling
- Automatic retry strategies
- Graceful degradation
- User-friendly error messages
- Error categorization and logging
- Recovery state management
"""

import logging
from typing import Optional, Dict, Any, Callable, List
from enum import Enum
from dataclasses import dataclass
import asyncio
import time

logger = logging.getLogger(__name__)


class ErrorCategory(Enum):
    """Categories of errors that can occur during plan execution."""
    VALIDATION_ERROR = "validation"      # Input validation failures
    DEPENDENCY_ERROR = "dependency"      # Dependency resolution failed
    SUBAGENT_ERROR = "subagent"         # SubAgent execution failed
    TIMEOUT_ERROR = "timeout"           # Operation timed out
    RESOURCE_ERROR = "resource"         # Resource exhausted
    NETWORK_ERROR = "network"           # Network connectivity issues
    DATA_ERROR = "data"                 # Data processing errors
    UNKNOWN_ERROR = "unknown"           # Unexpected errors


class RecoveryStrategy(Enum):
    """Strategies for recovering from errors."""
    RETRY = "retry"                     # Retry the operation
    SKIP = "skip"                       # Skip this step
    FALLBACK = "fallback"               # Use fallback value/path
    CANCEL = "cancel"                   # Cancel execution
    MANUAL = "manual"                   # Require manual intervention


@dataclass
class PlanError:
    """Represents an error during plan execution.
    
    Attributes:
        category: ErrorCategory of the error
        message: Human-readable error message
        step: Which execution step failed
        cause: The underlying exception (if any)
        recoverable: Whether recovery is possible
        suggested_action: Suggested recovery strategy
    """
    category: ErrorCategory
    message: str
    step: Optional[str] = None
    cause: Optional[Exception] = None
    recoverable: bool = True
    suggested_action: RecoveryStrategy = RecoveryStrategy.RETRY


@dataclass
class RecoveryResult:
    """Result of recovery attempt.
    
    Attributes:
        success: Whether recovery succeeded
        strategy_used: Which RecoveryStrategy was used
        new_state: New execution state after recovery
        message: Status message for user
    """
    success: bool
    strategy_used: RecoveryStrategy
    new_state: Optional[Dict[str, Any]] = None
    message: str = ""


class ErrorRecoveryHandler:
    """Handles errors during plan execution and attempts recovery.
    
    Features:
    - Error categorization
    - Automatic retry with exponential backoff
    - Graceful degradation
    - Recovery strategy selection
    - Error logging and tracking
    """
    
    def __init__(self, max_retries: int = 3, base_retry_delay: float = 1.0):
        """Initialize error recovery handler.
        
        Args:
            max_retries: Maximum number of retry attempts
            base_retry_delay: Base retry delay in seconds (exponential backoff)
        """
        self.max_retries = max_retries
        self.base_retry_delay = base_retry_delay
        self.error_history: List[PlanError] = []
        self.recovery_attempts: Dict[str, int] = {}  # step -> attempt count
    
    def categorize_error(self, error: Exception, context: str = "") -> ErrorCategory:
        """Categorize an exception into ErrorCategory.
        
        Args:
            error: The exception to categorize
            context: Additional context (e.g., step name)
        
        Returns:
            ErrorCategory for the error
        """
        error_type = type(error).__name__
        error_msg = str(error).lower()
        
        # Categorization logic
        if "timeout" in error_msg or "TimeoutError" in error_type:
            return ErrorCategory.TIMEOUT_ERROR
        elif "network" in error_msg or "ConnectionError" in error_type:
            return ErrorCategory.NETWORK_ERROR
        elif "validation" in error_msg or "ValueError" in error_type:
            return ErrorCategory.VALIDATION_ERROR
        elif "resource" in error_msg or "MemoryError" in error_type:
            return ErrorCategory.RESOURCE_ERROR
        elif "dependency" in error_msg or "KeyError" in error_type:
            return ErrorCategory.DEPENDENCY_ERROR
        elif "parse" in error_msg or "JSONDecodeError" in error_type:
            return ErrorCategory.DATA_ERROR
        else:
            return ErrorCategory.UNKNOWN_ERROR
    
    def create_plan_error(
        self,
        error: Exception,
        step: Optional[str] = None,
        context: str = ""
    ) -> PlanError:
        """Create a PlanError from an exception.
        
        Args:
            error: The exception that occurred
            step: The execution step where error occurred
            context: Additional context
        
        Returns:
            PlanError object with categorization
        """
        category = self.categorize_error(error, context)
        recoverable, suggested_action = self._suggest_recovery(category)
        
        # Generate user-friendly message
        user_message = self._generate_error_message(category, str(error), step)
        
        plan_error = PlanError(
            category=category,
            message=user_message,
            step=step,
            cause=error,
            recoverable=recoverable,
            suggested_action=suggested_action
        )
        
        self.error_history.append(plan_error)
        logger.error(f"Plan error in step '{step}': {user_message}", exc_info=error)
        
        return plan_error
    
    def _suggest_recovery(self, category: ErrorCategory) -> tuple[bool, RecoveryStrategy]:
        """Suggest recovery strategy for error category.
        
        Args:
            category: The ErrorCategory
        
        Returns:
            Tuple of (recoverable, suggested_strategy)
        """
        recovery_map = {
            ErrorCategory.VALIDATION_ERROR: (False, RecoveryStrategy.MANUAL),
            ErrorCategory.DEPENDENCY_ERROR: (False, RecoveryStrategy.SKIP),
            ErrorCategory.SUBAGENT_ERROR: (True, RecoveryStrategy.RETRY),
            ErrorCategory.TIMEOUT_ERROR: (True, RecoveryStrategy.RETRY),
            ErrorCategory.RESOURCE_ERROR: (False, RecoveryStrategy.CANCEL),
            ErrorCategory.NETWORK_ERROR: (True, RecoveryStrategy.RETRY),
            ErrorCategory.DATA_ERROR: (True, RecoveryStrategy.FALLBACK),
            ErrorCategory.UNKNOWN_ERROR: (True, RecoveryStrategy.RETRY),
        }
        
        return recovery_map.get(category, (True, RecoveryStrategy.RETRY))
    
    def _generate_error_message(
        self, category: ErrorCategory, error_detail: str, step: Optional[str]
    ) -> str:
        """Generate user-friendly error message.
        
        Args:
            category: ErrorCategory
            error_detail: Detailed error message
            step: Execution step where error occurred
        
        Returns:
            User-friendly error message
        """
        step_info = f" 在步骤 '{step}'" if step else ""
        
        messages = {
            ErrorCategory.VALIDATION_ERROR: f"❌ 输入验证失败{step_info}: {error_detail}",
            ErrorCategory.DEPENDENCY_ERROR: f"⚠️  依赖错误{step_info}: 无法获取必要的前置数据",
            ErrorCategory.SUBAGENT_ERROR: f"⚠️  执行错误{step_info}: SubAgent 处理失败",
            ErrorCategory.TIMEOUT_ERROR: f"⏱️  超时错误{step_info}: 操作耗时过长",
            ErrorCategory.RESOURCE_ERROR: f"🔴 资源错误{step_info}: 资源不足",
            ErrorCategory.NETWORK_ERROR: f"🌐 网络错误{step_info}: 连接失败，稍后重试",
            ErrorCategory.DATA_ERROR: f"📊 数据错误{step_info}: 数据处理失败",
            ErrorCategory.UNKNOWN_ERROR: f"❓ 未知错误{step_info}: {error_detail}",
        }
        
        return messages.get(category, f"❌ 执行失败{step_info}: {error_detail}")
    
    async def retry_with_backoff(
        self,
        operation: Callable,
        step_name: str,
        *args,
        **kwargs
    ) -> Optional[Any]:
        """Execute operation with exponential backoff retry.
        
        Args:
            operation: Async callable to retry
            step_name: Name of the step (for tracking)
            *args: Arguments for operation
            **kwargs: Keyword arguments for operation
        
        Returns:
            Operation result or None if all retries failed
        """
        attempt = 0
        last_error = None
        
        while attempt <= self.max_retries:
            try:
                result = await operation(*args, **kwargs)
                
                # Clear retry counter on success
                self.recovery_attempts[step_name] = 0
                logger.info(f"Step '{step_name}' succeeded on attempt {attempt + 1}")
                return result
                
            except Exception as e:
                last_error = e
                attempt += 1
                self.recovery_attempts[step_name] = attempt
                
                if attempt <= self.max_retries:
                    # Exponential backoff: 1s, 2s, 4s, 8s
                    delay = self.base_retry_delay * (2 ** (attempt - 1))
                    logger.warning(
                        f"Step '{step_name}' attempt {attempt} failed: {e}. "
                        f"Retrying in {delay}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Step '{step_name}' failed after {self.max_retries + 1} attempts"
                    )
        
        return None
    
    async def execute_with_recovery(
        self,
        operation: Callable,
        step_name: str,
        fallback_value: Optional[Any] = None,
        *args,
        **kwargs
    ) -> tuple[bool, Optional[Any]]:
        """Execute operation with automatic recovery on failure.
        
        Args:
            operation: Async callable to execute
            step_name: Name of execution step
            fallback_value: Value to return if operation fails
            *args: Arguments for operation
            **kwargs: Keyword arguments for operation
        
        Returns:
            Tuple of (success, result). On failure, returns (False, fallback_value)
        """
        try:
            # Try with retries
            result = await self.retry_with_backoff(operation, step_name, *args, **kwargs)
            
            if result is not None:
                return (True, result)
            else:
                # All retries exhausted
                return (False, fallback_value)
                
        except Exception as e:
            error = self.create_plan_error(e, step=step_name)
            
            if error.suggested_action == RecoveryStrategy.FALLBACK:
                logger.info(f"Using fallback value for step '{step_name}'")
                return (False, fallback_value)
            else:
                return (False, fallback_value)
    
    def get_error_summary(self) -> str:
        """Get formatted summary of all errors encountered.
        
        Returns:
            Markdown formatted error summary
        """
        if not self.error_history:
            return "✅ 没有发生错误\n"
        
        summary = f"## ❌ 错误摘要\n\n发生了 {len(self.error_history)} 个错误:\n\n"
        
        for i, error in enumerate(self.error_history, 1):
            summary += f"{i}. **{error.category.value}** (步骤: {error.step or '未知'})\n"
            summary += f"   - {error.message}\n"
            if error.recoverable:
                summary += f"   - 可恢复: 建议 {error.suggested_action.value}\n"
            else:
                summary += f"   - 不可恢复: 需要手动干预\n"
            summary += "\n"
        
        return summary
    
    def clear_history(self) -> None:
        """Clear error history."""
        self.error_history.clear()
        self.recovery_attempts.clear()


# Global singleton instance
_error_handler_instance: Optional[ErrorRecoveryHandler] = None


def get_error_recovery_handler() -> ErrorRecoveryHandler:
    """Get or create singleton error recovery handler instance.
    
    Returns:
        Shared ErrorRecoveryHandler instance
    """
    global _error_handler_instance
    if _error_handler_instance is None:
        _error_handler_instance = ErrorRecoveryHandler()
    return _error_handler_instance
