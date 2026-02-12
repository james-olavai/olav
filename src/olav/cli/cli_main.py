"""OLAV CLI Main Entry Point - Typer-based CLI with interactive mode.

P7 Enhancement: Added streaming output for real-time token display.
Supports:
  - uv run olav              # Interactive mode (default)
  - uv run olav query "..."  # Single query
  - uv run olav devices      # List devices
  - uv run olav --help       # Show help
"""

import asyncio
import logging
import sys
from typing import TYPE_CHECKING, Any

import typer

logger = logging.getLogger(__name__)
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

if TYPE_CHECKING:
    from olav.cli.session import OlavPromptSession

# Lazy imports to speed up --help
console = Console()
app = typer.Typer(
    name="olav",
    help="OLAV v0.9.6 - Network Operations AI Assistant",
    no_args_is_help=False,  # Default to interactive mode
    invoke_without_command=True,
)


def _display_todos(agent_graph: Any) -> None:
    """Display todo list from agent state using Rich.

    Args:
        agent_graph: Compiled LangGraph agent with state
    """
    try:
        # Get the latest state from the graph
        state = agent_graph.get_state()
        todos: list[dict[str, Any]] = state.values.get("todos", []) if state and hasattr(state, "values") else []

        if not todos:
            return

        table = Table(show_header=True, header_style="bold magenta", border_style="blue")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Status", width=15)
        table.add_column("Task", min_width=30)

        status_icons = {"not-started": "⬜", "in-progress": "🔄", "completed": "✅"}

        for todo in todos:
            icon = status_icons.get(todo.get("status", "not-started"), "⬜")
            table.add_row(
                str(todo.get("id", "")),
                f"{icon} {todo.get('status', 'not-started')}",
                str(todo.get("title", "")),
            )

        panel = Panel(table, title="📋 Task Progress", border_style="blue")
        console.print(panel)
    except Exception as e:
        logger.debug(f"Could not display todos: {e}")


async def stream_agent_response(
    agent: Any,
    inputs: dict[str, Any] | list[dict[str, Any]],
    verbose: bool = False,
    thread_id: str | None = None,  # LangGraph thread_id for session
    timeout: float | None = None,  # Query timeout in seconds (None = use settings)
) -> str:
    """Stream agent response with timeout and session support.

    Args:
        agent: OLAV agent instance (CompiledGraph)
        inputs: Input dict
        verbose: Show reasoning process
        thread_id: Session thread_id for checkpointer
        timeout: Query timeout in seconds (None = use settings.query_timeout)

    Returns:
        Final result string
    """
    import asyncio

    from config.settings import settings
    from olav.cli.display import StreamingDisplay

    # Use settings if timeout not specified
    if timeout is None:
        timeout = float(settings.execution.query_timeout)
    is_tty = sys.stdin.isatty()

    if isinstance(inputs, dict):
        base_inputs = inputs
    else:
        base_inputs = {"messages": inputs, "retry_count": 0}

    # Add thread_id to config for checkpointer
    config = {}
    if thread_id:
        config["configurable"] = {"thread_id": thread_id}

    display = StreamingDisplay(verbose=verbose, show_spinner=True, quiet=not is_tty)

    # Show spinner if not verbose (in verbose, logs will show activity)
    if not verbose:
        display.show_processing_status("☃️ Olav is digging...")

    try:
        # Use ainvoke with timeout
        final_state = await asyncio.wait_for(
            agent.ainvoke(base_inputs, config=config),
            timeout=timeout,
        )

        display.stop_processing_status()

        result = final_state.get("result")
        error = final_state.get("error")
        sql_query = final_state.get("sql_query")

        # If verbose mode or if result is missing, check message content
        messages = final_state.get("messages", [])
        last_message_content = ""
        if messages:
            last_msg = messages[-1]
            if hasattr(last_msg, "content") and last_msg.content:
                last_message_content = last_msg.content

        if verbose and sql_query:
            from rich.panel import Panel

            # In verbose mode, show the generated SQL
            if display.console:
                display.console.print(Panel(sql_query, title="Generated SQL", border_style="dim"))

        if error:
            display.show_error(error)
            return f"Error: {error}"

        if result:
            result_str = str(result)

            if is_tty:
                # Default: render ALL output as Markdown.
                # Orchestrator returns markdown-formatted text (tables, headers,
                # lists). Rich's Markdown renderer handles all of these well.
                # Structured JSON/list data is pre-formatted by the Orchestrator
                # into markdown tables before reaching here.
                display.show_result(result_str, markdown=True)

            # P10 Fix: Ensure output is flushed to stdout when piped (bypassing Rich/print stack)
            if not is_tty:
                val_to_print = result_str
                if isinstance(result, (dict, list)):
                    import json

                    val_to_print = json.dumps(result, ensure_ascii=False)

                # Use os.write to guarantee output to stdout (fd 1) even if Python buffers/redirects
                import os

                os.write(1, (val_to_print + "\n").encode())

            if is_tty:
                print()  # Final newline for prompt-toolkit
            return result_str

        # If no structured result, but we have text content (explanation), show that
        if last_message_content and not result:
            if is_tty:
                display.show_result(last_message_content, markdown=True)
            else:
                # Piped mode: write raw text to stdout
                import os
                os.write(1, (last_message_content + "\n").encode())
            return last_message_content
        return "No result available"

    except TimeoutError:
        display.stop_processing_status()
        error_msg = f"Query timed out after {timeout} seconds"
        display.show_error(error_msg)
        return f"Error: {error_msg}"

    except Exception as e:
        display.stop_processing_status()
        import traceback

        traceback.print_exc()
        display.show_error(str(e))
        return f"Error: {e}"


