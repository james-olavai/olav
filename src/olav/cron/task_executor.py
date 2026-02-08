"""Task Executor - Execute scheduled tasks with resilience patterns.

Responsibilities:
- Execute tasks with retry logic and exponential backoff
- Manage circuit breaker for failing tasks
- Route failed tasks to dead letter queue
- Track execution results and metrics
- Handle timeouts and failures gracefully

Resilience Patterns:
- Exponential Backoff: 4s, 8s, 10s max
- Circuit Breaker: Open after 5 consecutive failures
- Dead Letter Queue: Failed tasks moved to DLQ for manual review
- Timeout Handling: Configurable execution timeout
"""

import asyncio
import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from tenacity import retry, stop_after_attempt, wait_exponential

from config.paths import (
    TASKS_DLQ_DIR,
    TASKS_RESULTS_DIR,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class TaskExecutionResult:
    """Result of task execution."""

    task_id: str
    status: str  # success, failure, timeout, circuit_open
    execution_time: float  # Seconds
    result: dict[str, Any] | None = None
    error: str | None = None
    retry_count: int = 0
    executed_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_json(self) -> str:
        """Convert to JSON string."""
        data = self.to_dict()
        data["executed_at"] = data["executed_at"] or datetime.now().isoformat()
        return json.dumps(data, default=str)


# =============================================================================
# Circuit Breaker
# =============================================================================


class CircuitBreaker:
    """Circuit breaker for task execution.

    States:
    - Closed (normal): Execute requests
    - Open: Reject requests (too many failures)
    - Half-Open: Attempt recovery (experimental request)
    """

    def __init__(self, failure_threshold: int = 5, reset_timeout_seconds: int = 300) -> None:
        """Initialize circuit breaker.

        Args:
            failure_threshold: Open circuit after N failures
            reset_timeout_seconds: Time until half-open state
        """
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds

        self.failures: dict[str, int] = {}
        self.open_circuits: dict[str, datetime] = {}  # task_id → open_time

    def is_open(self, task_id: str) -> bool:
        """Check if circuit is open.

        Args:
            task_id: Task ID

        Returns:
            True if circuit is open, False otherwise
        """
        if task_id not in self.open_circuits:
            return False

        # Check if timeout elapsed (half-open state)
        open_time = self.open_circuits[task_id]
        elapsed = (datetime.now() - open_time).total_seconds()

        if elapsed > self.reset_timeout_seconds:
            # Half-open: Allow 1 attempt to recover
            return False

        return True

    def record_success(self, task_id: str) -> None:
        """Record successful execution.

        Args:
            task_id: Task ID
        """
        self.failures[task_id] = 0
        self.open_circuits.pop(task_id, None)
        logger.debug(f"Circuit breaker CLOSED for {task_id}")

    def record_failure(self, task_id: str) -> None:
        """Record execution failure.

        Args:
            task_id: Task ID
        """
        self.failures[task_id] = self.failures.get(task_id, 0) + 1

        if self.failures[task_id] >= self.failure_threshold:
            self.open_circuits[task_id] = datetime.now()
            logger.warning(
                f"Circuit breaker OPEN for {task_id} ({self.failures[task_id]} failures)"
            )

    def reset(self, task_id: str) -> None:
        """Manually reset circuit breaker.

        Args:
            task_id: Task ID
        """
        self.failures[task_id] = 0
        self.open_circuits.pop(task_id, None)
        logger.info(f"Circuit breaker manually reset for {task_id}")

    def failure_count(self, task_id: str) -> int:
        """Get failure count for task.

        Args:
            task_id: Task ID

        Returns:
            Number of consecutive failures
        """
        return self.failures.get(task_id, 0)


# Global circuit breaker
global_circuit_breaker = CircuitBreaker()


# =============================================================================
# Retry Logic with Exponential Backoff
# =============================================================================


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10), reraise=True)
async def execute_task_with_retry(
    task_config: dict[str, Any],
) -> dict[str, Any]:
    """Execute task with automatic retry.

    Retry schedule:
    - Attempt 1: Immediate
    - Attempt 2: Wait 4+ seconds
    - Attempt 3: Wait 8+ seconds (max 10s)

    Args:
        task_config: Task configuration

    Returns:
        Query execution result

    Raises:
        Exception: If all retries exhausted
    """
    from olav.agents.orchestrator import orchestrate_query

    task_id = task_config.get("task_id")
    query = task_config.get("query")

    logger.debug(f"Executing task {task_id} (retry attempt)")

    # Execute query using orchestrator
    result = await orchestrate_query(query)

    return result


# =============================================================================
# Task Execution
# =============================================================================


