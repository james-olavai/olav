#!/usr/bin/env python3
"""
OLAV Logs Service — Syslog UDP receiver lifecycle management.

Provides start/stop/status/restart/config/logs operations for the syslog receiver.
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from olav.core.defaults import DEFAULT_LOG_PORT

logger = logging.getLogger(__name__)


from olav.cli.commands.services._paths import find_workspace_root


def _project_root() -> Path:
    """Workspace root for syslog runtime files.  See gitea #12."""
    return find_workspace_root()


def _pid_file() -> Path:
    return _project_root() / ".olav" / "run" / "syslog_receiver.pid"


def _log_file() -> Path:
    return _project_root() / ".olav" / "logs" / "syslog_receiver.log"


def _config_file() -> Path:
    return _project_root() / ".olav" / "config" / "api.json"


def _runtime_file() -> Path:
    return _project_root() / ".olav" / "config" / "runtime.json"


class LogsService:
    """Manage syslog UDP receiver lifecycle."""

    def __init__(self):
        self.console = Console()
        self._cfg = self._load_config()

    def _load_config(self) -> dict[str, Any]:
        """Load logs service configuration from settings.json."""
        default_logs = {
            "enabled": True,
            "port": DEFAULT_LOG_PORT,
            "host": "0.0.0.0",
            "batch_size": 75,
            "flush_interval": 120,
            "parquet_compression": "snappy",
            "retention_days": 30,
            "auto_start": False,
        }

        if _config_file().exists():
            try:
                full_cfg = json.loads(_config_file().read_text())
                return full_cfg.get("syslog_receiver", default_logs)
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, using defaults")

        return default_logs

    def _save_config(self) -> None:
        """Save logs service configuration into settings.json."""
        _config_file().parent.mkdir(parents=True, exist_ok=True)

        full_cfg = {}
        if _config_file().exists():
            try:
                full_cfg = json.loads(_config_file().read_text())
            except Exception:
                pass
        elif _runtime_file().exists():
            try:
                full_cfg = json.loads(_runtime_file().read_text())
            except Exception:
                pass

        full_cfg["syslog_receiver"] = self._cfg
        _config_file().write_text(json.dumps(full_cfg, indent=2))
        logger.info(f"Config section updated in {_config_file()}")

    def _is_running(self) -> bool:
        """Check if receiver process is running."""
        if not _pid_file().exists():
            return False

        try:
            pid = int(_pid_file().read_text().strip())
            # Try to send signal 0 (check if process exists)
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, FileNotFoundError):
            return False

    def _get_pid(self) -> int | None:
        """Get receiver process PID."""
        if not _pid_file().exists():
            return None
        try:
            return int(_pid_file().read_text().strip())
        except ValueError:
            return None

    async def start(self, port: int | None = None, flush_interval: int | None = None) -> str:
        """Start syslog receiver process."""
        if self._is_running():
            pid = self._get_pid()
            return f"[yellow]Syslog receiver already running (PID: {pid}, port: {self._cfg['port']}).[/yellow]"

        # Update config if params provided
        if port is not None:
            self._cfg["port"] = port
        if flush_interval is not None:
            self._cfg["flush_interval"] = flush_interval

        self._save_config()

        port = self._cfg["port"]
        flush_interval = self._cfg["flush_interval"]

        # Ensure directories exist
        _pid_file().parent.mkdir(parents=True, exist_ok=True)
        _log_file().parent.mkdir(parents=True, exist_ok=True)

        # Start receiver as a detached subprocess using the installed module
        log_fh = open(_log_file(), "a")  # noqa: SIM115
        try:
            _process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "olav.services.syslog_receiver",
                    "--port",
                    str(port),
                    "--flush-interval",
                    str(flush_interval),
                ],
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,  # detach cleanly
                cwd=str(_project_root()),
            )
        except Exception as e:
            log_fh.close()
            return f"[red]Error starting receiver: {e}[/red]"

        # Wait briefly for startup
        await asyncio.sleep(1)

        if self._is_running():
            pid = self._get_pid()
            return f"[green]✓[/green] Syslog receiver started (PID: {pid}, port: {port}, flush: {flush_interval}s)"
        else:
            # Read tail of log for error clue
            log_fh.close()
            tail = ""
            if _log_file().exists():
                lines = _log_file().read_text().split("\n")
                tail = "\n".join(lines[-6:]).strip()
            return f"[red]Failed to start:[/red]\n{tail}"

    async def stop(self) -> str:
        """Stop syslog receiver process."""
        if not self._is_running():
            return "[yellow]Syslog receiver is not running.[/yellow]"

        pid = self._get_pid()
        try:
            os.kill(pid, signal.SIGTERM)

            # Wait for graceful shutdown
            for _ in range(10):
                if not self._is_running():
                    if _pid_file().exists():
                        _pid_file().unlink()
                    return f"[green]✓[/green] Syslog receiver stopped (PID: {pid})"
                await asyncio.sleep(0.5)

            # Force kill if needed
            os.kill(pid, signal.SIGKILL)
            if _pid_file().exists():
                _pid_file().unlink()
            return f"[yellow]⚠ Force-killed syslog receiver (PID: {pid})[/yellow]"

        except ProcessLookupError:
            if _pid_file().exists():
                _pid_file().unlink()
            return f"[yellow]Process {pid} not found[/yellow]"
        except Exception as e:
            return f"[red]Error stopping receiver: {e}[/red]"

    async def restart(self) -> str:
        """Restart syslog receiver."""
        await self.stop()
        await asyncio.sleep(1)
        return await self.start()

    def status(self) -> str:
        """Show syslog receiver status."""
        is_running = self._is_running()
        pid = self._get_pid()
        port = self._cfg["port"]
        flush_interval = self._cfg["flush_interval"]

        # Status table
        table = Table(title="Syslog Receiver Status", show_header=False)
        table.add_column(style="cyan")
        table.add_column()

        status_text = "[green]Running[/green]" if is_running else "[red]Stopped[/red]"
        table.add_row("Status", status_text)

        if pid:
            table.add_row("PID", str(pid))

        table.add_row("Port", str(port))
        table.add_row("Flush Interval", f"{flush_interval}s")

        # Log storage info
        log_dir = _project_root() / ".olav" / "databases" / "syslogs"
        parquet_count = len(list(log_dir.glob("**/*.parquet"))) if log_dir.exists() else 0
        table.add_row("Parquet Files", str(parquet_count))
        table.add_row("Log Directory", str(log_dir))

        self.console.print(table)

        # Show last log lines if running
        if is_running and _log_file().exists():
            self.console.print("\n[bold]Recent Log Output:[/bold]")
            lines = _log_file().read_text().split("\n")[-5:]
            for line in lines:
                if line.strip():
                    self.console.print(f"  {line}")

        return ""

    async def config(self, subcommand: str = "show", **kwargs) -> str:
        """Manage configuration."""
        if subcommand == "show":
            self.console.print_json(data=self._cfg)
            return f"[dim]Config: {_config_file()}[/dim]"

        elif subcommand == "set":
            key = kwargs.get("key")
            value = kwargs.get("value")
            if not key or value is None:
                return "[red]Usage: service logs config set <key> <value>[/red]"

            # Navigate nested config
            parts = key.split(".")
            cfg = self._cfg
            for part in parts[:-1]:
                if part not in cfg:
                    cfg[part] = {}
                cfg = cfg[part]

            # Type conversion
            if value.lower() in ("true", "false"):
                cfg[parts[-1]] = value.lower() == "true"
            elif value.isdigit():
                cfg[parts[-1]] = int(value)
            else:
                cfg[parts[-1]] = value

            self._save_config()
            return f"[green]✓[/green] Set {key} = {cfg[parts[-1]]}"

        else:
            return f"[red]Unknown subcommand: {subcommand}[/red]"

    async def logs(self, tail: int = 50) -> str:
        """Show receiver logs."""
        if not _log_file().exists():
            return "[yellow]No log file yet. Start the receiver with 'olav service logs start'[/yellow]"

        lines = _log_file().read_text().split("\n")

        # Show last N lines
        display_lines = lines[-tail:] if len(lines) > tail else lines

        self.console.print(f"\n[bold]Last {len(display_lines)} log lines ({_log_file()}):[/bold]\n")
        for line in display_lines:
            if line.strip():
                self.console.print(line)

        return ""

    async def execute(self, action: str = "status", **kwargs) -> str:
        """Execute service action."""
        action = action.strip().lower()

        if action == "start":
            return await self.start(
                port=kwargs.get("port"), flush_interval=kwargs.get("flush_interval")
            )
        elif action == "stop":
            return await self.stop()
        elif action == "restart":
            return await self.restart()
        elif action == "status":
            self.status()
            return ""
        elif action == "config":
            subcommand = kwargs.pop("subcommand", "show")
            return await self.config(subcommand=subcommand, **kwargs)
        elif action == "logs":
            return await self.logs(tail=kwargs.get("tail", 50))
        else:
            return f"[red]Unknown action: {action}[/red]"
