"""Task Scheduler Configuration - OLAV v2.0

Manages periodic inspection tasks using python-crontab.

Configuration Priority (high to low):
1. Environment variables (TASK_*)
2. .olav/config/tasks.json
3. Code defaults (TaskSchedulerSettings)

Design Principles:
- KISS: Simple cron-based scheduling (not Airflow/Prefect)
- Dynamic loading: All tasks from config, not hardcoded
- Configurable: Adjust schedule without code changes
- No hardcoding: Times, names, parameters all configurable
"""

from typing import Literal
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict, JsonConfigSettingsSource


class TaskDefinition(BaseModel):
    """Single task definition"""
    
    name: str = Field(
        ...,
        description="Task name (e.g., 'daily-inspection')",
        min_length=1,
        max_length=50
    )
    description: str = Field(
        default="",
        description="Human-readable task description"
    )
    
    # Task execution
    workflow: str = Field(
        ...,
        description="Workflow to execute (.olav/workflows/{workflow}.md)"
    )
    command: str = Field(
        ...,
        description="Command template (e.g., 'olav inspect {workflow}')"
    )
    
    # Schedule
    schedule: str = Field(
        ...,
        description="Cron expression (e.g., '0 6 * * *' = daily 6am)",
        pattern=r"^(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)\s+(\*|[0-9,\-/]+)\s+(\*|[0-7,\-/]+)$"
    )
    
    # Control
    enabled: bool = Field(
        default=True,
        description="Enable/disable this task"
    )
    timeout: int = Field(
        default=3600,
        ge=60,
        le=86400,
        description="Task timeout in seconds (60s-24h)"
    )
    
    # Retries
    max_retries: int = Field(
        default=3,
        ge=0,
        le=10,
        description="Max retry attempts on failure"
    )
    retry_delay: int = Field(
        default=300,
        ge=60,
        le=3600,
        description="Delay between retries (seconds)"
    )
    
    # Notifications
    notify_on_failure: bool = Field(
        default=True,
        description="Send notification on task failure"
    )
    notify_on_success: bool = Field(
        default=False,
        description="Send notification on task success"
    )
    
    # Custom parameters (task-specific)
    params: dict = Field(
        default_factory=dict,
        description="Task-specific parameters (kwargs to task)"
    )


class TaskSchedulerSettings(BaseSettings):
    """Task scheduler configuration"""
    
    # Global settings
    enabled: bool = Field(
        default=True,
        description="Enable task scheduler globally"
    )
    
    log_dir: str = Field(
        default=".olav/logs",
        description="Log directory for task execution"
    )
    
    report_dir: str = Field(
        default="exports/reports",  # FIXED: Changed from exports/reports/snapshots (removed redundant snapshots subdir)
        description="Report directory for task outputs"
    )
    
    # Task definitions (from config file or env)
    tasks: dict[str, TaskDefinition] = Field(
        default_factory=lambda: {
            # Default daily inspection task
            "daily-inspection": TaskDefinition(
                name="daily-inspection",
                description="Daily network inspection snapshot",
                workflow="daily-run",
                command="olav inspect {workflow}",
                schedule="0 6 * * *",  # 6am daily
                enabled=True,
                timeout=1800,  # 30 minutes
                max_retries=2,
                notify_on_failure=True,
            ),
            # Weekly deep audit
            "weekly-audit": TaskDefinition(
                name="weekly-audit",
                description="Weekly network deep audit with LLM analysis",
                workflow="weekly-audit",
                command="olav inspect {workflow} --deep",
                schedule="0 2 * * 0",  # Sunday 2am
                enabled=False,  # Disabled by default
                timeout=3600,
                max_retries=1,
                notify_on_failure=True,
                notify_on_success=True,
            ),
            # Monthly report generation
            "monthly-report": TaskDefinition(
                name="monthly-report",
                description="Generate monthly operations report",
                workflow="monthly-report",
                command="olav report generate --month",
                schedule="0 9 1 * *",  # 1st of month 9am
                enabled=False,  # Disabled by default
                timeout=3600,
                max_retries=1,
                notify_on_failure=True,
            ),
        },
        description="Task definitions (name -> TaskDefinition)"
    )
    
    # Advanced settings
    max_concurrent_tasks: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Max concurrent task executions"
    )
    
    task_log_retention_days: int = Field(
        default=30,
        ge=7,
        le=365,
        description="Keep task logs for N days"
    )
    
    model_config = SettingsConfigDict(
        env_prefix="TASK_",
        extra="ignore",
        case_sensitive=False,
        json_file=".olav/config/tasks.json",  # Load from JSON file if present
    )
    
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        return (
            init_settings,
            env_settings,
            JsonConfigSettingsSource(settings_cls),
        )

    def get_enabled_tasks(self) -> dict[str, TaskDefinition]:
        """Get all enabled tasks"""
        if not self.enabled:
            return {}
        return {
            name: task
            for name, task in self.tasks.items()
            if task.enabled
        }
    
    def get_task(self, name: str) -> TaskDefinition | None:
        """Get task by name"""
        return self.tasks.get(name)


# Global instance (lazy loaded)
_scheduler_settings: TaskSchedulerSettings | None = None


def get_scheduler_settings() -> TaskSchedulerSettings:
    """Get task scheduler settings (cached)"""
    global _scheduler_settings
    if _scheduler_settings is None:
        _scheduler_settings = TaskSchedulerSettings()
    return _scheduler_settings
