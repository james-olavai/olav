"""Task Management CLI Commands - OLAV v2.0

Commands for managing periodic inspection tasks.

Usage:
    olav task schedule           # Schedule all enabled tasks
    olav task unschedule         # Remove all scheduled tasks
    olav task status             # Show task status and next runs
    olav task run daily-inspection  # Run task immediately
    olav task logs               # Show recent task logs
    olav task cleanup            # Clean up old task logs
"""

import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config.settings import settings
from src.olav.lib.cron_manager import TaskManager

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(help="Manage periodic inspection tasks")


@app.command(name="schedule")
def cmd_schedule_all():
    """Schedule all enabled tasks to crontab
    
    Reads task definitions from config/settings.py and creates/updates
    cron jobs for all enabled tasks.
    """
    console.print("[yellow]📅 Scheduling all tasks...[/yellow]")
    
    manager = TaskManager()
    result = manager.schedule_all()
    
    if result["status"] == "success":
        console.print(f"[green]✓ Scheduled {result['scheduled']} tasks[/green]")
        
        # Show scheduled tasks
        if result["tasks"]:
            table = Table(title="Scheduled Tasks", show_header=True)
            table.add_column("Task", style="cyan")
            table.add_column("Status", style="green")
            
            for task_name, status in result["tasks"].items():
                table.add_row(task_name, status)
            
            console.print(table)
    
    else:
        console.print(f"[red]✗ Scheduling failed: {result.get('message')}[/red]")
        for error in result.get("errors", []):
            console.print(f"  - {error}")
        raise typer.Exit(code=1)
    
    if result.get("errors"):
        console.print("[yellow]⚠️  Errors occurred:[/yellow]")
        for error in result["errors"]:
            console.print(f"  - {error}")


@app.command(name="unschedule")
def cmd_unschedule_all():
    """Remove all scheduled tasks from crontab
    
    Removes all OLAV task entries from the system crontab.
    This does NOT delete task definitions, only the schedules.
    """
    console.print("[yellow]❌ Removing all scheduled tasks...[/yellow]")
    
    manager = TaskManager()
    
    # Unschedule all tasks
    for task_name in settings.tasks.tasks.keys():
        task_def = settings.tasks.tasks[task_name]
        try:
            manager._unschedule_task(task_def)
            console.print(f"  [green]✓[/green] Removed: {task_name}")
        except Exception as e:
            console.print(f"  [red]✗[/red] Failed to remove {task_name}: {e}")
    
    # Save crontab
    try:
        manager.cron.write()
        console.print("[green]✓ Crontab updated[/green]")
    except Exception as e:
        console.print(f"[red]✗ Failed to save crontab: {e}[/red]")


@app.command(name="status")
def cmd_status():
    """Show status of all tasks
    
    Displays:
    - Which tasks are enabled/disabled
    - Cron schedule for each task
    - Last execution time (if available)
    - Next run time (if scheduled)
    """
    manager = TaskManager()
    status = manager.get_status()
    
    # Main status panel
    if status["crontab_available"]:
        cron_status = "[green]✓ Available[/green]"
    else:
        cron_status = "[red]✗ Not available[/red]"
    
    scheduler_status = "[green]enabled[/green]" if status["scheduler_enabled"] else "[yellow]disabled[/yellow]"
    
    info = f"""
    Scheduler: {scheduler_status}
    Crontab: {cron_status}
    Total Tasks: {status['total_tasks']}
    Enabled: {status['enabled_tasks']}
    """
    
    console.print(Panel(info.strip(), title="📊 Task Scheduler Status", border_style="blue"))
    
    # Tasks table
    if status["tasks"]:
        table = Table(title="Task Details", show_header=True, show_lines=True)
        table.add_column("Task Name", style="cyan", width=25)
        table.add_column("Enabled", style="green", width=10)
        table.add_column("Schedule", style="yellow", width=15)
        table.add_column("Last Run", style="blue", width=20)
        table.add_column("Next Run", style="magenta", width=20)
        
        for task_name, task_info in status["tasks"].items():
            enabled_str = "✓" if task_info["enabled"] else "✗"
            last_run = task_info["last_run"] or "Never"
            next_run = task_info["next_run"] or "N/A"
            
            # Format timestamps
            if last_run != "Never":
                last_run = last_run.split("T")[0]  # Date only
            if next_run != "N/A":
                next_run = next_run.split("T")[0]  # Date only
            
            table.add_row(
                task_name,
                enabled_str,
                task_info["schedule"],
                last_run,
                next_run
            )
        
        console.print(table)
    else:
        console.print("[yellow]⚠️  No tasks defined[/yellow]")


