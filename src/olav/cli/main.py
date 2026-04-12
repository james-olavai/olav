#!/usr/bin/env python3
"""OLAV v0.14.0 CLI - Full deepagents-cli integration.

This is a thin wrapper around deepagents-cli for domain operations.
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
import contextlib
import logging
import os
import signal
import sys
import uuid as _uuid_mod
import warnings
from importlib.metadata import entry_points
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

from olav.core.audit_recorder import AuditEventRecorder
from olav.core.version import (
    VERSION,
    format_version_banner,
)

from .banner import print_olav_banner

if TYPE_CHECKING:
    from olav.core.auth import UserIdentity

console = Console()
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SIGTERM / atexit guard — mark active run as "interrupted" on unexpected exit
# ---------------------------------------------------------------------------
_active_audit: AuditEventRecorder | None = None
_active_run_id: str | None = None


def _mark_run_interrupted() -> None:
    """Best-effort: mark the current active run as interrupted."""
    global _active_audit, _active_run_id
    if _active_run_id and _active_audit:
        try:
            _active_audit.record_run_end(run_id=_active_run_id, status="interrupted")
            _active_audit.close()
        except Exception:
            pass
        finally:
            _active_audit = None
            _active_run_id = None


def _sigterm_handler(signum: int, frame: object) -> None:
    _mark_run_interrupted()
    sys.exit(0)


signal.signal(signal.SIGTERM, _sigterm_handler)

_GENERIC_DOMAIN_PROMPT = "You are an AI Operations Assistant."


def get_domain_prompt() -> str:
    """Discover domain prompt from installed plugins via entry_points.

    Checks the ``olav.domain_prompts`` entry point group. Returns the prompt
    from the first registered entry point, or a generic fallback if none exist.
    """
    eps = entry_points(group="olav.domain_prompts")
    for ep in eps:
        try:
            return ep.load()
        except Exception:
            logger.warning("Failed to load domain prompt entry point %r", ep.name)
    return _GENERIC_DOMAIN_PROMPT


def parse_args():
    """Parse command line arguments - deepagents-cli compatible."""
    import types as _types

    # Known subcommands – if the first non-flag positional arg is NOT one of
    # these, treat all remaining positionals as a natural-language query so
    # that both `olav "show log statistics"` and `olav show log counts` work.
    known_commands = {
        "list",
        "help",
        "version",
        "admin",
        "config",
        "service",
        "reset",
        "skills",
        "log",
        "init",
        "refresh",
        "sessions",
        "workspace",
        "export",
        "skill",
        "registry",
        "kb",
    }

    # Flags that consume the immediately following token as their value.
    # We must skip those tokens when searching for the first true positional.
    flags_with_value = {
        "--agent",
        "-a",
        "--sandbox",
        "--sandbox-id",
        "--sandbox-setup",
        "--session",
    }

    raw_argv = sys.argv[1:]

    def _first_positional(argv: list[str]) -> str | None:
        skip_next = False
        for tok in argv:
            if skip_next:
                skip_next = False
                continue
            if tok in flags_with_value:
                skip_next = True
                continue
            if tok.startswith("-"):
                continue
            return tok
        return None

    first_positional = _first_positional(raw_argv)

    if first_positional and first_positional not in known_commands:
        # ── Fast path: natural-language single-query mode ──────────────────
        # Use a lightweight pre-parser to extract flags while leaving the
        # query tokens untouched.
        pre = argparse.ArgumentParser(add_help=False)
        pre.add_argument("--agent", "-a", default=None)
        pre.add_argument("--workspace", "-w", default=None)
        pre.add_argument("--auto-approve", dest="auto_approve", action="store_true")
        pre.add_argument(
            "--dangerously-skip-permissions",
            dest="dangerously_skip_permissions",
            action="store_true",
            help="Skip all approval gates (for testing only — not for production use)",
        )
        pre.add_argument(
            "--sandbox", default="none", choices=["none", "modal", "daytona", "runloop"]
        )
        pre.add_argument("--sandbox-id", dest="sandbox_id", default=None)
        pre.add_argument("--sandbox-setup", dest="sandbox_setup", default=None)
        pre.add_argument("--session", default=None)
        pre.add_argument("--no-splash", dest="no_splash", action="store_true")
        pre.add_argument("--verbose", "-v", action="store_true")
        pre.add_argument("--profile", default=None)  # ISSUE-004: audit profile shorthand
        pre.add_argument(
            "--enable-api-write",
            dest="enable_api_write",
            action="store_true",
            help="Unlock API write operations (POST/PUT/PATCH/DELETE). Writes still require dry-run + approval.",
        )

        pre_args, query_tokens = pre.parse_known_args()
        query = " ".join(query_tokens).strip()
        # ISSUE-004: --profile builds a deterministic run-audit query
        if pre_args.profile and not query:
            profile_name = pre_args.profile
            if not profile_name.endswith(".md") and "/" not in profile_name:
                from olav.core.workspace import resolve_workspace_path
                profile_path = str(
                    resolve_workspace_path("audit", "profiles", workspace=pre_args.workspace)
                    / f"{profile_name}.md"
                )
            else:
                profile_path = profile_name
            query = f"Run audit using profile {profile_path}"
        # Resolve agent default: use active workspace default if not specified
        agent = pre_args.agent
        if agent is None:
            from olav.core.workspace import get_active_workspace
            ws = pre_args.workspace or get_active_workspace()
            agent = "quick" if ws == "core" else ws
        # Build a Namespace that matches what the rest of main() expects
        return _types.SimpleNamespace(
            command=None,
            query=query,
            agent=agent,
            workspace=pre_args.workspace,
            auto_approve=pre_args.auto_approve,
            dangerously_skip_permissions=pre_args.dangerously_skip_permissions,
            sandbox=pre_args.sandbox,
            sandbox_id=pre_args.sandbox_id,
            sandbox_setup=pre_args.sandbox_setup,
            session=pre_args.session,
            no_splash=pre_args.no_splash,
            verbose=pre_args.verbose,
        )

    # ── Normal subcommand / interactive path ──────────────────────────────
    parser = argparse.ArgumentParser(
        prog="olav",
        description=f"OLAV v{VERSION} - AI Operations Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Version command
    subparsers.add_parser("version", help="Show version and system information")

    # List agents command
    subparsers.add_parser("list", help="List all available agents")

    # Help command
    subparsers.add_parser("help", help="Show help information")

    # Admin command
    admin_parser = subparsers.add_parser("admin", help="Admin commands (status, backup, etc.)")
    admin_parser.add_argument("args", nargs=argparse.REMAINDER, help="Admin command arguments")

    # Config command
    config_parser = subparsers.add_parser(
        "config",
        help="Configuration commands (evolve, or natural language query)",
    )
    config_parser.add_argument(
        "args",
        nargs=argparse.REMAINDER,
        help="'evolve --list', 'evolve --approve <id>', or natural language config query",
    )

    # Init command
    subparsers.add_parser("init", help="Initialize platform scaffolding")

    # Refresh command — rebuild global agent registry (deterministic, no LLM)
    subparsers.add_parser(
        "refresh", help="Rebuild global agent registry (PLATFORM.md + routing table)"
    )

    # Sessions command — list conversation sessions across interfaces (M4)
    sessions_parser = subparsers.add_parser(
        "sessions", help="List conversation sessions across CLI/TUI/Web interfaces"
    )
    sessions_parser.add_argument(
        "--all", action="store_true", help="Include inactive sessions"
    )
    sessions_parser.add_argument(
        "--user", metavar="NAME", help="Admin: list sessions for a specific user"
    )

    # Workspace command
    workspace_parser = subparsers.add_parser("workspace", help="Manage workspace lifecycle")
    workspace_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Workspace lifecycle arguments"
    )

    # Export command
    export_parser = subparsers.add_parser("export", help="Export Claude-compatible artifacts")
    export_parser.add_argument("args", nargs=argparse.REMAINDER, help="Export command arguments")

    # Service command (logs, web, daemon, etc.)
    service_parser = subparsers.add_parser("service", help="Manage background services")
    service_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Service management arguments"
    )

    registry_parser = subparsers.add_parser(
        "registry", help="Register and manage external service integrations"
    )
    registry_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Registry subcommand arguments"
    )

    skill_parser = subparsers.add_parser(
        "skill", help="Install and manage workspace skills from git repos"
    )
    skill_parser.add_argument(
        "args", nargs=argparse.REMAINDER, help="Skill subcommand and arguments"
    )

    # Reset command - clear agent conversation/checkpoint history
    reset_parser = subparsers.add_parser("reset", help="Reset agent conversation history")
    reset_parser.add_argument("--agent", "-a", required=True, help="Agent identifier to reset")
    reset_parser.add_argument(
        "--target", default=None, help="Copy initial prompt from this agent (optional)"
    )

    # Skills command - manage agent skills/tools in .olav/workspace/
    skills_parser = subparsers.add_parser("skills", help="Manage agent skills")
    skills_sub = skills_parser.add_subparsers(dest="skills_command", help="Skills action")

    # skills list
    skills_list = skills_sub.add_parser("list", help="List skills for an agent")
    skills_list.add_argument("--agent", "-a", default=None, help="Filter by agent")

    # skills create <name>
    skills_create = skills_sub.add_parser("create", help="Create a new skill template")
    skills_create.add_argument("name", help="Skill name")
    skills_create.add_argument("--agent", "-a", required=True, help="Agent to add skill to")

    # skills info <name>
    skills_info = skills_sub.add_parser("info", help="Show skill details")
    skills_info.add_argument("name", help="Skill name")
    skills_info.add_argument("--agent", "-a", default=None, help="Agent to search in")

    # Log command — query audit.duckdb
    log_parser = subparsers.add_parser("log", help="Query audit log (audit.duckdb)")
    log_sub = log_parser.add_subparsers(dest="log_command", help="Log action")
    log_sub.add_parser("list", help="List recent runs (default, last 24 h)")
    log_show_p = log_sub.add_parser("show", help="Show all events for a run")
    log_show_p.add_argument("run_id", help="Run ID to show")
    log_errors_p = log_sub.add_parser("errors", help="Show error events")
    log_errors_p.add_argument("--hours", type=int, default=24, help="Look-back window in hours")

    # log export sft — export audit data as SFT chat JSONL
    log_export_p = log_sub.add_parser("export", help="Export audit data for training")
    log_export_sub = log_export_p.add_subparsers(dest="export_format", help="Export format")
    log_export_sft = log_export_sub.add_parser("sft", help="Export SFT chat JSONL")
    log_export_sft.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_sft.add_argument("--output", default=None, help="Output directory")
    log_export_sft.add_argument(
        "--min-score", type=float, default=0.0, help="Minimum rule score threshold (0.0-1.0)"
    )
    log_export_sft.add_argument(
        "--encrypt", action="store_true", default=None, help="Force encryption"
    )
    log_export_sft.add_argument(
        "--no-encrypt", dest="encrypt", action="store_false", help="Force plaintext"
    )
    log_export_sft.add_argument("--key-ref", default=None, help="Keyset reference name")
    log_export_traj = log_export_sub.add_parser(
        "trajectory", help="Export tool-use trajectory JSONL"
    )
    log_export_traj.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_traj.add_argument("--output", default=None, help="Output directory")
    log_export_traj.add_argument(
        "--min-score", type=float, default=0.0, help="Minimum rule score threshold (0.0-1.0)"
    )
    log_export_traj.add_argument(
        "--encrypt", action="store_true", default=None, help="Force encryption"
    )
    log_export_traj.add_argument(
        "--no-encrypt", dest="encrypt", action="store_false", help="Force plaintext"
    )
    log_export_traj.add_argument("--key-ref", default=None, help="Keyset reference name")
    log_export_atif = log_export_sub.add_parser("atif", help="Export ATIF trace JSONL")
    log_export_atif.add_argument("--hours", type=int, default=24, help="Look-back window in hours")
    log_export_atif.add_argument("--output", default=None, help="Output directory")
    log_export_atif.add_argument(
        "--min-score", type=float, default=0.0, help="Minimum rule score threshold (0.0-1.0)"
    )
    log_export_atif.add_argument(
        "--encrypt", action="store_true", default=None, help="Force encryption"
    )
    log_export_atif.add_argument(
        "--no-encrypt", dest="encrypt", action="store_false", help="Force plaintext"
    )
    log_export_atif.add_argument("--key-ref", default=None, help="Keyset reference name")
    log_export_grant = log_export_sub.add_parser(
        "grant-local-train", help="Issue one-time token for local training access"
    )
    log_export_grant.add_argument(
        "--export-id", required=True, help="Export ID to bind the token to"
    )
    log_export_grant.add_argument(
        "--ttl-minutes", type=int, default=10, help="Token TTL in minutes (default: 10)"
    )

    # KB (Unified Knowledge Store) command group
    from olav.cli.commands.kb import build_kb_parser
    build_kb_parser(subparsers)

    # Default interactive mode flags
    parser.add_argument(
        "--agent",
        "-a",
        default="quick",
        help="Agent identifier for separate memory stores (default: quick)",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables HITL)",
    )
    parser.add_argument(
        "--dangerously-skip-permissions",
        dest="dangerously_skip_permissions",
        action="store_true",
        help="Skip all approval gates — check_approval, sandbox_guard, service_call write gate (for testing only)",
    )
    parser.add_argument(
        "--enable-api-write",
        dest="enable_api_write",
        action="store_true",
        help="Unlock API write operations. Writes still require dry-run + mandatory approval.",
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
        "--session",
        help="Session ID for session recovery (stored in ~/.olav/sessions/)",
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

    if missing:
        console.print("\n[bold red]Missing required dependencies![/bold red]")
        console.print("\nThe following packages are required:")
        for pkg in missing:
            console.print(f"  - {pkg}")
        console.print("\nInstall with: [bold]uv sync[/bold]")
        sys.exit(1)


def _resolve_agent_id(agent_id: str, workspace: str | None) -> str:
    """Resolve effective agent_id for OLAVAgent given an optional workspace name.

    Strategy (flat→nested, §11.6):
    1. If workspace is None: return agent_id as-is (flat compat)
    2. If flat .olav/workspace/<agent_id>/ exists: return agent_id (backward compat)
    3. Otherwise: return "<workspace>/<agent_id>" for nested structure
    """
    from olav.core.workspace import resolve_workspace_path

    resolved = resolve_workspace_path(agent_id, workspace=workspace)
    workspace_root = (Path(".olav") / "workspace").resolve()
    try:
        return str(resolved.relative_to(workspace_root))
    except ValueError:
        return agent_id


def create_olav_agent_with_backend(
    assistant_id: str,
    session_id: str | None = None,
    sandbox=None,
    sandbox_type: str | None = None,
    workspace: str | None = None,
):
    """Create OLAV agent with CompositeBackend.

    This integrates OLAV's domain-specific agent with deepagents infrastructure.

    Args:
        assistant_id: Agent identifier for memory storage
        session_id: Optional session ID for recovery
        sandbox: Optional sandbox backend for remote execution
        sandbox_type: Type of sandbox ("modal", "runloop", "daytona")

    Returns:
        Tuple of (agent graph, composite backend)
    """
    from deepagents.backends import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend

    from olav.agents.agent import OLAVAgent

    # Resolve agent_id through workspace routing (§4, §11.6)
    effective_id = _resolve_agent_id(assistant_id, workspace)

    # Create OLAV agent (which uses create_deep_agent internally)
    olav_agent = OLAVAgent(
        agent_id=effective_id,
        session_id=session_id,
        enable_checkpointer=True,
    )

    # Create backend
    if sandbox is None:
        # Local mode — use LocalShellBackend directly (NOT wrapped in CompositeBackend).
        # CompositeBackend does not inherit SandboxBackendProtocol, so wrapping it
        # would prevent deepagents from injecting the `execute` shell tool.
        # LocalShellBackend inherits SandboxBackendProtocol → agent gets `execute`.
        from olav.agents._deepagents_bridge import HAS_LOCAL_SHELL_BACKEND, LocalShellBackend

        if HAS_LOCAL_SHELL_BACKEND and LocalShellBackend is not None:
            composite_backend = LocalShellBackend(root_dir=str(Path.cwd()), inherit_env=True)
        else:
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

    # Bake plugin callbacks into the graph so they fire even when callers
    # (e.g. deepagents_cli.execute_task) build their own config without callbacks.
    graph = olav_agent.graph
    cbs = olav_agent.plugin_registry.get_callback_plugins()
    if cbs:
        graph = graph.with_config({"callbacks": cbs})  # type: ignore[assignment]
    # Attach plugin_registry to the graph so CLI/API code can access it for
    # binding the top-level run context to callback plugins (e.g. audit).
    graph.plugin_registry = olav_agent.plugin_registry  # type: ignore[attr-defined]
    return graph, composite_backend


@contextlib.contextmanager
def _hitl_audit_scope(recorder: AuditEventRecorder, run_id: str, agent_id: str):
    """Context manager that patches *prompt_for_tool_approval* to emit HITL
    audit events (``hitl_requested`` / ``hitl_decision``) for every interrupt.

    The patch is thread-local to this invocation: the original function is
    restored in the ``finally`` block even if an exception occurs.
    """
    try:
        import deepagents_cli.execution as _dce  # type: ignore[import]

        _original = _dce.prompt_for_tool_approval
    except Exception as _e:
        logger.debug("_hitl_audit_scope: deepagents_cli not available (%s) — HITL events disabled", _e)
        yield
        return

    def _audited(action_request, assistant_id_arg):
        interrupt_id = str(_uuid_mod.uuid4())
        recorder.record_hitl_requested(
            run_id=run_id,
            interrupt_id=interrupt_id,
            action_requests=[action_request]
            if not isinstance(action_request, list)
            else action_request,
            agent_id=agent_id,
        )
        decision = _original(action_request, assistant_id_arg)
        decision_type = (
            decision.get("type")
            if isinstance(decision, dict)
            else getattr(decision, "type", str(decision))
        )
        recorder.record_hitl_decision(
            run_id=run_id,
            interrupt_id=interrupt_id,
            decision=str(decision_type),
            agent_id=agent_id,
        )
        return decision

    _dce.prompt_for_tool_approval = _audited
    try:
        yield
    finally:
        _dce.prompt_for_tool_approval = _original


async def simple_cli(
    agent,
    assistant_id: str,
    session_state,
    backend,
    sandbox_type: str | None = None,
    no_splash: bool = False,
) -> None:
    """Main CLI loop using deepagents-cli components."""
    try:
        from deepagents_cli.config import COLORS
        from deepagents_cli.execution import execute_task
        from deepagents_cli.input import create_prompt_session
        from deepagents_cli.ui import TokenTracker
    except ImportError as _e:
        console.print(
            f"[red]Error:[/red] Interactive TUI requires deepagents-cli: {_e}\n"
            "Install with: [cyan]pip install deepagents-cli==0.0.10 --no-deps[/cyan]"
        )
        return

    # Show splash
    if not no_splash:
        # Print OLAV banner with gradient
        print_olav_banner()

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

        # Handle slash commands (/quit, /exit, /q, /clear, /help, /tokens)
        if user_input.startswith("/"):
            # Custom OLAV slash commands — handled before deepagents_cli
            _cmd = user_input.strip().lower().split()[0]
            if _cmd == "/trace-review":
                _parts = user_input.strip().split()
                _hours = 168
                _limit = 50
                for _p in _parts[1:]:
                    if _p.startswith("hours="):
                        try:
                            _hours = int(_p.split("=", 1)[1])
                        except ValueError:
                            pass
                    elif _p.startswith("limit="):
                        try:
                            _limit = int(_p.split("=", 1)[1])
                        except ValueError:
                            pass
                from olav.cli.commands.trace_review import (
                    _handle_trace_review,
                    print_trace_review,
                )

                console.print("\n[bold cyan]Running trace review...[/bold cyan]")
                _tr_result = _handle_trace_review(hours=_hours, limit=_limit)
                print_trace_review(_tr_result, console)
                continue

            from deepagents_cli.commands import handle_command

            # Check OLAV's own slash command registry first (e.g. /model, /tokens, /history)
            from olav.cli.commands.builtin import execute_command

            try:
                _olav_result = await execute_command(user_input)
            except EOFError:
                console.print("\nGoodbye!", style=COLORS["primary"])
                break
            if not isinstance(_olav_result, str) or not _olav_result.startswith(
                "Unknown command:"
            ):
                if _olav_result:
                    console.print(_olav_result)
                continue

            result = handle_command(user_input, agent, token_tracker)
            if result == "exit":
                console.print("\nGoodbye!", style=COLORS["primary"])
                break
            continue

        # Handle !bash prefix for local shell execution
        if user_input.startswith("!"):
            from deepagents_cli.commands import execute_bash_command

            execute_bash_command(user_input)
            continue

        # Check for bare quit keywords
        if user_input.lower() in ["quit", "exit", "q"]:
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        import os as _os
        import uuid as _uuid

        _run_id = str(_uuid.uuid4())
        _audit = AuditEventRecorder()
        # Register as active run so SIGTERM handler can mark it interrupted
        global _active_audit, _active_run_id
        _active_audit, _active_run_id = _audit, _run_id
        _audit.record_run_start(
            run_id=_run_id,
            agent_id=assistant_id,
            user_id=_os.environ.get("USER", "anonymous"),
            source_channel="cli_interactive",
        )
        _audit.record(
            event_type="user_input_received",
            run_id=_run_id,
            agent_id=assistant_id,
            payload={"content": user_input},
        )
        # Record the user turn in audit_messages for dataset export
        _audit.record_message(run_id=_run_id, role="user", content=user_input)

        # Bind the top-level run context to AuditCallbackPlugin so tool events
        # and LLM responses are recorded under the same run_id.
        from olav.plugins.callbacks.audit import AuditCallbackPlugin as _AuditCBPlugin
        _audit_cbs = [
            _cb for _cb in (
                agent.plugin_registry.get_callback_plugins()
                if hasattr(agent, "plugin_registry") else []
            )
            if isinstance(_cb, _AuditCBPlugin)
        ]
        for _cb in _audit_cbs:
            _cb.bind_run(_run_id, _audit)

        # Record routing decision
        try:
            from olav.core.router import route_query as _route_query

            _route_query(user_input, recorder=_audit, run_id=_run_id)
        except Exception:
            pass

        # Execute task (with HITL audit wrapping)
        try:
            with _hitl_audit_scope(_audit, _run_id, assistant_id):
                await execute_task(
                    user_input,
                    agent,
                    assistant_id,
                    session_state,
                    token_tracker,
                    backend=backend,
                )
            _audit.record(
                event_type="assistant_output_final",
                run_id=_run_id,
                agent_id=assistant_id,
                payload={},
            )
            _audit.record_run_end(run_id=_run_id, status="completed")
        except KeyboardInterrupt:
            _audit.record(
                event_type="run_cancelled",
                run_id=_run_id,
                agent_id=assistant_id,
                payload={"reason": "KeyboardInterrupt"},
            )
            _audit.record_run_end(run_id=_run_id, status="cancelled")
            raise
        except Exception:
            _audit.record(
                event_type="run_error",
                run_id=_run_id,
                agent_id=assistant_id,
                payload={},
            )
            _audit.record_run_end(run_id=_run_id, status="error")
            raise
        finally:
            for _cb in _audit_cbs:
                _cb.unbind_run()
            _audit.close()
            _active_audit = None
            _active_run_id = None


# ---------------------------------------------------------------------------
# Auth helpers (P1: inline login gate + single-query silent auth)
# ---------------------------------------------------------------------------


def _get_auth_mode() -> str:
    """Read auth.mode from ConfigLoader (api.json). Default: 'none'."""
    try:
        from olav.core.config import ConfigLoader

        return ConfigLoader().auth.mode
    except Exception:
        return "none"


async def _inline_login_gate() -> UserIdentity | None:
    """Inline login prompt for interactive mode when auth.mode != 'none'.

    Uses prompt_toolkit masked password input (D5). Returns UserIdentity on
    success, None if user aborts (Ctrl-C).
    Returns None immediately if mode == 'none' (OS identity).
    """
    from olav.core.auth import UserIdentity, get_auth_provider

    mode = _get_auth_mode()
    if mode == "none":
        return get_auth_provider("none").authenticate()

    try:
        from prompt_toolkit import prompt as pt_prompt
        from prompt_toolkit.formatted_text import ANSI
    except ImportError:
        # Fallback without prompt_toolkit masking
        import getpass

        token = getpass.getpass("Token: ")
        return get_auth_provider(mode).authenticate(token=token, source_channel="cli_interactive")

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            token = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: pt_prompt("Token: ", is_password=True),
            )
        except (KeyboardInterrupt, EOFError):
            console.print("\n[yellow]Login cancelled.[/yellow]")
            return None
        token = token.strip()
        if not token:
            continue
        identity = get_auth_provider(mode).authenticate(
            token=token, source_channel="cli_interactive"
        )
        if identity.source == "token":
            console.print(
                f"  [green]✓ Authenticated as [bold]{identity.username}[/bold] [{identity.role}][/green]"
            )
            return identity
        console.print(f"  [red]✗ Authentication failed (attempt {attempt}/{max_attempts})[/red]")
    console.print("[red]Too many failed attempts. Exiting.[/red]")
    return None


def _silent_auth() -> UserIdentity | None:
    """Silent token auth for single-query mode (D6).

    Reads ~/.olav/token or OLAV_TOKEN env var. Returns None if not
    authenticated in token mode, so caller can show error and exit.
    """
    mode = _get_auth_mode()
    if mode == "none":
        from olav.core.auth import get_auth_provider

        return get_auth_provider("none").authenticate()

    # Check OLAV_TOKEN env override first (D6, CI scenario)
    token = os.environ.get("OLAV_TOKEN")
    if not token:
        token_file = Path.home() / ".olav" / "token"
        if token_file.exists():
            token = token_file.read_text(encoding="utf-8").strip()

    if not token:
        return None  # caller prints error

    from olav.core.auth import get_auth_provider

    identity = get_auth_provider(mode).authenticate(token=token, source_channel="cli_token")
    if identity.source == "token":
        return identity
    return None  # invalid token


async def run_interactive(
    assistant_id: str,
    session_state,
    sandbox_type: str = "none",
    session_id: str | None = None,
    workspace: str | None = None,
) -> None:
    """Run interactive mode."""
    agent, backend = create_olav_agent_with_backend(
        assistant_id, session_id=session_id, workspace=workspace
    )

    # P1: inline login gate (skipped in mode=none)
    if _get_auth_mode() != "none":
        identity = await _inline_login_gate()
        if identity is None:
            return  # aborted or too many failures

    await simple_cli(
        agent,
        assistant_id,
        session_state,
        backend,
        sandbox_type=sandbox_type if sandbox_type != "none" else None,
        no_splash=session_state.no_splash,
    )


async def run_single_query(
    query: str,
    assistant_id: str,
    session_id: str | None = None,
    workspace: str | None = None,
) -> None:
    """Run a single query and exit."""
    import uuid

    # Intercept slash commands before sending to LLM — workspace MANIFEST.yaml
    # slash_commands (kind=shell) run scripts directly without LLM overhead.
    if query.strip().startswith("/"):
        from olav.cli.commands.builtin import execute_command

        _slash_result = await execute_command(query.strip(), auto_approve=True)
        if _slash_result is not None and not (
            isinstance(_slash_result, str) and _slash_result.startswith("Unknown command:")
        ):
            if _slash_result:
                console.print(_slash_result)
            return

    try:
        from deepagents_cli.config import COLORS
        from deepagents_cli.execution import execute_task
        from deepagents_cli.input import SessionState
        from deepagents_cli.ui import TokenTracker
    except ImportError as _e:
        console.print(
            f"[red]Error:[/red] Single-query mode requires deepagents-cli: {_e}\n"
            "Install with: [cyan]pip install deepagents-cli==0.0.10 --no-deps[/cyan]"
        )
        sys.exit(1)

    # P1: silent auth check (D6) — no interactive prompt in single-query mode
    if _get_auth_mode() != "none":
        identity = _silent_auth()
        if identity is None:
            import sys

            print(
                "Not authenticated. Run `olav` to log in or set OLAV_TOKEN env var.",
                file=sys.stderr,
            )
            sys.exit(1)
        user_id = identity.username
    else:
        user_id = os.environ.get("USER", "anonymous")

    agent, backend = create_olav_agent_with_backend(
        assistant_id, session_id=session_id, workspace=workspace
    )

    run_id = str(uuid.uuid4())
    recorder = AuditEventRecorder()
    global _active_audit, _active_run_id
    _active_audit, _active_run_id = recorder, run_id
    recorder.record_run_start(
        run_id=run_id,
        agent_id=assistant_id,
        user_id=user_id,
        source_channel="cli",
    )
    recorder.record(
        event_type="user_input_received",
        run_id=run_id,
        agent_id=assistant_id,
        payload={"content": query},
    )
    # Record the user turn in audit_messages for dataset export
    recorder.record_message(run_id=run_id, role="user", content=query)

    # Bind the top-level run context to AuditCallbackPlugin
    from olav.plugins.callbacks.audit import AuditCallbackPlugin as _AuditCBPlugin
    _audit_cbs = [
        _cb for _cb in (
            agent.plugin_registry.get_callback_plugins()
            if hasattr(agent, "plugin_registry") else []
        )
        if isinstance(_cb, _AuditCBPlugin)
    ]
    for _cb in _audit_cbs:
        _cb.bind_run(run_id, recorder)

    # Record routing decision
    try:
        from olav.core.router import route_query as _route_query

        _route_query(query, recorder=recorder, run_id=run_id)
    except Exception:
        pass

    session_state = SessionState(auto_approve=True)
    token_tracker = TokenTracker()

    try:
        with _hitl_audit_scope(recorder, run_id, assistant_id):
            result = await execute_task(
                query,
                agent,
                assistant_id,
                session_state,
                token_tracker,
                backend=backend,
            )
        final_content = str(result) if result is not None else ""
        recorder.record(
            event_type="assistant_output_final",
            run_id=run_id,
            agent_id=assistant_id,
            payload={"content": final_content},
        )
        # Record assistant response in audit_messages for dataset export
        if final_content:
            recorder.record_message(run_id=run_id, role="assistant", content=final_content)
        recorder.record_run_end(run_id=run_id, status="completed")
    except KeyboardInterrupt:
        recorder.record(
            event_type="run_cancelled",
            run_id=run_id,
            agent_id=assistant_id,
            payload={"reason": "KeyboardInterrupt"},
        )
        recorder.record_run_end(run_id=run_id, status="cancelled")
        raise
    except Exception:
        recorder.record(
            event_type="run_error",
            run_id=run_id,
            agent_id=assistant_id,
            payload={},
        )
        recorder.record_run_end(run_id=run_id, status="error")
        raise
    finally:
        for _cb in _audit_cbs:
            _cb.unbind_run()
        recorder.close()
        _active_audit = None
        _active_run_id = None


def cli_main_async() -> None:
    """Main entry point for console script (async wrapper)."""
    # Suppress LangChain Pydantic V1 deprecation warning on Python 3.14+.
    # LangChain internally uses pydantic.v1 compatibility shim; the warning is
    # cosmetic — it does not affect runtime behaviour on Python 3.11–3.14.
    warnings.filterwarnings(
        "ignore",
        message="Core Pydantic V1 functionality",
        category=UserWarning,
    )

    # Fix for gRPC fork issue on macOS
    if sys.platform == "darwin":
        os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

    check_dependencies()
    asyncio.run(cli_main_impl())


async def cli_main_impl() -> None:
    """Async implementation of cli_main."""
    try:
        args = parse_args()

        if args.verbose:
            logging.basicConfig(level=logging.DEBUG)

        # Handle version command
        if args.command == "version":
            import platform

            # Use the formatted banner from version module
            console.print(format_version_banner())

            # System information
            try:
                console.print("[bold dim]System Information:[/bold dim]")
                console.print(f"  Python: {platform.python_version()}")
                console.print(f"  Platform: {platform.system()} {platform.release()}")
                console.print(f"  Machine: {platform.machine()}")
            except Exception:
                pass

            # Installation path
            try:
                olav_module = Path(__file__).parent.parent
                console.print(f"  Installation: {olav_module}")
            except Exception:
                pass

            console.print()
            return

        # Handle list command
        if args.command == "list":
            import yaml
            from olav.core.workspace import resolve_workspace_root

            workspace_root = resolve_workspace_root()
            console.print("\n[bold]Available Agents:[/bold]\n")
            found = []
            if workspace_root.exists():
                for agent_md in sorted(workspace_root.glob("*/AGENT.md")):
                    agent_dir = agent_md.parent
                    try:
                        raw = agent_md.read_text()
                        if raw.startswith("---"):
                            parts = raw.split("---", 2)
                            meta = yaml.safe_load(parts[1]) if len(parts) >= 2 else {}
                        else:
                            meta = {}
                        name = meta.get("name") or agent_dir.name
                        desc = " ".join(str(meta.get("description", "")).split())
                        found.append((agent_dir.name, name, desc))
                    except Exception:
                        found.append((agent_dir.name, agent_dir.name, ""))
            if found:
                for flag, _name, desc in found:
                    default_tag = " [dim](default)[/dim]" if flag == "olav" else ""
                    console.print(f"  • [bold]{flag}[/bold]{default_tag}")
                    if desc:
                        console.print(f"    [dim]{desc}[/dim]")
                    console.print(f"    Location: .olav/workspace/{flag}/")
                    console.print()
            else:
                console.print("  [yellow]No agents found in .olav/workspace/[/yellow]\n")
            return

        # Handle help command
        if args.command == "help":
            console.print()
            console.print(f"[bold cyan]OLAV v{VERSION} - AI Operations Assistant[/bold cyan]\n")
            console.print("[bold]Usage:[/bold]")
            console.print("  [cyan]olav[/cyan]                                    Interactive mode")
            console.print(
                '  [cyan]olav[/cyan] [green]"query"[/green]                           Single query'
            )
            console.print(
                '  [cyan]olav[/cyan] [yellow]--agent ops[/yellow] [green]"Check network"[/green]      Multi-agent'
            )
            console.print(
                '  [cyan]olav[/cyan] [yellow]--sandbox modal[/yellow] [green]"Deploy config"[/green]  Remote execution'
            )
            console.print()
            console.print("[bold]Commands:[/bold]")
            console.print("  [cyan]version[/cyan]              Show version and system information")
            console.print("  [cyan]list[/cyan]                 List all available agents")
            console.print("  [cyan]help[/cyan]                 Show this help message")
            console.print(
                "  [cyan]reset[/cyan] --agent ID     Reset agent conversation/session history"
            )
            console.print(
                "  [cyan]skills[/cyan] list          List all skills          (alias: [dim]skills[/dim])"
            )
            console.print(
                "  [cyan]skills[/cyan] create NAME   Create new skill template  --agent required"
            )
            console.print("  [cyan]skills[/cyan] info NAME     Show skill details")
            console.print(
                "  [cyan]admin[/cyan]               Admin commands (status, backup, etc.)"
            )
            console.print("  [cyan]config[/cyan]              Configuration management")
            console.print("  [cyan]init[/cyan]                Initialize platform scaffolding")
            console.print(
                "  [cyan]workspace[/cyan]           Manage workspace lifecycle (status/diff/upgrade/disable/remove/prune/rollback)"
            )
            console.print(
                "  [cyan]workspace[/cyan]           Manage workspace lifecycle (status/diff/upgrade/disable/remove/prune/rollback)"
            )
            console.print(
                "  [cyan]export[/cyan]              Export Claude skills or plugin layout"
            )
            console.print(
                "  [cyan]service[/cyan]             Manage background services (daemon, logs, web)"
            )
            console.print()
            console.print("[bold]Interactive Slash Commands:[/bold]")
            console.print("  [cyan]/help[/cyan]                Show interactive commands")
            console.print("  [cyan]/clear[/cyan]               Reset conversation and clear screen")
            console.print("  [cyan]/tokens[/cyan]              Show token usage statistics")
            console.print(
                "  [cyan]/trace-review[/cyan]        Analyze agent failures → learn constraints"
            )
            console.print(
                "  [cyan]/quit[/cyan]  [cyan]/exit[/cyan]  [cyan]/q[/cyan]   Exit the CLI"
            )
            console.print()
            console.print("[bold]Special Input Prefixes:[/bold]")
            console.print(
                "  [cyan]!<cmd>[/cyan]               Run a bash command (e.g., [dim]!ls -la[/dim], [dim]!git status[/dim])"
            )
            console.print(
                "  [cyan]@<file>[/cyan]              Inject file contents into the prompt"
            )
            console.print()
            console.print("[bold]Global Options:[/bold]")
            console.print(
                "  [yellow]-a, --agent[/yellow] AGENT       Set active agent (quick, ops, audit, config)"
            )
            console.print(
                "  [yellow]--sandbox[/yellow] TYPE          Remote sandbox (none, modal, daytona, runloop)"
            )
            console.print("  [yellow]--sandbox-id[/yellow] ID         Reuse existing sandbox ID")
            console.print(
                "  [yellow]--auto-approve[/yellow]          Auto-approve tool usage without prompting"
            )
            console.print(
                "  [yellow]--session[/yellow] ID            Session ID for recovery (in ~/.olav/sessions/)"
            )
            console.print("  [yellow]--no-splash[/yellow]            Disable startup banner")
            console.print("  [yellow]-v, --verbose[/yellow]         Enable verbose/debug output")
            console.print("  [yellow]-V, --version[/yellow]         Show version information")
            console.print("  [yellow]-h, --help[/yellow]            Show this help message")
            console.print()
            console.print("[bold]Examples:[/bold]")
            console.print("  [dim]# Start interactive mode[/dim]")
            console.print("  [cyan]$ olav[/cyan]")
            console.print()
            console.print("  [dim]# Ask a quick question[/dim]")
            console.print('  [cyan]$ olav "How many records are in the database?"[/cyan]')
            console.print()
            console.print("  [dim]# Use a specific agent for deep analysis[/dim]")
            console.print('  [cyan]$ olav --agent ops "Analyze recent audit logs"[/cyan]')
            console.print()
            console.print("  [dim]# Run in a remote sandbox[/dim]")
            console.print('  [cyan]$ olav --sandbox modal "Deploy configuration"[/cyan]')
            console.print()
            console.print("[bold]Documentation:[/bold]")
            console.print("  README:           ./README.md")
            console.print("  User Guide:       ./docs/")
            console.print("  Configuration:    ~/.olav/config/")
            console.print()
            return

        # Handle admin command
        if args.command == "admin":
            cmd_args = " ".join(args.args) if args.args else "status"

            # User management sub-commands → AdminUsersCommand
            _user_mgmt_cmds = {"add-user", "list-users", "revoke-token", "rotate-token"}
            _first_token = cmd_args.split()[0] if cmd_args.strip() else ""
            if _first_token in _user_mgmt_cmds:
                from olav.cli.commands.admin_users import AdminUsersCommand

                _admin_users = AdminUsersCommand()
                _result_str = await _admin_users.execute(cmd_args)
                console.print(_result_str)
                if _result_str.startswith("error:"):
                    raise SystemExit(1)
                return

            # System admin commands → legacy admin_handler
            from olav.cli.admin import admin_handler

            result = await admin_handler(f"/admin {cmd_args}")
            if result.get("status") == "error":
                console.print(f"[red]Error:[/red] {result.get('message')}")
            else:
                console.print(result.get("message", result))
            return

        # Handle config command
        if args.command == "config":
            # If args provided, check for 'evolve' subcommand first
            if args.args and args.args[0] == "evolve":
                from olav.cli.commands.config_evolve import run_evolve_command
                from olav.core.config import DOMAIN_DB_PATH

                output = run_evolve_command(
                    args=args.args[1:],
                    domain_db_path=DOMAIN_DB_PATH,
                )
                console.print(output)
            elif args.args:
                query = " ".join(args.args)
                await run_single_query(query, args.agent, session_id=args.session)
            else:
                # Otherwise show configuration
                from olav.core.config import settings

                console.print("\n[bold]OLAV Configuration:[/bold]\n")
                console.print(f"  LLM Provider: {settings.llm_provider}")
                console.print(f"  LLM Model: {settings.llm_model_name}")
                console.print(f"  Temperature: {settings.llm_temperature}")
                console.print()
            return

        # Handle init command
        if args.command == "init":
            from olav.cli.commands.init import InitCommand

            cmd = InitCommand()
            result = await cmd.execute()
            console.print(result)
            return

        # Handle refresh command — rebuild global agent registry
        if args.command == "refresh":
            from olav.cli.commands.refresh import RefreshCommand

            cmd = RefreshCommand()
            result = await cmd.execute()
            console.print(result)
            return

        # Handle sessions command (M4: session listing across interfaces)
        if args.command == "sessions":
            from olav.cli.commands.sessions import SessionsCommand

            cmd = SessionsCommand()
            # Build args string from the proper argparse attributes
            _sessions_parts = []
            if getattr(args, "all", False):
                _sessions_parts.append("--all")
            if getattr(args, "user", None):
                _sessions_parts.extend(["--user", args.user])
            result = await cmd.execute(" ".join(_sessions_parts))
            console.print(result)
            return

        # Handle service command
        if args.command == "service":
            from olav.cli.commands.service import ServiceCommand

            cmd = ServiceCommand()
            service_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(service_args)
            if result and result != "success":
                console.print(result)
            return

        # Handle registry command (external service registration)
        if args.command == "registry":
            from olav.cli.commands.service_registry import ServiceRegistryCommand

            cmd = ServiceRegistryCommand()
            registry_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(registry_args)
            if result and result not in ("success", ""):
                console.print(result)
            return

        if args.command == "skill":
            from olav.cli.commands.skill import SkillCommand

            cmd = SkillCommand()
            skill_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(skill_args)
            console.print(result)
            return

        # Handle workspace command
        if args.command == "workspace":
            from olav.cli.commands.workspace import WorkspaceCommand

            cmd = WorkspaceCommand()
            workspace_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(workspace_args)
            if result:
                console.print(result)
            return

        # Handle export command
        if args.command == "export":
            from olav.cli.commands.export import ExportCommand

            cmd = ExportCommand()
            export_args = " ".join(args.args) if args.args else ""
            result = await cmd.execute(export_args)
            if result:
                console.print(result)
            return

        # Handle reset command - clear checkpoint/session data for an agent
        if args.command == "reset":
            import shutil

            agent_id = args.agent
            source = getattr(args, "target", None)
            sessions_dir = Path.home() / ".olav" / "sessions"
            removed = 0
            if sessions_dir.exists():
                for f in sessions_dir.iterdir():
                    if agent_id in f.name:
                        f.unlink()
                        removed += 1
            if source:
                console.print(
                    "[yellow]--target copy not supported in OLAV (agents live in "
                    ".olav/workspace/). Cleared session data only.[/yellow]"
                )
            console.print(
                f"[bold green]✓[/bold green] Agent [bold]{agent_id}[/bold] reset "
                f"({removed} session file(s) removed)."
            )
            console.print(f"  [dim]Sessions dir: {sessions_dir}[/dim]")
            return

        # Handle log command — query audit.duckdb
        if args.command == "log":
            from olav.cli.log_cmd import log_errors, log_list, log_show

            log_sub_cmd = getattr(args, "log_command", None)
            if log_sub_cmd == "show":
                events = log_show(args.run_id)
                if not events:
                    console.print(f"[yellow]No events found for run_id: {args.run_id}[/yellow]")
                else:
                    for ev in events:
                        ts = str(ev.get("timestamp", ""))[:19]
                        console.print(f"  [{ts}] {ev['event_type']:30s} {ev.get('agent_id') or ''}")
            elif log_sub_cmd == "errors":
                hours = getattr(args, "hours", 24)
                events = log_errors(since_hours=hours)
                if not events:
                    console.print(f"[green]No errors in the last {hours}h[/green]")
                else:
                    for ev in events:
                        ts = str(ev.get("timestamp", ""))[:19]
                        console.print(
                            f"  [{ts}] [red]{ev['event_type']}[/red]  run={ev.get('run_id', '')[:8]}"
                        )
            elif log_sub_cmd == "export":
                export_fmt = getattr(args, "export_format", None)
                try:
                    from olav.enterprise.cli_bridge import dispatch_log_export
                except ImportError:
                    console.print(
                        "[red]Error: olav-ent package not installed. "
                        "Install with: pip install olav-ent[/red]"
                    )
                    return
                dispatch_log_export(export_fmt, args, console)
            else:
                runs = log_list()
                if not runs:
                    console.print("[yellow]No audit runs in the last 24h[/yellow]")
                else:
                    console.print("\n[bold]Recent Audit Runs (last 24h):[/bold]\n")
                    for r in runs:
                        ts = str(r.get("start_time", ""))[:19]
                        rid = str(r.get("run_id", ""))[:8]
                        status = r.get("status", "")
                        agent = r.get("agent_id", "")
                        console.print(f"  [{ts}] {rid}  {status:12s}  agent={agent}")
            return

        # Handle skills command - manage SKILL.md files in .olav/workspace/
        if args.command == "skills":
            from olav.core.workspace import resolve_workspace_root
            workspace = resolve_workspace_root()
            skills_cmd = getattr(args, "skills_command", None)

            if skills_cmd is None or skills_cmd == "list":
                agent_filter = getattr(args, "agent", None)
                console.print("\n[bold]Agent Skills:[/bold]\n")
                found_any = False
                search_dirs = (
                    ([workspace / agent_filter] if agent_filter else sorted(workspace.iterdir()))
                    if workspace.exists()
                    else []
                )
                for agent_dir in search_dirs:
                    if not agent_dir.is_dir():
                        continue
                    tools_dir = agent_dir / "tools"
                    if not tools_dir.exists():
                        continue
                    for skill_dir in sorted(tools_dir.iterdir()):
                        skill_md = skill_dir / "SKILL.md"
                        if skill_md.exists():
                            found_any = True
                            console.print(
                                f"  [cyan]{agent_dir.name}[/cyan] / [bold]{skill_dir.name}[/bold]"
                            )
                            console.print(f"    [dim]{skill_md}[/dim]")
                if not found_any:
                    console.print("  [yellow]No skills found in .olav/workspace/[/yellow]")
                console.print()

            elif skills_cmd == "create":
                skill_name = args.name
                agent_id = args.agent
                skill_dir = workspace / agent_id / "tools" / skill_name
                skill_dir.mkdir(parents=True, exist_ok=True)
                skill_md = skill_dir / "SKILL.md"
                if skill_md.exists():
                    console.print(
                        f"[yellow]Skill '{skill_name}' already exists at {skill_md}[/yellow]"
                    )
                else:
                    template = f"""---
