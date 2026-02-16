"""Cron Task Manager - OLAV v2.0

Manages periodic inspection tasks using python-crontab.

Features:
- Schedule/unschedule tasks from TaskSchedulerSettings
- Execute tasks on-demand or automatically
- Track task execution history and logs
- Handle retry logic and notifications
- Provide task status and monitoring

Usage:
    from src.olav.lib.cron_manager import TaskManager
    
    manager = TaskManager()
    manager.schedule_all()          # Schedule all enabled tasks
    status = manager.get_status()   # Get task execution status
    result = manager.run_task("daily-inspection")  # Run task on-demand
"""

import json
import logging
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from crontab import CronTab
from pydantic import ValidationError

from config.settings import settings
from config.tasks import TaskDefinition, TaskSchedulerSettings
from config.paths import UNIFIED_DB, OLAV_BASE_DIR

logger = logging.getLogger(__name__)


class TaskManager:
    """Manages cron-based task scheduling and execution"""
    
    def __init__(self):
        """Initialize task manager"""
        self.config: TaskSchedulerSettings = settings.tasks
        self.logs_dir = Path(self.config.log_dir)
        self.reports_dir = Path(self.config.report_dir)
        self.status_file = self.logs_dir / "task_status.json"
        
        # Ensure directories exist
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        
        # Load crontab
        try:
            self.cron = CronTab(user=True)
        except Exception as e:
            logger.error(f"Failed to access crontab: {e}")
            self.cron = None
    
    def schedule_all(self) -> dict[str, Any]:
        """Schedule all enabled tasks to crontab
        
        Returns:
            {
                "status": "success" | "failed",
                "scheduled": int (count),
                "skipped": int (count),
                "errors": list[str]
            }
        """
        if not self.config.enabled:
            logger.warning("Task scheduler disabled globally (config.tasks.enabled=False)")
            return {
                "status": "skipped",
                "message": "Task scheduler disabled",
                "scheduled": 0,
                "skipped": 0,
                "errors": []
            }
        
        if not self.cron:
            return {
                "status": "failed",
                "message": "Cannot access crontab",
                "scheduled": 0,
                "skipped": 0,
                "errors": ["Failed to access crontab"]
            }
        
        results = {
            "status": "success",
            "scheduled": 0,
            "skipped": 0,
            "errors": [],
            "tasks": {}
        }
        
        for task_name, task_def in self.config.tasks.items():
            try:
                if task_def.enabled:
                    self._schedule_task(task_def)
                    results["scheduled"] += 1
                    results["tasks"][task_name] = "scheduled"
                    logger.info(f"✓ Scheduled task: {task_name}")
                else:
                    self._unschedule_task(task_def)
                    results["skipped"] += 1
                    results["tasks"][task_name] = "disabled"
                    logger.info(f"✓ Unscheduled task: {task_name}")
            
            except Exception as e:
                results["errors"].append(f"{task_name}: {str(e)}")
                results["tasks"][task_name] = "failed"
                logger.error(f"✗ Error scheduling {task_name}: {e}")
        
        # Save crontab changes
        if results["scheduled"] > 0:
            try:
                self.cron.write()
                logger.info(f"Crontab saved: {results['scheduled']} tasks scheduled")
            except Exception as e:
                results["status"] = "partial"
                results["errors"].append(f"Failed to save crontab: {str(e)}")
                logger.error(f"Failed to write crontab: {e}")
        
        return results
    
    def _schedule_task(self, task_def: TaskDefinition):
        """Schedule a single task to crontab"""
        # Build command
        command = self._build_command(task_def)
        comment = f"OLAV-{task_def.name}"
        
        # Find existing job
        existing_job = None
        for job in self.cron:
            if job.comment == comment:
                existing_job = job
                break
        
        if existing_job:
            # Update existing job
            existing_job.setall(task_def.schedule)
            logger.debug(f"Updated cron job: {comment}")
        else:
            # Create new job
            job = self.cron.new(command=command, comment=comment)
            job.setall(task_def.schedule)
            logger.debug(f"Created new cron job: {comment}")
    
    def _unschedule_task(self, task_def: TaskDefinition):
        """Remove a task from crontab"""
        comment = f"OLAV-{task_def.name}"
        
        for job in list(self.cron):
            if job.comment == comment:
                self.cron.remove(job)
                logger.debug(f"Removed cron job: {comment}")
                break
    
    def _build_command(self, task_def: TaskDefinition) -> str:
        """Build shell command for task execution
        
        Format: cd {project_root} && python3 -m uv run {command} >> {log_file} 2>&1
        """
        log_file = self.logs_dir / f"{task_def.name}.log"
        
        # Substitute workflow name in command
        cmd = task_def.command.format(workflow=task_def.workflow)
        
        # Full command with logging and error handling
        full_cmd = f"cd {Path.cwd()} && {cmd} >> {log_file} 2>&1"
        
        return full_cmd
    
    def run_task(self, task_name: str, force: bool = False) -> dict[str, Any]:
        """Execute a task on-demand
        
        Args:
            task_name: Name of task to run
            force: Skip enabled check and run anyway
        
        Returns:
            {
                "status": "success" | "failed",
                "task": task_name,
                "started": datetime,
                "duration": seconds,
                "output": str,
                "error": str or None
            }
        """
        task_def = self.config.get_task(task_name)
        if not task_def:
            return {
                "status": "failed",
                "error": f"Task not found: {task_name}"
            }
        
        if not task_def.enabled and not force:
            return {
                "status": "skipped",
                "message": f"Task disabled: {task_name} (use force=True to override)"
            }
        
        # Build and execute command
        command = self._build_command(task_def)
        log_file = self.logs_dir / f"{task_def.name}.log"
        
        start_time = datetime.now()
        logger.info(f"Starting task: {task_name}")
        
        try:
            # Execute with timeout
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=task_def.timeout
            )
            
            duration = (datetime.now() - start_time).total_seconds()
            
            if result.returncode == 0:
                logger.info(f"✓ Task completed: {task_name} ({duration:.1f}s)")
                return {
                    "status": "success",
                    "task": task_name,
                    "started": start_time.isoformat(),
                    "duration": duration,
                    "output": result.stdout,
                    "returncode": 0
                }
            else:
                logger.error(f"✗ Task failed: {task_name} (exit code: {result.returncode})")
                return {
                    "status": "failed",
                    "task": task_name,
                    "started": start_time.isoformat(),
                    "duration": duration,
                    "error": result.stderr,
                    "returncode": result.returncode
                }
        
        except subprocess.TimeoutExpired:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"✗ Task timeout: {task_name} (>{task_def.timeout}s)")
            return {
                "status": "timeout",
                "task": task_name,
                "started": start_time.isoformat(),
                "duration": duration,
                "error": f"Task exceeded timeout ({task_def.timeout}s)"
            }
        
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            logger.error(f"✗ Task error: {task_name} - {str(e)}")
            return {
                "status": "failed",
                "task": task_name,
                "started": start_time.isoformat(),
                "duration": duration,
                "error": str(e)
            }
    
    def get_status(self) -> dict[str, Any]:
        """Get status of all tasks
        
        Returns:
            {
                "crontab_enabled": bool,
                "tasks_count": int,
                "enabled_count": int,
                "tasks": {
                    "task_name": {
                        "enabled": bool,
                        "schedule": "cron_expr",
                        "last_run": datetime or None,
                        "last_status": "success" | "failed" | None
                    }
                }
            }
        """
        tasks_info = {}
        
        for task_name, task_def in self.config.tasks.items():
            # Try to find last execution in logs
            log_file = self.logs_dir / f"{task_name}.log"
            last_run = None
            
            if log_file.exists():
                try:
                    last_run = datetime.fromtimestamp(log_file.stat().st_mtime)
                except Exception:
                    pass
            
            # Get task info
            tasks_info[task_name] = {
                "enabled": task_def.enabled,
                "description": task_def.description,
                "schedule": task_def.schedule,
                "workflow": task_def.workflow,
                "timeout": task_def.timeout,
                "last_run": last_run.isoformat() if last_run else None,
                "next_run": self._get_next_run(task_def) if self.cron else None,
            }
        
        return {
            "status": "ok",
            "crontab_available": self.cron is not None,
            "scheduler_enabled": self.config.enabled,
            "total_tasks": len(self.config.tasks),
            "enabled_tasks": sum(1 for t in self.config.tasks.values() if t.enabled),
            "tasks": tasks_info
        }
    
    def _get_next_run(self, task_def: TaskDefinition) -> str | None:
        """Calculate next run time from cron expression"""
        if not self.cron:
            return None
        
        try:
            from croniter import croniter
            cron = croniter(task_def.schedule)
            next_run = cron.get_next(datetime)
            return next_run.isoformat()
        except Exception:
            return None
    
    def cleanup_old_logs(self) -> dict[str, Any]:
        """Clean up old task logs based on retention policy
        
        Returns:
            {"deleted": int, "freed_bytes": int}
        """
        now = datetime.now()
        cutoff = now - timedelta(days=self.config.task_log_retention_days)
        
        deleted = 0
        freed_bytes = 0
        
        for log_file in self.logs_dir.glob("*.log"):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff:
                    file_size = log_file.stat().st_size
                    log_file.unlink()
                    deleted += 1
                    freed_bytes += file_size
                    logger.debug(f"Deleted old log: {log_file.name}")
            except Exception as e:
                logger.warning(f"Failed to delete {log_file}: {e}")
        
        return {
            "status": "success",
            "deleted": deleted,
            "freed_bytes": freed_bytes,
            "retention_days": self.config.task_log_retention_days
        }


# Convenience function
def get_task_manager() -> TaskManager:
    """Get task manager instance (singleton pattern recommended)"""
    return TaskManager()
