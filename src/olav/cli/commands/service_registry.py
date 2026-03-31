"""
service_registry.py — CLI for external service registration

Subcommands:
  olav registry register <name>   — fetch spec, generate tools
  olav registry refresh <name>    — force re-fetch schema
  olav registry list              — list registered services
  olav registry status <name>     — check service reachability
"""

from __future__ import annotations

import logging
import shlex

from rich.console import Console
from rich.table import Table

from olav.cli.commands.base import BaseCommand

logger = logging.getLogger(__name__)


class ServiceRegistryCommand(BaseCommand):
    """Manage external service registrations (ContainerLab, NetBox, …)."""

    def __init__(self) -> None:
        super().__init__(
            name="registry",
            description="Register and manage external service integrations",
        )
        self.console = Console()

    async def execute(self, args: str = "") -> str:
        parts = shlex.split(args.strip()) if args.strip() else []
        if not parts:
            return await self._list()

        sub = parts[0]
        rest = parts[1:]

        if sub in ("list", "ls"):
            return await self._list()
        elif sub == "register":
            return await self._register(rest, force=False)
        elif sub == "refresh":
            return await self._register(rest, force=True)
        elif sub == "status":
            return await self._status(rest)
        else:
            self.console.print(
                "[yellow]Usage:[/yellow] olav registry [register|refresh|list|status] [name]"
            )
            return "error"

    async def _list(self) -> str:
        from olav.platform.services.registry import ServiceRegistry
        from olav.core.api_registry import is_loaded

        registry = ServiceRegistry.get_instance()
        services = registry.list()

        if not services:
            self.console.print("[yellow]No services configured in .olav/config/services.yaml[/yellow]")
            return ""

        table = Table(
            title="External Services",
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Name", style="bold")
        table.add_column("Display Name")
        table.add_column("Endpoint")
        table.add_column("Schema Loaded")
        table.add_column("Auth")

        for svc in services:
            loaded = is_loaded(svc.name)
            schema_cell = "[green]yes[/green]" if loaded else "[dim]no[/dim]"
            table.add_row(
                svc.name,
                svc.display_name,
                svc.endpoint or "[dim]none[/dim]",
                schema_cell,
                svc.auth.type,
            )

        self.console.print()
        self.console.print(table)
        self.console.print(
            "\n[dim]Register: [bold]olav registry register <name>[/bold][/dim]\n"
        )
        return ""

    async def _register(self, args: list[str], force: bool) -> str:
        if not args:
            self.console.print("[red]Usage: olav registry register <service_name>[/red]")
            return "error"

        name = args[0]
        action = "refresh" if force else "register"
        self.console.print(f"\n[bold cyan]olav registry {action} {name}[/bold cyan]")

        try:
            from olav.platform.services.tool_generator import register_service
            result = register_service(name, force=force)
        except KeyError as e:
            self.console.print(f"[red]Error:[/red] {e}")
            return "error"
        except Exception as e:
            logger.exception("Registration failed for '%s'", name)
            self.console.print(f"[red]Registration failed:[/red] {e}")
            return "error"

        self.console.print(
            f"  [green]✓[/green] Loaded [bold]{result['ops_loaded']}[/bold] operations"
        )
        for f in result["files_written"]:
            self.console.print(f"  [green]✓[/green] Generated [dim]{f}[/dim]")

        if not result["files_written"]:
            self.console.print("  [yellow]No tool files generated (check tag names in services.yaml)[/yellow]")

        return "success"

    async def _status(self, args: list[str]) -> str:
        if not args:
            self.console.print("[red]Usage: olav registry status <service_name>[/red]")
            return "error"

        name = args[0]
        try:
            from olav.platform.services.registry import ServiceRegistry
            registry = ServiceRegistry.get_instance()
            svc = registry.get(name)
        except KeyError as e:
            self.console.print(f"[red]Error:[/red] {e}")
            return "error"

        import httpx
        health_path = svc.lifecycle.health_check
        if not health_path:
            # Default: GET /
            health_path = "GET /"

        # Strip "GET " prefix if present
        parts = health_path.split(None, 1)
        method, path = (parts[0], parts[1]) if len(parts) == 2 else ("GET", parts[0])

        url = svc.endpoint.rstrip("/") + path
        self.console.print(f"\n[bold]Checking {name}[/bold] → {url}")
        try:
            with httpx.Client(timeout=svc.lifecycle.health_timeout) as client:
                resp = client.request(method, url)
            if resp.status_code < 400:
                self.console.print(f"  [green]● Reachable[/green] (HTTP {resp.status_code})")
                return "success"
            else:
                self.console.print(f"  [yellow]⚠ HTTP {resp.status_code}[/yellow]")
                return "degraded"
        except Exception as e:
            self.console.print(f"  [red]○ Unreachable:[/red] {e}")
            return "error"
