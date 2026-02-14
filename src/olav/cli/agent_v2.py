#!/usr/bin/env python3
"""
OLAV v2.0 Agent CLI - Unified agent entry point.

Usage:
    uv run olav                                   # Interactive mode (default)
    uv run olav -m "How many devices?"            # Single message mode
    uv run olav --msg "show version on R1"        # Single message mode
    uv run olav admin status                      # Admin command
    uv run olav devices                           # List devices
    uv run olav --help                            # Help
"""

import asyncio
import logging
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

app = typer.Typer(
    name="olav",
    help="OLAV v2.0 - Network Operations AI Assistant\n\n"
         "Run without arguments to enter interactive mode.\n"
         "Use -m/--msg to send a single message.",
    no_args_is_help=False,  # Bare `olav` enters interactive mode
    invoke_without_command=True,
)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from olav.agents.agent import create_olav_agent
from olav.cli.admin import admin_handler

# ============================================================================
# Helpers
# ============================================================================

def _check_llm_key():
    """Check if LLM API key is configured."""
    from config.settings import settings
    if not settings.llm_api_key:
        console.print(
            "[bold red]Error:[/] LLM_API_KEY environment variable not set",
            style="red"
        )
        console.print("\nTo set up LLM API access:")
        console.print("  1. Add to .env file:")
        console.print("     LLM_API_KEY='your-api-key'")
        console.print("     LLM_PROVIDER='openai'")
        console.print("     LLM_MODEL_NAME='gpt-4'")
        raise typer.Exit(1)


async def _stream_response(agent, query: str, thread_id: str | None = None):
    """Stream agent response with real-time display."""
    try:
        result = await agent.invoke(query, thread_id=thread_id)

        if result["status"] == "success":
            console.print(result["response"])
        else:
            console.print(Panel(
                result.get("message", result.get("error", "Unknown error")),
                title="[red]✗ Error[/red]",
                border_style="red"
            ))

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}", file=sys.stderr)
        raise


def _run_interactive():
    """Enter interactive conversation mode."""
    import uuid

    _check_llm_key()
    agent = create_olav_agent(enable_checkpointer=False)
    thread_id = str(uuid.uuid4())[:8]

    console.print(Panel(
        f"OLAV v2.0 - Interactive Mode\n\n"
        f"Thread: {thread_id}\n"
        f"Type 'exit' or 'quit' to exit.\n"
        f"Send any natural language query.",
        border_style="blue",
        title="[cyan]OLAV[/cyan]"
    ))

    while True:
        try:
            query = console.input("\n[bold cyan]You:[/bold cyan] ")

            if query.lower().strip() in ["exit", "quit", "bye", "/quit", "/exit"]:
                console.print("[cyan]Goodbye![/cyan]")
                break

            if not query.strip():
                continue

            asyncio.run(_stream_response(agent, query, thread_id))

        except (KeyboardInterrupt, EOFError):
            console.print("\n[cyan]Goodbye![/cyan]")
            break
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")


# ============================================================================
# Commands
# ============================================================================

@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    msg: str | None = typer.Option(None, "--msg", "-m", help="Send a single message (non-interactive)"),
    version: bool = typer.Option(False, "--version", "-V", help="Show version"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
):
    """OLAV v2.0 - Network Operations AI Assistant.

    Run without arguments to enter interactive mode.
    Use -m/--msg to send a single message.

    Examples:
        olav                              # Enter interactive mode
        olav -m "How many devices?"       # Single query
        olav --msg "List core routers"    # Single query
        olav admin status                 # Admin command
        olav devices                      # List devices
    """
    if version:
        console.print("OLAV v2.0.0 (2026-02-14)")
        raise typer.Exit()

    if verbose:
        logging.basicConfig(level=logging.DEBUG)

    # If a subcommand was invoked (admin, devices), let it handle
    if ctx.invoked_subcommand is not None:
        return

    # Single message mode: -m "query"
    if msg:
        _check_llm_key()
        agent = create_olav_agent(enable_checkpointer=False)
        asyncio.run(_stream_response(agent, msg))
        return

    # Default: interactive mode
    _run_interactive()


@app.command()
def admin(
    command: str = typer.Argument(..., help="Admin command (status, backup, restore, etc)"),
    args: str | None = typer.Argument(None, help="Command arguments"),
):
    """Execute admin commands (<100ms response time).

    Commands:
        status      - System status check
        backup      - Backup all databases
        restore     - Restore from backup
        db-info     - Database information
        skill-list  - List skills
        cron-list   - List cron tasks

    Examples:
        olav2 admin status
        olav2 admin backup
        olav2 admin restore /path/to/backup.tar.gz
    """
    full_cmd = f"/admin {command}"
    if args:
        full_cmd += f" {args}"

    result = asyncio.run(admin_handler(full_cmd))

    if result["status"] == "success":
        console.print(Panel(
            str(result.get("data", result)),
            title="[green]✓ Success[/green]",
            border_style="green"
        ))
    else:
        console.print(Panel(
            result.get("message", "Unknown error"),
            title="[red]✗ Error[/red]",
            border_style="red"
        ))


@app.command()
def devices(
    role: str | None = typer.Option(None, "--role", help="Filter by role (core, access, edge)"),
    site: str | None = typer.Option(None, "--site", help="Filter by site"),
):
    """List network devices with optional filtering.

    Examples:
        olav2 devices
        olav2 devices --role core
        olav2 devices --site prod
    """
    try:
        from pathlib import Path

        import duckdb

        # Connect to main database
        db_path = Path(".olav/databases/main.duckdb")
        if not db_path.exists():
            console.print("[red]Error:[/red] Database not found. Run 'admin status' to initialize.", style="red")
            raise typer.Exit(1)

        conn = duckdb.connect(str(db_path), read_only=True)

        # Build query
        query = "SELECT * FROM devices WHERE 1=1"
        params = []

        if role:
            query += " AND role = ?"
            params.append(role)

        if site:
            query += " AND site = ?"
            params.append(site)

        query += " ORDER BY name"

        # Execute query
        try:
            results = conn.execute(query, params).fetchall()
            columns = [desc[0] for desc in conn.description]

            if not results:
                console.print("[yellow]No devices found matching the criteria.[/yellow]")
                return

            # Display as table
            table = Table(title=" 🖥️  Network Devices")
            for col in columns:
                table.add_column(col, style="cyan")

            for row in results:
                table.add_row(*[str(v) for v in row])

            console.print(table)

        finally:
            conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}", style="red")


if __name__ == "__main__":
    app()
