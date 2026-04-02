#!/usr/bin/env python3
"""
Cron 调度工具 - 管理定时任务和执行计划（基于系统 crontab）

本工具使用 python-crontab 库管理系统 crontab（非 Python schedule 库）：
- 创建/更新/删除定时任务
- 立即执行任务（同步）
- 查看任务状态和执行日志
- 管理日志和报告

所有者: olav-config

使用示例:
    # 创建每天 2:00 的快照任务
    manage_cron(action="schedule", schedule="0 2 * * *", workflow="daily-snapshot")
    
    # 立即执行任务
    manage_cron(action="run", workflow="daily-snapshot")
    
    # 查看日志
    manage_cron(action="logs", workflow="daily-snapshot")
    
    # 删除任务
    manage_cron(action="unschedule", workflow="daily-snapshot")
"""

import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from crontab import CronTab
from langchain_core.tools import tool
from pydantic import BaseModel, Field

# ============================================================================
# Configuration
# ============================================================================

def _find_project_root():
    """Find project root by locating .olav directory"""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / ".olav").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
OLAV_DIR = PROJECT_ROOT / ".olav"
LOGS_DIR = OLAV_DIR / "logs"
WORKFLOWS_DIR = OLAV_DIR / "workflows"
# FIXED: Changed from "exports/reports/snapshots" to "exports/agent_outputs"
# Snapshots subdirectory was redundant and unused (no snapshot versioning needed)
REPORTS_DIR = PROJECT_ROOT / "exports" / "agent_outputs"

# Ensure directories exist
LOGS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================================
# Pydantic Models
# ============================================================================

class InspectionScheduleInput(BaseModel):
    """Input for scheduling inspection"""
    action: Literal["schedule", "unschedule", "list", "run", "status", "logs"]
    workflow: str = Field(
        default="daily-inspection",
        description="Workflow name / label (used in cron comment and log filename)"
    )
    schedule: str | None = Field(
        default=None,
        description="Cron schedule expression (e.g., '0 6 * * *')"
    )
    enabled: bool = Field(
        default=True,
        description="Enable or disable the schedule"
    )
    days: int = Field(
        default=7,
        description="Number of days for log/status queries"
    )
    devices: str | None = Field(
        default=None,
        description="Comma-separated device names to inspect (default: all devices)"
    )
    groups: str | None = Field(
        default=None,
        description="Comma-separated Nornir group names (e.g. core,access)"
    )
    output_dir: str | None = Field(
        default=None,
        description="Directory to write reports (default: agent_outputs)"
    )


class InspectionOutput(BaseModel):
    """Output for inspection operations"""
    status: str = Field(..., description="success | failed")
    action: str = Field(..., description="Action performed")
    message: str | None = Field(None, description="Human-readable message")
    data: dict | list | None = Field(None, description="Additional data")
    error: str | None = Field(None, description="Error message if failed")


# ============================================================================
# Helper Functions
# ============================================================================

def _get_crontab() -> CronTab:
    """Get current user's crontab"""
    return CronTab(user=True)


def _get_inspection_command(workflow: str, devices: str | None = None, output_dir: Path | None = None) -> str:
    """Get the shell command to run snapshot via take_snapshot tool.

    Args:
        workflow:   Workflow label (used only in cron comment).
        devices:    Optional comma-separated device names.
        output_dir: Unused (take_snapshot writes to its own location).
    """
    venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
    config_tools = OLAV_DIR / "workspace" / "config" / "sync" / "tools"

    dev_arg = repr(devices.split(",")) if devices else "None"
    # Python -c snippet: add tools dir to path, call take_snapshot @tool
    py_snippet = (
        f"import sys; sys.path.insert(0, r'{config_tools}'); "
        f"from take_snapshot import take_snapshot; import json; "
        f"r = take_snapshot.invoke({{'devices': {dev_arg}}}); "
        f"print(json.dumps(r, default=str))"
    )
    parts = [
        f"cd {PROJECT_ROOT}",
        f"&& {venv_python} -c '{py_snippet}'",
        f">> {LOGS_DIR}/cron_{workflow}.log 2>&1",
    ]
    return " ".join(parts)