def _get_snapshot_time() -> str | None:
    """Get snapshot timestamp from database.

    Returns:
        Snapshot timestamp string or None if unavailable
    """
    try:
        from olav.core.unified_database import UnifiedDatabase

        with UnifiedDatabase() as db:
            # Try to get snapshot time from views
            result = db.query("""
                SELECT DISTINCT snapshot_date
                FROM main.v_system
                LIMIT 1
            """)
            if result and result[0]:
                return str(result[0][0])
    except Exception as e:
        logger.debug(f"Failed to get snapshot time: {e}")
    return None


async def run_interactive_loop_async(
    session: "OlavPromptSession",
    agent: Any,
    resume: bool = False,
    thread_id: str | None = None,
) -> None:
    """Run the OLAV CLI (asynchronous version for proper event loop handling).

    Args:
        session: Prompt session
        agent: OLAV agent instance (with checkpointer for state management)
        resume: Resume last session
        thread_id: Specific thread ID to use or resume
    """
    import uuid

    from config.settings import settings
    from olav.cli.commands.builtin import execute_command
    from olav.cli.input_parser import parse_input

    # Check if running in TTY mode
    is_tty = sys.stdin.isatty()

    # Generate or load session thread_id for checkpointer
    from config.paths import OLAV_BASE_DIR
    
    thread_id_file = OLAV_BASE_DIR / ".last_thread_id"
    
    if resume and thread_id_file.exists():
        # Resume last session
        loaded_thread_id = thread_id_file.read_text().strip()
        if not thread_id:
            thread_id = loaded_thread_id
            if is_tty:
                console.print(f"[cyan]📂 Resuming session: {thread_id}[/cyan]")
    
    if not thread_id:
        # Generate new thread_id
        thread_id = str(uuid.uuid4())
        if is_tty:
            console.print(f"[cyan]🆕 New session: {thread_id}[/cyan]")
    else:
        if is_tty:
            console.print(f"[cyan]🔗 Using session: {thread_id}[/cyan]")
    
    # Save thread_id for --resume
    thread_id_file.parent.mkdir(exist_ok=True)
    thread_id_file.write_text(thread_id)
    
    logger.debug(f"Starting interactive session with thread_id: {thread_id}")

    # Initialize Guard (Security Gatekeeper) and Display
    from olav.cli.display import StreamingDisplay
    from olav.core.guard import Guard

    display = StreamingDisplay(
        console=console, verbose=False, show_spinner=is_tty, quiet=not is_tty
    )

    # Initialize Guard for security checks
    guard = Guard()

    # Display cache metrics on startup (TTY only)
    if is_tty:
        try:
            from olav.cache import cache

            metrics = cache.get_cache_metrics()
            intent = metrics["intent"]
            if intent["total_entries"] > 0:
                print(
                    f"📊 Cache: {intent['total_entries']} entries, "
                    f"{intent['total_hits']} hits, "
                    f"hit rate {intent['hit_rate_pct']}%"
                )
        except Exception as e:
            logger.debug(f"Failed to display cache metrics: {e}")

    if is_tty:
        print("Type /help for available commands or just ask a question.\n")

    while True:
        try:
            # Get user input asynchronously
            prompt_str = "OLAV> " if is_tty else ""
            user_input = await session.prompt_async(prompt_str)

            # Strip BOM and whitespace (PowerShell on Windows adds BOM to piped input)
            user_input = user_input.lstrip("\ufeff").strip()

            if not user_input:
                continue

            # =========================================================================
            # Guard: Security check before processing
            # =========================================================================
            guard_result = guard.check(user_input)

            # Handle Guard rejections
            if guard_result.action == "reject":
                print(f"🚫 {guard_result.message}")
                continue

            # Handle approval requirements
            if guard_result.action == "require_approval":
                print(f"⚠️  {guard_result.message}")
                confirm = await session.prompt_async("Continue? (yes/no): ")
                if confirm.lower() not in ["yes", "y"]:
                    print("❌ Cancelled")
                    continue

            # Handle warnings
            if guard_result.action == "warn" and guard_result.message:
                print(f"⚠️  {guard_result.message}")

            # Check for slash commands first
            if user_input.startswith("/"):
                try:
                    # Run async command handler with await
                    result = await execute_command(
                        user_input,
                        agent=None,  # Slash commands don't need agent
                    )
                    if result:
                        # Check if result should be sent to Agent
                        if result.startswith("AGENT_PROMPT::"):
                            # Extract prompt and send to Orchestrator
                            agent_prompt = result[len("AGENT_PROMPT::"):]
                            print("🤖 Sending to Orchestrator for analysis...\n")
                            from langchain_core.messages import HumanMessage

                            from olav.agents.orchestrator import create_orchestrator
                            _cmd_agent = create_orchestrator(thread_id=thread_id)
                            use_verbose = settings.display_thinking
                            _cmd_inputs = {"messages": [HumanMessage(content=agent_prompt)]}
                            output = await stream_agent_response(
                                _cmd_agent, _cmd_inputs, verbose=use_verbose, thread_id=thread_id
                            )
                        else:
                            print(result)
                except EOFError:
                    # /quit raises EOFError - re-raise to exit
                    raise
                except Exception as e:
                    print(f"❌ Error: {e}", file=sys.stderr)
                continue

            # Parse input for special syntax (file refs, shell commands)
            processed_text, is_shell_cmd, shell_cmd = parse_input(user_input)

            # Handle shell commands
            if is_shell_cmd and shell_cmd:
                import subprocess

                try:
                    result = subprocess.run(  # noqa: ASYNC221
                        shell_cmd,
                        shell=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    if result.stdout:
                        print(result.stdout)
                    if result.stderr:
                        print(f"⚠️ {result.stderr}", file=sys.stderr)
                except subprocess.TimeoutExpired:
                    print("⏱️ Command timed out (30s)")
                except Exception as e:
                    print(f"❌ Error executing command: {e}")
                continue

            # Handle normal queries
            # Checkpointer automatically manages conversation history

            # P8: Stream agent response with layered output
            if is_tty:
                print("🔍 Processing...", flush=True)
            try:
                # =========================================================
                # Unified Routing: ALL queries → Orchestrator
                # =========================================================
                # Orchestrator's DeepAgents SubAgent routing handles:
                #   query SubAgent → database queries
                #   analysis SubAgent → diagnostics
                #   cli SubAgent → device command execution
                #   expert SubAgent → complex troubleshooting
                # Orchestrator owns format_and_export for file output.
                # CLI default output: markdown (rendered by Rich).
                # =========================================================
                from langchain_core.messages import HumanMessage

                from olav.agents.orchestrator import create_orchestrator
                agent = create_orchestrator(thread_id=thread_id)
                inputs = {"messages": [HumanMessage(content=processed_text)]}

                # Use verbose mode only if DISPLAY_THINKING=true
                use_verbose = settings.display_thinking

                # Use await instead of asyncio.run() to properly handle async context
                output = await stream_agent_response(
                    agent,
                    inputs,
                    verbose=use_verbose,
                    thread_id=thread_id,  # Session thread_id
                )

                if output:
                    # Display todos if present in agent state (QueryAgent only)
                    if hasattr(agent, 'agent'):
                        _display_todos(agent.agent)
                else:
                    print("\n⚠️ No response from agent\n")

            except Exception as e:
                print(f"❌ Error: {str(e)}")

        except EOFError:
            # User pressed Ctrl+D or /quit
            if sys.stdin.isatty():
                print("\n👋 Goodbye! Session saved.")
            break
        except KeyboardInterrupt:
            print("\n⚠️ Interrupted. Type /quit to exit.")
            continue
        except Exception:
            # Suppress error printing to prevent infinite loops
            continue


@app.command()
def query(
    query_text: str = typer.Argument(..., help="Network operation query"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug logging"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show full LLM thinking process"),
    guard: bool = typer.Option(None, "--guard/--no-guard", help="Use Guard routing (default: use settings)"),
) -> None:
    """Execute a single network operations query with Guard routing.

    Examples:
        olav query "查看 R1 的接口状态"
        olav query "R1 的 BGP 邻居" --debug
        olav query "Check R2 BGP" --verbose
        olav query "count devices" --guard       # Force Guard enabled
        olav query "list routers" --no-guard     # Force Guard disabled
    """
    from olav.cli.display import StreamingDisplay
    from config.settings import settings

    display = StreamingDisplay(console=console, verbose=verbose, show_spinner=not verbose)

    console.print(Panel(f"[bold cyan]Query[/bold cyan]: {query_text}", border_style="cyan"))

    try:
        if not verbose:
            display.show_processing_status("🛡️ Guard analyzing query...")

        # Determine if Guard should be used (Phase 5: Guard as Entry Point)
        use_guard = guard if guard is not None else settings.agent.enable_guard_routing
        
        if use_guard:
            # Phase 5: Use Guard.route_and_execute() as entry point
            # Guard will route based on query classification:
            #   - High confidence (≥0.75): Direct execution (bypasses Orchestrator)
            #   - Low confidence (<0.75): Falls back to Orchestrator
            from olav.agents.guard import get_guard
            guard_instance = get_guard()
            result = guard_instance.route_and_execute(query_text)
        else:
            # Fallback to sync orchestrator (v0.11.x behavior, without Guard)
            from olav.agents.orchestrator import orchestrate_query_sync
            result = orchestrate_query_sync(query_text)

        display.stop_processing_status()

        # Display Guard routing info if available
        if result.get("route"):
            route = result["route"]
            confidence = result.get("confidence", 0.0)
            console.print(f"[dim]Route: {route} (confidence: {confidence:.2f})[/dim]")
        
        if result.get("execution_time"):
            latency = result["execution_time"]
            console.print(f"[dim]Latency: {latency:.1f}ms[/dim]")

        # Handle Orchestrator result dict
        if result.get("status") == "complete":
            answer = result.get("final_answer", result.get("result", ""))
            if answer:
                from rich.markdown import Markdown
                console.print(Markdown(answer))
            else:
                console.print("\n[bold yellow]⚠[/bold yellow] No result\n")
        elif result.get("status") == "rejected":
            console.print(f"\n[bold red]❌ {result.get('message', 'Query rejected')}[/bold red]\n")
        else:
            error_msg = result.get("error_message", result.get("message", "Unknown error"))
            console.print(
                f"\n[bold red]❌ Error:[/bold red] {error_msg}\n"
            )

    except Exception as e:
        display.stop_processing_status()
        console.print(f"[bold red]❌ Error: {str(e)}[/bold red]")
        if debug:
            import traceback

            traceback.print_exc()
        raise typer.Exit(1) from None


@app.command()
def devices() -> None:
    """List all managed network devices."""
    from olav.core.tool_registry import get_tool

    console.print("[bold cyan]Loading network devices...[/bold cyan]")
    try:
        # Get tool from registry
        list_devices_tool = get_tool("list_devices")
        if list_devices_tool:
            # Try to call the tool (handle both tool wrapper and direct function)
            if hasattr(list_devices_tool, 'func'):
                result = list_devices_tool.func()
            else:
                result = list_devices_tool()
        else:
            result = "Error: list_devices tool not found"
        
        console.print(
            Panel(result, title="[bold cyan]Network Devices[/bold cyan]", border_style="cyan")
        )
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/bold red]")
        raise typer.Exit(1) from None


