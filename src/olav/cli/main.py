#!/usr/bin/env python3
"""OLAV v0.9.9 CLI - argparse-based (deepagents-cli style).

This replaces the Typer-based CLI for a simpler, more maintainable architecture.

Usage:
    olav                                    # Interactive mode
    olav ask "How many devices?"           # Single query
    olav devices                            # List devices
    olav db status                          # Database status
    olav status                             # OLAV status
    olav --help                             # Help
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

logger = logging.getLogger(__name__)
console = Console()

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

# Version
VERSION = "0.9.9"

# Global agent cache
_cached_agent = None


# ============================================================================
# Helper Functions
# ============================================================================


def _get_cached_agent():
    """Get or create cached agent instance."""
    global _cached_agent
    if _cached_agent is None:
        from olav.agents.agent import create_olav_agent

        _cached_agent = create_olav_agent(enable_checkpointer=False, enable_store=False)
    return _cached_agent


def _check_llm_key():
    """Check if LLM API key is configured."""
    from config.settings import settings

    if not settings.llm_api_key:
        console.print("[bold red]Error:[/] LLM_API_KEY environment variable not set", style="red")
        console.print("\nTo set up LLM API access:")
        console.print("  1. Add to .env file:")
        console.print("     LLM_API_KEY='your-api-key'")
        console.print("     LLM_PROVIDER='openai'")
        console.print("     LLM_MODEL_NAME='gpt-4'")
        sys.exit(1)


async def _stream_response(agent, query: str, thread_id: str | None = None) -> dict:
    """Invoke agent and render the response."""
    from rich.markdown import Markdown
    from olav.cli.daemon import query_daemon
    from olav.cli.display import StreamingDisplay

    display = StreamingDisplay(console=console, verbose=False)

    # Tier 0: Exact cache hit
    try:
        from olav.core.response_cache import get_response_cache

        cache = get_response_cache()
        hit = cache.get_exact(query)
        if hit:
            response = hit["response"]
            if response:
                console.print(Markdown(response))
                console.print()
            return {"status": "success", "response": response}
    except Exception as cache_err:
        logger.debug("ResponseCache lookup failed: %s", cache_err)

    # Tier 1 & 2: Call the agent
    display.show_processing_status("Thinking...")

    try:
        # Tier 1: daemon
        daemon_result = await query_daemon(query, thread_id=thread_id)
        if daemon_result is not None:
            display.stop_processing_status()
            response = daemon_result.get("response", "")
            if response:
                console.print(Markdown(response))
                console.print()
            return daemon_result

        # Tier 2: in-process agent
        if agent is None:
            agent = _get_cached_agent()

        result = await agent.invoke(query, thread_id=thread_id)
        display.stop_processing_status()

        response = result.get("response", "")
        if response:
            console.print(Markdown(response))
            console.print()

        return result

    except Exception as e:
        display.stop_processing_status()
        console.print(f"[red]Error:[/red] {e}", style="red")
        return {"status": "error", "message": str(e)}


def _run_interactive():
    """Enter interactive mode."""
    import uuid
    from olav.cli.commands.builtin import execute_command
    from olav.cli.daemon import get_daemon_status, spawn_daemon
    from olav.cli.display import StreamingDisplay, display_banner, load_banner_from_config
    from olav.cli.session import OlavPromptSession

    _check_llm_key()
    thread_id = str(uuid.uuid4())[:8]

    # Display banner
    banner_text = load_banner_from_config()
    if banner_text:
        display_banner(banner_text, console=console)

    async def _interactive_loop():
        display = StreamingDisplay(console=console)
        display.show_processing_status("Initializing OLAV...")

        status = get_daemon_status()
        if not status.get("running"):
            spawn_daemon()
            agent = await asyncio.to_thread(_get_cached_agent)
        else:
            agent = None

        display.stop_processing_status()

        console.print(
            Panel(
                f"OLAV v{VERSION} - Interactive Mode (Thread: [bold cyan]{thread_id}[/bold cyan])\n\n"
                f"• Type [bold]/help[/bold] for commands, [bold]/quit[/bold] to exit.\n"
                f"• Natural language queries are supported directly.",
                border_style="blue",
                title="[cyan]READY[/cyan]",
            )
        )

        session = OlavPromptSession(enable_completion=False, multiline=False)

        while True:
            try:
                query = await session.prompt_async("OLAV> ")
                query = query.strip()

                if not query:
                    continue

                if query.lower() in ("exit", "quit", "bye"):
                    console.print("[cyan]Goodbye![/cyan]")
                    break

                if query.startswith("/"):
                    try:
                        result = await execute_command(query, agent=None)
                        if result:
                            console.print(result)
                    except EOFError:
                        console.print("[cyan]Goodbye![/cyan]")
                        break
                    except Exception as e:
                        console.print(f"[red]Error:[/red] {e}")
                    continue

                await _stream_response(agent, query, thread_id)

            except (KeyboardInterrupt, EOFError):
                console.print("\n[cyan]Goodbye![/cyan]")
                break
            except Exception as e:
                console.print(f"[red]Error:[/red] {e}")

    asyncio.run(_interactive_loop())


# ============================================================================
# Command Implementations (no Typer dependencies)
# ============================================================================


def cmd_ask(query: str):
    """Execute a single query."""
    _check_llm_key()
    agent = _get_cached_agent()
    asyncio.run(_stream_response(agent, query))


def cmd_devices(role: str | None = None, site: str | None = None):
    """List network devices."""
    import duckdb

    db_path = Path(".olav/databases/main.duckdb")
    if not db_path.exists():
        console.print("[red]Error:[/red] Database not found. Run 'olav status' to initialize.")
        sys.exit(1)

    conn = duckdb.connect(str(db_path), read_only=True)

    query = "SELECT * FROM devices WHERE 1=1"
    params = []

    if role:
        query += " AND role = ?"
        params.append(role)

    if site:
        query += " AND site = ?"
        params.append(site)

    query += " ORDER BY name"

    try:
        results = conn.execute(query, params).fetchall()
        columns = [desc[0] for desc in conn.description]

        if not results:
            console.print("[yellow]No devices found matching the criteria.[/yellow]")
            return

        table = Table(title=" 🖥️  Network Devices")
        for col in columns:
            table.add_column(col, style="cyan")

        for row in results:
            table.add_row(*[str(v) for v in row])

        console.print(table)

    finally:
        conn.close()


def cmd_inspect(devices: str | None = None, categories: str | None = None):
    """Run network snapshot."""
    import sys as _sys

    _config_tools = Path(".olav/skills/olav-config/tools")
    if str(_config_tools) not in _sys.path:
        _sys.path.insert(0, str(_config_tools))
    from take_snapshot import take_snapshot

    device_list = [d.strip() for d in devices.split(",")] if devices else None
    category_list = [c.strip() for c in categories.split(",")] if categories else None

    scope = " | ".join(
        filter(
            None,
            [
                f"devices: {devices}" if devices else None,
                "all devices" if not devices else None,
            ],
        )
    )
    console.print(f"\n[cyan]🎯 Snapshot scope:[/cyan] {scope}")
    if categories:
        console.print(f"[cyan]Categories:[/cyan] {categories}")
    console.print()

    result = take_snapshot.invoke(
        {
            "devices": device_list,
            "categories": category_list,
        }
    )

    if result.get("status") == "success":
        collected = result.get("devices_collected", [])
        console.print(f"[green]✅ Snapshot complete — {len(collected)} device(s)[/green]")
        if collected:
            console.print(f"[cyan]Devices:[/cyan] {', '.join(collected)}")
        sys.exit(0)
    else:
        msg = result.get("message") or result.get("error") or "Unknown error"
        console.print(f"[red]✗ Snapshot failed:[/red] {msg}", style="red")
        sys.exit(1)


def cmd_db_status():
    """Show database status."""
    import duckdb

    db_path = Path(".olav/databases/main.duckdb")

    if not db_path.exists():
        console.print("[red]Database not found[/red]")
        return

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        size_mb = db_path.stat().st_size / (1024 * 1024)
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


def cmd_db_query(sql: str, output: str | None = None):
    """Execute SQL query."""
    import csv
    import duckdb

    db_path = Path(".olav/databases/main.duckdb")

    if not db_path.exists():
        console.print("[red]Database not found[/red]")
        sys.exit(1)

    try:
        conn = duckdb.connect(str(db_path), read_only=True)
        result = conn.execute(sql).fetchall()
        columns = [desc[0] for desc in conn.description]

        if output:
            output_path = Path(output)
            with open(output_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(columns)
                writer.writerows(result)
            console.print(f"[green]✓ Output saved to:[/green] {output}")
        else:
            if not result:
                console.print("[yellow]No results[/yellow]")
                return

            table = Table(title=f"Query Results ({len(result)} rows)")
            for col in columns:
                table.add_column(col, style="cyan")

            for row in result[:50]:
                table.add_row(*[str(v) for v in row])

            console.print(table)

            if len(result) > 50:
                console.print(f"\n[yellow]... and {len(result) - 50} more rows[/yellow]")

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def cmd_db_schema(table: str | None = None):
    """Show database schema."""
    import duckdb

    db_path = Path(".olav/databases/main.duckdb")

    if not db_path.exists():
        console.print("[red]Database not found[/red]")
        sys.exit(1)

    try:
        conn = duckdb.connect(str(db_path), read_only=True)

        if table:
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
            console.print("\n[dim]Tip: Use 'olav db schema <table>' for detailed schema[/dim]")

        conn.close()

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)


def cmd_status():
    """Show OLAV system status."""
    from olav.cli.admin import admin_handler

    result = asyncio.run(admin_handler("/admin status"))

    if result["status"] == "success":
        console.print(
            Panel(
                str(result.get("data", result)),
                title="[green]✓ OLAV Status[/green]",
                border_style="green",
            )
        )
    else:
        console.print(
            Panel(
                result.get("message", "Unknown error"),
                title="[red]✗ Error[/red]",
                border_style="red",
            )
        )


def cmd_backup(target: str | None = None):
    """Backup OLAV data."""
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
            timeout=60,
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


def cmd_restore(file: str):
    """Restore from backup."""
    backup_path = Path(file)
    if not backup_path.exists():
        console.print(f"[red]Error:[/red] Backup file not found: {file}")
        sys.exit(1)

    console.print("[yellow]⚠️  This will overwrite existing data![/yellow]")
    console.print(f"[cyan]Restoring from:[/cyan] {file}")

    try:
        result = subprocess.run(
            ["tar", "-xzf", file, "-C", "."],
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode == 0:
            console.print(f"[green]✓ Restored from:[/green] {file}")
        else:
            console.print(f"[red]✗ Restore failed:[/red] {result.stderr}")

    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Restore timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


def cmd_skills(detail: bool = False):
    """List available skills."""
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


def cmd_ls(pattern: str = "*", directory: str = "."):
    """List files matching pattern."""
    try:
        result = subprocess.run(
            ["find", directory, "-name", pattern, "-type", "f"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0:
            files = result.stdout.strip().split("\n")
            files = [f for f in files if f]

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


def cmd_search(pattern: str, file_type: str = "py", directory: str = "."):
    """Search for pattern in codebase."""
    cmd = ["grep", "-r", "-n", pattern, directory]

    if file_type != "all":
        cmd.append(f"--include=*.{file_type}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            lines = [l for l in lines if l]

            console.print(f"[cyan]Found {len(lines)} matches:[/cyan]")
            for line in lines[:50]:
                console.print(line)

            if len(lines) > 50:
                console.print(f"\n[yellow]... and {len(lines) - 50} more matches[/yellow]")
        else:
            console.print(f"[yellow]No matches found for '{pattern}'[/yellow]")

    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Command timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


def cmd_tree(directory: str = ".", depth: int = 3):
    """Show directory tree."""
    import shutil

    if not shutil.which("tree"):
        console.print("[yellow]'tree' not found, using 'find' instead[/yellow]")
        try:
            result = subprocess.run(
                ["find", directory, "-maxdepth", str(depth), "-type", "d"],
                capture_output=True,
                text=True,
                timeout=10,
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
            timeout=10,
        )
        console.print(result.stdout)
    except subprocess.TimeoutExpired:
        console.print("[red]Error:[/red] Command timed out")
    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")


# ============================================================================
# Argument Parser Setup
# ============================================================================


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        prog="olav",
        description="OLAV v0.9.9 - Network Operations AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument("--version", "-V", action="version", version=f"OLAV v{VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # ask command
    ask_parser = subparsers.add_parser("ask", help="Ask OLAV a question (non-interactive)")
    ask_parser.add_argument("query", help="Natural language query")

    # devices command
    devices_parser = subparsers.add_parser("devices", help="List network devices")
    devices_parser.add_argument("--role", "-r", help="Filter by role (core, access, edge)")
    devices_parser.add_argument("--site", "-s", help="Filter by site")

    # inspect command
    inspect_parser = subparsers.add_parser("inspect", help="Run network snapshot")
    inspect_parser.add_argument("--devices", "-d", help="Comma-separated device names")
    inspect_parser.add_argument("--categories", "-c", help="Comma-separated categories")

    # db command group
    db_parser = subparsers.add_parser("db", help="Database operations")
    db_subparsers = db_parser.add_subparsers(dest="db_command", help="Database commands")

    # db status
    db_subparsers.add_parser("status", help="Show database status")

    # db query
    db_query_parser = db_subparsers.add_parser("query", help="Execute SQL query")
    db_query_parser.add_argument("sql", help="SQL query to execute")
    db_query_parser.add_argument("--output", "-o", help="Output to CSV file")

    # db schema
    db_schema_parser = db_subparsers.add_parser("schema", help="Show database schema")
    db_schema_parser.add_argument("table", nargs="?", help="Table name (optional)")

    # status command
    subparsers.add_parser("status", help="Show OLAV system status")

    # backup command
    backup_parser = subparsers.add_parser("backup", help="Backup OLAV data")
    backup_parser.add_argument("--target", "-t", help="Target path for backup")

    # restore command
    restore_parser = subparsers.add_parser("restore", help="Restore from backup")
    restore_parser.add_argument("file", help="Backup file path")

    # skills command
    skills_parser = subparsers.add_parser("skills", help="List available skills")
    skills_parser.add_argument("--detail", "-d", action="store_true", help="Show detailed info")

    # ls command
    ls_parser = subparsers.add_parser("ls", help="List files matching pattern")
    ls_parser.add_argument("pattern", nargs="?", default="*", help="File pattern")
    ls_parser.add_argument("--dir", "-d", default=".", help="Directory to search")

    # search command
    search_parser = subparsers.add_parser("search", help="Search for pattern in files")
    search_parser.add_argument("pattern", help="Search pattern")
    search_parser.add_argument("--type", "-t", default="py", help="File type (py, md, all)")
    search_parser.add_argument("--dir", "-d", default=".", help="Directory to search")

    # tree command
    tree_parser = subparsers.add_parser("tree", help="Show directory tree")
    tree_parser.add_argument("directory", nargs="?", default=".", help="Directory to show")
    tree_parser.add_argument("--depth", "-L", type=int, default=3, help="Max depth")

    # Legacy aliases (for backward compatibility)
    # db-status, db-query, db-schema are handled in main()

    return parser.parse_args()


# ============================================================================
# Main Entry Point
# ============================================================================


def cli_main():
    """Main entry point for console script."""
    # Fix for gRPC fork issue on macOS
    if sys.platform == "darwin":
        import os

        os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

    try:
        args = parse_args()

        if args.verbose:
            logging.basicConfig(level=logging.DEBUG)

        # Handle commands
        if args.command == "ask":
            cmd_ask(args.query)

        elif args.command == "devices":
            cmd_devices(role=args.role, site=args.site)

        elif args.command == "inspect":
            cmd_inspect(devices=args.devices, categories=args.categories)

        elif args.command == "db":
            if args.db_command == "status":
                cmd_db_status()
            elif args.db_command == "query":
                cmd_db_query(args.sql, output=args.output)
            elif args.db_command == "schema":
                cmd_db_schema(args.table)
            else:
                console.print("[yellow]Usage: olav db {status|query|schema}[/yellow]")
                sys.exit(1)

        elif args.command == "status":
            cmd_status()

        elif args.command == "backup":
            cmd_backup(target=args.target)

        elif args.command == "restore":
            cmd_restore(args.file)

        elif args.command == "skills":
            cmd_skills(detail=args.detail)

        elif args.command == "ls":
            cmd_ls(pattern=args.pattern, directory=args.dir)

        elif args.command == "search":
            cmd_search(pattern=args.pattern, file_type=args.type, directory=args.dir)

        elif args.command == "tree":
            cmd_tree(directory=args.directory, depth=args.depth)

        elif args.command is None:
            # No command - enter interactive mode
            _run_interactive()

        else:
            console.print(f"[red]Unknown command:[/red] {args.command}")
            sys.exit(1)

    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {e}")
        if logging.getLogger().level == logging.DEBUG:
            console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