name: {skill_name}
description: |
  Describe what this skill does in one sentence.
  What domain does it cover? What agent does it enable?
version: "1.0"
---

# {skill_name}

## Instructions

Describe the agent's role, capabilities, and operating constraints here.
What should the agent do? What should it avoid?
What tools are available and when should each be used?

## Examples

- "Show me all interfaces on router-01"
- "Compare running config vs last snapshot"
- "Deploy the lab topology from topology.yaml"
"""
                    skill_md.write_text(template)
                    console.print(
                        f"[bold green]✓[/bold green] Skill '[bold]{skill_name}[/bold]' created at {skill_md}"
                    )
                    console.print(f"  [dim]Edit with: nano {skill_md}[/dim]")

            elif skills_cmd == "info":
                skill_name = args.name
                agent_filter = getattr(args, "agent", None)
                found = False
                search_dirs = (
                    ([workspace / agent_filter] if agent_filter else sorted(workspace.iterdir()))
                    if workspace.exists()
                    else []
                )
                for agent_dir in search_dirs:
                    skill_md = agent_dir / "tools" / skill_name / "SKILL.md"
                    if skill_md.exists():
                        found = True
                        console.print(
                            f"\n[bold]Skill:[/bold] {skill_name}  [dim](agent: {agent_dir.name})[/dim]\n"
                        )
                        console.print(skill_md.read_text())
                        break
                if not found:
                    console.print(f"[red]Skill '{skill_name}' not found.[/red]")
                    console.print("[dim]Use 'olav skills list' to see available skills.[/dim]")
            return

        # Handle kb command group (Unified Knowledge Store)
        if args.command == "kb":
            from olav.cli.commands.kb import handle_kb_command
            sys.exit(handle_kb_command(args))
            return

        # Activate bypass mode before creating session (sets env var for all gates)
        if getattr(args, "dangerously_skip_permissions", False):
            from olav.platform.safety.permissions import set_bypass
            set_bypass(True)
            console.print(
                "  [bold red]⚠ --dangerously-skip-permissions: ON[/bold red] "
                "[dim](all approval gates disabled — for testing only)[/dim]"
            )
            console.print()

        # Activate API write mode (separate from skip-permissions)
        if getattr(args, "enable_api_write", False):
            import os as _os
            _os.environ["OLAV_ENABLE_API_WRITE"] = "1"
            console.print(
                "  [bold yellow]⚠ API WRITE MODE ENABLED[/bold yellow]"
            )
            console.print(
                "  [dim]• Backup your data before proceeding[/dim]\n"
                "  [dim]• All writes require dry-run verification + manual approval[/dim]\n"
                "  [dim]• --dangerously-skip-permissions does NOT bypass write approval[/dim]"
            )
            console.print()

        # Create session state
        try:
            from deepagents_cli.config import SessionState
        except ImportError as _e:
            console.print(
                f"[red]Error:[/red] Interactive mode requires deepagents-cli: {_e}\n"
                "Install with: [cyan]pip install deepagents-cli==0.0.10 --no-deps[/cyan]"
            )
            sys.exit(1)

        session_state = SessionState(
            auto_approve=args.auto_approve,
            no_splash=args.no_splash,
        )

        _workspace = getattr(args, "workspace", None)
        if args.query:
            # Single query mode
            await run_single_query(
                args.query, args.agent, session_id=args.session, workspace=_workspace
            )
        else:
            # Interactive mode
            await run_interactive(
                assistant_id=args.agent,
                session_state=session_state,
                sandbox_type=args.sandbox,
                session_id=args.session,
                workspace=_workspace,
            )

    except KeyboardInterrupt:
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[bold red]Error:[/bold red] {e}")
        import traceback

        # Only print full traceback in debug mode; suppress for known API errors
        # (e.g., 402 Payment Required, 429 Rate Limit) to avoid noisy stderr.
        _is_api_error = any(
            marker in str(type(e).__name__) or marker in str(e)
            for marker in ("APIStatusError", "APIError", "RateLimitError", "AuthenticationError")
        )
        if logging.getLogger().level == logging.DEBUG or not _is_api_error:
            traceback.print_exc()
        if logging.getLogger().level == logging.DEBUG:
            console.print_exception()
        sys.exit(1)


def cli_main() -> None:
    """Main entry point for console script."""
    cli_main_async()


if __name__ == "__main__":
    cli_main()