@app.command()
def version() -> None:
    """Show OLAV version and information."""
    console.print(
        Panel(
            "[bold cyan]OLAV v0.9.6[/bold cyan]\n"
            "Network Operations AI Assistant\n"
            "Unified Schema & Zero-ETL Architecture",
            border_style="cyan",
        )
    )


@app.command()
def clean(
    all: bool = typer.Option(False, "--all", "-a", help="Clean everything (cache + checkpoints + databases)"),
    cache: bool = typer.Option(False, "--cache", "-c", help="Clean cache only"),
    checkpoints: bool = typer.Option(False, "--checkpoints", "-p", help="Clean checkpoints only"),
    databases: bool = typer.Option(False, "--databases", "-d", help="Clean snapshot databases only (keeps device inventory)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation prompt"),
) -> None:
    """Clean OLAV data: cache, checkpoints, and databases.
    
    Examples:
        olav clean --cache              # Clear query cache only
        olav clean --checkpoints        # Clear session checkpoints
        olav clean --all                # Clean everything (with confirmation)
        olav clean --all --force        # Clean everything (no confirmation)
        olav clean --databases          # Clear snapshot data (keeps devices table)
    """
    
    # If no specific flags, show help
    if not (all or cache or checkpoints or databases):
        console.print("[yellow]Please specify what to clean:[/yellow]")
        console.print("  --cache        Cache files")
        console.print("  --checkpoints  Session checkpoints")
        console.print("  --databases    Snapshot databases")
        console.print("  --all          Everything")
        console.print("\nUse --help for more info")
        return
    
    # Determine what to clean
    clean_cache = all or cache
    clean_checkpoints = all or checkpoints
    clean_databases = all or databases
    
    # Show what will be cleaned
    items = []
    if clean_cache:
        items.append("• Query cache (.olav/cache/*.db)")
    if clean_checkpoints:
        items.append("• Session checkpoints (.olav/user_checkpoint.db, .olav/.last_thread_id)")
    if clean_databases:
        items.append("• Snapshot databases (raw_outputs, views - keeps devices table)")
    
    console.print("\n[bold yellow]⚠️  The following will be deleted:[/bold yellow]")
    for item in items:
        console.print(f"  {item}")
    console.print()
    
    # Confirmation
    if not force:
        confirm = typer.confirm("Are you sure you want to continue?")
        if not confirm:
            console.print("[cyan]Aborted.[/cyan]")
            return
    
    console.print("\n[cyan]🧹 Cleaning...[/cyan]\n")
    
    # Clean cache
    if clean_cache:
        try:
            from config.paths import CACHE_DIR
            cache_dir = CACHE_DIR
            if cache_dir.exists():
                for db_file in cache_dir.glob("*.db"):
                    db_file.unlink()
                    console.print(f"  ✅ Deleted: {db_file}")
                console.print("  ✅ Cache cleaned")
            else:
                console.print("  ℹ️  No cache directory found")
        except Exception as e:
            console.print(f"  ❌ Cache cleanup failed: {e}")
    
    # Clean checkpoints
    if clean_checkpoints:
        try:
            from config.paths import OLAV_BASE_DIR
            
            checkpoint_file = OLAV_BASE_DIR / "user_checkpoint.db"
            if checkpoint_file.exists():
                checkpoint_file.unlink()
                console.print(f"  ✅ Deleted: {checkpoint_file}")
            
            thread_id_file = OLAV_BASE_DIR / ".last_thread_id"
            if thread_id_file.exists():
                thread_id_file.unlink()
                console.print(f"  ✅ Deleted: {thread_id_file}")
            
            console.print("  ✅ Checkpoints cleaned")
        except Exception as e:
            console.print(f"  ❌ Checkpoint cleanup failed: {e}")
    
    # Clean databases (keep devices table)
    if clean_databases:
        try:
            import duckdb
            from config.paths import UNIFIED_DB
            
            if UNIFIED_DB.exists():
                conn = duckdb.connect(str(UNIFIED_DB))
                
                # Drop raw_outputs
                try:
                    conn.execute("DROP TABLE IF EXISTS raw_outputs")
                    console.print("  ✅ Dropped: raw_outputs table")
                except Exception as e:
                    console.print(f"  ⚠️  Could not drop raw_outputs: {e}")
                
                # Drop all views
                tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='VIEW'").fetchall()
                for (view_name,) in tables:
                    try:
                        conn.execute(f"DROP VIEW IF EXISTS {view_name}")
                        console.print(f"  ✅ Dropped: view {view_name}")
                    except Exception as e:
                        console.print(f"  ⚠️  Could not drop {view_name}: {e}")
                
                conn.close()
                console.print("  ✅ Snapshot data cleaned (devices table preserved)")
            else:
                console.print("  ℹ️  No main database found")
        except Exception as e:
            console.print(f"  ❌ Database cleanup failed: {e}")
    
    console.print("\n[bold green]✅ Cleanup complete![/bold green]\n")