def _find_inspection_job(cron: CronTab, workflow: str) -> Any | None:
    """Find inspection cron job by workflow name"""
    comment = f"OLAV-{workflow}"
    for job in cron:
        if job.comment == comment:
            return job
    return None


def _get_log_file(workflow: str, date: datetime | None = None) -> Path:
    """Get log file path for workflow"""
    if date is None:
        date = datetime.now()
    return LOGS_DIR / f"{workflow}_{date.strftime('%Y%m%d')}.log"


def _get_report_file(date: datetime | None = None) -> Path:
    """Get report file path"""
    if date is None:
        date = datetime.now()
    return REPORTS_DIR / f"{date.strftime('%Y%m%d')}.md"


# ============================================================================
# Action Handlers
# ============================================================================

def handle_schedule(workflow: str, schedule: str, enabled: bool,
                    devices: str | None = None, groups: str | None = None,
                    output_dir: str | None = None) -> InspectionOutput:
    """Schedule or update inspection workflow"""
    try:
        cron = _get_crontab()
        report_dir = Path(output_dir) if output_dir else None

        # Find or create job
        job = _find_inspection_job(cron, workflow)

        if job:
            # Update existing job
            job.setall(schedule)
            job.enable(enabled)
            # Rebuild command with latest args
            job.command = _get_inspection_command(
                workflow, devices=devices, groups=groups, output_dir=report_dir
            )
            message = f"Updated schedule for {workflow}: {schedule} (enabled={enabled})"
        else:
            # Create new job
            command = _get_inspection_command(
                workflow, devices=devices, groups=groups, output_dir=report_dir
            )
            job = cron.new(command=command, comment=f"OLAV-{workflow}")
            job.setall(schedule)
            job.enable(enabled)
            message = f"Created schedule for {workflow}: {schedule}"

        # Save crontab
        cron.write()

        return InspectionOutput(
            status="success",
            action="schedule",
            message=message,
            data={
                "workflow": workflow,
                "schedule": schedule,
                "enabled": enabled,
                "next_run": str(job.schedule(date_from=datetime.now()).get_next())
            }
        )

    except Exception as e:
        return InspectionOutput(
            status="failed",
            action="schedule",
            error=str(e)
        )


def handle_unschedule(workflow: str) -> InspectionOutput:
    """Remove inspection schedule"""
    try:
        cron = _get_crontab()
        job = _find_inspection_job(cron, workflow)

        if job:
            cron.remove(job)
            cron.write()
            return InspectionOutput(
                status="success",
                action="unschedule",
                message=f"Removed schedule for {workflow}"
            )
        else:
            return InspectionOutput(
                status="failed",
                action="unschedule",
                error=f"No schedule found for {workflow}"
            )

    except Exception as e:
        return InspectionOutput(
            status="failed",
            action="unschedule",
            error=str(e)
        )


def handle_list() -> InspectionOutput:
    """List all inspection schedules"""
    try:
        cron = _get_crontab()
        schedules = []

        for job in cron:
            if job.comment and job.comment.startswith("OLAV-"):
                workflow = job.comment.replace("OLAV-", "")
                schedules.append({
                    "workflow": workflow,
                    "schedule": str(job.slices),
                    "enabled": job.is_enabled(),
                    "command": job.command,
                    "next_run": str(job.schedule(date_from=datetime.now()).get_next()) if job.is_enabled() else None
                })

        return InspectionOutput(
            status="success",
            action="list",
            message=f"Found {len(schedules)} scheduled inspections",
            data=schedules
        )

    except Exception as e:
        return InspectionOutput(
            status="failed",
            action="list",
            error=str(e)
        )


