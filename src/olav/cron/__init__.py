"""Task Scheduler Package - Semantic task scheduling and execution.

Modules:
- task_scheduler: Task creation and cron scheduling
- task_executor: Task execution with resilience patterns
- task_manager: Task lifecycle management

Example:
    >>> from olav.cron.task_manager import TaskManager
    >>> manager = TaskManager()
    >>> task = await manager.create_task(
    ...     query="SELECT COUNT(*) FROM devices",
    ...     cron="*/10 * * * *"
    ... )
"""

from olav.cron.task_executor import (
    CircuitBreaker,
    NotificationRateLimiter,
    execute_task,
)
from olav.cron.task_manager import TaskManager
from olav.cron.task_scheduler import (
    create_schedule_from_intent,
    create_task,
    detect_permission_tier,
    validate_cron_expression,
)

__all__ = [
    "create_task",
    "create_schedule_from_intent",
    "validate_cron_expression",
    "detect_permission_tier",
    "execute_task",
    "CircuitBreaker",
    "NotificationRateLimiter",
    "TaskManager",
]