@app.command()
def doctor() -> None:
    """Run system health check and display diagnostics.
    
    Checks:
    - Database connectivity and schema
    - LLM API availability
    - Nornir inventory configuration
    - Network device reachability
    - Cache and checkpoint status
    """
    from config.paths import UNIFIED_DB
    
    console.print("\n[bold cyan]🏥 OLAV System Health Check[/bold cyan]\n")
    
    # Check 1: Database
    console.print("[cyan]1. Database Status[/cyan]")
    try:
        import duckdb
        if not UNIFIED_DB.exists():
            console.print("  ❌ Database not found")
            console.print("     Run: olav snapshot")
        else:
            conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
            
            # Check devices table
            device_count = conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
            console.print(f"  ✅ Devices table: {device_count} devices")
            
            # Check raw_outputs
            try:
                output_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]
                console.print(f"  ✅ Raw outputs: {output_count} records")
            except:
                console.print("  ⚠️  Raw outputs: Table not initialized")
            
            # Check views
            tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='main' AND table_type='VIEW'").fetchall()
            if tables:
                console.print(f"  ✅ Views: {len(tables)} initialized ({', '.join([t[0] for t in tables[:3]])}...)")
            else:
                console.print("  ⚠️  Views: None initialized")
                console.print("     Run: olav snapshot (to create views)")
            
            conn.close()
    except Exception as e:
        console.print(f"  ❌ Database error: {e}")
    
    console.print()
    
    # Check 2: LLM API
    console.print("[cyan]2. LLM API Configuration[/cyan]")
    try:
        from config.settings import settings
        console.print(f"  Provider: {settings.llm_provider}")
        console.print(f"  Model: {settings.llm_model_name}")
        console.print(f"  Base URL: {settings.llm_base_url or 'default'}")
        console.print(f"  API Key: {'✅ Set' if settings.llm_api_key else '❌ Missing'}")
        
        if settings.llm_api_key:
            try:
                from olav.core.llm import LLMFactory
                llm = LLMFactory.get_chat_model()
                console.print("  ✅ LLM API: Ready")
            except Exception as e:
                console.print(f"  ❌ LLM API: {str(e)[:50]}...")
        else:
            console.print("  ❌ Set LLM_API_KEY in .env")
    except Exception as e:
        console.print(f"  ❌ Configuration error: {e}")
    
    console.print()
    
    # Check 3: Nornir Inventory
    console.print("[cyan]3. Nornir Inventory[/cyan]")
    try:
        from olav.shared.tools.network import get_nornir
        nr = get_nornir()
        console.print(f"  ✅ Hosts: {len(nr.inventory.hosts)}")
        console.print(f"  ✅ Groups: {len(nr.inventory.groups)}")
        
        # Show first 3 hosts
        for i, (name, host) in enumerate(list(nr.inventory.hosts.items())[:3]):
            console.print(f"     • {name}: {host.hostname}")
    except Exception as e:
        console.print(f"  ❌ Nornir error: {e}")
    
    console.print()
    
    # Check 4: Network Reachability
    console.print("[cyan]4. Network Connectivity[/cyan]")
    try:
        from olav.shared.tools.network import get_nornir
        import socket
        nr = get_nornir()
        
        reachable = []
        unreachable = []
        
        for name, host in list(nr.inventory.hosts.items())[:5]:  # Test first 5
            try:
                socket.create_connection((host.hostname, 22), timeout=2)
                reachable.append(name)
            except:
                unreachable.append(name)
        
        if reachable:
            console.print(f"  ✅ Reachable: {', '.join(reachable)}")
        if unreachable:
            console.print(f"  ⚠️  Unreachable: {', '.join(unreachable)}")
            console.print("     Check: VPN, firewall, SSH service")
        
        if not reachable and not unreachable:
            console.print("  ℹ️  No devices to test")
    except Exception as e:
        console.print(f"  ⚠️  Connectivity check failed: {e}")
    
    console.print()
    
    # Check 5: Cache Status
    console.print("[cyan]5. Cache & Checkpoints[/cyan]")
    try:
        from config.paths import CACHE_DIR, OLAV_BASE_DIR
        
        cache_dir = CACHE_DIR
        if cache_dir.exists():
            cache_files = list(cache_dir.glob("*.db"))
            total_size = sum(f.stat().st_size for f in cache_files) / 1024 / 1024
            console.print(f"  ✅ Cache: {len(cache_files)} files ({total_size:.1f} MB)")
        else:
            console.print("  ℹ️  Cache: Not initialized")
        
        checkpoint = OLAV_BASE_DIR / "user_checkpoint.db"
        if checkpoint.exists():
            size = checkpoint.stat().st_size / 1024 / 1024
            console.print(f"  ✅ Checkpoint: {size:.1f} MB")
        else:
            console.print("  ℹ️  Checkpoint: Not initialized")
        
        thread_id = OLAV_BASE_DIR / ".last_thread_id"
        if thread_id.exists():
            tid = thread_id.read_text().strip()[:16]
            console.print(f"  ✅ Last session: {tid}...")
    except Exception as e:
        console.print(f"  ⚠️  Cache check failed: {e}")
    
    console.print("\n[bold green]✅ Health check complete![/bold green]\n")


