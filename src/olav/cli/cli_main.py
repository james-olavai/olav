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
from collections.abc import Callable
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
        todos = state.values.get("todos", []) if state and hasattr(state, "values") else []

        if not todos:
            return

        table = Table(show_header=True, header_style="bold magenta", border_style="blue")
        table.add_column("ID", style="dim", width=4)
        table.add_column("Status", width=15)
        table.add_column("Task", min_width=30)

        status_icons = {
            "not-started": "⬜",
            "in-progress": "🔄",
            "completed": "✅"
        }

        for todo in todos:
            icon = status_icons.get(todo.get("status", "not-started"), "⬜")
            table.add_row(
                str(todo.get("id", "")),
                f"{icon} {todo.get('status', 'not-started')}",
                todo.get("title", "")
            )

        panel = Panel(table, title="📋 Task Progress", border_style="blue")
        console.print(panel)
    except Exception as e:
        logger.debug(f"Could not display todos: {e}")


async def stream_agent_response(
    agent: Any,
    inputs: dict[str, Any] | list[dict[str, Any]],
    verbose: bool = False,
    learn_callback: "Callable[[str], str | None] | None" = None,
    thread_id: str | None = None,  # LangGraph thread_id for session
    timeout: float = 60.0,  # Query timeout in seconds
) -> str:
    """Stream agent response with timeout and session support.

    Args:
        agent: OLAV agent instance (CompiledGraph)
        inputs: Input dict
        verbose: Show reasoning process
        learn_callback: Optional callback for interactive alias learning
        thread_id: Session thread_id for checkpointer
        timeout: Query timeout in seconds

    Returns:
        Final result string
    """
    import asyncio

    from olav.cli.display import StreamingDisplay

    # P8 Enhancement: Always enable streaming for better responsiveness
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
        display.show_processing_status("Generating SQL and querying...")

    try:
        # Use ainvoke with timeout
        final_state = await asyncio.wait_for(
            agent.ainvoke(base_inputs, config=config, learn_callback=learn_callback),
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
            # P10: Ensure result is displayed even if it's a string JSON
            # Only use Rich display for TTY, use plain output for piped
            if is_tty:
                display.show_json_table(result)

            # P10 Fix: Ensure output is flushed to stdout when piped (bypassing Rich/print stack)
            if not is_tty:
                # If it's a complex object (Table), print it as JSON string for parsability
                val_to_print = str(result)
                if isinstance(result, (dict, list)):
                    import json

                    val_to_print = json.dumps(result, ensure_ascii=False)

                # Use os.write to guarantee output to stdout (fd 1) even if Python buffers/redirects
                import os

                os.write(1, (val_to_print + "\n").encode())

            if is_tty:
                print()  # Final newline for prompt-toolkit
            return str(result)

        # If no structured result, but we have text content (explanation), show that
        if last_message_content and not result:
            display.show_result(last_message_content, markdown=True)
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


def _create_learning_callback(session: "OlavPromptSession") -> Callable[[str], str | None]:
    """Create a callback function for interactive alias learning.

    Args:
        session: OlavPromptSession instance for user interaction

    Returns:
        Callback function that prompts user and returns canonical form
    """

    def learn_alias(entity: str) -> str | None:
        """Prompt user to teach the meaning of an unknown entity.

        Args:
            entity: The unknown entity (e.g., "核心路由器")

        Returns:
            Canonical form (e.g., "R1,R2,R3") or None if user declines
        """
        try:
            # Prompt user with context
            prompt_msg = f"\n🎓 Learning: I don't know '{entity}'. Which devices do you mean?\n"
            prompt_msg += "  Enter device names (comma-separated), or press Enter to skip: "

            # Use input() fallback since callback context cannot be async
            # TODO: Consider moving learning to main loop for proper async handling
            user_response = input(prompt_msg)

            if not user_response or not user_response.strip():
                print(f"  ⏭️  Skipped learning '{entity}'")
                return None

            # Validate response (basic check for device-like patterns)
            response = user_response.strip()

            # Confirm with user
            confirm_msg = f"  ✅ Learned: '{entity}' = '{response}'. Got it!\n"
            print(confirm_msg)

            return response

        except (EOFError, KeyboardInterrupt):
            print(f"  ⏭️  Skipped learning '{entity}' (interrupted)")
            return None
        except Exception as e:
            logger.warning(f"Learning callback error: {e}")
            return None

    return learn_alias


async def run_interactive_loop_async(
    session: "OlavPromptSession",
    agent: Any,
) -> None:
    """Run the OLAV CLI (asynchronous version for proper event loop handling).

    Args:
        session: Prompt session
        agent: OLAV agent instance (with checkpointer for state management)
    """
    import uuid

    from config.settings import settings
    from olav.agents.query_agent_v2 import QueryAgentV2
    from olav.cli.commands import execute_command
    from olav.cli.input_parser import parse_input
    from olav.core.query_router import QueryRouter

    # Generate session thread_id for checkpointer
    thread_id = str(uuid.uuid4())
    logger.debug(f"Starting interactive session with thread_id: {thread_id}")

    # Initialize QueryRouter and Display
    is_tty = sys.stdin.isatty()
    from olav.cli.display import StreamingDisplay

    display = StreamingDisplay(
        console=console, verbose=False, show_spinner=is_tty, quiet=not is_tty
    )

    try:
        from config.paths import ROUTING_RULES_PATH

        router = QueryRouter(ROUTING_RULES_PATH)
        if is_tty:
            print("✅ QueryRouter initialized")
    except FileNotFoundError:
        router = None
        if is_tty:
            print("⚠️  QueryRouter config not found, using default routing")
    
    # Display cache metrics on startup (TTY only)
    if is_tty:
        try:
            from olav.cache import cache
            metrics = cache.get_cache_metrics()
            intent = metrics['intent']
            if intent['total_entries'] > 0:
                print(f"📊 Cache: {intent['total_entries']} entries, "
                      f"{intent['total_hits']} hits, "
                      f"hit rate {intent['hit_rate_pct']}%")
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
            # QueryRouter: Route user input before processing
            # =========================================================================
            if router:
                routing_decision = router.route(user_input)

                # Handle Guard rejections
                if routing_decision.action == "reject":
                    print(f"🚫 {routing_decision.message}")
                    continue

                # Handle approval requirements
                if routing_decision.action == "require_approval":
                    print(f"⚠️  {routing_decision.message}")
                    confirm = await session.prompt_async("Continue? (yes/no): ")
                    if confirm.lower() not in ["yes", "y"]:
                        print("❌ Cancelled")
                        continue

                # Log routing decision for debugging (if verbose)
                if settings.display_thinking and is_tty:
                    print(f"🎯 Route: {routing_decision.expert} -> {routing_decision.tool}")

                # Fast-Path: Direct tool execution if tool and params are provided
                if (
                    routing_decision.expert == "database"
                    and routing_decision.tool
                    and routing_decision.params
                ):
                    # Look for the tool in the agent's scripts/skills
                    # For simplicity, we can use the agent's existing tool runners if possible
                    # or call the SkillAdapter directly.
                    try:
                        from olav.core.skill_adapter import SkillAdapter
                        from olav.core.skill_loader import get_skill_loader

                        loader = get_skill_loader()
                        skill = loader.get_skill("network-query")

                        # Find the tool in the skill
                        tool_def = next(
                            (
                                t
                                for t in skill.frontmatter.get("tools", [])
                                if t["name"] == routing_decision.tool
                            ),
                            None,
                        )

                        if tool_def:
                            display.show_processing_status(
                                f"⚡ Fast-Path: Executing {routing_decision.tool}..."
                            )
                            # Get skill directory for relative path resolution
                            from pathlib import Path

                            skill_file = Path(skill.file_path)
                            skill_dir = skill_file.parent if skill_file.is_file() else skill_file

                            executor = SkillAdapter._create_executor(
                                tool_def["script"], skill_dir=skill_dir
                            )
                            result = executor(**routing_decision.params)
                            display.stop_processing_status()

                            # Standardize result check (handle both 'data' and 'results' keys)
                            tool_data = result.get("data") or result.get("results")
                            has_data = (
                                tool_data is not None and len(tool_data) > 0
                                if isinstance(tool_data, (list, dict))
                                else tool_data is not None
                            )

                            if not has_data:
                                if is_tty:
                                    print(
                                        "📊 Database lookup yielded no results. Falling back to Agent analysis..."
                                    )
                                # Do NOT continue; fall through to normal agent query
                            else:
                                # ============ 命令历史记录 ============
                                # 记录 Fast-Path 或白名单命令执行到命令历史
                                # 支持后续 tab 补全和命令重现

                                # 提取信息
                                command_used = routing_decision.tool if routing_decision else ""
                                device_queried = (
                                    routing_decision.params.get("device")
                                    if routing_decision and routing_decision.params
                                    else ""
                                )
                                sql_used = (
                                    tool_data.get("sql_query")
                                    if routing_decision
                                    and routing_decision.tool == "query_database"
                                    and isinstance(tool_data, dict)
                                    else ""
                                )

                                # 记录到历史
                                session.record_query(
                                    query=user_input,
                                    command_used=command_used or "",
                                    device=device_queried or "",
                                    sql_query=sql_used or "",
                                )

                                # Note: Session history auto-persisted by FileHistory + checkpointer

                                # Check if it's a semantic tier hit (Tier 0 or Tier 1)
                                is_semantic = routing_decision.message and (
                                    "Tier 0" in routing_decision.message
                                    or "Tier 1" in routing_decision.message
                                )

                                if is_semantic:
                                    # Add data source indicator before synthesis
                                    if routing_decision.tool == "query_database":
                                        snapshot_time = _get_snapshot_time()
                                        display.show_data_source_indicator(
                                            "sql", snapshot_time=snapshot_time
                                        )
                                    elif routing_decision.tool == "smart_query":
                                        device = (
                                            routing_decision.params.get("device")
                                            if routing_decision.params
                                            else None
                                        )
                                        display.show_data_source_indicator("cli", device=device)

                                    display.show_processing_status("🤔 Synthesizing response...")
                                    if hasattr(agent, "synthesis"):
                                        synthesis_output = await agent.synthesis(
                                            user_input, tool_data
                                        )
                                        display.stop_processing_status()
                                        display.show_result(
                                            synthesis_output, end="\n"
                                        )  # Ensure newline
                                        continue
                                    else:
                                        display.stop_processing_status()

                                # Fallback to standard result display (for regex-matched fast-path)
                                # Add data source indicator
                                if routing_decision.tool == "query_database":
                                    # SQL database source
                                    snapshot_time = _get_snapshot_time()
                                    display.show_data_source_indicator(
                                        "sql", snapshot_time=snapshot_time
                                    )
                                elif routing_decision.tool == "smart_query":
                                    # CLI live query source
                                    device = (
                                        routing_decision.params.get("device")
                                        if routing_decision.params
                                        else None
                                    )
                                    display.show_data_source_indicator("cli", device=device)
                                else:
                                    # Unknown source
                                    display.show_data_source_indicator("unknown")

                                display.show_result(
                                    f"✅ Fast-Path Result for {routing_decision.tool}:"
                                )
                                if isinstance(tool_data, (list, dict)):
                                    display.show_json_table(tool_data)
                                else:
                                    display.show_result(str(tool_data), end="\n")

                                continue  # Skip the agent loop
                    except Exception as e:
                        display.stop_processing_status()
                        display.show_error(f"Fast-path execution failed: {e}")
                        # Fall through to normal agent query

            # Check for slash commands first
            if user_input.startswith("/"):
                try:
                    # Run async command handler with await
                    result = await execute_command(
                        user_input,
                        agent=agent,
                    )
                    if result:
                        # Check if result should be sent to Agent
                        if result.startswith("AGENT_PROMPT::"):
                            # Extract prompt and send to Agent
                            agent_prompt = result[len("AGENT_PROMPT::") :]
                            print("🤖 Sending to Agent for analysis...\n")
                            # Checkpointer automatically manages history
                            use_verbose = settings.display_thinking
                            inputs = {
                                "messages": [{"role": "user", "content": agent_prompt}],
                                "retry_count": 0,
                            }
                            output = await stream_agent_response(
                                agent, inputs, verbose=use_verbose, thread_id=thread_id
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
                    result = subprocess.run(
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
                # Checkpointer will retrieve conversation history automatically
                agent_messages = [{"role": "user", "content": processed_text}]

                # Phase 17: Resolve Expert Skill (Federated Specialists)
                skill_name = "network-query"
                if router and routing_decision.expert:
                    expert_cfg = router.get_expert_config(routing_decision.expert)
                    skill_name = expert_cfg.get("skill", skill_name)

                # Initialize Query Agent V2 with specific skill
                agent = QueryAgentV2(enable_summarization=False, skill_name=skill_name)

                # === NEW: Create learning callback ===
                # Only enable interactive learning in TTY mode
                learn_callback = _create_learning_callback(session) if is_tty else None

                # Use verbose mode only if DISPLAY_THINKING=true
                use_verbose = settings.display_thinking
                inputs = {"messages": agent_messages, "retry_count": 0}

                # Use await instead of asyncio.run() to properly handle async context
                output = await stream_agent_response(
                    agent,
                    inputs,
                    verbose=use_verbose,
                    learn_callback=learn_callback,
                    thread_id=thread_id,  # Session thread_id
                )

                if output:
                    # Display todos if present in agent state
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
) -> None:
    """Execute a single network operations query.

    Examples:
        olav query "查看 R1 的接口状态"
        olav query "R1 的 BGP 邻居" --debug
        olav query "Check R2 BGP" --verbose
    """
    from olav.agents.query_agent_v2 import QueryAgentV2
    from olav.cli.display import StreamingDisplay

    display = StreamingDisplay(console=console, verbose=verbose, show_spinner=not verbose)

    console.print(Panel(f"[bold cyan]Query[/bold cyan]: {query_text}", border_style="cyan"))

    try:
        if not verbose:
            display.show_processing_status("Processing query...")

        import asyncio

        # Phase 17: Intent Routing for single query
        from olav.core.query_router import QueryRouter

        router = QueryRouter()
        routing_decision = router.route(query_text)

        skill_name = "network-query"
        if routing_decision.expert:
            expert_cfg = router.get_expert_config(routing_decision.expert)
            skill_name = expert_cfg.get("skill", skill_name)

        # Initialize QueryAgentV2 with routed skill
        agent = QueryAgentV2(enable_summarization=False, skill_name=skill_name)

        # Execute query
        result = asyncio.run(agent.query(query_text))

        display.stop_processing_status()

        # Handle result
        if result["status"] == "success":
            console.print(f"\n[bold green]✓[/bold green] {result['output']}\n")
        elif result["status"] == "not_implemented":
            console.print(f"\n[bold yellow]⚠[/bold yellow] {result['message']}\n")
        else:
            console.print(
                f"\n[bold red]❌ Error:[/bold red] {result.get('error', 'Unknown error')}\n"
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
    from olav.tools.network import list_devices as nornir_list_devices_tool

    console.print("[bold cyan]Loading network devices...[/bold cyan]")
    try:
        # The @tool decorator wraps the function, so we need to call it via the tool's func attribute
        # or directly use the underlying function
        result = nornir_list_devices_tool.func()  # type: ignore[call-arg]
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
def snapshot(
    group: str = typer.Option(
        None,
        "--group",
        "-g",
        help="Nornir group to snapshot (defaults to NORNIR_DEFAULT_GROUP in settings)",
    ),
    devices: str = typer.Option(
        "all", "--devices", "-d", help="Devices to snapshot (comma-separated or 'all')"
    ),
) -> None:
    """Capture network device state snapshot (Stage 1: collect, Stage 2: parse+analyze).

    Examples:
        olav snapshot                    # Snapshot all devices in configured default group
        olav snapshot --group production # Snapshot production group
        olav snapshot --devices R1,R2    # Snapshot specific devices
    """
    import os

    # Load settings to get default group
    from config.settings import settings
    from olav.tools.sync_tools import sync_all

    # Use provided group or fall back to settings default
    if group is None:
        group = settings.nornir_default_group

    # Set CLI mode flag for sync_tools to wait for Stage 2
    os.environ["OLAV_CLI_MODE"] = "1"

    console.print(
        Panel(
            f"[bold cyan]Capturing Network Snapshot[/bold cyan]\n"
            f"Group: {group}\nDevices: {devices}",
            border_style="cyan",
        )
    )

    try:
        # Parse devices parameter: convert comma-separated string to list
        device_list = None if devices == "all" else [d.strip() for d in devices.split(",")]

        # sync_all is a StructuredTool, use .invoke() to call it
        result = sync_all.invoke({"devices": device_list})  # type: ignore[attr-defined]

        console.print(
            Panel(result, title="[bold green]Snapshot Complete[/bold green]", border_style="green")
        )
    except Exception as e:
        console.print(f"[bold red]❌ Snapshot Error: {str(e)}[/bold red]")
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
            from olav.tools.sync_tools import sync_all

            console.print("🔄 Refreshing snapshot data...")
            sync_all.invoke({"devices": device or group})  # Pass filter to sync_all

        # Phase 15: Resolve Nornir filters to device list
        device_list = None
        if device or group or test:
            from olav.tools.network import get_nornir

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
def interactive_mode(ctx: typer.Context) -> None:
    """Start interactive OLAV session (default when no command given)."""
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
            console.print("=" * 60 + "\n")

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

        # Phase 17: Federated Specialists - Initial agent is a Router
        from olav.agents.query_agent_v2 import QueryAgentV2

        # Note: In interactive loop, we re-initialize the agent per query
        # or use the Router to select. For now, we pass a dummy or None
        # and let the loop handle it.
        agent = QueryAgentV2(enable_summarization=False)

        # Run interactive loop (async mode for proper event loop handling)
        asyncio.run(run_interactive_loop_async(session, agent))
        # Note: History is auto-saved by FileHistory, session state by checkpointer

    except KeyboardInterrupt:
        console.print("\n\n👋 Interrupted. Goodbye!")
        sys.exit(0)
    except Exception as e:
        console.print(f"[bold red]❌ Fatal error: {e}[/bold red]")
        raise typer.Exit(1) from None


def main() -> None:
    """Main entry point for OLAV CLI."""
    # Initialize logging
    from config.logging import setup_logging
    from config.settings import settings

    log_level = settings.log_level if hasattr(settings, "log_level") else "INFO"
    setup_logging(log_level=log_level)

    # P1: Initialize SkillConfig at startup for better performance
    from olav.core.skill_config import SkillConfig
    SkillConfig.initialize()

    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