def handle_run(workflow: str) -> InspectionOutput:
    """Execute inspection immediately"""
    try:
        # Check if workflow exists
        workflow_file = WORKFLOWS_DIR / f"{workflow}.md"
        if not workflow_file.exists():
            return InspectionOutput(
                status="failed",
                action="run",
                error=f"Workflow not found: {workflow_file}"
            )

        # Execute inspection
        log_file = _get_log_file(workflow)

        result = subprocess.run(
            [sys.executable, "-m", "uv", "run", "olav", "inspect", workflow],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=1800  # 30 minutes
        )

        # Write log
        with open(log_file, "a") as f:
            f.write(f"\n{'='*80}\n")
            f.write(f"[{datetime.now().isoformat()}] Manual execution\n")
            f.write(f"{'='*80}\n")
            f.write(result.stdout)
            if result.stderr:
                f.write(f"\nSTDERR:\n{result.stderr}")

        if result.returncode == 0:
            # Check if report was generated
            report_file = _get_report_file()
            report_exists = report_file.exists()

            return InspectionOutput(
                status="success",
                action="run",
                message="Inspection completed successfully",
                data={
                    "workflow": workflow,
                    "log_file": str(log_file),
                    "report_file": str(report_file) if report_exists else None,
                    "duration": None  # Could parse from output
                }
            )
        else:
            return InspectionOutput(
                status="failed",
                action="run",
                error=f"Inspection failed with exit code {result.returncode}",
                data={
                    "stdout": result.stdout[-500:] if result.stdout else None,
                    "stderr": result.stderr[-500:] if result.stderr else None
                }
            )

    except subprocess.TimeoutExpired:
        return InspectionOutput(
            status="failed",
            action="run",
            error="Inspection timeout (30 minutes)"
        )
    except Exception as e:
        return InspectionOutput(
            status="failed",
            action="run",
            error=str(e)
        )


def handle_status(workflow: str, days: int = 7) -> InspectionOutput:
    """Get inspection status and history"""
    try:
        # Get schedule info
        cron = _get_crontab()
        job = _find_inspection_job(cron, workflow)

        schedule_info = None
        if job:
            schedule_info = {
                "schedule": str(job.slices),
                "enabled": job.is_enabled(),
                "next_run": str(job.schedule(date_from=datetime.now()).get_next()) if job.is_enabled() else None
            }

        # Get recent logs
        recent_logs = []
        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            log_file = _get_log_file(workflow, date)
            report_file = _get_report_file(date)

            if log_file.exists():
                recent_logs.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "log_file": str(log_file),
                    "log_size": log_file.stat().st_size,
                    "report_exists": report_file.exists(),
                    "report_file": str(report_file) if report_file.exists() else None
                })

        return InspectionOutput(
            status="success",
            action="status",
            message=f"Status for {workflow} (last {days} days)",
            data={
                "workflow": workflow,
                "schedule": schedule_info,
                "recent_executions": recent_logs,
                "total_executions": len(recent_logs)
            }
        )

    except Exception as e:
        return InspectionOutput(
            status="failed",
            action="status",
            error=str(e)
        )


def handle_logs(workflow: str, days: int = 7) -> InspectionOutput:
    """Get recent log content"""
    try:
        logs = []

        for i in range(days):
            date = datetime.now() - timedelta(days=i)
            log_file = _get_log_file(workflow, date)

            if log_file.exists():
                with open(log_file) as f:
                    content = f.read()

                # Extract summary (last 50 lines)
                lines = content.split('\n')
                summary = '\n'.join(lines[-50:]) if len(lines) > 50 else content

                logs.append({
                    "date": date.strftime("%Y-%m-%d"),
                    "file": str(log_file),
                    "size": len(content),
                    "summary": summary
                })

        return InspectionOutput(
            status="success",
            action="logs",
            message=f"Logs for {workflow} (last {days} days)",
            data=logs
        )

    except Exception as e:
        return InspectionOutput(
            status="failed",
            action="logs",
            error=str(e)
        )


# ============================================================================
# Main Tool
# ============================================================================