@app.command()
def init(
    group: str = typer.Option(
        None,
        "--group",
        "-g",
        help="Nornir group to initialize (defaults to NORNIR_DEFAULT_GROUP in settings)",
    ),
    devices: str = typer.Option(
        "all", "--devices", "-d", help="Devices to initialize (comma-separated or 'all')"
    ),
    diagnose: bool = typer.Option(
        True, "--diagnose/--no-diagnose", help="Show detailed diagnostic information"
    ),
) -> None:
    """Initialize OLAV database with network device snapshot and diagnostics.

    First-time setup: Captures network device state, initializes database views,
    and verifies all systems are working.

    Examples:
        olav init                    # Initialize all devices with full diagnostics
        olav init --group production # Initialize production group only
        olav init --devices R1,R2    # Initialize specific devices
        olav init --no-diagnose      # Skip diagnostic output (automated)
    """
    import os

    # Load settings to get default group
    from config.settings import settings
    from olav.shared.tools.sync_tools import sync_all

    # Use provided group or fall back to settings default
    if group is None:
        group = settings.nornir_default_group

    # Set CLI mode flag for sync_tools to wait for Stage 2
    os.environ["OLAV_CLI_MODE"] = "1"

    console.print(
        Panel(
            f"[bold cyan]Initializing OLAV Database[/bold cyan]\n"
            f"Group: {group}\nDevices: {devices}",
            border_style="cyan",
        )
    )

    # Pre-flight diagnostics
    if diagnose:
        console.print("\n[cyan]🔍 Running pre-flight diagnostics...[/cyan]")
        
        from config.paths import UNIFIED_DB
        
        # Check 1: Database connectivity
        try:
            import duckdb
            conn = duckdb.connect(str(UNIFIED_DB))
            device_count = conn.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
            conn.close()
            console.print(f"  ✅ Database: Connected ({device_count} devices registered)")
        except Exception as e:
            console.print(f"  ⚠️  Database: {str(e)}")
        
        # Check 2: LLM API availability
        try:
            from olav.core.llm import LLMFactory
            llm = LLMFactory.get_chat_model()
            console.print(f"  ✅ LLM API: {settings.llm_provider}/{settings.llm_model_name}")
        except Exception as e:
            console.print(f"  ❌ LLM API: {str(e)}")
        
        # Check 3: Nornir inventory
        try:
            from olav.shared.tools.network import get_nornir
            nr = get_nornir()
            console.print(f"  ✅ Nornir: {len(nr.inventory.hosts)} hosts configured")
        except Exception as e:
            console.print(f"  ❌ Nornir: {str(e)}")
        
        # Check 4: Network connectivity preview
        try:
            from olav.shared.tools.network import get_nornir
            nr = get_nornir()
            reachable = 0
            for host in list(nr.inventory.hosts.values())[:3]:  # Test first 3
                try:
                    import socket
                    socket.create_connection((host.hostname, 22), timeout=2)
                    reachable += 1
                except:
                    pass
            if reachable > 0:
                console.print(f"  ✅ Network: {reachable}/3 sample devices reachable")
            else:
                console.print(f"  ⚠️  Network: No devices reachable (may need VPN)")
        except Exception as e:
            console.print(f"  ⚠️  Network: {str(e)}")
        
        console.print()

    try:
        # Parse devices parameter: convert comma-separated string to list
        device_list = None if devices == "all" else [d.strip() for d in devices.split(",")]

        # sync_all is a StructuredTool, use .invoke() to call it
        result = sync_all.invoke({"devices": device_list})  # type: ignore[attr-defined]

        console.print(
            Panel(result, title="[bold green]✅ Initialization Complete[/bold green]", border_style="green")
        )
        
        # Post-snapshot diagnostics
        if diagnose:
            console.print("\n[cyan]📊 Post-initialization status:[/cyan]")
            try:
                import duckdb
                from config.paths import UNIFIED_DB
                
                conn = duckdb.connect(str(UNIFIED_DB), read_only=True)
                
                # Check raw_outputs
                raw_count = conn.execute('SELECT COUNT(*) FROM raw_outputs').fetchone()[0]
                console.print(f"  📝 Raw outputs: {raw_count} records")
                
                # Check if views exist
                tables = conn.execute("SELECT table_name, table_type FROM information_schema.tables WHERE table_schema='main'").fetchall()
                view_count = sum(1 for _, type in tables if type == 'VIEW')
                console.print(f"  📊 Database views: {view_count} initialized")
                
                if view_count == 0:
                    console.print("  💡 Tip: Run 'olav database init-views' to create query views")
                
                conn.close()
            except Exception as e:
                console.print(f"  ⚠️  Status check failed: {str(e)}")
            
            console.print()
        
    except Exception as e:
        console.print(f"[bold red]❌ Initialization Error: {str(e)}[/bold red]")
        if "connection" in str(e).lower():
            console.print("\n💡 Troubleshooting:")
            console.print("  • Check device IP addresses in inventory")
            console.print("  • Verify SSH credentials")
            console.print("  • Ensure network connectivity (VPN if needed)")
        elif "api" in str(e).lower() or "key" in str(e).lower():
            console.print("\n💡 Troubleshooting:")
            console.print("  • Check LLM_API_KEY in .env")
            console.print("  • Verify API provider is accessible")
        raise typer.Exit(1) from None


