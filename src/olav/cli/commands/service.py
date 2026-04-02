#!/usr/bin/env python3
"""
OLAV Service Management Command - Manage background services.

Provides CLI interface to service lifecycle (start/stop/restart/status/config/logs).

Services
--------
  logs    – Syslog UDP receiver (RFC 3164/5424 → Parquet)
  web     – FastAPI/uvicorn REST + SSE API server
  daemon  – Agent Unix-socket daemon (pre-warmed LLM, fast queries)

Quick start (all services):
  olav service start --all
  olav service stop  --all
  olav service status
"""

import asyncio
import logging
import shlex
from typing import Any

from rich.console import Console
from rich.table import Table

from olav.cli.commands.base import BaseCommand
from olav.cli.commands.services.daemon_svc import DaemonService
from olav.cli.commands.services.logs import LogsService
from olav.cli.commands.services.web import WebService

logger = logging.getLogger(__name__)

# Services launched / stopped when --all is specified (ordered)
_ALL_SERVICES_ORDER = ["logs", "web", "daemon"]


class ServiceCommand(BaseCommand):
    """Manage OLAV background services."""

    def __init__(self) -> None:
        super().__init__(
            name="service",
            description="Manage background services (logs, web, daemon)",
        )
        self.console = Console()
        self.services: dict[str, Any] = {
            "logs": LogsService(),
            "web": WebService(),
            "daemon": DaemonService(),
        }

    async def execute(self, args: str = "") -> str:
        """Execute service subcommand.

        Usage:
            # Individual service
            olav service logs   start  [--port 5514] [--flush-interval 60]
            olav service web    start  [--port 2280] [--host 0.0.0.0]
            olav service daemon start

            olav service <svc>  stop
            olav service <svc>  restart
            olav service <svc>  status
            olav service <svc>  logs   [--tail 50]

            # All services at once
            olav service start  --all
            olav service stop   --all
            olav service status          # shows all when no svc given
        """
        if not args or not args.strip():
            # Bare "olav service" → show status of all services
            return await self._status_all()

        parts = shlex.split(args.strip())
        first = parts[0]

        # ── "olav service register <name> [--force]" ─────────────────────
        if first == "register":
            service_name = parts[1] if len(parts) > 1 else ""
            if not service_name:
                return "[red]Usage: olav service register <service_name> [--force][/red]"
            kwargs = self._parse_kwargs(parts[2:])
            return await self._register_service(service_name, force=bool(kwargs.get("force")))

        # ── "olav service status" (no service name) ──────────────────────
        if first == "status" and len(parts) == 1:
            return await self._status_all()

        # ── "olav service start --all" / "olav service stop --all" ───────
        kwargs_all = self._parse_kwargs(parts[1:])
        if first in ("start", "stop", "restart") and kwargs_all.get("all"):
            return await self._exec_all(first)

        # ── "olav service <svc> <action> [opts]" ─────────────────────────
        service_name = first
        action = parts[1] if len(parts) > 1 else "status"
        kwargs = self._parse_kwargs(parts[2:])

        svc = self.services.get(service_name)
        if not svc:
            available = ", ".join(self.services.keys())
            return (
                f"[red]Unknown service '{service_name}'.[/red] "
                f"Available: {available}  |  use '--all' for all services"
            )

        try:
            result = await svc.execute(action, **kwargs)
            if result:
                self.console.print(result)
            return "success" if not result or "[red]" not in result else "error"
        except Exception as e:
            logger.exception(f"Service error: {e}")
            return f"[red]Error: {e}[/red]"

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    async def _exec_all(self, action: str) -> str:
        """Run start/stop/restart across all services in defined order."""
        order = _ALL_SERVICES_ORDER
        if action == "stop":
            order = list(reversed(order))  # stop in reverse order

        self.console.print(f"\n[bold cyan]olav service {action} --all[/bold cyan]\n")
        lines = []
        for name in order:
            svc = self.services[name]
            try:
                msg = await svc.execute(action)
                label = f"[bold]{name}[/bold]"
                self.console.print(f"  {label:30s} {msg or '[dim]ok[/dim]'}")
                lines.append(msg or "ok")
            except Exception as e:
                self.console.print(f"  [red]{name}[/red] → Error: {e}")
                lines.append(f"error: {e}")
        return "success"

    async def _status_all(self) -> str:
        """Print a combined status table for all services."""
        from olav.cli.daemon import get_daemon_status

        table = Table(title="OLAV Service Status", show_header=True, header_style="bold cyan")
        table.add_column("Service", style="bold")
        table.add_column("Status")
        table.add_column("PID")
        table.add_column("Endpoint / Info")

        for name in _ALL_SERVICES_ORDER:
            svc = self.services[name]
            if name == "logs":
                running = svc._is_running()
                pid = svc._get_pid() or "-"
                port = svc._cfg.get("port", 5514)
                info = f"UDP :{port}"
            elif name == "web":
                running = svc._is_running()
                pid = svc._get_pid() or "-"
                info = f"http://{svc._host}:{svc._port}"
            elif name == "daemon":
                d = get_daemon_status()
                running = bool(d.get("running"))
                pid = d.get("pid", "-")
                q = d.get("query_count", 0)
                uptime = int(d.get("uptime_seconds", 0))
                info = f"queries={q}, uptime={uptime}s" if running else "Unix socket"
            else:
                running = False
                pid = "-"
                info = ""

            status_cell = "[green]● Running[/green]" if running else "[red]○ Stopped[/red]"
            table.add_row(name, status_cell, str(pid), info)

        self.console.print()
        self.console.print(table)
        self.console.print(
            "\n[dim]Start all: [bold]olav service start --all[/bold]  |  "
            "Stop all: [bold]olav service stop --all[/bold][/dim]\n"
        )
        return ""

    async def _register_service(self, service_name: str, force: bool = False) -> str:
        """Pull OpenAPI schema and generate tools for a registered service."""
        from olav.platform.services.tool_generator import register_service

        self.console.print(
            f"\n[bold cyan]Registering service:[/bold cyan] {service_name}"
            + (" [dim](force)[/dim]" if force else "")
        )
        result = register_service(service_name, force=force, max_retries=3, retry_delay=5.0)

        if result.get("status") == "error":
            self.console.print(f"[red]Error:[/red] {result['error']}")
            return f"error: {result['error']}"

        ops = result.get("ops_loaded", 0)
        files = result.get("files_written", [])
        self.console.print(f"  [green]✓[/green] Loaded [bold]{ops}[/bold] API operations")
        for f in files:
            self.console.print(f"  [green]✓[/green] Generated: [dim]{f}[/dim]")
        if not files:
            self.console.print("  [yellow]⚠[/yellow] No tool files generated (check tag config)")
        self.console.print()
        return f"registered {service_name}: {ops} ops, {len(files)} tool files"

    def _show_help(self) -> str:
        """Show help for service command."""
        help_text = """
[bold cyan]OLAV Service Management[/bold cyan]

[bold]Usage:[/bold]
  olav service <service> <action> [options]
  olav service start  --all          Start all services
  olav service stop   --all          Stop  all services
  olav service status                Show all service statuses

[bold]Services:[/bold]
  logs    – Syslog UDP receiver (RFC 3164/5424 → Parquet)
  web     – FastAPI REST + SSE API server  (default port 2280)
  daemon  – Agent daemon via Unix socket   (fast pre-warmed LLM)

[bold]Actions:[/bold]
  start   – Start the service
  stop    – Stop the service
  restart – Restart the service
  status  – Show service status
  logs    – View recent log output

[bold]Options per service:[/bold]
  logs:   --port 5514 --flush-interval 120
  web:    --port 2280 --host 0.0.0.0
  daemon: (no options)

[bold]Examples:[/bold]
  olav service start --all
  olav service logs start --port 5514
  olav service web  start --port 8080
  olav service daemon status
  olav service web  logs --tail 100
"""
        self.console.print(help_text)
        return ""

    @staticmethod
    def _parse_kwargs(args: list[str]) -> dict[str, Any]:
        """Parse keyword arguments from CLI args.

        Examples:
            ["--port", "5514"] → {"port": 5514}
            ["--flush-interval", "60"] → {"flush_interval": 60}
            ["show"] → {"subcommand": "show"}
            ["set", "nested.key", "value"] → {"subcommand": "set", "key": "nested.key", "value": "value"}
        """
        kwargs = {}
        i = 0
        subcommand = None
        positional_args = []

        while i < len(args):
            arg = args[i]

            if arg.startswith("--"):
                key = arg[2:].replace("-", "_")
                if i + 1 < len(args) and not args[i + 1].startswith("--"):
                    value = args[i + 1]
                    # Type conversion
                    if value.isdigit():
                        kwargs[key] = int(value)
                    elif value.lower() in ("true", "false"):
                        kwargs[key] = value.lower() == "true"
                    else:
                        kwargs[key] = value
                    i += 2
                else:
                    kwargs[key] = True
                    i += 1
            else:
                # Collect all positional arguments
                positional_args.append(arg)
                i += 1

        # Process positional arguments
        if positional_args:
            subcommand = positional_args[0]
            if subcommand == "set" and len(positional_args) >= 3:
                # For "config set key value" pattern
                kwargs["key"] = positional_args[1]
                kwargs["value"] = positional_args[2]
            elif len(positional_args) > 1:
                # For other patterns with multiple positional args
                # Treat remaining args as key-value pairs
                for i in range(1, len(positional_args), 2):
                    if i + 1 < len(positional_args):
                        key = positional_args[i]
                        value = positional_args[i + 1]
                        # Type conversion
                        if value.isdigit():
                            kwargs[key] = int(value)
                        elif value.lower() in ("true", "false"):
                            kwargs[key] = value.lower() == "true"
                        else:
                            kwargs[key] = value

            kwargs["subcommand"] = subcommand

        return kwargs
