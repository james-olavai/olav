"""Task Scheduler - Semantic task scheduling with cron integration.

Responsibilities:
- Parse natural language intent to cron expressions
- Create and validate scheduled tasks
- Auto-detect permission tiers from SQL queries
- Manage task lifecycle (created → scheduled → running → completed/expired → archived)

Permission Tiers:
- Green: Read-only queries (SELECT) - No approval needed
- Yellow: Modify operations (UPDATE, INSERT) - Requires HITL approval
- Red: Irreversible operations (DELETE, DROP) - Forbidden
- Forbidden: Explicitly blocked operations
"""

import logging
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from config.paths import (
    TASKS_SCHEDULED_DIR,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

# Cron field patterns
CRON_PATTERN = (
    r"^(\*|([0-9]|1[0-9]|2[0-9]|3[0-9]|4[0-9]|5[0-9])|\*/[0-9]+)"
    r"\s+(\*|([0-9]|1[0-9]|2[0-3])|\*/[0-9]+)"
    r"\s+(\*|([1-9]|1[0-9]|2[0-9]|3[0-1])|\*/[0-9]+)"
    r"\s+(\*|([1-9]|1[0-2])|\*/[0-9]+)"
    r"\s+(\*|([0-6])|\*/[0-9]+)$"
)

# Forbidden SQL patterns
FORBIDDEN_PATTERNS = [
    r"DROP\s+(TABLE|DATABASE|SCHEMA)",
    r"TRUNCATE",
    r"DELETE\s+\*",
    r"PRAGMA\s+drop_schema",
    r"ALTER\s+TABLE.*DROP",
]

# Permission tier patterns
PERMISSION_PATTERNS = {
    "red": [
        r"^DELETE",
        r"DROP\s+(TABLE|DATABASE|SCHEMA)",
        r"TRUNCATE",
    ],
    "yellow": [
        r"^UPDATE",
        r"^INSERT",
        r"^ALTER\s+TABLE",
        r"^CREATE\s+TABLE",
    ],
    "green": [
        r"^SELECT",
        r"^SHOW",
        r"^DESCRIBE",
        r"^EXPLAIN",
    ],
}


# =============================================================================
# Data Models
# =============================================================================


@dataclass
class TaskConfig:
    """Scheduled task configuration."""

    task_id: str
    query: str
    cron_expression: str
    permission_tier: str  # green, yellow, red, forbidden
    status: str  # created, scheduled, running, succeeded, failed, expired, cancelled, archived
    created_at: str
    modified_at: str

    name: str | None = None
    description: str | None = None
    duration_hours: int | None = None
    expires_at: str | None = None
    timeout_seconds: int = 300

    # Approval (Yellow tasks only)
    requires_approval: bool = False
    approval_status: str | None = None  # pending, approved, rejected
    approved_by: str | None = None
    rejected_by: str | None = None
    rejection_reason: str | None = None
    approval_timestamp: str | None = None

    # Notifications
    notifications: dict[str, Any] | None = None

    # Tracking
    last_execution_at: str | None = None
    last_execution_result: str | None = None
    execution_count: int = 0
    failure_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for YAML serialization."""
        return asdict(self)

    def to_yaml(self) -> str:
        """Convert to YAML string."""
        return yaml.dump(self.to_dict(), default_flow_style=False)  # noqa: ANN101


# =============================================================================
# Validation Functions
# =============================================================================


def validate_cron_expression(cron: str) -> bool:
    """Validate cron expression format.

    Args:
        cron: Cron expression (5 fields: minute hour day month weekday)

    Returns:
        True if valid, raises ValueError otherwise

    Examples:
        >>> validate_cron_expression("*/5 * * * *")  # Every 5 minutes
        True
        >>> validate_cron_expression("0 * * * *")     # Every hour
        True
        >>> validate_cron_expression("invalid")
        ValueError
    """
    if not re.match(CRON_PATTERN, cron.strip()):
        raise ValueError(f"Invalid cron expression: {cron}")
    return True


def detect_permission_tier(query: str) -> str:
    """Auto-detect permission tier from SQL query.

    Args:
        query: SQL query string

    Returns:
        Permission tier: "green", "yellow", "red", or "forbidden"

    Raises:
        PermissionError: If query is forbidden
    """
    query_upper = query.strip().upper()

    # Check forbidden patterns first
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, query_upper, re.IGNORECASE):
            raise PermissionError(f"Operation forbidden: {query}")

    # Check permission tiers
    for tier, patterns in PERMISSION_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, query_upper, re.IGNORECASE):
                return tier

    # Default to green (unknown operation, assume safe)
    return "green"


def validate_query_safety(query: str) -> None:
    """Validate query for forbidden operations.

    Args:
        query: SQL query to validate

    Raises:
        PermissionError: If query contains forbidden operations
    """
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, query.upper(), re.IGNORECASE):
            raise PermissionError(f"Forbidden operation detected: {query}")


# =============================================================================
# Task Schedule Creation
# =============================================================================


async def create_schedule_from_intent(intent: str) -> dict[str, Any]:
    """Parse natural language to scheduled task.

    Converts intents like:
    - "Monitor R1 BGP every 10 minutes for 24 hours"
    - "Check OSPF routes every 5 minutes for 2 hours"

    Into scheduled task configs.

    Args:
        intent: Natural language intent string

    Returns:
        Task configuration dict

    Raises:
        ValueError: If intent cannot be parsed
    """
    logger.info(f"Parsing intent: {intent}")

    # Use LLM to parse intent → structured query
    # For MVP, parse common patterns

    # Extract time interval (e.g., "every 10 minutes")
    interval_match = re.search(r"every\s+(\d+)\s+(minute|hour|day|week)s?", intent, re.IGNORECASE)

    if not interval_match:
        raise ValueError(f"Cannot parse interval from intent: {intent}")

    interval_value = int(interval_match.group(1))
    interval_unit = interval_match.group(2).lower()

    # Build cron expression
    if interval_unit == "minute":
        cron = f"*/{interval_value} * * * *"
    elif interval_unit == "hour":
        cron = f"0 */{interval_value} * * *"
    elif interval_unit == "day":
        cron = "0 0 * * *"  # Daily at midnight
    else:
        raise ValueError(f"Unknown interval unit: {interval_unit}")

    validate_cron_expression(cron)

    # Extract duration (e.g., "for 24 hours")
    duration_match = re.search(r"for\s+(\d+)\s+(hour|day|week)s?", intent, re.IGNORECASE)

    duration_hours = None
    if duration_match:
        duration_value = int(duration_match.group(1))
        duration_unit = duration_match.group(2).lower()

        if duration_unit == "hour":
            duration_hours = duration_value
        elif duration_unit == "day":
            duration_hours = duration_value * 24
        elif duration_unit == "week":
            duration_hours = duration_value * 24 * 7

    # Extract query/operation from intent
    # For MVP, assume intent contains a query starting with common keywords
    query = None
    for keyword in ["select", "read", "check", "monitor", "query"]:
        if keyword.lower() in intent.lower():
            # Extract operation description
            query = intent  # Placeholder: would use LLM to extract actual SQL
            break

    if not query:
        query = intent  # Fallback to intent as query description

    # Create task ID
    task_id = str(uuid.uuid4())[:8]

    now = datetime.now()
    expires_at = None
    if duration_hours:
        expires_at = (now + timedelta(hours=duration_hours)).isoformat()

    return {
        "task_id": task_id,
        "cron_expression": cron,
        "duration_hours": duration_hours,
        "expires_at": expires_at,
        "status": "scheduled",
        "created_at": now.isoformat(),
    }


async def create_task(
    query: str,
    cron: str,
    name: str | None = None,
    description: str | None = None,
    permission_tier: str | None = None,
    duration_hours: int | None = None,
    timeout_seconds: int = 300,
    notifications: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a new scheduled task.

    Args:
        query: SQL query or operation description
        cron: Cron expression (e.g., "*/10 * * * *")
        name: Task name
        description: Task description
        permission_tier: green/yellow/red/forbidden (auto-detected if not provided)
        duration_hours: Auto-expire after N hours
        timeout_seconds: Query execution timeout
        notifications: Notification config

    Returns:
        Task configuration

    Raises:
        ValueError: If cron or query invalid
        PermissionError: If query forbidden
    """
    # Validate cron
    validate_cron_expression(cron)

    # Validate query
    validate_query_safety(query)

    # Auto-detect permission tier if not specified
    if not permission_tier:
        permission_tier = detect_permission_tier(query)

    # Validate permission tier
    if permission_tier == "red":
        raise PermissionError("Red tier operations not permitted in scheduled tasks")

    # Create task
    task_id = str(uuid.uuid4())[:12]
    now = datetime.now()

    expires_at = None
    if duration_hours:
        expires_at = (now + timedelta(hours=duration_hours)).isoformat()

    task = TaskConfig(
        task_id=task_id,
        query=query,
        cron_expression=cron,
        permission_tier=permission_tier,
        status="created",
        created_at=now.isoformat(),
        modified_at=now.isoformat(),
        name=name,
        description=description,
        duration_hours=duration_hours,
        expires_at=expires_at,
        timeout_seconds=timeout_seconds,
        requires_approval=(permission_tier == "yellow"),
        approval_status="pending" if permission_tier == "yellow" else None,
        notifications=notifications or {},
    )

    logger.info(f"Created task {task_id}: {name or query[:50]}")

    # Save task configuration
    await save_task_config(task)

    return task.to_dict()


# =============================================================================
# Task Configuration Management
# =============================================================================


async def save_task_config(task: TaskConfig) -> Path:
    """Save task configuration to YAML file.

    Args:
        task: Task configuration

    Returns:
        Path to saved configuration file
    """
    TASKS_SCHEDULED_DIR.mkdir(parents=True, exist_ok=True)

    task_file = TASKS_SCHEDULED_DIR / f"{task.task_id}.yaml"

    with open(task_file, "w") as f:
        f.write(task.to_yaml())

    logger.debug(f"Saved task config: {task_file}")
    return task_file


async def load_task_config(task_id: str) -> TaskConfig:
    """Load task configuration from YAML file.

    Args:
        task_id: Task ID

    Returns:
        Task configuration

    Raises:
        FileNotFoundError: If task not found
    """
    task_file = TASKS_SCHEDULED_DIR / f"{task_id}.yaml"

    if not task_file.exists():
        raise FileNotFoundError(f"Task not found: {task_id}")

    with open(task_file) as f:
        data = yaml.safe_load(f)

    return TaskConfig(**data)


# =============================================================================
# Cron Expression Parsing (Reference)
# =============================================================================


def parse_cron_expression(cron: str) -> dict[str, Any]:
    """Parse cron expression into readable format.

    Args:
        cron: Cron expression (e.g., "*/5 * * * *")

    Returns:
        Dictionary with parsed fields

    Examples:
        >>> parse_cron_expression("*/5 * * * *")
        {'minute': '*/5', 'hour': '*', 'day': '*', 'month': '*', 'weekday': '*'}
    """
    fields = cron.split()
    if len(fields) != 5:
        raise ValueError(f"Invalid cron expression: {cron}")

    return {
        "minute": fields[0],
        "hour": fields[1],
        "day": fields[2],
        "month": fields[3],
        "weekday": fields[4],
    }


# =============================================================================
# Task Listing and Search
# =============================================================================


async def list_scheduled_tasks() -> list[dict[str, Any]]:
    """List all scheduled tasks.

    Returns:
        List of task configurations
    """
    tasks = []

    if not TASKS_SCHEDULED_DIR.exists():
        return tasks

    for task_file in TASKS_SCHEDULED_DIR.glob("*.yaml"):
        try:
            with open(task_file) as f:
                task_data = yaml.safe_load(f)
            tasks.append(task_data)
        except Exception as e:
            logger.error(f"Error loading task {task_file}: {e}")

    return tasks


async def find_tasks_by_status(status: str) -> list[dict[str, Any]]:
    """Find tasks by status.

    Args:
        status: Task status (created, scheduled, running, etc.)

    Returns:
        List of matching tasks
    """
    all_tasks = await list_scheduled_tasks()
    return [t for t in all_tasks if t.get("status") == status]