@app.command()
def inspect(
    test: bool = typer.Option(
        False, "--test", "-t", help="Run in test mode (no snapshot, mock LLM)"
    ),
    refresh: bool = typer.Option(
        False, "--refresh", "-r", help="Force a new snapshot before inspection"
    ),
    group: str = typer.Option(None, "--group", "-g", help="Group filter (Nornir)"),
    device: str = typer.Option(None, "--device", "-d", help="Device filter (Nornir)"),
    date: str = typer.Option(None, "--date", help="Inspect data from a specific date (YYYY-MM-DD)"),
) -> None:
    """Run Skill-Centric Agentic Inspection.

    Examples:
        olav inspect             # Use latest snapshot
        olav inspect --test      # Fast test mode
        olav inspect --refresh   # Snapshot then inspect
        olav inspect --group test # Filter by group
    """
    import asyncio

    from olav.agents.inspector import InspectionOrchestrator

    console.print(
        Panel("[bold cyan]Starting Agentic Network Inspection[/bold cyan]", border_style="cyan")
    )

    try:
        if refresh:
            from olav.shared.tools.sync_tools import sync_all

            console.print("🔄 Refreshing snapshot data...")
            sync_all.invoke({"devices": device or group})  # Pass filter to sync_all

        # Phase 15: Resolve Nornir filters to device list
        device_list = None
        if device or group or test:
            from olav.shared.tools.network import get_nornir

            nr = get_nornir()
            matched_devices = []

            # Simple manual filtering for robustness
            for name, host in nr.inventory.hosts.items():
                # Check group
                group_match = True
                if group:
                    host_groups = [g.name if hasattr(g, "name") else str(g) for g in host.groups]
                    if group not in host_groups:
                        group_match = False

                # Check device
                device_match = True
                if device:
                    target_devices = [d.strip() for d in device.split(",")]
                    if name not in target_devices:
                        device_match = False

                if group_match and device_match:
                    matched_devices.append(name)

            device_list = matched_devices

            if not device_list:
                console.print(
                    f"[yellow]⚠️  No devices found matching filter (group={group}, device={device})[/yellow]"
                )
                raise typer.Exit(0)

        # Run async inspection
        orchestrator = InspectionOrchestrator()
        inspection_type = "scheduled" if "cronjob" in str(test) else "manual"
        report = asyncio.run(
            orchestrator.run_inspection(
                test_mode=test, device_filter=device_list, inspection_type=inspection_type
            )
        )

        console.print(Panel("[bold green]Inspection Complete[/bold green]", border_style="green"))

        # Display report location
        from config.paths import REPORTS_DIR

        console.print(f"📄 Report saved to: [bold]{REPORTS_DIR}/latest.md[/bold]")

        # Optionally print the summary part of the report
        if "\n## " in report:
            summary = report.split("\n## ")[0] + "\n## " + report.split("\n## ")[1]
            console.print(Panel(summary, title="Report Summary", border_style="blue"))

    except Exception as e:
        console.print(f"[bold red]❌ Inspection Error: {str(e)}[/bold red]")
        raise typer.Exit(1) from None


