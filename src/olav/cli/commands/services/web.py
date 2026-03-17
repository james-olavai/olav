#!/usr/bin/env python3
"""
OLAV Web Service — FastAPI / uvicorn lifecycle management.

Provides start/stop/status/restart/logs operations for the OLAV API server.
The server exposes LangGraph-compatible SSE streaming endpoints used by
deep-agents-ui and any external HTTP clients.
"""

import asyncio
import logging
import os
import signal
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from olav.core.defaults import DEFAULT_WEB_PORT

logger = logging.getLogger(__name__)


def _find_project_root() -> Path:
    """Find project root (pyproject.toml location)."""
    p = Path(__file__).resolve().parent
    while p != p.parent:
        if (p / "pyproject.toml").exists():
            return p
        p = p.parent
    return Path.cwd()


PROJECT_ROOT = _find_project_root()
PID_FILE = PROJECT_ROOT / ".olav" / "run" / "web.pid"
LOG_FILE = PROJECT_ROOT / ".olav" / "logs" / "web.log"

_DEFAULT_HOST = "0.0.0.0"
_DEFAULT_PORT = DEFAULT_WEB_PORT


class WebService:
    """Manage OLAV API Server (uvicorn + FastAPI) lifecycle."""

    def __init__(self) -> None:
        self.console = Console()
        self._host = _DEFAULT_HOST
        self._port = _DEFAULT_PORT

    # ------------------------------------------------------------------
    # Process helpers
    # ------------------------------------------------------------------

    def _is_running(self) -> bool:
        if not PID_FILE.exists():
            return False
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            return True
        except (ValueError, ProcessLookupError, FileNotFoundError, PermissionError):
            return False

    def _get_pid(self) -> int | None:
        if not PID_FILE.exists():
            return None
        try:
            return int(PID_FILE.read_text().strip())
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    async def start(
        self,
        host: str | None = None,
        port: int | None = None,
    ) -> str:
        """Start the FastAPI server as a background process."""
        if self._is_running():
            pid = self._get_pid()
            return f"[yellow]Web API already running (PID: {pid}, port: {self._port}).[/yellow]"

        if host:
            self._host = host
        if port:
            self._port = port

        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # P3: generate server token if auth.mode == 'server'
        _server_token_line = ""
        try:
            from olav.core.config import ConfigLoader
            if ConfigLoader().auth.mode == "server":
                from olav.core.auth.server_token import ServerTokenProvider
                srv_token = ServerTokenProvider.create_and_persist()
                _server_token_line = (
                    f"\n[bold yellow]  WebUI token URL:[/bold yellow] "
                    f"http://{self._host}:{self._port}/?token={srv_token}"
                )
        except Exception:
            pass

        log_fh = open(LOG_FILE, "a")  # noqa: SIM115 – subprocess needs a real fd
        try:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "olav.api.server:app",
                    "--host",
                    self._host,
                    "--port",
                    str(self._port),
                    "--log-level",
                    "info",
                ],
                stdout=log_fh,
                stderr=log_fh,
                start_new_session=True,  # detach cleanly; no event-loop transport GC
            )
        except Exception as e:
            log_fh.close()
            return f"[red]Failed to spawn uvicorn: {e}[/red]"

        # Write PID immediately (uvicorn doesn't write one itself)
        PID_FILE.write_text(str(process.pid))

        # Give it a moment to bind the port
        await asyncio.sleep(1.5)

        if self._is_running():
            return (
                f"[green]✓[/green] Web API started "
                f"(PID: {process.pid}, http://{self._host}:{self._port})"
                + _server_token_line
            )
        else:
            # Probably crashed – grab tail of log
            log_fh.close()
            tail = ""
            if LOG_FILE.exists():
                lines = LOG_FILE.read_text().split("\n")
                tail = "\n".join(lines[-6:]).strip()
            return f"[red]Web API failed to start.[/red]\n{tail}"

    async def stop(self) -> str:
        """Stop the API server gracefully (SIGTERM → SIGKILL)."""
        if not self._is_running():
            return "[yellow]Web API is not running.[/yellow]"

        pid = self._get_pid()
        if pid is None:
            return "[yellow]PID file missing — Web API may have stopped already.[/yellow]"
        try:
            os.kill(pid, signal.SIGTERM)
            for _ in range(10):
                if not self._is_running():
                    if PID_FILE.exists():
                        PID_FILE.unlink()
                    return f"[green]✓[/green] Web API stopped (PID: {pid})"
                await asyncio.sleep(0.5)

            os.kill(pid, signal.SIGKILL)
            if PID_FILE.exists():
                PID_FILE.unlink()
            return f"[yellow]⚠ Force-killed Web API (PID: {pid})[/yellow]"

        except ProcessLookupError:
            if PID_FILE.exists():
                PID_FILE.unlink()
            return f"[yellow]Process {pid} not found (already stopped?)[/yellow]"
        except Exception as e:
            return f"[red]Error stopping Web API: {e}[/red]"

    async def restart(self) -> str:
        stop_msg = await self.stop()
        await asyncio.sleep(1)
        start_msg = await self.start()
        return f"{stop_msg}\n{start_msg}"

    def status(self) -> str:
        """Print a Rich status table."""
        is_running = self._is_running()
        pid = self._get_pid()

        table = Table(title="Web API Status", show_header=False)
        table.add_column(style="cyan")
        table.add_column()

        table.add_row("Status", "[green]Running[/green]" if is_running else "[red]Stopped[/red]")
        if pid:
            table.add_row("PID", str(pid))
        table.add_row("Endpoint", f"http://{self._host}:{self._port}")
        table.add_row("Health", f"http://{self._host}:{self._port}/health")
        table.add_row("Log", str(LOG_FILE))

        self.console.print(table)
        return ""

    async def logs(self, tail: int = 50) -> str:
        """Show the last N lines of the server log."""
        if not LOG_FILE.exists():
            return "[yellow]No log file yet. Start the API with 'olav service web start'[/yellow]"

        lines = LOG_FILE.read_text().split("\n")
        display = lines[-tail:] if len(lines) > tail else lines
        self.console.print(f"\n[bold]Last {len(display)} log lines ({LOG_FILE}):[/bold]\n")
        for line in display:
            if line.strip():
                self.console.print(line)
        return ""

    # ------------------------------------------------------------------
    # Unified execute() dispatcher (mirrors LogsService interface)
    # ------------------------------------------------------------------

    async def execute(self, action: str = "status", **kwargs) -> str:
        action = action.strip().lower()
        if action == "start":
            return await self.start(
                host=str(kwargs["host"]) if "host" in kwargs else None,  # type: ignore[arg-type]
                port=int(kwargs["port"]) if "port" in kwargs else None,  # type: ignore[arg-type]
            )
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
