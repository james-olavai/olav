#!/usr/bin/env python3
"""OLAV v0.10.0 CLI - Full deepagents-cli integration.

This is a thin wrapper around deepagents-cli for network operations.
All domain functionality is exposed through workspace agents and tools, not CLI commands.

Usage:
    olav                                    # Interactive mode
    olav "How many devices?"               # Single query
    olav --agent ops "Check network"       # Multi-agent
    olav --sandbox modal "Deploy config"   # Remote execution
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

VERSION = "0.10.0"
OLAV_ASCII = """
  ██████╗  ██████╗  ██╗  ██╗  █████╗ 
 ██╔════╝ ██╔═══██╗ ██║  ██║ ██╔══██╗
 ██║      ██║   ██║ ███████║ ███████║
 ██║      ██║   ██║ ██╔══██║ ██╔══██║
 ╚██████╗ ╚██████╔╝ ██║  ██║ ██║  ██║
  ╚═════╝  ╚═════╝  ╚═╝  ╚═╝ ╚═╝  ╚═╝
         Network Operations AI
"""


def parse_args():
    """Parse command line arguments - deepagents-cli compatible."""
    parser = argparse.ArgumentParser(
        prog="olav",
        description=f"OLAV v{VERSION} - Network Operations AI Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # List agents command
    subparsers.add_parser("list", help="List all available agents")

    # Help command
    subparsers.add_parser("help", help="Show help information")

    # Admin command
    admin_parser = subparsers.add_parser("admin", help="Admin commands (status, backup, etc.)")
    admin_parser.add_argument("args", nargs="*", help="Admin command arguments")

    # Config command
    config_parser = subparsers.add_parser("config", help="Configuration commands")
    config_parser.add_argument("args", nargs="*", help="Config command arguments")

    # Default interactive mode flags
    parser.add_argument(
        "--agent",
        default="olav",
        help="Agent identifier for separate memory stores (default: olav)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables HITL)",
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "modal", "daytona", "runloop"],
        default="none",
        help="Remote sandbox for code execution (default: none - local only)",
    )
    parser.add_argument(
        "--sandbox-id",
        help="Existing sandbox ID to reuse (skips creation and cleanup)",
    )
    parser.add_argument(
        "--sandbox-setup",
        help="Path to setup script to run in sandbox after creation",
    )
    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Disable the startup splash screen",
    )
    parser.add_argument("--version", "-V", action="version", version=f"OLAV v{VERSION}")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose output")
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")

    # Single positional argument for query
    parser.add_argument(
        "query",
        nargs="?",
        help="Natural language query (starts interactive mode if omitted)",
    )

    return parser.parse_args()


def check_dependencies() -> None:
    """Check if required dependencies are installed."""
    missing = []

    try:
        import rich
    except ImportError:
        missing.append("rich")

    try:
        import prompt_toolkit
    except ImportError:
        missing.append("prompt-toolkit")

    try:
        import dotenv
    except ImportError:
        missing.append("python-dotenv")

    if missing:
        console.print("\n[bold red]Missing required dependencies![/bold red]")
        console.print("\nThe following packages are required:")
        for pkg in missing:
            console.print(f"  - {pkg}")
        console.print("\nInstall with: [bold]uv sync[/bold]")
        sys.exit(1)


def create_olav_agent_with_backend(
    assistant_id: str, sandbox=None, sandbox_type: str | None = None
):
    """Create OLAV agent with CompositeBackend.

    This integrates OLAV's domain-specific agent with deepagents infrastructure.

    Args:
        assistant_id: Agent identifier for memory storage
        sandbox: Optional sandbox backend for remote execution
        sandbox_type: Type of sandbox ("modal", "runloop", "daytona")

    Returns:
        Tuple of (agent graph, composite backend)
    """
    from deepagents import create_deep_agent
    from deepagents.backends import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend

    from config.settings import settings
    from olav.agents.agent import OLAVAgent

    # Create OLAV agent (which uses create_deep_agent internally)
    olav_agent = OLAVAgent(
        enable_checkpointer=True,
        enable_store=True,
    )

    # Create backend
    if sandbox is None:
        # Local mode - use filesystem backend
        composite_backend = CompositeBackend(
            default=FilesystemBackend(),
            routes={},
        )
    else:
        # Remote sandbox mode
        composite_backend = CompositeBackend(
            default=sandbox,
            routes={},
        )

    # Return the graph and backend
    return olav_agent.graph, composite_backend


def get_system_prompt(assistant_id: str, sandbox_type: str | None = None) -> str:
    """Get the system prompt for OLAV agent."""
    cwd = Path.cwd()
    agent_dir = f"~/.deepagents/{assistant_id}"

    if sandbox_type:
        from deepagents_cli.integrations.sandbox_factory import get_default_working_dir

        working_dir = get_default_working_dir(sandbox_type)
        working_dir_section = f"""### Current Working Directory