async def execute_task(task_config: dict[str, Any]) -> TaskExecutionResult:
    """Execute scheduled task with resilience patterns.

    Implements:
    - Circuit breaker (reject if too many failures)
    - Retry logic with exponential backoff
    - Timeout handling
    - Dead letter queue for failures

    Args:
        task_config: Task configuration

    Returns:
        Execution result
    """
    task_id = task_config.get("task_id")
    query = task_config.get("query")
    timeout_seconds = task_config.get("timeout_seconds", 300)

    start_time = datetime.now()

    # Check circuit breaker
    if global_circuit_breaker.is_open(task_id):
        logger.warning(f"Circuit breaker OPEN for {task_id}, skipping execution")
        return TaskExecutionResult(
            task_id=task_id,
            status="circuit_open",
            execution_time=0,
            error="Circuit breaker open",
        )

    try:
        # Execute with timeout
        logger.info(f"Executing task {task_id}: {query[:50]}...")

        try:
            result = await asyncio.wait_for(
                execute_task_with_retry(task_config), timeout=timeout_seconds
            )
        except TimeoutError as e:
            raise TimeoutError(f"Task execution timeout after {timeout_seconds}s") from e

        # Success
        global_circuit_breaker.record_success(task_id)
        execution_time = (datetime.now() - start_time).total_seconds()

        logger.info(f"Task {task_id} succeeded in {execution_time:.2f}s")

        return TaskExecutionResult(
            task_id=task_id,
            status="success",
            execution_time=execution_time,
            result=result if isinstance(result, dict) else {"data": result},
            executed_at=datetime.now().isoformat(),
        )

    except Exception as e:
        # Failure
        global_circuit_breaker.record_failure(task_id)
        execution_time = (datetime.now() - start_time).total_seconds()
        error_msg = str(e)

        logger.error(f"Task {task_id} failed: {error_msg}")

        # Move to DLQ if circuit opens
        if global_circuit_breaker.is_open(task_id):
            await move_to_dead_letter_queue(task_config, error_msg)
            await send_alert(
                f"Task {task_id} moved to DLQ after "
                f"{global_circuit_breaker.failure_count(task_id)} failures"
            )

        return TaskExecutionResult(
            task_id=task_id,
            status="failure",
            execution_time=execution_time,
            error=error_msg,
            retry_count=0,
            executed_at=datetime.now().isoformat(),
        )


# =============================================================================
# Dead Letter Queue Management
# =============================================================================


async def move_to_dead_letter_queue(task_config: dict[str, Any], error: str) -> Path:
    """Move failed task to dead letter queue.

    DLQ stores failed task configs for manual review and retry.

    Args:
        task_config: Failed task configuration
        error: Error message

    Returns:
        Path to DLQ file
    """
    TASKS_DLQ_DIR.mkdir(parents=True, exist_ok=True)

    dlq_file = TASKS_DLQ_DIR / f"{task_config['task_id']}.yaml"

    # Add DLQ metadata
    dlq_config = dict(task_config)
    dlq_config["dlq_timestamp"] = datetime.now().isoformat()
    dlq_config["dlq_error"] = error
    dlq_config["dlq_failure_count"] = global_circuit_breaker.failure_count(task_config["task_id"])

    with open(dlq_file, "w") as f:
        yaml.dump(dlq_config, f)

    logger.warning(f"Task {task_config['task_id']} moved to DLQ: {dlq_file}")

    return dlq_file


# =============================================================================
# Result Persistence
# =============================================================================


async def save_execution_result(result: TaskExecutionResult) -> Path:
    """Save task execution result to file.

    Args:
        result: Execution result

    Returns:
        Path to result file
    """
    TASKS_RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    result_file = TASKS_RESULTS_DIR / f"{result.task_id}.json"

    result_file.write_text(result.to_json())

    return result_file


async def get_execution_result(task_id: str) -> dict[str, Any] | None:
    """Get saved execution result.

    Args:
        task_id: Task ID

    Returns:
        Execution result dictionary or None if not found
    """
    result_file = TASKS_RESULTS_DIR / f"{task_id}.json"

    if not result_file.exists():
        return None

    return json.loads(result_file.read_text())


class NotificationRateLimiter:
    """Rate limit notifications to prevent spam.

    Config:
    - Max N emails per hour
    - Batch failures into single digest
    - Escalate after M consecutive failures
    """

    def __init__(self, max_per_hour: int = 5):
        """Initialize rate limiter.

        Args:
            max_per_hour: Maximum notifications per hour
        """
        self.max_per_hour = max_per_hour
        self.notifications: dict[str, list[datetime]] = {}

    def should_notify(self, task_id: str) -> bool:
        """Check if notification should be sent.

        Args:
            task_id: Task ID

        Returns:
            True if under rate limit, False otherwise
        """
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)

        # Get notifications from last hour
        if task_id not in self.notifications:
            self.notifications[task_id] = []

        recent = [t for t in self.notifications[task_id] if t > hour_ago]
        self.notifications[task_id] = recent

        # Check rate limit
        if len(recent) >= self.max_per_hour:
            return False

        # Record this notification
        self.notifications[task_id].append(now)
        return True


# =============================================================================
# Alerting
# =============================================================================


async def send_alert(message: str) -> None:
    """Send alert notification.

    Args:
        message: Alert message
    """
    # TODO: Implement alerting (email, Slack, etc.)
    logger.warning(f"ALERT: {message}")
