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

from __future__ import annotations

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
    """Enter interactive conversation mode with prompt-toolkit (history, slash commands)."""
    import uuid

    from olav.cli.commands.builtin import execute_command, SLASH_COMMANDS
    from olav.cli.display import display_banner, load_banner_from_config
    from olav.cli.session import OlavPromptSession

    _check_llm_key()
    agent = create_olav_agent(enable_checkpointer=False)
    thread_id = str(uuid.uuid4())[:8]

    # Display banner from config (uses config/banners.py styles)
    banner_text = load_banner_from_config()
    if banner_text:
        display_banner(banner_text, console=console)

    console.print(Panel(
        f"OLAV v2.0 - Interactive Mode\n\n"
        f"Thread: {thread_id}\n"
        f"Type [bold]/help[/bold] for available commands.\n"
        f"Use [bold]↑↓[/bold] arrow keys to navigate history.\n"
        f"Type [bold]/quit[/bold] or [bold]exit[/bold] to exit.",
        border_style="blue",
        title="[cyan]OLAV[/cyan]"
    ))

    # Initialize prompt-toolkit session (FileHistory + AutoSuggestFromHistory)
    session = OlavPromptSession(enable_completion=False, multiline=False)

    async def _interactive_loop():
        while True:
            try:
                # Use prompt-toolkit async prompt (supports arrow keys, history)
                query = await session.prompt_async("OLAV> ")
                query = query.strip()

                if not query:
                    continue

                # Exit commands
                if query.lower() in ("exit", "quit", "bye"):
                    console.print("[cyan]Goodbye![/cyan]")
                    break

                # Slash command routing
                if query.startswith("/"):
                    try:
                        result = await execute_command(query, agent=None)
                        if result:
                            console.print(result)
                    except EOFError:
                        # /quit or /exit raises EOFError
                        console.print("[cyan]Goodbye![/cyan]")
                        break
                    except Exception as e:
                        console.print(f"[red]Error:[/red] {e}")
                    continue

                # Normal query → agent
                await _stream_response(agent, query, thread_id)

            except (KeyboardInterrupt, EOFError):
                console.print("\n[cyan]Goodbye![/cyan]")
                break
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

    asyncio.run(_interactive_loop())


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
    command: str = typer.Argument(..., help="Natural language task or legacy command"),
    args: str | None = typer.Argument(None, help="Command arguments"),
):
    """Execute Admin Agent task (AI-powered, natural language).

    🎯 Use this for AI-powered tasks that require planning and execution.
    💡 For simple operations, use direct commands instead (see below).

    AI-Powered Examples:
        olav admin "fix bug in network-query skill"
        olav admin "create a new monitoring skill"
        olav admin "analyze database performance"
        olav admin "cleanup old exports"

    Legacy commands (still supported, but direct commands are preferred):
        olav ls "*.py"                # instead of: olav admin list "*.py"
        olav search "pattern"         # instead of: olav admin search "pattern"
        olav backup                   # instead of: olav admin backup
        olav skills                   # instead of: olav admin skills
        olav db-status                # instead of: olav admin db-info
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


# ============================================================================
# Quick Commands (no 'admin' prefix) - v2.1 ⭐
# ============================================================================

@app.command()
def ls(
    pattern: str = typer.Argument("*", help="File pattern (e.g., '*.py', 'SKILL.md')"),
    directory: str = typer.Option(".", "--dir", "-d", help="Directory to search"),
):
    """List files matching pattern (replaces 'admin list').

    Examples:
        olav ls "*.py"
        olav ls ".olav/skills/*/SKILL.md"
        olav ls "*.md" --dir .olav/skills
    """
    import subprocess
    try:
        result = subprocess.run(
            ["find", directory, "-name", pattern, "-type", "f"],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0:
            files = result.stdout.strip().split('\n')
            files = [f for f in files if f]  # Remove empty strings
            
            if files:
                console.print(f"[cyan]Found {len(files)} files:[/cyan]")
                for f in files:
                    console.print(f"  {f}")
            else:
                console.print(f"[yellow]No files found matching '{pattern}'[/yellow]")
        else:
            console.print(f"[red]Error:[/red] {result.stderr}")
            
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Command timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def search(
    pattern: str = typer.Argument(..., help="Search pattern"),
    file_type: str = typer.Option("py", "--type", "-t", help="File type (py, md, all)"),
    directory: str = typer.Option(".", "--dir", "-d", help="Directory to search"),
):
    """Search for pattern in codebase (replaces 'admin search').

    Examples:
        olav search "execute_sql"
        olav search "execute_sql" --type py
        olav search "class Agent" --type py --dir src/
    """
    import subprocess
    
    # Build grep command
    cmd = ["grep", "-r", "-n", pattern, directory]
    
    if file_type != "all":
        cmd.append(f"--include=*.{file_type}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            lines = [l for l in lines if l]
            
            console.print(f"[cyan]Found {len(lines)} matches:[/cyan]")
            for line in lines[:50]:  # Limit to 50 results
                console.print(line)
            
            if len(lines) > 50:
                console.print(f"\n[yellow]... and {len(lines) - 50} more matches[/yellow]")
        else:
            console.print(f"[yellow]No matches found for '{pattern}'[/yellow]")
            
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Command timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def tree(
    directory: str = typer.Argument(".", help="Directory to show"),
    depth: int = typer.Option(3, "--depth", "-L", help="Max depth"),
):
    """Show directory tree (replaces 'admin tree').

    Examples:
        olav tree
        olav tree .olav/skills --depth 2
        olav tree src/olav -L 3
    """
    import subprocess
    import shutil
    
    if not shutil.which("tree"):
        # Fallback to find if tree is not installed
        console.print("[yellow]'tree' not found, using 'find' instead[/yellow]")
        try:
            result = subprocess.run(
                ["find", directory, "-maxdepth", str(depth), "-type", "d"],
                capture_output=True,
                text=True,
                timeout=10
            )
            console.print(result.stdout)
        except Exception as e:
            console.print(f"[red]Error:[/red] {e}")
        return
    
    try:
        result = subprocess.run(
            ["tree", "-L", str(depth), directory],
            capture_output=True,
            text=True,
            timeout=10
        )
        console.print(result.stdout)
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Command timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def backup(
    target: str | None = typer.Option(None, "--target", "-t", help="Target path for backup"),
):
    """Backup OLAV data (replaces 'admin backup').

    Examples:
        olav backup                      # Auto-named backup
        olav backup --target ~/backups/  # Custom target
    """
    import subprocess
    from datetime import datetime
    
    if not target:
        target = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz"
    elif Path(target).is_dir():
        target = str(Path(target) / f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tar.gz")
    
    console.print(f"[cyan]Creating backup:[/cyan] {target}")
    
    try:
        result = subprocess.run(
            ["tar", "-czf", target, ".olav/"],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            size = Path(target).stat().st_size / (1024 * 1024)
            console.print(f"[green]✓ Backup created:[/green] {target} ({size:.1f} MB)")
        else:
            console.print(f"[red]✗ Backup failed:[/red] {result.stderr}")
            
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Backup timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def restore(
    file: str = typer.Argument(..., help="Backup file path"),
):
    """Restore from backup (replaces 'admin restore').

    Examples:
        olav restore backup_20260215_153000.tar.gz
        olav restore ~/backups/latest.tar.gz
    """
    import subprocess
    
    backup_path = Path(file)
    if not backup_path.exists():
        console.print(f"[red]Error:[/red] Backup file not found: {file}")
        raise typer.Exit(1)
    
    console.print(f"[yellow]⚠️  This will overwrite existing data![/yellow]")
    confirm = typer.confirm("Continue with restore?")
    
    if not confirm:
        console.print("[cyan]Restore cancelled[/cyan]")
        return
    
    console.print(f"[cyan]Restoring from:[/cyan] {file}")
    
    try:
        result = subprocess.run(
            ["tar", "-xzf", file, "-C", "."],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode == 0:
            console.print(f"[green]✓ Restored from:[/green] {file}")
        else:
            console.print(f"[red]✗ Restore failed:[/red] {result.stderr}")
            
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Restore timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command()
def skills(
    detail: bool = typer.Option(False, "--detail", "-d", help="Show detailed info"),
):
    """List available skills (replaces 'admin skills').

    Examples:
        olav skills
        olav skills --detail
    """
    from pathlib import Path
    
    skills_path = Path(".olav/skills")
    
    if not skills_path.exists():
        console.print("[yellow]No skills directory found[/yellow]")
        return
    
    skill_list = []
    for skill_dir in sorted(skills_path.iterdir()):
        if skill_dir.is_dir() and (skill_dir / "SKILL.md").exists():
            if detail:
                tools_dir = skill_dir / "tools"
                tool_count = len(list(tools_dir.glob("*.py"))) if tools_dir.exists() else 0
                skill_list.append((skill_dir.name, tool_count))
            else:
                skill_list.append(skill_dir.name)
    
    if not skill_list:
        console.print("[yellow]No skills found[/yellow]")
        return
    
    console.print(f"[cyan]Found {len(skill_list)} skills:[/cyan]")
    
    if detail:
        table = Table(title="Skills")
        table.add_column("Skill Name", style="cyan")
        table.add_column("Tools", style="green")
        
        for name, tool_count in skill_list:
            table.add_row(name, str(tool_count))
        
        console.print(table)
    else:
        for skill in skill_list:
            console.print(f"  • {skill}")


@app.command()
def git(
    args: list[str] = typer.Argument(..., help="Git command and arguments"),
):
    """Git command shortcut.

    Examples:
        olav git status
        olav git log -10
        olav git diff
    """
    import subprocess
    
    try:
        result = subprocess.run(
            ["git"] + args,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.stdout:
            console.print(result.stdout)
        if result.stderr:
            console.print(result.stderr, style="yellow")
            
        if result.returncode != 0:
            raise typer.Exit(result.returncode)
            
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Git command timed out")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command()
def inspect(
    devices: str | None = typer.Option(
        None, "--devices", "-d",
        help="Comma-separated device names, e.g. 'R1,R2' (default: all)",
    ),
    groups: str | None = typer.Option(
        None, "--groups", "-g",
        help="Comma-separated Nornir group names, e.g. 'core,access' (default: all)",
    ),
    categories: str | None = typer.Option(
        None, "--categories", "-c",
        help="Comma-separated collection categories, e.g. 'routing,system' (default: all)",
    ),
    output_dir: str | None = typer.Option(
        None, "--output-dir", "-o",
        help="Directory to write the report (default: exports/reports)",
    ),
):
    """Run network snapshot — collect live data from devices via Nornir.

    Executes platform-specific commands in parallel and writes results to:
    - DuckDB parsed_outputs table (for SQL queries via olav-ops)
    - exports/snapshots/{date}/raw/ (raw command output files)

    Examples:
        olav inspect                               # All devices, all categories
        olav inspect --devices R1,R2               # Specific devices
        olav inspect --categories routing,system   # Specific command categories
        olav inspect --output-dir /tmp/reports     # Custom output directory
    """
    import sys as _sys

    _config_tools = Path(".olav/skills/olav-config/tools")
    if str(_config_tools) not in _sys.path:
        _sys.path.insert(0, str(_config_tools))
    from take_snapshot import take_snapshot  # noqa: PLC0415

    device_list = [d.strip() for d in devices.split(",")] if devices else None
    category_list = [c.strip() for c in categories.split(",")] if categories else None

    # Show scope to user before executing
    scope = " | ".join(filter(None, [
        f"devices: {devices}" if devices else None,
        "all devices" if not devices else None,
    ]))
    console.print(f"\n[cyan]🎯 Snapshot scope:[/cyan] {scope}")
    if categories:
        console.print(f"[cyan]Categories:[/cyan] {categories}")
    console.print()

    result = take_snapshot.invoke({
        "devices": device_list,
        "categories": category_list,
    })

    if result.get("status") == "success":
        collected = result.get("devices_collected", [])
        console.print(f"[green]✅ Snapshot complete — {len(collected)} device(s)[/green]")
        if collected:
            console.print(f"[cyan]Devices:[/cyan] {', '.join(collected)}")
        raise typer.Exit(0)
    else:
        msg = result.get("message") or result.get("error") or "Unknown error"
        console.print(f"[red]✗ Snapshot failed:[/red] {msg}", style="red")
        raise typer.Exit(1)


@app.command(name="db-status")
def db_status():
    """Show database status (replaces 'admin db-status').

    Examples:
        olav db-status
    """
    from pathlib import Path
    import duckdb
    
    db_path = Path(".olav/databases/main.duckdb")
    
    if not db_path.exists():
        console.print("[red]Database not found[/red]")
        return
    
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        
        # Get database size
        size_mb = db_path.stat().st_size / (1024 * 1024)
        
        # Get table list
        tables = conn.execute("SHOW TABLES").fetchall()
        
        console.print(f"[cyan]Database:[/cyan] {db_path}")
        console.print(f"[cyan]Size:[/cyan] {size_mb:.2f} MB")
        console.print(f"\n[cyan]Tables ({len(tables)}):[/cyan]")
        
        for table in tables:
            table_name = table[0]
            count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
            console.print(f"  • {table_name}: {count} rows")
        
        conn.close()
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


@app.command(name="db-query")
def db_query(
    sql: str = typer.Argument(..., help="SQL query to execute"),
    output: str | None = typer.Option(None, "--output", "-o", help="Output to CSV file"),
):
    """Execute SQL query on main database (replaces 'admin db-query').

    Examples:
        olav db-query "SELECT * FROM devices LIMIT 10"
        olav db-query "SELECT COUNT(*) FROM devices" 
        olav db-query "SELECT * FROM devices" --output devices.csv
    """
    from pathlib import Path
    import duckdb
    
    db_path = Path(".olav/databases/main.duckdb")
    
    if not db_path.exists():
        console.print("[red]Database not found[/red]")
        raise typer.Exit(1)
    
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        
        result = conn.execute(sql).fetchall()
        columns = [desc[0] for desc in conn.description]
        
        if output:
            # Write to CSV
            import csv
            output_path = Path(output)
            with open(output_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(result)
            console.print(f"[green]✓ Output saved to:[/green] {output}")
        else:
            # Display in terminal
            if not result:
                console.print("[yellow]No results[/yellow]")
                return
            
            table = Table(title=f"Query Results ({len(result)} rows)")
            for col in columns:
                table.add_column(col, style="cyan")
            
            for row in result[:50]:  # Limit display to 50 rows
                table.add_row(*[str(v) for v in row])
            
            console.print(table)
            
            if len(result) > 50:
                console.print(f"\n[yellow]... and {len(result) - 50} more rows[/yellow]")
        
        conn.close()
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


@app.command(name="db-schema")
def db_schema(
    table: str | None = typer.Argument(None, help="Table name (optional)"),
):
    """Show database schema (replaces 'admin db-schema').

    Examples:
        olav db-schema           # Show all tables
        olav db-schema devices   # Show schema for devices table
    """
    from pathlib import Path
    import duckdb
    
    db_path = Path(".olav/databases/main.duckdb")
    
    if not db_path.exists():
        console.print("[red]Database not found[/red]")
        raise typer.Exit(1)
    
    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        
        if table:
            # Show schema for specific table
            schema = conn.execute(f"DESCRIBE {table}").fetchall()
            
            console.print(f"[cyan]Schema for table:[/cyan] {table}")
            
            tbl = Table()
            tbl.add_column("Column", style="cyan")
            tbl.add_column("Type", style="green")
            tbl.add_column("Null", style="yellow")
            
            for row in schema:
                tbl.add_row(row[0], row[1], "YES" if row[2] else "NO")
            
            console.print(tbl)
        else:
            # Show all tables with row counts
            tables = conn.execute("SHOW TABLES").fetchall()
            
            console.print(f"[cyan]Database Schema ({len(tables)} tables):[/cyan]")
            
            tbl = Table()
            tbl.add_column("Table", style="cyan")
            tbl.add_column("Rows", style="green")
            
            for t in tables:
                table_name = t[0]
                count = conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                tbl.add_row(table_name, str(count))
            
            console.print(tbl)
            console.print("\n[dim]Tip: Use 'olav db-schema <table>' for detailed schema[/dim]")
        
        conn.close()
        
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


# ============================================================================
# Task Management Subcommand
# ============================================================================

try:
    from olav.cli.task_manager import get_task_app
    app.add_typer(get_task_app(), name="task", help="Manage periodic inspection tasks")
except Exception as e:
    logger.debug(f"Task manager not available: {e}")


if __name__ == "__main__":
    app()
