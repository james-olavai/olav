#!/usr/bin/env python3
"""
OLAV Daemon Service — Agent Unix-socket daemon lifecycle management.

Wraps `olav.cli.daemon` (spawn_daemon / stop_daemon / get_daemon_status)
into the standard ServiceCommand interface so it can be managed alongside
the syslog receiver and web API with a single `olav service` command.
"""

import asyncio
import logging
from pathlib import Path

from rich.console import Console
from rich.table import Table

logger = logging.getLogger(__name__)


from olav.cli.commands.services._paths import find_workspace_root


def _log_file() -> Path:
    """Re-resolve daemon log path against current workspace.  See gitea #12."""
    return find_workspace_root() / ".olav" / "logs" / "daemon.log"


class DaemonService:
    """Manage OLAV Agent Daemon (Unix socket server) lifecycle.

    The daemon pre-warms OLAVAgent so each interactive query skips the
    3–5 s cold-start overhead.  CLI queries are forwarded via Unix socket.
    """

    def __init__(self) -> None:
        self.console = Console()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def start(self) -> str:
        """Spawn daemon in background if not already running."""
        from olav.cli.daemon import get_daemon_status, spawn_daemon

        status = get_daemon_status()
        if status.get("running"):
            pid = status.get("pid")
            return f"[yellow]Agent daemon already running (PID: {pid}).[/yellow]"

        pid = spawn_daemon()

        # Wait up to 8 s for the daemon to write its PID file (it pre-warms
        # the LLM agent which takes a few seconds on first run)
        for _ in range(16):
            await asyncio.sleep(0.5)
            s = get_daemon_status()
            if s.get("running"):
                return f"[green]✓[/green] Agent daemon started (PID: {s.get('pid')})"

        return (
            f"[yellow]⚠ Daemon process spawned (PID: {pid}) but not yet ready "
            f"— it may still be pre-warming the agent. Check with 'olav service daemon status'.[/yellow]"
        )

    async def stop(self) -> str:
        """Send SIGTERM to the daemon."""
        from olav.cli.daemon import get_daemon_status, stop_daemon

        if not get_daemon_status().get("running"):
            return "[yellow]Agent daemon is not running.[/yellow]"

        stopped = stop_daemon()
        if stopped:
            # Brief wait for clean shutdown
            await asyncio.sleep(1)
            return "[green]✓[/green] Agent daemon stopped."
        return "[red]Failed to stop agent daemon.[/red]"

    async def restart(self) -> str:
        stop_msg = await self.stop()
        await asyncio.sleep(1)
        start_msg = await self.start()
        return f"{stop_msg}\n{start_msg}"

    def status(self) -> str:
        """Print a Rich status table."""
        from olav.cli.daemon import _socket_path, get_daemon_status

        info = get_daemon_status()
        is_running = bool(info.get("running"))

        table = Table(title="Agent Daemon Status", show_header=False)
        table.add_column(style="cyan")
        table.add_column()

        table.add_row("Status", "[green]Running[/green]" if is_running else "[red]Stopped[/red]")
        if is_running:
            table.add_row("PID", str(info.get("pid", "?")))
            uptime = int(info.get("uptime_seconds") or 0)  # type: ignore[arg-type]
            h, m, s = uptime // 3600, (uptime % 3600) // 60, uptime % 60
            table.add_row("Uptime", f"{h:02d}:{m:02d}:{s:02d}")
            table.add_row("Queries Served", str(info.get("query_count", 0)))
        table.add_row("Socket", str(_socket_path()))

        self.console.print(table)
        return ""

    async def logs(self, tail: int = 50) -> str:
        """Show the last N lines of the daemon log (if redirected)."""
        if not _log_file().exists():
            return (
                "[yellow]No dedicated daemon log found. "
                "Daemon stdout/stderr go to the terminal that launched it.[/yellow]"
            )

        lines = _log_file().read_text().split("\n")
        display = lines[-tail:] if len(lines) > tail else lines
        self.console.print(f"\n[bold]Last {len(display)} log lines ({_log_file()}):[/bold]\n")
        for line in display:
            if line.strip():
                self.console.print(line)
        return ""

    # ------------------------------------------------------------------
    # Unified execute() dispatcher
    # ------------------------------------------------------------------

    async def execute(self, action: str = "status", **kwargs) -> str:
        action = action.strip().lower()
        if action == "start":
            return await self.start()
        elif action == "stop":
            return await self.stop()
        elif action == "restart":
            return await self.restart()
        elif action == "status":
            self.status()
            return ""
        elif action == "logs":
            return await self.logs(tail=int(kwargs.get("tail", 50)))  # type: ignore[arg-type]
        else:
            return f"[red]Unknown action '{action}'. Available: start, stop, restart, status, logs[/red]"