@app.command(name="run")
def cmd_run(
    task_name: Annotated[str, typer.Argument(..., help="Task name to run")] = None,
    force: Annotated[bool, typer.Option("--force", help="Run even if disabled")] = False,
):
    """Run a task immediately
    
    Executes the specified task without waiting for its schedule.
    
    Examples:
        olav task run daily-inspection
        olav task run weekly-audit --force
    """
    if not task_name:
        console.print("[red]Error: task_name required[/red]")
        console.print("Usage: olav task run <task_name>")
        raise typer.Exit(code=1)
    
    console.print(f"[yellow]▶️  Running task: {task_name}[/yellow]")
    
    manager = TaskManager()
    result = manager.run_task(task_name, force=force)
    
    if result["status"] == "success":
        duration = result.get("duration", 0)
        console.print(f"[green]✓ Task completed in {duration:.1f}s[/green]")
        
        # Show output
        if result.get("output"):
            console.print("\n[blue]Output:[/blue]")
            console.print(result["output"][:500])  # First 500 chars
    
    elif result["status"] == "timeout":
        console.print(f"[red]✗ Task timeout after {result.get('duration', 0):.1f}s[/red]")
    
    elif result["status"] == "skipped":
        console.print(f"[yellow]⚠️  {result.get('message')}[/yellow]")
    
    else:
        console.print(f"[red]✗ Task failed[/red]")
        if result.get("error"):
            console.print(f"  Error: {result['error']}")
        raise typer.Exit(code=1)


@app.command(name="logs")
def cmd_logs(
    task_name: Annotated[str | None, typer.Option("--task", help="Specific task (optional)")] = None,
    lines: Annotated[int, typer.Option("--lines", "-n", help="Number of lines to show")] = 50,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Follow log output (like tail -f)")] = False,
):
    """View task execution logs
    
    Shows recent task execution logs. Can filter by task or follow in real-time.
    
    Examples:
        olav task logs                           # Show all recent logs
        olav task logs --task daily-inspection   # Specific task only
        olav task logs --lines 100              # Last 100 lines
        olav task logs --task weekly-audit -f   # Follow in real-time
    """
    logs_dir = Path(settings.tasks.log_dir)
    
    if task_name:
        # Show specific task log
        log_file = logs_dir / f"{task_name}.log"
        if not log_file.exists():
            console.print(f"[yellow]⚠️  No logs found for: {task_name}[/yellow]")
            return
        
        console.print(f"[blue]📋 Logs for: {task_name}[/blue]\n")
        
        try:
            with open(log_file, "r") as f:
                all_lines = f.readlines()
                recent_lines = all_lines[-lines:] if len(all_lines) > lines else all_lines
                console.print("".join(recent_lines))
        except Exception as e:
            console.print(f"[red]✗ Error reading log: {e}[/red]")
    
    else:
        # Show all task logs (summary)
        log_files = sorted(logs_dir.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
        
        if not log_files:
            console.print("[yellow]⚠️  No task logs found[/yellow]")
            return
        
        console.print(f"[blue]📋 Recent task logs (top {lines} lines from each):[/blue]\n")
        
        for log_file in log_files[:5]:  # Show last 5 task logs
            console.print(f"[cyan]{log_file.name}[/cyan]")
            try:
                with open(log_file, "r") as f:
                    all_lines = f.readlines()
                    recent = all_lines[-5:] if len(all_lines) > 5 else all_lines
                    for line in recent:
                        console.print(f"  {line.rstrip()}")
            except Exception as e:
                console.print(f"  Error: {e}")
            console.print()


@app.command(name="cleanup")
def cmd_cleanup():
    """Clean up old task logs
    
    Removes task logs older than the retention period configured in
    config/settings.py (default: 30 days).
    """
    console.print("[yellow]🧹 Cleaning up old task logs...[/yellow]")
    
    manager = TaskManager()
    result = manager.cleanup_old_logs()
    
    freed_mb = result["freed_bytes"] / (1024 * 1024)
    console.print(f"[green]✓ Deleted {result['deleted']} old logs[/green]")
    console.print(f"  Freed: {freed_mb:.1f} MB")
    console.print(f"  Retention: {result['retention_days']} days")


def get_task_app() -> typer.Typer:
    """Get the task management app"""
    return app