@tool
def manage_cron(
    action: Literal["schedule", "unschedule", "list", "run", "status", "logs"],
    workflow: str = "daily-inspection",
    schedule: str | None = None,
    enabled: bool = True,
    days: int = 7,
    devices: str | None = None,
    groups: str | None = None,
    output_dir: str | None = None,
) -> dict:
    """Manage cron schedules and on-demand execution for network data collection.
    
    Uses system crontab (via python-crontab), not Python's schedule library.
    
    Actions:
        - schedule: Create/update cron schedule
        - unschedule: Remove cron schedule
        - list: List all scheduled jobs
        - run: Execute job immediately (synchronous)
        - status: Get job status and history
        - logs: View recent job logs

    Cron Format (schedule parameter):
        "⁣分(0-59) 时(0-23) 日(1-31) 月(1-12) 周(0-7)"
        Examples:
          - "0 2 * * *"      → Every day at 2:00 AM
          - "0 6,18 * * *"   → Every day at 6 AM and 6 PM
          - "0 */4 * * *"    → Every 4 hours (0, 4, 8, 12, ...)
          - "0 0 * * 1"      → Every Monday at midnight
          - "0 0 1 * *"      → First day of every month at midnight
          - "*/15 * * * *"   → Every 15 minutes

    Args:
        action: Action to perform
        workflow: Workflow label/name (default: "daily-inspection")
        schedule: Cron schedule expression (required for "schedule" action)
        enabled: Enable/disable schedule (default: True)
        days: Number of days for history queries (default: 7)
        devices: Comma-separated device names (default: all devices)
        groups: Comma-separated Nornir group names (e.g. "core,access")
        output_dir: Directory to write reports (default: agent_outputs)

    Returns:
        {
            "status": "success | failed",
            "action": "action_name",
            "message": "Human-readable message",
            "data": {...},
            "error": "Error message if failed"
        }

    Logs:
        - All job output: ~/.olav/logs/cron_{workflow}.log
        - Execution logs: ~/.olav/logs/cron_{workflow}_YYYYMMDD.log

    Important Notes:
        ⚠️  修改任何 cron 任务前需要 HITL（Human-in-Loop）确认！
        ✅ 使用有意义的 workflow 名称如"daily-backup", "hourly-health-check"
        ✅ 先用 manage_cron("run") 测试，再用 manage_cron("schedule") 创建定时任务
        ✅ 用 manage_cron("logs") 定期检查任务执行状态和错误日志
        ❌ 不要创建两个相同 schedule 的任务（会互相覆盖）
        ❌ 在网络高峰期不要调度 SSH 采集任务（避免拥塞）

    Examples:
        # 创建每天凌晨 2:00 的快照任务
        manage_cron(action="schedule", workflow="daily-snapshot", schedule="0 2 * * *")

        # 立即运行一次（测试）
        manage_cron(action="run", workflow="daily-snapshot")

        # 查看最近 7 天的执行状态
        manage_cron(action="status", workflow="daily-snapshot", days=7)

        # 查看任务日志
        manage_cron(action="logs", workflow="daily-snapshot")

        # 列出所有定时任务
        manage_cron(action="list")

        # 删除任务
        manage_cron(action="unschedule", workflow="daily-snapshot")
    """
    try:
        # Validate input
        input_data = InspectionScheduleInput(
            action=action,
            workflow=workflow,
            schedule=schedule,
            enabled=enabled,
            days=days,
            devices=devices,
            groups=groups,
            output_dir=output_dir,
        )

        # Route to handler
        if action == "schedule":
            if not schedule:
                return InspectionOutput(
                    status="failed",
                    action="schedule",
                    error="schedule parameter is required for schedule action"
                ).dict()
            result = handle_schedule(workflow, schedule, enabled,
                                     devices=devices, groups=groups,
                                     output_dir=output_dir)

        elif action == "unschedule":
            result = handle_unschedule(workflow)

        elif action == "list":
            result = handle_list()

        elif action == "run":
            result = handle_run(workflow)

        elif action == "status":
            result = handle_status(workflow, days)

        elif action == "logs":
            result = handle_logs(workflow, days)

        else:
            result = InspectionOutput(
                status="failed",
                action=action,
                error=f"Unknown action: {action}"
            )

        return result.dict()

    except Exception as e:
        return InspectionOutput(
            status="failed",
            action=action,
            error=f"Tool execution failed: {str(e)}"
        ).dict()


# ============================================================================
# CLI Entry Point
# ============================================================================

if __name__ == "__main__":
    # Read JSON input from stdin
    try:
        input_json = sys.stdin.read()
        input_data = json.loads(input_json)

        result = manage_cron(**input_data)

        print(json.dumps(result, indent=2))

        sys.exit(0 if result["status"] == "success" else 1)

    except Exception as e:
        error_result = {
            "status": "failed",
            "action": "unknown",
            "error": str(e)
        }
        print(json.dumps(error_result, indent=2))
        sys.exit(1)
