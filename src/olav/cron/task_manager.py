"""Task Manager - Manage task lifecycle and configuration.

Responsibilities:
- Task CRUD operations (create, read, update, delete)
- Task state machine transitions
- Approval workflow management
- Git-based version control
- Task archival and cleanup
"""

import json
import logging
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from config.paths import (
    TASKS_ARCHIVE_DIR,
    TASKS_AUDIT_DIR,
    TASKS_DIR,
    TASKS_DLQ_DIR,
    TASKS_RESULTS_DIR,
    TASKS_SCHEDULED_DIR,
)
from olav.cron.task_executor import execute_task as executor_execute_task
from olav.cron.task_scheduler import create_task as scheduler_create_task

logger = logging.getLogger(__name__)


# =============================================================================
# Task Manager
# =============================================================================


class TaskManager:
    """Manage scheduled task lifecycle."""

    def __init__(self):
        """Initialize task manager."""
        self.created_directories = False

    async def init_directories(self) -> None:
        """Create task directories if not exist.""" 
        if self.created_directories:
            return

        for dir_path in [
            TASKS_DIR,
            TASKS_SCHEDULED_DIR,
            TASKS_RESULTS_DIR,
            TASKS_ARCHIVE_DIR,
            TASKS_DLQ_DIR,
            TASKS_AUDIT_DIR,
        ]:
            dir_path.mkdir(parents=True, exist_ok=True)

        self.created_directories = True
        logger.debug("Task directories initialized")

    # =========================================================================
    # Create / Read / Update / Delete
    # =========================================================================

    async def create_task(
        self,
        query: str,
        cron: str,
        name: str | None = None,
        description: str | None = None,
        permission_tier: str | None = None,
        duration_hours: int | None = None,
        notifications: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create new task.

        Args:
            query: SQL query
            cron: Cron expression
            name: Task name
            description: Task description
            permission_tier: green/yellow/red
            duration_hours: Auto-expire after N hours
            notifications: Notification config

        Returns:
            Task configuration
        """
        await self.init_directories()

        task = await scheduler_create_task(
            query=query,
            cron=cron,
            name=name,
            description=description,
            permission_tier=permission_tier,
            duration_hours=duration_hours,
            notifications=notifications,
        )

        await self._git_commit(
            f"Create task: {name or query[:50]}", TASKS_SCHEDULED_DIR / f"{task['task_id']}.yaml"
        )

        return task

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get task by ID.

        Args:
            task_id: Task ID

        Returns:
            Task configuration or None if not found
        """
        await self.init_directories()

        # Check scheduled tasks
        task_file = TASKS_SCHEDULED_DIR / f"{task_id}.yaml"
        if task_file.exists():
            with open(task_file) as f:
                return yaml.safe_load(f)

        # Check archived tasks
        archived_file = TASKS_ARCHIVE_DIR / f"{task_id}.yaml"
        if archived_file.exists():
            with open(archived_file) as f:
                return yaml.safe_load(f)

        # Check DLQ
        dlq_file = TASKS_DLQ_DIR / f"{task_id}.yaml"
        if dlq_file.exists():
            with open(dlq_file) as f:
                return yaml.safe_load(f)

        return None

    async def list_tasks(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List all tasks.

        Args:
            status: Filter by status (optional)

        Returns:
            List of task configurations
        """
        await self.init_directories()

        tasks = []

        # Load from all directories
        for task_dir in [TASKS_SCHEDULED_DIR, TASKS_ARCHIVE_DIR, TASKS_DLQ_DIR]:
            if not task_dir.exists():
                continue

            for task_file in task_dir.glob("*.yaml"):
                try:
                    with open(task_file) as f:
                        task = yaml.safe_load(f)

                    if status is None or task.get("status") == status:
                        tasks.append(task)

                except Exception as e:
                    logger.error(f"Error loading task {task_file}: {e}")

        return tasks

    async def update_task(self, task_id: str, **updates) -> dict[str, Any]:
        """Update task configuration.

        Args:
            task_id: Task ID
            **updates: Fields to update

        Returns:
            Updated task configuration

        Raises:
            FileNotFoundError: If task not found
        """
        await self.init_directories()

        task = await self.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")

        # Update fields
        task.update(updates)
        task["modified_at"] = datetime.now().isoformat()

        # Save updated config
        task_file = TASKS_SCHEDULED_DIR / f"{task_id}.yaml"
        with open(task_file, "w") as f:
            yaml.dump(task, f)

        await self._git_commit(f"Update task: {task_id}", task_file)

        return task

    async def delete_task(self, task_id: str) -> None:
        """Delete task (move to archive).

        Args:
            task_id: Task ID
        """
        await self.archive_task(task_id)

    # =========================================================================
    # Task Lifecycle
    # =========================================================================

    async def schedule_task(self, task_id: str) -> dict[str, Any]:
        """Mark task as scheduled.

        Args:
            task_id: Task ID

        Returns:
            Updated task
        """
        return await self.update_task(
            task_id,
            status="scheduled",
        )

    async def execute_task(self, task_id: str) -> dict[str, Any]:
        """Execute task immediately.

        Args:
            task_id: Task ID

        Returns:
            Execution result
        """
        task = await self.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")

        # Mark as running
        task["status"] = "running"
        task["modified_at"] = datetime.now().isoformat()

        task_file = TASKS_SCHEDULED_DIR / f"{task_id}.yaml"
        with open(task_file, "w") as f:
            yaml.dump(task, f)

        # Execute
        result = await executor_execute_task(task)

        # Update task after execution
        if result.status == "success":
            await self.mark_task_completed(task_id)
        else:
            await self.mark_task_failed(task_id)

        return result.to_dict()

    async def mark_task_completed(self, task_id: str) -> dict[str, Any]:
        """Mark task as completed.

        Args:
            task_id: Task ID

        Returns:
            Updated task
        """
        return await self.update_task(
            task_id,
            status="succeeded",
            last_execution_at=datetime.now().isoformat(),
        )

    async def mark_task_failed(self, task_id: str) -> dict[str, Any]:
        """Mark task as failed.

        Args:
            task_id: Task ID

        Returns:
            Updated task
        """
        task = await self.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")

        failure_count = task.get("failure_count", 0) + 1

        return await self.update_task(
            task_id,
            status="failed",
            failure_count=failure_count,
            last_execution_at=datetime.now().isoformat(),
        )

    # =========================================================================
    # Approval Workflow
    # =========================================================================

    async def approve_task(
        self,
        task_id: str,
        approved_by: str,
    ) -> dict[str, Any]:
        """Approve yellow task for execution.

        Args:
            task_id: Task ID
            approved_by: Approver name

        Returns:
            Updated task
        """
        task = await self.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")

        if task.get("permission_tier") != "yellow":
            raise ValueError("Only yellow tasks require approval")

        # Update approval status
        task = await self.update_task(
            task_id,
            approval_status="approved",
            approved_by=approved_by,
            approval_timestamp=datetime.now().isoformat(),
        )

        # Log to audit trail
        await self._audit_log(task_id, "approved", {"approved_by": approved_by})

        return task

    async def reject_task(
        self,
        task_id: str,
        reason: str,
        rejected_by: str | None = None,
    ) -> dict[str, Any]:
        """Reject yellow task.

        Args:
            task_id: Task ID
            reason: Rejection reason
            rejected_by: Rejector name

        Returns:
            Updated task
        """
        task = await self.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")

        # Update rejection status
        task = await self.update_task(
            task_id,
            approval_status="rejected",
            rejection_reason=reason,
            rejected_by=rejected_by,
        )

        # Log to audit trail
        await self._audit_log(task_id, "rejected", {"reason": reason, "rejected_by": rejected_by})

        return task

    # =========================================================================
    # Task Archival
    # =========================================================================

    async def archive_task(self, task_id: str) -> None:
        """Archive task (move to archived directory).

        Args:
            task_id: Task ID
        """
        task = await self.get_task(task_id)
        if not task:
            raise FileNotFoundError(f"Task not found: {task_id}")

        TASKS_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

        # Move file
        source = TASKS_SCHEDULED_DIR / f"{task_id}.yaml"
        dest = TASKS_ARCHIVE_DIR / f"{task_id}.yaml"

        if source.exists():
            source.rename(dest)

        task["status"] = "archived"
        task["modified_at"] = datetime.now().isoformat()

        with open(dest, "w") as f:
            yaml.dump(task, f)

        await self._git_commit(f"Archive task: {task_id}", dest)

    async def archive_expired_tasks(self) -> int:
        """Archive expired tasks.

        Returns:
            Number of archived tasks
        """
        count = 0
        now = datetime.now()

        tasks = await self.list_tasks()

        for task in tasks:
            expires_at = task.get("expires_at")
            if not expires_at:
                continue

            expires_dt = datetime.fromisoformat(expires_at)

            if now > expires_dt:
                await self.archive_task(task["task_id"])
                count += 1

        return count

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        """Cancel scheduled task.

        Args:
            task_id: Task ID

        Returns:
            Updated task
        """
        return await self.update_task(
            task_id,
            status="cancelled",
        )

    # =========================================================================
    # Git Integration
    # =========================================================================

    async def _git_commit(self, message: str, file_path: Path) -> None:
        """Commit task file to Git.

        Args:
            message: Commit message
            file_path: File to commit
        """
        try:
            # Stage file
            subprocess.run(
                ["git", "add", str(file_path)],
                cwd=TASKS_DIR,
                capture_output=True,
                check=False,
            )

            # Commit
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=TASKS_DIR,
                capture_output=True,
                check=False,
            )

            logger.debug(f"Git commit: {message}")

        except Exception as e:
            logger.warning(f"Git commit failed: {e}")

    async def rollback_task(self, task_id: str, commits_back: int = 1) -> dict[str, Any]:
        """Rollback task to previous version.

        Args:
            task_id: Task ID
            commits_back: Number of commits to go back

        Returns:
            Restored task configuration
        """
        task_file = TASKS_SCHEDULED_DIR / f"{task_id}.yaml"

        try:
            # Checkout previous version
            subprocess.run(
                ["git", "checkout", f"HEAD~{commits_back}", str(task_file)],
                cwd=TASKS_DIR,
                capture_output=True,
                check=True,
            )

            # Load restored config
            with open(task_file) as f:
                task = yaml.safe_load(f)

            logger.info(f"Rolled back task {task_id} ({commits_back} commits)")

            return task

        except Exception as e:
            logger.error(f"Rollback failed: {e}")
            raise

    # =========================================================================
    # Auditing
    # =========================================================================

    async def _audit_log(
        self,
        task_id: str,
        action: str,
        details: dict[str, Any],
    ) -> None:
        """Log task action to audit trail.

        Args:
            task_id: Task ID
            action: Action performed
            details: Action details
        """
        TASKS_AUDIT_DIR.mkdir(parents=True, exist_ok=True)

        audit_file = TASKS_AUDIT_DIR / f"{task_id}_approvals.log"

        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "action": action,
            "details": details,
        }

        with open(audit_file, "a") as f:
            f.write(json.dumps(log_entry) + "\n")

        logger.debug(f"Audit log: {task_id} {action}")