You are operating in a **remote Linux sandbox** at `{working_dir}`.

All code execution and file operations happen in this sandbox environment.
"""
    else:
        working_dir_section = f"""<env>
Working directory: {cwd}
</env>

### Current Working Directory

The filesystem backend is currently operating in: `{cwd}`

### File System and Paths

**IMPORTANT - Path Handling:**
- All file paths must be absolute paths (e.g., `{cwd}/file.txt`)
- Use the working directory from <env> to construct absolute paths
"""

    return (
        working_dir_section
        + f"""### Agents & Skills Directory

Your agents and their skills are defined in: `{agent_dir}/workspace/`

### Network Operations Domain

You are OLAV, a Network Operations AI Assistant. You help with:
- Querying network device data from DuckDB
- Executing CLI commands on network devices via Nornir
- Managing network snapshots and configurations
- Scheduling inspection tasks

### Human-in-the-Loop Tool Approval

Some tool calls require user approval before execution. When a tool call is rejected:
1. Accept the decision immediately - do NOT retry the same command
2. Explain that you understand they rejected the action
3. Suggest an alternative approach or ask for clarification

### Todo List Management

When using write_todos:
1. Keep the list MINIMAL - aim for 3-6 items maximum
2. Only create todos for complex, multi-step tasks
3. For simple tasks (1-2 steps), just do them directly
4. Update status promptly as you complete each item
"""
    )


async def simple_cli(
    agent,
    assistant_id: str,
    session_state,
    backend,
    sandbox_type: str | None = None,
    no_splash: bool = False,
) -> None:
    """Main CLI loop using deepagents-cli components."""
    from deepagents_cli.config import COLORS
    from deepagents_cli.execution import execute_task
    from deepagents_cli.input import create_prompt_session
    from deepagents_cli.ui import TokenTracker

    # Show splash
    if not no_splash:
        console.print(OLAV_ASCII, style=f"bold {COLORS['primary']}")
        console.print()

    # Show working directory
    console.print("[dim]OLAV v{} - Network Operations AI Assistant[/dim]".format(VERSION))
    console.print(f"[dim]Working directory: {Path.cwd()}[/dim]")
    console.print()

    if session_state.auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()

    # Show key bindings
    if sys.platform == "darwin":
        tips = (
            "  Tips: ⏎ Enter to submit, ⌥ Option + ⏎ Enter for newline, "
            "⌃E to open editor, ⌃T to toggle auto-approve, ⌃C to exit"
        )
    else:
        tips = (
            "  Tips: Enter to submit, Alt+Enter for newline, "
            "Ctrl+E to open editor, Ctrl+T to toggle auto-approve, Ctrl+C to exit"
        )
    console.print(tips, style=f"dim {COLORS['dim']}")
    console.print()

    # Create prompt session and token tracker
    session = create_prompt_session(assistant_id, session_state)
    token_tracker = TokenTracker()

    while True:
        try:
            user_input = await session.prompt_async()
            if session_state.exit_hint_handle:
                session_state.exit_hint_handle.cancel()
                session_state.exit_hint_handle = None
            session_state.exit_hint_until = None
            user_input = user_input.strip()
        except EOFError:
            break
        except KeyboardInterrupt:
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        if not user_input:
            continue

        # Check for quit keywords
        if user_input.lower() in ["quit", "exit", "q"]:
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        # Execute task
        await execute_task(
            user_input,
            agent,
            assistant_id,
            session_state,
            token_tracker,
            backend=backend,
        )


async def run_interactive(assistant_id: str, session_state, sandbox_type: str = "none") -> None:
    """Run interactive mode."""
    agent, backend = create_olav_agent_with_backend(assistant_id)

    await simple_cli(
        agent,
        assistant_id,
        session_state,
        backend,
        sandbox_type=sandbox_type if sandbox_type != "none" else None,
        no_splash=session_state.no_splash,
    )


async def run_single_query(query: str, assistant_id: str) -> None:
    """Run a single query and exit."""
    from deepagents_cli.config import COLORS
    from deepagents_cli.execution import execute_task
    from deepagents_cli.input import SessionState
    from deepagents_cli.ui import TokenTracker

    agent, backend = create_olav_agent_with_backend(assistant_id)

    session_state = SessionState(auto_approve=True)
    token_tracker = TokenTracker()

    await execute_task(
        query,
        agent,
        assistant_id,
        session_state,
        token_tracker,
        backend=backend,
    )


def cli_main() -> None:
    """Main entry point for console script."""
    # Fix for gRPC fork issue on macOS
    if sys.platform == "darwin":
        os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

    check_dependencies()

    try:
        args = parse_args()

        if args.verbose:
            logging.basicConfig(level=logging.DEBUG)

        # Handle list command
        if args.command == "list":
            console.print("\n[bold]Available Agents:[/bold]\n")
            console.print(f"  • [bold]olav[/bold] (default)")
            console.print(f"    Location: ~/.deepagents/olav/")
            console.print()
            return

        # Handle help command
        if args.command == "help":
            console.print(f"\n[bold]OLAV v{VERSION} - Network Operations AI Assistant[/bold]\n")
            console.print("Usage:")
            console.print("  olav                                    Interactive mode")
            console.print('  olav "query"                           Single query')
            console.print('  olav --agent ops "Check network"      Multi-agent')
            console.print('  olav --sandbox modal "Deploy config"  Remote execution')
            console.print()
            console.print("Options:")
            console.print("  --agent AGENT       Agent identifier (default: olav)")
            console.print("  --sandbox TYPE      Remote sandbox (none, modal, daytona, runloop)")
            console.print("  --auto-approve      Skip tool approval prompts")
            console.print("  --no-splash         Disable startup banner")
            console.print("  --verbose           Enable debug logging")
            console.print()
            return

        # Handle admin command
        if args.command == "admin":
            import asyncio
            from olav.cli.admin import admin_handler
            cmd_args = args.args[0] if args.args else "status"
            result = asyncio.run(admin_handler(f"/admin {cmd_args}"))
            if result.get("status") == "error":
                console.print(f"[red]Error:[/red] {result.get('message')}")
            else:
                console.print(result.get("message", result))
            return

        # Handle config command
        if args.command == "config":
            from olav.core.config import settings
            console.print("\n[bold]OLAV Configuration:[/bold]\n")
            console.print(f"  LLM Provider: {settings.llm_provider}")
            console.print(f"  LLM Model: {settings.llm_model_name}")
            console.print(f"  Temperature: {settings.llm_temperature}")
            console.print()
            return

        # Create session state
        from deepagents_cli.config import SessionState

        session_state = SessionState(
            auto_approve=args.auto_approve,
            no_splash=args.no_splash,
        )

        if args.query:
            # Single query mode
            asyncio.run(run_single_query(args.query, args.agent))
        else:
            # Interactive mode
            asyncio.run(
                run_interactive(
                    assistant_id=args.agent,
                    session_state=session_state,
                    sandbox_type=args.sandbox,
                )
            )

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        if logging.getLogger().level == logging.DEBUG:
            console.print_exception()
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