@app.callback(invoke_without_command=True)
def interactive_mode(
    ctx: typer.Context,
    thread_id: str = typer.Option(
        None,
        "--thread-id",
        "-t",
        help="Resume session with specific thread ID (for testing context/memory)",
    ),
    resume: bool = typer.Option(
        False,
        "--resume",
        "-r",
        help="Resume last session (loads previous thread_id)",
    ),
) -> None:
    """Start interactive OLAV session (default when no command given).
    
    Examples:
        olav                           # New session with random thread_id
        olav --thread-id abc123        # Resume session 'abc123'
        olav --resume                  # Resume last session
    """
    # If a subcommand was invoked, skip interactive mode
    if ctx.invoked_subcommand is not None:
        return

    # Import heavy modules only when needed
    from olav.cli.display import display_banner, load_banner_from_config
    from olav.cli.session import OlavPromptSession

    is_interactive = sys.stdin.isatty()

    try:
        if is_interactive:
            console.print("\n" + "=" * 60)
            console.print("💬 OLAV Interactive CLI - v0.9.6")
            console.print("=" * 60)
            console.print("[dim]Session ID saved. Use 'olav --resume' to continue this conversation.[/dim]\n")

        # Create CLI session (checkpointer manages state)

        # Create CLI session (history_file handled by session.py via USER_HISTORY_PATH)
        try:
            session = OlavPromptSession(
                enable_completion=is_interactive,
                multiline=False,
            )
        except Exception as e:
            console.print(f"[yellow]⚠️ Warning: {e}[/yellow]")
            session = OlavPromptSession(
                enable_completion=False,
                multiline=False,
            )

        # Display banner
        if is_interactive:
            banner_text = load_banner_from_config()
            if banner_text:
                display_banner(banner_text)

        # All queries route through Orchestrator (created per-query in the loop).
        # The `agent` parameter is kept for backward compatibility with
        # execute_command() but is no longer the primary execution path.
        agent = None

        # Run interactive loop (async mode for proper event loop handling)
        asyncio.run(run_interactive_loop_async(session, agent, resume=resume, thread_id=thread_id))
        # Note: History is auto-saved by FileHistory, session state by checkpointer

    except KeyboardInterrupt:
        console.print("\n\n👋 Interrupted. Goodbye!")
        sys.exit(0)
    except Exception as e:
        import traceback
        console.print(f"[bold red]❌ Fatal error: {e}[/bold red]")
        logger.error(f"Full traceback:\n{traceback.format_exc()}")
        raise typer.Exit(1) from None


def main() -> None:
    """Main entry point for OLAV CLI."""
    # Initialize logging
    from config.logging import setup_logging
    from config.settings import settings

    log_level = settings.log_level if hasattr(settings, "log_level") else "INFO"
    setup_logging(log_level=log_level)

    # P5.2: Schema initialization removed (manager was unused in v0.11.1+)

    # P1: Lazy-load SkillConfig to improve startup time (moved to first use)
    # SkillConfig will be initialized when first needed by agents
    # This reduces startup time from ~5s to ~1-2s

    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
